"""Reconcile the catalog with the shipped prompt templates.

A metric whose template is missing, or whose template forgets to include the
code, produces a prompt that looks fine and measures nothing.
"""

from __future__ import annotations

import pytest

from pynoptic.metrics import CATALOG, Shape, get_metric
from pynoptic.metrics.llm import ExerciseSpec, load_template, number_source, render_prompt
from pynoptic.metrics.llm.render import NO_CONTEXT, PROMPT_FIELDS

SOURCE = "def f(xs):\n    for x in xs:\n        return x > 0\n    return False\n"


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_metric_ships_a_template(metric: object) -> None:
    assert load_template(metric).strip()  # type: ignore[arg-type]


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_template_offers_every_placeholder(metric: object) -> None:
    template = load_template(metric)  # type: ignore[arg-type]
    for field in PROMPT_FIELDS:
        assert "{" + field + "}" in template, field


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_rendering_leaves_no_placeholder_behind(metric: object) -> None:
    prompt = render_prompt(metric, SOURCE)  # type: ignore[arg-type]
    for field in PROMPT_FIELDS:
        assert "{" + field + "}" not in prompt


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_prompt_carries_the_numbered_code(metric: object) -> None:
    """Without the listing the judge has nothing to anchor a line to."""
    prompt = render_prompt(metric, SOURCE)  # type: ignore[arg-type]
    assert "1  def f(xs):" in prompt
    assert "4      return False" in prompt


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_prompt_demands_json_and_offers_the_vocabulary(metric: object) -> None:
    prompt = render_prompt(metric, SOURCE)  # type: ignore[arg-type]
    assert "JSON" in prompt
    for token in ("SI", "NO_APLICA", "NO_DECIDIBLE"):
        assert token in prompt, token


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_prompt_states_both_escape_hatches(metric: object) -> None:
    """An answer with nowhere to say 'not applicable' invents one instead."""
    prompt = render_prompt(metric, SOURCE)  # type: ignore[arg-type]
    assert "`NO_APLICA` si" in prompt
    assert "`NO_DECIDIBLE` si" in prompt


@pytest.mark.parametrize("metric", CATALOG, ids=[m.id for m in CATALOG])
def test_every_prompt_asks_about_exactly_one_metric(metric: object) -> None:
    """Ten dimensions in one prompt is what produced thirty neutral answers."""
    prompt = render_prompt(metric, SOURCE)  # type: ignore[arg-type]
    assert prompt.count("## Qué buscar") == 1


def test_counting_prompts_ask_for_a_number() -> None:
    for metric in CATALOG:
        if metric.shape is not Shape.COUNT:
            continue
        assert '"n": <int>' in render_prompt(metric, SOURCE), metric.id


def test_the_class_prompt_offers_the_growth_classes() -> None:
    prompt = render_prompt(get_metric("M13"), SOURCE)
    assert '"clase_estudiante"' in prompt
    assert "desconocida" in prompt


def test_context_is_optional_and_says_so() -> None:
    without = render_prompt(get_metric("M06"), SOURCE)
    assert NO_CONTEXT in without

    with_spec = render_prompt(
        get_metric("M06"),
        SOURCE,
        spec=ExerciseSpec(statement="Decide si todos son positivos.", level=3),
    )
    assert "Decide si todos son positivos." in with_spec
    assert NO_CONTEXT not in with_spec


def test_line_numbers_are_one_indexed_and_aligned() -> None:
    numbered = number_source("a\nb\nc\n")
    assert numbered.splitlines()[0].startswith("1  ")
    assert numbered.splitlines()[2].startswith("3  ")


def test_numbering_pads_to_the_widest_line_number() -> None:
    numbered = number_source("\n".join(str(i) for i in range(1, 12)))
    assert numbered.splitlines()[0].startswith(" 1  ")
    assert numbered.splitlines()[10].startswith("11  ")
