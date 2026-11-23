"""Score a judge's answer against the detector's verdict.

The one thing this module must never do is report a disagreement where there
was nothing to agree with. Two of the seventeen metrics have only a partial
oracle and the interesting half of them is not decidable by any tool, so an
"agreement" figure computed over them would be measuring the detector's blind
spot and calling it the model's error.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Judgement, Metric, MetricFinding, Oracle
from .schema import Answer

__all__ = ["Agreement", "compare"]


@dataclass(frozen=True)
class Agreement:
    """How one answer lines up with one detector verdict."""

    metric_id: str
    oracle: Oracle
    detector: Judgement
    judge: Judgement
    #: None when the metric has no oracle for what was asked, which is not
    #: the same as False.
    agrees: bool | None
    #: Whether the judge cited at least one line the detector also cited.
    #: Measured separately from the verdict: a judge can reach the right
    #: answer for the wrong reason, and that is worth seeing.
    evidence_overlap: bool | None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return the JSON shape consumers see."""
        return {
            "metric_id": self.metric_id,
            "oracle": str(self.oracle),
            "detector": str(self.detector),
            "judge": str(self.judge),
            "agrees": self.agrees,
            "evidence_overlap": self.evidence_overlap,
            "note": self.note,
        }


def compare(metric: Metric, finding: MetricFinding, answer: Answer) -> Agreement:
    """Line a judge's answer up against the detector's verdict.

    Parameters:
        - metric: The catalog entry both were asked about.
        - finding: What the detector concluded.
        - answer: What the judge replied.

    Returns:
        - The comparison, with agrees set to None whenever the detector was
          not in a position to settle the question.
    """
    detector_lines = {e.line for e in finding.evidence}
    judge_lines = {e.line for e in answer.evidence}
    overlap: bool | None = None
    if detector_lines and judge_lines:
        overlap = bool(detector_lines & judge_lines)

    if metric.oracle is Oracle.NONE:
        return Agreement(
            metric_id=metric.id,
            oracle=metric.oracle,
            detector=finding.verdict,
            judge=answer.verdict,
            agrees=None,
            evidence_overlap=overlap,
            note="no deterministic verifier exists for this metric",
        )

    if answer.verdict is Judgement.UNDECIDABLE:
        return Agreement(
            metric_id=metric.id,
            oracle=metric.oracle,
            detector=finding.verdict,
            judge=answer.verdict,
            agrees=None,
            evidence_overlap=overlap,
            note="the judge declined to decide, which is an allowed answer",
        )

    if not finding.resolved:
        return Agreement(
            metric_id=metric.id,
            oracle=metric.oracle,
            detector=finding.verdict,
            judge=answer.verdict,
            agrees=None,
            evidence_overlap=overlap,
            note="the detector reports a candidate awaiting a run, not a verdict",
        )

    if (
        metric.oracle is Oracle.PARTIAL
        and finding.verdict is Judgement.ABSENT
        and answer.verdict is Judgement.PRESENT
    ):
        # The decidable half found nothing and the judge found something. On a
        # partial oracle that is the expected shape of a correct answer, not a
        # disagreement: the judge may be seeing the half no tool can check.
        return Agreement(
            metric_id=metric.id,
            oracle=metric.oracle,
            detector=finding.verdict,
            judge=answer.verdict,
            agrees=None,
            evidence_overlap=overlap,
            note="the judge reports what the verifier cannot see; needs human adjudication",
        )

    agrees = finding.verdict is answer.verdict
    note = ""
    if metric.oracle is Oracle.PARTIAL:
        note = "only the decidable half of this metric was compared"
    elif agrees and overlap is False:
        note = "same verdict, different lines"
    return Agreement(
        metric_id=metric.id,
        oracle=metric.oracle,
        detector=finding.verdict,
        judge=answer.verdict,
        agrees=agrees,
        evidence_overlap=overlap,
        note=note,
    )
