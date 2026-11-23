"""Detection, classification and the end-to-end scan.

The AST engine is driven directly because it is pure; only the full-pipeline
test pays for a Semgrep subprocess.
"""

from __future__ import annotations

from pynoptic import Level, scan_source
from pynoptic.static import detect


def test_syntax_error_is_an_outcome_not_a_crash() -> None:
    detections, failed = detect("def f(:\n")
    assert failed is True
    assert detections == []


def test_chained_comparison_is_located() -> None:
    detections, failed = detect("def f(a, b, c):\n    return a < b < c\n")
    assert failed is False
    hit = next(d for d in detections if d.restriction_id == "R10")
    assert hit.detector == "ast"
    assert hit.location.line == 2


def test_plain_comparison_is_not_flagged() -> None:
    detections, _ = detect("def f(a, b):\n    return a < b\n")
    assert "R10" not in {d.restriction_id for d in detections}


def test_dict_display_is_detected() -> None:
    detections, _ = detect('def f():\n    return {"a": 1}\n')
    assert "R36" in {d.restriction_id for d in detections}


def test_locations_are_one_indexed() -> None:
    """Column 0 of the source is reported as column 1."""
    detections, _ = detect('d = {"a": 1}\n')
    hit = next(d for d in detections if d.restriction_id == "R36")
    assert hit.location.line == 1
    assert hit.location.column == 5


def test_scan_source_classifies_by_level(semgrep: None) -> None:
    source = "def f(items):\n    return [x for x in items]\n"

    at_l1 = scan_source(source, level=Level.L1)
    assert "R110" in at_l1.restriction_ids
    assert at_l1.verdict is not None
    assert at_l1.verdict.n_violations >= 1

    finding = next(f for f in at_l1.findings if f.restriction.id == "R110")
    assert finding.location.line == 2


def test_report_serialises(semgrep: None) -> None:
    report = scan_source("def f():\n    return 1\n", level=Level.L1)
    payload = report.to_dict()
    assert payload["exercise_level"] == 1
    assert payload["syntax_error"] is False
    assert isinstance(payload["findings"], list)
