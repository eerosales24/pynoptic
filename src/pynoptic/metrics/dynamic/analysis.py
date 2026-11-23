"""The DynaPyt analysis that observes what a submission actually does.

Nine of the seventeen metrics ask a question the tree cannot answer. Whether
a loop turned once or a thousand times, whether the value a name held was
thrown away unread, whether two paths really returned different types — all
of that is a property of a run.

Two decisions shape this module.

**It aggregates in the hook, not afterwards.** A loop can turn a million
times, and emitting one event per turn would cost more than the submission.
Every hook here updates a counter in a dict keyed by instruction id and
returns. Locations are resolved once, at the end, for the handful of ids that
ended up with something to say.

**It writes its summary even when the submission raises.** Student code
raises all the time, and ``run_analysis`` has no ``finally``: an exception on
the way out would take the observations with it. The flush is registered with
``atexit`` as well as exposed as ``end_execution``, and is idempotent.

The budget is the third piece. A loop that never terminates cannot be
reported by a run that never ends, so a loop that passes ``MAX_ITERATIONS``
is recorded as exhausted and the run is stopped from the inside. That is what
turns M11 from a guess into an observation.
"""

from __future__ import annotations

import atexit
import json
import time
from pathlib import Path
from typing import Any

from dynapyt.analyses.BaseAnalysis import BaseAnalysis

__all__ = ["METRIC_RESULTS_FILE", "BudgetExceeded", "MAX_ITERATIONS", "MetricDynamicAnalysis"]

#: Where the summary lands, next to the NCC analysis's own output.
METRIC_RESULTS_FILE = "pynoptic_metrics.json"

#: Turns of a single loop before the run is stopped and the loop recorded as
#: non-terminating. A secondary guard: the real one is the clock below.
MAX_ITERATIONS = 2_000_000

#: Turns across every loop, for the submission that spreads a runaway over
#: several loops rather than one.
MAX_TOTAL_ITERATIONS = 6_000_000

#: Seconds of looping before the run is stopped from the inside, when the
#: caller does not say otherwise.
#:
#: The clock, not the turn count, is what makes M11 answerable. A turn count
#: cannot be chosen correctly, because it has to be below what the timeout
#: allows and above what honest work needs, and those two move
#: independently: instrumented code runs one to two orders of magnitude
#: slower than plain code, and ~15x slower again when both analyses are
#: installed, while an honest O(n^2) over a few hundred elements is already
#: a hundred thousand turns. Any fixed number either falsely accuses real
#: work or never fires.
#:
#: A deadline has neither problem, and it buys something the timeout cannot:
#: when the parent's timeout kills the child, the analysis never writes its
#: summary and the whole run is lost. Stopping from the inside first turns
#: that same situation into a recorded observation naming the loop that was
#: still turning.
DEFAULT_BUDGET_SECONDS = 20.0

#: Turns between clock checks. Reading the clock every turn would itself be
#: a measurable cost in the hot path of every loop in every submission.
CLOCK_EVERY = 2048

#: How many observed iterable lengths to keep per loop. The distribution is
#: what matters, not every sample, and an unbounded list is a leak.
MAX_SAMPLES = 32

#: Events a trace keeps before it stops recording. A trace is for reading,
#: and a loop with a hundred thousand turns produces a file nobody opens.
#: The summary's counters stay exact either way: truncating the trace loses
#: the narrative, never the verdict.
MAX_TRACE = 600

#: How much of a value's repr a trace keeps. Enough to recognise it, not
#: enough to paste a student's whole data structure into a report.
VALUE_WIDTH = 48

#: Calls whose cost is proportional to their argument. They run in C, so
#: nothing else in this analysis would notice the work they do.
LINEAR_CALLS = frozenset(
    {
        "count",
        "index",
        "remove",
        "sort",
        "reverse",
        "sorted",
        "max",
        "min",
        "sum",
        "join",
        "copy",
    }
)


class BudgetExceeded(RuntimeError):
    """Raised inside the submission when a loop passes its iteration budget.

    It inherits from RuntimeError rather than BaseException on purpose: a
    submission with a bare ``except:`` can swallow it, so the flag on the
    analysis is what the parent trusts, not the exception reaching the top.
    """


def _sized(value: Any) -> int | None:
    """Return len(value) when asking is safe and cheap.

    A generator must not be consumed, and ``__len__`` on a student's class
    can raise or take arbitrarily long, so anything that is not a builtin
    container is left alone.

    Parameters:
        - value: The object to measure.

    Returns:
        - The length, or None when it cannot be taken safely.
    """
    if isinstance(value, str | bytes | list | tuple | dict | set | frozenset | range):
        try:
            return len(value)
        except Exception:  # noqa: BLE001 - a length must never break a run
            return None
    return None


def _brief(value: Any) -> str:
    """Return a short, safe repr of a value for a trace line.

    A student's object can have a ``__repr__`` that raises, recurses or
    prints a megabyte. None of that may break the run or the report.

    Parameters:
        - value: The value to describe.

    Returns:
        - The repr, truncated, or a placeholder when it cannot be taken.
    """
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 - a repr must never break a run
        return f"<{type(value).__name__}>"
    text = text.replace("\n", " ")
    if len(text) > VALUE_WIDTH:
        return text[: VALUE_WIDTH - 1] + "…"
    return text


def _same(left: Any, right: Any) -> bool:
    """Return whether two values are equal, without trusting __eq__.

    A submission's ``__eq__`` may raise, recurse or return something that is
    not a bool. Identity is tried first, and anything unusual is reported as
    "not equal", which only ever costs a write being counted as a change.

    Parameters:
        - left: The value before.
        - right: The value after.

    Returns:
        - True when the two are the same value.
    """
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:  # noqa: BLE001 - a comparison must never break a run
        return False


class _Loop:
    """What one loop did, accumulated across every time it was entered."""

    __slots__ = (
        "kind",
        "entries",
        "iterations",
        "longest",
        "current",
        "sizes",
        "containers",
        "exhausted",
        "returned_at",
        "last_change",
        "idle_turns",
    )

    def __init__(self, kind: str) -> None:
        self.kind = kind
        #: How many times the loop was started.
        self.entries = 0
        #: Turns taken across every entry.
        self.iterations = 0
        #: Turns taken in the longest single entry.
        self.longest = 0
        #: Turns taken in the entry currently running.
        self.current = 0
        #: Lengths of the iterables walked, sampled.
        self.sizes: list[int] = []
        #: Distinct container identities walked, mapped to how many entries
        #: walked them. The key to M09: two loops over one list.
        self.containers: dict[int, int] = {}
        #: True when the budget stopped this loop.
        self.exhausted = False
        #: Turn numbers at which a return fired inside this loop.
        self.returned_at: list[int] = []
        #: The last turn on which a write inside the loop changed anything.
        self.last_change = 0
        #: Turns taken after the last change, summed over entries.
        self.idle_turns = 0

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON shape the resolver reads."""
        return {
            "kind": self.kind,
            "entries": self.entries,
            "iterations": self.iterations,
            "longest": self.longest,
            "sizes": self.sizes,
            "distinct_containers": len(self.containers),
            "max_passes_over_one_container": max(self.containers.values(), default=0),
            "exhausted": self.exhausted,
            "returned_at": self.returned_at[:MAX_SAMPLES],
            "idle_turns": self.idle_turns,
        }


class MetricDynamicAnalysis(BaseAnalysis):
    """Observe the run and summarise what the nine dynamic metrics need."""

    def __init__(self, trace: str = "", budget_seconds: str = "", **kwargs: Any) -> None:
        """Set up the counters and arrange for them to be written.

        Parameters:
            - trace: Anything but "", "0" or "false" turns on the ordered
              event log. It arrives as a string because DynaPyt builds the
              analysis from a ``path;key=value`` configuration line.
            - budget_seconds: How long the submission may spend looping
              before it is stopped from the inside. Also a string, for the
              same reason.
            - kwargs: Forwarded to BaseAnalysis; carries output_dir.
        """
        super().__init__(**kwargs)
        try:
            self.budget_seconds = float(budget_seconds) if budget_seconds else (
                DEFAULT_BUDGET_SECONDS
            )
        except ValueError:  # pragma: no cover - a bad config must not kill the run
            self.budget_seconds = DEFAULT_BUDGET_SECONDS
        self._deadline = time.monotonic() + self.budget_seconds
        self.tracing = trace.lower() not in ("", "0", "false", "no")
        #: The ordered log, when tracing. Raw ids; lines are resolved once,
        #: at flush, like every other record here.
        self.trace: list[dict[str, Any]] = []
        self.trace_truncated = False
        self.seq = 0
        self.loops: dict[tuple[str, int], _Loop] = {}
        #: The loops currently running, innermost last. A None marks the
        #: start of a function call: a loop below the marker belongs to the
        #: caller, and a return must not close it.
        self.stack: list[tuple[str, int] | None] = []
        self.returns: dict[tuple[str, int], dict[str, Any]] = {}
        #: Per function, every exit it took and the type it handed back.
        #: Keyed by the function's own instruction id.
        self.exits: dict[tuple[str, int], dict[str, Any]] = {}
        self.writes: dict[tuple[str, int], dict[str, Any]] = {}
        self.subscripts: dict[tuple[str, int], dict[str, Any]] = {}
        self.comparisons: dict[tuple[str, int], dict[str, Any]] = {}
        self.calls: dict[tuple[str, int], dict[str, Any]] = {}
        #: Containers walked, one dict per live call. Scoped to the call
        #: rather than to the run for two reasons: "walks the same container
        #: twice" is a claim about one invocation, and CPython reuses the
        #: address of a freed object, so two short-lived lists in two
        #: separate calls routinely share an id. Keying on the identity
        #: together with the length and type narrows the remaining overlap
        #: to objects that are interchangeable anyway.
        self.frames: list[dict[tuple[int, int, str], dict[str, Any]]] = [{}]
        #: Containers that one call walked more than once.
        self.repeated: list[dict[str, Any]] = []
        self.total_iterations = 0
        self.budget_exceeded = False
        self.budget_detail: dict[str, Any] = {}
        self._flushed = False
        atexit.register(self._flush)

    def _log(self, hook: str, dyn_ast: str, iid: int, detail: str) -> None:
        """Append one line to the ordered trace, if tracing is on.

        The sequence number is kept even past the cap, so a truncated trace
        still says how much happened after it stopped looking.

        Parameters:
            - hook: The hook that fired.
            - dyn_ast: The instrumented file the event came from.
            - iid: The instruction id of the event.
            - detail: What happened, already formatted.
        """
        self.seq += 1
        if len(self.trace) >= MAX_TRACE:
            # Turning tracing off, not just skipping the append. Every call
            # site formats its detail before calling this, so leaving the
            # flag on would keep paying a repr per event for a loop that
            # runs a hundred thousand more times.
            self.trace_truncated = True
            self.tracing = False
            return
        self.trace.append(
            {"seq": self.seq, "hook": hook, "file": dyn_ast, "iid": iid, "detail": detail}
        )

    # -- loops ---------------------------------------------------------

    def _loop(self, dyn_ast: str, iid: int, kind: str) -> _Loop:
        """Return the record for one loop, creating it on first sight.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
            - kind: "for" or "while".

        Returns:
            - The accumulator for that loop.
        """
        key = (dyn_ast, iid)
        loop = self.loops.get(key)
        if loop is None:
            loop = self.loops[key] = _Loop(kind)
        if not self.stack or self.stack[-1] != key:
            self.stack.append(key)
        return loop

    def _current(self) -> _Loop | None:
        """Return the innermost loop currently turning, if any.

        A call frame marker is stepped over rather than stopping the search:
        a write made inside a helper called from a loop body still happened
        during that turn, and attributing it to the caller's loop is what
        makes "this turn changed nothing" mean what it says.

        Returns:
            - The loop, or None when nothing is running.
        """
        for entry in reversed(self.stack):
            if entry is not None:
                return self.loops.get(entry)
        return None

    def _turn(self, loop: _Loop, key: tuple[str, int]) -> None:
        """Count one turn of a loop and enforce the budget.

        Parameters:
            - loop: The loop taking a turn.
            - key: Its (file, iid) identity, for the budget record.

        Raises:
            - BudgetExceeded: When this loop or the run passes its budget.
        """
        loop.iterations += 1
        loop.current += 1
        if loop.current > loop.longest:
            loop.longest = loop.current
        self.total_iterations += 1

        out_of_turns = (
            loop.current > MAX_ITERATIONS or self.total_iterations > MAX_TOTAL_ITERATIONS
        )
        out_of_time = (
            self.total_iterations % CLOCK_EVERY == 0 and time.monotonic() > self._deadline
        )
        if not (out_of_turns or out_of_time):
            return

        # Read before flushing: the flush closes open entries, which resets
        # the very counter the message is about.
        turns = loop.current
        reason = (
            f"{turns} turns" if out_of_turns else f"{self.budget_seconds:g}s of looping"
        )
        loop.exhausted = True
        self.budget_exceeded = True
        self.budget_detail = {
            "file": key[0],
            "iid": key[1],
            "iterations": turns,
            "total": self.total_iterations,
            "reason": "turns" if out_of_turns else "time",
        }
        self._flush()
        raise BudgetExceeded(
            f"loop stopped after {reason}; it does not appear to terminate"
        )

    def enter_for(
        self,
        dyn_ast: str,
        iid: int,
        next_value: Any,
        iterable: Any,
        iterator: Any,
    ) -> None:
        """Count a turn of a for loop and note what it is walking.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
            - next_value: The element this turn received; unused.
            - iterable: What the loop walks, measured but never consumed.
            - iterator: The live iterator; unused.
        """
        # The runtime calls this hook one last time with a StopIteration
        # instance to signal that the iterable is exhausted — it tests for
        # exactly this itself before deciding whether the body runs. Taking
        # it for a turn inflates every exhausted loop's count by one, and
        # with it M10's tally of turns that changed nothing.
        if isinstance(next_value, StopIteration):
            if self.tracing:
                turns = self.loops[(dyn_ast, iid)].current if (dyn_ast, iid) in self.loops else 0
                self._log("for", dyn_ast, iid, f"iterable exhausted after {turns} turns")
            self._close(dyn_ast, iid)
            return

        key = (dyn_ast, iid)
        loop = self._loop(dyn_ast, iid, "for")
        if loop.current == 0:
            loop.entries += 1
            size = _sized(iterable)
            if size is not None and len(loop.sizes) < MAX_SAMPLES:
                loop.sizes.append(size)
            if size is not None:
                identity = (id(iterable), size, type(iterable).__name__)
                loop.containers[identity[0]] = loop.containers.get(identity[0], 0) + 1
                frame = self.frames[-1]
                record = frame.get(identity)
                if record is None:
                    record = frame[identity] = {"passes": 0, "size": size, "loops": []}
                record["passes"] += 1
                if key not in record["loops"]:
                    record["loops"].append(key)
        if self.tracing:
            size = _sized(iterable)
            self._log(
                "for",
                dyn_ast,
                iid,
                f"turn {loop.current + 1}"
                + (f" of {size}" if size is not None else "")
                + f", element = {_brief(next_value)}",
            )
        self._turn(loop, key)

    def enter_while(self, dyn_ast: str, iid: int, cond_value: bool) -> None:
        """Count a turn of a while loop.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
            - cond_value: The condition's value; the loop body only runs when
              it is true, so a false value closes the entry.
        """
        loop = self._loop(dyn_ast, iid, "while")
        if not cond_value:
            if self.tracing:
                self._log(
                    "while", dyn_ast, iid, f"condition false after {loop.current} turns"
                )
            self._close(dyn_ast, iid)
            return
        if loop.current == 0:
            loop.entries += 1
        if self.tracing:
            self._log("while", dyn_ast, iid, f"turn {loop.current + 1}, condition true")
        self._turn(loop, (dyn_ast, iid))

    def _close(self, dyn_ast: str, iid: int) -> None:
        """Finish an entry of a loop, banking its idle turns.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
        """
        key = (dyn_ast, iid)
        loop = self.loops.get(key)
        if loop is None:
            return
        if loop.current:
            loop.idle_turns += max(0, loop.current - loop.last_change)
        loop.current = 0
        loop.last_change = 0
        if key in self.stack:
            # Everything above it closed too: a break out of nested loops
            # leaves the inner frames without an exit hook of their own.
            index = len(self.stack) - 1 - self.stack[::-1].index(key)
            for entry in self.stack[index + 1 :]:
                if entry is not None and entry != key:
                    self._bank(entry)
            del self.stack[index:]

    def _bank(self, key: tuple[str, int]) -> None:
        """Close one loop's entry without touching the stack.

        Parameters:
            - key: The loop's (file, iid) identity.
        """
        loop = self.loops.get(key)
        if loop is None:
            return
        if loop.current:
            loop.idle_turns += max(0, loop.current - loop.last_change)
        loop.current = 0
        loop.last_change = 0

    def _bank_frame(self) -> None:
        """Close the current call's container tally, keeping the repeats.

        Only containers a single call walked more than once survive, which
        is the claim M09 makes. Everything else is dropped with the frame.
        """
        if len(self.frames) <= 1:
            frame = self.frames[0]
            self.frames[0] = {}
        else:
            frame = self.frames.pop()
        for (_identity, size, kind), record in frame.items():
            if record["passes"] > 1 and len(self.repeated) < MAX_SAMPLES:
                self.repeated.append(
                    {
                        "passes": record["passes"],
                        "size": size,
                        "kind": kind,
                        "loops": record["loops"],
                    }
                )

    # -- call frames ---------------------------------------------------

    def function_enter(
        self, dyn_ast: str, iid: int, args: list[Any], name: str, is_lambda: bool
    ) -> None:
        """Mark the start of a call, so a return cannot close the caller's loop.

        Parameters:
            - dyn_ast: The instrumented file the function is in.
            - iid: The instruction id of the function.
            - args: The arguments, as thunks; unused.
            - name: The function's name; unused.
            - is_lambda: Whether this is a lambda; unused.
        """
        self.stack.append(None)
        self.frames.append({})

    def function_exit(self, dyn_ast: str, function_iid: int, name: str, result: Any) -> None:
        """Record every exit a function takes, and close the loops it left.

        This hook is what sees a function falling off its end. DynaPyt's
        ``implicit_return`` is declared by the instrumenter but never
        dispatched by the runtime: ``_func_exit_`` calls ``function_exit``
        with None, and ``_return_`` calls it with the value. So this is the
        one place that sees *every* type a function hands back, which is
        exactly what M07 asks for.

        Parameters:
            - dyn_ast: The instrumented file the function is in.
            - function_iid: The instruction id of the function.
            - name: The function's name.
            - result: What this exit handed back.
        """
        self._bank_frame()
        key = (dyn_ast, function_iid)
        record = self.exits.get(key)
        if record is None:
            record = self.exits[key] = {"n": 0, "types": {}, "name": name, "explicit": 0}
        record["n"] += 1
        type_name = type(result).__name__
        record["types"][type_name] = record["types"].get(type_name, 0) + 1

        # Unwind to this call's marker, banking any loop it was still
        # inside. A loop still turning when its function exits is a loop the
        # function returned out of, and the turn it was on is what tells M06
        # whether one element decided the answer. This has to happen here
        # rather than in `_return`, because the runtime calls `function_exit`
        # first and the stack is already unwound by the time `_return` runs.
        while self.stack:
            entry = self.stack.pop()
            if entry is None:
                break
            loop = self.loops.get(entry)
            if loop is not None and loop.current:
                if len(loop.returned_at) < MAX_SAMPLES:
                    loop.returned_at.append(loop.current)
                if self.tracing:
                    self._log(
                        "exit",
                        dyn_ast,
                        function_iid,
                        f"left {name} from inside a loop on turn {loop.current}",
                    )
            self._bank(entry)
        if self.tracing:
            self._log(
                "exit",
                dyn_ast,
                function_iid,
                f"{name} returned {type(result).__name__} {_brief(result)}",
            )

    def exit_for(self, dyn_ast: str, iid: int) -> None:
        """Close a for loop's entry.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
        """
        self._close(dyn_ast, iid)

    def exit_while(self, dyn_ast: str, iid: int) -> None:
        """Close a while loop's entry.

        Parameters:
            - dyn_ast: The instrumented file the loop is in.
            - iid: The instruction id of the loop.
        """
        self._close(dyn_ast, iid)

    # -- returns -------------------------------------------------------

    def _return(
        self, dyn_ast: str, iid: int, function_iid: int, function_name: str, value: Any
    ) -> None:
        """Record what one return statement handed back, line by line.

        The per-function tally lives in `function_exit`, which sees the
        implicit exits too. This hook exists for the evidence: it is what
        lets a report point at the line that returned a str next to the line
        that returned an int.

        Parameters:
            - dyn_ast: The instrumented file the return is in.
            - iid: The instruction id of the return.
            - function_iid: The instruction id of the enclosing function.
            - function_name: The function's name; unused.
            - value: What was returned.
        """
        key = (dyn_ast, iid)
        record = self.returns.get(key)
        if record is None:
            record = self.returns[key] = {"types": {}, "n": 0, "implicit": False}
        name = type(value).__name__
        record["types"][name] = record["types"].get(name, 0) + 1
        record["n"] += 1
        exit_record = self.exits.get((dyn_ast, function_iid))
        if exit_record is not None:
            exit_record["explicit"] += 1
        if self.tracing:
            self._log("return", dyn_ast, iid, f"{name} = {_brief(value)}")

    # -- writes --------------------------------------------------------

    def write(self, dyn_ast: str, iid: int, old_vals: list[Any], new_val: Any) -> None:
        """Record a write, and whether it discarded a value that was there.

        The old values arrive as thunks so an analysis can decide not to pay
        for them. They are paid for here, because "the value it held was
        thrown away" is exactly the question M15 asks, and because the answer
        decides whether a loop turn counted as doing something.

        Parameters:
            - dyn_ast: The instrumented file the write is in.
            - iid: The instruction id of the write.
            - old_vals: Thunks returning the values before the write.
            - new_val: The value after.
        """
        key = (dyn_ast, iid)
        record = self.writes.get(key)
        if record is None:
            record = self.writes[key] = {
                "n": 0,
                "rebound": 0,
                "discarded": 0,
                "changed": 0,
                "old_types": {},
            }
        record["n"] += 1

        changed = False
        bound = False
        previous = ""
        for thunk in old_vals or ():
            try:
                old = thunk() if callable(thunk) else thunk
            except Exception:  # noqa: BLE001 - an unbound name is the normal case
                continue
            if self.tracing and not bound:
                previous = _brief(old)
            bound = True
            # The name held something. That is what M15 asks about: a value
            # the function computed and replaced without reading. Whether
            # the replacement happens to be equal is beside the point —
            # `a = x * y` then `a = round(x * y, 2)` can write back the
            # same number and still have thrown the first computation away.
            record["rebound"] += 1
            name = type(old).__name__
            record["old_types"][name] = record["old_types"].get(name, 0) + 1
            if not _same(old, new_val):
                changed = True
                record["discarded"] += 1
        # Whether the turn did anything is a different question, and that
        # one does turn on equality: a write of the value already there
        # left the state alone, which is what M10 counts as an idle turn.
        if changed:
            record["changed"] += 1
            loop = self._current()
            if loop is not None:
                loop.last_change = loop.current
        if self.tracing:
            self._log(
                "write",
                dyn_ast,
                iid,
                (f"{previous} -> {_brief(new_val)}" if bound else f"= {_brief(new_val)}")
                + ("" if changed or not bound else "  (same value)"),
            )

    # -- calls ---------------------------------------------------------

    def pre_call(
        self,
        dyn_ast: str,
        iid: int,
        function: Any,
        pos_args: tuple[Any, ...],
        kw_args: dict[str, Any],
    ) -> None:
        """Charge a call that walks its argument its real cost.

        ``sorted``, ``in``, ``.count`` and friends do their work in C, so a
        bytecode or iteration count sees them as free. M13 asks about growth,
        and a quadratic built out of ``lista.count(x)`` inside a loop is
        invisible without this. Only the linear ones are tallied, and only
        the size of the argument is kept.

        Parameters:
            - dyn_ast: The instrumented file the call is in.
            - iid: The instruction id of the call.
            - function: The callable being invoked.
            - pos_args: The positional arguments.
            - kw_args: The keyword arguments; unused.
        """
        name = getattr(function, "__name__", "")
        if name not in LINEAR_CALLS:
            return
        receiver = getattr(function, "__self__", None)
        size = _sized(receiver)
        if size is None:
            for argument in pos_args or ():
                size = _sized(argument)
                if size is not None:
                    break
        key = (dyn_ast, iid)
        record = self.calls.get(key)
        if record is None:
            record = self.calls[key] = {"n": 0, "name": name, "work": 0}
        record["n"] += 1
        record["work"] += size or 1

    # -- comparisons ---------------------------------------------------

    def comparison(
        self,
        dyn_ast: str,
        iid: int,
        left: Any,
        operator: str,
        right: Any,
        result: Any,
    ) -> None:
        """Tally how a comparison came out, to spot the ones that never vary.

        The static detector for M02 can only see a bare literal among the
        operands. A test that is invariant without containing a literal —
        ``if edad > edad`` — is visible only here, as a comparison evaluated
        many times that never once came out the other way.

        The runtime calls this hook as (left, operator, right, result);
        DynaPyt's own TraceAll docstring lists the operator first and is out
        of date. The order below is the one the runtime actually passes.

        Parameters:
            - dyn_ast: The instrumented file the comparison is in.
            - iid: The instruction id of the comparison.
            - left: The left operand; unused.
            - operator: The DynaPyt operator name; unused.
            - right: The right operand; unused.
            - result: What the comparison came out as.
        """
        key = (dyn_ast, iid)
        record = self.comparisons.get(key)
        if record is None:
            record = self.comparisons[key] = {"n": 0, "true": 0, "false": 0}
        record["n"] += 1
        if result:
            record["true"] += 1
        else:
            record["false"] += 1
        if self.tracing:
            self._log(
                "compare",
                dyn_ast,
                iid,
                f"{_brief(left)} {operator} {_brief(right)} -> {bool(result)}",
            )

    # -- subscripts ----------------------------------------------------

    def read_subscript(
        self, dyn_ast: str, iid: int, base: Any, sl: Any, val: Any
    ) -> None:
        """Record a subscript read, noting mappings and their sizes.

        A read that raised KeyError never reaches this hook — the exception
        is the observation, and the runner reports it. What is recorded here
        is the read that worked, which is what refutes the candidate.

        Parameters:
            - dyn_ast: The instrumented file the subscript is in.
            - iid: The instruction id of the subscript.
            - base: The object being indexed.
            - sl: The subscript.
            - val: The value read; unused.
        """
        key = (dyn_ast, iid)
        record = self.subscripts.get(key)
        if record is None:
            record = self.subscripts[key] = {"n": 0, "mapping": False, "sizes": []}
        record["n"] += 1
        if isinstance(base, dict):
            record["mapping"] = True
            if len(record["sizes"]) < MAX_SAMPLES:
                try:
                    record["sizes"].append(len(base))
                except Exception:  # noqa: BLE001 - a length must never break a run
                    pass
        if self.tracing:
            self._log(
                "subscript",
                dyn_ast,
                iid,
                f"{type(base).__name__}[{_brief(sl)}] -> {_brief(val)}",
            )

    # -- output --------------------------------------------------------

    def _locate(self, dyn_ast: str, iid: int) -> int:
        """Return the source line of an instruction id, or 0.

        Parameters:
            - dyn_ast: The instrumented file.
            - iid: The instruction id to resolve.

        Returns:
            - The one-indexed line, or 0 when it cannot be resolved.
        """
        try:
            return int(self.iid_to_location(dyn_ast, iid).start_line)
        except Exception:  # noqa: BLE001 - a missing map must not lose the run
            return 0

    def _by_line(self, records: dict[tuple[str, int], Any]) -> dict[str, Any]:
        """Re-key a per-instruction dict by source line.

        Two instructions can share a line; their records are merged by taking
        the one with more observations, which keeps the summary flat without
        inventing a total that mixes two constructs.

        Parameters:
            - records: The per-instruction accumulators.

        Returns:
            - The same data keyed by line number as a string.
        """
        out: dict[str, Any] = {}
        for (dyn_ast, iid), value in records.items():
            line = str(self._locate(dyn_ast, iid))
            payload = value.to_dict() if isinstance(value, _Loop) else value
            current = out.get(line)
            if current is None or payload.get("n", 0) > current.get("n", 0):
                out[line] = payload
        return out

    def _flush(self) -> None:
        """Write the summary, once, wherever the run ended up.

        Registered with atexit as well as called by end_execution, because a
        submission that raises never reaches DynaPyt's own shutdown and its
        observations would otherwise be lost.
        """
        if self._flushed or not self.output_dir:
            return
        self._flushed = True
        for entry in list(self.stack):
            if entry is not None:
                self._bank(entry)
        self.stack.clear()
        while len(self.frames) > 1 or self.frames[0]:
            self._bank_frame()
        passes = [
            {
                "passes": r["passes"],
                "size": r["size"],
                "lines": sorted({self._locate(f, i) for f, i in r["loops"]}),
            }
            for r in self.repeated
        ]
        payload = {
            "loops": self._by_line(self.loops),
            "returns": self._by_line(self.returns),
            "exits": self._by_line(self.exits),
            "writes": self._by_line(self.writes),
            "subscripts": self._by_line(self.subscripts),
            "comparisons": self._by_line(self.comparisons),
            "calls": self._by_line(self.calls),
            "linear_work": sum(int(r["work"]) for r in self.calls.values()),
            "containers_walked_more_than_once": passes,
            "total_iterations": self.total_iterations,
            "budget_exceeded": self.budget_exceeded,
            "budget": self.budget_detail,
            "trace": [
                {
                    "seq": event["seq"],
                    "hook": event["hook"],
                    "line": self._locate(event["file"], event["iid"]),
                    "detail": event["detail"],
                }
                for event in self.trace
            ],
            "trace_truncated": self.trace_truncated,
            "events_total": self.seq,
        }
        try:
            path = Path(self.output_dir) / METRIC_RESULTS_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:  # pragma: no cover - the parent reports an empty run
            pass

    def end_execution(self, *args: Any) -> None:
        """Write the summary at DynaPyt's shutdown.

        Parameters:
            - args: Ignored; accepted because DynaPyt calls this on shutdown.
        """
        self._flush()
