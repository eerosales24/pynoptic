"""Reconcile the restriction catalog with the detectors that implement it.

The catalog is the single source of truth, but three of its fields are only
honoured by convention: ``Restriction.ast`` is a declarative label no runtime
code reads, ``DynamicMatch.candidate`` names a Semgrep candidate declared
elsewhere, and ``DynamicMatch.hook`` names a method that must exist on the
analysis class. Nothing enforces any of that at import time, so these tests
are the enforcement.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from pynoptic.dynamic.analysis import NccDynamicAnalysis
from pynoptic.models import Level, Tool
from pynoptic.restrictions import AST_SPECS, SEMGREP_SPECS, restrictions
from pynoptic.verdict import SUPPRESSION, UNCONFIRMED_OPERATORS

AST_ENGINE = Path(__file__).resolve().parents[1] / "src" / "pynoptic" / "static" / "ast_engine.py"


def _emitted_ast_ids() -> set[str]:
    """Collect the restriction ids the AST visitor passes to _emit.

    Returns:
        - The set of literal ids found in _emit(...) calls.
    """
    source = AST_ENGINE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_emit"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                found.add(value)
    return found


def test_ids_are_unique_and_well_formed() -> None:
    ids = [r.id for r in restrictions()]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    assert duplicates == []
    assert [i for i in ids if not re.fullmatch(r"R\d+", i)] == []


def test_every_restriction_has_a_detector() -> None:
    orphans = [
        r.id
        for r in restrictions()
        if r.semgrep is None and r.ast is None and r.candidate is None and not r.dynamic
    ]
    assert orphans == []


def test_tool_matches_the_declared_detectors() -> None:
    mismatched: list[str] = []
    for restriction in restrictions():
        if restriction.tool is Tool.AST and restriction.ast is None:
            mismatched.append(restriction.id)
        if restriction.tool is Tool.SEMGREP and restriction.semgrep is None:
            mismatched.append(restriction.id)
        if restriction.tool is Tool.HYBRID and not restriction.dynamic:
            mismatched.append(restriction.id)
    assert mismatched == []


def test_ast_labels_and_visitor_emissions_agree() -> None:
    """The ast= label is declarative, so only this test couples it to the code."""
    declared = {r.id for r in restrictions() if r.ast is not None}
    emitted = _emitted_ast_ids()
    assert declared == emitted
    assert set(AST_SPECS) == declared


def test_semgrep_specs_index_matches_the_catalog() -> None:
    assert set(SEMGREP_SPECS) == {r.id for r in restrictions() if r.semgrep is not None}


def test_dynamic_candidates_exist_as_static_candidates() -> None:
    """A runtime trigger resolves a candidate that some restriction must declare."""
    declared = {r.id for r in restrictions() if r.candidate is not None}
    orphans = sorted(
        {m.candidate for r in restrictions() for m in r.dynamic} - declared
    )
    assert orphans == []


def test_dynamic_hooks_are_implemented_by_the_analysis() -> None:
    """DynaPyt derives instrumentation from method names, so a typo is inert."""
    implemented = {name for name in dir(NccDynamicAnalysis) if not name.startswith("__")}
    declared = {m.hook for r in restrictions() for m in r.dynamic}
    assert declared <= implemented


def test_scopes_are_levels() -> None:
    assert all(isinstance(r.scope, Level) for r in restrictions())


def test_suppression_and_unconfirmed_reference_real_ids() -> None:
    known = {r.id for r in restrictions()}
    referenced = {i for pair in SUPPRESSION for i in pair} | set(UNCONFIRMED_OPERATORS)
    assert sorted(referenced - known) == []


def test_suppression_pairs_are_not_self_referential() -> None:
    assert [pair for pair in SUPPRESSION if pair[0] == pair[1]] == []
