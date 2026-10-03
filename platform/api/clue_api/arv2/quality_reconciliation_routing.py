"""Candidate routing, never claim selection or editorial judgment."""

from __future__ import annotations

from typing import Any

from clue_api.arv2.display.recipes import SectionRecipe

# Section purposes, not industry/person-specific questions. Unknown metadata falls through to
# all owned sections, so incomplete field classification cannot hide a new finding.
TOPICS = {
    "money-and-momentum": ("funding", "finance", "revenue", "budget", "growth"),
    "tools-they-already-use": ("technology", "tool", "stack", "software", "system"),
    "how-they-sell": ("commercial", "sales", "market", "customer", "distribution"),
    "buying-signals": (
        "priority",
        "pain",
        "workflow",
        "hiring",
        "initiative",
        "statement",
        "voice",
    ),
    "why-they-fit": ("priority", "pain", "workflow", "initiative", "statement", "strategy", "icp"),
    "why-now": ("hiring", "funding", "launch", "expansion", "change", "initiative"),
    "buying-committee": ("role", "responsibil", "leadership", "professional", "committee"),
    "how-to-approach": ("priority", "pain", "workflow", "statement", "voice", "professional"),
    "what-they-do": ("identity", "company", "offering", "business model", "product"),
    "watch-outs": ("risk", "conflict", "constraint", "adverse"),
}


def candidate_sections(claim: dict[str, Any], recipes: list[SectionRecipe]) -> set[str]:
    value = claim.get("value") or {}
    if not isinstance(value, dict):
        value = {}
    tags = " ".join(str(value.get(k, "")) for k in ("topic", "section", "claim_type")).lower()
    matches = {
        f"{r.page}/{r.section_key}"
        for r in recipes
        if claim["field_key"] in r.allowed_field_keys
        or any(t in tags for t in TOPICS.get(r.section_key, ()))
    }
    if value.get("review", {}).get("status") == "potential_conflict":
        matches |= {f"{r.page}/{r.section_key}" for r in recipes if r.section_key == "watch-outs"}
    return matches or {f"{r.page}/{r.section_key}" for r in recipes}


def compact_claim(row: dict[str, Any]) -> dict[str, Any]:
    value = row["value_json"]
    if isinstance(value, dict):
        # The original entry is duplicated inside the import audit payload. Preserve its
        # substantive fields and section, without repeating it or import hashes to the model.
        origin = value.get("dossier_entry") or {}
        value = {k: v for k, v in value.items() if k != "dossier_entry"}
        if origin.get("section"):
            value["section"] = origin["section"]
    return {
        "id": str(row["id"]),
        "entity_id": str(row["entity_id"]),
        "field_key": row["field_key"],
        "value": value,
        "source_url": row["source_url"],
        "evidence_span": row["evidence_span"],
        "quality": row["conclusion"],
        "superseded_by": str(row["superseded_by"]) if row["superseded_by"] else None,
    }


def reference_ids(value: Any) -> set[str]:
    if isinstance(value, list):
        return set().union(*(reference_ids(v) for v in value))
    if isinstance(value, dict):
        result: set[str] = set()
        for k, v in value.items():
            if k in ("claimIds", "claim_ids", "duplicate_of", "conflicts_with", "superseded_by"):
                result.update(str(x) for x in (v if isinstance(v, list) else [v]) if x)
            else:
                result.update(reference_ids(v))
        return result
    return set()


def replace_citations(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [replace_citations(v, mapping) for v in value]
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k in ("claimIds", "claim_ids"):
                if any(str(id) not in mapping for id in v):
                    raise ValueError("Unknown citation; use only supplied request-local aliases")
                result[k] = [mapping[str(id)] for id in v]
            else:
                result[k] = replace_citations(v, mapping)
        return result
    return value
