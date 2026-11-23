"""The child process that executes a submission.

Run as ``python -m pynoptic.sandbox.child <plan.json>``. Everything it needs
arrives in that one file so no path has to survive the command line.

The order of the steps is the whole design:

1. Apply OS limits, before any of the submission's code can allocate.
2. Import the analysis machinery, so arming the guard cannot block it.
3. Arm the audit hook.
4. Run the entry point.
5. Write the outcome where the parent can read it, whatever happened.

Step 5 matters as much as the rest: a submission that catches
``PolicyViolation`` must not be able to make the violation disappear, so the
record is written from here and not from the exception handler the submission
could reach.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .guard import PolicyViolation, arm
from .limits import apply
from .policy import ExecutionPolicy

__all__ = ["OUTCOME_FILE", "main"]

#: Where the child records what happened, next to the analysis output.
OUTCOME_FILE = "pynoptic_sandbox.json"


def _write_outcome(workdir: Path, payload: dict[str, Any]) -> None:
    """Record the run's outcome for the parent.

    Parameters:
        - workdir: The run's working directory.
        - payload: What to record.
    """
    try:
        (workdir / OUTCOME_FILE).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:  # pragma: no cover - the parent falls back to the exit code
        pass


def main(argv: list[str] | None = None) -> int:
    """Execute one submission under a policy.

    Parameters:
        - argv: The arguments to use; defaults to sys.argv[1:]. The single
          argument is a JSON plan with the entry, the analyses, the workdir
          and the policy.

    Returns:
        - 0 when the run completed, 3 when the policy stopped it, 1 when the
          submission raised something else.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:  # pragma: no cover - the parent always passes one
        print("usage: python -m pynoptic.sandbox.child <plan.json>", file=sys.stderr)
        return 2

    plan = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    entry = Path(plan["entry"])
    workdir = Path(plan["workdir"])
    # A plan may name one analysis or several. Both spellings are accepted
    # because the single-analysis plan predates the metrics subsystem and a
    # plan file on disk outlives the process that wrote it.
    analyses: list[str] = list(plan.get("analyses") or ())
    if not analyses and plan.get("analysis"):
        analyses = [str(plan["analysis"])]
    policy = ExecutionPolicy.from_json(json.dumps(plan["policy"]))
    local_modules = frozenset(plan.get("local_modules") or ())

    notes: list[str] = apply(policy)
    # The privilege check is the parent's job: asking Windows whether we
    # are Administrator means importing ctypes, and a module imported
    # here is one the guard can never see again.

    # Imported here, before the guard is armed, so that arming cannot block
    # the machinery that does the work.
    from dynapyt.run_analysis import run_analysis

    violations: list[str] = []
    arm(policy, workdir, violations, local_modules)

    status = "ok"
    error = ""
    try:
        run_analysis(entry=str(entry), analyses=analyses, output_dir=str(workdir))
    except PolicyViolation as exc:
        status = "blocked"
        error = str(exc)
    except BaseException as exc:  # noqa: BLE001 - a submission can raise anything
        status = "error"
        error = f"{type(exc).__name__}: {exc}"

    # A submission that swallowed the violation does not get to hide it.
    if violations and status == "ok":
        status = "blocked"
        error = f"policy violated and suppressed by the submission: {violations[0]}"

    _write_outcome(
        workdir,
        {
            "status": status,
            "error": error,
            "violations": violations,
            "notes": notes,
        },
    )
    if status == "blocked":
        return 3
    if status == "error":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
