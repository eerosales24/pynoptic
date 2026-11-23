"""The boundary around executing someone else's code.

Four layers, weakest first:

1. ``screen`` refuses a submission whose source already shows a problem,
   before a process is started.
2. ``limits`` applies OS resource limits in the child. POSIX only.
3. ``guard`` installs an audit hook that sees imports, spawns, sockets,
   native loads and writes, and cannot be uninstalled.
4. The parent kills the child on a timeout.

**None of this is a sandbox**, and ``policy`` says so at length. Run the tool
inside a real boundary — a container, an unprivileged account, nsjail — and
treat these as the layer that catches the ordinary cases legibly.
"""

from __future__ import annotations

from .child import OUTCOME_FILE
from .guard import PolicyViolation
from .policy import CS1_IMPORTS, PERMISSIVE, STRICT, ExecutionPolicy
from .screen import ScreenResult, screen_source

__all__ = [
    "CS1_IMPORTS",
    "ExecutionPolicy",
    "OUTCOME_FILE",
    "PERMISSIVE",
    "PolicyViolation",
    "STRICT",
    "ScreenResult",
    "screen_source",
]
