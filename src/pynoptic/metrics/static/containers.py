"""Metrics about how the function walks, indexes and copies its data.

Every detector here is a candidate. Work, memory and key presence are
properties of a run, not of a shape: a nested loop can be linear, a copy can
be the asked-for output, a key can be guaranteed by the statement.
"""

from __future__ import annotations

import ast
from collections import defaultdict

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Methods and builtins that walk their argument. Their cost is invisible to
#: a bytecode counter because the work happens in C, which is exactly why
#: they are worth spotting in the tree first.
LINEAR_METHODS = frozenset({"count", "index", "remove", "sort", "reverse"})
LINEAR_BUILTINS = frozenset({"sorted", "max", "min", "sum"})
#: Calls that allocate a copy proportional to their argument.
COPYING_BUILTINS = frozenset({"list", "dict", "set", "tuple", "sorted"})
#: Methods that prove a name is used as a mapping.
MAPPING_METHODS = frozenset({"keys", "values", "items"})
#: Calls and tests that make a missing key safe.
GUARDS = frozenset({"get", "setdefault", "keys"})

#: Three identical calls is no longer a coincidence.
REPEATED_CALL_THRESHOLD = 3


def _inside_loops(ctx: FunctionContext) -> set[int]:
    """Return the ids of nodes that sit inside some loop.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - The set of id() values for nodes under a for or while.
    """
    inside: set[int] = set()
    for loop in ctx.loops:
        for node in ast.walk(loop):
            if node is not loop:
                inside.add(id(node))
    return inside


def _walked_name(loop: ast.For) -> str | None:
    """Return the name of the container a for walks, when it is a plain name.

    Parameters:
        - loop: The loop to inspect.

    Returns:
        - The container's name, or None when the iterable is an expression.
    """
    iterable = loop.iter
    if isinstance(iterable, ast.Name):
        return iterable.id
    if (
        isinstance(iterable, ast.Call)
        and isinstance(iterable.func, ast.Name)
        and iterable.func.id == "range"
        and iterable.args
    ):
        last = iterable.args[-1]
        if (
            isinstance(last, ast.Call)
            and isinstance(last.func, ast.Name)
            and last.func.id == "len"
            and last.args
            and isinstance(last.args[0], ast.Name)
        ):
            return last.args[0].id
    return None


@detector("m09_repeated_work")
def repeated_work(ctx: FunctionContext) -> MetricDetection:
    """Count passes over the same container, and calls made again unchanged.

    The count is the verdict, which is what makes this metric the one best
    coupled to its verifier: the profiler reports the same number and no
    threshold has to be argued about.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with the lines of each extra pass, ABSENT, or
          NOT_APPLICABLE when nothing is walked or called.
    """
    walked: defaultdict[str, list[int]] = defaultdict(list)
    for loop in ctx.loops:
        if isinstance(loop, ast.For):
            name = _walked_name(loop)
            if name is not None:
                walked[name].append(loop.lineno)

    calls: defaultdict[str, list[int]] = defaultdict(list)
    for node in ctx.nodes:
        if isinstance(node, ast.Call):
            calls[ast.dump(node)].append(node.lineno)

    if not walked and not calls:
        return MetricDetection(
            metric_id="M09",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "the function neither loops nor calls anything"},
        )

    hits: list[Evidence] = []
    passes = 0
    for name, lines in sorted(walked.items()):
        if len(lines) < 2:
            continue
        passes += len(lines)
        for line in lines:
            hits.append(
                Evidence(line=line, element=name, detail=f"{len(lines)} passes over {name}")
            )
    for lines in calls.values():
        if len(lines) < REPEATED_CALL_THRESHOLD:
            continue
        for line in lines:
            hits.append(
                Evidence(
                    line=line,
                    element=ctx.line(line),
                    detail=f"the same call appears {len(lines)} times",
                )
            )

    if not hits:
        return MetricDetection(metric_id="M09", verdict=Judgement.ABSENT, data={"n": 0})
    return MetricDetection(
        metric_id="M09",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": passes or len(hits)},
        resolved=False,
    )


def _is_mapping_annotation(annotation: ast.expr | None) -> bool:
    """Return whether an annotation names a mapping type.

    Parameters:
        - annotation: The annotation node, when there is one.

    Returns:
        - True for dict, Dict, Mapping and their subscripted forms.
    """
    if annotation is None:
        return False
    if isinstance(annotation, ast.Subscript):
        annotation = annotation.value
    if isinstance(annotation, ast.Attribute):
        return annotation.attr in {"Dict", "Mapping", "MutableMapping", "defaultdict"}
    if isinstance(annotation, ast.Name):
        return annotation.id in {"dict", "Dict", "Mapping", "MutableMapping", "defaultdict"}
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.split("[")[0].strip() in {"dict", "Dict", "Mapping"}
    return False


def _annotated_mappings(ctx: FunctionContext) -> set[str]:
    """Return the parameters and variables annotated as mappings.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - The names a reader can see are dictionaries.
    """
    args = ctx.node.args
    declared = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    found = {a.arg for a in declared if _is_mapping_annotation(a.annotation)}
    for node in ctx.nodes:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_mapping_annotation(node.annotation)
        ):
            found.add(node.target.id)
    return found


@detector("m12_unguarded_key")
def unguarded_key(ctx: FunctionContext) -> MetricDetection:
    """Report reading d[k] with no `in` test and no `get`.

    Whether the key may be absent lives in the exercise statement, not in the
    code, so the tree only narrows the field. A run with a key removed is
    what confirms the KeyError, and deciding which inputs are legitimate is
    the judge's irreplaceable contribution.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          no name is used as a mapping.
    """
    # A dictionary that arrives as a parameter is the commonest shape of
    # all — `def contar(inventario: dict)` — and nothing in the body has to
    # announce it. Reading the annotation is what stops the metric being
    # NOT_APPLICABLE for exactly the submissions it is about.
    mappings: set[str] = _annotated_mappings(ctx)
    guarded: set[str] = set()
    for node in ctx.nodes:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict | ast.DictComp):
            mappings |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.attr in MAPPING_METHODS:
                    mappings.add(node.func.value.id)
                if node.func.attr in GUARDS:
                    guarded.add(node.func.value.id)
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.In | ast.NotIn) for op in node.ops
        ):
            guarded |= {c.id for c in node.comparators if isinstance(c, ast.Name)}

    if not mappings:
        return MetricDetection(
            metric_id="M12",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no name is used as a dictionary"},
        )

    hits: list[Evidence] = []
    for node in ctx.nodes:
        if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)):
            continue
        if not isinstance(node.value, ast.Name) or isinstance(node.slice, ast.Slice):
            continue
        name = node.value.id
        if name not in mappings or name in guarded:
            continue
        if isinstance(node.slice, ast.Constant):
            continue
        hits.append(
            Evidence(
                line=node.lineno,
                element=ctx.line(node.lineno),
                detail=f"{name} is read without checking the key",
            )
        )

    if not hits:
        return MetricDetection(metric_id="M12", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M12",
        verdict=Judgement.PRESENT,
        evidence=tuple(hits),
        data={"n": len(hits)},
        resolved=False,
    )


@detector("m13_excess_complexity")
def excess_complexity(ctx: FunctionContext) -> MetricDetection:
    """Report linear work hidden in a call inside a loop.

    This is how an accidental quadratic shows up in practice: `in`, `.count`,
    `sorted` run once per turn. Nesting on its own is deliberately not the
    signal. The class itself is a run's answer, from counts over scaled
    inputs, so the tree only says where to look.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          the function has no loop.
    """
    if not ctx.loops:
        return MetricDetection(
            metric_id="M13",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no loop in the function"},
        )

    inside = _inside_loops(ctx)
    hits: list[Evidence] = []
    for node in ctx.nodes:
        if id(node) not in inside:
            continue
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.In | ast.NotIn) for op in node.ops
        ):
            hits.append(
                Evidence(
                    line=node.lineno,
                    element=ctx.line(node.lineno),
                    detail="membership test runs once per turn",
                )
            )
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Attribute) and node.func.attr in LINEAR_METHODS:
                name = node.func.attr
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id in LINEAR_BUILTINS
                # `max(a, b)` picks the larger of two numbers in constant
                # time; `max(lista)` walks. The container form takes exactly
                # one positional argument, and that is the whole difference.
                and len(node.args) == 1
                and not node.keywords
            ):
                name = node.func.id
            if name is not None:
                hits.append(
                    Evidence(
                        line=node.lineno,
                        element=name,
                        detail=f"{name} walks its argument once per turn",
                    )
                )

    if not hits:
        return MetricDetection(metric_id="M13", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M13",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits), "clase_estudiante": "desconocida"},
        resolved=False,
    )


@detector("m14_excess_memory")
def excess_memory(ctx: FunctionContext) -> MetricDetection:
    """Report a copy allocated once per turn of a loop.

    Slicing, `list(...)` and `.copy()` inside a loop grow with the input
    where a running value would not. How much more than the reference is the
    verifier's number, not the judge's.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, ABSENT, or NOT_APPLICABLE when
          the function has no loop.
    """
    if not ctx.loops:
        return MetricDetection(
            metric_id="M14",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "no loop in the function"},
        )

    inside = _inside_loops(ctx)
    hits: list[Evidence] = []
    for node in ctx.nodes:
        if id(node) not in inside:
            continue
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            hits.append(
                Evidence(
                    line=node.lineno,
                    element=ctx.line(node.lineno),
                    detail="a slice copies on every turn",
                )
            )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
                hits.append(
                    Evidence(line=node.lineno, element="copy", detail="copies on every turn")
                )
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id in COPYING_BUILTINS
                and node.args
            ):
                hits.append(
                    Evidence(
                        line=node.lineno,
                        element=node.func.id,
                        detail=f"{node.func.id}() allocates on every turn",
                    )
                )

    if not hits:
        return MetricDetection(metric_id="M14", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M14",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits)},
        resolved=False,
    )
