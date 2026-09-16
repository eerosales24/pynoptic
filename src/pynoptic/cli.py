"""
CLI for pynoptic, with subcommands to inspect the catalog, scan one submission,
or scan multiple submissions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .engine import scan_file
from .models import NccKind, Restriction
from .restrictions import restrictions, restrictions_at_least
from .scan_multiple import LevelResolver, ScanMultiple

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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Parameters:
        - argv: The arguments to parse; defaults to sys.argv.

    Returns:
        - Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "catalog":
        return _cmd_catalog(args)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "scan-multiple":
        return _cmd_scan_multiple(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
