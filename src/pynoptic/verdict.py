from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .models import Detection, Level, Verdict
from .restrictions import get_restriction, restrictions

__all__ = ["SUPPRESSION", "UNCONFIRMED_OPERATORS", "candidate_groups", "to_verdict"]


#: Pairs (general, specific); at the same position the general id is dropped
#: when the specific one is present.
SUPPRESSION: tuple[tuple[str, str], ...] = (
    ("R24", "R25"),
    ("R24", "R48"),
    ("R24", "R54"),
    ("R24", "R78"),
    ("R53", "R115"),
    ("R41", "R122"),
    ("R123", "R125"),
    ("R175", "R176"),
    ("R220", "R79"),
    ("R181", "R133"),
    ("R180", "R134"),
    ("R182", "R136"),
    ("R187", "R137"),
    ("R186", "R138"),
    ("R188", "R140"),
    ("R7", "R141"),
    ("R6", "R141"),
    ("R9", "R142"),
    ("R8", "R142"),
    ("R67", "R23"),
    ("R68", "R23"),
    ("R132", "R23"),
)


#: Singleton-candidate operators whose static pattern collides with
#: unrestricted numeric arithmetic. A bare ``a * b`` / ``a + b`` / ``a - b`` /
#: ``a -= b`` is overwhelmingly numeric, so an *unresolved* static candidate
#: must not count as a violation the way other unanimous scope votes do:
#: only a DynaPyt-confirmed (``exact``) observation counts. Cf. the catalog
#: notes "Collides with numeric arithmetic" (R55/R56) and the set-operator
#: notes (R135/R139).
UNCONFIRMED_OPERATORS: frozenset[str] = frozenset({"R55", "R56", "R135", "R139"})


def _number(restriction_id: str) -> int:
    """Return the numeric part of a restriction id, for ordering.

    Parameters:
        - restriction_id: A restriction id such as R37.

    Returns:
        - The integer 37.
    """
    return int(restriction_id[1:])


def _scope(restriction_id: str) -> Level | None:
    """Return a restriction's scope, or None when it is unknown.

    Parameters:
        - restriction_id: A restriction id.

    Returns:
        - The scope, or None for an id outside the catalog.
    """
    try:
        return get_restriction(restriction_id).scope
    except KeyError:
        return None


def candidate_groups() -> dict[str, tuple[str, ...]]:
    """Group every restriction by the candidate key that resolves it.

    A candidate key K maps to {K} plus every restriction whose runtime
    trigger names K as its candidate.

    Returns:
        - A mapping from candidate key to the sorted restriction ids it covers.
    """
    groups: dict[str, set[str]] = {}
    for restriction in restrictions():
        for match in restriction.dynamic:
            group = groups.setdefault(match.candidate, {match.candidate})
            group.add(restriction.id)
    return {
        key: tuple(sorted(value, key=_number)) for key, value in groups.items()
    }


_CANDIDATE_GROUPS = candidate_groups()


def _position_key(detection: Detection) -> tuple[str | None, int, int]:
    """Return the canonical (file, line, column) position of a detection.

    Parameters:
        - detection: The detection to locate.

    Returns:
        - The position key used to group occurrences.
    """
    location = detection.location
    return (location.file, location.line, location.column)


def to_verdict(
    detections: Iterable[Detection],
    exercise_level: Level | int | str,
) -> Verdict:
    """Count occurrences for a submission.

    Parameters:
        - detections: The raw or resolved detections for one submission.
        - exercise_level: The level the submission is audited against.

    Returns:
        - The counted violations and the ambiguous occurrences that were not
          counted.
    """
    level = Level.parse(exercise_level)
    by_position: dict[tuple[str | None, int, int], list[Detection]] = {}
    for detection in detections:
        key = _position_key(detection)
        by_position.setdefault(key, []).append(detection)

    counted: Counter[str] = Counter()
    ambiguous: Counter[str] = Counter()

    for detections_at in by_position.values():
        ids = {detection.restriction_id for detection in detections_at}
        for general, specific in SUPPRESSION:
            if general in ids and specific in ids:
                ids.discard(general)

        candidates = {d.candidate for d in detections_at if d.candidate}
        handled: set[str] = set()
        for candidate in candidates:
            group = set(_CANDIDATE_GROUPS.get(candidate, (candidate,)))
            exact = {
                detection.restriction_id
                for detection in detections_at
                if detection.detector == "dynapyt"
                and detection.resolved
                and detection.candidate == candidate
                and detection.restriction_id in group
            }
            if exact:
                if len(exact) == 1:
                    counted[next(iter(exact))] += 1
                else:
                    ambiguous["|".join(sorted(exact, key=_number))] += 1
            else:
                group_scopes = [
                    scope for scope in (_scope(rid) for rid in group) if scope is not None
                ]
                verdicts = {scope >= level for scope in group_scopes}
                if verdicts == {True}:
                    if candidate in UNCONFIRMED_OPERATORS:
                        ambiguous[candidate] += 1
                    else:
                        counted[candidate] += 1
                elif verdicts == {False}:
                    pass
                else:
                    ambiguous["|".join(sorted(group, key=_number))] += 1
            handled |= group

        for restriction_id in ids - handled:
            scope = _scope(restriction_id)
            if scope is not None and scope >= level:
                counted[restriction_id] += 1

    ordered_violations = dict(sorted(counted.items(), key=lambda item: _number(item[0])))
    ordered_ambiguous = dict(sorted(ambiguous.items()))
    return Verdict(
        exercise_level=level,
        violations=ordered_violations,
        ambiguous=ordered_ambiguous,
    )
