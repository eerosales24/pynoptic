"""Shared fixtures for the pynoptic test suite."""

from __future__ import annotations

import pytest

from pynoptic.static import semgrep_runner


@pytest.fixture(scope="session")
def semgrep() -> None:
    """Skip the test when the Semgrep CLI cannot be located.

    Scanning through the engine shells out to Semgrep, which costs seconds
    rather than milliseconds, so tests that need the full pipeline request
    this fixture and everything else drives the AST engine directly.
    """
    try:
        semgrep_runner._executable()
    except semgrep_runner.SemgrepError:
        pytest.skip("semgrep executable not available")
