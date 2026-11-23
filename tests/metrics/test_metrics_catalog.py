"""Reconcile the metric catalog with its detectors, hooks and prompts.

This is the check the NCC side could not have: there, the catalog's ast label
is declarative and nothing looks a detector up by it. Here Metric.static is
the registry key, so a metric without an implementation fails the suite
instead of silently never firing.
"""

from __future__ import annotations

import re
from collections import Counter

from pynoptic.dynamic.analysis import NccDynamicAnalysis
from pynoptic.metrics import CATALOG, Oracle, Shape, get_metric, metrics_at
from pynoptic.metrics.dynamic.analysis import MetricDynamicAnalysis
from pynoptic.metrics.static import DETECTORS
from pynoptic.models import Level

#: Hooks DynaPyt exposes and this project is willing to implement. A hook name
#: outside this set would be silently inert, because instrumentation is
#: derived from the analysis class's method names.
KNOWN_HOOKS = frozenset(
    {
        "pre_call",
        "binary_operation",
        "augmented_assignment",
        "comparison",
        "read_subscript",
        "enter_for",
        "exit_for",
        "normal_exit_for",
        "enter_while",
        "exit_while",
        "normal_exit_while",
        "_return",
        "function_enter",
        "function_exit",
        "write",
    }
)


def test_catalog_has_seventeen_metrics() -> None:
    assert len(CATALOG) == 17


def test_ids_are_unique_and_well_formed() -> None:
    ids = [m.id for m in CATALOG]
    assert [k for k, n in Counter(ids).items() if n > 1] == []
    assert [i for i in ids if not re.fullmatch(r"M\d{2}", i)] == []


def test_every_metric_declares_a_detector() -> None:
    assert [m.id for m in CATALOG if not m.static] == []


def test_every_declared_detector_is_registered() -> None:
    """Metric.static is a live key, not a label: a typo must fail here."""
    missing = [m.id for m in CATALOG if m.static and m.static not in DETECTORS]
    assert missing == []


def test_no_detector_is_registered_without_a_metric() -> None:
    declared = {m.static for m in CATALOG if m.static}
    assert sorted(set(DETECTORS) - declared) == []


def test_every_metric_declares_a_prompt() -> None:
    assert [m.id for m in CATALOG if not m.prompt] == []


def test_prompt_filenames_match_their_metric() -> None:
    assert [m.id for m in CATALOG if m.prompt != f"{m.id}.md"] == []


def test_declared_hooks_are_real_dynapyt_hooks() -> None:
    declared = {hook for m in CATALOG for hook in m.dynamic}
    assert sorted(declared - KNOWN_HOOKS) == []


def test_dynamic_primary_metrics_declare_hooks() -> None:
    assert [m.id for m in CATALOG if m.primary == "dynamic" and not m.dynamic] == []


def test_primary_is_a_known_verifier() -> None:
    assert [m.id for m in CATALOG if m.primary not in {"static", "dynamic"}] == []


def test_each_dimension_implements_its_own_hooks() -> None:
    """The NCC analysis resolves ambiguous constructs; loops are the metrics'."""
    ncc = {n for n in dir(NccDynamicAnalysis) if not n.startswith("__")}
    metric = {n for n in dir(MetricDynamicAnalysis) if not n.startswith("__")}
    assert "comparison" in ncc
    assert "enter_for" not in ncc
    assert {"enter_for", "enter_while", "write", "function_exit"} <= metric


def test_every_declared_hook_is_actually_implemented() -> None:
    """A declared hook nobody implements is a metric that never resolves.

    This is the check that catches the quiet failure: the catalog promising
    a runtime verifier for a metric whose hook is not in either analysis, so
    the candidate stays a candidate forever and nothing says why.
    """
    implemented = {
        name
        for analysis in (NccDynamicAnalysis, MetricDynamicAnalysis)
        for name in dir(analysis)
        if not name.startswith("__")
    }
    missing = sorted(
        {hook for m in CATALOG for hook in m.dynamic if hook not in implemented}
    )
    assert missing == []


def test_no_metric_declares_implicit_return() -> None:
    """DynaPyt weaves it but never calls it; function_exit is the real hook.

    The instrumenter honours `implicit_return` when selecting what to wrap,
    which makes it look supported. The runtime's `_func_exit_` then calls
    `function_exit`. A metric declaring implicit_return would silently never
    see a function falling off the end of its body, which is M07's most
    common shape.
    """
    assert [m.id for m in CATALOG if "implicit_return" in m.dynamic] == []


def test_shapes_and_oracles_are_enum_members() -> None:
    assert all(isinstance(m.shape, Shape) for m in CATALOG)
    assert all(isinstance(m.oracle, Oracle) for m in CATALOG)


def test_only_the_two_undecidable_halves_are_partial() -> None:
    """If this list grows, something stopped being verifiable; say so loudly."""
    partial = sorted(m.id for m in CATALOG if m.oracle is not Oracle.FULL)
    assert partial == ["M16", "M17"]


def test_counts_are_the_metrics_where_a_number_means_something() -> None:
    counted = sorted(m.id for m in CATALOG if m.shape is Shape.COUNT)
    assert counted == ["M05", "M09", "M17"]


def test_exactly_one_metric_answers_with_a_class() -> None:
    assert [m.id for m in CATALOG if m.shape is Shape.CLASS] == ["M13"]


def test_applies_at_reads_upwards_unlike_restriction_scope() -> None:
    """Restriction.is_ncc holds from its scope downwards; this is the inverse."""
    premature = get_metric("M06")
    assert premature.min_level is Level.L3
    assert premature.applies_at(Level.L2) is False
    assert premature.applies_at(Level.L3) is True
    assert premature.applies_at(Level.L4) is True


def test_metrics_at_filters_by_level() -> None:
    at_l1 = {m.id for m in metrics_at(Level.L1)}
    at_l4 = {m.id for m in metrics_at(Level.L4)}
    assert at_l1 < at_l4
    assert at_l4 == {m.id for m in CATALOG}
    assert "M06" not in at_l1


def test_every_metric_carries_a_note() -> None:
    assert [m.id for m in CATALOG if not m.note.strip()] == []
