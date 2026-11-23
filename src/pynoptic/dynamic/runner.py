"""Run the DynaPyt analysis over a submission and collect its findings.

The submission runs in a child process under an ``ExecutionPolicy``: screened
before it starts, limited while it runs, and killed if it will not stop. See
``pynoptic.sandbox.policy`` for what that does and does not buy — in short,
it is defence in depth, not a boundary. Put the whole thing inside a real one.

The runner always works on a temporary copy and never modifies the original.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from pynoptic.models import Detection, Location
from pynoptic.sandbox import STRICT, ExecutionPolicy, screen_source
from pynoptic.sandbox.child import OUTCOME_FILE
from pynoptic.sandbox.limits import privilege_warning
from pynoptic.sources import read_source

ANALYSIS = "pynoptic.dynamic.analysis.NccDynamicAnalysis"
RESULTS_FILE = "pynoptic_dynamic.json"
PLAN_FILE = "pynoptic_plan.json"

#: The analyses a plain NCC run installs. Callers that want the quality
#: metrics as well pass their own list: instrumentation is derived from the
#: union of the analyses' method names, so an analysis left out of this list
#: is an analysis whose hooks are never woven into the submission.
DEFAULT_ANALYSES: tuple[str, ...] = (ANALYSIS,)

#: Seconds a submission may run before it is killed, when the policy does not
#: say otherwise. A pure-Python loop cannot be interrupted from another
#: thread and signal.alarm does not exist on Windows, so the parent kills the
#: child instead.
DEFAULT_TIMEOUT = STRICT.timeout


@dataclass
class DynamicRun:
    """Dynamic observations for one submission."""

    detections: list[Detection] = field(default_factory=list)
    observed: set[tuple[str, int]] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Policy violations the guard recorded, even ones the submission caught.
    violations: list[str] = field(default_factory=list)
    #: Limits the platform could not enforce, and privilege warnings.
    notes: list[str] = field(default_factory=list)
    #: True when the submission was refused before it ran.
    refused: bool = False
    #: Output files other analyses wrote, parsed, keyed by file name. The
    #: NCC analysis's own events stay in `events`; this is where a second
    #: analysis running in the same child puts its summary.
    payloads: dict[str, Any] = field(default_factory=dict)


def _purge_temp_modules() -> None:
    """Drop submission/driver modules cached by a previous dynamic run.

    Without this, a second run whose submission has the same module name
    would import the previous (already deleted) module from sys.modules.
    """
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if filename and "pynoptic-dynamic-" in filename:
            sys.modules.pop(name, None)


def _instrument(directory: Path, analyses: Sequence[str] = DEFAULT_ANALYSES) -> list[str]:
    """Instrument every Python file under directory in place.

    Parameters:
        - directory: The temporary directory holding the submission and driver.
        - analyses: The analyses whose hooks decide what gets woven in.

    Returns:
        - A list of human-readable error messages; empty on success.
    """
    from dynapyt.instrument.instrument import instrument_file
    from dynapyt.utils.hooks import get_hooks_from_analysis

    errors: list[str] = []
    hooks = get_hooks_from_analysis(list(analyses))
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
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
    analyses: Sequence[str] = DEFAULT_ANALYSES,
    collect: Sequence[str] = (),
) -> DynamicRun:
    """
    Instrument submission and execute it, collecting dynamic findings.

    Exactly one of driver (a path to a driver script) or driver_code
    (a driver source string) should exercise the submission. With neither, the
    submission module is executed as-is, which only records constructs reached
    at import time.

    The submission is screened before it runs, executed in a child process
    under the policy's limits, and killed if it outlives the timeout. That is
    defence in depth, not a boundary: see pynoptic.sandbox.policy.

    Parameters:
        - submission: Path to the student submission.
        - driver: Optional path to a script that calls the submission.
        - driver_code: Optional driver source used instead of driver.
        - policy: The limits to run under; STRICT by default.
        - timeout: Overrides the policy's timeout when given.
        - analyses: The DynaPyt analyses to install. The instrumentation is
          derived from their hooks, so this also decides what is woven in.
        - collect: Extra output file names to read back into `payloads`,
          for analyses that write their own summary.

    Returns:
        - The recorded detections, observed candidates, raw events, errors,
          policy violations and any limits the platform could not enforce.
    """
    submission_path = Path(submission)
    run = DynamicRun()
    if not submission_path.exists():
        run.errors.append(f"submission not found: {submission}")
        return run

    if timeout is not None:
        policy = replace(policy, timeout=timeout)

    if policy.screen:
        source = read_source(submission_path)
        verdict = screen_source(source, policy)
        if not verdict.allowed:
            run.refused = True
            run.errors.append("refused before execution: " + "; ".join(verdict.reasons))
            return run

    workdir = Path(tempfile.mkdtemp(prefix="pynoptic-dynamic-"))
    try:
        # Written, not copied. A submission carrying a byte-order mark is
        # valid UTF-8 and copies byte for byte, and then the instrumenter
        # fails on `﻿` before the first keyword. Decoding here means
        # the run sees the same text the static pass did.
        target = workdir / submission_path.name
        target.write_text(read_source(submission_path), encoding="utf-8")

        if driver is not None:
            driver_path = Path(driver)
            (workdir / driver_path.name).write_text(
                read_source(driver_path), encoding="utf-8"
            )
            entry = workdir / driver_path.name
        elif driver_code is not None:
            entry = workdir / "pynoptic_driver.py"
            entry.write_text(driver_code, encoding="utf-8")
        else:
            entry = target

        _purge_temp_modules()
        run.errors.extend(_instrument(workdir, analyses))

        warning = privilege_warning()
        if warning:
            run.notes.append(warning)
        run.errors.extend(_execute(entry, workdir, policy, analyses))
        _absorb_outcome(workdir, run)

        for name in collect:
            payload = _read_payload(workdir, name)
            if payload is not None:
                run.payloads[name] = payload

        events = _read_events(workdir)
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


#: Variables the child needs. Everything else in the parent's environment —
#: tokens, keys, the rest of PATH — is withheld, so a submission that reads
#: os.environ finds nothing worth having.
_KEPT_ENV = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "HOME",
    "USERPROFILE",
)


def _child_environment() -> dict[str, str]:
    """Build the minimal environment the child runs with.

    Returns:
        - The variables the interpreter needs, plus a PYTHONPATH that keeps
          the package importable from a source checkout.
    """
    environment = {k: v for k, v in os.environ.items() if k in _KEPT_ENV}
    environment["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p and p != ".")
    # Writing bytecode into the submission's directory is a write we would
    # rather not have to allow.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _execute(
    entry: Path,
    workdir: Path,
    policy: ExecutionPolicy,
    analyses: Sequence[str] = DEFAULT_ANALYSES,
) -> list[str]:
    """Run the instrumented entry point in a guarded child process.

    The child is what makes every limit enforceable. A pure-Python loop
    cannot be interrupted from another thread and signal.alarm does not exist
    on Windows, so the timeout has to be a kill from outside. Resource limits
    and the audit hook have to be installed before the submission starts,
    which means before this process would have had the chance.

    Parameters:
        - entry: The instrumented script to execute.
        - workdir: The directory DynaPyt writes its output to.
        - policy: The limits to run under.
        - analyses: The analyses the child installs.

    Returns:
        - Human-readable error messages; empty when the run was clean.

    Note:
        - On a timeout the analysis never reaches end_execution, so the events
          it had buffered are lost. The timeout is reported as an error and the
          caller sees an empty, not a partial, observation set.
    """
    plan = workdir / PLAN_FILE
    plan.write_text(
        json.dumps(
            {
                "entry": str(entry),
                "workdir": str(workdir),
                "analyses": list(analyses),
                # The driver imports the submission by whatever the file
                # is called, so the guard has to be told those names.
                "local_modules": sorted({p.stem for p in workdir.glob("*.py")}),
                "policy": json.loads(policy.to_json()),
            }
        ),
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pynoptic.sandbox.child", str(plan)],
            capture_output=True,
            text=True,
            timeout=policy.timeout,
            check=False,
            cwd=str(workdir),
            env=_child_environment(),
        )
    except subprocess.TimeoutExpired:
        return [f"dynamic execution timed out after {policy.timeout}s"]
    except OSError as exc:  # pragma: no cover - environment dependent
        return [f"dynamic execution could not start: {exc}"]

    # Exit code 3 is a policy refusal; the child already recorded the detail,
    # so _absorb_outcome reports it rather than this generic message.
    if completed.returncode not in (0, 3):
        tail = _last_error_line(completed.stderr or "") or f"exit {completed.returncode}"
        return [f"dynamic execution error: {tail}"]
    return []


def _last_error_line(stderr: str) -> str:
    """Return the last line of stderr that is an error rather than a warning.

    Running the child with ``-m`` makes runpy emit a RuntimeWarning about
    the package already being in sys.modules, and it arrives *after* the
    traceback. Taking the literal last line would report that warning as
    the cause of every failed run and bury the real one.

    Parameters:
        - stderr: Everything the child wrote to stderr.

    Returns:
        - The most informative line, or "" when there is nothing to report.
    """
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    for line in reversed(lines):
        if "Warning:" in line or line.startswith("warnings.warn"):
            continue
        return line
    return lines[-1] if lines else ""


def _absorb_outcome(workdir: Path, run: DynamicRun) -> None:
    """Fold the child's own record of the run into the result.

    The child writes this itself rather than letting the exception handler
    report it, so a submission that catches PolicyViolation cannot make the
    violation disappear.

    Parameters:
        - workdir: The run's working directory.
        - run: The result to update in place.
    """
    outcome = workdir / OUTCOME_FILE
    if not outcome.exists():
        return
    try:
        payload = json.loads(outcome.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
        return
    run.violations.extend(str(v) for v in payload.get("violations") or ())
    run.notes.extend(str(n) for n in payload.get("notes") or ())
    if payload.get("status") == "blocked":
        run.refused = True
        run.errors.append(f"stopped by policy: {payload.get('error', 'unknown violation')}")
    elif payload.get("status") == "error" and payload.get("error"):
        run.errors.append(f"dynamic execution error: {payload['error']}")


def _read_payload(workdir: Path, filename: str) -> Any | None:
    """Read one analysis output file from anywhere under the workdir.

    DynaPyt writes into <workdir>/dynapyt_output-<session>/, whose name is
    only known to the child, so the tree is searched rather than a path
    predicted.

    Parameters:
        - workdir: The temporary directory used for the run.
        - filename: The output file to look for.

    Returns:
        - The parsed JSON, or None when there is none to read.
    """
    for output in workdir.rglob(filename):
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _read_events(workdir: Path) -> list[dict[str, Any]]:
    """
    Read the analysis output.

    DynaPyt writes it under <workdir>/dynapyt_output-<session>/, so the whole
    tree is searched rather than one predicted path.

    Parameters:
        - workdir: The temporary directory used for the run.

    Returns:
        - The recorded events, or an empty list when no output was produced.
    """
    candidates: list[Path] = list(workdir.rglob(RESULTS_FILE))
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
