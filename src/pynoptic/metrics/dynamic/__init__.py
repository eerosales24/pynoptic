"""Runtime resolution for the metrics the tree cannot settle.

The entry point is `observe`, which runs a submission under the metric
analysis and hands back what it saw. `resolve_report` then applies those
observations to a static report.

The analysis class is named by string rather than imported here. DynaPyt
instruments a submission from the *names* of an analysis class's methods, so
the class has to be resolvable by path inside the child process, and
importing it in the parent would only pull libcst into a process that has no
use for it.
"""

from __future__ import annotations

from pathlib import Path

from ...dynamic.runner import ANALYSIS as NCC_ANALYSIS
from ...dynamic.runner import DynamicRun, run_dynamic
from ...sandbox import STRICT, ExecutionPolicy
from .analysis import METRIC_RESULTS_FILE
from .observations import RunObservations
from .resolve import RESOLVERS, resolve_report

__all__ = [
    "METRIC_ANALYSIS",
    "METRIC_RESULTS_FILE",
    "RESOLVERS",
    "RunObservations",
    "observe",
    "observe_run",
    "resolve_report",
]

#: The analysis the child installs for the metric dimension.
METRIC_ANALYSIS = "pynoptic.metrics.dynamic.analysis.MetricDynamicAnalysis"


def observe_run(
    submission: str | Path,
    *,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
    with_ncc: bool = False,
    trace: bool = False,
) -> tuple[RunObservations, DynamicRun]:
    """Run a submission once and hand back both dimensions' observations.

    Installing both analyses in one child is what lets a profile cost one
    execution rather than two. Instrumentation is the expensive half and it
    is shared; the two analyses then write separate summaries.

    Parameters:
        - submission: The file to run.
        - driver: A script that imports the submission and exercises it.
        - driver_code: Driver source used instead of a driver file.
        - policy: The limits to run under.
        - timeout: Overrides the policy's timeout.
        - with_ncc: Also install the NCC analysis, so the same execution
          resolves the restriction candidates.
        - trace: Record an ordered log of what the run did. Off by default:
          it costs a repr per event and is for reading one submission, not
          for sweeping a corpus.

    Returns:
        - The metric observations, and the raw run the NCC side reads.
    """
    # DynaPyt builds an analysis from a `path;key=value` line and passes the
    # pairs to the constructor, so this is how configuration reaches a class
    # instantiated inside the child process.
    #
    # The looping budget is derived from the timeout rather than fixed: the
    # analysis has to stop the submission *before* the parent kills it, or
    # the summary is never written and a non-terminating loop goes
    # unreported. Three quarters leaves room for instrumentation, import and
    # the flush itself.
    limit = timeout if timeout is not None else policy.timeout
    budget = max(2.0, limit * 0.75)
    settings = [f"budget_seconds={budget:g}"]
    if trace:
        settings.append("trace=1")
    analyses = [";".join([METRIC_ANALYSIS, *settings])]
    if with_ncc:
        analyses.append(NCC_ANALYSIS)
    run = run_dynamic(
        submission,
        driver=driver,
        driver_code=driver_code,
        policy=policy,
        timeout=timeout,
        analyses=analyses,
        collect=(METRIC_RESULTS_FILE,),
    )
    observations = RunObservations.from_summary(
        run.payloads.get(METRIC_RESULTS_FILE),
        errors=tuple(run.errors),
        refused=run.refused,
    )
    return observations, run


def observe(
    submission: str | Path,
    *,
    driver: str | Path | None = None,
    driver_code: str | None = None,
    policy: ExecutionPolicy = STRICT,
    timeout: float | None = None,
    with_ncc: bool = False,
) -> RunObservations:
    """Run a submission under the metric analysis and report what it did.

    Parameters:
        - submission: The file to run.
        - driver: A script that imports the submission and exercises it.
        - driver_code: Driver source used instead of a driver file.
        - policy: The limits to run under.
        - timeout: Overrides the policy's timeout.
        - with_ncc: Also install the NCC analysis, so one execution serves
          both dimensions. It costs more instrumentation, so it is off by
          default and the profile command turns it on.

    Returns:
        - The observations; `executed` is False when nothing ran.
    """
    observations, _run = observe_run(
        submission,
        driver=driver,
        driver_code=driver_code,
        policy=policy,
        timeout=timeout,
        with_ncc=with_ncc,
    )
    return observations
