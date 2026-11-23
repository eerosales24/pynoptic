"""The execution boundary: what it stops, and what it admits it cannot.

These tests are adversarial on purpose. A guard that blocks nothing passes a
suite that only checks the happy path, so each case here is a thing a
submission could actually try.

The two layers are exercised separately. Running with ``screen=False``
isolates the audit hook, which matters because the static screen catches most
of these first and would otherwise hide a guard that does not work.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pynoptic.dynamic.runner import run_dynamic
from pynoptic.sandbox import PERMISSIVE, STRICT, ExecutionPolicy, screen_source
from pynoptic.sandbox.policy import NEVER_ALLOWED, is_private_accelerator

#: The hook alone, with the early screen switched off.
HOOK_ONLY = replace(STRICT, screen=False)


def _run(tmp_path: Path, source: str, policy: ExecutionPolicy):  # type: ignore[no-untyped-def]
    """Execute a submission under a policy and return the run."""
    (tmp_path / "sub.py").write_text(source, encoding="utf-8")
    (tmp_path / "drv.py").write_text(
        "import sub\ntry:\n    sub.f()\nexcept BaseException:\n    pass\n",
        encoding="utf-8",
    )
    return run_dynamic(tmp_path / "sub.py", driver=tmp_path / "drv.py", policy=policy)


# --------------------------------------------------------------- the screen

SCREENED = [
    ("a forbidden import", "import socket\ndef f():\n    return 1\n"),
    ("an unvetted package", "import requests\ndef f():\n    return 1\n"),
    ("turning data into code", "def f(s):\n    return eval(s)\n"),
    ("walking to the interpreter", "def f():\n    return ().__class__.__bases__\n"),
    ("an import built at run time", 'def f():\n    return __import__("os")\n'),
]


@pytest.mark.parametrize(("label", "source"), SCREENED, ids=[c[0] for c in SCREENED])
def test_the_screen_refuses_before_anything_runs(label: str, source: str) -> None:
    verdict = screen_source(source, STRICT)
    assert not verdict.allowed, label
    assert verdict.reasons


def test_the_screen_passes_ordinary_code() -> None:
    verdict = screen_source("import math\ndef f(x):\n    return math.sqrt(x)\n", STRICT)
    assert verdict.allowed
    assert verdict.reasons == ()


def test_unparsable_source_is_not_the_screen_s_problem() -> None:
    """It cannot run, and the static analysis already reported the error."""
    assert screen_source("def f(:\n", STRICT).allowed


def test_widening_the_allowlist_cannot_admit_the_forbidden() -> None:
    """A course that teaches pandas must not thereby admit ctypes."""
    widened = STRICT.allowing("pandas", "numpy", "ctypes")
    assert screen_source("import pandas\ndef f():\n    return 1\n", widened).allowed
    assert not screen_source("import ctypes\ndef f():\n    return 1\n", widened).allowed


def test_private_accelerators_are_not_mistaken_for_user_imports() -> None:
    """str.format reaches for _string; blocking it breaks ordinary code."""
    assert is_private_accelerator("_string")
    assert is_private_accelerator("_collections")
    assert not is_private_accelerator("_ctypes")


# ----------------------------------------------------------------- the hook

BLOCKED_AT_RUNTIME = [
    ("a forbidden import", "def f():\n    import socket\n    return 1\n"),
    ("native code", "def f():\n    import ctypes\n    return 1\n"),
    ("a deserialisation gadget", "def f():\n    import pickle\n    return 1\n"),
    (
        "an import the screen cannot see",
        'def f():\n    return __import__("".join(["soc", "ket"]))\n',
    ),
    (
        "a write outside the working directory",
        'import os\ndef f():\n    open(os.path.expanduser("~/pynoptic-probe.txt"), "w")\n',
    ),
    ("spawning a program", 'import os\ndef f():\n    os.system("echo hi")\n'),
]


@pytest.mark.parametrize(
    ("label", "source"), BLOCKED_AT_RUNTIME, ids=[c[0] for c in BLOCKED_AT_RUNTIME]
)
def test_the_hook_stops_it_even_with_the_screen_off(
    label: str, source: str, tmp_path: Path
) -> None:
    run = _run(tmp_path, source, HOOK_ONLY)
    assert run.refused, label
    assert run.violations, label


def test_a_swallowed_violation_is_still_recorded(tmp_path: Path) -> None:
    """`except BaseException: pass` must not make the violation disappear."""
    run = _run(
        tmp_path,
        "def f():\n    try:\n        import socket\n    except BaseException:\n"
        "        pass\n    return 1\n",
        HOOK_ONLY,
    )
    assert run.refused
    assert any("socket" in v for v in run.violations)


def test_ordinary_code_is_left_alone(tmp_path: Path) -> None:
    """The guard is worthless if it also stops the work."""
    run = _run(tmp_path, "import math\ndef f():\n    return math.sqrt(4)\n", HOOK_ONLY)
    assert not run.refused
    assert run.violations == []


def test_the_submission_may_write_inside_its_own_directory(tmp_path: Path) -> None:
    """That directory is temporary and discarded, so writing there is free."""
    run = _run(tmp_path, 'def f():\n    open("scratch.txt", "w").write("x")\n', HOOK_ONLY)
    assert not run.refused


def test_a_permissive_policy_really_is_permissive(tmp_path: Path) -> None:
    run = _run(tmp_path, "def f():\n    import json\n    return json\n", PERMISSIVE)
    assert not run.refused


# ------------------------------------------------------------- the contract


def test_the_policy_survives_a_round_trip() -> None:
    restored = ExecutionPolicy.from_json(STRICT.to_json())
    assert restored == STRICT


def test_an_unrestricted_import_list_is_not_an_empty_one() -> None:
    """None lifts the restriction; frozenset() would forbid everything."""
    assert PERMISSIVE.allowed_imports is None
    assert STRICT.allowed_imports is not None


def test_the_deny_list_covers_the_ways_out_of_python() -> None:
    for module in ("ctypes", "subprocess", "socket", "pickle", "importlib"):
        assert module in NEVER_ALLOWED, module


def test_a_missing_submission_is_reported_not_raised() -> None:
    run = run_dynamic("does-not-exist.py", policy=STRICT)
    assert run.errors
    assert not run.refused
