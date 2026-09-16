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
from .restrictions import (
    get_restriction,
    restrictions,
    restrictions_at_least,
    restrictions_by_tool,
)
from .scan_multiple import ScanMultiple, ScanMultipleRecord

__version__ = "0.1.0"

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
]
