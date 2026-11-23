"""Metrics about what the function hands back."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Calls whose name is the type they build.
CONSTRUCTORS = frozenset({"str", "int", "float", "bool", "list", "dict", "tuple", "set"})


def _static_type(value: ast.expr) -> str | None:
    """Name the type of an expression when the tree alone settles it.

    Parameters:
        - value: The returned expression.

    Returns:
        - The type name, or None when only execution could tell.
    """
    if isinstance(value, ast.Constant):
        return type(value.value).__name__
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id in CONSTRUCTORS:
            return value.func.id
        return None
    if isinstance(value, ast.List | ast.ListComp):
        return "list"
    if isinstance(value, ast.Dict | ast.DictComp):
        return "dict"
    if isinstance(value, ast.Tuple):
        return "tuple"
    if isinstance(value, ast.Set | ast.SetComp):
        return "set"
    if isinstance(value, ast.JoinedStr):
        return "str"
    return None


def _terminates(statements: list[ast.stmt]) -> bool:
    """Return whether a block always leaves by return or raise.

    Parameters:
        - statements: The block to inspect.

    Returns:
        - True when control cannot reach the statement after this block.
    """
    for statement in statements:
        if isinstance(statement, ast.Return | ast.Raise):
            return True
        if isinstance(statement, ast.If) and statement.orelse:
            if _terminates(statement.body) and _terminates(statement.orelse):
                return True
        if isinstance(statement, ast.While) and not statement.orelse:
            # `while True:` with no break is the only loop that reliably
            # does not fall through, and proving the absence of a break is
            # the only part worth claiming.
            test = statement.test
            if isinstance(test, ast.Constant) and test.value is True:
                if not any(isinstance(n, ast.Break) for n in ast.walk(statement)):
                    return True
    return False


def _may_fall_through(ctx: FunctionContext) -> bool:
    """Return whether some path can reach the end of the body.

    A function that falls off its end returns None on that path, which makes
    its return type unstable the moment any other path returns a value. The
    tree can see the shape but not which paths run, so this only ever makes
    the static answer a candidate.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - True when control can reach the end of the body.
    """
    return not _terminates(ctx.node.body)


@detector("m07_unstable_return_type")
def unstable_return_type(ctx: FunctionContext) -> MetricDetection:
    """Report a function whose paths return different types.

    The caller cannot write one line that uses the result. The evidence is
    deliberately a pair of lines rather than one: the defect is the
    disagreement between two points, and demanding both stops a judge from
    claiming it while pointing at an ordinary return.

    Only returns whose type the tree settles are counted, so a function that
    returns variables comes back ABSENT here and is left to the run, which
    sees the actual values.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with one Evidence per return, ABSENT, or NOT_APPLICABLE
          when the function returns nothing explicitly.
    """
    if not ctx.returns:
        return MetricDetection(
            metric_id="M07",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "the function has no return with a value"},
        )

    typed: list[tuple[int, str]] = []
    for node in ctx.returns:
        if node.value is None:  # pragma: no cover - ctx.returns filters these
            continue
        name = _static_type(node.value)
        if name is not None:
            typed.append((node.lineno, name))

    kinds = {name for _, name in typed}
    if len(kinds) < 2:
        # Everything the tree could type agreed, which is not the same as
        # the function being stable. A `return total` says nothing here, and
        # neither does a path that falls off the end of the body. Both are
        # the run's to settle, so this ABSENT is a candidate, not a verdict.
        opaque = len(ctx.returns) - len(typed)
        falls_through = _may_fall_through(ctx)
        return MetricDetection(
            metric_id="M07",
            verdict=Judgement.ABSENT,
            data={
                "types": ",".join(sorted(kinds)),
                "untyped_returns": opaque,
                "falls_through": str(falls_through),
            },
            resolved=opaque == 0 and not falls_through,
        )

    return MetricDetection(
        metric_id="M07",
        verdict=Judgement.PRESENT,
        evidence=tuple(
            Evidence(line=line, element=ctx.line(line), detail=f"returns {name}")
            for line, name in sorted(typed)
        ),
        data={"types": ",".join(sorted(kinds)), "n": len(kinds)},
    )
