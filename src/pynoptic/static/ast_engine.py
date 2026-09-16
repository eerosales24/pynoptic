"""Static detection via Python's ast module.

These are the restrictions whose shape no Semgrep pattern expresses (chained
comparison, collection displays, assignment shapes, signatures, decorators,
idioms). Each restriction declares its ast detector label in the catalog
(:mod:`pynoptic.restrictions`).
"""

from __future__ import annotations

import ast

from ..models import Detection, Location

__all__ = ["detect"]


def _loc(node: ast.AST, filename: str | None) -> Location:
    """Build a 1-indexed Location for an AST node.

    Parameters:
        - node: The node to locate.
        - filename: The file the node came from, or None.

    Returns:
        - The node's source span.
    """
    start_column = getattr(node, "col_offset", 0)
    end_offset = getattr(node, "end_col_offset", None)
    end_column = None
    if end_offset is not None:
        end_column = end_offset + 1
    return Location(
        file=filename,
        line=getattr(node, "lineno", 0),
        column=start_column + 1,
        end_line=getattr(node, "end_lineno", None),
        end_column=end_column,
    )


class _AstAuditor(ast.NodeVisitor):
    """Walks the tree once and emits a detection for each matching node."""

    def __init__(self, filename: str | None) -> None:
        """Store the file label and start with no detections.

        Parameters:
            - filename: The file the source came from, or None.
        """
        self.filename = filename
        self.detections: list[Detection] = []
        self._function_depth = 0

    def _emit(self, restriction_id: str, node: ast.AST) -> None:
        """Record a detection for a restriction at a node.

        Parameters:
            - restriction_id: The restriction to report.
            - node: The node that triggered it.
        """
        self.detections.append(
            Detection(
                restriction_id=restriction_id,
                detector="ast",
                location=_loc(node, self.filename),
            )
        )

    def visit_Compare(self, node: ast.Compare) -> None:
        """Detect chained comparisons such as a < b < c (R10)."""
        if len(node.ops) > 1:
            self._emit("R10", node)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Detect dictionary displays such as {"a": 1} (R41)."""
        self._emit("R41", node)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        """Detect set displays such as {1, 2} (R123)."""
        self._emit("R123", node)
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        """Detect list displays such as [1, 2] (R53)."""
        self._emit("R53", node)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        """Detect tuple displays such as (1, 2) (R220)."""
        self._emit("R220", node)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Detect anonymous functions and their signature (R155, R47/R153)."""
        self._emit("R155", node)
        self._check_signature(node.args, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Detect keyword arguments at a call site (R47)."""
        if node.keywords:
            self._emit("R47", node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Detect chained assignment and tuple packing/unpacking (R79/R80/R87/R88)."""
        if len(node.targets) > 1:
            self._emit("R87", node)
        if isinstance(node.value, ast.Tuple):
            self._emit("R79", node)
        for target in node.targets:
            self._check_unpacking(target, node)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """Detect starred unpacking in a for target (R88)."""
        self._check_starred_target(node.target, node)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """Detect starred unpacking in an async for target (R88)."""
        self._check_starred_target(node.target, node)
        self.generic_visit(node)

    def _check_unpacking(self, target: ast.AST, node: ast.AST) -> None:
        """Emit R88 for a starred target, otherwise R80.

        Parameters:
            - target: The assignment target to inspect.
            - node: The statement to report the location of.
        """
        if isinstance(target, (ast.Tuple, ast.List)):
            if _contains_starred(target):
                self._emit("R88", node)
            else:
                self._emit("R80", node)

    def _check_starred_target(self, target: ast.AST, node: ast.AST) -> None:
        """Emit R88 when a loop target contains a starred element.

        Parameters:
            - target: The loop target to inspect.
            - node: The statement to report the location of.
        """
        if isinstance(target, (ast.Tuple, ast.List)) and _contains_starred(target):
            self._emit("R88", node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a regular function definition."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an asynchronous function definition."""
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Detect nested functions, decorators and signatures (R154/R175/R176/R47/R153).

        Parameters:
            - node: The function definition being visited.
        """
        if self._function_depth > 0:
            self._emit("R154", node)
        if node.decorator_list:
            self._emit("R175", node)
            for decorator in node.decorator_list:
                if _decorator_name(decorator) in {"staticmethod", "classmethod"}:
                    self._emit("R176", node)
        self._check_signature(node.args, node)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Detect decorated classes (R175/R176)."""
        if node.decorator_list:
            self._emit("R175", node)
            for decorator in node.decorator_list:
                if _decorator_name(decorator) in {"staticmethod", "classmethod"}:
                    self._emit("R176", node)
        self.generic_visit(node)

    def _check_signature(self, args: ast.arguments, node: ast.AST) -> None:
        """Emit R47 for defaults and R153 for *args/**kwargs.

        Parameters:
            - args: The function arguments to inspect.
            - node: The node to report the location of.
        """
        if args.defaults or any(d is not None for d in args.kw_defaults):
            self._emit("R47", node)
        if args.vararg is not None or args.kwarg is not None:
            self._emit("R153", node)

    def visit_Try(self, node: ast.Try) -> None:
        """Detect a finally clause (R149)."""
        if node.finalbody:
            self._emit("R149", node)
        self.generic_visit(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        """Detect a finally clause on an except* block (R149)."""
        if node.finalbody:
            self._emit("R149", node)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        """Detect the if __name__ == "__main__" guard (R161)."""
        if _is_main_guard(node.test):
            self._emit("R161", node)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        """Detect structural pattern matching (R144)."""
        self._emit("R144", node)
        self.generic_visit(node)


def _contains_starred(target: ast.AST) -> bool:
    """Return whether a target contains a starred element.

    Parameters:
        - target: The assignment or loop target to search.

    Returns:
        - True when any descendant is an ast.Starred.
    """
    return any(isinstance(child, ast.Starred) for child in ast.walk(target))


def _decorator_name(node: ast.AST) -> str:
    """Return the final name of a decorator expression.

    Parameters:
        - node: The decorator expression.

    Returns:
        - The function name, or an empty string for unsupported shapes.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _is_main_guard(test: ast.AST) -> bool:
    """Return whether a condition is __name__ == "__main__".

    Parameters:
        - test: The if condition to inspect.

    Returns:
        - True when it compares __name__ with "__main__".
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    is_name = isinstance(left, ast.Name) and left.id == "__name__"
    is_main = isinstance(right, ast.Constant) and right.value == "__main__"
    reverse_name = isinstance(right, ast.Name) and right.id == "__name__"
    reverse_main = isinstance(left, ast.Constant) and left.value == "__main__"
    return (is_name and is_main) or (reverse_name and reverse_main)


def detect(source: str, filename: str | None = None) -> tuple[list[Detection], bool]:
    """Run the ast detectors over source.

    Parameters:
        - source: The Python source to analyse.
        - filename: The file label used in detections.

    Returns:
        - A tuple of the detections and a flag telling whether the source
          failed to parse. A SyntaxError is a first-class outcome: such
          submissions are recorded, not silently dropped.
    """
    try:
        tree = ast.parse(source, filename=filename or "<unknown>")
    except SyntaxError:
        return [], True
    auditor = _AstAuditor(filename)
    auditor.visit(tree)
    return auditor.detections, False
