"""Run M4 — deep contact profiling for one committee member (profile_contact).

Fills the contact.facet.* gap fields and tags every claim with a born-correct
identity_binding + use_class (the governance that decides whether a hook may drive
outreach). Pass --account-id/--contact-id from scripts 03/05, or omit them to seed a
fresh demo account + contact.

    uv run python scripts/06_contact_profiling.py --account-id <A> --contact-id <C> --tier high
    uv run python scripts/06_contact_profiling.py --tier high      # seeds a demo account+contact

Facet fields fill through the source waterfall, which has no live resolver offline. To
show the real tagging path end-to-end, this script binds a small inline demo facet
resolver (one canned, evidence-bound facet) — everything after it (binding classifier,
use-class tagger, claim write) is the real thing.
"""

import argparse
import asyncio
from uuid import UUID, uuid4

import clue_obs
from clue_core import (
    Claim,
    Entity,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    ResearchMode,
    UseClass,
    contact_claim,
    new_run_id,
)
from clue_db import db_lifespan, transaction
from clue_research.api.composition import load_research_packs
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.profiling import profile_contact
from clue_research.sources import bind_resolver, clear_resolver_bindings


class DemoFacetResolver:
    """A stand-in tier-4 facet resolver: returns one evidence-bound facet claim. The
    placeholder binding/use_class tags are what M4 re-derives authoritatively. The evidence
    points at the contact's own LinkedIn so the binding classifier can bind it strongly."""

    tier = 4

    def __init__(self, contact_linkedin: str) -> None:
        self._linkedin = contact_linkedin

    def resolve(self, entity: Entity, field_def: FieldDef) -> list[Claim]:
        # Facet fields have different shapes; fill only the stated-interests one (a list of
        # strings) and leave the structured facets empty (an empty field is a correct output).
        if field_def.value_type != "list[str]":
            return []
        return [
            contact_claim(
                entity_id=entity.entity_id,
                field_key=field_def.field_key,
                value_json=["robotics", "trail running"],
                source_tier=self.tier,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.9,
                run_id=new_run_id(),  # placeholder — M4 overrides
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.WEAK,  # placeholder — M4 re-tags
                use_class=UseClass.PROFESSIONAL_PUBLIC,  # placeholder — M4 re-tags
                source_url=self._linkedin,
                evidence_span="Jane CFO lists robotics and trail running among her interests.",
            )
        ]


async def main(
    workspace_id: str, tier: str, account_id: str | None, contact_id: str | None
) -> None:
    tag = uuid4().hex[:8]  # unique per run so re-runs don't collide
    contact_linkedin = f"https://linkedin.com/in/jane-cfo-{tag}"
    clear_resolver_bindings()
    bind_resolver(
        "exa_deep", DemoFacetResolver(contact_linkedin)
    )  # the facet fields' tier-4 source

    async with db_lifespan(), transaction() as conn:
        await load_research_packs(conn)
        if account_id is None:
            account_id = str(
                await insert_account_entity(
                    conn,
                    canonical_name=f"Acme Robotics {tag}",
                    primary_domain=f"acme-{tag}.example",
                )
            )
            print(f"seeded demo account: {account_id}")
        if contact_id is None:
            contact_id = str(
                await insert_contact_entity(
                    conn,
                    account_entity_id=UUID(account_id),
                    full_name="Jane CFO",
                    linkedin_url=contact_linkedin,
                )
            )
            print(f"seeded demo contact: {contact_id}")

        result = await profile_contact(
            conn,
            contact_entity_id=UUID(contact_id),
            account_entity_id=UUID(account_id),
            run_id=new_run_id(),
            workspace_id=workspace_id,
            tier=tier,
        )

    print("\n=== M4 contact profiling ===")
    print(f"contact_entity_id : {result.contact_entity_id}")
    print(f"fields_filled     : {result.fields_filled}")
    print(f"fields_empty      : {result.fields_empty}")
    print(f"cost_cents        : {result.cost_cents}")
    for claim in result.profile_claims:
        print(
            f"  tier={claim.source_tier} binding={claim.identity_binding} "
            f"use_class={claim.use_class} value={claim.value_json!r}"
        )


if __name__ == "__main__":
    clue_obs.setup()
    p = argparse.ArgumentParser(description="M4 deep contact profiling")
    p.add_argument("--workspace-id", default="acme")
    p.add_argument("--tier", default="high")
    p.add_argument(
        "--account-id", default=None, help="UUID from script 03/05 (seeds one if omitted)"
    )
    p.add_argument("--contact-id", default=None, help="UUID from script 05 (seeds one if omitted)")
    args = p.parse_args()
    asyncio.run(main(args.workspace_id, args.tier, args.account_id, args.contact_id))
