"""The three answer shapes an LLM judge may return, and their validation.

The judge and the detector share a vocabulary on purpose. Comparing two
different vocabularies means translating one into the other, and a
translation step is somewhere a disagreement can hide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..models import Evidence, Judgement, Metric, Shape

__all__ = ["Answer", "InvalidAnswer", "parse_answer", "schema_for"]

#: The literal JSON an LLM is shown, one per shape. Kept as text rather than
#: generated so what the prompt promises and what the parser accepts are the
#: same thing, visible side by side.
SCHEMAS: dict[Shape, str] = {
    Shape.BINARY: (
        "{\n"
        '  "veredicto": "SI" | "NO" | "NO_APLICA" | "NO_DECIDIBLE",\n'
        '  "evidencia": [{"linea": <int>, "elemento": "<texto>"}],\n'
        '  "razon": "<una frase>"\n'
        "}"
    ),
    Shape.COUNT: (
        "{\n"
        '  "veredicto": "SI" | "NO" | "NO_APLICA" | "NO_DECIDIBLE",\n'
        '  "n": <int>,\n'
        '  "evidencia": [{"linea": <int>, "elemento": "<texto>"}],\n'
        '  "razon": "<una frase>"\n'
        "}"
    ),
    Shape.CLASS: (
        "{\n"
        '  "veredicto": "SI" | "NO" | "NO_APLICA" | "NO_DECIDIBLE",\n'
        '  "clase_estudiante": "O(1)" | "O(n)" | "O(n^2)" | "O(n^3+)",\n'
        '  "clase_referencia": "O(1)" | "O(n)" | "O(n^2)" | "O(n^3+)" | "desconocida",\n'
        '  "evidencia": [{"linea": <int>, "elemento": "<texto>"}],\n'
        '  "razon": "<una frase>"\n'
        "}"
    ),
}

#: Valid growth classes, in order.
CLASSES = ("O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3+)")


class InvalidAnswer(ValueError):
    """Raised when a judge's reply does not satisfy its metric's schema."""


@dataclass(frozen=True)
class Answer:
    """One judge's reply, parsed and checked against its metric."""

    metric_id: str
    verdict: Judgement
    evidence: tuple[Evidence, ...] = ()
    reason: str = ""
    count: int | None = None
    student_class: str | None = None
    reference_class: str | None = None


def schema_for(metric: Metric) -> str:
    """Return the JSON schema text for a metric's answer shape.

    Parameters:
        - metric: The catalog entry being asked about.

    Returns:
        - The literal JSON shown in the prompt.
    """
    return SCHEMAS[metric.shape]


def _evidence(raw: object, *, line_count: int) -> tuple[Evidence, ...]:
    """Parse and bound-check the evidence list.

    Parameters:
        - raw: The value of the "evidencia" key.
        - line_count: How many lines the submission has.

    Returns:
        - The parsed evidence.

    Raises:
        - InvalidAnswer: When an entry is malformed or cites a line that does
          not exist. A judge that invents a line number is the failure this
          catches, and it is the one measured most often.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise InvalidAnswer("`evidencia` must be a list")
    parsed: list[Evidence] = []
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidAnswer("each evidence entry must be an object")
        line = item.get("linea")
        if not isinstance(line, int) or isinstance(line, bool):
            raise InvalidAnswer("`linea` must be an integer")
        if not 1 <= line <= line_count:
            raise InvalidAnswer(f"line {line} is outside the submission (1..{line_count})")
        element = item.get("elemento", "")
        parsed.append(Evidence(line=line, element=str(element)))
    return tuple(parsed)


def parse_answer(metric: Metric, payload: str | dict[str, object], *, line_count: int) -> Answer:
    """Parse a judge's reply and check it against the metric's shape.

    Parameters:
        - metric: The catalog entry that was asked about.
        - payload: The raw JSON text, or an already-decoded object.
        - line_count: How many lines the submission has, to bound the
          evidence.

    Returns:
        - The parsed answer.

    Raises:
        - InvalidAnswer: When the reply is not JSON, omits a required field,
          uses a verdict outside the vocabulary, cites a line that does not
          exist, or gives a positive verdict without evidence.
    """
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidAnswer(f"reply is not valid JSON: {exc}") from exc
    else:
        decoded = payload
    if not isinstance(decoded, dict):
        raise InvalidAnswer("reply must be a JSON object")

    raw_verdict = decoded.get("veredicto")
    try:
        verdict = Judgement(str(raw_verdict))
    except ValueError as exc:
        allowed = ", ".join(j.value for j in Judgement)
        raise InvalidAnswer(f"`veredicto` must be one of: {allowed}") from exc

    evidence = _evidence(decoded.get("evidencia"), line_count=line_count)
    if verdict is Judgement.PRESENT and not evidence:
        raise InvalidAnswer("a SI verdict must cite at least one line")

    count: int | None = None
    if metric.shape is Shape.COUNT:
        raw_count = decoded.get("n")
        if verdict is Judgement.PRESENT:
            if not isinstance(raw_count, int) or isinstance(raw_count, bool):
                raise InvalidAnswer("`n` must be an integer for a counting metric")
            if raw_count < 1:
                raise InvalidAnswer("`n` must be at least 1 when the verdict is SI")
            count = raw_count
        elif isinstance(raw_count, int) and not isinstance(raw_count, bool):
            count = raw_count

    student_class: str | None = None
    reference_class: str | None = None
    if metric.shape is Shape.CLASS and verdict is Judgement.PRESENT:
        student_class = str(decoded.get("clase_estudiante", ""))
        reference_class = str(decoded.get("clase_referencia", ""))
        if student_class not in CLASSES:
            raise InvalidAnswer(f"`clase_estudiante` must be one of: {', '.join(CLASSES)}")
        if reference_class not in (*CLASSES, "desconocida"):
            raise InvalidAnswer("`clase_referencia` must be a class or 'desconocida'")

    return Answer(
        metric_id=metric.id,
        verdict=verdict,
        evidence=evidence,
        reason=str(decoded.get("razon", "")),
        count=count,
        student_class=student_class,
        reference_class=reference_class,
    )
