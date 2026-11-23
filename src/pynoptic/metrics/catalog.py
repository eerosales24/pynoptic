"""The quality-metric catalog: seventeen entries, single source of truth.

Each entry declares what is measured, the shape of the answer, the level from
which it applies, which detector implements it, which DynaPyt hooks confirm
it at run time, and how much of the question a deterministic verifier can
actually settle.

Two field conventions differ from ``restrictions.py`` on purpose:

- ``min_level`` reads *upwards*: a metric applies when the exercise level is
  at or above it. ``Restriction.scope`` reads downwards. Mixing the two
  comparisons inverts every entry.
- ``static`` is a live registry key, looked up by the dispatcher, not a
  declarative label like ``Restriction.ast``.

No prevalence or discrimination figures live here. They are properties of one
corpus, and this package knows nothing about any corpus.
"""

from __future__ import annotations

from ..models import Level
from .models import Metric, Oracle, Shape

__all__ = ["CATALOG", "get_metric", "metrics", "metrics_at"]


CATALOG: tuple[Metric, ...] = (
    Metric(
        "M01",
        "Ignored parameter",
        Shape.BINARY,
        min_level=Level.L1,
        static="m01_ignored_parameter",
        primary="static",
        prompt="M01.md",
        note="The signature takes a parameter the body never reads, so the "
        "result cannot depend on it. Decidable from the tree alone, which is "
        "why it doubles as the calibration probe for a judge that confabulates.",
    ),
    Metric(
        "M02",
        "Condition independent of the input",
        Shape.BINARY,
        min_level=Level.L2,
        static="m02_constant_condition",
        dynamic=("comparison",),
        primary="static",
        prompt="M02.md",
        note='A test whose value never varies, such as `if "a" or "b" in text`, '
        "where precedence makes the first operand a non-empty string. A bare "
        "literal among the operands settles it outright, so the static verdict "
        "is final; the runtime hook widens the net to invariant conditions "
        "with no literal in them, which the tree cannot see.",
    ),
    Metric(
        "M03",
        "Branches that do the same thing",
        Shape.BINARY,
        min_level=Level.L2,
        static="m03_identical_branches",
        primary="static",
        prompt="M03.md",
        note="Both arms of an if/else have the same body: the decision decides "
        "nothing. Subtree comparison is exact, so there is nothing to confirm.",
    ),
    Metric(
        "M04",
        "Implicit precedence",
        Shape.BINARY,
        min_level=Level.L2,
        static="m04_implicit_precedence",
        primary="static",
        prompt="M04.md",
        note="An `and` inside an `or` without parentheses. Needs the source, "
        "not the tree: `x or (y and z)` and `x or y and z` parse identically.",
    ),
    Metric(
        "M05",
        "Repeated blocks inside the function",
        Shape.COUNT,
        min_level=Level.L1,
        static="m05_repeated_blocks",
        primary="static",
        prompt="M05.md",
        note="Sibling statements with the same tree. Counted rather than "
        "judged: two repeats is a slip, six is the shape of the solution. "
        "Structure, not behaviour, so no profiler applies.",
    ),
    Metric(
        "M06",
        "Premature decision",
        Shape.BINARY,
        min_level=Level.L3,
        static="m06_premature_decision",
        dynamic=("enter_for", "enter_while", "_return", "function_exit"),
        primary="dynamic",
        prompt="M06.md",
        note="Returns from inside the loop on the first pass, answering for one "
        "element a question that depends on all of them. Runtime settles it: "
        "iterations run divided by the length of the container.",
    ),
    Metric(
        "M07",
        "Unstable return type",
        Shape.BINARY,
        min_level=Level.L2,
        static="m07_unstable_return_type",
        dynamic=("_return", "function_exit"),
        primary="dynamic",
        prompt="M07.md",
        note="Different paths return different types. Runtime sees the cases "
        "the tree cannot, where the returned expression is a variable. The "
        "hook is function_exit, not implicit_return: the instrumenter honours "
        "implicit_return but the runtime dispatches every exit, explicit or "
        "not, through function_exit, so that is the only hook that sees a "
        "path falling off the end of the body.",
    ),
    Metric(
        "M08",
        "Impossible or repeated branch",
        Shape.BINARY,
        min_level=Level.L2,
        static="m08_impossible_branch",
        dynamic=("comparison",),
        primary="static",
        prompt="M08.md",
        note="A branch of an if/elif chain that cannot be true given the ones "
        "before it, or literally the same test twice. Runtime can refute but "
        "not confirm: a branch no input reached may still be reachable.",
    ),
    Metric(
        "M09",
        "Repeated work",
        Shape.COUNT,
        min_level=Level.L2,
        static="m09_repeated_work",
        dynamic=("enter_for",),
        primary="dynamic",
        prompt="M09.md",
        note="Walks the same container more than once where one pass was "
        "enough. The count is the verdict: no threshold to argue about.",
    ),
    Metric(
        "M10",
        "Iterations with no effect",
        Shape.BINARY,
        min_level=Level.L3,
        static="m10_idle_iterations",
        dynamic=("enter_for", "enter_while", "write"),
        primary="dynamic",
        prompt="M10.md",
        note="The loop keeps turning after the answer is settled, changing no "
        "state. Below Level 3 a full traversal may be the only option taught, "
        "which is why the metric does not apply there.",
    ),
    Metric(
        "M11",
        "Loop that never terminates",
        Shape.BINARY,
        min_level=Level.L3,
        static="m11_nonterminating_loop",
        dynamic=("enter_while",),
        primary="dynamic",
        prompt="M11.md",
        note="A while whose control variable never moves towards false on some "
        "path. The execution budget is both the safety guard and the detector.",
    ),
    Metric(
        "M12",
        "Key access without a guard",
        Shape.BINARY,
        min_level=Level.L2,
        static="m12_unguarded_key",
        dynamic=("read_subscript",),
        primary="dynamic",
        prompt="M12.md",
        note="Reads d[k] without `in` or `get` when the key may be absent. "
        "Whether it may be absent is in the statement, not the code, which is "
        "where the judge is irreplaceable.",
    ),
    Metric(
        "M13",
        "Complexity higher than necessary",
        Shape.CLASS,
        min_level=Level.L3,
        static="m13_excess_complexity",
        dynamic=("enter_for", "enter_while", "pre_call"),
        primary="dynamic",
        prompt="M13.md",
        note="A growth class above the reference. Asking for the class rather "
        "than for 'is it slow' denies the judge the neutral middle. Needs "
        "scaled inputs, and builtins must be charged their real cost.",
    ),
    Metric(
        "M14",
        "Auxiliary memory higher than necessary",
        Shape.BINARY,
        min_level=Level.L3,
        static="m14_excess_memory",
        dynamic=("enter_for", "enter_while"),
        primary="dynamic",
        prompt="M14.md",
        note="Builds structures proportional to the input where the reference "
        "is constant. The judge sees that a copy happens, not how large: the "
        "factor is the verifier's to report.",
    ),
    Metric(
        "M15",
        "Data rewrite",
        Shape.BINARY,
        min_level=Level.L1,
        static="m15_data_rewrite",
        dynamic=("write",),
        primary="dynamic",
        prompt="M15.md",
        note="Destroys a value it already held without using it. The write "
        "hook carries the old value and the new one, so this is observed "
        "rather than inferred.",
    ),
    Metric(
        "M16",
        "Names without meaning",
        Shape.BINARY,
        min_level=Level.L1,
        static="m16_meaningless_names",
        primary="static",
        oracle=Oracle.PARTIAL,
        prompt="M16.md",
        note="Two halves. Shape — one or two characters, numbered names, "
        "casing — is decidable. Whether the name matches what the variable "
        "holds is not decidable by any tool, and that half has no oracle.",
    ),
    Metric(
        "M17",
        "Suspicious comments",
        Shape.COUNT,
        min_level=Level.L1,
        static="m17_suspicious_comments",
        primary="static",
        oracle=Oracle.PARTIAL,
        prompt="M17.md",
        note="Comments that do not fit the code they sit on. A docstring "
        "documenting parameters the signature lacks is decidable; register and "
        "voice are not. Report as a flag for human review, never as a verdict: "
        "this one has consequences for a person.",
    ),
)


_BY_ID: dict[str, Metric] = {m.id: m for m in CATALOG}


def metrics() -> tuple[Metric, ...]:
    """Return the whole catalog.

    Returns:
        - Every metric, in catalog order.
    """
    return CATALOG


def get_metric(metric_id: str) -> Metric:
    """Return one metric by id.

    Parameters:
        - metric_id: The catalog id, such as "M01".

    Returns:
        - The matching metric.

    Raises:
        - KeyError: When the id is not in the catalog.
    """
    return _BY_ID[metric_id]


def metrics_at(exercise_level: Level | int | str) -> tuple[Metric, ...]:
    """Return the metrics that apply at a level.

    Parameters:
        - exercise_level: The level of the exercise being audited.

    Returns:
        - The metrics whose min_level is at or below that level.
    """
    return tuple(m for m in CATALOG if m.applies_at(exercise_level))
