"""Metrics about the signature and what the body does with it."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Receiver names are bound by the call, not by the caller, so a method that
#: ignores them is not solving a smaller problem.
RECEIVERS = frozenset({"self", "cls"})


def _rebound_before_read(ctx: FunctionContext, name: str) -> bool:
    """Return whether a name is assigned before anything reads it.

    Position, not walk order, decides "before": ``ast.walk`` is breadth
    first and would call a read in a nested branch earlier than an
    assignment above it.

    A rebinding that reads the name first — the accumulator ``x = x + 1`` —
    does not count, because the received value was used to compute the new
    one.

    Parameters:
        - ctx: The function under audit.
        - name: The parameter to check.

    Returns:
        - True when the argument's value cannot reach any read.
    """
    first_read: tuple[int, int] | None = None
    first_write: tuple[int, int] | None = None
    for node in ctx.nodes:
        if not isinstance(node, ast.Name) or node.id != name:
            continue
        position = (node.lineno, node.col_offset)
        if isinstance(node.ctx, ast.Load):
            if first_read is None or position < first_read:
                first_read = position
        elif isinstance(node.ctx, ast.Store):
            if first_write is None or position < first_write:
                first_write = position

    if first_write is None or first_read is None:
        return False
    if first_read < first_write:
        return False

    # The write wins. It only shadows the argument if it is unconditional:
    # an assignment inside an `if` leaves a path where the argument is the
    # value that gets read.
    for statement in ctx.node.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = statement.value
        reads_itself = value is not None and any(
            isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
            for n in ast.walk(value)
        )
        return not reads_itself
    return False


@detector("m01_ignored_parameter")
def ignored_parameter(ctx: FunctionContext) -> MetricDetection:
    """Report parameters the body never reads.

    A result cannot depend on a value the function does not look at, so an
    ignored parameter means the submission answers a smaller question than
    the one asked. The tree settles this outright, which is what makes the
    metric useful as a calibration probe for a judge that confabulates.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the unread names, ABSENT, or NOT_APPLICABLE when the
          signature takes nothing.
    """
    declared = ctx.params - RECEIVERS
    if not declared:
        return MetricDetection(
            metric_id="M01",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "the signature takes no parameters"},
        )

    unread = set(declared - ctx.loaded)
    # A parameter the body overwrites before reading is ignored just as
    # surely as one it never mentions: the result cannot depend on what the
    # caller passed. `def f(x): x = 5; return x` reads the name and ignores
    # the argument, and counting the name as a read hides exactly that.
    shadowed = {name for name in declared - unread if _rebound_before_read(ctx, name)}
    unread |= shadowed
    if not unread:
        return MetricDetection(metric_id="M01", verdict=Judgement.ABSENT)
    ordered = sorted(unread)

    return MetricDetection(
        metric_id="M01",
        verdict=Judgement.PRESENT,
        evidence=tuple(
            Evidence(
                line=ctx.node.lineno,
                element=name,
                detail="overwritten before it was read" if name in shadowed else "never read",
            )
            for name in ordered
        ),
        data={"n": len(ordered)},
    )
