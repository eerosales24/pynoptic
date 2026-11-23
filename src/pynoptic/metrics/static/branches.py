"""Metrics about decisions that decide nothing and blocks written twice."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Below this, two sibling statements with the same shape are things like a
#: pair of `i += 1`, which is repetition without being a copied block.
MIN_SIGNATURE_LENGTH = 60


def _shape(node: ast.AST) -> str | None:
    """Return a structural signature for a node, ignoring field names.

    Parameters:
        - node: Any tree node.

    Returns:
        - The dump, or None when the node cannot be dumped.
    """
    try:
        return ast.dump(node, annotate_fields=False)
    except (TypeError, ValueError, RecursionError):  # pragma: no cover - defensive
        return None


@detector("m03_identical_branches")
def identical_branches(ctx: FunctionContext) -> MetricDetection:
    """Report an if whose two arms have the same body.

    The student wrote the structure of a decision without the decision
    changing anything. Comparing the two subtrees is exact, so there is
    nothing here for a profiler to confirm.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the line of each such if, ABSENT, or NOT_APPLICABLE
          when the function has no two-armed conditional.
    """
    conditionals = [n for n in ctx.nodes if isinstance(n, ast.If) and n.orelse]
    if not conditionals:
        return MetricDetection(
            metric_id="M03",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no if/else in the function"},
        )

    hits: list[Evidence] = []
    for node in conditionals:
        taken = _shape(ast.Module(body=node.body, type_ignores=[]))
        otherwise = _shape(ast.Module(body=node.orelse, type_ignores=[]))
        if taken is not None and taken == otherwise:
            hits.append(
                Evidence(
                    line=node.lineno,
                    element=ctx.line(node.lineno),
                    detail="both arms have the same body",
                )
            )

    if not hits:
        return MetricDetection(metric_id="M03", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M03",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
    )


@detector("m05_repeated_blocks")
def repeated_blocks(ctx: FunctionContext) -> MetricDetection:
    """Count sibling statements that are literal copies of each other.

    Counted rather than judged, because the number carries the meaning: two
    repeats is a slip, six is the shape of the solution.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with one Evidence per repeat and the total in data["n"],
          or ABSENT.
    """
    hits: list[Evidence] = []
    for node in ctx.nodes:
        for attribute in ("body", "orelse", "finalbody"):
            block = getattr(node, attribute, None)
            if not isinstance(block, list) or len(block) < 2:
                continue
            seen: dict[str, int] = {}
            for statement in block:
                shape = _shape(statement)
                if shape is None or len(shape) < MIN_SIGNATURE_LENGTH:
                    continue
                line = getattr(statement, "lineno", 0)
                if shape in seen:
                    hits.append(
                        Evidence(
                            line=line,
                            element=ctx.line(line),
                            detail=f"repeats line {seen[shape]}",
                        )
                    )
                else:
                    seen[shape] = line

    if not hits:
        return MetricDetection(metric_id="M05", verdict=Judgement.ABSENT, data={"n": 0})
    return MetricDetection(
        metric_id="M05",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits)},
    )
