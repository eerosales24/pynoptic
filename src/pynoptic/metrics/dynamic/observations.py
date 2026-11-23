"""What one run saw, in the shape the resolver asks questions of.

The analysis writes a flat JSON summary keyed by source line. This module is
the typed reading of it, and the one place that knows the summary's layout.
Keeping the parsing here means the resolver reads like the rules it encodes
rather than like dictionary access.

Everything is tolerant of a missing key. A run that was refused, timed out or
crashed before it reached a construct produces a partial summary, and a
partial summary must answer "I did not see that" rather than raise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CallRun",
    "ComparisonRun",
    "ContainerPasses",
    "ExitRun",
    "LoopRun",
    "ReturnRun",
    "RunObservations",
    "SubscriptRun",
    "TraceEvent",
    "WriteRun",
]

#: "KeyError: 'nombre'" out of the runner's error strings. The exception type
#: is the observation M12 needs, and it only ever arrives as text because it
#: happened in another process.
_EXCEPTION = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception))\b")


@dataclass(frozen=True)
class LoopRun:
    """What one loop did, as the analysis recorded it."""

    line: int
    kind: str = "for"
    entries: int = 0
    iterations: int = 0
    longest: int = 0
    sizes: tuple[int, ...] = ()
    distinct_containers: int = 0
    max_passes_over_one_container: int = 0
    exhausted: bool = False
    returned_at: tuple[int, ...] = ()
    idle_turns: int = 0

    @property
    def ran(self) -> bool:
        """Return whether the loop was entered at all."""
        return self.entries > 0

    @property
    def largest_input(self) -> int:
        """Return the biggest iterable the loop walked, or 0."""
        return max(self.sizes, default=0)

    @property
    def returned_on_first_turn(self) -> bool:
        """Return whether a return fired on turn one of some entry."""
        return 1 in self.returned_at


@dataclass(frozen=True)
class ReturnRun:
    """What one return statement handed back, across the whole run."""

    line: int
    types: dict[str, int] = field(default_factory=dict)
    n: int = 0
    implicit: bool = False


@dataclass(frozen=True)
class ExitRun:
    """Every exit one function took, and the type each handed back.

    This is the complete picture, unlike the per-return tally: a function
    that falls off its end exits without any return statement, and only this
    record sees it.
    """

    line: int
    n: int = 0
    types: dict[str, int] = field(default_factory=dict)
    #: Exits that went through a return statement.
    explicit: int = 0
    name: str = ""

    @property
    def implicit(self) -> int:
        """Return how many exits fell off the end of the body."""
        return max(0, self.n - self.explicit)


@dataclass(frozen=True)
class WriteRun:
    """What one write did, across the whole run."""

    line: int
    n: int = 0
    #: Writes that replaced a value the name already held, equal or not.
    #: This is M15's criterion: the first computation was thrown away.
    rebound: int = 0
    #: Writes that replaced a value with a *different* one. This is M10's
    #: criterion: the turn actually changed the state.
    discarded: int = 0
    changed: int = 0
    old_types: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SubscriptRun:
    """What one subscript read saw, across the whole run."""

    line: int
    n: int = 0
    mapping: bool = False
    sizes: tuple[int, ...] = ()


@dataclass(frozen=True)
class CallRun:
    """One call site that walks its argument, and the work it did."""

    line: int
    n: int = 0
    name: str = ""
    #: Elements walked in total: the sum of the argument sizes over every
    #: call, which is the cost a bytecode count never sees.
    work: int = 0


@dataclass(frozen=True)
class ComparisonRun:
    """How one comparison came out, across the whole run."""

    line: int
    n: int = 0
    true: int = 0
    false: int = 0

    @property
    def invariant(self) -> bool:
        """Return whether it was evaluated more than once and never varied."""
        return self.n > 1 and (self.true == 0 or self.false == 0)


@dataclass(frozen=True)
class TraceEvent:
    """One thing that happened, in the order it happened.

    The summary says a loop turned six times and a write discarded a float.
    The trace says which turn, with which element, and what the value was
    before. It is how a disputed verdict gets checked against the run
    instead of against the rule that produced it.
    """

    seq: int
    hook: str
    line: int
    detail: str


@dataclass(frozen=True)
class ContainerPasses:
    """One container and how many loop entries walked it."""

    passes: int
    size: int
    lines: tuple[int, ...]


@dataclass
class RunObservations:
    """Everything one run of one submission reported."""

    loops: dict[int, LoopRun] = field(default_factory=dict)
    returns: dict[int, ReturnRun] = field(default_factory=dict)
    exits: dict[int, ExitRun] = field(default_factory=dict)
    writes: dict[int, WriteRun] = field(default_factory=dict)
    subscripts: dict[int, SubscriptRun] = field(default_factory=dict)
    comparisons: dict[int, ComparisonRun] = field(default_factory=dict)
    calls: dict[int, CallRun] = field(default_factory=dict)
    repeated_containers: tuple[ContainerPasses, ...] = ()
    total_iterations: int = 0
    #: Elements walked inside C-level calls, which iteration counts miss.
    linear_work: int = 0
    #: The ordered log, when the run was asked for one.
    trace: tuple[TraceEvent, ...] = ()
    #: True when the trace stopped recording before the run ended.
    trace_truncated: bool = False
    #: Hook calls the run made in total, traced or not.
    events_total: int = 0
    budget_exceeded: bool = False
    #: True when a run actually happened and produced a summary.
    executed: bool = False
    #: Error text from the child, if the submission raised.
    errors: tuple[str, ...] = ()
    #: True when a layer refused to run the submission at all.
    refused: bool = False

    @property
    def exception(self) -> str:
        """Return the name of the exception the submission raised, or "".

        Returns:
            - Something like "KeyError", or an empty string when the run
              finished or failed for a reason that was not an exception.
        """
        for error in self.errors:
            match = _EXCEPTION.search(error)
            if match:
                return match.group(1)
        return ""

    @property
    def returned_types(self) -> dict[str, int]:
        """Return every type the function handed back, with its tally.

        Taken from the exits rather than the returns: a path that falls off
        the end of the body hands back None without passing a return
        statement, and leaving it out is what made the static detector miss
        this metric's most common shape in the first place.
        """
        tally: dict[str, int] = {}
        source = self.exits.values() if self.exits else self.returns.values()
        for record in source:
            for name, count in record.types.items():
                tally[name] = tally.get(name, 0) + count
        return tally

    def loop_at(self, line: int) -> LoopRun | None:
        """Return the loop recorded at a line, when there is one.

        Parameters:
            - line: The source line of the loop.

        Returns:
            - The record, or None.
        """
        return self.loops.get(line)

    def enclosing_loop(self, line: int) -> LoopRun | None:
        """Return the innermost loop that plausibly contains a line.

        The analysis keys loops by their own line, while a static finding
        points at a statement inside the body. The nearest loop at or above
        the finding is the one that contains it, which holds for every shape
        a CS1 submission takes and is stated here rather than assumed.

        Parameters:
            - line: The line of the construct inside the loop.

        Returns:
            - The closest loop at or above that line, or None.
        """
        candidates = [loop for at, loop in self.loops.items() if at <= line]
        if not candidates:
            return None
        return max(candidates, key=lambda loop: loop.line)

    @classmethod
    def from_summary(
        cls,
        payload: dict[str, Any] | None,
        *,
        errors: tuple[str, ...] = (),
        refused: bool = False,
    ) -> RunObservations:
        """Build the observations from the analysis's JSON summary.

        Parameters:
            - payload: The parsed summary, or None when none was written.
            - errors: What the runner reported about the run.
            - refused: Whether a sandbox layer stopped the submission.

        Returns:
            - The observations; executed is False when there is no summary.
        """
        if not payload:
            return cls(executed=False, errors=errors, refused=refused)

        loops: dict[int, LoopRun] = {}
        for key, value in (payload.get("loops") or {}).items():
            line = int(key)
            loops[line] = LoopRun(
                line=line,
                kind=str(value.get("kind", "for")),
                entries=int(value.get("entries", 0)),
                iterations=int(value.get("iterations", 0)),
                longest=int(value.get("longest", 0)),
                sizes=tuple(int(s) for s in value.get("sizes") or ()),
                distinct_containers=int(value.get("distinct_containers", 0)),
                max_passes_over_one_container=int(
                    value.get("max_passes_over_one_container", 0)
                ),
                exhausted=bool(value.get("exhausted", False)),
                returned_at=tuple(int(t) for t in value.get("returned_at") or ()),
                idle_turns=int(value.get("idle_turns", 0)),
            )

        returns: dict[int, ReturnRun] = {}
        for key, value in (payload.get("returns") or {}).items():
            line = int(key)
            returns[line] = ReturnRun(
                line=line,
                types={str(k): int(v) for k, v in (value.get("types") or {}).items()},
                n=int(value.get("n", 0)),
                implicit=bool(value.get("implicit", False)),
            )

        exits: dict[int, ExitRun] = {}
        for key, value in (payload.get("exits") or {}).items():
            line = int(key)
            exits[line] = ExitRun(
                line=line,
                n=int(value.get("n", 0)),
                types={str(k): int(v) for k, v in (value.get("types") or {}).items()},
                explicit=int(value.get("explicit", 0)),
                name=str(value.get("name", "")),
            )

        writes: dict[int, WriteRun] = {}
        for key, value in (payload.get("writes") or {}).items():
            line = int(key)
            writes[line] = WriteRun(
                line=line,
                n=int(value.get("n", 0)),
                rebound=int(value.get("rebound", 0)),
                discarded=int(value.get("discarded", 0)),
                changed=int(value.get("changed", 0)),
                old_types={str(k): int(v) for k, v in (value.get("old_types") or {}).items()},
            )

        subscripts: dict[int, SubscriptRun] = {}
        for key, value in (payload.get("subscripts") or {}).items():
            line = int(key)
            subscripts[line] = SubscriptRun(
                line=line,
                n=int(value.get("n", 0)),
                mapping=bool(value.get("mapping", False)),
                sizes=tuple(int(s) for s in value.get("sizes") or ()),
            )

        comparisons: dict[int, ComparisonRun] = {}
        for key, value in (payload.get("comparisons") or {}).items():
            line = int(key)
            comparisons[line] = ComparisonRun(
                line=line,
                n=int(value.get("n", 0)),
                true=int(value.get("true", 0)),
                false=int(value.get("false", 0)),
            )

        calls: dict[int, CallRun] = {}
        for key, value in (payload.get("calls") or {}).items():
            line = int(key)
            calls[line] = CallRun(
                line=line,
                n=int(value.get("n", 0)),
                name=str(value.get("name", "")),
                work=int(value.get("work", 0)),
            )

        repeated = tuple(
            ContainerPasses(
                passes=int(entry.get("passes", 0)),
                size=int(entry.get("size", 0)),
                lines=tuple(int(line) for line in entry.get("lines") or ()),
            )
            for entry in payload.get("containers_walked_more_than_once") or ()
        )

        return cls(
            loops=loops,
            returns=returns,
            exits=exits,
            writes=writes,
            subscripts=subscripts,
            comparisons=comparisons,
            calls=calls,
            repeated_containers=repeated,
            total_iterations=int(payload.get("total_iterations", 0)),
            linear_work=int(payload.get("linear_work", 0)),
            trace=tuple(
                TraceEvent(
                    seq=int(event.get("seq", 0)),
                    hook=str(event.get("hook", "")),
                    line=int(event.get("line", 0)),
                    detail=str(event.get("detail", "")),
                )
                for event in payload.get("trace") or ()
            ),
            trace_truncated=bool(payload.get("trace_truncated", False)),
            events_total=int(payload.get("events_total", 0)),
            budget_exceeded=bool(payload.get("budget_exceeded", False)),
            executed=True,
            errors=errors,
            refused=refused,
        )
