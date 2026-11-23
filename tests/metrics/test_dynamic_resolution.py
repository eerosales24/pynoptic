"""Runtime resolution of the metrics the tree cannot settle.

These tests instrument and execute code, so they cost seconds each. They are
the only place the claims in ``metrics/dynamic/resolve.py`` are checked
against a real run, which is what makes them worth the wall clock: every
other test in the suite would pass with the whole dynamic layer deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pynoptic.metrics import Judgement, MetricFinding, scan_metrics_file

pytestmark = pytest.mark.slow


def profile(
    tmp_path: Path, source: str, driver: str, *, level: int = 3
) -> dict[str, MetricFinding]:
    """Run one submission under a driver and return its findings by id."""
    submission = tmp_path / "submission.py"
    submission.write_text(source, encoding="utf-8")
    driver_path = tmp_path / "driver.py"
    driver_path.write_text(driver, encoding="utf-8")
    report = scan_metrics_file(
        submission, level=level, dynamic=True, driver=driver_path, timeout=60
    )
    assert report.diagnostics.get("dynamic") == "executed", report.diagnostics
    return {f.metric.id: f for f in report.findings}


# -- M06: did one element really decide ---------------------------------


def test_m06_confirms_a_return_on_the_first_turn(tmp_path: Path) -> None:
    findings = profile(
        tmp_path,
        "def todos_positivos(numeros: list) -> bool:\n"
        "    for n in numeros:\n"
        "        if n > 0:\n"
        "            return True\n"
        "        else:\n"
        "            return False\n",
        "from submission import todos_positivos\ntodos_positivos([1, 2, -3, 4])\n",
    )
    assert findings["M06"].verdict is Judgement.PRESENT
    assert findings["M06"].resolved is True
    assert "turn 1 of 4" in findings["M06"].data["runtime"]


def test_m06_refutes_the_search_that_walks_before_answering(tmp_path: Path) -> None:
    """A legitimate early return looks identical to the tree; the run differs."""
    findings = profile(
        tmp_path,
        "def primer_par(numeros: list) -> int:\n"
        "    for n in numeros:\n"
        "        if n % 2 == 0:\n"
        "            return n\n"
        "    return -1\n",
        "from submission import primer_par\nprimer_par([1, 3, 5, 8])\n",
    )
    assert findings["M06"].verdict is Judgement.ABSENT
    assert findings["M06"].resolved is True


# -- M07: the type the tree never saw -----------------------------------


def test_m07_confirms_a_path_that_falls_off_the_end(tmp_path: Path) -> None:
    """The run sees the implicit None that no return statement carries."""
    findings = profile(
        tmp_path,
        "def buscar(items: list, objetivo: int) -> int:\n"
        "    for i in range(len(items)):\n"
        "        if items[i] == objetivo:\n"
        "            return i\n",
        "from submission import buscar\nbuscar([1, 2, 3], 2)\nbuscar([1, 2, 3], 99)\n",
    )
    assert findings["M07"].verdict is Judgement.PRESENT
    assert "NoneType" in findings["M07"].data["tipos"]


def test_m07_treats_int_and_float_as_one_type(tmp_path: Path) -> None:
    """A caller can use either the same way; flagging it would be noise."""
    findings = profile(
        tmp_path,
        "def mitad(n: int) -> float:\n"
        "    if n % 2 == 0:\n"
        "        return n // 2\n"
        "    return n / 2\n",
        "from submission import mitad\nmitad(4)\nmitad(5)\n",
    )
    assert findings["M07"].verdict is Judgement.ABSENT


# -- M09: passes over one container -------------------------------------


def test_a_for_loop_counts_its_turns_exactly(tmp_path: Path) -> None:
    """The exhaustion signal is not a turn.

    DynaPyt calls `enter_for` one final time with a StopIteration instance
    to say the iterable ran out. Counting it inflates every exhausted loop
    by one, which lands directly in M10's tally: eight elements with the
    answer settled on turn two leaves six idle turns, not seven.
    """
    findings = profile(
        tmp_path,
        "def contiene_negativo(numeros: list) -> bool:\n"
        "    encontrado = False\n"
        "    for numero in numeros:\n"
        "        if numero < 0:\n"
        "            encontrado = True\n"
        "    return encontrado\n",
        "from submission import contiene_negativo\n"
        "contiene_negativo([5, -3, 7, 8, 9, 10, 11, 12])\n",
    )
    idle = findings["M10"]
    assert idle.verdict is Judgement.PRESENT
    assert idle.data["vueltas_inutiles"] == 6
    assert idle.data["vueltas"] == 8


def test_m09_counts_passes_over_the_same_object(tmp_path: Path) -> None:
    findings = profile(
        tmp_path,
        "def contar(numeros: list) -> int:\n"
        "    pares = 0\n"
        "    impares = 0\n"
        "    for n in numeros:\n"
        "        if n % 2 == 0:\n"
        "            pares = pares + 1\n"
        "    for n in numeros:\n"
        "        if n % 2 == 1:\n"
        "            impares = impares + 1\n"
        "    return pares\n",
        "from submission import contar\ncontar([1, 2, 3, 4, 5, 6])\n",
        level=2,
    )
    assert findings["M09"].verdict is Judgement.PRESENT
    assert findings["M09"].data["n"] == 2


def test_m09_does_not_confuse_two_calls_for_two_passes(tmp_path: Path) -> None:
    """Two short-lived lists in two calls routinely share an address."""
    findings = profile(
        tmp_path,
        "def sumar(numeros: list) -> int:\n"
        "    total = 0\n"
        "    for n in numeros:\n"
        "        total = total + n\n"
        "    return total\n",
        "from submission import sumar\nsumar([1, 2, 3])\nsumar([4, 5, 6])\n",
        level=2,
    )
    assert findings["M09"].verdict is Judgement.ABSENT


# -- M11: the loop that does not stop -----------------------------------


def test_m11_confirms_a_loop_that_never_terminates(tmp_path: Path) -> None:
    """The budget is the detector: the run is stopped from the inside."""
    findings = profile(
        tmp_path,
        "def contar(n: int) -> int:\n"
        "    i = 0\n"
        "    total = 0\n"
        "    while i < n:\n"
        "        total = total + 1\n"
        "    return total\n",
        "from submission import contar\ncontar(5)\n",
    )
    assert findings["M11"].verdict is Judgement.PRESENT
    assert findings["M11"].resolved is True


def test_the_budget_trips_before_the_parent_timeout(tmp_path: Path) -> None:
    """A runaway must be reported, not lost to the kill that stops it.

    The analysis writes its summary when the child shuts down, so a parent
    that kills the child first takes every observation with it. The looping
    budget is derived from the timeout precisely so the submission is
    stopped from the inside while there is still someone to tell.
    """
    submission = tmp_path / "submission.py"
    submission.write_text(
        "def contar(n: int) -> int:\n"
        "    i = 0\n"
        "    total = 0\n"
        "    while i < n:\n"
        "        total = total + 1\n"
        "    return total\n",
        encoding="utf-8",
    )
    driver = tmp_path / "driver.py"
    driver.write_text("from submission import contar\ncontar(5)\n", encoding="utf-8")

    report = scan_metrics_file(
        submission, level=3, dynamic=True, driver=driver, timeout=12
    )

    assert report.diagnostics.get("dynamic") == "executed"
    assert report.diagnostics.get("budget_exceeded") is True
    assert not any("timed out" in note for note in report.diagnostics.get("dynamic_errors", []))
    nonterminating = report.by_id("M11")
    assert nonterminating is not None
    assert nonterminating.verdict is Judgement.PRESENT
    assert nonterminating.resolved is True


def test_m11_refutes_a_loop_that_stops(tmp_path: Path) -> None:
    findings = profile(
        tmp_path,
        "def contar(n: int) -> int:\n"
        "    i = 0\n"
        "    total = 0\n"
        "    while i < n:\n"
        "        total = total + 1\n"
        "        i = i + 1\n"
        "    return total\n",
        "from submission import contar\ncontar(5)\n",
    )
    assert findings["M11"].verdict in (Judgement.ABSENT, Judgement.NOT_APPLICABLE)


# -- M15: the value that was there --------------------------------------


def test_m15_confirms_a_rewrite_that_writes_back_an_equal_value(tmp_path: Path) -> None:
    """Equality is not the question: the first computation was still lost."""
    findings = profile(
        tmp_path,
        "def area(largo: float, ancho: float) -> float:\n"
        "    a = largo * ancho\n"
        "    a = round(largo * ancho, 2)\n"
        "    return a\n",
        "from submission import area\narea(3.0, 4.0)\n",
        level=1,
    )
    assert findings["M15"].verdict is Judgement.PRESENT
    assert findings["M15"].resolved is True


# -- the distinction the whole design rests on --------------------------


def test_a_metric_the_run_never_reached_is_not_reported_as_clean(
    tmp_path: Path,
) -> None:
    """A driver that calls nothing must leave the candidates unresolved."""
    submission = tmp_path / "submission.py"
    submission.write_text(
        "def todos_positivos(numeros: list) -> bool:\n"
        "    for n in numeros:\n"
        "        if n > 0:\n"
        "            return True\n"
        "        else:\n"
        "            return False\n",
        encoding="utf-8",
    )
    driver = tmp_path / "driver.py"
    driver.write_text("import submission\n", encoding="utf-8")

    report = scan_metrics_file(
        submission, level=3, dynamic=True, driver=driver, timeout=60
    )
    premature = report.by_id("M06")
    assert premature is not None
    assert premature.verdict is Judgement.PRESENT
    assert premature.resolved is False
    assert "M06" in report.diagnostics["unresolved"]
