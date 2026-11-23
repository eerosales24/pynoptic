"""Behavioural tests for every static metric detector.

Every fixture is synthetic and minimal. None of it comes from a corpus: the
package is published, and student submissions are not ours to publish.

Each metric is asserted three ways, because all three are part of the
contract the LLM judge is held to as well: the phenomenon present, the
phenomenon absent, and the construct missing entirely.
"""

from __future__ import annotations

import pytest

from pynoptic.metrics import Judgement, Shape, get_metric, scan_metrics
from pynoptic.metrics.models import MetricFinding


def verdict_for(metric_id: str, source: str) -> MetricFinding:
    """Scan a snippet at the highest level and return one metric's finding.

    Parameters:
        - metric_id: The catalog id to look up.
        - source: The snippet to analyse.

    Returns:
        - The finding for that metric.
    """
    report = scan_metrics(source, level=4)
    assert report.diagnostics.get("detector_errors") is None
    finding = report.by_id(metric_id)
    assert finding is not None, f"{metric_id} produced no finding"
    return finding


PRESENT: list[tuple[str, str]] = [
    ("M01", "def f(a, b):\n    return a\n"),
    ("M02", 'def f(t):\n    if "a" or "b" in t:\n        return 1\n    return 0\n'),
    ("M03", "def f(a):\n    if a > 0:\n        b = 1\n    else:\n        b = 1\n    return b\n"),
    ("M04", "def f(a, b, c):\n    return a or b and c\n"),
    (
        "M05",
        "def f(xs):\n"
        "    total = sum(xs) + len(xs) * 2\n"
        "    total = sum(xs) + len(xs) * 2\n"
        "    return total\n",
    ),
    ("M06", "def f(xs):\n    for x in xs:\n        return x > 0\n    return False\n"),
    ("M07", 'def f(a):\n    if a:\n        return "x"\n    return 0\n'),
    (
        "M08",
        "def f(x):\n    if x > 5:\n        return 1\n"
        "    elif x > 10:\n        return 2\n    return 3\n",
    ),
    (
        "M09",
        "def f(xs):\n"
        "    a = 0\n"
        "    for x in xs:\n"
        "        a += x\n"
        "    b = 1\n"
        "    for x in xs:\n"
        "        b += x\n"
        "    return a + b\n",
    ),
    (
        "M10",
        "def f(xs):\n"
        "    found = False\n"
        "    for x in xs:\n"
        "        if x < 0:\n"
        "            found = True\n"
        "    return found\n",
    ),
    ("M11", "def f(n):\n    i = 0\n    while i < n:\n        pass\n    return i\n"),
    (
        "M12",
        "def f(xs):\n"
        "    counts = {}\n"
        "    for x in xs:\n"
        "        counts[x] = 1\n"
        "    return counts[xs[0]]\n",
    ),
    (
        "M13",
        "def f(xs):\n"
        "    seen = []\n"
        "    n = 0\n"
        "    for x in xs:\n"
        "        if x in seen:\n"
        "            n += 1\n"
        "    return n\n",
    ),
    (
        "M14",
        'def f(s):\n    out = ""\n    for i in range(len(s)):\n'
        "        out += s[i:]\n    return out\n",
    ),
    ("M15", "def f(xs):\n    total = sum(xs)\n    total = len(xs)\n    return total\n"),
    ("M16", "def f(a, b, c, d):\n    e = a + b\n    g = c + d\n    return e + g\n"),
    (
        "M17",
        "def f(xs):\n"
        "    # Recorremos todos los elementos de la lista\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        total += x\n"
        "    return total\n",
    ),
]

ABSENT: list[tuple[str, str]] = [
    ("M01", "def f(a, b):\n    return a + b\n"),
    ("M02", 'def f(t):\n    if "a" in t:\n        return 1\n    return 0\n'),
    ("M03", "def f(a):\n    if a > 0:\n        b = 1\n    else:\n        b = 2\n    return b\n"),
    ("M04", "def f(a, b, c):\n    return a or (b and c)\n"),
    (
        "M05",
        "def f(xs):\n"
        "    total = sum(xs) + len(xs) * 2\n"
        "    other = sum(xs) + len(xs) * 3\n"
        "    return total + other\n",
    ),
    ("M06", "def f(xs):\n    total = 0\n    for x in xs:\n        total += x\n    return total\n"),
    ("M07", "def f(a):\n    if a:\n        return 1\n    return 0\n"),
    (
        "M08",
        "def f(x):\n    if x > 10:\n        return 1\n"
        "    elif x > 5:\n        return 2\n    return 3\n",
    ),
    ("M09", "def f(xs):\n    a = 0\n    for x in xs:\n        a += x\n    return a\n"),
    (
        "M10",
        "def f(xs):\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        if x < 0:\n"
        "            total += x\n"
        "    return total\n",
    ),
    ("M11", "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    return i\n"),
    (
        "M12",
        "def f(xs):\n"
        "    counts = {}\n"
        "    for x in xs:\n"
        "        counts[x] = 1\n"
        "    if xs[0] in counts:\n"
        "        return counts[xs[0]]\n"
        "    return 0\n",
    ),
    ("M13", "def f(xs):\n    n = 0\n    for x in xs:\n        n += x\n    return n\n"),
    ("M14", "def f(s):\n    n = 0\n    for c in s:\n        n += 1\n    return n\n"),
    ("M15", "def f(xs):\n    total = sum(xs)\n    return total\n"),
    (
        "M16",
        "def f(numerador, denominador):\n"
        "    resultado = numerador / denominador\n"
        "    total = resultado * 2\n"
        "    return total\n",
    ),
    (
        "M17",
        "def f(xs):\n"
        "    # 1e-9 absorbs the rounding error from the division above\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        total += x\n"
        "    return total\n",
    ),
]

NOT_APPLICABLE: list[tuple[str, str]] = [
    ("M01", "def f():\n    return 1\n"),
    ("M02", "def f(a):\n    return a\n"),
    ("M03", "def f(a):\n    if a > 0:\n        return 1\n    return 0\n"),
    ("M04", "def f(a, b):\n    return a or b\n"),
    ("M06", "def f(a):\n    return a\n"),
    ("M07", "def f(a):\n    print(a)\n"),
    ("M08", "def f(x):\n    return x\n"),
    ("M09", "def f(a):\n    return a\n"),
    ("M10", "def f(a):\n    return a\n"),
    ("M11", "def f(xs):\n    for x in xs:\n        pass\n    return 1\n"),
    ("M12", "def f(xs):\n    return len(xs)\n"),
    ("M13", "def f(a):\n    return a\n"),
    ("M14", "def f(a):\n    return a\n"),
    ("M16", "def f(a):\n    return a\n"),
    ("M17", "def f(a):\n    return a\n"),
]


@pytest.mark.parametrize(("metric_id", "source"), PRESENT, ids=[c[0] for c in PRESENT])
def test_the_phenomenon_is_detected(metric_id: str, source: str) -> None:
    finding = verdict_for(metric_id, source)
    assert finding.verdict is Judgement.PRESENT
    assert finding.evidence, "a positive verdict must be anchored to a line"
    for item in finding.evidence:
        assert item.line >= 1
        assert item.line <= len(source.splitlines())


@pytest.mark.parametrize(("metric_id", "source"), ABSENT, ids=[c[0] for c in ABSENT])
def test_clean_code_is_not_flagged(metric_id: str, source: str) -> None:
    assert verdict_for(metric_id, source).verdict is Judgement.ABSENT


@pytest.mark.parametrize(
    ("metric_id", "source"), NOT_APPLICABLE, ids=[c[0] for c in NOT_APPLICABLE]
)
def test_a_missing_construct_is_not_applicable(metric_id: str, source: str) -> None:
    finding = verdict_for(metric_id, source)
    assert finding.verdict is Judgement.NOT_APPLICABLE
    assert finding.data.get("reason"), "NO_APLICA must say what was missing"


def test_every_metric_has_a_positive_and_a_negative_case() -> None:
    """A metric nobody exercised is a metric nobody knows works."""
    from pynoptic.metrics import CATALOG

    covered_present = {metric_id for metric_id, _ in PRESENT}
    covered_absent = {metric_id for metric_id, _ in ABSENT}
    declared = {m.id for m in CATALOG}
    assert covered_present == declared
    assert covered_absent == declared


def test_counting_metrics_report_a_number() -> None:
    for metric_id, source in PRESENT:
        if get_metric(metric_id).shape is not Shape.COUNT:
            continue
        finding = verdict_for(metric_id, source)
        assert int(finding.data["n"]) >= 1


#: Metrics whose positive verdict is a suspicion, not a finding: the shape is
#: there but only a run can say whether it was a defect. A legitimate early
#: return looks like a premature decision; a loop that walks everything may be
#: doing the work the statement asked for; a key may be guaranteed present.
CANDIDATES = frozenset({"M06", "M09", "M10", "M11", "M12", "M13", "M14", "M15"})

#: The complement: the tree settles these outright. An unread parameter, two
#: identical branches, a bare literal in a test — none of them need a run.
CONCLUSIVE = frozenset({"M01", "M02", "M03", "M04", "M05", "M07", "M08", "M16", "M17"})


def test_the_two_groups_cover_the_catalog() -> None:
    from pynoptic.metrics import CATALOG

    assert CANDIDATES | CONCLUSIVE == {m.id for m in CATALOG}
    assert not CANDIDATES & CONCLUSIVE


@pytest.mark.parametrize(("metric_id", "source"), PRESENT, ids=[c[0] for c in PRESENT])
def test_candidates_do_not_pass_as_settled(metric_id: str, source: str) -> None:
    """A suspicion that reports itself as resolved would never be revisited."""
    expected_resolved = metric_id in CONCLUSIVE
    assert verdict_for(metric_id, source).resolved is expected_resolved


def test_every_candidate_declares_a_runtime_hook() -> None:
    """Something has to be able to settle it later, or it never resolves."""
    assert [m for m in CANDIDATES if not get_metric(m).dynamic] == []
