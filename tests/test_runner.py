"""The dynamic runner: instrumentation, execution budget and event recovery.

These tests instrument and execute code, so they cost seconds. They are the
only place the candidate-to-restriction resolution is exercised end to end.
"""

from __future__ import annotations

import time
from pathlib import Path

from pynoptic.dynamic.runner import DEFAULT_TIMEOUT, _read_events, run_dynamic


def _write(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return path


def test_missing_submission_is_reported_not_raised() -> None:
    run = run_dynamic("does-not-exist.py")
    assert run.errors
    assert run.detections == []


def test_read_events_tolerates_an_empty_workdir(tmp_path: Path) -> None:
    assert _read_events(tmp_path) == []


def test_default_timeout_is_finite() -> None:
    assert 0 < DEFAULT_TIMEOUT < 600


def test_runtime_type_resolves_the_static_candidate(tmp_path: Path) -> None:
    """`remove` is a list and a set method; only execution says which."""
    _write(
        tmp_path,
        "submission.py",
        "def f(xs: list) -> int:\n    xs.remove(1)\n    return xs.count(2)\n",
    )
    driver = _write(
        tmp_path,
        "driver.py",
        "from submission import f\n\nf([1, 2, 2])\n",
    )

    run = run_dynamic(tmp_path / "submission.py", driver=driver)

    assert run.errors == []
    resolved = {(d.restriction_id, d.location.line) for d in run.detections}
    assert ("R55", 2) in resolved
    assert all(d.detector == "dynapyt" and d.resolved for d in run.detections)


def test_a_submission_that_never_terminates_is_killed(tmp_path: Path) -> None:
    """Before the budget existed this hung the host process forever."""
    _write(
        tmp_path,
        "submission.py",
        "def spin(n: int) -> int:\n    i = 0\n    while i < n:\n        pass\n    return i\n",
    )
    driver = _write(tmp_path, "driver.py", "from submission import spin\n\nspin(1)\n")

    started = time.perf_counter()
    run = run_dynamic(tmp_path / "submission.py", driver=driver, timeout=2.0)
    elapsed = time.perf_counter() - started

    assert any("timed out" in message for message in run.errors)
    assert elapsed < 30
    assert run.detections == []


def test_the_original_submission_is_never_modified(tmp_path: Path) -> None:
    source = "def f(xs: list) -> int:\n    return xs.count(2)\n"
    submission = _write(tmp_path, "submission.py", source)
    driver = _write(tmp_path, "driver.py", "from submission import f\n\nf([2])\n")

    run_dynamic(submission, driver=driver)

    assert submission.read_text(encoding="utf-8") == source
