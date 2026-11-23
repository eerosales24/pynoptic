"""The package's own metadata: the version, and where it comes from.

The version used to be written twice — once in `pyproject.toml` and once as a
literal in `pynoptic/__init__.py` — while the CLI read only the second. Bump
one and forget the other and you ship a distribution whose metadata says one
version and whose `--version` says another. It is now read from the installed
distribution, and these tests are what keep the fallback from going stale.
"""

from __future__ import annotations

import re
from importlib.metadata import version

import pynoptic


def test_version_matches_the_installed_distribution() -> None:
    assert pynoptic.__version__ == version("pynoptic")


def test_version_is_a_release_number() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", pynoptic.__version__)


def test_the_cli_reports_the_same_version(capsys) -> None:  # type: ignore[no-untyped-def]
    """`--version` exits 0 after printing; argparse raises SystemExit."""
    from pynoptic.cli import main

    try:
        main(["--version"])
    except SystemExit as exit_code:
        assert exit_code.code == 0
    assert capsys.readouterr().out.strip() == f"pynoptic {pynoptic.__version__}"
