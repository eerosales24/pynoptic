"""The runtime guard, installed inside the child process.

An audit hook (PEP 578) sees events the source never shows: the import built
from a string, the socket opened by a library, the file written three frames
down. It cannot be removed once installed — there is no API to take one off —
which is what makes it worth more than a wrapper the submission could rebind.

What it still cannot do: stop code that never raises an audited event, and
stop a caller determined enough to reach the interpreter through C. Those are
the OS's job, and the reason ``policy`` opens by saying this is not a sandbox.

The hook is armed as late as possible, after the analysis machinery has
finished importing. Everything already in ``sys.modules`` at that moment is
treated as allowed, so arming cannot break the harness that armed it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from .policy import (
    ALWAYS_ALLOWED_PREFIXES,
    NEVER_ALLOWED,
    ExecutionPolicy,
    is_private_accelerator,
)

__all__ = ["PolicyViolation", "arm"]

#: Events that run a program. Never allowed unless the policy says so.
_SPAWN_EVENTS = frozenset(
    {
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "subprocess.Popen",
        "pty.spawn",
    }
)

#: Events that reach the network.
_NETWORK_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "urllib.Request",
        "ftplib.connect",
        "smtplib.connect",
        "http.client.connect",
    }
)

#: Events that load native code, which is how one leaves Python entirely.
_NATIVE_EVENTS = frozenset(
    {
        "ctypes.dlopen",
        "ctypes.dlsym",
        "ctypes.dlsym/handle",
        "ctypes.call_function",
        "ctypes.set_exception",
    }
)

#: Events that change the interpreter's own instrumentation. A submission
#: that installs a trace function can see, and skew, the analysis measuring
#: it.
#:
#: Deliberately absent, having been measured firing during ordinary work:
#: ``marshal.loads`` fires on every cached bytecode import, and
#: ``sys._getframe`` fires constantly in library code. Blocking either would
#: break the harness, not the submission.
_INTROSPECTION_EVENTS = frozenset(
    {
        "sys.settrace",
        "sys.setprofile",
        "pickle.find_class",
    }
)

#: Events that change the file system. Scoped to the working directory
#: rather than forbidden outright, because the instrumenter creates and
#: removes files of its own while it works.
_FILESYSTEM_EVENTS = frozenset(
    {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate"}
)

#: Modes that mean a write. Reading is always allowed: the submission has to
#: be able to read itself, and DynaPyt reads it too.
_WRITE_MODES = frozenset({"w", "a", "x", "+"})


class PolicyViolation(RuntimeError):
    """Raised inside the child when a submission breaks the policy.

    It inherits from RuntimeError rather than from anything the submission is
    likely to catch by name, but a bare ``except:`` will still swallow it.
    That is why the child also records the violation out of band, so a
    submission cannot hide one by catching it.
    """

    def __init__(self, event: str, detail: str = "") -> None:
        self.event = event
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"blocked by policy: {event}{suffix}")


def _module_of(name: str) -> str:
    """Return the top-level package of a module name.

    Parameters:
        - name: A module name, possibly dotted.

    Returns:
        - Its first component.
    """
    return name.split(".", 1)[0]


def arm(
    policy: ExecutionPolicy,
    workdir: Path,
    violations: list[str],
    local_modules: frozenset[str] = frozenset(),
) -> None:
    """Install the audit hook for the rest of this process's life.

    Call this after every import the harness needs, and immediately before
    handing control to the submission.

    Parameters:
        - policy: The limits to enforce.
        - workdir: The one directory the submission may write into.
        - violations: A list the hook appends to, so a violation is recorded
          even if the submission catches the exception.
        - local_modules: Module names the harness itself placed in the
          working directory. The driver has to import the submission, and
          its name is whatever the file was called.
    """
    # CPython raises the `import` event only when a module is really
    # loaded, never when it is served from sys.modules. So anything already
    # imported is invisible to the hook for the rest of the process, and a
    # forbidden module the harness pulled in would be handed to the
    # submission silently. Dropping them from the cache first means the next
    # import genuinely loads — and genuinely fires the event.
    for cached in [m for m in sys.modules if _module_of(m) in NEVER_ALLOWED]:
        sys.modules.pop(cached, None)

    preloaded = frozenset(sys.modules)
    # Two roots, not one. The instrumenter writes scratch files of its own
    # into the system temp directory, and the hook cannot tell its calls from
    # the submission's. Temp is volatile and already holds the working
    # directory, so admitting it costs little; what stays shut is everything
    # that lasts — the home directory, the project tree, system paths.
    roots = (workdir.resolve(), Path(tempfile.gettempdir()).resolve())

    def refuse(event: str, detail: str = "") -> None:
        violations.append(f"{event}: {detail}" if detail else event)
        raise PolicyViolation(event, detail)

    def hook(event: str, args: tuple[object, ...]) -> None:
        if event == "import":
            name = str(args[0]) if args else ""
            top = _module_of(name)
            # Checked before the shortcuts below: the harness imports ctypes
            # itself to ask whether it is running as Administrator, which
            # would otherwise leave ctypes on the preloaded list and hand the
            # submission the one module that leaves Python altogether.
            if top in NEVER_ALLOWED:
                refuse("import", f"{top} is never allowed")
                return
            if top in preloaded or name in preloaded:
                return
            if any(top == p for p in ALWAYS_ALLOWED_PREFIXES):
                return
            if is_private_accelerator(top):
                return
            if top in local_modules:
                return
            if policy.allowed_imports is not None and top not in policy.allowed_imports:
                refuse("import", top)
            return

        if event in _SPAWN_EVENTS and not policy.allow_subprocess:
            refuse(event)
        if event in _NETWORK_EVENTS and not policy.allow_network:
            refuse(event)
        if event in _NATIVE_EVENTS:
            refuse(event, "loading native code is never allowed")
        if event in _INTROSPECTION_EVENTS:
            refuse(event, "the submission may not instrument the interpreter")

        if policy.allow_file_writes:
            return

        if event == "open":
            mode = str(args[1]) if len(args) > 1 and args[1] else "r"
            if any(flag in mode for flag in _WRITE_MODES):
                _require_inside(event, args[:1])
        elif event in _FILESYSTEM_EVENTS:
            _require_inside(event, args)

    def _require_inside(event: str, candidates: tuple[object, ...]) -> None:
        """Refuse unless every path-looking argument is under the workdir.

        The hook cannot tell the submission's calls from the harness's, and
        the harness legitimately creates and removes files while it works.
        Scoping to the working directory is what separates the two without
        having to guess at the caller: that directory is temporary and
        discarded, so a submission writing there changes nothing that lasts.
        """
        for candidate in candidates:
            # A file descriptor has no path to check, and it can only have
            # come from an open() this hook already saw.
            if not isinstance(candidate, str | bytes | Path):
                continue
            try:
                resolved = Path(os.fsdecode(candidate)).resolve()
            except (OSError, ValueError):  # pragma: no cover - defensive
                refuse(event, "unresolvable path")
                return
            if not any(resolved.is_relative_to(r) for r in roots):
                refuse(event, f"touches {resolved}, outside the working directory")

    sys.addaudithook(hook)
