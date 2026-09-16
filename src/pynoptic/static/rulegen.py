"""Generate the Semgrep ruleset from the detector registry.

This is a maintainer tool. The generated YAML is committed and shipped as
package data; :func:`build_rules` is used by tests to detect drift between the
registry and the committed file. Run python -m pynoptic.static.rulegen to
regenerate.
"""

from __future__ import annotations

import io
from pathlib import Path

from ..restrictions import restrictions

__all__ = ["build_rules", "generate_yaml", "RULES_PATH", "CANDIDATE_SUFFIX"]

CANDIDATE_SUFFIX = "_candidate"
RULES_PATH = Path(__file__).parent / "rules" / "ncc.yml"


def candidate_rule_id(restriction_id: str) -> str:
    """Return the Semgrep rule id used for a hybrid candidate.

    Parameters:
        - restriction_id: The restriction the candidate belongs to.

    Returns:
        - The candidate rule id, with the _candidate suffix.
    """
    return f"{restriction_id}{CANDIDATE_SUFFIX}"


def build_rules() -> list[dict[str, object]]:
    """Build the full list of Semgrep rules (static + hybrid candidates).

    Returns:
        - The rules, sorted by restriction number.
    """
    rules: list[dict[str, object]] = []
    for restriction in restrictions():
        if restriction.semgrep is None:
            continue
        rules.append(restriction.semgrep.to_rule(restriction))
    for restriction in restrictions():
        if restriction.candidate is None:
            continue
        rule = restriction.candidate.to_rule(restriction)
        rule["id"] = candidate_rule_id(restriction.id)
        metadata = dict(rule.get("metadata", {}))
        metadata["rule_id"] = rule["id"]
        rule["metadata"] = metadata
        rules.append(rule)
    rules.sort(key=lambda rule: int(str(rule["id"]).split("_")[0][1:]))
    return rules


def generate_yaml() -> str:
    """Serialize the ruleset to YAML in a deterministic form.

    Returns:
        - The YAML document as a string.
    """
    import yaml

    buffer = io.StringIO()
    yaml.safe_dump(
        {"rules": build_rules()},
        buffer,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
        allow_unicode=True,
    )
    return buffer.getvalue()


def main() -> int:  # pragma: no cover - maintainer entry point
    """Regenerate the committed Semgrep ruleset.

    Returns:
        - Process exit code.
    """
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(generate_yaml(), encoding="utf-8")
    print(f"Wrote {RULES_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
