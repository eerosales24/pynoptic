"""Run the Semgrep ruleset and turn its JSON output into detections."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..models import Detection, Location
from ..restrictions import get_restriction
from .rulegen import CANDIDATE_SUFFIX

__all__ = ["SemgrepError", "SemgrepRun", "rules_path", "scan_paths"]


class SemgrepError(RuntimeError):
    """Raised when Semgrep cannot be executed or returns unusable output."""


@dataclass
class SemgrepRun:
    """Detections grouped by file, plus non-fatal rule errors."""

    detections: list[Detection] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def rules_path() -> Path:
    """Return the absolute path of the bundled Semgrep ruleset."""
    return Path(str(files("pynoptic.static").joinpath("rules", "ncc.yml")))


def _executable() -> list[str]:
    """Return the command prefix used to invoke Semgrep.

    PATH is tried first, then the script directory next to the running
    interpreter, which is where the console script lands in a virtual
    environment that has not been activated.

    Returns:
        - The argument list that invokes the Semgrep CLI.

    Raises:
        - SemgrepError: when no Semgrep executable can be located. Running it
          as ``python -m semgrep`` is not a fallback: Semgrep deprecated that
          entry point in 1.38.0 and the project requires 1.177.0 or newer.
    """
    found = shutil.which("semgrep")
    if found:
        return [found]
    for candidate in ("semgrep.exe", "semgrep"):
        sibling = Path(sys.executable).parent / candidate
        if sibling.exists():
            return [str(sibling)]
    raise SemgrepError(
        "semgrep executable not found on PATH or next to the interpreter at "
        f"{sys.executable}"
    )


def _detection_from_result(result: dict[str, Any]) -> Detection | None:
    """Convert one Semgrep JSON result into a :class:`Detection`.

    Parameters:
        - result: A single entry from Semgrep's results array.

    Returns:
        - The detection, or None when the result has no usable rule id.
    """
    extra = result.get("extra", {})
    metadata = extra.get("metadata", {}) or {}
    raw_id = metadata.get("rule_id") or str(result.get("check_id", "")).split(".")[-1]
    if not raw_id:
        return None

    is_candidate = str(raw_id).endswith(CANDIDATE_SUFFIX)
    restriction_id = str(raw_id)
    if is_candidate:
        restriction_id = str(raw_id)[: -len(CANDIDATE_SUFFIX)]
    resolved = True
    if is_candidate:
        resolved = get_restriction(restriction_id).conclusive

    start = result.get("start", {})
    end = result.get("end", {})
    end_line = end.get("line")
    end_column = end.get("col")
    normalized_end_line = None
    if end_line is not None:
        normalized_end_line = int(end_line)
    normalized_end_column = None
    if end_column is not None:
        normalized_end_column = int(end_column)
    candidate = ""
    if is_candidate:
        candidate = restriction_id
    return Detection(
        restriction_id=restriction_id,
        detector="semgrep",
        location=Location(
            file=result.get("path"),
            line=int(start.get("line", 0)),
            column=int(start.get("col", 0)),
            end_line=normalized_end_line,
            end_column=normalized_end_column,
        ),
        resolved=resolved,
        candidate=candidate,
    )


def scan_paths(
    paths: Sequence[str | Path],
    *,
    rules: str | Path | None = None,
    timeout: float = 120.0,
) -> SemgrepRun:
    """Scan paths with the bundled (or given) ruleset.

    Parameters:
        - paths: The files or directories to scan.
        - rules: An alternative ruleset path; defaults to the bundled rules.
        - timeout: Seconds to wait before aborting the Semgrep process.

    Returns:
        - The detections and any non-fatal rule errors.

    Raises:
        - SemgrepError: If Semgrep cannot be run or its output cannot be read.
    """
    if not paths:
        return SemgrepRun()
    command = [
        *_executable(),
        "scan",
        "--config",
        str(rules or rules_path()),
        "--json",
        "--quiet",
        "--metrics",
        "off",
        "--no-git-ignore",
        "--disable-version-check",
        *[str(p) for p in paths],
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise SemgrepError("semgrep executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SemgrepError(f"semgrep timed out after {timeout}s") from exc

    if not completed.stdout.strip():
        raise SemgrepError(
            f"semgrep produced no JSON output (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SemgrepError(f"could not parse semgrep output: {exc}") from exc

    run = SemgrepRun()
    for error in payload.get("errors", []):
        message = error.get("message") or error.get("type") or str(error)
        run.errors.append(str(message))
    for result in payload.get("results", []):
        detection = _detection_from_result(result)
        if detection is not None:
            run.detections.append(detection)
    return run
