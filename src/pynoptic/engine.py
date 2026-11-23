"""
Module to combine static and dynamic analysis of a Python submission into a single report.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from pynoptic import static
from pynoptic.dynamic.runner import DynamicRun, run_dynamic
from pynoptic.models import Detection, Finding, Level, Location, Report
from pynoptic.restrictions import get_restriction
from pynoptic.sources import read_source
from pynoptic.static import semgrep_runner
from pynoptic.verdict import to_verdict

__all__ = [
    "scan_source",
    "scan_file",
    "scan_paths",
    "to_findings",
    "merge_dynamic",
]


def to_findings(
    detections: Iterable[Detection],
    exercise_level: Level | int | str,
) -> list[Finding]:
    """Classify raw detections and keep only the ones that are NCCs.

    Detections for constructs that are allowed at exercise_level are
    dropped, and duplicate detections of the same restriction at the same
    source span are collapsed.

    Parameters:
        - detections: The raw detections to classify.
        - exercise_level: The level of the exercise being audited.

    Returns:
        - The findings that are Non-Curricular Constructs.
    """
    level = Level.parse(exercise_level)
    findings: list[Finding] = []
    seen: set[tuple[object, ...]] = set()
    for detection in detections:
        try:
            restriction = get_restriction(detection.restriction_id)
        except KeyError:
            continue
        kind = restriction.kind_at(level)
        if kind is None:
            continue
        location = detection.location
        key = (
            restriction.id,
            location.file,
            location.line,
            location.column,
            detection.detector,
        )
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Finding(
                restriction=restriction,
                kind=kind,
                detector=detection.detector,
                location=location,
                resolved=detection.resolved,
                candidate=detection.candidate,
            )
        )
    return findings


def _to_detection(finding: Finding) -> Detection:
    """Convert a finding back into a raw detection.

    Parameters:
        - finding: The finding to convert.

    Returns:
        - The equivalent detection.
    """
    return Detection(
        restriction_id=finding.restriction.id,
        detector=finding.detector,
        location=finding.location,
        resolved=finding.resolved,
        candidate=finding.candidate,
    )


def _resolve_detections(
    detections: Iterable[Detection], dynamic: DynamicRun
) -> list[Detection]:
    """Resolve static candidates with runtime observations.

    A candidate whose (candidate, line) was observed is replaced by the
    runtime detection; a candidate observed but unrestricted is refuted and
    dropped; an unobserved candidate is kept as unresolved.

    Parameters:
        - detections: The static detections, including candidates.
        - dynamic: The dynamic observations collected for the submission.

    Returns:
        - The merged detections, candidates resolved where possible.
    """
    by_candidate: dict[tuple[str, int], list[Detection]] = {}
    for detection in dynamic.detections:
        if detection.candidate:
            key = (detection.candidate, detection.location.line)
            by_candidate.setdefault(key, []).append(detection)

    merged: list[Detection] = []
    for detection in detections:
        if not detection.candidate:
            merged.append(detection)
            continue
        key = (detection.candidate, detection.location.line)
        if key in by_candidate:
            merged.extend(by_candidate.pop(key))
        elif key in dynamic.observed:
            continue
        else:
            merged.append(detection)
    for leftover in by_candidate.values():
        merged.extend(leftover)
    return merged


def merge_dynamic(
    static_findings: list[Finding],
    dynamic: DynamicRun,
    exercise_level: Level | int | str,
) -> list[Finding]:
    """Resolve, refute or enrich static candidates with runtime observations.

    A static candidate whose location was observed at run time is replaced by
    the restriction(s) the runtime types denote; if it was observed but no
    restriction applied, it is refuted and dropped. Candidates never observed
    at run time stay flagged as unresolved.

    Parameters:
        - static_findings: The findings from the static pass.
        - dynamic: The dynamic observations collected for the submission.
        - exercise_level: The level of the exercise being audited.

    Returns:
        - The merged findings.
    """
    detections = [_to_detection(finding) for finding in static_findings]
    return to_findings(_resolve_detections(detections, dynamic), exercise_level)


def _relabel(detection: Detection, label: str | None) -> Detection:
    """Return a copy of a detection whose location uses label as its file.

    Parameters:
        - detection: The detection to relabel.
        - label: The file label to report.

    Returns:
        - The relabelled detection.
    """
    location = detection.location
    return Detection(
        restriction_id=detection.restriction_id,
        detector=detection.detector,
        location=Location(
            file=label,
            line=location.line,
            column=location.column,
            end_line=location.end_line,
            end_column=location.end_column,
        ),
        resolved=detection.resolved,
        candidate=detection.candidate,
    )


def _collect(
    source: str, filename: str | None
) -> tuple[list[Detection], bool, list[str]]:
    """Run the ast and Semgrep detectors over a source string.

    Semgrep reads from disk, so the source is written to a temporary file.

    Parameters:
        - source: The Python source to analyse.
        - filename: The label to use for the source in detections.

    Returns:
        - The detections, whether the source failed to parse, and any Semgrep
          rule errors.
    """
    detections, syntax_error = static.detect(source, filename)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(source)
        temp_path = handle.name
    try:
        run = semgrep_runner.scan_paths([temp_path])
    finally:
        Path(temp_path).unlink(missing_ok=True)
    detections.extend(_relabel(detection, filename) for detection in run.detections)
    return detections, syntax_error, run.errors


def scan_source(
    source: str,
    *,
    filename: str | None = None,
    level: Level | int | str = Level.L4,
    dynamic: bool = False,
    driver: str | Path | None = None,
    driver_code: str | None = None,
) -> Report:
    """Audit an in-memory source string for NCCs at level.

    Parameters:
        - source: The Python source to audit.
        - filename: The label to use for the source in the report.
        - level: The level of the exercise being audited.
        - dynamic: Whether to resolve ambiguous constructs with DynaPyt.
        - driver: A driver script that exercises the submission.
        - driver_code: A driver source string used instead of driver.

    Returns:
        - The audit report.
    """
    parsed_level = Level.parse(level)
    if not dynamic:
        detections, syntax_error, errors = _collect(source, filename)
        report = Report(exercise_level=parsed_level, syntax_error=syntax_error)
        if errors:
            report.diagnostics["semgrep_errors"] = errors
        report.extend(to_findings(detections, parsed_level))
        report.verdict = to_verdict(detections, parsed_level)
        return report

    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(source)
        temp_path = handle.name
    try:
        return scan_file(
            temp_path,
            level=parsed_level,
            dynamic=True,
            driver=driver,
            driver_code=driver_code,
            display_name=filename,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)


def scan_file(
    path: str | Path,
    *,
    level: Level | int | str = Level.L4,
    dynamic: bool = False,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    display_name: str | None = None,
) -> Report:
    """Audit a single file, optionally resolving ambiguous constructs at run time.

    Parameters:
        - path: The file to audit.
        - level: The level of the exercise being audited.
        - dynamic: Whether to resolve ambiguous constructs with DynaPyt.
        - driver: A driver script that exercises the submission.
        - driver_code: A driver source string used instead of driver.
        - display_name: The label to report instead of the file's path.

    Returns:
        - The audit report.
    """
    parsed_level = Level.parse(level)
    file_path = Path(path)
    label = display_name or str(file_path)

    try:
        source = read_source(file_path)
    except (OSError, UnicodeDecodeError):
        detections: list[Detection] = []
        syntax_error = True
    else:
        detections, syntax_error = static.detect(source, label)

    semgrep_run = semgrep_runner.scan_paths([file_path])
    detections.extend(
        _relabel(detection, label) for detection in semgrep_run.detections
    )

    findings = to_findings(detections, parsed_level)
    report = Report(exercise_level=parsed_level, syntax_error=syntax_error)
    if semgrep_run.errors:
        report.diagnostics["semgrep_errors"] = semgrep_run.errors

    if dynamic:
        run = run_dynamic(file_path, driver=driver, driver_code=driver_code)
        if run.errors:
            report.diagnostics["dynamic_errors"] = run.errors
        report.diagnostics["dynamic_observations"] = len(run.observed)
        detections = _resolve_detections(detections, run)
        findings = to_findings(detections, parsed_level)

    report.extend(findings)
    report.verdict = to_verdict(detections, parsed_level)
    return report


def scan_paths(
    paths: Sequence[str | Path],
    *,
    level: Level | int | str = Level.L4,
) -> dict[str, Report]:
    """Audit many files in a single batched Semgrep invocation (static only).

    Parameters:
        - paths: The files to audit.
        - level: The level of the exercises being audited.

    Returns:
        - A mapping from each file path to its report.
    """
    parsed_level = Level.parse(level)
    file_paths = [Path(p) for p in paths]
    ast_by_file: dict[str, list[Detection]] = {}
    syntax_errors: set[str] = set()
    for file_path in file_paths:
        try:
            source = read_source(file_path)
        except (OSError, UnicodeDecodeError):
            syntax_errors.add(str(file_path))
            continue
        detections, syntax_error = static.detect(source, str(file_path))
        ast_by_file[str(file_path)] = detections
        if syntax_error:
            syntax_errors.add(str(file_path))

    run = semgrep_runner.scan_paths(file_paths)
    semgrep_by_file: dict[str, list[Detection]] = {}
    for detection in run.detections:
        semgrep_by_file.setdefault(str(detection.location.file), []).append(detection)

    reports: dict[str, Report] = {}
    for file_path in file_paths:
        key = str(file_path)
        detections = ast_by_file.get(key, []) + semgrep_by_file.get(key, [])
        report = Report(
            exercise_level=parsed_level,
            syntax_error=key in syntax_errors,
        )
        if run.errors:
            report.diagnostics["semgrep_errors"] = run.errors
        report.extend(to_findings(detections, parsed_level))
        report.verdict = to_verdict(detections, parsed_level)
        reports[key] = report
    return reports
