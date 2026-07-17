"""M2.2 — canonicalization plan (pure, no DB)."""

from __future__ import annotations

from clue_core import AccountEntity, new_entity_id
from clue_research.identity.canonicalize import plan_merge


def _account(name: str, **kwargs: object) -> AccountEntity:
    return AccountEntity(id=new_entity_id(), canonical_name=name, **kwargs)  # type: ignore[arg-type]


def test_plan_unions_aliases_and_registry_and_fills_gaps() -> None:
    survivor = _account("Acme", aliases=("acme",), registry_ids={"DUNS": "111"})
    loser = _account(
        "Acme Corporation",
        primary_domain="acme.com",
        aliases=("acme corp",),
        registry_ids={"LEI": "222"},
        hq_geo={"country": "US"},
    )
    plan = plan_merge(survivor, loser)
    # Survivor lacked a domain / geo → the loser's fill the gap.
    assert plan.primary_domain == "acme.com"
    assert plan.hq_geo == {"country": "US"}
    # The loser's name + aliases are absorbed as aliases.
    assert "Acme Corporation" in plan.add_aliases
    assert "acme corp" in plan.add_aliases
    # Registry ids union; survivor's already-present DUNS is not in the *add* set (it stays).
    assert plan.add_registry_ids == {"LEI": "222"}
    # The more informative name (more tokens) is adopted.
    assert plan.canonical_name == "Acme Corporation"


def test_plan_keeps_survivor_strong_key_and_name_when_better() -> None:
    survivor = _account("Acme Corporation", primary_domain="acme.com")
    loser = _account("Acme")
    plan = plan_merge(survivor, loser)
    assert plan.primary_domain is None  # survivor already had one → not overwritten
    assert plan.canonical_name is None  # survivor's name is already the better one
    assert "Acme" in plan.add_aliases
