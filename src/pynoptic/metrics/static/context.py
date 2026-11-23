"""The unit a static metric detector works on.

The NCC visitor dispatches per node type, which suits "does this construct
appear". A metric asks a different kind of question — about a parameter that
is never read, about sibling statements, about a whole if/elif chain — so the
unit here is the function, built once and handed to every detector.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property

__all__ = ["FunctionContext", "build_context"]

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class FunctionContext:
    """One function, with the derived views detectors keep asking for."""

    node: FunctionNode
    source: str

    @cached_property
    def lines(self) -> tuple[str, ...]:
        """Return the source lines, so line N is lines[N - 1]."""
        return tuple(self.source.splitlines())

    @cached_property
    def nodes(self) -> tuple[ast.AST, ...]:
        """Return the whole subtree, walked once."""
        return tuple(ast.walk(self.node))

    @cached_property
    def params(self) -> frozenset[str]:
        """Return every parameter name in the signature."""
        args = self.node.args
        collected = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg is not None:
            collected.append(args.vararg)
        if args.kwarg is not None:
            collected.append(args.kwarg)
        return frozenset(a.arg for a in collected)

    @cached_property
    def loaded(self) -> frozenset[str]:
        """Return every name the body reads."""
        return frozenset(
            n.id for n in self.nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        )

    @cached_property
    def assigned(self) -> frozenset[str]:
        """Return every name the body binds with a plain assignment."""
        return frozenset(
            target.id
            for n in self.nodes
            if isinstance(n, ast.Assign)
            for target in n.targets
            if isinstance(target, ast.Name)
        )

    @cached_property
    def loops(self) -> tuple[ast.For | ast.While, ...]:
        """Return every loop in the function."""
        return tuple(n for n in self.nodes if isinstance(n, ast.For | ast.While))

    @cached_property
    def returns(self) -> tuple[ast.Return, ...]:
        """Return every return statement that carries a value."""
        return tuple(n for n in self.nodes if isinstance(n, ast.Return) and n.value is not None)

    def line(self, number: int) -> str:
        """Return one source line, stripped, or "" when out of range.

        Parameters:
            - number: A one-indexed line number.

        Returns:
            - The line's text without surrounding whitespace.
        """
        if 1 <= number <= len(self.lines):
            return self.lines[number - 1].strip()
        return ""


def build_context(source: str, *, function: str | None = None) -> FunctionContext | None:
    """Build the context for the function under audit.

    Named is better than first. A submission that defines a helper above the
    answer would otherwise have its helper audited and the answer ignored,
    and in a corpus the expected name is always known — it is what the
    exercise asked for. Without a name the first top-level function is used,
    which is what a single-function submission means by "the function".

    A nested function is never picked by name alone: ``ast.walk`` would
    happily return one, and a closure inside the answer is part of the
    answer, not the unit under audit.

    Parameters:
        - source: The submission's source code.
        - function: The name to audit, when the exercise fixes one.

    Returns:
        - The context, or None when the source does not parse or defines no
          matching function.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    top_level = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if function is not None:
        for node in top_level:
            if node.name == function:
                return FunctionContext(node=node, source=source)
        # A submission may wrap its answer in a class, or define it inside
        # another function. The name was asked for, so it is worth finding.
        for inner in ast.walk(tree):
            if (
                isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef)
                and inner.name == function
            ):
                return FunctionContext(node=inner, source=source)
        return None

    if top_level:
        return FunctionContext(node=top_level[0], source=source)
    for inner in ast.walk(tree):
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef):
            return FunctionContext(node=inner, source=source)
    return None
