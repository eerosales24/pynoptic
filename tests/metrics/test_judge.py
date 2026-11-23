"""Validating a judge's reply, and comparing it with the detector.

The schema tests encode the failure modes actually observed: a verdict
outside the vocabulary, a positive answer with no line, and a line number
that does not exist in the submission.
"""

from __future__ import annotations

import pytest

from pynoptic.metrics import Judgement, Oracle, get_metric, scan_metrics
from pynoptic.metrics.llm import InvalidAnswer, parse_answer
from pynoptic.metrics.llm.compare import compare

SOURCE = "def f(a, b):\n    return a\n"
LINES = len(SOURCE.splitlines())

BINARY = get_metric("M01")
COUNTING = get_metric("M05")
CLASSED = get_metric("M13")
PARTIAL = get_metric("M16")


def finding_for(metric_id: str, source: str = SOURCE):  # type: ignore[no-untyped-def]
    """Return the detector's finding for a metric, for use in comparisons."""
    report = scan_metrics(source, level=4)
    finding = report.by_id(metric_id)
    assert finding is not None
    return finding


def test_a_well_formed_answer_parses() -> None:
    answer = parse_answer(
        BINARY,
        '{"veredicto": "SI", "evidencia": [{"linea": 1, "elemento": "b"}], "razon": "x"}',
        line_count=LINES,
    )
    assert answer.verdict is Judgement.PRESENT
    assert answer.evidence[0].line == 1
    assert answer.evidence[0].element == "b"


def test_a_reply_that_is_not_json_is_rejected() -> None:
    with pytest.raises(InvalidAnswer, match="not valid JSON"):
        parse_answer(BINARY, "Creo que sí, el parámetro b no se usa.", line_count=LINES)


def test_a_verdict_outside_the_vocabulary_is_rejected() -> None:
    with pytest.raises(InvalidAnswer, match="veredicto"):
        parse_answer(BINARY, '{"veredicto": "QUIZAS"}', line_count=LINES)


def test_a_positive_verdict_without_evidence_is_rejected() -> None:
    """This is the requirement that took evidence anchoring to 94.1%."""
    with pytest.raises(InvalidAnswer, match="must cite at least one line"):
        parse_answer(BINARY, '{"veredicto": "SI", "evidencia": []}', line_count=LINES)


def test_an_invented_line_number_is_rejected() -> None:
    with pytest.raises(InvalidAnswer, match="outside the submission"):
        parse_answer(
            BINARY,
            '{"veredicto": "SI", "evidencia": [{"linea": 99, "elemento": "b"}]}',
            line_count=LINES,
        )


def test_a_negative_verdict_needs_no_evidence() -> None:
    answer = parse_answer(BINARY, '{"veredicto": "NO"}', line_count=LINES)
    assert answer.verdict is Judgement.ABSENT
    assert answer.evidence == ()


def test_a_counting_metric_needs_a_number() -> None:
    with pytest.raises(InvalidAnswer, match="`n` must be an integer"):
        parse_answer(
            COUNTING,
            '{"veredicto": "SI", "evidencia": [{"linea": 1, "elemento": "x"}]}',
            line_count=LINES,
        )


def test_a_counting_metric_rejects_zero_when_present() -> None:
    with pytest.raises(InvalidAnswer, match="at least 1"):
        parse_answer(
            COUNTING,
            '{"veredicto": "SI", "n": 0, "evidencia": [{"linea": 1, "elemento": "x"}]}',
            line_count=LINES,
        )


def test_a_class_metric_rejects_an_invented_class() -> None:
    with pytest.raises(InvalidAnswer, match="clase_estudiante"):
        parse_answer(
            CLASSED,
            '{"veredicto": "SI", "clase_estudiante": "rapido", '
            '"clase_referencia": "O(n)", "evidencia": [{"linea": 1, "elemento": "x"}]}',
            line_count=LINES,
        )


def test_a_class_metric_accepts_an_unknown_reference() -> None:
    """Without a reference solution the judge must still be able to answer."""
    answer = parse_answer(
        CLASSED,
        '{"veredicto": "SI", "clase_estudiante": "O(n^2)", '
        '"clase_referencia": "desconocida", "evidencia": [{"linea": 1, "elemento": "x"}]}',
        line_count=LINES,
    )
    assert answer.student_class == "O(n^2)"
    assert answer.reference_class == "desconocida"


def test_agreement_on_a_settled_metric() -> None:
    finding = finding_for("M01")
    answer = parse_answer(
        BINARY,
        '{"veredicto": "SI", "evidencia": [{"linea": 1, "elemento": "b"}], "razon": "x"}',
        line_count=LINES,
    )
    result = compare(BINARY, finding, answer)
    assert result.agrees is True
    assert result.evidence_overlap is True


def test_disagreement_on_a_settled_metric() -> None:
    finding = finding_for("M01")
    answer = parse_answer(BINARY, '{"veredicto": "NO"}', line_count=LINES)
    assert compare(BINARY, finding, answer).agrees is False


def test_an_unresolved_candidate_is_not_comparable() -> None:
    """A candidate is not a verdict, so scoring against it would be noise."""
    source = "def f(xs):\n    for x in xs:\n        return x > 0\n    return False\n"
    finding = finding_for("M06", source)
    assert finding.resolved is False
    answer = parse_answer(
        get_metric("M06"),
        '{"veredicto": "SI", "evidencia": [{"linea": 3, "elemento": "x"}], "razon": "x"}',
        line_count=len(source.splitlines()),
    )
    result = compare(get_metric("M06"), finding, answer)
    assert result.agrees is None
    assert "candidate" in result.note


def test_declining_to_decide_is_not_a_disagreement() -> None:
    finding = finding_for("M01")
    answer = parse_answer(BINARY, '{"veredicto": "NO_DECIDIBLE"}', line_count=LINES)
    assert compare(BINARY, finding, answer).agrees is None


def test_a_partial_oracle_does_not_score_what_it_cannot_see() -> None:
    """The detector checking only the shape must not make the judge wrong."""
    source = "def f(contador, acumulado, total, parcial):\n    return contador\n"
    finding = finding_for("M16", source)
    assert finding.verdict is Judgement.ABSENT
    answer = parse_answer(
        PARTIAL,
        '{"veredicto": "SI", "evidencia": [{"linea": 1, "elemento": "contador"}], '
        '"razon": "contador no cuenta nada"}',
        line_count=len(source.splitlines()),
    )
    result = compare(PARTIAL, finding, answer)
    assert result.agrees is None
    assert result.oracle is Oracle.PARTIAL
    assert "human adjudication" in result.note


def test_a_partial_oracle_still_scores_what_it_can_see() -> None:
    """When the decidable half fires, missing it is a real disagreement."""
    source = "def f(a, b, c, d):\n    e = a + b\n    g = c + d\n    return e + g\n"
    finding = finding_for("M16", source)
    assert finding.verdict is Judgement.PRESENT
    answer = parse_answer(PARTIAL, '{"veredicto": "NO"}', line_count=len(source.splitlines()))
    assert compare(PARTIAL, finding, answer).agrees is False
