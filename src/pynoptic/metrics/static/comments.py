"""Metric about comments that do not fit the code they sit on.

This one has consequences for a person, so it is a count of flags for a human
to read, never a verdict. The catalog marks its oracle as partial: a
docstring that documents parameters the signature does not have is decidable,
while register and voice are not.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

from ..models import Evidence, Judgement, MetricDetection
from .context import FunctionContext
from .registry import detector

#: First-person-plural narration of the obvious, in Spanish and English. It
#: is a flag, not proof: a student may well write this way.
NARRATION = re.compile(
    r"\b("
    r"inicializamos|recorremos|creamos|definimos|calculamos|verificamos|"
    r"comprobamos|retornamos|devolvemos|guardamos|obtenemos|recorriendo|"
    r"we\s+(initialize|iterate|create|define|calculate|check|return|store|get)"
    r")\b",
    re.IGNORECASE,
)
#: A docstring parameter line: "name (type): description".
DOC_PARAM = re.compile(r"^\s*(\w+)\s*\(", re.MULTILINE)
#: Names that appear in a parameter block without being parameters.
DOC_NOISE = frozenset({"int", "str", "float", "list", "dict", "bool", "tuple", "set", "None"})


def _comment_lines(source: str) -> list[tuple[int, str]]:
    """Return the standalone comments in the source.

    tokenize is used rather than a regex so a `#` inside a string literal is
    not mistaken for a comment.

    Parameters:
        - source: The submission's source code.

    Returns:
        - Pairs of (line number, comment text).
    """
    found: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], token.string.lstrip("# ").strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return found
    return found


@detector("m17_suspicious_comments")
def suspicious_comments(ctx: FunctionContext) -> MetricDetection:
    """Count comments that do not match the code around them.

    Two shapes are flagged: a docstring that documents parameters the
    signature does not declare, which the tree settles outright, and comments
    that narrate the obvious in the first person plural, which it does not.

    Parameters:
        - ctx: The function under audit.

    Returns:
        - PRESENT with one Evidence per flag, ABSENT, or NOT_APPLICABLE when
          the function carries neither comments nor a docstring.
    """
    comments = _comment_lines(ctx.source)
    docstring = ast.get_docstring(ctx.node)
    if not comments and not docstring:
        return MetricDetection(
            metric_id="M17",
            verdict=Judgement.NOT_APPLICABLE,
            data={"reason": "the function has no comments or docstring"},
        )

    hits: list[Evidence] = []
    for line, text in comments:
        if NARRATION.search(text):
            hits.append(
                Evidence(
                    line=line,
                    element=text[:60],
                    detail="narrates the step rather than explaining it",
                )
            )

    if docstring and ctx.params:
        documented = {m for m in DOC_PARAM.findall(docstring)} - DOC_NOISE
        phantom = sorted(documented - ctx.params)
        if phantom:
            hits.append(
                Evidence(
                    line=ctx.node.lineno,
                    element=", ".join(phantom),
                    detail="documented but not in the signature",
                )
            )

    if not hits:
        return MetricDetection(metric_id="M17", verdict=Judgement.ABSENT, data={"n": 0})
    return MetricDetection(
        metric_id="M17",
        verdict=Judgement.PRESENT,
        evidence=tuple(sorted(hits, key=lambda e: e.line)),
        data={"n": len(hits)},
    )
