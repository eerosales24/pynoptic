"""One submission, both dimensions, in a form a person or a model can read.

``scan_file`` answers "which non-curricular constructs are here" and
``scan_metrics_file`` answers "which defects are here". A profile runs both
over one submission, at one level, with one execution, and reports what
fired and where.

The output is built for two readers at once, which is a constraint worth
stating because it shapes every field:

- **A person** wants the short list. What fired, on which line, and why that
  line. Not the fourteen metrics that came back clean, and not a table of
  everything the catalog contains.
- **A model** calling this as a tool wants the same facts without having to
  parse prose or count anything. So the JSON carries the counts already
  totalled, the source text of every cited line, and — the part that matters
  most — three separate lists for *fired*, *clean* and *not checked*.

That last distinction is the whole reason this module exists. A metric that
never executed is not a metric that passed, and a format that lets the two
blur together will be read as a clean bill of health for code nobody ran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dynamic.runner import DynamicRun
from .engine import _collect, _resolve_detections, scan_source, to_findings
from .metrics import Judgement, MetricFinding, MetricReport, scan_metrics
from .metrics.dynamic.observations import TraceEvent
from .metrics.models import Metric
from .models import Finding, Level, Report
from .sandbox import STRICT, ExecutionPolicy
from .sources import read_source
from .verdict import to_verdict

__all__ = ["Profile", "profile_source", "profile_file", "SCHEMA_VERSION"]

#: Bumped when the JSON shape changes in a way a consumer would notice.
#: A model told to read `metrics[].verdict` should fail loudly against a
#: format that renamed it, not silently find None.
SCHEMA_VERSION = "1.0"

#: What the four verdicts mean, shipped with every JSON payload. A model
#: reading this tool's output should not have to be told separately that
#: NO_APLICA is not a pass.
VERDICT_GLOSSARY = {
    "SI": "the defect is present",
    "NO": "the defect is absent",
    "NO_APLICA": "the construct this metric asks about does not exist here",
    "NO_DECIDIBLE": "the construct exists but nothing could decide it",
}


@dataclass
class Profile:
    """Everything one audit of one submission found."""

    path: str
    level: Level
    function: str = ""
    source: str = ""
    metrics: MetricReport | None = None
    ncc: Report | None = None
    #: Seconds the whole profile took, run included.
    elapsed: float = 0.0
    dynamic: str = "not run"
    notes: list[str] = field(default_factory=list)
    syntax_error: bool = False
    #: What the run did, in order, when a trace was asked for.
    trace: tuple[TraceEvent, ...] = ()
    trace_truncated: bool = False
    events_total: int = 0

    # -- the three lists ------------------------------------------------

    @property
    def fired(self) -> list[MetricFinding]:
        """Return the metrics that found something, worst anchored first."""
        if self.metrics is None:
            return []
        return sorted(
            (f for f in self.metrics.findings if f.verdict is Judgement.PRESENT),
            key=lambda f: (min((e.line for e in f.evidence), default=0), f.metric.id),
        )

    @property
    def clean(self) -> list[MetricFinding]:
        """Return the metrics that were checked and found nothing."""
        if self.metrics is None:
            return []
        return [
            f
            for f in self.metrics.findings
            if f.verdict is Judgement.ABSENT and f.resolved
        ]

    @property
    def unchecked(self) -> list[MetricFinding]:
        """Return the metrics nothing settled.

        Kept apart from `clean` deliberately. These are the metrics whose
        construct is present and whose answer needed a run that did not
        reach it, which is the opposite of a pass.
        """
        if self.metrics is None:
            return []
        return [f for f in self.metrics.findings if not f.resolved]

    @property
    def not_applicable(self) -> list[MetricFinding]:
        """Return the metrics whose construct is not in this submission."""
        if self.metrics is None:
            return []
        return [f for f in self.metrics.findings if f.verdict is Judgement.NOT_APPLICABLE]

    @property
    def violations(self) -> list[Finding]:
        """Return the NCC findings that count as violations."""
        if self.ncc is None:
            return []
        return sorted(self.ncc.findings, key=lambda f: (f.location.line or 0, f.restriction.id))

    def line(self, number: int) -> str:
        """Return one source line, stripped.

        Parameters:
            - number: A one-indexed line number.

        Returns:
            - The line's text, or "" when out of range.
        """
        lines = self.source.splitlines()
        if 1 <= number <= len(lines):
            return lines[number - 1].strip()
        return ""

    # -- output ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON a tool consumer reads.

        Returns:
            - A payload whose counts are already totalled and whose every
              cited line carries its own source text.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "file": self.path,
            "function": self.function,
            "level": int(self.level),
            "syntax_error": self.syntax_error,
            "execution": self.dynamic,
            "elapsed_seconds": round(self.elapsed, 3),
            "summary": {
                "metrics_fired": len(self.fired),
                "metrics_clean": len(self.clean),
                "metrics_unchecked": len(self.unchecked),
                "metrics_not_applicable": len(self.not_applicable),
                "ncc_violations": len(self.violations),
                "verdict_glossary": VERDICT_GLOSSARY,
            },
            "fired": [self._metric_dict(f) for f in self.fired],
            "unchecked": [self._metric_dict(f) for f in self.unchecked],
            "clean": [f.metric.id for f in self.clean],
            "not_applicable": [f.metric.id for f in self.not_applicable],
            "ncc": [self._ncc_dict(f) for f in self.violations],
            "trace": {
                "events_recorded": len(self.trace),
                "events_total": self.events_total,
                "truncated": self.trace_truncated,
                "events": [
                    {
                        "seq": e.seq,
                        "hook": e.hook,
                        "line": e.line,
                        "code": self.line(e.line),
                        "detail": e.detail,
                    }
                    for e in self.trace
                ],
            },
            "notes": self.notes,
            "diagnostics": dict(self.metrics.diagnostics) if self.metrics else {},
        }

    def _metric_dict(self, finding: MetricFinding) -> dict[str, Any]:
        """Return one metric finding with its lines spelled out.

        Parameters:
            - finding: The finding to render.

        Returns:
            - The JSON shape, with the source text of each cited line.
        """
        metric: Metric = finding.metric
        return {
            "id": metric.id,
            "name": metric.name,
            "verdict": str(finding.verdict),
            "resolved": finding.resolved,
            "shape": str(metric.shape),
            "oracle": str(metric.oracle),
            "decided_by": finding.detector,
            "runtime": finding.data.get("runtime", ""),
            "lines": sorted({e.line for e in finding.evidence}),
            "evidence": [
                {
                    "line": e.line,
                    "code": self.line(e.line),
                    "element": e.element,
                    "why": e.detail,
                }
                for e in finding.evidence
            ],
            "data": {k: v for k, v in finding.data.items() if k != "runtime"},
        }

    def _ncc_dict(self, finding: Finding) -> dict[str, Any]:
        """Return one NCC finding.

        Parameters:
            - finding: The finding to render.

        Returns:
            - The JSON shape, with the source text of the cited line.
        """
        line = finding.location.line or 0
        return {
            "id": finding.restriction.id,
            "restriction": finding.restriction.restriction,
            "kind": finding.kind.value,
            "scope_level": int(finding.restriction.scope),
            "line": line,
            "code": self.line(line),
            "resolved": finding.resolved,
            "decided_by": finding.detector,
        }

    def render(self, *, width: int = 78) -> str:
        """Return the short human report.

        What fired and where, and nothing else at the top. The counts that
        close it are what tell a reader how much of the catalog was even
        applicable, so a short list is not mistaken for a clean submission.

        Parameters:
            - width: The column the detail is wrapped to.

        Returns:
            - The report as text.
        """
        head = f"{self.path} · nivel {int(self.level)}"
        if self.function:
            head += f" · función {self.function}"
        out = [head, "=" * min(len(head), width)]

        if self.syntax_error:
            reason = ""
            if self.metrics is not None:
                reason = str(self.metrics.diagnostics.get("reason", ""))
            out.append(f"No se evaluó: {reason or 'la fuente no compila'}")
            return "\n".join(out)

        fired = self.fired
        applicable = len(self.metrics.findings) if self.metrics else 0
        out.append("")
        out.append(f"MÉTRICAS ({len(fired)} de {applicable})")
        if not fired:
            out.append("  — ninguna métrica se activó")
        for finding in fired:
            lines = ", ".join(str(line) for line in sorted({e.line for e in finding.evidence}))
            where = f"línea {lines}" if lines else "—"
            out.append(f"  {finding.metric.id}  {finding.metric.name:<34} {where}")
            runtime = str(finding.data.get("runtime", ""))
            if runtime:
                out.append(f"        {runtime}")
            for evidence in finding.evidence[:4]:
                code = self.line(evidence.line)
                if code:
                    out.append(f"        {evidence.line:>4} | {code[: width - 16]}")
                out.append(f"             → {evidence.detail}")

        violations = self.violations
        out.append("")
        out.append(f"NCC ({len(violations)})")
        if not violations:
            out.append("  — ningún constructo fuera del nivel")
        for violation in violations:
            mark = " " if violation.resolved else "?"
            out.append(
                f"  {mark}{violation.restriction.id:<5} {violation.kind.value:<14} "
                f"línea {violation.location.line}: "
                f"{violation.restriction.restriction[: width - 34]}"
            )

        unchecked = self.unchecked
        if unchecked:
            out.append("")
            out.append(f"SIN RESOLVER ({len(unchecked)}) — no son veredictos")
            for finding in unchecked:
                why = str(finding.data.get("runtime", "no se ejecutó"))
                out.append(f"  {finding.metric.id}  {finding.metric.name:<34} {why}")

        if self.trace:
            out.append("")
            shown = len(self.trace)
            header = f"TRAZA ({shown} de {self.events_total} eventos"
            out.append(header + (", truncada)" if self.trace_truncated else ")"))
            for event in self.trace:
                out.append(
                    f"  {event.seq:>5} {event.hook:<9} "
                    f"L{event.line:<4} {event.detail[: width - 24]}"
                )

        out.append("")
        out.append(
            f"{len(self.clean)} limpias · {len(self.not_applicable)} no aplican · "
            f"ejecución: {self.dynamic} · {self.elapsed:.2f}s"
        )
        for note in self.notes:
            out.append(f"  nota: {note}")
        return "\n".join(out)


def profile_source(
    source: str,
    *,
    level: Level | int | str,
    function: str | None = None,
    path: str = "<source>",
    dynamic: bool = False,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
    ncc: bool = True,
    run_file: Path | None = None,
    trace: bool = False,
) -> Profile:
    """Audit one submission held in memory.

    Parameters:
        - source: The submission's code.
        - level: The exercise's level.
        - function: The function to audit, when the exercise fixes one.
        - path: A display name for the report.
        - dynamic: Whether to run the submission. Requires a file, so the
          source is written to a temporary one.
        - driver: A script that exercises the submission.
        - driver_code: Driver source used instead of a driver file.
        - policy: The limits the run happens under.
        - timeout: Overrides the policy's timeout.
        - ncc: Whether to run the restriction catalog as well. Turning it
          off skips Semgrep, which is most of the static cost.
        - run_file: The file the dynamic run should use. A driver written
          by hand imports the submission by its real module name, so a
          caller holding the real file passes it here rather than letting
          the source be written to a temporary one under another name.

    Returns:
        - The profile.
    """
    started = time.perf_counter()
    profile = Profile(path=path, level=Level.parse(level), source=source)

    metrics = scan_metrics(source, level=level, filename=path, function=function)
    profile.metrics = metrics
    profile.function = str(metrics.diagnostics.get("function", ""))
    if metrics.syntax_error:
        profile.syntax_error = True
        profile.elapsed = time.perf_counter() - started
        return profile

    run: DynamicRun | None = None
    if dynamic:
        import tempfile

        from .metrics.dynamic import observe_run, resolve_report

        # One execution, both dimensions. Instrumenting a submission costs
        # more than running it, and running a student's code twice to ask
        # two questions about the same run is the kind of waste that turns
        # a corpus into a weekend.
        if run_file is not None:
            observations, run = observe_run(
                run_file,
                driver=driver,
                driver_code=driver_code,
                policy=policy,
                timeout=timeout,
                with_ncc=ncc,
                trace=trace,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="pynoptic-profile-") as tmp:
                target = Path(tmp) / "submission.py"
                target.write_text(source, encoding="utf-8")
                observations, run = observe_run(
                    target,
                    driver=driver,
                    driver_code=driver_code,
                    policy=policy,
                    timeout=timeout,
                    with_ncc=ncc,
                    trace=trace,
                )
        profile.metrics = resolve_report(metrics, observations)
        profile.dynamic = str(profile.metrics.diagnostics.get("dynamic", "no observations"))
        profile.notes.extend(observations.errors)
        profile.trace = observations.trace
        profile.trace_truncated = observations.trace_truncated
        profile.events_total = observations.events_total

    if ncc:
        try:
            profile.ncc = _ncc_report(source, path, level, run)
        except Exception as exc:  # noqa: BLE001 - Semgrep absence must not sink it
            profile.notes.append(f"NCC no evaluado: {type(exc).__name__}: {exc}")

    profile.elapsed = time.perf_counter() - started
    return profile


def _ncc_report(
    source: str,
    path: str,
    level: Level | int | str,
    run: DynamicRun | None,
) -> Report:
    """Build the restriction report, folding in a run that already happened.

    Parameters:
        - source: The submission's code.
        - path: The label to report.
        - level: The exercise's level.
        - run: The execution the metric pass already paid for, when there
          was one. Its observations resolve the ambiguous candidates
          without a second run.

    Returns:
        - The NCC report.
    """
    parsed = Level.parse(level)
    if run is None:
        return scan_source(source, filename=path, level=parsed)

    detections, syntax_error, errors = _collect(source, path)
    detections = _resolve_detections(detections, run)
    report = Report(exercise_level=parsed, syntax_error=syntax_error)
    if errors:
        report.diagnostics["semgrep_errors"] = errors
    report.diagnostics["dynamic_observations"] = len(run.observed)
    report.extend(to_findings(detections, parsed))
    report.verdict = to_verdict(detections, parsed)
    return report


def profile_file(
    path: str | Path,
    *,
    level: Level | int | str,
    function: str | None = None,
    dynamic: bool = False,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
    ncc: bool = True,
    trace: bool = False,
) -> Profile:
    """Audit one submission on disk.

    Parameters:
        - path: The file to audit.
        - level: The exercise's level.
        - function: The function to audit.
        - dynamic: Whether to run the submission.
        - driver: A script that exercises the submission.
        - driver_code: Driver source used instead of a driver file.
        - policy: The limits the run happens under.
        - timeout: Overrides the policy's timeout.
        - ncc: Whether to run the restriction catalog as well.

    Returns:
        - The profile; syntax_error is set when the file cannot be read.
    """
    file_path = Path(path)
    try:
        source = read_source(file_path)
    except OSError as exc:
        profile = Profile(path=str(file_path), level=Level.parse(level), syntax_error=True)
        profile.metrics = MetricReport(exercise_level=Level.parse(level), syntax_error=True)
        profile.metrics.diagnostics["reason"] = f"no se pudo leer {file_path}: {exc}"
        return profile

    # A driver on disk refers to the submission by its real module name, so
    # the run uses the file where it is rather than a renamed copy.
    return profile_source(
        source,
        level=level,
        function=function,
        path=str(file_path),
        dynamic=dynamic,
        driver=driver,
        driver_code=driver_code,
        policy=policy,
        timeout=timeout,
        ncc=ncc,
        run_file=file_path,
        trace=trace,
    )
