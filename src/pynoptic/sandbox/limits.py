"""Operating-system limits, applied in the child before anything runs.

These are the only limits here the interpreter cannot talk its way out of,
and they exist on POSIX alone. Windows has no ``resource`` module; its
equivalent is a Job Object, which needs a pile of ``ctypes`` that would be
its own source of bugs. So on Windows the memory, process and file-size
limits are simply **not enforced**, and ``apply`` says so in its return value
rather than letting a caller believe otherwise.

What still holds on every platform is the timeout, which the parent enforces
by killing the child, and the audit hook.
"""

from __future__ import annotations

import sys

from .policy import ExecutionPolicy

__all__ = ["apply", "privilege_warning"]

MEGABYTE = 1024 * 1024


def apply(policy: ExecutionPolicy) -> list[str]:
    """Apply the policy's resource limits to the current process.

    Parameters:
        - policy: The limits to apply.

    Returns:
        - One note per limit that could not be applied. Empty means every
          requested limit is in force.
    """
    try:
        import resource
    except ImportError:
        wanted = [
            name
            for name, value in (
                ("memory", policy.max_memory_mb),
                ("process count", policy.max_processes),
                ("file size", policy.max_file_size_mb),
            )
            if value is not None
        ]
        if not wanted:
            return []
        return [
            "this platform has no resource limits; "
            f"{', '.join(wanted)} not enforced (timeout and audit hook still apply)"
        ]

    unmet: list[str] = []
    wanted_limits = [
        ("RLIMIT_AS", policy.max_memory_mb, MEGABYTE, "memory"),
        ("RLIMIT_NPROC", policy.max_processes, 1, "process count"),
        ("RLIMIT_FSIZE", policy.max_file_size_mb, MEGABYTE, "file size"),
    ]
    for attribute, value, scale, label in wanted_limits:
        if value is None:
            continue
        limit = getattr(resource, attribute, None)
        # Fetched by name because the resource module's surface differs
        # between platforms, and a type checker running on one of them
        # cannot see the other's.
        setrlimit = getattr(resource, "setrlimit", None)
        if limit is None or setrlimit is None:  # pragma: no cover - platform dependent
            unmet.append(f"{label} not enforced: {attribute} is unavailable")
            continue
        try:
            setrlimit(limit, (value * scale, value * scale))
        except (ValueError, OSError) as exc:  # pragma: no cover - platform dependent
            unmet.append(f"{label} not enforced: {exc}")
    return unmet


def privilege_warning() -> str | None:
    """Return a warning when the process runs with more rights than it needs.

    Executing someone else's code as root or as an Administrator removes the
    one protection that holds when every other layer fails: that the code
    cannot reach past the account running it.

    Returns:
        - A sentence to report, or None when the process is unprivileged.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.shell32.IsUserAnAdmin():
                return (
                    "running as Administrator: a submission that escapes the "
                    "guard inherits those rights"
                )
        except Exception:  # noqa: BLE001 - probing privileges must never fail a run
            return None
        return None

    import os

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return "running as root: a submission that escapes the guard inherits those rights"
    return None
