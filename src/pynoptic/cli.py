"""
CLI for pynoptic, with subcommands to inspect either catalog, scan one or many
submissions for non-curricular constructs, apply the quality metrics, and
build or score the prompts sent to an LLM judge.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .engine import scan_file
from .metrics import CATALOG as METRIC_CATALOG
from .metrics import get_metric, metrics_at, scan_metrics_file
from .metrics.llm import ExerciseSpec, InvalidAnswer, parse_answer, render_prompt
from .models import NccKind, Restriction
from .restrictions import restrictions, restrictions_at_least
from .scan_multiple import LevelResolver, ScanMultiple
from .sources import read_source

__all__ = ["main", "build_parser"]


def _kind_value(restriction: Restriction, level: int | None) -> str | None:
    """Return a restriction's NCC kind at a level, as a string.

    Parameters:
        - restriction: The restriction to classify.
        - level: The level to classify against, or None to skip.

    Returns:
        - The kind value, or None when there is no level or no NCC.
    """
    if level is None:
        return None
    kind = restriction.kind_at(level)
    if kind is None:
        return None
    return kind.value


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        - The configured parser with the catalog, scan and scan-multiple
          subcommands.
    """
    parser = argparse.ArgumentParser(prog="pynoptic", description=__doc__)
    parser.add_argument("--version", action="version", version=f"pynoptic {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    catalog = subparsers.add_parser("catalog", help="Inspect the restriction catalog")
    catalog.add_argument(
        "--level",
        type=int,
        choices=(1, 2, 3, 4),
        help="Only show restrictions that are NCCs at this level",
    )
    catalog.add_argument(
        "--kind",
        choices=[k.value for k in NccKind],
        help="Filter by NCC granularity (requires --level)",
    )
    catalog.add_argument("--json", action="store_true", help="Emit JSON")

    scan = subparsers.add_parser("scan", help="Audit a single submission")
    scan.add_argument("path", type=Path, help="Submission file")
    scan.add_argument("--level", type=int, choices=(1, 2, 3, 4), required=True)
    scan.add_argument("--dynamic", action="store_true", help="Enable DynaPyt resolution")
    scan.add_argument("--driver", type=Path, help="Driver script for dynamic mode")
    scan.add_argument("--json", action="store_true", help="Emit the report as JSON")

    scan_multiple = subparsers.add_parser(
        "scan-multiple", help="Scan multiple submissions, one record per file"
    )
    scan_multiple.add_argument("paths", nargs="+", type=Path)
    scan_multiple.add_argument(
        "--level",
        type=int,
        choices=(1, 2, 3, 4),
        default=4,
        help="Level applied to every submission (default 4)",
    )
    scan_multiple.add_argument(
        "--levels",
        type=Path,
        help="JSON object mapping path/name/stem/dir to a level",
    )
    scan_multiple.add_argument(
        "--pattern", default="*.py", help="Glob pattern (default *.py)"
    )
    scan_multiple.add_argument("--no-recursive", action="store_true")
    scan_multiple.add_argument("--out", type=Path, help="Write JSON lines to this file")
    scan_multiple.add_argument("--limit", type=int, help="Stop after N submissions")

    metrics_catalog = subparsers.add_parser(
        "metrics-catalog", help="Inspect the quality-metric catalog"
    )
    metrics_catalog.add_argument(
        "--level",
        type=int,
        choices=(1, 2, 3, 4),
        help="Only show metrics that apply at this level",
    )
    metrics_catalog.add_argument("--json", action="store_true", help="Emit JSON")

    metrics = subparsers.add_parser("metrics", help="Apply the quality metrics to a submission")
    metrics.add_argument("path", type=Path, help="Submission file")
    metrics.add_argument("--level", type=int, choices=(1, 2, 3, 4), required=True)
    metrics.add_argument("--all", action="store_true", help="Show NO and NO_APLICA too")
    metrics.add_argument("--json", action="store_true", help="Emit the report as JSON")

    profile = subparsers.add_parser(
        "profile", help="Audit one submission on both dimensions and report what fired"
    )
    profile.add_argument("path", type=Path, help="Submission file")
    profile.add_argument("--level", type=int, choices=(1, 2, 3, 4), required=True)
    profile.add_argument("--function", help="The function to audit, when the exercise fixes one")
    profile.add_argument(
        "--dynamic",
        action="store_true",
        help="Run the submission to settle the behavioural metrics",
    )
    profile.add_argument("--driver", type=Path, help="Script that exercises the submission")
    profile.add_argument("--timeout", type=float, help="Seconds before the run is killed")
    profile.add_argument(
        "--trace",
        action="store_true",
        help="Show what the run did, in order: turns, writes, comparisons, returns",
    )
    profile.add_argument("--no-ncc", action="store_true", help="Skip the restriction catalog")
    profile.add_argument("--json", action="store_true", help="Emit the profile as JSON")

    prompt = subparsers.add_parser("prompt", help="Emit the prompt an LLM judge receives")
    prompt.add_argument("metric", help="Metric id, such as M06")
    prompt.add_argument("path", type=Path, help="Submission file")
    prompt.add_argument("--spec", type=Path, help="JSON file describing the exercise")
    prompt.add_argument("--out", type=Path, help="Write the prompt here instead of stdout")

    judge = subparsers.add_parser("judge", help="Score an LLM answer against the detector")
    judge.add_argument("metric", help="Metric id, such as M06")
    judge.add_argument("path", type=Path, help="Submission file")
    judge.add_argument("--answer", type=Path, required=True, help="The model's JSON reply")
    judge.add_argument("--level", type=int, choices=(1, 2, 3, 4), default=4)
    judge.add_argument("--json", action="store_true", help="Emit the comparison as JSON")
    return parser


def _cmd_catalog(args: argparse.Namespace) -> int:
    """Print the restriction catalog, optionally filtered and as JSON.

    Parameters:
        - args: The parsed catalog arguments.

    Returns:
        - Process exit code.
    """
    if args.level is None:
        catalog = restrictions()
    else:
        catalog = restrictions_at_least(args.level)
        if args.kind is not None:
            catalog = tuple(
                r for r in catalog if _kind_value(r, args.level) == args.kind
            )
    rows = [
        {
            "id": r.id,
            "restriction": r.restriction,
            "scope": int(r.scope),
            "tool": r.tool.value,
            "technique": r.technique,
            "kind": _kind_value(r, args.level),
        }
        for r in catalog
    ]
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for row in rows:
            print(f"{row['id']:>5}  L{row['scope']}  {row['restriction']}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    """Audit a single submission and print the report.

    Parameters:
        - args: The parsed scan arguments.

    Returns:
        - Process exit code.
    """
    report = scan_file(
        args.path,
        level=args.level,
        dynamic=args.dynamic,
        driver=args.driver,
    )
    if args.json:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if report.syntax_error:
        print("SyntaxError: submission was not evaluated")
    for finding in report.findings:
        mark = "?"
        if finding.resolved:
            mark = " "
        location = finding.location
        print(
            f"{mark} {finding.restriction.id:>5}  "
            f"{finding.kind.value:<14}  line {location.line}: {finding.restriction.restriction}"
        )
    if not report.findings:
        print("No NCC findings.")
    if report.verdict is not None:
        print(
            f"Violations: {report.verdict.n_violations}; "
            f"ambiguous (not counted): {report.verdict.n_ambiguous}"
        )
    return 0


def _cmd_scan_multiple(args: argparse.Namespace) -> int:
    """Scan multiple submissions and print a summary.

    Parameters:
        - args: The parsed scan-multiple arguments.

    Returns:
        - Process exit code.
    """
    if args.levels is not None:
        levels: LevelResolver = json.loads(args.levels.read_text(encoding="utf-8"))
    else:
        levels = args.level
    scan_multiple = ScanMultiple(
        args.paths,
        levels=levels,
        pattern=args.pattern,
        recursive=not args.no_recursive,
        default_level=args.level,
    )
    total = 0
    flagged = 0
    for record in scan_multiple.run(output=args.out, limit=args.limit):
        total += 1
        if record.findings:
            flagged += 1
    destination = ""
    if args.out:
        destination = f" -> {args.out}"
    print(f"Scanned {total} submission(s); {flagged} with findings{destination}")
    return 0


def _cmd_metrics_catalog(args: argparse.Namespace) -> int:
    """List the quality metrics.

    Parameters:
        - args: The parsed metrics-catalog arguments.

    Returns:
        - Process exit code.
    """
    selected = metrics_at(args.level) if args.level else METRIC_CATALOG
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": m.id,
                        "name": m.name,
                        "shape": str(m.shape),
                        "min_level": int(m.min_level),
                        "primary": m.primary,
                        "oracle": str(m.oracle),
                        "note": m.note,
                    }
                    for m in selected
                ],
                indent=2,
            )
        )
        return 0
    for metric in selected:
        oracle = "" if metric.oracle.value == "full" else f"  [oracle: {metric.oracle.value}]"
        print(
            f"{metric.id}  L{int(metric.min_level)}+  {metric.shape.value:<7} "
            f"{metric.primary:<7}  {metric.name}{oracle}"
        )
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    """Apply the quality metrics to one submission.

    Parameters:
        - args: The parsed metrics arguments.

    Returns:
        - Process exit code.
    """
    report = scan_metrics_file(args.path, level=args.level)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if report.syntax_error:
        print(f"Not evaluated: {report.diagnostics.get('reason', 'unreadable submission')}")
        return 0
    shown = report.findings if args.all else report.present
    for finding in shown:
        mark = " " if finding.resolved else "?"
        anchor = ", ".join(f"line {e.line} {e.element}".strip() for e in finding.evidence)
        print(f"{mark} {finding.metric.id}  {finding.verdict.value:<13} {finding.metric.name}")
        if anchor:
            print(f"    {anchor}")
    if not shown:
        print("No metric findings.")
    unresolved = report.diagnostics.get("unresolved") or []
    if unresolved:
        print(f"Awaiting a run to confirm: {', '.join(unresolved)}")
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    """Audit one submission on both dimensions and print what fired.

    Parameters:
        - args: The parsed profile arguments.

    Returns:
        - Process exit code; 1 when something fired, so the command is
          usable from a shell conditional.
    """
    from .profile import profile_file

    profile = profile_file(
        args.path,
        level=args.level,
        function=args.function,
        dynamic=args.dynamic,
        driver=args.driver,
        timeout=args.timeout,
        ncc=not args.no_ncc,
        trace=args.trace,
    )
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(profile.render())
    if profile.syntax_error:
        return 2
    return 1 if (profile.fired or profile.violations) else 0


def _exercise_spec(path: Path | None) -> ExerciseSpec:
    """Build an ExerciseSpec from a JSON description, if one was given.

    Parameters:
        - path: The JSON file, or None.

    Returns:
        - The spec; empty when no file was given.
    """
    if path is None:
        return ExerciseSpec()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExerciseSpec(
        statement=str(payload.get("enunciado", "")),
        signature=str(payload.get("funcion", "")),
        returns=str(payload.get("retorno_tipo", "")),
        returns_description=str(payload.get("retorno_descripcion", "")),
        level=payload.get("nivel"),
    )


def _cmd_prompt(args: argparse.Namespace) -> int:
    """Emit the prompt a judge would receive.

    Parameters:
        - args: The parsed prompt arguments.

    Returns:
        - Process exit code.
    """
    try:
        metric = get_metric(args.metric)
    except KeyError:
        print(f"Unknown metric: {args.metric}", file=sys.stderr)
        return 2
    source = read_source(args.path)
    text = render_prompt(metric, source, spec=_exercise_spec(args.spec))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote the prompt for {metric.id} -> {args.out}")
        return 0
    print(text)
    return 0


def _cmd_judge(args: argparse.Namespace) -> int:
    """Score a model's answer against the detector.

    Parameters:
        - args: The parsed judge arguments.

    Returns:
        - Process exit code; 2 when the answer does not satisfy its schema.
    """
    from .metrics.llm.compare import compare

    try:
        metric = get_metric(args.metric)
    except KeyError:
        print(f"Unknown metric: {args.metric}", file=sys.stderr)
        return 2
    source = read_source(args.path)
    report = scan_metrics_file(args.path, level=args.level)
    finding = report.by_id(metric.id)
    if finding is None:
        print(
            f"{metric.id} does not apply at level {args.level}",
            file=sys.stderr,
        )
        return 2
    try:
        answer = parse_answer(
            metric,
            args.answer.read_text(encoding="utf-8"),
            line_count=len(source.splitlines()),
        )
    except InvalidAnswer as exc:
        print(f"Invalid answer for {metric.id}: {exc}", file=sys.stderr)
        return 2

    agreement = compare(metric, finding, answer)
    if args.json:
        print(json.dumps(agreement.to_dict(), indent=2, ensure_ascii=False))
        return 0
    verdict = {True: "agree", False: "disagree", None: "not comparable"}[agreement.agrees]
    print(f"{metric.id}  detector={agreement.detector.value}  judge={agreement.judge.value}")
    print(f"  {verdict}" + (f" — {agreement.note}" if agreement.note else ""))
    if agreement.evidence_overlap is not None:
        print(f"  evidence overlaps: {'yes' if agreement.evidence_overlap else 'no'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Parameters:
        - argv: The arguments to parse; defaults to sys.argv.

    Returns:
        - Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "catalog": _cmd_catalog,
        "scan": _cmd_scan,
        "scan-multiple": _cmd_scan_multiple,
        "metrics-catalog": _cmd_metrics_catalog,
        "metrics": _cmd_metrics,
        "profile": _cmd_profile,
        "prompt": _cmd_prompt,
        "judge": _cmd_judge,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
