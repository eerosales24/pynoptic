from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

__all__ = [
    "Level",
    "NccKind",
    "Tool",
    "Restriction",
    "Location",
    "Detection",
    "Finding",
    "Report",
    "Verdict",
    "SemgrepSpec",
    "AstSpec",
    "DynamicMatch",
]


class Level(IntEnum):
    """A course level. CS1 progresses cumulatively through four levels."""

    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4

    @classmethod
    def parse(cls, value: Level | int | str) -> Level:
        """Normalise a level given in any accepted form.

        Parameters:
            - value: A Level, an int 1-4, or a string such as
              "Level 2", "L2" or "2".

        Returns:
            - The matching Level.

        Raises:
            - ValueError: If the value is not a valid level.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):  # guard: bool is an int subclass
            raise ValueError(f"Invalid level: {value!r}")
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, str):
            text = value.strip().lower().replace("level", "").strip()
            text = text.removeprefix("l").strip()
            return cls(int(text))
        raise ValueError(f"Invalid level: {value!r}")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Level {self.value}"


class NccKind(StrEnum):
    """Granularity of a Non-Curricular Construct occurrence."""

    COURSE_WIDE = "course-wide"
    LEVEL_RELATIVE = "level-relative"


class Tool(StrEnum):
    """Detector responsible for a restriction, as declared in the catalog."""

    SEMGREP = "semgrep"
    AST = "ast"
    HYBRID = "semgrep+dynapyt"


@dataclass(frozen=True)
class DynamicMatch:
    """How a restriction is classified once the runtime type is known.

    Parameters:
        - hook: The DynaPyt hook that delivers the event (e.g. pre_call).
        - names: The method/operator names it fires for, or "slice" /
          "negative_index".
        - accepts: The observed type categories that select this restriction;
          an empty tuple matches any type.
        - candidate: The static Semgrep candidate this restriction resolves.
    """

    hook: str
    names: tuple[str, ...]
    accepts: tuple[str, ...]
    candidate: str


@dataclass(frozen=True)
class Restriction:
    """One row of the restriction catalog.

    Parameters:
        - id: Unique restriction identifier, prefixed with R.
        - restriction: Short name of what must not be used.
        - scope: Last level at which the construct is off-limits.
        - tool: The detector responsible for the restriction.
        - technique: How that detector identifies it.
        - note: Why it needs that technique and what detection may miss.
        - semgrep: The Semgrep rule for this restriction, when it is detected
          statically by Semgrep.
        - ast: The ast detector label, when it is detected by the ast
          engine.
        - candidate: A Semgrep candidate pattern for a statically ambiguous
          construct that DynaPyt later resolves.
        - conclusive: Whether a candidate is already definitive statically.
        - dynamic: The runtime triggers that classify the construct.
    """

    id: str
    restriction: str
    scope: Level
    tool: Tool
    technique: str
    note: str = ""
    semgrep: SemgrepSpec | None = None
    ast: str | None = None
    candidate: SemgrepSpec | None = None
    conclusive: bool = False
    dynamic: tuple[DynamicMatch, ...] = ()

    def is_ncc(self, exercise_level: Level | int | str) -> bool:
        """Return whether this restriction is off-limits at a level.

        Parameters:
            - exercise_level: The level of the exercise being audited, given
              as a Level, an int, or a string like "Level 2".

        Returns:
            - True when the construct is a Non-Curricular Construct, meaning
              its scope is at or above exercise_level.
        """
        level = Level.parse(exercise_level)
        return self.scope >= level

    def kind_at(self, exercise_level: Level | int | str) -> NccKind | None:
        """Return the NCC granularity of this restriction at a level.

        Parameters:
            - exercise_level: The level of the exercise being audited.

        Returns:
            - NccKind.COURSE_WIDE when the scope is Level 4,
              NccKind.LEVEL_RELATIVE when it is a lower level, or None
              when the construct is allowed.
        """
        if not self.is_ncc(exercise_level):
            return None
        if self.scope == Level.L4:
            return NccKind.COURSE_WIDE
        return NccKind.LEVEL_RELATIVE


@dataclass(frozen=True)
class Location:
    """A source span, 1-indexed to match editor conventions."""

    file: str | None = None
    line: int = 0
    column: int = 0
    end_line: int | None = None
    end_column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the location as a JSON-serialisable dictionary."""
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True)
class Detection:
    """A raw detection emitted by one detector, before level classification.

    Keeping detections independent of a Restriction and its NccKind
    lets the static and dynamic engines stay decoupled from the catalog and
    lets the engine attribute a candidate to different restrictions depending
    on the runtime types it observes.

    Parameters:
        - restriction_id: The restriction this detection refers to.
        - detector: The tool that produced it (ast, semgrep,
          dynapyt).
        - location: The source span where it occurred.
        - resolved: Whether the construct's type is known; False marks an
          unresolved static candidate.
        - candidate: For static Semgrep candidates, the candidate id they
          belong to; empty for definitive detections.
    """

    restriction_id: str
    detector: str
    location: Location = field(default_factory=Location)
    resolved: bool = True
    candidate: str = ""


@dataclass(frozen=True)
class Finding:
    """A detected (or candidate) use of a restriction.

    Parameters:
        - restriction: The matched restriction.
        - kind: Whether the occurrence is course-wide or level-relative.
        - detector: The tool that produced it.
        - location: The source span where it occurred.
        - resolved: False for a statically ambiguous candidate whose
          runtime type was never observed (e.g. a branch no test input
          reached).
        - candidate: The static candidate id this finding resolves, or empty
          for definitive detections.
    """

    restriction: Restriction
    kind: NccKind
    detector: str
    location: Location = field(default_factory=Location)
    resolved: bool = True
    candidate: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the finding as a JSON-serialisable dictionary."""
        return {
            "restriction_id": self.restriction.id,
            "restriction": self.restriction.restriction,
            "scope": int(self.restriction.scope),
            "kind": self.kind.value,
            "detector": self.detector,
            "resolved": self.resolved,
            "candidate": self.candidate,
            "location": self.location.to_dict(),
        }


@dataclass(frozen=True)
class Verdict:
    """Occurrence counts for one submission, after suppression and collapse.

    Parameters:
        - exercise_level: The level the submission was audited against.
        - violations: Restriction id -> number of counted occurrences.
        - ambiguous: Ambiguous group -> number of uncounted occurrences.
    """

    exercise_level: Level
    violations: dict[str, int] = field(default_factory=dict)
    ambiguous: dict[str, int] = field(default_factory=dict)

    @property
    def n_violations(self) -> int:
        """Total number of counted violation occurrences."""
        return sum(self.violations.values())

    @property
    def n_ambiguous(self) -> int:
        """Total number of ambiguous, uncounted occurrences."""
        return sum(self.ambiguous.values())

    @property
    def compliant(self) -> bool:
        """True when no occurrence was counted as a violation."""
        return self.n_violations == 0

    def to_dict(self) -> dict[str, Any]:
        """Return the verdict as a JSON-serialisable dictionary."""
        return {
            "level": int(self.exercise_level),
            "n_violations": self.n_violations,
            "violations": self.violations,
            "ambiguous": self.ambiguous,
            "n_ambiguous": self.n_ambiguous,
            "compliant": self.compliant,
        }


@dataclass
class Report:
    """The NCC audit of a single submission.

    Parameters:
        - exercise_level: The level the submission was audited against.
        - findings: The NCCs found, resolved or unresolved.
        - syntax_error: Whether the submission failed to parse.
        - diagnostics: Tool-specific notes, such as Semgrep or DynaPyt errors.
        - verdict: Occurrence counts, or None when not computed.
    """

    exercise_level: Level
    findings: list[Finding] = field(default_factory=list)
    syntax_error: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    verdict: Verdict | None = None

    @property
    def course_wide(self) -> list[Finding]:
        """Findings whose construct is outside the whole CS1 subset."""
        return [f for f in self.findings if f.kind is NccKind.COURSE_WIDE]

    @property
    def level_relative(self) -> list[Finding]:
        """Findings whose construct is curricular only at a later level."""
        return [f for f in self.findings if f.kind is NccKind.LEVEL_RELATIVE]

    @property
    def unresolved(self) -> list[Finding]:
        """Candidates that never executed, so their type is unknown."""
        return [f for f in self.findings if not f.resolved]

    @property
    def restriction_ids(self) -> set[str]:
        """The distinct restriction ids present in the report."""
        return {f.restriction.id for f in self.findings}

    def extend(self, findings: Iterable[Finding]) -> None:
        """Append several findings to the report.

        Parameters:
            - findings: The findings to add.
        """
        self.findings.extend(findings)

    def to_dict(self) -> dict[str, Any]:
        """Return the report as a JSON-serialisable dictionary."""
        payload: dict[str, Any] = {
            "exercise_level": int(self.exercise_level),
            "syntax_error": self.syntax_error,
            "diagnostics": self.diagnostics,
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.verdict is not None:
            payload["verdict"] = self.verdict.to_dict()
        return payload


# --------------------------------------------------------------------------
# Detector specs
#
# These describe *how* a restriction is detected. They are kept separate from
# the human-facing catalog and are linked by restriction id, so that the two
# can be validated against each other.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SemgrepSpec:
    """A Semgrep detection.

    pattern is a single pattern; patterns are a list of Semgrep pattern
    dictionaries that are ANDed; either are simple patterns ORed together;
    regex is a lexical pattern-regex over the source.
    """

    pattern: str | None = None
    patterns: tuple[dict[str, Any], ...] = ()
    either: tuple[str, ...] = ()
    regex: str | None = None
    message: str = ""

    def to_rule(self, restriction: Restriction) -> dict[str, Any]:
        """Turn this spec into a Semgrep rule dictionary.

        Parameters:
            - restriction: The restriction the rule detects, used for the rule
              id, message and metadata.

        Returns:
            - A Semgrep rule ready to be serialised to YAML.
        """
        rule: dict[str, Any] = {
            "id": restriction.id,
            "languages": ["python"],
            "severity": "INFO",
            "metadata": {
                "rule_id": restriction.id,
                "restriction": restriction.restriction,
                "scope": int(restriction.scope),
            },
            "message": self.message or f"Detected: {restriction.restriction}",
        }
        if self.regex is not None:
            rule["pattern-regex"] = self.regex
        elif self.patterns:
            rule["patterns"] = list(self.patterns)
        elif self.either:
            rule["pattern-either"] = [{"pattern": p} for p in self.either]
        elif self.pattern is not None:
            rule["pattern"] = self.pattern
        else:  # pragma: no cover - guarded by tests
            raise ValueError(f"Empty SemgrepSpec for {restriction.id}")
        return rule


@dataclass(frozen=True)
class AstSpec:
    """A Python ast detector, looked up by name in the detector registry."""

    detector: str
