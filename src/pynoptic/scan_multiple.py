"""Batch scanning for corpus studies.

Streams one JSON record per submission so a corpus of any size can be
processed without holding every report in memory.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import scan_paths
from .models import Level, Report

__all__ = ["ScanMultiple", "ScanMultipleRecord", "LevelResolver"]

LevelResolver = int | Level | Mapping[str, int] | Callable[[Path], int]

_BATCH_SIZE = 250


@dataclass
class ScanMultipleRecord:
    """One scanned submission.

    Parameters:
        - path: The submission's path.
        - exercise_level: The level it was audited against.
        - syntax_error: Whether the submission failed to parse.
        - findings: The NCCs found, as dictionaries.
        - diagnostics: Tool-specific notes.
        - error: An error that stopped the scan of this submission, if any.
        - n_violations: Counted violation occurrences.
        - violations: Restriction id -> counted occurrences.
        - n_ambiguous: Ambiguous, uncounted occurrences.
        - ambiguous: Ambiguous group -> occurrences.
        - compliant: True when no occurrence was counted.
    """

    path: str
    exercise_level: int
    syntax_error: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    n_violations: int = 0
    violations: dict[str, int] = field(default_factory=dict)
    n_ambiguous: int = 0
    ambiguous: dict[str, int] = field(default_factory=dict)
    compliant: bool = True

    @classmethod
    def from_report(cls, path: str, report: Report) -> ScanMultipleRecord:
        """Build a record from a completed report.

        Parameters:
            - path: The submission's path.
            - report: The report to convert.

        Returns:
            - The corresponding scan-multiple record.
        """
        payload = report.to_dict()
        record = cls(
            path=path,
            exercise_level=payload["exercise_level"],
            syntax_error=payload["syntax_error"],
            findings=payload["findings"],
            diagnostics=payload["diagnostics"],
        )
        verdict = report.verdict
        if verdict is not None:
            record.n_violations = verdict.n_violations
            record.violations = verdict.violations
            record.n_ambiguous = verdict.n_ambiguous
            record.ambiguous = verdict.ambiguous
            record.compliant = verdict.compliant
        return record

    @classmethod
    def failure(cls, path: str, level: Level, error: str) -> ScanMultipleRecord:
        """Build a record for a submission that could not be scanned.

        Parameters:
            - path: The submission's path.
            - level: The level it was audited against.
            - error: The error message.

        Returns:
            - The corresponding scan-multiple record.
        """
        return cls(path=path, exercise_level=int(level), syntax_error=False, error=error)

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-serialisable dictionary."""
        return {
            "path": self.path,
            "exercise_level": self.exercise_level,
            "syntax_error": self.syntax_error,
            "error": self.error,
            "diagnostics": self.diagnostics,
            "findings": self.findings,
            "n_violations": self.n_violations,
            "violations": self.violations,
            "n_ambiguous": self.n_ambiguous,
            "ambiguous": self.ambiguous,
            "compliant": self.compliant,
        }


class ScanMultiple:
    """Scan a directory tree or list of submissions against a level mapping.

    Parameters:
        - paths: A directory, a file, or a sequence of either.
        - levels: A single level for every file, a mapping keyed by full path,
          file name, stem, or parent directory name, or a callable.
        - pattern: The glob pattern used when walking directories.
        - recursive: Whether to recurse into subdirectories.
        - default_level: The level used when levels does not match a file.
    """

    def __init__(
        self,
        paths: str | Path | Sequence[str | Path],
        *,
        levels: LevelResolver = Level.L4,
        pattern: str = "*.py",
        recursive: bool = True,
        default_level: int | Level = Level.L4,
    ) -> None:
        if isinstance(paths, (str, Path)):
            paths = [paths]
        self.paths = [Path(p) for p in paths]
        self.levels = levels
        self.pattern = pattern
        self.recursive = recursive
        self.default_level = Level.parse(default_level)

    def iter_files(self) -> Iterator[Path]:
        """Yield every submission file once, in a stable order.

        Returns:
            - The submission paths.
        """
        seen: set[Path] = set()
        for path in self.paths:
            if path.is_dir():
                if self.recursive:
                    candidates = list(path.rglob(self.pattern))
                else:
                    candidates = list(path.glob(self.pattern))
            else:
                candidates = [path]
            for candidate in sorted(candidates):
                if candidate.is_file() and candidate not in seen:
                    seen.add(candidate)
                    yield candidate

    def level_for(self, path: Path) -> Level:
        """Resolve the exercise level for one submission.

        Parameters:
            - path: The submission's path.

        Returns:
            - The level from the mapping or callable, or the default.
        """
        if isinstance(self.levels, (int, Level)):
            return Level.parse(self.levels)
        if callable(self.levels):
            return Level.parse(self.levels(path))
        for key in (str(path), path.name, path.stem, path.parent.name):
            if key in self.levels:
                return Level.parse(self.levels[key])
        return self.default_level

    def run(
        self,
        *,
        output: str | Path | None = None,
        limit: int | None = None,
    ) -> Iterator[ScanMultipleRecord]:
        """Scan the files, optionally writing JSON lines to output.

        Parameters:
            - output: A file to append JSON lines to, or None.
            - limit: Stop after this many submissions, or None for all.

        Returns:
            - The scan-multiple records, streamed as they are produced.
        """
        sink = None
        if output:
            sink = Path(output).open("w", encoding="utf-8")
        count = 0
        try:
            batch: list[tuple[Path, Level]] = []
            for path in self.iter_files():
                if limit is not None and count >= limit:
                    break
                batch.append((path, self.level_for(path)))
                count += 1
                if len(batch) >= _BATCH_SIZE:
                    yield from self._emit_batch(batch, sink)
                    batch = []
            if batch:
                yield from self._emit_batch(batch, sink)
        finally:
            if sink is not None:
                sink.close()

    def _emit_batch(
        self, batch: list[tuple[Path, Level]], sink: Any
    ) -> Iterator[ScanMultipleRecord]:
        """Scan one batch, grouping files by level for a single scan.

        Parameters:
            - batch: The files and their levels.
            - sink: An open JSON-lines file, or None.

        Returns:
            - The records for this batch.
        """
        by_level: dict[Level, list[Path]] = {}
        for path, level in batch:
            by_level.setdefault(level, []).append(path)
        for level, paths in by_level.items():
            try:
                reports = scan_paths(paths, level=level)
            except Exception as exc:  # noqa: BLE001 - keep batch failures isolated
                for path in paths:
                    record = ScanMultipleRecord.failure(str(path), level, str(exc))
                    _write(sink, record)
                    yield record
                continue
            for path in paths:
                key = str(path)
                report = reports.get(key)
                if report is None:
                    record = ScanMultipleRecord.failure(
                        key, level, "no report produced for submission"
                    )
                else:
                    record = ScanMultipleRecord.from_report(key, report)
                _write(sink, record)
                yield record


def _write(sink: Any, record: ScanMultipleRecord) -> None:
    """Write one record as a JSON line when a sink is open.

    Parameters:
        - sink: An open JSON-lines file, or None.
        - record: The record to write.
    """
    if sink is not None:
        sink.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        sink.flush()
