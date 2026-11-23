"""Build prompts for an LLM judge and check what it answers.

The subsystem's purpose is comparison: the judge and the detector answer the
same question in the same vocabulary, so the agreement between them is a
measurement rather than a translation.
"""

from __future__ import annotations

from .render import ExerciseSpec, load_template, number_source, render_prompt
from .schema import Answer, InvalidAnswer, parse_answer, schema_for

__all__ = [
    "Answer",
    "ExerciseSpec",
    "InvalidAnswer",
    "load_template",
    "number_source",
    "parse_answer",
    "render_prompt",
    "schema_for",
]
