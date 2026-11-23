# Pynoptic — a static and dynamic profiler for non-curricular constructs and code quality in CS1 Python submissions

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](#versioning)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Eduardo Rosales, Diego Munevar, Eric Alarcon — Universidad de los Andes

**Pynoptic** — from *Python* + *Panoptic* ("providing a comprehensive view") —
is a profiler that combines static and dynamic analysis to detect
**Non-Curricular Constructs** (NCC) in Python code.

An NCC is a Python construct a student is not expected to use for a given
exercise: either it lies outside the CS1 subset entirely (*course-wide*), or it
becomes curricular only at a later level (*level-relative*). Pynoptic uses a
catalog of 215 restrictions and three detection engines to find them.

## What this repository provides

- A catalog of **215 restrictions**, each declaring the engine that finds it,
  resolved by Semgrep, the `ast` module and DynaPyt.
- A second catalog of **17 quality metrics** — "is there a defect here?"
  rather than "was this taught yet?" — with static detectors and run-time
  confirmation.
- A **prompt-and-validation harness** for comparing a deterministic verdict
  against an LLM judge, metric by metric, in one shared vocabulary.
- A **four-layer boundary** for executing submitted code, documented for what
  it is and is not.
- A CLI and a typed Python API.
- A suite of **340 tests** that reconciles both catalogs against the code, and
  a demonstration corpus of 17 exercises, one per metric.

> **Status.** No publication is associated with this release yet.

## Background and approach

Automatic graders assess functional correctness only. A submission can earn
full credit while relying on constructs the exercise was designed to avoid.
Pynoptic makes those constructs visible, which supports research on submission
patterns and gives instructors a multidimensional view of student code.

## Repository structure

```
src/pynoptic/
    restrictions.py       the 215-entry catalog, the single source of truth
    models.py             Level, Restriction, Finding, Report and friends
    engine.py             orchestrates a scan; merges static and dynamic
    verdict.py            occurrence counting and candidate voting
    scan_multiple.py      streaming scans over a corpus
    profile.py            both dimensions over one submission
    sources.py            reading a submission from disk, safely
    cli.py                the command line
    static/
        ast_engine.py     the 18 restrictions no Semgrep pattern expresses
        rulegen.py        generates the ruleset from the catalog
        semgrep_runner.py shells out to Semgrep
        rules/ncc.yml     the generated ruleset, committed
    dynamic/              DynaPyt analysis for the ambiguous candidates
    sandbox/              screen, limits, audit hook, timeout
    metrics/
        catalog.py        the 17-entry metric catalog
        static/           one detector per metric
        dynamic/          run-time resolution for the nine behavioural ones
        llm/              prompt rendering, answer validation, comparison
        prompts/          one prompt template per metric
tests/                    the test suite
demo/                     17 exercises, one per metric
```

## Requirements

- Python 3.11 or newer.
- Semgrep and DynaPyt, installed automatically as dependencies.
- Memory and process limits in dynamic mode are **POSIX only**. On Windows
  only the timeout and the audit hook apply, and a run says so rather than
  pretending otherwise.

## Installation

```bash
pip install pynoptic
```

## Usage

### Quick start

```python
from pynoptic import Level, scan_source, scan_file

# Audit an in-memory submission at Level 1.
report = scan_source(
    "def f(items):\n    return [x for x in items]\n",
    level=Level.L1,
)
for finding in report.findings:
    print(finding.restriction.id, finding.kind, finding.location.line)
# R110 course-wide 2
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
pynoptic metrics-catalog --level 2         # list the metrics in scope
pynoptic metrics submission.py --level 3   # apply the quality metrics
pynoptic prompt M06 submission.py          # what the judge is sent
pynoptic judge M06 submission.py --answer reply.json
```

`profile` is the one subcommand that audits both dimensions at once, from a
single execution:

```bash
pynoptic profile submission.py --level 2 --function contar_pares     --dynamic --driver driver.py --trace
```

It reports what fired and where, and nothing else. `--json` emits the same
thing for a program to read: three separate lists for what fired, what came
back clean and what nothing could settle — a metric that never ran is not a
metric that passed, and the format is built so the two cannot be confused.
`--no-ncc` skips the restriction catalog, which is most of the wall clock,
and `--trace` records what the run did, in order.

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
| `Restriction.semgrep` | 155 | Semgrep | literals, names, operators, imports, node types |
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
`R50`/`R51` (`*`, `+`) and `R130`/`R134` (`-`, `-=`) collide with unrestricted
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

### Executing someone else's code

Dynamic mode **runs the submission**. That is the whole point, and it is the
riskiest thing the tool does, so it happens behind four layers.

| Layer | What it stops | Where |
|---|---|---|
| **1. Screen** | A submission whose *source* already shows a problem: an import off the allowlist, `eval`, a walk to `__subclasses__`. Refused before a process starts. | `sandbox/screen.py` |
| **2. Limits** | Memory, extra processes, file size. **POSIX only** — Windows has no `resource` module, and the run says so instead of pretending. | `sandbox/limits.py` |
| **3. Guard** | What the source does not show: an import built from a string, a socket, a write outside the working directory, `os.system`, loading native code. An audit hook (PEP 578) that cannot be uninstalled. | `sandbox/guard.py` |
| **4. Timeout** | A submission that never stops. The parent kills the child. The only limit that holds on every platform. | `dynamic/runner.py` |

```python
from pynoptic.sandbox import STRICT
from pynoptic.dynamic import run_dynamic

run = run_dynamic("submission.py", driver="driver.py", policy=STRICT)
run.refused      # True when a layer stopped it
run.violations   # what the guard saw, even if the submission caught it
run.notes        # limits this platform could not enforce
```

The default policy allows a short list of standard-library modules a CS1
answer has a reason to use, and nothing else. Widen it per course:

```python
policy = STRICT.allowing("pandas", "numpy")
```

Widening cannot admit `ctypes`, `subprocess`, `socket`, `pickle` or
`importlib`: those are on a separate deny list precisely so that loosening
the allowlist for a course cannot open them by accident.

#### What this is not

**It is not a sandbox.** A determined attacker who already has code execution
can get around guards written in Python. Run the whole thing inside a real
boundary — a container, an unprivileged account, nsjail, seccomp — and treat
these layers as what catches the ordinary cases legibly.

Three specific gaps, stated rather than buried:

- **Windows enforces no memory or process limits.** Only the timeout and the
  audit hook apply there.
- **Writes are allowed anywhere under the system temp directory**, not only
  the working directory. The instrumenter puts scratch files there and the
  hook cannot tell its calls from the submission's. Temp is volatile; the
  home directory, the project tree and system paths stay shut.
- **CPython raises the `import` audit event only when a module is really
  loaded**, never when it comes from `sys.modules`. Anything the harness
  imports before arming the guard would be invisible to it forever, so the
  guard drops forbidden modules from the cache first and the privilege check
  runs in the parent. If you add an import to the child, check this still
  holds — there is a test for it.

A run that finds itself executing as root or Administrator says so in
`run.notes`. Do not ignore it: that is the one protection left when every
other layer fails.

## Quality metrics

A restriction answers *"did the student use a construct the course has not
taught yet?"*. A metric answers *"is there a defect or a bad practice here?"*.
The second question is a separate catalog, `pynoptic/metrics/catalog.py`, with
its own types and its own registry.

```bash
pynoptic metrics-catalog --level 2
pynoptic metrics submission.py --level 3
pynoptic metrics submission.py --level 3 --json
```

```python
from pynoptic.metrics import scan_metrics

report = scan_metrics(source, level=3)
for finding in report.present:
    print(finding.metric.id, finding.verdict, finding.evidence)
```

Each metric declares the shape of its answer — **binary**, a **count**, or a
growth **class** — the level it applies from, the detector that implements it,
and the DynaPyt hooks that confirm it at run time.

Two conventions differ from the restriction catalog, and mixing them up
inverts every entry:

- `Metric.min_level` reads *upwards*: the metric applies when the exercise is
  at or above it. `Restriction.scope` reads downwards.
- `Metric.static` is a live registry key the dispatcher looks the detector up
  by, not a declarative label.

### Candidates and oracles

Nine metrics are **candidates** when the tree alone has spoken: a legitimate
early return looks exactly like a premature decision, and a key may be
guaranteed present by the exercise statement. Those findings carry
`resolved=False` until a run settles them, and nothing downstream treats them
as verdicts.

Two metrics have only a **partial oracle**. Whether a name matches what the
variable holds, and whether a comment reads as generated, are not decidable by
any tool. The catalog says so with `Metric.oracle`, and the comparison layer
reports *not comparable* rather than inventing a disagreement — scoring a
model against a check that does not exist would measure the detector's blind
spot and call it the model's error.

### The LLM judge

The subsystem exists to compare a deterministic verdict against an LLM's,
metric by metric, in one shared vocabulary.

```bash
pynoptic prompt M06 submission.py --spec exercise.json
pynoptic judge  M06 submission.py --answer reply.json
```

`prompt` renders the template shipped at `pynoptic/metrics/prompts/M06.md`
with the exercise context, the numbered source and the exact JSON schema.
`judge` validates the reply and lines it up against the detector.

Three properties of the prompts are measured rather than stylistic, so
changing them invalidates comparisons with earlier runs: one metric per
prompt, numbered source with mandatory line evidence, and `NO_APLICA` /
`NO_DECIDIBLE` always available. The validator rejects a reply that cites a
line the submission does not have.

## Configuration

- **`--level 1..4`** is the level of the exercise, and it decides what
  applies. A restriction is an NCC when its scope is at or above that level;
  a metric applies from its `min_level` upwards.
- **`--levels levels.json`** maps many submissions at once. The JSON keys may
  be a full path, a file name, a stem or a parent directory.
- **`--function`** names the function to audit. Without it the first
  top-level function is used, so a submission with a helper above the answer
  would have its helper measured.
- **`--driver`** supplies the script that exercises the submission, and
  **`--timeout`** bounds the run. The looping budget is derived from the
  timeout, so a shorter timeout also shortens how long a loop may run before
  it is reported as non-terminating.
- The execution policy is widened per course with
  `STRICT.allowing("pandas", "numpy")`. Widening can never admit `ctypes`,
  `subprocess`, `socket`, `pickle` or `importlib`.
- `static/rules/ncc.yml` is generated from the catalog and committed. After
  editing a `Restriction`, regenerate it with
  `python -m pynoptic.static.rulegen`; a test fails if the two drift apart.

## Demonstration corpus

`demo/` holds seventeen exercises, one per metric, each written so that its
metric fires:

```bash
python demo/correr.py              # the table: 17 cases, what fired and why
python demo/correr.py M10 --traza  # one case, with the record of what ran
python demo/correr.py --juez       # each metric's JSON contract, validated
```

A case passes when its metric comes back **present and resolved**. The second
half matters as much as the first: a candidate that nothing settled is not a
detection, and counting it as one would claim the dynamic layer works without
ever having run it.

The exercises are written in the style of the course they come from, which is
to say in Spanish, and the verdict vocabulary (`SI`, `NO`, `NO_APLICA`,
`NO_DECIDIBLE`) is part of the measured prompt contract rather than a
stylistic choice — changing it invalidates comparisons against earlier runs.

## Limitations

- Semgrep and `ast` see every submission that parses, but submissions recorded
  with a `SyntaxError` cannot be analysed statically.
- DynaPyt observes only executed paths. An ambiguous construct on a branch no
  input reaches stays `unresolved`.
- Method-name and qualified-call rules cannot see receiver types, so hybrid
  candidates are only counted once confirmed at run time.
- NCC use alone does not establish LLM assistance; results are meant for
  aggregate comparison, not individual attribution.
- The nine candidate metrics need a driver that exercises the submission
  before they resolve. Without one, they report a suspicion, not a finding.
- `M13` and `M14` compare against a reference solution. With none supplied
  they report the student's own class and `desconocida` for the reference.
- `M17` flags comments for a human to read. It is not evidence of anything on
  its own, and it is the metric whose output has consequences for a person.

## What is not included

- **Student submissions.** Fixtures are synthetic by policy: the submissions
  the tool was developed against are not ours to publish, so none are here,
  although the tool reads them happily enough as input.
- **No corpus, no database dump, no analysis notebooks, no published
  results.** This repository is the tool.
- **No sandbox.** The four layers in *Executing someone else's code* are
  defence in depth. Run the whole thing inside a real boundary.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests demo
uv run mypy
```

Both catalogs are reconciled by the test suite, which is what keeps a
declarative field from drifting away from the code that honours it:

- every restriction has a detector, and every `ast=` label is an id the
  visitor actually emits;
- the committed `static/rules/ncc.yml` matches `generate_yaml()`, so an edit
  to a `Restriction` cannot leave the shipped ruleset behind;
- every metric has a registered detector and a shipped prompt template, every
  template offers every placeholder, and every rendered prompt carries the
  numbered code and both escape hatches;
- every metric has a positive and a negative synthetic case.

Regenerate the Semgrep ruleset after editing the catalog:

```bash
python -m pynoptic.static.rulegen
```

## Versioning

Pynoptic follows [Semantic Versioning](https://semver.org/). The version is
declared once, in `pyproject.toml`; `pynoptic.__version__` and
`pynoptic --version` read it from the installed distribution.

### Release history

- **1.0.0** — 2026-11-23 — first public release. Adds the quality-metric
  catalog, the LLM-judge harness and the execution boundary to the
  restriction catalog, and ships the generated Semgrep ruleset, which earlier
  versions expected callers to generate themselves.

Version 0.1.0 was internal and never published.

## License

Released under the MIT License. See [LICENSE](./LICENSE) for the full text.

The restriction catalog in `src/pynoptic/restrictions.py` and the metric
catalog in `src/pynoptic/metrics/catalog.py` are covered by the same license.

## Contact

- Eduardo Rosales — <ee.rosales24@uniandes.edu.co>
- Diego Munevar — <d.munevar@uniandes.edu.co>
- Eric Alarcon — <e.alarcond@uniandes.edu.co>
