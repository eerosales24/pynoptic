# Pynoptic

**Pynoptic** — from *Python* + *Panoptic* ("providing a comprehensive view") —
is a profiler that combines static and dynamic analysis to detect
**Non-Curricular Constructs** (NCC) in Python code.

An NCC is a Python construct a student is not expected to use for a given
exercise: either it lies outside the CS1 subset entirely (*course-wide*), or it
becomes curricular only at a later level (*level-relative*). Pynoptic uses a
catalog of 220 restrictions and three detection engines to find them.

## Why

Automatic graders assess functional correctness only. A submission can earn
full credit while relying on constructs the exercise was designed to avoid.
Pynoptic makes those constructs visible, which supports research on submission
patterns and gives instructors a multidimensional view of student code.

## Install

```bash
pip install pynoptic
```

Requires Python 3.11+. Semgrep and DynaPyt are installed automatically.

## Quick start

```python
from pynoptic import Level, scan_source, scan_file

# Audit an in-memory submission at Level 1.
report = scan_source(
    "def f(items):\n    return [x for x in items]\n",
    level=Level.L1,
)
for finding in report.findings:
    print(finding.restriction.id, finding.kind, finding.location.line)
# R115 course-wide 2
```

```python
from pynoptic import scan_file, Level

report = scan_file("submission.py", level=Level.L2)
print(report.course_wide)      # outside the whole CS1 subset
print(report.level_relative)   # curricular later, off-limits here
```

### Command line

```bash
pynoptic catalog --level 1                 # list NCCs at Level 1
pynoptic scan submission.py --level 2      # audit one file
pynoptic scan submission.py --level 2 --json
pynoptic scan-multiple corpus/ --level 1 --out ncc.jsonl
pynoptic scan-multiple corpus/ --levels levels.json --out ncc.jsonl
```

### Batch scans

`ScanMultiple` streams one JSON record per submission, so a large corpus is not held
in memory:

```python
from pynoptic import ScanMultiple

for record in ScanMultiple("corpus/", levels={"hw1": 1, "hw4": 3}, default_level=2).run(
    output="ncc.jsonl"
):
    ...
```

The `--levels` JSON maps a full path, file name, stem, or parent directory to
a level.

## How detection works

The catalog (`pynoptic/restrictions.py`) is the single source of
truth. Each `Restriction` declares the detector that finds it:

| Field | Count | Tool | What it catches |
| --- | --- | --- | --- |
| `Restriction.semgrep` | 160 | Semgrep | literals, names, operators, imports, node types |
| `Restriction.ast` | 18 | `ast` | shapes Semgrep cannot express (chained assignment, variadic parameters, the main-module guard, ...) |
| `Restriction.candidate` | 23 | Semgrep | statically ambiguous names/operators (the candidates) |
| `Restriction.dynamic` | 42 | DynaPyt | run-time triggers that classify a candidate by type |

The generated Semgrep ruleset lives in `pynoptic/static/rules/ncc.yml` and is
regenerated from the catalog with:

```bash
python -m pynoptic.static.rulegen
```

### Classification

For an exercise at level *L*, a restriction is an NCC when its scope is *L* or
higher. It is *course-wide* when the scope is `Level 4` and *level-relative*
otherwise. Constructs that are allowed at *L* are not reported.

### Occurrence counts

Alongside `findings`, every report carries a `verdict` with occurrence counts:
a specific restriction suppresses a general one at the same position, and a
candidate that denotes several restrictions is counted once. When DynaPyt
resolved it, the exact id wins; otherwise the candidate group is voted on by
scope at the exercise level, and a mixed vote is reported under `ambiguous` and
not counted. Arithmetic operators are the exception to unanimous votes:
`R55`/`R56` (`*`, `+`) and `R135`/`R139` (`-`, `-=`) collide with unrestricted
numeric arithmetic, so an unresolved static candidate stays `ambiguous` until
runtime confirms a `list`/`set` operand — plain `2 * 3` never counts.
`Report.verdict` exposes `violations`, `ambiguous`,
`n_violations`, `n_ambiguous` and `compliant`.

### Dynamic disambiguation

Some constructs share a name or operator across types: `count()` is a `str` or
`list` method, `*` is list repetition or numeric multiplication, and `&` is
bitwise AND or set intersection. Pynoptic emits a Semgrep candidate and
resolves it with DynaPyt hooks (`pre_call`, `binary_operation`,
`augmented_assignment`, `comparison`, `read_subscript`). Each restriction
declares its own runtime trigger (`DynamicMatch`); `pynoptic.dynamic.resolve`
builds an index from those triggers, so there is no separate name-to-restriction
table. Dynamic mode is enabled per scan:

```python
report = scan_file(
    "submission.py",
    level=Level.L1,
    dynamic=True,
    driver="driver.py",   # imports the submission and exercises it
)
```

Candidates that never execute remain flagged as `resolved=False`; candidates
that execute but turn out to be unrestricted are refuted.

### Sandboxing

Dynamic mode **executes student code**. Pynoptic does not sandbox; run it
inside your existing isolation boundary — the grading worker already executes
submissions inside Docker with `nsjail`. The runner works on a temporary copy
and never modifies the original file.

## Limitations

- Semgrep and `ast` see every submission that parses, but submissions recorded
  with a `SyntaxError` cannot be analysed statically.
- DynaPyt observes only executed paths. An ambiguous construct on a branch no
  input reaches stays `unresolved`.
- Method-name and qualified-call rules cannot see receiver types, so hybrid
  candidates are only counted once confirmed at run time.
- NCC use alone does not establish LLM assistance; results are meant for
  aggregate comparison, not individual attribution.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy
```

The catalog and detector registry are reconciled by the test suite: every
restriction must have a detector, and the committed Semgrep ruleset must match
`generate_yaml()`.

## License

To be defined.
