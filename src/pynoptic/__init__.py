"""Pynoptic — profiler-based auditing of Python code submissions.

Pynoptic detects *Non-Curricular Constructs* (NCC) in student submissions:
Python constructs a student is not expected to use for a given exercise,
because they are outside the CS1 subset entirely (course-wide) or become
curricular only at a later level (level-relative).

The public surface is intentionally small::

    from pynoptic import Level, Report, scan_source, scan_file

    report = scan_file("submission.py", level=Level.L2)
    for finding in report.findings:
        print(finding.restriction.id, finding.kind)
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _metadata_version

from .dynamic.runner import DynamicRun, run_dynamic
from .engine import scan_file, scan_paths, scan_source, to_findings
from .models import (
    AstSpec,
    Detection,
    DynamicMatch,
    Finding,
    Level,
    Location,
    NccKind,
    Report,
    Restriction,
    SemgrepSpec,
    Tool,
    Verdict,
)
from .profile import Profile, profile_file, profile_source
from .restrictions import (
    get_restriction,
    restrictions,
    restrictions_at_least,
    restrictions_by_tool,
)
from .scan_multiple import ScanMultiple, ScanMultipleRecord

#: Read from the installed distribution rather than written here, so the
#: version exists in exactly one place: `pyproject.toml`. The CLI's
#: `--version` reads this constant, so a hand-maintained copy that drifts
#: from the packaging metadata makes the tool report a version it is not.
#:
#: The fallback is for running straight from a checkout that was never
#: installed, where there is no distribution to ask. A test pins the two
#: together so the literal cannot go stale unnoticed.
try:
    __version__ = _metadata_version("pynoptic")
except PackageNotFoundError:  # pragma: no cover - only outside an install
    __version__ = "1.0.0"

__all__ = [
    "__version__",
    "Level",
    "NccKind",
    "Tool",
    "Restriction",
    "Location",
    "Detection",
    "Finding",
    "Report",
    "Verdict",
    "SemgrepSpec",
    "AstSpec",
    "DynamicMatch",
    "restrictions",
    "get_restriction",
    "restrictions_at_least",
    "restrictions_by_tool",
    "scan_source",
    "scan_file",
    "scan_paths",
    "to_findings",
    "run_dynamic",
    "DynamicRun",
    "ScanMultiple",
    "ScanMultipleRecord",
    "Profile",
    "profile_file",
    "profile_source",
]
