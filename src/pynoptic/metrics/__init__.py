"""Quality metrics: a second analysis dimension beside the NCC catalog.

A restriction asks whether the student used a construct the course has not
taught yet. A metric asks whether the code has a defect or a bad practice.
The subsystem exists to compare a deterministic verdict with an LLM judge's,
metric by metric, so both speak the same vocabulary.
"""

from __future__ import annotations

from .catalog import CATALOG, get_metric, metrics, metrics_at
from .engine import scan_metrics, scan_metrics_file
from .models import (
    Evidence,
    Judgement,
    Metric,
    MetricDetection,
    MetricFinding,
    MetricReport,
    Oracle,
    Shape,
)

__all__ = [
    "CATALOG",
    "Evidence",
    "Judgement",
    "Metric",
    "MetricDetection",
    "MetricFinding",
    "MetricReport",
    "Oracle",
    "Shape",
    "get_metric",
    "scan_metrics",
    "scan_metrics_file",
    "metrics",
    "metrics_at",
]
