"""Metrics about tests that cannot vary and branches that cannot be reached."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Comparisons whose literal operand orders the chain: `x > 5` followed by
#: `x > 10` can never reach the second test.
_UPPER = (ast.Gt, ast.GtE)
_LOWER = (ast.Lt, ast.LtE)


def _operands(test: ast.expr) -> list[ast.expr]:
    """Return every operand of a boolean test, however deeply nested.

    One level is not enough. `a or (b and "c")` hides its literal inside the
    inner `and`, and that is the exact shape the course's recurring mistake
    takes once a student adds a third clause.

    Parameters:
        - test: The expression in an if or while.

    Returns:
        - The leaves of the boolean tree, or the test itself.
    """
    if not isinstance(test, ast.BoolOp):
        return [test]
    found: list[ast.expr] = []
    for value in test.values:
        found.extend(_operands(value))
    return found


@detector("m02_constant_condition")
def constant_condition(ctx: FunctionContext) -> MetricDetection:
    """Report a test with a bare literal among its operands.

    The course's recurring case is `if "a" or "b" in text`, which reads as a
    membership test and evaluates as a non-empty string: always true, and the
    else branch never runs. `while True` is excluded, being a legitimate idiom.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the offending line and literal, ABSENT, or
          NOT_APPLICABLE when the function branches on nothing.
    """
    tests = [n for n in ctx.nodes if isinstance(n, ast.If | ast.While)]
    if not tests:
        return MetricDetection(
            metric_id="M02",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no if or while in the function"},
        )

    hits: list[Evidence] = []
    for node in tests:
        operands = _operands(node.test)
        for operand in operands:
            if not isinstance(operand, ast.Constant):
                continue
            if isinstance(operand.value, bool):
                # `while True` is the idiom for a loop with a break, and
                # saying so about it would be noise. `if True` is not an
                # idiom: it is a branch the student stopped deciding.
                if isinstance(node, ast.While) or len(operands) > 1:
                    continue
            hits.append(
                Evidence(
                    line=node.lineno,
                    element=repr(operand.value),
                    detail="literal operand, so the test never varies",
                )
            )

    if not hits:
        return MetricDetection(metric_id="M02", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M02",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
    )


def _chain(node: ast.If) -> list[ast.If]:
    """Return an if/elif chain as a flat list.

    Parameters:
        - node: The head of the chain.

    Returns:
        - Every if in the chain, head first.
    """
    chain = [node]
    while len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        node = node.orelse[0]
        chain.append(node)
    return chain


def _threshold(test: ast.expr) -> tuple[str, type[ast.cmpop], float] | None:
    """Return (name, operator, bound) for a simple numeric comparison.

    Parameters:
        - test: The expression to inspect.

    Returns:
        - The triple, or None when the test is not `name <op> number`.
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left, right = test.left, test.comparators[0]
    if not isinstance(left, ast.Name) or not isinstance(right, ast.Constant):
        return None
    if isinstance(right.value, bool) or not isinstance(right.value, int | float):
        return None
    return left.id, type(test.ops[0]), float(right.value)


@detector("m08_impossible_branch")
def impossible_branch(ctx: FunctionContext) -> MetricDetection:
    """Report a branch that cannot be true given the ones before it.

    Two shapes are decided here: the same test written twice in one chain,
    and numeric thresholds ordered so a later branch is unreachable
    (`if x > 5` then `elif x > 10`). Anything with compound conditions is
    left undecided rather than guessed at.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the unreachable branch, ABSENT, or NOT_APPLICABLE when
          there is no if/elif chain.
    """
    heads: list[ast.If] = []
    nested: set[int] = set()
    for node in ctx.nodes:
        if isinstance(node, ast.If):
            for link in _chain(node)[1:]:
                nested.add(id(link))
    for node in ctx.nodes:
        if isinstance(node, ast.If) and id(node) not in nested:
            heads.append(node)

    chains = [_chain(head) for head in heads]
    chains = [chain for chain in chains if len(chain) > 1]
    if not chains:
        return MetricDetection(
            metric_id="M08",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no if/elif chain in the function"},
        )

    hits: list[Evidence] = []
    for chain in chains:
        seen: dict[str, int] = {}
        bounds: dict[str, tuple[type[ast.cmpop], float]] = {}
        for link in chain:
            shape = ast.dump(link.test)
            if shape in seen:
                hits.append(
                    Evidence(
                        line=link.lineno,
                        element=ctx.line(link.lineno),
                        detail=f"same test as line {seen[shape]}",
                    )
                )
            seen.setdefault(shape, link.lineno)

            threshold = _threshold(link.test)
            if threshold is None:
                continue
            name, operator, bound = threshold
            previous = bounds.get(name)
            if previous is not None:
                before_op, before_bound = previous
                unreachable = (
                    issubclass(before_op, _UPPER)
                    and issubclass(operator, _UPPER)
                    and bound >= before_bound
                ) or (
                    issubclass(before_op, _LOWER)
                    and issubclass(operator, _LOWER)
                    and bound <= before_bound
                )
                if unreachable:
                    hits.append(
                        Evidence(
                            line=link.lineno,
                            element=ctx.line(link.lineno),
                            detail="an earlier branch already caught every value",
                        )
                    )
            bounds[name] = (operator, bound)

    if not hits:
        return MetricDetection(metric_id="M08", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M08",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits)},
    )
