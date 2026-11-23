"""Level parsing and the NCC classification rule."""

from __future__ import annotations

import pytest

from pynoptic.models import Level, NccKind, SemgrepSpec
from pynoptic.restrictions import get_restriction


@pytest.mark.parametrize(
    "value",
    [2, "2", "L2", "l2", "Level 2", "level 2", Level.L2],
)
def test_level_parse_accepts_the_documented_forms(value: object) -> None:
    assert Level.parse(value) is Level.L2  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, 0, 5, "L9", "", "two"])
def test_level_parse_rejects_everything_else(value: object) -> None:
    with pytest.raises(ValueError):
        Level.parse(value)  # type: ignore[arg-type]


def test_level_str_is_human_readable() -> None:
    assert str(Level.L3) == "Level 3"


def test_is_ncc_holds_from_the_scope_downwards() -> None:
    """A restriction is off-limits at its own level and at every lower one."""
    r = get_restriction("R110")  # list comprehension, scope Level 4
    assert r.scope is Level.L4
    assert r.is_ncc(Level.L1) is True
    assert r.is_ncc(Level.L4) is True


def test_kind_at_separates_course_wide_from_level_relative() -> None:
    course_wide = get_restriction("R110")
    assert course_wide.kind_at(Level.L2) is NccKind.COURSE_WIDE

    relative = next(r for r in (get_restriction("R1"),) if r.scope is Level.L1)
    assert relative.kind_at(Level.L1) is NccKind.LEVEL_RELATIVE
    assert relative.kind_at(Level.L2) is None


def test_empty_semgrep_spec_is_rejected() -> None:
    with pytest.raises(ValueError):
        SemgrepSpec().to_rule(get_restriction("R1"))


def test_location_round_trips_to_dict() -> None:
    from pynoptic.models import Location

    payload = Location(file="a.py", line=3, column=1, end_line=3, end_column=9).to_dict()
    assert payload == {
        "file": "a.py",
        "line": 3,
        "column": 1,
        "end_line": 3,
        "end_column": 9,
    }
