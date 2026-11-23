"""Metrics about data the function destroys before using it."""

from __future__ import annotations

import ast

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: Methods that change the receiver in place.
MUTATORS = frozenset(
    {"append", "sort", "extend", "insert", "pop", "remove", "reverse", "clear", "update"}
)


def _reads(node: ast.AST) -> set[str]:
    """Return every name read inside a subtree.

    Parameters:
        - node: The subtree to inspect.

    Returns:
        - The set of names loaded.
    """
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _dead_stores(ctx: FunctionContext) -> list[Evidence]:
    """Find values overwritten before anything reads them.

    Only straight-line runs of statements are considered: once control
    branches or loops, "before" stops being a property of the text. That is
    also what keeps the accumulator idiom out, since `x = x + 1` reads x.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - One Evidence per lost value.
    """
    loop_targets: set[str] = set()
    for node in ctx.nodes:
        if isinstance(node, ast.For):
            loop_targets |= {t.id for t in ast.walk(node.target) if isinstance(t, ast.Name)}

    found: list[Evidence] = []
    for node in ctx.nodes:
        for attribute in ("body", "orelse", "finalbody"):
            block = getattr(node, attribute, None)
            if not isinstance(block, list):
                continue
            pending: dict[str, int] = {}
            for statement in block:
                read_here = _reads(statement)
                for name in [n for n in pending if n in read_here]:
                    del pending[name]
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                ):
                    name = statement.targets[0].id
                    if name in pending and name in ctx.loaded and name not in loop_targets:
                        # Anchored on the write that destroys the value, not
                        # on the one that computed it. That is the statement
                        # a reader has to change, and it is the line the run
                        # observes: the write hook fires where the old value
                        # is discarded.
                        found.append(
                            Evidence(
                                line=statement.lineno,
                                element=name,
                                detail=(
                                    f"discards what line {pending[name]} computed, "
                                    "which nothing read"
                                ),
                            )
                        )
                    computed = not isinstance(statement.value, ast.Constant)
                    if computed and name not in _reads(statement.value):
                        pending[name] = statement.lineno
                    else:
                        pending.pop(name, None)
                elif isinstance(statement, ast.For | ast.While | ast.If | ast.Try):
                    pending.clear()
    return found


def _mutations(ctx: FunctionContext) -> list[Evidence]:
    """Find in-place changes to what the function received.

    Aliasing counts: `copy = param` without a real copy leaves both names on
    the same object, which is the half a reader most often misses.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - One Evidence per mutation of a parameter or an alias of one.
    """
    aliases: set[str] = set()
    for node in ctx.nodes:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name)
            and node.value.id in ctx.params
        ):
            aliases.add(node.targets[0].id)

    targets = ctx.params | aliases
    found: list[Evidence] = []
    for node in ctx.nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in targets
                ):
                    found.append(
                        Evidence(
                            line=node.lineno,
                            element=target.value.id,
                            detail="writes into what it received",
                        )
                    )
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Subscript)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id in targets
        ):
            found.append(
                Evidence(
                    line=node.lineno,
                    element=node.target.value.id,
                    detail="writes into what it received",
                )
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in targets
            and node.func.attr in MUTATORS
        ):
            alias_note = " through an alias" if node.func.value.id in aliases else ""
            found.append(
                Evidence(
                    line=node.lineno,
                    element=f"{node.func.value.id}.{node.func.attr}()",
                    detail=f"changes what it received in place{alias_note}",
                )
            )
    return found


@detector("m15_data_rewrite")
def data_rewrite(ctx: FunctionContext) -> MetricDetection:
    """Report a value the function destroys without using it.

    Two shapes are visible from the tree: an assignment overwritten before
    anything reads it, and an in-place change to what the function received.
    A name that is never read at all is not this metric — that is a declared
    and unused variable, which the restriction catalog already covers.

    The run settles both far better, because the write hook carries the old
    value and the new one, so the answer is observed rather than inferred.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT as an unresolved candidate, or ABSENT.
    """
    hits = _dead_stores(ctx) + _mutations(ctx)
    if not hits:
        return MetricDetection(metric_id="M15", verdict=Judgement.ABSENT)
    return MetricDetection(
        metric_id="M15",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits)},
        resolved=False,
    )
