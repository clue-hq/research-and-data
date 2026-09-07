"""D2 T3 exit gate: subjects, committee expansion and the recipe input filter, over a real DB.

Everything here is seeded through the lenient claim writer into a rolled-back transaction, so the
assertions run against the same rows production would read: live claims (not the merge), the
workspace-scoped claim read, and the real ``display_section_recipe`` rows.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.display.gather import (
    SectionInput,
    SubjectNotFound,
    client_context,
    committee_members,
    gather_section_inputs,
    resolve_subject,
)
from clue_api.arv2.display.recipes import load_display_recipes, read_recipes
from clue_config import Settings
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

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests._workspace import seed_workspace
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_g"
VERIFYING = Settings(_env_file=None, verification_enabled=True)
PERMISSIVE = Settings(_env_file=None, verification_enabled=False)


@dataclass(frozen=True)
class Seeded:
    """The ids one seeded workspace hands the assertions."""

    workspace_id: str
    account: EntityId
    nick: EntityId
    vari: EntityId
    silent: EntityId
    claims: dict[str, str]  # label -> claim id


async def _write(
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


async def _seed(conn: AsyncConnection) -> Seeded:
    ws = await seed_workspace(conn, WORKSPACE)
    await load_core_pack(conn)
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)
    await load_arv2_pack(conn)
    await load_display_recipes(conn)
    await conn.execute(
        text("INSERT INTO brand (brand_id, workspace_id, name) VALUES ('b_g', :ws, 'Clue')"),
        {"ws": ws},
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
        await _write(
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
        await _write(
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


async def _seed_coverage(conn: AsyncConnection, seeded: Seeded, members: list[EntityId]) -> None:
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


def _by_key(section: SectionInput, field_key: str) -> list[str]:
    """The claim ids a section carries for one field key."""
    return [claim.claim_id for claim in section.claims if claim.field_key == field_key]


def _section(sections: list[SectionInput], section_key: str) -> SectionInput:
    return next(section for section in sections if section.recipe.section_key == section_key)


def test_resolve_subject_reads_the_person_their_persona_and_their_account() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            subject = await resolve_subject(
                conn, workspace_id=seeded.workspace_id, kind="contact", subject_id=str(seeded.nick)
            )
            assert subject.kind == "contact"
            assert subject.name == "Nick Fisher"
            assert subject.persona == "economic_buyer"
            assert subject.title == "VP of Marketing"
            assert subject.account_id == str(seeded.account)
            assert subject.account_name == "Zafran Security"
            assert subject.account_domain == "zafran.io"
            assert subject.to_prompt() == {
                "kind": "contact",
                "name": "Nick Fisher",
                "persona": "economic_buyer",
                "title": "VP of Marketing",
                "account": "Zafran Security",
            }

            account = await resolve_subject(
                conn,
                workspace_id=seeded.workspace_id,
                kind="account",
                subject_id=str(seeded.account),
            )
            assert account.kind == "account" and account.name == "Zafran Security"
            assert account.account_id == str(seeded.account)

            with pytest.raises(SubjectNotFound):
                await resolve_subject(
                    conn,
                    workspace_id=seeded.workspace_id,
                    kind="contact",
                    subject_id=str(uuid.uuid4()),
                )

    run_async(_run())


def test_committee_members_without_a_coverage_row_are_the_contacts_that_have_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            members = await committee_members(
                conn, workspace_id=seeded.workspace_id, account_id=str(seeded.account)
            )
            assert {member.id for member in members} == {str(seeded.nick), str(seeded.vari)}
            assert str(seeded.silent) not in {member.id for member in members}
            by_id = {member.id: member for member in members}
            assert by_id[str(seeded.nick)].persona == "economic_buyer"
            assert by_id[str(seeded.nick)].title == "VP of Marketing"
            assert by_id[str(seeded.vari)].persona == "champion"
            assert all(member.account_name == "Zafran Security" for member in members)

    run_async(_run())


def test_the_latest_coverage_row_is_the_committee_even_when_a_member_has_no_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _seed_coverage(conn, seeded, [seeded.vari, seeded.silent])
            members = await committee_members(
                conn, workspace_id=seeded.workspace_id, account_id=str(seeded.account)
            )
            # The research finalized this committee: its order is kept, a member the store holds
            # no claim for is still a member, and Nick — who has claims — is not one.
            assert [member.id for member in members] == [str(seeded.vari), str(seeded.silent)]
            assert members[0].persona == "champion"
            assert members[1].persona is None

    run_async(_run())


def test_the_contact_page_routes_safe_unsafe_and_sensitive_claims_to_their_sections() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            subject = await resolve_subject(
                conn, workspace_id=seeded.workspace_id, kind="contact", subject_id=str(seeded.nick)
            )
            recipes = await read_recipes(conn, "contact", workspace_id=seeded.workspace_id)
            sections = await gather_section_inputs(
                conn,
                workspace_id=seeded.workspace_id,
                subject=subject,
                recipes=recipes,
                people=(),
                settings=VERIFYING,
            )

            openers = _section(sections, "openers")
            ids = {claim.claim_id for claim in openers.claims}
            assert seeded.claims["hobby_safe"] in ids
            assert seeded.claims["voice_quote"] in ids
            assert seeded.claims["hobby_unsafe"] not in ids
            assert seeded.claims["hobby_sensitive"] not in ids
            assert openers.excluded_unsafe == 1 and openers.excluded_sensitive == 1
            quote = next(
                claim for claim in openers.claims if claim.claim_id == seeded.claims["voice_quote"]
            )
            assert quote.value == "We buy tools that show us the buyer, not the dashboard"
            assert quote.media_timestamp == "12:04"
            assert quote.subject == "Nick Fisher"
            assert not openers.empty

            restricted = _section(sections, "do-not-mention")
            restricted_ids = {claim.claim_id for claim in restricted.claims}
            assert seeded.claims["hobby_unsafe"] in restricted_ids
            assert seeded.claims["reputation_risk"] in restricted_ids
            assert seeded.claims["hobby_sensitive"] not in restricted_ids
            assert restricted.excluded_sensitive == 1 and restricted.excluded_unsafe == 0

            problem = _section(sections, "problem-right-now")
            requisitions = [
                claim for claim in problem.claims if claim.claim_id == seeded.claims["requisitions"]
            ]
            assert len(requisitions) == 1 and requisitions[0].subject is None

    run_async(_run())


def test_the_account_page_dedupes_funding_and_obeys_the_verification_posture() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            subject = await resolve_subject(
                conn,
                workspace_id=seeded.workspace_id,
                kind="account",
                subject_id=str(seeded.account),
            )
            people = await committee_members(
                conn, workspace_id=seeded.workspace_id, account_id=str(seeded.account)
            )
            recipes = await read_recipes(conn, "overview", workspace_id=seeded.workspace_id)

            verified_only = await gather_section_inputs(
                conn,
                workspace_id=seeded.workspace_id,
                subject=subject,
                recipes=recipes,
                people=people,
                settings=VERIFYING,
            )
            why_now = _section(verified_only, "why-now")
            funding = _by_key(why_now, "account.recent_funding")
            assert funding == [seeded.claims["funding_long"]]
            assert why_now.deduped[seeded.claims["funding_short"]] == seeded.claims["funding_long"]
            assert _by_key(why_now, "account.strategic_moves") == []
            assert why_now.excluded_unverified == 1

            everything = await gather_section_inputs(
                conn,
                workspace_id=seeded.workspace_id,
                subject=subject,
                recipes=recipes,
                people=people,
                settings=PERMISSIVE,
            )
            open_why_now = _section(everything, "why-now")
            assert _by_key(open_why_now, "account.strategic_moves") == [
                seeded.claims["strategic_moves"]
            ]
            assert open_why_now.excluded_unverified == 0

            committee = _section(everything, "buying-committee")
            personas = {
                claim.claim_id: claim.subject
                for claim in committee.claims
                if claim.field_key == "contact.persona"
            }
            assert personas == {
                seeded.claims["nick_persona"]: "Nick Fisher",
                seeded.claims["vari_persona"]: "Vari Bindra",
            }
            certifications = {
                claim.claim_id: claim.subject
                for claim in committee.claims
                if claim.field_key == "contact.facet.certifications"
            }
            assert certifications == {
                seeded.claims["nick_cert"]: "Nick Fisher",
                seeded.claims["vari_cert"]: "Vari Bindra",
            }
            assert committee.deduped == {}

    run_async(_run())


def test_client_context_is_the_workspace_brand_and_the_settings_pitch() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            client = await client_context(
                conn, workspace_id=seeded.workspace_id, settings=VERIFYING
            )
            assert client.name == "Clue"
            assert client.what_we_sell == VERIFYING.arv2_display_client_pitch
            assert client.to_prompt() == {
                "name": "Clue",
                "what_we_sell": VERIFYING.arv2_display_client_pitch,
            }

    run_async(_run())
