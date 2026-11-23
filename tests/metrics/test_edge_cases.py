"""The edge cases each metric was getting wrong, one test per claim.

Every test here corresponds to a submission shape that the first version of
a detector answered incorrectly. They are kept separate from
``test_detectors.py``, which checks that each metric fires at all: these
check that it fires on the right things.
"""

from __future__ import annotations

import pytest

from pynoptic.metrics import Judgement, scan_metrics
from pynoptic.metrics.static import build_context
from pynoptic.metrics.static.registry import get_detector


def verdict(key: str, source: str) -> tuple[Judgement, tuple[int, ...], bool]:
    """Run one detector and return its verdict, lines and resolution."""
    context = build_context(source)
    assert context is not None, "the fixture must parse and define a function"
    detection = get_detector(key)(context)
    return detection.verdict, tuple(e.line for e in detection.evidence), detection.resolved


# -- M01: a parameter whose value cannot reach a read ------------------


def test_m01_flags_a_parameter_overwritten_before_it_is_read() -> None:
    """`x = 5` makes the argument unreachable even though `x` is read."""
    answer, _lines, _ = verdict(
        "m01_ignored_parameter",
        "def f(x: int) -> int:\n    x = 5\n    return x\n",
    )
    assert answer is Judgement.PRESENT


def test_m01_spares_the_accumulator_that_reads_itself() -> None:
    answer, _lines, _ = verdict(
        "m01_ignored_parameter",
        "def f(x: int) -> int:\n    x = x + 1\n    return x\n",
    )
    assert answer is Judgement.ABSENT


def test_m01_spares_a_conditional_rebinding() -> None:
    """A write inside an if leaves a path where the argument is read."""
    answer, _lines, _ = verdict(
        "m01_ignored_parameter",
        "def f(x: int) -> int:\n    if x > 100:\n        x = 100\n    return x\n",
    )
    assert answer is Judgement.ABSENT


def test_m01_still_flags_the_parameter_never_mentioned() -> None:
    answer, _lines, _ = verdict(
        "m01_ignored_parameter",
        "def f(a: int, b: int) -> int:\n    return a\n",
    )
    assert answer is Judgement.PRESENT


# -- M02: literals nested deeper than one level ------------------------


def test_m02_finds_a_literal_inside_a_nested_boolean() -> None:
    """`a or (b and "c")` hides the literal one level down."""
    answer, _lines, _ = verdict(
        "m02_constant_condition",
        'def f(a: bool, b: bool) -> bool:\n    if a or (b and "c"):\n        return True\n'
        "    return False\n",
    )
    assert answer is Judgement.PRESENT


def test_m02_leaves_while_true_alone() -> None:
    answer, _lines, _ = verdict(
        "m02_constant_condition",
        "def f(n: int) -> int:\n    while True:\n        n = n - 1\n        if n < 0:\n"
        "            break\n    return n\n",
    )
    assert answer is Judgement.ABSENT


def test_m02_flags_if_true_which_is_not_an_idiom() -> None:
    answer, _lines, _ = verdict(
        "m02_constant_condition",
        "def f(n: int) -> int:\n    if True:\n        return n\n    return 0\n",
    )
    assert answer is Judgement.PRESENT


# -- M04: whose parentheses are they -----------------------------------


def test_m04_flags_an_and_inside_a_call_argument() -> None:
    """The call's own bracket is not the expression's."""
    answer, _lines, _ = verdict(
        "m04_implicit_precedence",
        "def f(a: bool, b: bool, c: bool) -> bool:\n    return bool(a or b and c)\n",
    )
    assert answer is Judgement.PRESENT


def test_m04_spares_the_parenthesised_form() -> None:
    answer, _lines, _ = verdict(
        "m04_implicit_precedence",
        "def f(a: bool, b: bool, c: bool) -> bool:\n    return a or (b and c)\n",
    )
    assert answer is Judgement.ABSENT


def test_m04_spares_parentheses_spread_over_two_lines() -> None:
    answer, _lines, _ = verdict(
        "m04_implicit_precedence",
        "def f(a: bool, b: bool, c: bool) -> bool:\n    return a or (\n        b and c\n    )\n",
    )
    assert answer is Judgement.ABSENT


# -- M07: the type the tree could not see ------------------------------


def test_m07_leaves_a_variable_return_as_a_candidate() -> None:
    """`return total` says nothing about the type, so nothing is settled."""
    answer, _lines, resolved = verdict(
        "m07_unstable_return_type",
        "def f(xs: list) -> int:\n    total = 0\n    for x in xs:\n        total = total + x\n"
        "    return total\n",
    )
    assert answer is Judgement.ABSENT
    assert resolved is False


def test_m07_leaves_a_function_that_can_fall_through_as_a_candidate() -> None:
    answer, _lines, resolved = verdict(
        "m07_unstable_return_type",
        "def f(x: int) -> int:\n    if x > 0:\n        return 1\n",
    )
    assert answer is Judgement.ABSENT
    assert resolved is False


def test_m07_settles_a_function_whose_every_path_is_typed() -> None:
    answer, _lines, resolved = verdict(
        "m07_unstable_return_type",
        "def f(x: int) -> int:\n    if x > 0:\n        return 1\n    return 2\n",
    )
    assert answer is Judgement.ABSENT
    assert resolved is True


# -- M12: the dictionary that arrived as a parameter -------------------


def test_m12_sees_a_dict_parameter_from_its_annotation() -> None:
    answer, _lines, _ = verdict(
        "m12_unguarded_key",
        "def f(inventario: dict, clave: str) -> int:\n    return inventario[clave]\n",
    )
    assert answer is Judgement.PRESENT


def test_m12_respects_a_membership_guard() -> None:
    answer, _lines, _ = verdict(
        "m12_unguarded_key",
        "def f(inventario: dict, clave: str) -> int:\n    if clave in inventario:\n"
        "        return inventario[clave]\n    return 0\n",
    )
    assert answer is Judgement.ABSENT


def test_m12_does_not_apply_to_a_list_parameter() -> None:
    answer, _lines, _ = verdict(
        "m12_unguarded_key",
        "def f(xs: list, i: int) -> int:\n    return xs[i]\n",
    )
    assert answer is Judgement.NOT_APPLICABLE


# -- M13: the call that only looks linear ------------------------------


def test_m13_spares_max_of_two_scalars() -> None:
    answer, _lines, _ = verdict(
        "m13_excess_complexity",
        "def f(xs: list) -> int:\n    mayor = 0\n    for x in xs:\n"
        "        mayor = max(mayor, x)\n    return mayor\n",
    )
    assert answer is Judgement.ABSENT


def test_m13_flags_max_of_a_container_inside_a_loop() -> None:
    answer, _lines, _ = verdict(
        "m13_excess_complexity",
        "def f(xs: list) -> list:\n    out = []\n    for x in xs:\n"
        "        out.append(max(xs))\n    return out\n",
    )
    assert answer is Judgement.PRESENT


# -- M15: anchored where the value is destroyed ------------------------


def test_m15_anchors_on_the_write_that_discards() -> None:
    """The run observes the discard at the overwriting line, not the first."""
    answer, lines, _ = verdict(
        "m15_data_rewrite",
        "def f(a: int, b: int) -> int:\n    r = a + b\n    r = a * b\n    return r\n",
    )
    assert answer is Judgement.PRESENT
    assert lines == (3,)


# -- M16: whose names are being judged ---------------------------------


def test_m16_does_not_count_builtins_towards_the_denominator() -> None:
    """Three builtins must not dilute two opaque names into compliance."""
    answer, _lines, _ = verdict(
        "m16_meaningless_names",
        "def f(a: list, b: list) -> int:\n    c = len(a)\n    d = len(b)\n"
        "    return round(max(c, d))\n",
    )
    assert answer is Judgement.PRESENT


def test_m16_passes_a_well_named_function() -> None:
    answer, _lines, _ = verdict(
        "m16_meaningless_names",
        "def promedio(valores: list) -> float:\n    total = 0\n"
        "    for valor in valores:\n        total = total + valor\n"
        "    return total / len(valores)\n",
    )
    assert answer is Judgement.ABSENT


# -- the function under audit ------------------------------------------


def test_the_named_function_is_audited_not_the_first_one() -> None:
    """A helper defined above the answer must not be the one measured."""
    source = (
        "def ayuda(x: int) -> int:\n    return x\n\n\n"
        "def respuesta(a: int, b: int) -> int:\n    return a\n"
    )
    report = scan_metrics(source, level=1, function="respuesta")
    assert report.diagnostics["function"] == "respuesta"
    assert report.by_id("M01").verdict is Judgement.PRESENT


def test_a_missing_named_function_is_reported_not_guessed() -> None:
    report = scan_metrics("def otra(x: int) -> int:\n    return x\n", level=1, function="falta")
    assert report.syntax_error is True
    assert "falta" in report.diagnostics["reason"]


@pytest.mark.parametrize(
    "source",
    [
        "",
        "x = 1\n",
        "def f(:\n",
        "class A:\n    pass\n",
    ],
)
def test_a_submission_with_no_function_is_not_a_crash(source: str) -> None:
    report = scan_metrics(source, level=4)
    assert report.syntax_error is True
    assert report.findings == []
