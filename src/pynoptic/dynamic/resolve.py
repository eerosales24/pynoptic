"""Runtime classification of statically ambiguous constructs.

Python reuses one name or operator across several types. Each hybrid
restriction declares, in the catalog, the runtime trigger that selects it
(:class:`~pynoptic.models.DynamicMatch`). This module builds a small derived
index from those triggers and matches observed runtime facts against it, so
there is no hand-maintained name-to-restriction map.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pynoptic.models import DynamicMatch, Restriction
from pynoptic.restrictions import restrictions


@dataclass(frozen=True)
class Match:
    """A restriction selected by a runtime observation.

    Parameters:
        - restriction_id: The restriction the observation denotes.
        - candidate: The static candidate the observation resolves.
    """

    restriction_id: str
    candidate: str


@dataclass(frozen=True)
class Outcome:
    """The result of classifying one runtime event.

    Parameters:
        - matches: The restrictions the event denotes.
        - refuted: The static candidates that were reached but turned out to be
          unrestricted (e.g. 2 * 3 refutes the list-repetition candidate
          R55).
    """

    matches: tuple[Match, ...] = ()
    refuted: tuple[str, ...] = ()


def _build() -> tuple[
    dict[tuple[str, str], list[tuple[Restriction, DynamicMatch]]],
    dict[tuple[str, str], tuple[str, ...]],
]:
    """Index the catalog's dynamic triggers by (hook, name).

    Returns:
        - A map from (hook, name) to the restrictions and triggers that
          fire for it.
        - A map from (hook, name) to the static candidate ids those
          restrictions resolve, used to refute candidates.
    """
    index: dict[tuple[str, str], list[tuple[Restriction, DynamicMatch]]] = {}
    candidates: dict[tuple[str, str], set[str]] = {}
    for restriction in restrictions():
        for match in restriction.dynamic:
            for name in match.names:
                key = (match.hook, name)
                index.setdefault(key, []).append((restriction, match))
                candidates.setdefault(key, set()).add(match.candidate)
    return index, {key: tuple(sorted(value)) for key, value in candidates.items()}


_DYNAMIC_INDEX, _CANDIDATES = _build()


def category(value: object) -> str | None:
    """Map a runtime value to the coarse type category used by triggers.

    Parameters:
        - value: Any runtime value observed by the analysis.

    Returns:
        - A category such as "int", "str", "list", "set",
          "dict" or "tuple", or None for values with no category
          (including booleans).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (set, frozenset)):
        return "set"
    return None


def match_dynamic(hook: str, name: str, categories: Iterable[str]) -> list[Match]:
    """Return the restrictions whose trigger matches an event.

    Parameters:
        - hook: The DynaPyt hook that delivered the event.
        - name: The method/operator name, or "slice" / "negative_index".
        - categories: The observed type categories.

    Returns:
        - The matching restrictions, or an empty list when the event is not a
          restriction.
    """
    observed = set(categories)
    found: list[Match] = []
    for restriction, match in _DYNAMIC_INDEX.get((hook, name), ()):
        if not match.accepts or (set(match.accepts) & observed):
            found.append(Match(restriction.id, match.candidate))
    return found


def resolve_dynamic(hook: str, name: str, categories: Iterable[str]) -> Outcome:
    """Classify a runtime event, refuting candidates when nothing matches.

    Parameters:
        - hook: The DynaPyt hook that delivered the event.
        - name: The method/operator name, or "slice" / "negative_index".
        - categories: The observed type categories.

    Returns:
        - An Outcome with the matches, or the candidates to refute.
    """
    matches = match_dynamic(hook, name, categories)
    if matches:
        return Outcome(matches=tuple(matches))
    return Outcome(refuted=_CANDIDATES.get((hook, name), ()))


def subscript_outcome(base: object, slices: Sequence[object]) -> Outcome:
    """Classify a subscript read as slicing or negative indexing.

    Parameters:
        - base: The object being indexed.
        - slices: The subscript's slice components; slice objects mean
          slicing, an integer means indexing.

    Returns:
        - The slicing restriction for the base type, the negative-index
          restriction, or an empty outcome for a plain positive index.
    """
    if any(isinstance(item, slice) for item in slices):
        categories = {cat for cat in (category(base),) if cat is not None}
        return resolve_dynamic("read_subscript", "slice", categories)
    if len(slices) == 1 and isinstance(slices[0], int) and not isinstance(slices[0], bool):
        if slices[0] < 0:
            return resolve_dynamic("read_subscript", "negative_index", ())
    return Outcome()
