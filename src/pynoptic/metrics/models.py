"""Types for the quality-metric dimension.

A restriction answers "did the student use a construct the course has not
taught yet?". A metric answers "is there a defect or a bad practice here?".
The two are independent, so metrics get their own types rather than widening
``Detection``: that dataclass is frozen with five fixed fields and no channel
for a value, while a metric routinely has one (how many passes over the list,
which complexity class, how much more memory than the reference).

The verdict vocabulary is shared with the LLM judge on purpose. The whole
point of the subsystem is to compare the two, and a comparison between
different vocabularies is a translation step that can silently disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..models import Level, Location

__all__ = [
    "Evidence",
    "Judgement",
    "Metric",
    "MetricDetection",
    "MetricFinding",
    "MetricReport",
    "Oracle",
    "Shape",
]


class Judgement(StrEnum):
    """The four answers a metric admits.

    Member names are English like the rest of the package; the values are the
    tokens that travel in JSON, which the prompts also demand verbatim.
    """

    PRESENT = "SI"
    ABSENT = "NO"
    #: The construct the metric asks about does not exist in this submission
    #: (asking about dictionaries of a function that has none).
    NOT_APPLICABLE = "NO_APLICA"
    #: The construct exists but the judge could not decide. Without this
    #: option an empty answer disguises itself as a judgement.
    UNDECIDABLE = "NO_DECIDIBLE"


class Shape(StrEnum):
    """How a metric's answer is shaped.

    - BINARY: the phenomenon is there or it is not.
    - COUNT: the number means something on its own and is comparable against
      the verifier without converting anything.
    - CLASS: the answer has structure, such as a complexity class.
    """

    BINARY = "binary"
    COUNT = "count"
    CLASS = "class"


class Oracle(StrEnum):
    """How much of the question a deterministic verifier can settle.

    This exists so a report cannot pass off "nothing could check this" as
    "the judge was wrong". Agreement is only meaningful against FULL; against
    PARTIAL it covers the decidable half; against NONE there is nothing to
    agree with, and the study has to fall back on inter-model agreement or
    human adjudication.
    """

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True)
class Evidence:
    """One anchored piece of support for a verdict.

    A line alone is not enough: a judge can hit the right line by accident.
    ``element`` names what on that line carries the phenomenon.
    """

    line: int
    element: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON shape consumers see."""
        return {"linea": self.line, "elemento": self.element, "detalle": self.detail}


@dataclass(frozen=True)
class Metric:
    """A catalog entry: what is measured, how it is answered, who verifies it.

    Unlike ``Restriction.ast``, which is a declarative label no runtime code
    reads, ``static`` is the real registry key: the reconciliation test looks
    the detector up by it.
    """

    id: str
    name: str
    shape: Shape
    #: A metric applies from this level upwards. Note this is the opposite
    #: comparison to Restriction.is_ncc, which holds from its scope downwards.
    min_level: Level = Level.L1
    static: str | None = None
    dynamic: tuple[str, ...] = ()
    #: Which verifier is authoritative when both run: "static" or "dynamic".
    primary: str = "static"
    #: How much of what the prompt asks the verifier can actually settle.
    oracle: Oracle = Oracle.FULL
    prompt: str = ""
    note: str = ""

    def applies_at(self, exercise_level: Level | int | str) -> bool:
        """Return whether this metric is in scope at a level.

        Parameters:
            - exercise_level: The level of the exercise being audited.

        Returns:
            - True when the exercise is at or above the metric's min_level.
        """
        return Level.parse(exercise_level) >= self.min_level

    @property
    def has_oracle(self) -> bool:
        """Return whether a deterministic verifier can decide this metric."""
        return self.oracle is not Oracle.NONE


@dataclass(frozen=True)
class MetricDetection:
    """What a detector concluded, before it is tied back to its catalog entry."""

    metric_id: str
    verdict: Judgement
    evidence: tuple[Evidence, ...] = ()
    detector: str = "ast"
    #: The value channel Detection does not have: {"pasadas": 3},
    #: {"clase": "O(n^2)"}, {"factor": 2.4}.
    data: Mapping[str, int | float | str] = field(default_factory=dict)
    #: False when a static candidate still awaits runtime confirmation.
    resolved: bool = True


@dataclass(frozen=True)
class MetricFinding:
    """A detection joined to its catalog entry, ready to serialise."""

    metric: Metric
    verdict: Judgement
    evidence: tuple[Evidence, ...] = ()
    detector: str = "ast"
    data: Mapping[str, int | float | str] = field(default_factory=dict)
    resolved: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON shape consumers see."""
        return {
            "metric_id": self.metric.id,
            "metric": self.metric.name,
            "shape": str(self.metric.shape),
            "veredicto": str(self.verdict),
            "evidencia": [e.to_dict() for e in self.evidence],
            "detector": self.detector,
            "resolved": self.resolved,
            "data": dict(self.data),
        }


@dataclass
class MetricReport:
    """Every metric's verdict for one submission."""

    exercise_level: Level
    findings: list[MetricFinding] = field(default_factory=list)
    syntax_error: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def present(self) -> list[MetricFinding]:
        """Return only the findings whose verdict is SI."""
        return [f for f in self.findings if f.verdict is Judgement.PRESENT]

    def by_id(self, metric_id: str) -> MetricFinding | None:
        """Return the finding for a metric id, when there is one.

        Parameters:
            - metric_id: The catalog id, such as "M01".

        Returns:
            - The matching finding, or None.
        """
        for finding in self.findings:
            if finding.metric.id == metric_id:
                return finding
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON shape consumers see."""
        return {
            "exercise_level": int(self.exercise_level),
            "syntax_error": self.syntax_error,
            "diagnostics": self.diagnostics,
            "findings": [f.to_dict() for f in self.findings],
        }


def location_of(evidence: Evidence, file: str | None = None) -> Location:
    """Adapt an Evidence to the package-wide Location type.

    Parameters:
        - evidence: The anchored support to convert.
        - file: The display path of the submission, when known.

    Returns:
        - A Location carrying the same line.
    """
    return Location(file=file, line=evidence.line)
