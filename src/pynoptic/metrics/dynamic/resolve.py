"""Turn static candidates into verdicts using what the run observed.

Eight metrics ship a candidate the tree cannot settle, and one — M07 — ships
an ABSENT the tree had no way to question. This module is the rulebook that
decides each of them against a run, and it is deliberately written as one
small function per metric: these are the claims the project makes about what
a run proves, and they should be readable as claims.

Three outcomes, and the third is as important as the others:

- **confirmed** — the run saw the phenomenon. The verdict becomes PRESENT
  and resolved, and the evidence carries what was measured.
- **refuted** — the run exercised the construct and it behaved. ABSENT and
  resolved, with the inputs' reach noted, because a refutation is only ever
  as good as the driver.
- **left open** — the construct never executed. The finding keeps
  ``resolved=False``. A metric that never ran must not be reported as clean;
  that is the difference between "we checked" and "nothing reached it".

A refutation is always relative to the inputs the driver supplied. Where
that matters most — M08's unreachable branch, M12's missing key — the note
says so rather than letting a single happy path read as proof.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..models import Evidence, Judgement, MetricFinding, MetricReport
from .observations import RunObservations

__all__ = ["RESOLVERS", "resolve_report"]

Resolver = Callable[[MetricFinding, RunObservations], MetricFinding]

RESOLVERS: dict[str, Resolver] = {}

#: Types that are interchangeable as a return: a function answering 1 or 1.0
#: has not changed what the caller can do with the result, while one
#: answering 1 or "uno" has. Counting bool as int would hide the common
#: `return True` / `return 0` slip, so it is kept separate.
_COMPATIBLE: tuple[frozenset[str], ...] = (frozenset({"int", "float"}),)


def _resolver(metric_id: str) -> Callable[[Resolver], Resolver]:
    """Register a resolver for one metric.

    Parameters:
        - metric_id: The catalog id the resolver settles.

    Returns:
        - A decorator that records the function and returns it unchanged.
    """

    def register(function: Resolver) -> Resolver:
        RESOLVERS[metric_id] = function
        return function

    return register


def _confirm(
    finding: MetricFinding,
    detail: str,
    *,
    evidence: tuple[Evidence, ...] | None = None,
    **data: int | float | str,
) -> MetricFinding:
    """Return the finding as a confirmed runtime verdict.

    Parameters:
        - finding: The static candidate.
        - detail: What the run saw, in one phrase.
        - evidence: Replacement evidence, when the run anchors it better.
        - data: Measurements to merge into the finding's data.

    Returns:
        - A PRESENT, resolved finding.
    """
    return replace(
        finding,
        verdict=Judgement.PRESENT,
        resolved=True,
        detector="dynapyt",
        evidence=evidence if evidence is not None else finding.evidence,
        data={**dict(finding.data), "runtime": detail, **data},
    )


def _refute(
    finding: MetricFinding, detail: str, **data: int | float | str
) -> MetricFinding:
    """Return the finding as refuted by the run.

    Parameters:
        - finding: The static candidate.
        - detail: Why the run disagrees, in one phrase.
        - data: Measurements to merge into the finding's data.

    Returns:
        - An ABSENT, resolved finding.
    """
    return replace(
        finding,
        verdict=Judgement.ABSENT,
        resolved=True,
        detector="dynapyt",
        data={**dict(finding.data), "runtime": detail, **data},
    )


def _unreached(finding: MetricFinding, detail: str) -> MetricFinding:
    """Return the finding untouched, recording why the run settled nothing.

    Parameters:
        - finding: The static candidate.
        - detail: What the run failed to reach.

    Returns:
        - The finding, still unresolved.
    """
    return replace(finding, data={**dict(finding.data), "runtime": detail})


# -- the rules ---------------------------------------------------------


@_resolver("M02")
def _constant_condition(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Widen M02 to conditions that never varied, literal or not.

    The static verdict is final when it fired: a bare literal among the
    operands settles the question without a run. What the run adds is the
    other half — a comparison evaluated many times that never once came out
    differently.
    """
    if finding.verdict is Judgement.PRESENT:
        return replace(finding, resolved=True)
    invariant = [c for c in obs.comparisons.values() if c.invariant]
    if not invariant:
        return finding
    return _confirm(
        finding,
        "evaluated repeatedly and never varied",
        evidence=tuple(
            Evidence(
                line=c.line,
                element="",
                detail=f"always {'true' if c.true else 'false'} over {c.n} evaluations",
            )
            for c in sorted(invariant, key=lambda c: c.line)
        ),
        n=len(invariant),
    )


@_resolver("M06")
def _premature_decision(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M06 on whether a loop really answered from one element.

    The confirmation is precise: a return fired on turn one of a loop whose
    iterable held more than one element. A legitimate search returns on the
    turn it finds the answer, which is rarely the first and never when the
    container has one element to begin with.
    """
    loops = [obs.enclosing_loop(e.line) for e in finding.evidence]
    seen = [loop for loop in loops if loop is not None and loop.ran]
    if not seen:
        return _unreached(finding, "the loop never ran")

    for loop in seen:
        if loop.returned_on_first_turn and loop.largest_input > 1:
            return _confirm(
                finding,
                f"returned on turn 1 of {loop.largest_input} elements",
                elementos=loop.largest_input,
                vueltas=loop.longest,
            )
    deepest = max(seen, key=lambda loop: loop.longest)
    if deepest.largest_input <= 1:
        return _unreached(
            finding, "every input had at most one element, so turn one proves nothing"
        )
    return _refute(
        finding,
        f"the loop ran {deepest.longest} turns before answering",
        vueltas=deepest.longest,
        elementos=deepest.largest_input,
    )


@_resolver("M07")
def _unstable_return_type(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M07 on the types the function actually handed back.

    This is the metric the run widens most. The tree sees the type only when
    the returned expression is a literal or a constructor; the run sees it
    whatever it is, including the None of a path that just ends.
    """
    if finding.verdict is Judgement.NOT_APPLICABLE:
        return finding
    tally = obs.returned_types
    if not tally:
        return _unreached(finding, "no return was reached")
    kinds = set(tally)
    for group in _COMPATIBLE:
        if kinds <= group:
            kinds = {"/".join(sorted(group))}
    if len(kinds) > 1:
        evidence = [
            Evidence(
                line=record.line,
                element=", ".join(sorted(record.types)),
                detail="returned " + ", ".join(sorted(record.types)),
            )
            for record in sorted(obs.returns.values(), key=lambda r: r.line)
        ]
        evidence += [
            Evidence(
                line=record.line,
                element="NoneType",
                detail=f"fell off the end of the body {record.implicit} time(s), returning None",
            )
            for record in sorted(obs.exits.values(), key=lambda r: r.line)
            if record.implicit
        ]
        return _confirm(
            finding,
            "returned " + ", ".join(sorted(tally)),
            evidence=tuple(sorted(evidence, key=lambda e: e.line)),
            tipos=", ".join(sorted(tally)),
            n=len(tally),
        )
    return _refute(finding, f"every return was {next(iter(tally))}", tipos=next(iter(tally)))


@_resolver("M08")
def _impossible_branch(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Leave M08 where the static verdict put it, noting what ran.

    The run can refute but not confirm, and it cannot really refute either:
    a branch no input reached may still be reachable by an input nobody
    tried. Saying so is the honest answer, so the static verdict stands and
    the run only annotates it.
    """
    if finding.verdict is not Judgement.PRESENT:
        return finding
    taken = [obs.comparisons.get(e.line) for e in finding.evidence]
    reached = [c for c in taken if c is not None and c.true]
    if reached:
        return _refute(
            finding,
            "the branch was reached at run time, so it is not unreachable",
            n=len(reached),
        )
    return replace(
        finding,
        resolved=True,
        data={
            **dict(finding.data),
            "runtime": "no input reached the branch, which is consistent but not proof",
        },
    )


@_resolver("M09")
def _repeated_work(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M09 on how many times one container was really walked.

    The count is the verdict for this metric, and the run's count is the one
    that counts: two loops in the text may walk different objects, and one
    loop in the text may walk the same object twice.
    """
    if not obs.executed:
        return _unreached(finding, "the function never ran")
    repeated = [c for c in obs.repeated_containers if c.passes > 1]
    if not repeated:
        if not obs.loops:
            return _unreached(finding, "no loop ran")
        return _refute(finding, "no container was walked more than once", n=0)
    worst = max(repeated, key=lambda c: c.passes)
    return _confirm(
        finding,
        f"one container of {worst.size} elements was walked {worst.passes} times",
        evidence=tuple(
            Evidence(
                line=line,
                element="",
                detail=f"one of {worst.passes} passes over the same {worst.size} elements",
            )
            for line in worst.lines
        )
        or finding.evidence,
        n=worst.passes,
        elementos=worst.size,
    )


@_resolver("M10")
def _idle_iterations(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M10 on turns taken after the last one that changed anything.

    The analysis records, per loop, the turn on which a write last changed a
    value. Everything after it is a turn that cost time and altered nothing,
    which is the metric stated exactly.
    """
    loops = [obs.enclosing_loop(e.line) for e in finding.evidence]
    seen = [loop for loop in loops if loop is not None and loop.ran]
    if not seen:
        return _unreached(finding, "the loop never ran")
    worst = max(seen, key=lambda loop: loop.idle_turns)
    if worst.idle_turns > 0:
        return _confirm(
            finding,
            f"{worst.idle_turns} turns after the last one that changed anything",
            vueltas_inutiles=worst.idle_turns,
            vueltas=worst.longest,
        )
    return _refute(finding, "every turn changed something", vueltas=worst.longest)


@_resolver("M11")
def _nonterminating_loop(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M11 on whether the loop ever stopped.

    The execution budget is the detector: a loop that passes it is stopped
    from the inside and recorded as exhausted, which is the only way this
    question gets an answer at all.
    """
    loops = [obs.enclosing_loop(e.line) for e in finding.evidence]
    seen = [loop for loop in loops if loop is not None]
    exhausted = [loop for loop in seen if loop.exhausted]
    if exhausted:
        return _confirm(
            finding,
            f"stopped after {exhausted[0].longest} turns without terminating",
            vueltas=exhausted[0].longest,
        )
    if obs.budget_exceeded:
        return _confirm(finding, "the run hit its iteration budget", vueltas=obs.total_iterations)
    ran = [loop for loop in seen if loop.ran]
    if not ran:
        return _unreached(finding, "the while never ran")
    return _refute(
        finding,
        f"the loop terminated after {max(loop.longest for loop in ran)} turns",
        vueltas=max(loop.longest for loop in ran),
    )


@_resolver("M12")
def _unguarded_key(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M12 on whether a key was actually missing.

    A read that raised KeyError never reaches the subscript hook, so the
    exception is the observation. A read that worked refutes the candidate
    only for the keys the driver supplied, and the note says so: whether the
    key may be absent lives in the exercise statement, which is where the
    judge remains irreplaceable.
    """
    if obs.exception == "KeyError":
        return _confirm(finding, "the run raised KeyError on a missing key")
    read = [obs.subscripts.get(e.line) for e in finding.evidence]
    seen = [s for s in read if s is not None and s.n]
    if not seen:
        return _unreached(finding, "the subscript never ran")
    return _refute(
        finding,
        "every key the driver supplied was present; the statement decides the rest",
        lecturas=sum(s.n for s in seen),
    )


@_resolver("M13")
def _excess_complexity(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Measure M13's work, and refuse to name a class from one input.

    A growth class is a statement about how the work scales, and one input
    size cannot support it. What a single run gives is the work done and the
    input it was done on; naming the class needs ``profile --scaled``, which
    runs the submission over several sizes. Reporting a class from one point
    would be inventing the slope.
    """
    if not obs.executed or not obs.loops:
        return _unreached(finding, "no loop ran")
    largest = max((loop.largest_input for loop in obs.loops.values()), default=0)
    work = obs.total_iterations + obs.linear_work
    return replace(
        finding,
        data={
            **dict(finding.data),
            "runtime": (
                f"{work} units of work over at most {largest} elements; "
                "a growth class needs several input sizes"
            ),
            "trabajo": work,
            "vueltas": obs.total_iterations,
            "trabajo_en_c": obs.linear_work,
            "elementos": largest,
        },
    )


@_resolver("M14")
def _excess_memory(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M14 on how many times the allocation really happened.

    A copy written inside a loop costs nothing if the loop turns once. The
    run says how many turns there were, which is the difference between a
    shape that looks wasteful and work that was.
    """
    loops = [obs.enclosing_loop(e.line) for e in finding.evidence]
    seen = [loop for loop in loops if loop is not None and loop.ran]
    if not seen:
        return _unreached(finding, "the allocation never ran")
    worst = max(seen, key=lambda loop: loop.longest)
    if worst.longest > 1:
        return _confirm(
            finding,
            f"allocated on each of {worst.longest} turns",
            vueltas=worst.longest,
            elementos=worst.largest_input,
        )
    return _refute(finding, "the loop turned at most once", vueltas=worst.longest)


@_resolver("M15")
def _data_rewrite(finding: MetricFinding, obs: RunObservations) -> MetricFinding:
    """Settle M15 on whether a value was really thrown away.

    The write hook carries the old value and the new one, so this is the one
    metric whose confirmation is an observation rather than an inference:
    either the name held something different before the write or it did not.
    """
    writes = [obs.writes.get(e.line) for e in finding.evidence]
    seen = [w for w in writes if w is not None and w.n]
    if not seen:
        return _unreached(finding, "the write never ran")
    # `rebound`, not `discarded`: the question is whether the name already
    # held a value, not whether the new one differs. A rounding that writes
    # back the same number still threw the first computation away, and the
    # static pass has already established that nothing read it.
    rebound = [w for w in seen if w.rebound]
    if rebound:
        total = sum(w.rebound for w in rebound)
        return _confirm(
            finding,
            f"{total} writes replaced a value the name already held",
            evidence=tuple(
                Evidence(
                    line=w.line,
                    element=", ".join(sorted(w.old_types)),
                    detail=(
                        f"discarded a {', '.join(sorted(w.old_types))} {w.rebound} times"
                        + ("" if w.discarded else ", writing back an equal value")
                    ),
                )
                for w in sorted(rebound, key=lambda w: w.line)
            ),
            n=total,
        )
    return _refute(finding, "the name held nothing before the write", n=0)


# -- entry point -------------------------------------------------------


def resolve_report(report: MetricReport, obs: RunObservations) -> MetricReport:
    """Apply the run to every finding that a run can settle.

    A resolver runs for a metric whenever one is registered, not only when
    the static verdict was a candidate: M02 and M07 are widened by the run,
    and a finding the tree called ABSENT can become PRESENT because of what
    executed.

    Parameters:
        - report: The static report to settle.
        - obs: What the run observed.

    Returns:
        - The same report with its findings resolved where the run allows,
          and diagnostics recording what the run could not reach.
    """
    if obs.refused:
        report.diagnostics["dynamic"] = "refused before execution"
        report.diagnostics["dynamic_errors"] = list(obs.errors)
        return report

    resolved: list[MetricFinding] = []
    for finding in report.findings:
        rule = RESOLVERS.get(finding.metric.id)
        if rule is None:
            resolved.append(finding)
            continue
        try:
            resolved.append(rule(finding, obs))
        except Exception as exc:  # noqa: BLE001 - one rule must not sink the rest
            report.diagnostics.setdefault("resolver_errors", []).append(
                f"{finding.metric.id}: {type(exc).__name__}: {exc}"
            )
            resolved.append(finding)
    report.findings = resolved

    report.diagnostics["dynamic"] = "executed" if obs.executed else "no observations"
    if obs.errors:
        report.diagnostics["dynamic_errors"] = list(obs.errors)
    if obs.budget_exceeded:
        report.diagnostics["budget_exceeded"] = True
    report.diagnostics["unresolved"] = [
        f.metric.id for f in report.findings if not f.resolved and f.verdict is Judgement.PRESENT
    ]
    return report
