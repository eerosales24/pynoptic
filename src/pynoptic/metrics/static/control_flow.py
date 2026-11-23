"""Metrics about loops: stopping too early, too late, or never.

All three are static candidates. The authoritative answer is the run: how
many turns the loop actually took, whether the later turns changed anything,
whether it finished at all. The tree can only say the shape is suspicious.
"""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

Loop = ast.For | ast.While


def _reads(node: ast.AST) -> set[str]:
    """Return every name read inside a subtree.

    Parameters:
        - node: The subtree to inspect.

    Returns:
        - The set of names loaded.
    """
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _bound(statements: list[ast.stmt], *, deep: bool) -> set[str]:
    """Return the names these statements bind.

    Parameters:
        - statements: The block to inspect.
        - deep: Whether to look inside nested blocks as well.

    Returns:
        - The set of names assigned, augmented or bound by a for target.
    """
    names: set[str] = set()
    for statement in statements:
        nodes = ast.walk(statement) if deep else [statement]
        for node in nodes:
            if isinstance(node, ast.Assign):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.For):
                names |= {t.id for t in ast.walk(node.target) if isinstance(t, ast.Name)}
    return names


@detector("m06_premature_decision")
def premature_decision(ctx: FunctionContext) -> MetricDetection:
    """Report a return taken on the first turn of a loop.

    Two shapes: a bare return in the loop body, and an if whose two arms both
    return, which answers for the first element a question about all of them.
    A legitimate early return from a search looks the same from here, so the
    static answer is a candidate; the statement decides, and so does the run.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          the function has no loop.
    """
    if not ctx.loops:
        return MetricDetection(
            metric_id="M06",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no loop in the function"},
        )

    hits: list[Evidence] = []
    for loop in ctx.loops:
        for statement in loop.body:
            if isinstance(statement, ast.Return):
                hits.append(
                    Evidence(
                        line=statement.lineno,
                        element=ctx.line(statement.lineno),
                        detail="returns inside the loop body",
                    )
                )
            elif (
                isinstance(statement, ast.If)
                and statement.orelse
                and any(isinstance(s, ast.Return) for s in statement.body)
                and any(isinstance(s, ast.Return) for s in statement.orelse)
            ):
                hits.append(
                    Evidence(
                        line=statement.lineno,
                        element=ctx.line(statement.lineno),
                        detail="both arms return, so the first element decides",
                    )
                )

    if not hits:
        return MetricDetection(metric_id="M06", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M06",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
        resolved=False,
    )


@detector("m10_idle_iterations")
def idle_iterations(ctx: FunctionContext) -> MetricDetection:
    """Report a full traversal that is a search in disguise.

    The shape is a for with no break and no return whose whole body is one
    guard that sets a value without reading it. Once the guard has fired, the
    remaining turns change nothing. Whether those turns were wasted on a real
    input is the run's answer, not the tree's.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          the function has no loop.
    """
    if not ctx.loops:
        return MetricDetection(
            metric_id="M10",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no loop in the function"},
        )

    hits: list[Evidence] = []
    for loop in ctx.loops:
        if not isinstance(loop, ast.For):
            continue
        if any(isinstance(n, ast.Break | ast.Return) for n in ast.walk(loop)):
            continue
        if len(loop.body) != 1 or not isinstance(loop.body[0], ast.If):
            continue
        guard = loop.body[0]
        if guard.orelse:
            continue

        accumulates = False
        settles: list[ast.stmt] = []
        for statement in guard.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Name) and target.id not in _reads(statement.value):
                    settles.append(statement)
                    continue
            accumulates = True

        if settles and not accumulates:
            line = settles[-1].lineno
            hits.append(
                Evidence(
                    line=line,
                    element=ctx.line(line),
                    detail=f"settled in the loop at line {loop.lineno}, which keeps turning",
                )
            )

    if not hits:
        return MetricDetection(metric_id="M10", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M10",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
        resolved=False,
    )


@detector("m11_nonterminating_loop")
def nonterminating_loop(ctx: FunctionContext) -> MetricDetection:
    """Report a while whose control never moves towards false.

    Three gradations, weakest last: the body never binds any name the test
    reads; it binds one only inside a nested branch; it binds none directly
    but calls something that might. Only the run settles it, and the run's
    answer is the execution budget running out.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          the function has no while.
    """
    whiles = [loop for loop in ctx.loops if isinstance(loop, ast.While)]
    if not whiles:
        return MetricDetection(
            metric_id="M11",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no while in the function"},
        )

    hits: list[Evidence] = []
    for loop in whiles:
        control = _reads(loop.test)
        if not control:
            # `while True` and friends: the exit is a break, not the control.
            continue
        deep = _bound(loop.body, deep=True)
        shallow = _bound(loop.body, deep=False)
        calls = any(isinstance(n, ast.Call) for s in loop.body for n in ast.walk(s))

        if control & shallow:
            continue
        if control & deep:
            detail = "the control is only updated inside a branch"
        elif calls:
            detail = "the control only moves if a call changes it"
        else:
            detail = "the body never updates the control"
        hits.append(
            Evidence(
                line=loop.lineno,
                element=", ".join(sorted(control)),
                detail=detail,
            )
        )

    if not hits:
        return MetricDetection(metric_id="M11", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M11",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
        resolved=False,
    )
