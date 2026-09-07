"""The one seeded workspace the D2 display DB tests share: Zafran, three people, their claims.

Factored out of ``test_gather_db.py`` when the page test needed the same rows (D2 T6). One seed,
one set of ids: an assertion about what a page says and an assertion about what the filter kept
are then talking about the same claims, and a change to the fixture cannot make one test agree
with a world the other no longer lives in.

Everything is written through the lenient claim writer, so the rows are the rows production
writes — including the deliberately awkward ones (an unsafe twin of a safe hobby, a
special-category fact, a ``contact.*`` field mis-keyed onto the account).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.display.recipes import load_display_recipes
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    new_run_id,
)
from clue_research.claimstore.packs import load_core_pack
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.profiling.committee.fields import load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from tests._workspace import seed_workspace

#: The default workspace id the fixture seeds into. A test that needs its own passes one.
WORKSPACE = "ws_g"


@dataclass(frozen=True)
class Seeded:
    """The ids one seeded workspace hands the assertions."""

    workspace_id: str
    account: EntityId
    nick: EntityId
    vari: EntityId
    silent: EntityId
    claims: dict[str, str]  # label -> claim id


async def write_claim(
    conn: AsyncConnection,
    seeded: dict[str, str],
    *,
    label: str,
    workspace_id: str,
    entity_id: EntityId,
    entity_type: EntityType,
    field_key: str,
    value_json: Any,
    **overrides: Any,
) -> None:
    draft = ClaimDraft(
        entity_id=entity_id,
        entity_type=entity_type,
        field_key=field_key,
        value_json=value_json,
        extraction_method=overrides.pop("extraction_method", ExtractionMethod.SCRAPE),
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        workspace_id=workspace_id,
        source_url=overrides.pop("source_url", "https://zafran.io/newsroom"),
        **overrides,
    )
    receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
    seeded[label] = str(receipt.claim_id)


async def seed_display_fixture(conn: AsyncConnection, *, workspace_id: str = WORKSPACE) -> Seeded:
    ws = await seed_workspace(conn, workspace_id)
    await load_core_pack(conn)
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)
    await load_arv2_pack(conn)
    await load_display_recipes(conn)
    await conn.execute(
        text("INSERT INTO brand (brand_id, workspace_id, name) VALUES (:brand, :ws, 'Clue')"),
        {"brand": f"b_{ws}", "ws": ws},
    )

    account = await insert_account_entity(
        conn, canonical_name="Zafran Security", primary_domain="zafran.io", workspace_id=ws
    )
    nick = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Nick Fisher",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    )
    vari = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Vari Bindra",
        linkedin_url="https://www.linkedin.com/in/varibindra",
    )
    silent = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Nobody Withoutclaims",
        linkedin_url="https://www.linkedin.com/in/nobodywithoutclaims",
    )

    claims: dict[str, str] = {}

    async def account_claim(label: str, field_key: str, value: Any, **over: Any) -> None:
        await write_claim(
            conn,
            claims,
            label=label,
            workspace_id=ws,
            entity_id=account,
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value,
            **over,
        )

    async def contact_claim(
        label: str, entity: EntityId, field_key: str, value: Any, **over: Any
    ) -> None:
        await write_claim(
            conn,
            claims,
            label=label,
            workspace_id=ws,
            entity_id=entity,
            entity_type=EntityType.CONTACT,
            field_key=field_key,
            value_json=value,
            **over,
        )

    await account_claim(
        "requisitions",
        "account.open_requisitions",
        [{"title": "ABM Manager", "dept": "Marketing", "published": "2026-08-01"}],
        signal_priority=1,
        evidence_span="ABM Manager, Marketing",
    )
    await account_claim(
        "reputation_risk",
        "account.reputation_risk",
        {"what": "A 2025 customer dispute over an outage", "status": "unresolved"},
        signal_priority=3,
        outreach_safe=False,
        evidence_span="an unresolved dispute over the March outage",
    )
    await account_claim(
        "funding_short",
        "account.recent_funding",
        {"amount_usd": 30000000, "round": "Series B"},
        signal_priority=2,
        evidence_span="raised $30M",
    )
    await account_claim(
        "funding_long",
        "account.recent_funding",
        {"amount_usd": 30000000, "round": "Series B led by Cyberstarts"},
        signal_priority=2,
        evidence_span="Zafran Security announced a $30 million Series B led by Cyberstarts",
    )
    await account_claim(
        "strategic_moves",
        "account.strategic_moves",
        "Opened a New York office in June 2026",
        signal_priority=2,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        evidence_span="opened a New York office",
    )

    await contact_claim(
        "hobby_safe",
        nick,
        "contact.facet.hobby",
        ["Cocktail YouTuber, creator of the Cocktail Chemistry channel"],
        signal_priority=2,
        evidence_span="I run the Cocktail Chemistry channel",
    )
    await contact_claim(
        "hobby_unsafe",
        nick,
        "contact.facet.hobby",
        ["Posts about a family bereavement"],
        signal_priority=3,
        outreach_safe=False,
        evidence_span="a post about a family bereavement",
    )
    await contact_claim(
        "hobby_sensitive",
        nick,
        "contact.facet.hobby",
        ["Attends a weekly Buddhist meditation group"],
        signal_priority=3,
        outreach_safe=False,
        use_class=UseClass.SENSITIVE,
        identity_binding=IdentityBinding.STRONG,
        evidence_span="my Tuesday meditation group",
    )
    await contact_claim(
        "voice_quote",
        nick,
        "contact.facet.voice_quote",
        {
            "text": "We buy tools that show us the buyer, not the dashboard",
            "media_url": "https://youtu.be/zafran",
            "media_timestamp": "12:04",
        },
        signal_priority=1,
        evidence_span="We buy tools that show us the buyer, not the dashboard",
    )
    await contact_claim(
        "nick_persona", nick, "contact.persona", "economic_buyer", signal_priority=1
    )
    await contact_claim(
        "nick_title", nick, "contact.current_title", "VP of Marketing", signal_priority=1
    )
    await contact_claim("vari_persona", vari, "contact.persona", "champion", signal_priority=2)
    # The same certification, word for word, on two people: a fold across subjects would delete a
    # committee member from the page.
    for label, person in (("nick_cert", nick), ("vari_cert", vari)):
        await contact_claim(
            label,
            person,
            "contact.facet.certifications",
            ["AWS Certified Solutions Architect"],
            signal_priority=3,
            evidence_span="AWS Certified Solutions Architect",
        )
    # A ``contact.*`` fact mis-keyed onto the account entity — the lenient writer stores it, and
    # the filter must still route it by entity, so it can never be shown as somebody's persona.
    await account_claim("misfiled_persona", "contact.persona", "blocker", signal_priority=2)

    return Seeded(
        workspace_id=ws, account=account, nick=nick, vari=vari, silent=silent, claims=claims
    )


async def seed_coverage(conn: AsyncConnection, seeded: Seeded, members: list[EntityId]) -> None:
    """The M8D fleet triple a finished account-research run leaves behind, with ``members``.

    Inserted directly (the drivers are not this task's subject); the run/job rows exist only
    because the coverage row's FKs demand them, and the two scope CHECKs demand that their JSON
    repeats their own columns.
    """
    scope = {
        "workspace_id": seeded.workspace_id,
        "project_id": "prj_g",
        "product_id": "prd_g",
        "project_run_id": str(uuid.uuid4()),
    }
    run_id, job_id, selection_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread_id = "display-gather:zafran"
    lifecycle: dict[str, Any] = {
        "run_id": str(run_id),
        "run_kind": "account_research",
        "selection": {
            "selection_id": str(selection_id),
            "subject_type": "account",
            "budget_envelope_ref": "display-gather",
            **scope,
        },
    }
    authorization: dict[str, Any] = {
        "job_id": str(job_id),
        "research_run_id": str(run_id),
        "subject_type": "account",
        "subject_entity_id": str(seeded.account),
        "checkpoint_thread_id": thread_id,
        "selection": dict(scope),
        **scope,
    }

    def _sha(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    await conn.execute(
        text(
            """
            INSERT INTO entity_research_run
                (research_run_id, run_kind, subject_type, workspace_id, project_id, product_id,
                 project_run_id, selection_id, lifecycle_json, lifecycle_sha256,
                 budget_envelope_ref, budget_cap_cents, concurrency_limit, state)
            VALUES (:run_id, 'account_research', 'account', :workspace_id, :project_id,
                    :product_id, CAST(:project_run_id AS uuid), :selection_id,
                    CAST(:lifecycle AS jsonb), :sha, 'display-gather', 0, 1, 'queued')
            """
        ),
        {
            "run_id": run_id,
            "selection_id": selection_id,
            "lifecycle": json.dumps(lifecycle),
            "sha": _sha(lifecycle),
            **scope,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job
                (job_id, research_run_id, subject_type, subject_entity_id, workspace_id,
                 project_id, product_id, project_run_id, authorization_json, authorization_sha256,
                 budget_envelope_ref, budget_cap_cents, checkpoint_thread_id,
                 initial_state_sha256, current_state_sha256, state)
            VALUES (:job_id, :run_id, 'account', :account, :workspace_id, :project_id,
                    :product_id, CAST(:project_run_id AS uuid), CAST(:authorization AS jsonb),
                    :sha, 'display-gather', 0, :thread_id, :sha, :sha, 'queued')
            """
        ),
        {
            "job_id": job_id,
            "run_id": run_id,
            "account": seeded.account,
            "authorization": json.dumps(authorization),
            "sha": _sha(authorization),
            "thread_id": thread_id,
            **scope,
        },
    )
    coverage = {"origin": "display-gather"}
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_coverage
                (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                 result_refs, completed_field_keys, unresolved_field_keys, unresolved_reasons,
                 committee_result_refs, committee_member_ids, committee_status, review_flags,
                 claim_refs, evidence_refs, coverage_json, coverage_sha256)
            VALUES (:coverage_id, :run_id, :job_id, :workspace_id, :account, :empty, :empty,
                    :empty, :empty, :empty, :members, 'complete', :empty, :empty, :empty,
                    CAST(:coverage AS jsonb), :sha)
            """
        ),
        {
            "coverage_id": uuid.uuid4(),
            "run_id": run_id,
            "job_id": job_id,
            "workspace_id": seeded.workspace_id,
            "account": seeded.account,
            "empty": [],
            "members": members,
            "coverage": json.dumps(coverage),
            "sha": _sha(coverage),
        },
    )
