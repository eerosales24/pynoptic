"""DynaPyt analysis that records ambiguous constructs at run time.

The hooks in this analysis are called by the DynaPyt runtime; they are
rewritten versions of the runtime hooks so they can record the ambiguous
constructs that execute at run time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dynapyt.analyses.BaseAnalysis import BaseAnalysis

from pynoptic.dynamic.resolve import Match, Outcome, category, resolve_dynamic, subscript_outcome
from pynoptic.dynamic.runner import RESULTS_FILE


class NccDynamicAnalysis(BaseAnalysis):
    def __init__(self, **kwargs: Any) -> None:
        """Initialise the analysis with an empty event list.

        Parameters:
            - kwargs: Forwarded to BaseAnalysis; includes output_dir.
        """
        super().__init__(**kwargs)
        self.events: list[dict[str, Any]] = []

    def _location(self, dyn_ast: str, iid: int) -> dict[str, Any] | None:
        """Resolve an IID to a source location.

        Parameters:
            - dyn_ast: The instrumented file the event came from.
            - iid: The instruction id of the event.

        Returns:
            - The location as a dictionary, or None when it is unknown.
        """
        try:
            location = self.iid_to_location(dyn_ast, iid)
        except (KeyError, FileNotFoundError, OSError):
            return None
        return {
            "file": location.file,
            "line": location.start_line,
            "column": location.start_column + 1,
            "end_line": location.end_line,
            "end_column": location.end_column + 1,
        }

    def _record(self, dyn_ast: str, iid: int, hook: str, match: Match) -> None:
        """Record that an event resolved to a restriction.

        Parameters:
            - dyn_ast: The instrumented file the event came from.
            - iid: The instruction id of the event.
            - hook: The DynaPyt hook that delivered the event.
            - match: The restriction selected by the runtime type.
        """
        self.events.append(
            {
                "hook": hook,
                "candidate": match.candidate,
                "restrictions": [match.restriction_id],
                "location": self._location(dyn_ast, iid),
            }
        )

    def _record_refutation(self, dyn_ast: str, iid: int, hook: str, candidate: str) -> None:
        """Record that a static candidate was reached but did not apply.

        Parameters:
            - dyn_ast: The instrumented file the event came from.
            - iid: The instruction id of the event.
            - hook: The DynaPyt hook that delivered the event.
            - candidate: The static candidate that was refuted.
        """
        self.events.append(
            {
                "hook": hook,
                "candidate": candidate,
                "restrictions": [],
                "location": self._location(dyn_ast, iid),
            }
        )

    def _emit(self, dyn_ast: str, iid: int, hook: str, outcome: Outcome) -> None:
        """Record every match and refutation of one classified event.

        Parameters:
            - dyn_ast: The instrumented file the event came from.
            - iid: The instruction id of the event.
            - hook: The DynaPyt hook that delivered the event.
            - outcome: The classification result.
        """
        for match in outcome.matches:
            self._record(dyn_ast, iid, hook, match)
        for candidate in outcome.refuted:
            self._record_refutation(dyn_ast, iid, hook, candidate)

    def pre_call(
        self,
        dyn_ast: str,
        iid: int,
        function: Any,
        pos_args: tuple[Any, ...],
        kw_args: dict[str, Any],
    ) -> None:
        """Classify a method call by its receiver type.

        Parameters:
            - dyn_ast: The instrumented file the call came from.
            - iid: The instruction id of the call.
            - function: The callable being invoked.
            - pos_args: The positional arguments, kept for hook completeness.
            - kw_args: The keyword arguments, kept for hook completeness.
        """
        receiver = getattr(function, "__self__", None)
        if receiver is None:
            return
        name = getattr(function, "__name__", "")
        if isinstance(receiver, type):
            receiver_type = receiver.__name__
        else:
            receiver_type = type(receiver).__name__
        if receiver_type == "frozenset":
            receiver_type = "set"
        outcome = resolve_dynamic("pre_call", name, {receiver_type})
        self._emit(dyn_ast, iid, "pre_call", outcome)

    def binary_operation(
        self,
        dyn_ast: str,
        iid: int,
        operator: str,
        left: Any,
        right: Any,
        result: Any,
    ) -> None:
        """Classify a binary operation by its operand types.

        Parameters:
            - dyn_ast: The instrumented file the operation came from.
            - iid: The instruction id of the operation.
            - operator: The DynaPyt operator name, such as Multiply.
            - left: The left operand.
            - right: The right operand.
            - result: The operation result; None marks an augmented
              assignment, which its own hook reports.
        """
        if result is None:
            return
        categories = {c for c in (category(left), category(right)) if c is not None}
        outcome = resolve_dynamic("binary_operation", operator, categories)
        self._emit(dyn_ast, iid, "binary_operation", outcome)

    def augmented_assignment(
        self, dyn_ast: str, iid: int, left: Any, operator: str, right: Any
    ) -> None:
        """Classify an augmented assignment by its operand types.

        Parameters:
            - dyn_ast: The instrumented file the operation came from.
            - iid: The instruction id of the operation.
            - left: The left operand.
            - operator: The DynaPyt operator name, such as BitAndAssign.
            - right: The right operand.
        """
        categories = {c for c in (category(left), category(right)) if c is not None}
        outcome = resolve_dynamic("augmented_assignment", operator, categories)
        self._emit(dyn_ast, iid, "augmented_assignment", outcome)

    def comparison(
        self,
        dyn_ast: str,
        iid: int,
        left: Any,
        operator: str,
        right: Any,
        result: Any,
    ) -> None:
        """Classify an ordering comparison by its operand types.

        Parameters:
            - dyn_ast: The instrumented file the comparison came from.
            - iid: The instruction id of the comparison.
            - left: The left operand.
            - operator: The DynaPyt operator name, such as LessThan.
            - right: The right operand.
            - result: The comparison result, kept for hook completeness.
        """
        categories = {c for c in (category(left), category(right)) if c is not None}
        outcome = resolve_dynamic("comparison", operator, categories)
        self._emit(dyn_ast, iid, "comparison", outcome)

    def read_subscript(
        self,
        dyn_ast: str,
        iid: int,
        base: Any,
        slices: list[Any],
        value: Any,
    ) -> None:
        """Classify a subscript read as slicing or negative indexing.

        Parameters:
            - dyn_ast: The instrumented file the subscript came from.
            - iid: The instruction id of the subscript.
            - base: The object being indexed.
            - slices: The subscript components.
            - value: The value read, kept for hook completeness.
        """
        outcome = subscript_outcome(base, slices)
        self._emit(dyn_ast, iid, "read_subscript", outcome)

    def end_execution(self, *args: Any) -> None:
        """Write the recorded events to pynoptic_dynamic.json.

        Parameters:
            - args: Ignored; accepted because DynaPyt calls this on shutdown.
        """
        if not self.output_dir or not self.events:
            return
        path = Path(self.output_dir) / RESULTS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = []
        path.write_text(
            json.dumps(existing + self.events, indent=2), encoding="utf-8"
        )
