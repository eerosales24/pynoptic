"""Refuse a submission before running a line of it.

The cheapest check is the one that never starts the process. Parsing the
source costs milliseconds and catches the import of an unvetted package, the
call that reaches outside the interpreter, and the attribute walk that is how
one escapes a Python-level guard.

It is a first pass, not the guard. `__import__("os")` built from a string
slips through here by construction, which is exactly why the audit hook in
``guard`` runs as well: this one refuses early and legibly, that one refuses
late and for certain.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .policy import (
    ALWAYS_ALLOWED_PREFIXES,
    NEVER_ALLOWED,
    ExecutionPolicy,
    is_private_accelerator,
)

__all__ = ["ScreenResult", "screen_source"]

#: Builtins that turn data into code, or hand out the namespace that lets a
#: caller rebuild anything the guard took away.
DANGEROUS_CALLS: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__", "globals", "locals", "breakpoint", "memoryview"}
)

#: Attributes that walk from any object to the interpreter's innards. The
#: `().__class__.__bases__[0].__subclasses__()` route is the classic one.
DANGEROUS_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
        "__dict__",
        "__getattribute__",
        "__reduce__",
        "__reduce_ex__",
    }
)



@dataclass(frozen=True)
class ScreenResult:
    """What the static screen concluded about one submission."""

    allowed: bool
    #: One human-readable line per problem, each naming the line it is on.
    reasons: tuple[str, ...] = ()
    #: Top-level modules the submission imports, whether or not allowed.
    imports: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return self.allowed


def _top_level(name: str) -> str:
    """Return the first component of a dotted module name.

    Parameters:
        - name: A module name, possibly dotted.

    Returns:
        - The top-level package name.
    """
    return name.split(".", 1)[0]


def screen_source(source: str, policy: ExecutionPolicy) -> ScreenResult:
    """Decide whether a submission may be executed at all.

    A submission that does not parse is allowed through: it cannot run, and
    the static analysis has already reported the syntax error.

    Parameters:
        - source: The submission's source code.
        - policy: The limits in force.

    Returns:
        - The verdict, with one reason per problem found.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ScreenResult(allowed=True, reasons=("source does not parse",))

    imported: set[str] = set()
    reasons: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(_top_level(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(_top_level(node.module))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_CALLS:
                reasons.append(f"line {node.lineno}: calls {node.func.id}()")
        elif isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ATTRIBUTES:
            reasons.append(f"line {node.lineno}: reaches for {node.attr}")

    for module in sorted(imported):
        if any(module == p or module.startswith(p + ".") for p in ALWAYS_ALLOWED_PREFIXES):
            continue
        if is_private_accelerator(module):
            continue
        if module in NEVER_ALLOWED:
            reasons.append(f"imports {module}, which is never allowed")
            continue
        if policy.allowed_imports is not None and module not in policy.allowed_imports:
            reasons.append(f"imports {module}, which is not on the allowlist")

    return ScreenResult(
        allowed=not reasons,
        reasons=tuple(reasons),
        imports=frozenset(imported),
    )
