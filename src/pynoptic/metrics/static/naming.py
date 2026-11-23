"""Metric about names, and the half of it no tool can settle."""

from __future__ import annotations

import ast
import re

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Single letters that are idiomatic as indices and counters.
IDIOMATIC = frozenset({"i", "j", "k", "n", "_"})
#: `lista2`, `suma1`: a name disambiguated by a number rather than by meaning.
NUMBERED = re.compile(r"^[A-Za-z_]+\d+$")
#: Below this many names, a short one is not yet a habit. Three, not four:
#: the threshold used to be read against a count that included every
#: builtin the function mentioned, so a typical CS1 answer cleared it on
#: `len` and `round` alone. Counting only the names the student chose, a
#: well-named function binds two or three, and four would exempt most of
#: the corpus from the metric.
MIN_NAMES = 3
#: At or above this share of opaque names, the function reads as initials.
OPAQUE_SHARE = 0.5


def _bound_names(ctx: FunctionContext) -> set[str]:
    """Return the names the function itself binds.

    A name the student chose is one they assigned, walked a loop with,
    caught an exception into or unpacked. A name they only read belongs to
    the language or to an import, and judging their naming by it measures
    the standard library.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - Every name bound inside the function.
    """
    bound: set[str] = set()
    for node in ctx.nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.comprehension):
            bound |= {
                n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)
            }
    return bound


@detector("m16_meaningless_names")
def meaningless_names(ctx: FunctionContext) -> MetricDetection:
    """Report names that carry no meaning by their shape.

    This settles one half of the question: one- and two-character names that
    are not the idiomatic indices, and names disambiguated with a digit. The
    other half — whether the name matches what the variable actually holds —
    is not decidable by any tool, which is why the catalog marks this metric
    as having only a partial oracle. A judge asked the full question and
    scored only against this half would look wrong when it was right.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the offending names, ABSENT, or NOT_APPLICABLE when
          the function binds too few names to tell.
    """
    # Only names the student chose. Counting every Name in the tree pulls
    # in `len`, `range`, `round` and every imported module, which pads the
    # denominator with names nobody picked and drags the opaque share below
    # any threshold: a two-line function using three builtins would need
    # four bad names before it tripped.
    names = set(ctx.params) | _bound_names(ctx)
    considered = sorted(names - IDIOMATIC)
    if len(considered) < MIN_NAMES:
        return MetricDetection(
            metric_id="M16",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": f"only {len(considered)} names to judge"},
        )

    opaque = [n for n in considered if len(n) <= 2]
    numbered = [n for n in considered if NUMBERED.match(n)]
    share = len(opaque) / len(considered)

    offenders = sorted(set(opaque) | set(numbered))
    if share < OPAQUE_SHARE and not numbered:
        return MetricDetection(
            metric_id="M16",
            verdict=Judgement.ABSENT,
            data={"opaque_share": round(share, 2)},
        )

    lines: dict[str, int] = {}
    for node in ctx.nodes:
        if isinstance(node, ast.Name) and node.id in offenders:
            lines.setdefault(node.id, node.lineno)

    return MetricDetection(
        metric_id="M16",
        verdict=Judgement.PRESENT,
        evidence=tuple(
            Evidence(
                line=lines.get(name, ctx.node.lineno),
                element=name,
                detail="numbered rather than named" if NUMBERED.match(name) else "too short",
            )
            for name in offenders
        ),
        data={"n": len(offenders), "opaque_share": round(share, 2)},
    )
