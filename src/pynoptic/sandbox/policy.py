"""What a submission is allowed to do while it runs.

Read this first, because the rest of the package is easy to oversell.

**This is not a sandbox.** It is defence in depth inside the interpreter, and
a determined attacker who already has code execution can work around guards
written in Python. What it does buy is real: it stops the ordinary cases —
a submission that imports a package nobody vetted, that writes outside its
own directory, that opens a socket, that forks, that never terminates — and
it turns each of those from a silent event into a refusal you can read.

For an actual boundary, run the whole thing inside one: a container, a
separate unprivileged account, nsjail, seccomp. The policy below is what you
get on top of that, not instead of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "ALWAYS_ALLOWED_PREFIXES",
    "CS1_IMPORTS",
    "ExecutionPolicy",
    "PERMISSIVE",
    "STRICT",
]

#: Standard-library modules an introductory submission has a reason to
#: import. Anything outside this list is refused by default, which is the
#: point: a CS1 answer that reaches for a package nobody vetted is worth
#: stopping to look at, whatever its intent.
CS1_IMPORTS: frozenset[str] = frozenset(
    {
        "math",
        "random",
        "string",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "operator",
        "re",
        "copy",
        "decimal",
        "fractions",
        "statistics",
        "typing",
        "abc",
        "enum",
        "dataclasses",
        "json",
        "unicodedata",
        "textwrap",
        "heapq",
        "bisect",
        "array",
    }
)

#: The harness's own machinery. A submission cannot reach these without
#: importing them, and blocking them would stop the analysis from running at
#: all, so they are allowed unconditionally.
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = ("dynapyt", "libcst", "pynoptic")

#: Private C accelerators the standard library pulls in on its own. `str.format`
#: reaches for `_string`, `collections` for `_collections`, and a submission
#: never asks for them by name. Blocking them breaks ordinary code, so they are
#: allowed — except for the handful below, which are the C half of a module
#: that is itself forbidden and would otherwise be a way around the list.
PRIVATE_DENIED: frozenset[str] = frozenset(
    {
        "_ctypes",
        "_socket",
        "_ssl",
        "_posixsubprocess",
        "_winapi",
        "_multiprocessing",
        "_pickle",
        "_overlapped",
        "_asyncio",
    }
)


#: Modules that are never a CS1 answer, whatever the allowlist says, and
#: whatever is already loaded. Keeping them apart from the allowlist means a
#: course that widens the list for pandas cannot admit ctypes by accident,
#: and the "already imported" shortcut in the guard cannot whitewash one that
#: the harness itself pulled in.
NEVER_ALLOWED: frozenset[str] = frozenset(
    {
        "ctypes",
        "subprocess",
        "socket",
        "shutil",
        "pty",
        "multiprocessing",
        "pickle",
        "marshal",
        "importlib",
        "runpy",
        "builtins",
        "gc",
        "inspect",
        "signal",
        "mmap",
        "fcntl",
        "winreg",
        "msvcrt",
        "webbrowser",
        "tempfile",
    }
)


def is_private_accelerator(module: str) -> bool:
    """Report whether a module is an implicit private helper.

    Parameters:
        - module: A top-level module name.

    Returns:
        - True when the name is underscore-prefixed and not on the deny list.
    """
    return module.startswith("_") and module not in PRIVATE_DENIED


@dataclass(frozen=True)
class ExecutionPolicy:
    """The limits applied to one run of a submission."""

    #: Seconds before the child process is killed. The only limit that holds
    #: on every platform.
    timeout: float = 30.0
    #: Address-space ceiling. POSIX only; Windows has no equivalent here and
    #: reports the gap rather than pretending.
    max_memory_mb: int | None = 512
    #: Extra processes the submission may create. 0 blocks fork bombs.
    #: POSIX only.
    max_processes: int | None = 0
    #: Largest file the submission may write, in megabytes. POSIX only.
    max_file_size_mb: int | None = 8
    #: Top-level module names the submission may import, beyond the
    #: machinery prefixes. None lifts the restriction entirely, which is
    #: not the same as an empty set: that one allows nothing.
    allowed_imports: frozenset[str] | None = field(default_factory=lambda: CS1_IMPORTS)
    allow_network: bool = False
    allow_subprocess: bool = False
    #: Whether the submission may write outside its working directory. It can
    #: always write inside it: that directory is temporary and discarded.
    allow_file_writes: bool = False
    #: Whether to refuse a submission whose source already shows a problem,
    #: before running a single line of it.
    screen: bool = True

    def to_json(self) -> str:
        """Serialise the policy for the child process.

        Returns:
            - A JSON object the child can rebuild from.
        """
        return json.dumps(
            {
                "timeout": self.timeout,
                "max_memory_mb": self.max_memory_mb,
                "max_processes": self.max_processes,
                "max_file_size_mb": self.max_file_size_mb,
                "allowed_imports": (
                    None if self.allowed_imports is None else sorted(self.allowed_imports)
                ),
                "allow_network": self.allow_network,
                "allow_subprocess": self.allow_subprocess,
                "allow_file_writes": self.allow_file_writes,
                "screen": self.screen,
            }
        )

    @classmethod
    def from_json(cls, payload: str) -> ExecutionPolicy:
        """Rebuild a policy from its JSON form.

        Parameters:
            - payload: The text produced by to_json.

        Returns:
            - The policy.
        """
        raw: dict[str, Any] = json.loads(payload)
        return cls(
            timeout=float(raw["timeout"]),
            max_memory_mb=raw["max_memory_mb"],
            max_processes=raw["max_processes"],
            max_file_size_mb=raw["max_file_size_mb"],
            allowed_imports=(
                None if raw["allowed_imports"] is None else frozenset(raw["allowed_imports"])
            ),
            allow_network=bool(raw["allow_network"]),
            allow_subprocess=bool(raw["allow_subprocess"]),
            allow_file_writes=bool(raw["allow_file_writes"]),
            screen=bool(raw["screen"]),
        )

    def allowing(self, *modules: str) -> ExecutionPolicy:
        """Return a copy that also permits these imports.

        Courses that teach `pandas` or `numpy` widen the list here rather
        than editing the default, so the default stays the strict one.

        Parameters:
            - modules: Top-level module names to add.

        Returns:
            - A new policy.
        """
        if self.allowed_imports is None:
            return self
        return replace(self, allowed_imports=self.allowed_imports | frozenset(modules))


#: The default: nothing beyond the CS1 subset, no network, no subprocesses,
#: no writes outside the working directory.
STRICT = ExecutionPolicy()

#: For trusted code under your own control. Still bounded in time, because an
#: endless loop is a bug long before it is an attack.
PERMISSIVE = ExecutionPolicy(
    max_memory_mb=None,
    max_processes=None,
    max_file_size_mb=None,
    allowed_imports=None,
    allow_network=True,
    allow_subprocess=True,
    allow_file_writes=True,
    screen=False,
)
