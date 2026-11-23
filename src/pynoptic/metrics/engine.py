"""Run the metric detectors over a submission and collect the verdicts.

Two passes, and the second is optional only in the sense that a machine
without a driver cannot take it. Nine of the seventeen metrics ask about
behaviour, so a static-only report is a report of suspicions for those nine,
and says so through ``resolved=False`` rather than by rounding them to a
verdict.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Level
from ..sandbox import STRICT, ExecutionPolicy
from ..sources import read_source
from .catalog import metrics_at
from .models import Judgement, MetricFinding, MetricReport
from .static import DETECTORS, build_context

__all__ = ["scan_metrics", "scan_metrics_file"]


def scan_metrics(
    source: str,
    *,
    level: Level | int | str = Level.L4,
    filename: str | None = None,
    function: str | None = None,
) -> MetricReport:
    """Apply every metric that is in scope at a level.

    A metric whose detector raises is reported in diagnostics rather than
    taking the scan down with it: one broken detector must not cost the other
    sixteen verdicts.

    Parameters:
        - source: The submission's source code.
        - level: The level of the exercise being audited.
        - filename: A display name recorded in diagnostics.
        - function: The name of the function to audit, when the exercise
          fixes one. Without it the first top-level function is used.

    Returns:
        - A report with one finding per applicable metric.
    """
    exercise_level = Level.parse(level)
    report = MetricReport(exercise_level=exercise_level)
    if filename:
        report.diagnostics["file"] = filename

    context = build_context(source, function=function)
    if context is None:
        report.syntax_error = True
        report.diagnostics["reason"] = (
            f"the source does not parse or defines no function named {function}"
            if function
            else "the source does not parse or defines no function"
        )
        return report

    report.diagnostics["function"] = context.node.name
    failures: list[str] = []
    for metric in metrics_at(exercise_level):
        if not metric.static:  # pragma: no cover - the catalog test forbids this
            continue
        run = DETECTORS.get(metric.static)
        if run is None:  # pragma: no cover - the catalog test forbids this
            failures.append(f"{metric.id}: no detector registered")
            continue
        try:
            detection = run(context)
        except Exception as exc:  # noqa: BLE001 - one detector must not sink the scan
            failures.append(f"{metric.id}: {type(exc).__name__}: {exc}")
            continue
        report.findings.append(
            MetricFinding(
                metric=metric,
                verdict=detection.verdict,
                evidence=detection.evidence,
                detector=detection.detector,
                data=detection.data,
                resolved=detection.resolved,
            )
        )

    if failures:
        report.diagnostics["detector_errors"] = failures
    report.diagnostics["unresolved"] = [
        f.metric.id for f in report.findings if not f.resolved and f.verdict is Judgement.PRESENT
    ]
    return report


def scan_metrics_file(
    path: str | Path,
    *,
    level: Level | int | str = Level.L4,
    function: str | None = None,
    dynamic: bool = False,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
) -> MetricReport:
    """Apply every applicable metric to a file, optionally running it.

    Parameters:
        - path: The submission to read.
        - level: The level of the exercise being audited.
        - function: The name of the function to audit.
        - dynamic: Whether to run the submission and settle the candidates.
        - driver: A script that imports the submission and exercises it.
        - driver_code: Driver source used instead of a driver file.
        - policy: The limits the run happens under.
        - timeout: Overrides the policy's timeout.

    Returns:
        - A report; syntax_error is set when the file cannot be read or
          parsed. With dynamic, candidates carry a verdict wherever the run
          reached them.
    """
    file_path = Path(path)
    try:
        source = read_source(file_path)
    except OSError as exc:
        report = MetricReport(exercise_level=Level.parse(level), syntax_error=True)
        report.diagnostics["reason"] = f"could not read {file_path}: {exc}"
        return report

    report = scan_metrics(source, level=level, filename=str(file_path), function=function)
    if not dynamic or report.syntax_error:
        return report

    # Imported here: the dynamic package pulls in DynaPyt, and a static scan
    # should not pay for an import it never uses.
    from .dynamic import observe, resolve_report

    observations = observe(
        file_path,
        driver=driver,
        driver_code=driver_code,
        policy=policy,
        timeout=timeout,
    )
    return resolve_report(report, observations)
