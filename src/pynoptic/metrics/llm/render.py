"""Build the exact prompt sent to a judge for one metric and one submission.

Three choices here are measured rather than stylistic, and changing them
invalidates comparisons against earlier runs:

- **One metric per prompt.** Asking for ten dimensions at once is what made a
  3B model answer the neutral option thirty times out of thirty.
- **Numbered source and mandatory evidence.** With the line requirement,
  94.1% of reported findings cited a line that existed and contained what was
  claimed. Without it, a model asserted a `== True` comparison on a line that
  was an assignment.
- **The exercise statement is optional.** The tool has to run on code with no
  statement and no reference solution attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from ..models import Metric
from .schema import schema_for

__all__ = ["ExerciseSpec", "PROMPT_FIELDS", "load_template", "render_prompt"]

#: Every template must offer these, so a renderer change cannot silently drop
#: the code or the schema from a prompt.
PROMPT_FIELDS = ("contexto", "codigo_numerado", "esquema")

NO_CONTEXT = (
    "No se proporciona el enunciado del ejercicio. Juzga únicamente con el "
    "código que tienes delante y, si te falta información para decidir, "
    "responde `NO_DECIDIBLE`."
)


@dataclass(frozen=True)
class ExerciseSpec:
    """What is known about the exercise, all of it optional."""

    statement: str = ""
    signature: str = ""
    returns: str = ""
    returns_description: str = ""
    level: int | None = None

    def render(self) -> str:
        """Return the context block, or the no-context notice.

        Returns:
            - Markdown describing the exercise.
        """
        lines: list[str] = []
        if self.statement.strip():
            lines.append(f"**Enunciado.** {self.statement.strip()}")
        if self.signature.strip():
            lines.append(f"**Firma esperada.** `{self.signature.strip()}`")
        if self.returns.strip():
            described = f" — {self.returns_description.strip()}" if self.returns_description else ""
            lines.append(f"**Devuelve.** `{self.returns.strip()}`{described}")
        if self.level is not None:
            lines.append(f"**Nivel del curso.** {self.level}")
        return "\n\n".join(lines) if lines else NO_CONTEXT


def number_source(source: str) -> str:
    """Return the source with one-indexed line numbers prepended.

    Parameters:
        - source: The submission's code.

    Returns:
        - The numbered listing used in every prompt.
    """
    lines = source.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, start=1))


def load_template(metric: Metric) -> str:
    """Read a metric's prompt template from the package.

    Parameters:
        - metric: The catalog entry whose prompt is wanted.

    Returns:
        - The template text.

    Raises:
        - FileNotFoundError: When the catalog names a template that is not
          shipped. The reconciliation test exists to stop that reaching here.
    """
    resource = files("pynoptic.metrics").joinpath("prompts", metric.prompt)
    return resource.read_text(encoding="utf-8")


def render_prompt(
    metric: Metric,
    source: str,
    *,
    spec: ExerciseSpec | None = None,
) -> str:
    """Build the prompt for one metric and one submission.

    Parameters:
        - metric: The catalog entry being asked about.
        - source: The submission's code.
        - spec: What is known about the exercise, when anything is.

    Returns:
        - The prompt, ready to send.
    """
    # Substituting the known placeholders by name rather than with str.format
    # keeps braces inside the prompt's own examples intact: several metrics
    # illustrate themselves with a dict literal.
    filled = load_template(metric)
    for name, value in (
        ("contexto", (spec or ExerciseSpec()).render()),
        ("codigo_numerado", number_source(source)),
        ("esquema", schema_for(metric)),
    ):
        filled = filled.replace("{" + name + "}", value)
    return filled
