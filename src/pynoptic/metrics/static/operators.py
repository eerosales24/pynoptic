"""Metrics about how an expression reads versus how Python evaluates it."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector


def _char_before(lines: tuple[str, ...], line: int, column: int) -> str:
    """Return the last non-space character before a position.

    Parameters:
        - lines: The source lines.
        - line: The one-indexed line of the position.
        - column: The zero-indexed column of the position.

    Returns:
        - The character, or "" at the start of the source.
    """
    index = line - 1
    text = lines[index][:column] if 0 <= index < len(lines) else ""
    while True:
        stripped = text.rstrip()
        if stripped:
            return stripped[-1]
        index -= 1
        if index < 0:
            return ""
        text = lines[index]


def _char_after(lines: tuple[str, ...], line: int, column: int) -> str:
    """Return the first non-space character at or after a position.

    Parameters:
        - lines: The source lines.
        - line: The one-indexed line of the position.
        - column: The zero-indexed column of the position.

    Returns:
        - The character, or "" at the end of the source.
    """
    index = line - 1
    text = lines[index][column:] if 0 <= index < len(lines) else ""
    while True:
        stripped = text.lstrip()
        if stripped:
            return stripped[0]
        index += 1
        if index >= len(lines):
            return ""
        text = lines[index]


def _parenthesised(ctx: FunctionContext, node: ast.BoolOp) -> bool:
    """Return whether an expression is wrapped in its own parentheses.

    Both sides have to be checked. Looking only at what precedes the node
    calls `foo(a or b and c)` parenthesised because of the call's own
    bracket, and misses nothing at all when the student wrote the
    parentheses across two lines. A bracket before *and* a bracket after
    belongs to the expression.

    Parameters:
        - ctx: The function under audit.
        - node: The inner `and` to check.

    Returns:
        - True when the expression carries its own parentheses.
    """
    if node.end_lineno is None or node.end_col_offset is None:  # pragma: no cover
        return False
    before = _char_before(ctx.lines, node.lineno, node.col_offset)
    after = _char_after(ctx.lines, node.end_lineno, node.end_col_offset)
    return before == "(" and after == ")"


@detector("m04_implicit_precedence")
def implicit_precedence(ctx: FunctionContext) -> MetricDetection:
    """Report an `and` nested in an `or` without parentheses.

    `and` binds tighter than `or`, so `a or b and c` means `a or (b and c)`
    while it reads left to right. The distinction cannot come from the tree:
    parentheses are not stored, and `x or (y and z)` and `x or y and z`
    produce byte-identical dumps. The source position of the `and` node is
    what separates the student who wrote them from the one who did not.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the unparenthesised expression, ABSENT, or
          NOT_APPLICABLE when no `and` sits inside an `or` at all.
    """
    nested: list[tuple[ast.BoolOp, ast.BoolOp]] = []
    for node in ctx.nodes:
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        for value in node.values:
            if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.And):
                nested.append((node, value))

    if not nested:
        return MetricDetection(
            metric_id="M04",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no `and` inside an `or`"},
        )

    hits: list[Evidence] = []
    for _outer, inner in nested:
        if _parenthesised(ctx, inner):
            continue
        hits.append(
            Evidence(
                line=inner.lineno,
                element=ctx.line(inner.lineno),
                detail="`and` binds tighter than `or` here",
            )
        )

    if not hits:
        return MetricDetection(
            metric_id="M04",
            verdict=Judgement.ABSENT,
            data={"reason": "the `and` is parenthesised"},
        )
    return MetricDetection(
        metric_id="M04",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
    )
