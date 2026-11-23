"""Guard the committed Semgrep ruleset against drift from the catalog.

``static/rules/ncc.yml`` is generated from the catalog but shipped as package
data, so the two can diverge silently: an edit to a Restriction changes the
rules every scan should use, while the file on disk still holds the old ones.
"""

from __future__ import annotations

from pynoptic.restrictions import restrictions
from pynoptic.static.rulegen import (
    CANDIDATE_SUFFIX,
    build_rules,
    candidate_rule_id,
    generate_yaml,
)
from pynoptic.static.semgrep_runner import rules_path


def test_committed_ruleset_matches_the_catalog() -> None:
    """The regeneration command is `python -m pynoptic.static.rulegen`."""
    committed = rules_path().read_text(encoding="utf-8")
    assert committed == generate_yaml()


def test_every_rule_carries_its_round_trip_id() -> None:
    """semgrep_runner recovers the restriction from metadata.rule_id."""
    for rule in build_rules():
        metadata = rule.get("metadata")
        assert isinstance(metadata, dict)
        assert metadata.get("rule_id") == rule["id"]


def test_rule_count_matches_declared_detectors() -> None:
    definitive = sum(1 for r in restrictions() if r.semgrep is not None)
    candidates = sum(1 for r in restrictions() if r.candidate is not None)
    assert len(build_rules()) == definitive + candidates


def test_candidate_ids_strip_back_to_a_known_restriction() -> None:
    known = {r.id for r in restrictions()}
    for rule in build_rules():
        rule_id = str(rule["id"])
        if rule_id.endswith(CANDIDATE_SUFFIX):
            assert rule_id[: -len(CANDIDATE_SUFFIX)] in known
        else:
            assert rule_id in known


def test_candidate_rule_id_is_reversible() -> None:
    assert candidate_rule_id("R55") == f"R55{CANDIDATE_SUFFIX}"


def test_every_rule_declares_a_pattern() -> None:
    """SemgrepSpec.to_rule raises on an empty spec; nothing should be pattern-less."""
    keys = {"pattern", "patterns", "pattern-either", "pattern-regex"}
    for rule in build_rules():
        assert keys & set(rule), rule["id"]
