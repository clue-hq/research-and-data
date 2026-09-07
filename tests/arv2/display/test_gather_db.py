"""D2 T3 exit gate: subjects, committee expansion and the recipe input filter, over a real DB.

Everything here is seeded through the lenient claim writer into a rolled-back transaction, so the
assertions run against the same rows production would read: live claims (not the merge), the
workspace-scoped claim read, and the real ``display_section_recipe`` rows. The seed itself lives
in ``_seed.py`` — the page test (T6) reads the same workspace.
"""

from __future__ import annotations

import uuid

import pytest

from clue_api.arv2.display.gather import (
    SectionInput,
    SubjectNotFound,
    client_context,
    committee_members,
    gather_section_inputs,
    resolve_subject,
)
from clue_api.arv2.display.recipes import read_recipes
from clue_config import Settings
from tests.arv2.display._seed import seed_coverage, seed_display_fixture

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

VERIFYING = Settings(_env_file=None, verification_enabled=True)
PERMISSIVE = Settings(_env_file=None, verification_enabled=False)


def _by_key(section: SectionInput, field_key: str) -> list[str]:
    """The claim ids a section carries for one field key."""
    return [claim.claim_id for claim in section.claims if claim.field_key == field_key]


def _section(sections: list[SectionInput], section_key: str) -> SectionInput:
    return next(section for section in sections if section.recipe.section_key == section_key)


def test_resolve_subject_reads_the_person_their_persona_and_their_account() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn)
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
            seeded = await seed_display_fixture(conn)
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
            seeded = await seed_display_fixture(conn)
            await seed_coverage(conn, seeded, [seeded.vari, seeded.silent])
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
            seeded = await seed_display_fixture(conn)
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
            seeded = await seed_display_fixture(conn)
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
            seeded = await seed_display_fixture(conn)
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
