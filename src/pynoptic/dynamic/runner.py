"""Run the DynaPyt analysis over a submission and collect its findings.

The runner is sandbox-agnostic: it executes instrumented code in the current
process, on the assumption that the caller has already placed it inside the
grading worker's isolation boundary (Docker + nsjail). It never executes
student code directly and always works on a temporary copy.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pynoptic.models import Detection, Location

ANALYSIS = "pynoptic.dynamic.analysis.NccDynamicAnalysis"
RESULTS_FILE = "pynoptic_dynamic.json"


@dataclass
class DynamicRun:
    """Dynamic observations for one submission."""

    detections: list[Detection] = field(default_factory=list)
    observed: set[tuple[str, int]] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _purge_temp_modules() -> None:
    """Drop submission/driver modules cached by a previous dynamic run.

    Without this, a second run whose submission has the same module name
    would import the previous (already deleted) module from sys.modules.
    """
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if filename and "pynoptic-dynamic-" in filename:
            sys.modules.pop(name, None)


def _instrument(directory: Path) -> list[str]:
    """Instrument every Python file under directory in place.

    Parameters:
        - directory: The temporary directory holding the submission and driver.

    Returns:
        - A list of human-readable error messages; empty on success.
    """
    from dynapyt.instrument.instrument import instrument_file
    from dynapyt.utils.hooks import get_hooks_from_analysis

    errors: list[str] = []
    hooks = get_hooks_from_analysis([ANALYSIS])
    # DynaPyt's instrumenter prints progress to stdout; keep stdout clean for
    # callers that emit JSON.
    with contextlib.redirect_stdout(io.StringIO()):
        for path in sorted(directory.rglob("*.py")):
            try:
                if instrument_file(str(path), hooks) == 1:
                    errors.append(f"instrumentation failed for {path.name}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"instrumentation error for {path.name}: {exc}")
    return errors


def run_dynamic(
    submission: str | Path,
    *,
    driver: str | Path | None = None,
    driver_code: str | None = None,
) -> DynamicRun:
    """
    Instrument submission and execute it, collecting dynamic findings.

    Exactly one of driver (a path to a driver script) or driver_code
    (a driver source string) should exercise the submission. With neither, the
    submission module is executed as-is, which only records constructs reached
    at import time.

    Parameters:
        - submission: Path to the student submission.
        - driver: Optional path to a script that calls the submission.
        - driver_code: Optional driver source used instead of driver.

    Returns:
        - The recorded detections, observed candidates, raw events and errors.
    """
    submission_path = Path(submission)
    run = DynamicRun()
    if not submission_path.exists():
        run.errors.append(f"submission not found: {submission}")
        return run

    workdir = Path(tempfile.mkdtemp(prefix="pynoptic-dynamic-"))
    try:
        target = workdir / submission_path.name
        shutil.copy2(submission_path, target)

        if driver is not None:
            driver_path = Path(driver)
            shutil.copy2(driver_path, workdir / driver_path.name)
            entry = workdir / driver_path.name
        elif driver_code is not None:
            entry = workdir / "pynoptic_driver.py"
            entry.write_text(driver_code, encoding="utf-8")
        else:
            entry = target

        _purge_temp_modules()
        run.errors.extend(_instrument(workdir))

        session_id: str | None = None
        try:
            from dynapyt.run_analysis import run_analysis

            session_id = run_analysis(
                entry=str(entry),
                analyses=[ANALYSIS],
                output_dir=str(workdir),
            )
        except Exception as exc:  # noqa: BLE001 - student code can raise anything
            run.errors.append(f"dynamic execution error: {exc}")

        events = _read_events(workdir, session_id)
        run.events = events
        file_label = str(submission_path)
        for event in events:
            location = event.get("location") or {}
            line = int(location.get("line") or 0)
            candidate = event.get("candidate")
            if candidate:
                run.observed.add((str(candidate), line))
            for restriction_id in event.get("restrictions") or ():
                run.detections.append(
                    Detection(
                        restriction_id=restriction_id,
                        detector="dynapyt",
                        location=Location(
                            file=file_label,
                            line=line,
                            column=int(location.get("column") or 0),
                            end_line=location.get("end_line"),
                            end_column=location.get("end_column"),
                        ),
                        resolved=True,
                        candidate=str(candidate or ""),
                    )
                )
    finally:
        _purge_temp_modules()
        shutil.rmtree(workdir, ignore_errors=True)

    return run


def _read_events(workdir: Path, session_id: str | None = None) -> list[dict[str, Any]]:
    """
    Read the analysis output.

    DynaPyt writes it under <workdir>/dynapyt_output-<session>/, so look
    there first and fall back to a recursive search.

    Parameters:
        - workdir: The temporary directory used for the run.
        - session_id: The DynaPyt session id, when available.

    Returns:
        - The recorded events, or an empty list when no output was produced.
    """
    candidates: list[Path] = []
    if session_id:
        candidates.append(workdir / f"dynapyt_output-{session_id}" / RESULTS_FILE)
    candidates.extend(workdir.rglob(RESULTS_FILE))
    for output in candidates:
        if not output.exists():
            continue
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(payload, list):
            return payload
        return []
    return []
