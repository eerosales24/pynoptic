"""Static detection engines (Semgrep and Python ast).

This package initializer stays lightweight to avoid an import cycle with
:mod:`pynoptic.restrictions`. The Semgrep runner is imported explicitly by the
engine as pynoptic.static.semgrep_runner when it is needed.
"""

from .ast_engine import detect

__all__ = ["detect"]
