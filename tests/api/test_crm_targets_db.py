"""``read_crm_targets@1`` (CRM integration Phase 3, Task 4): a project's accounts and buying
committee, already reduced to what the personal-data rule allows (R-8.7, R-12.1, R-12.2, R-12.5,
R-12.6), each value with the claim it came from.

The ARV2 rows are seeded through the lenient claim writer into a rolled-back transaction, so the
reads see what production writes. The CRM is never called: the tool reads only Clue's database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.crm import writes
from clue_api.crm.target_tools import ReadCrmTargetsInput, ReadCrmTargetsTool
from clue_api.crm.targets import (
    ProjectTargets,
    hubspot_buying_role,
    hubspot_tier,
    project_targets,
    split_name,
)
from clue_api.crm.write_actions import write_spec
from clue_config import Settings
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    VerificationStatus,
    new_run_id,
)
from clue_research.claimstore import record_verification
from clue_research.claimstore.claims import supersede_with_existing
from clue_research.claimstore.run_lineage import record_run_lineage
from clue_research.identity import insert_account_entity, insert_contact_entity, mark_merged
from clue_research.profiling.committee.fields import load_committee_pack
from clue_toolbelt import PreconditionFailed
from tests._workspace import seed_project
from tests.api.test_crm_propose_db import _ctx
from tests.api.test_crm_tools_db import _connect
from tests.api.test_lane_d4_agent_gate_db import _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SETTINGS = Settings(_env_file=None)


# -- the pure rules (no database) -----------------------------------------------------------------


def test_tier_follows_the_fit_bands_the_screens_use() -> None:
    assert hubspot_tier(0.81, settings=SETTINGS) == "tier_1"
    assert hubspot_tier(0.70, settings=SETTINGS) == "tier_1"
    assert hubspot_tier(0.55, settings=SETTINGS) == "tier_2"
    assert hubspot_tier(0.10, settings=SETTINGS) == "tier_3"
    assert hubspot_tier(None, settings=SETTINGS) is None


def test_split_name_handles_one_and_many_words() -> None:
    assert split_name("Cher") == (None, "Cher")
    assert split_name("  Nick   Fisher ") == ("Nick", "Fisher")
    assert split_name("Mary Ann van der Berg") == ("Mary", "Ann van der Berg")


def test_buying_roles_are_hubspots_own_values() -> None:
    assert hubspot_buying_role("champion") == "CHAMPION"
    assert hubspot_buying_role("economic_buyer") == "BUDGET_HOLDER"
    assert hubspot_buying_role("technical_evaluator") == "INFLUENCER"
    assert hubspot_buying_role("blocker") == "BLOCKER"
    assert hubspot_buying_role("user") == "END_USER"
    assert hubspot_buying_role(None) is None
    assert hubspot_buying_role("decision_maker") is None


# -- the database reads ---------------------------------------------------------------------------


@pytest.fixture
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


_db = pytest.mark.usefixtures("require_db")


class _World:
    """One seeded workspace: a project, its accounts, their people and their claims."""

    def __init__(self, conn: Any, seeded: Any) -> None:
        self.conn = conn
        self.workspace_id: str = seeded.workspace_id
        self.project_id: str = seeded.project_id
        self.claims: dict[str, UUID] = {}

    async def account(self, name: str, domain: str, *, in_project: bool = True) -> EntityId:
        account = await insert_account_entity(
            self.conn, canonical_name=name, primary_domain=domain, workspace_id=self.workspace_id
        )
        if in_project:
            await self.add_to_project(account, self.project_id)
        return account

    async def add_to_project(self, account: EntityId, project_id: str) -> None:
        await self.conn.execute(
            text(
                "INSERT INTO project_account (workspace_id, project_id, account_entity_id, "
                "added_via, added_at) VALUES (:ws, :project, :account, 'discovered', now())"
            ),
            {"ws": self.workspace_id, "project": project_id, "account": account},
        )

    async def claim(
        self,
        label: str,
        entity: EntityId,
        field_key: str,
        value: Any,
        *,
        run_id: RunId | None = None,
        **overrides: Any,
    ) -> UUID:
        entity_type = EntityType.CONTACT if field_key.startswith("contact.") else EntityType.ACCOUNT
        if field_key == "core.work_email":
            entity_type = EntityType.CONTACT
        draft = ClaimDraft(
            entity_id=entity,
            entity_type=entity_type,
            field_key=field_key,
            value_json=value,
            extraction_method=overrides.pop("extraction_method", ExtractionMethod.API),
            run_id=run_id or new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            workspace_id=self.workspace_id,
            source_url=overrides.pop("source_url", "https://example.com/team"),
            evidence_span=overrides.pop("evidence_span", "named on the team page"),
            **overrides,
        )
        receipt = await LenientClaimWriter(lenient=True).write(self.conn, draft)
        self.claims[label] = UUID(str(receipt.claim_id))
        return self.claims[label]

    async def fit(self, label: str, account: EntityId, score: float, project_id: str) -> UUID:
        run_id = new_run_id()
        await record_run_lineage(
            self.conn,
            run_id=run_id,
            workspace_id=self.workspace_id,
            kind="discovery",
            project_id=project_id,
        )
        return await self.claim(
            label, account, "account.scoring.fit", {"value": score}, run_id=run_id
        )

    async def person(
        self, account: EntityId, name: str, *, linkedin: str | None = None
    ) -> EntityId:
        return await insert_contact_entity(
            self.conn, account_entity_id=account, full_name=name, linkedin_url=linkedin
        )


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_arv2_pack(conn)
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmt-{label}", label=label)
            await body(conn, _World(conn, seeded), seeded)

    run_async(scenario())


async def _targets(
    world: _World,
    *,
    provider: str | None = "hubspot",
    connection: Any = None,
    settings: Settings = SETTINGS,
    **kwargs: Any,
) -> ProjectTargets:
    return await project_targets(
        world.conn,
        workspace_id=world.workspace_id,
        project_id=world.project_id,
        connection_id=connection.connection_id if connection is not None else None,
        provider=provider,  # type: ignore[arg-type]
        settings=settings,
        **kwargs,
    )


@_db
def test_accounts_carry_their_project_fit_and_tier(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        high = await world.account("Zafran Security", "zafran.io")
        medium = await world.account("Probook", "probook.example")
        unscored = await world.account("Quietly Ltd", "quietly.example")
        outside = await world.account("Elsewhere Inc", "elsewhere.example", in_project=False)
        fit_high = await world.fit("fit_high", high, 0.81, world.project_id)
        await world.fit("fit_medium", medium, 0.55, world.project_id)
        await world.fit("fit_outside", outside, 0.95, world.project_id)
        # A fit scored for ANOTHER project of the workspace is not this project's fit.
        other = await seed_project(conn, world.workspace_id, name="Other project")
        await world.fit("fit_other_project", unscored, 0.9, other.project_id)

        page = await _targets(world)
        by_name = {account.name: account for account in page.accounts}
        assert set(by_name) == {"Zafran Security", "Probook", "Quietly Ltd"}
        assert page.total_accounts == 3
        zafran = by_name["Zafran Security"]
        assert zafran.account_entity_id == str(high)
        assert zafran.domain == "zafran.io"
        assert zafran.fit_band == "high"
        assert zafran.hubspot_icp_tier is not None
        assert zafran.hubspot_icp_tier.value == "tier_1"
        assert zafran.hubspot_icp_tier.claim_ids == (fit_high,)
        assert by_name["Probook"].fit_band == "medium"
        probook_tier = by_name["Probook"].hubspot_icp_tier
        assert probook_tier is not None and probook_tier.value == "tier_2"
        assert by_name["Quietly Ltd"].fit_band is None
        assert by_name["Quietly Ltd"].hubspot_icp_tier is None

        # Salesforce has no ICP tier field to offer (R-12.6 analogue): the band stays, the tier
        # does not.
        salesforce = await _targets(world, provider="salesforce")
        sf_zafran = next(a for a in salesforce.accounts if a.name == "Zafran Security")
        assert sf_zafran.fit_band == "high" and sf_zafran.hubspot_icp_tier is None

    _run(tmp_path, "fit", body)


@_db
def test_only_a_graded_valid_email_is_offered(tmp_path: Path) -> None:
    """R-12.10: ``verified_smtp`` and ``catch_all_valid`` are offered; the rest is held back."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(account, "Nick Fisher")
        vari = await world.person(account, "Vari Bindra")
        cath = await world.person(account, "Cath Allan")
        await world.claim("nick_persona", nick, "contact.persona", "champion")
        verified = await world.claim(
            "nick_email",
            nick,
            "core.work_email",
            {"address": "nick@zafran.io", "status": "verified_smtp"},
        )
        await world.claim("vari_persona", vari, "contact.persona", "user")
        await world.claim(
            "vari_email",
            vari,
            "core.work_email",
            {"address": "vari@zafran.io", "status": "unverified"},
        )
        await world.claim("cath_persona", cath, "contact.persona", "user")
        catch_all = await world.claim(
            "cath_email",
            cath,
            "core.work_email",
            {"address": "cath@zafran.io", "status": "catch_all_valid"},
        )

        page = await _targets(world)
        by_last = {contact.last_name.value: contact for contact in page.contacts}
        assert by_last["Fisher"].work_email is not None
        assert by_last["Fisher"].work_email.value == "nick@zafran.io"
        assert by_last["Fisher"].work_email.claim_ids == (verified,)
        assert by_last["Allan"].work_email is not None
        assert by_last["Allan"].work_email.value == "cath@zafran.io"
        assert by_last["Allan"].work_email.claim_ids == (catch_all,)
        assert by_last["Bindra"].work_email is None
        assert "email: not verified (unverified)" in by_last["Bindra"].withheld

    _run(tmp_path, "email", body)


@_db
def test_a_sensitive_or_unsafe_or_weak_claim_is_withheld(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        safe = await world.person(account, "Safe Person")
        sensitive = await world.person(account, "Sensitive Person")
        unsafe = await world.person(account, "Unsafe Person")
        weak = await world.person(account, "Weak Person")
        title = await world.claim("safe_title", safe, "contact.current_title", "VP Marketing")
        persona = await world.claim("safe_persona", safe, "contact.persona", "economic_buyer")
        role = await world.claim(
            "safe_role",
            safe,
            "contact.role_on_committee",
            {"role": "economic_buyer", "rationale": "owns the budget"},
        )
        await world.claim(
            "sensitive_title",
            sensitive,
            "contact.current_title",
            "Head of Oncology Support",
            use_class=UseClass.SENSITIVE,
            identity_binding=IdentityBinding.STRONG,
        )
        await world.claim(
            "unsafe_title", unsafe, "contact.current_title", "Interim CEO", outreach_safe=False
        )
        await world.claim(
            "weak_persona",
            weak,
            "contact.persona",
            "champion",
            identity_binding=IdentityBinding.WEAK,
        )

        page = await _targets(world)
        by_first = {
            contact.first_name.value: contact
            for contact in page.contacts
            if contact.first_name is not None
        }
        assert by_first["Safe"].job_title is not None
        assert by_first["Safe"].job_title.value == "VP Marketing"
        assert by_first["Safe"].job_title.claim_ids == (title,)
        assert by_first["Safe"].buying_role is not None
        assert by_first["Safe"].buying_role.value == "BUDGET_HOLDER"
        assert set(by_first["Safe"].buying_role.claim_ids) == {persona, role}
        assert by_first["Safe"].withheld == ()

        assert by_first["Sensitive"].job_title is None
        assert "title: sensitive" in by_first["Sensitive"].withheld
        assert by_first["Unsafe"].job_title is None
        assert "title: marked not safe for outreach" in by_first["Unsafe"].withheld
        assert by_first["Weak"].buying_role is None
        assert "buying role: identity not confirmed" in by_first["Weak"].withheld

        # Salesforce gets no buying role at all (R-12.6), and that is not a withholding.
        salesforce = await _targets(world, provider="salesforce")
        sf_safe = next(
            c
            for c in salesforce.contacts
            if c.last_name.value == "Person"
            and c.first_name is not None
            and c.first_name.value == "Safe"
        )
        assert sf_safe.buying_role is None and sf_safe.withheld == ()

    _run(tmp_path, "gate", body)


@_db
def test_linkedin_is_withheld_when_any_claim_is_weak(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        bound = await world.person(
            account, "Nick Fisher", linkedin="https://www.linkedin.com/in/nickfisher"
        )
        unbound = await world.person(
            account, "Vari Bindra", linkedin="https://www.linkedin.com/in/varibindra"
        )
        await world.claim(
            "nick_title",
            bound,
            "contact.current_title",
            "VP Marketing",
            identity_binding=IdentityBinding.STRONG,
        )
        await world.claim("vari_persona", unbound, "contact.persona", "champion")
        await world.claim(
            "vari_title",
            unbound,
            "contact.current_title",
            "Director",
            identity_binding=IdentityBinding.WEAK,
        )

        page = await _targets(world)
        by_last = {contact.last_name.value: contact for contact in page.contacts}
        nick = by_last["Fisher"]
        assert nick.linkedin_url is not None
        assert nick.linkedin_url.value == "https://www.linkedin.com/in/nickfisher"
        assert nick.linkedin_url.claim_ids == ()
        vari = by_last["Bindra"]
        assert vari.linkedin_url is None
        assert "LinkedIn: identity not confirmed" in vari.withheld
        # Her persona still passes on its own; only the weak title and LinkedIn are withheld.
        assert vari.buying_role is not None and vari.buying_role.value == "CHAMPION"
        assert "title: identity not confirmed" in vari.withheld

    _run(tmp_path, "linkedin", body)


@_db
def test_contacts_come_from_the_committee_rule(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        outside_account = await world.account("Elsewhere", "elsewhere.example", in_project=False)
        user = await world.person(account, "Aaron User")
        buyer = await world.person(account, "Zoe Buyer")
        await world.person(account, "Silent Withoutclaims")  # no claim: not on the committee
        outsider = await world.person(outside_account, "Out Sider")
        await world.claim("user_persona", user, "contact.persona", "user")
        await world.claim("buyer_persona", buyer, "contact.persona", "economic_buyer")
        await world.claim("outsider_persona", outsider, "contact.persona", "champion")

        page = await _targets(world)
        # Persona rank, then name: the committee's own order.
        assert [contact.contact_entity_id for contact in page.contacts] == [str(buyer), str(user)]
        assert all(contact.account_entity_id == str(account) for contact in page.contacts)

        without = await project_targets(
            conn,
            workspace_id=world.workspace_id,
            project_id=world.project_id,
            connection_id=None,
            provider=None,
            settings=SETTINGS,
            include_contacts=False,
        )
        assert without.contacts == [] and len(without.accounts) == 1

    _run(tmp_path, "committee", body)


@_db
def test_an_account_already_in_the_crm_carries_its_record_id(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        connection = await _connect(conn, world.workspace_id)
        linked = await world.account("Zafran Security", "zafran.io")
        await world.account("Probook", "probook.example")
        nick = await world.person(linked, "Nick Fisher")
        await world.claim("nick_persona", nick, "contact.persona", "champion")
        await writes.record_link(
            conn,
            workspace_id=world.workspace_id,
            connection_id=connection.connection_id,
            crm_object="company",
            crm_id="9001",
            created_by_clue=False,
            clue_entity_id=UUID(str(linked)),
        )
        await writes.record_link(
            conn,
            workspace_id=world.workspace_id,
            connection_id=connection.connection_id,
            crm_object="contact",
            crm_id="501",
            created_by_clue=True,
            clue_entity_id=UUID(str(nick)),
        )

        page = await _targets(world, connection=connection)
        by_name = {account.name: account for account in page.accounts}
        assert by_name["Zafran Security"].crm_record_id == "9001"
        assert by_name["Probook"].crm_record_id is None
        assert page.contacts[0].crm_record_id == "501"

        # Through the tool: the active connection is found, and it is named.
        tool = ReadCrmTargetsTool(settings=SETTINGS, conn_factory=conn_session_factory(conn))
        ctx = _ctx(conn, world.workspace_id)
        inputs = ReadCrmTargetsInput(project_id=world.project_id)
        assert await tool.preconditions(inputs, ctx) == ()
        refs = (await tool.invoke(inputs, ctx)).references
        assert refs["connected_crm"] == "hubspot"
        assert refs["total_accounts"] == 2
        tool_zafran = next(a for a in refs["accounts"] if a["name"] == "Zafran Security")
        assert tool_zafran["crm_record_id"] == "9001"
        assert refs["contacts"][0]["crm_record_id"] == "501"
        assert refs["contacts"][0]["buying_role"]["value"] == "CHAMPION"
        assert refs["contacts"][0]["buying_role"]["claim_ids"] == [
            str(world.claims["nick_persona"])
        ]

    _run(tmp_path, "links", body)


@_db
def test_workspace_isolation(tmp_path: Path) -> None:
    """A second seeded workspace, with its own project, accounts, people, claims and CRM link:
    reading this workspace's project returns none of it, and its project is refused here."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        mine = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(mine, "Nick Fisher")
        await world.claim("nick_persona", nick, "contact.persona", "champion")

        theirs = await _seed(conn, tmp_path, workspace_id="ws-crmt-other", label="other")
        other = _World(conn, theirs)
        their_connection = await _connect(conn, other.workspace_id)
        their_account = await other.account("Theirs Inc", "theirs.example")
        await other.fit("their_fit", their_account, 0.9, other.project_id)
        their_person = await other.person(their_account, "Tom Theirs")
        await other.claim("their_persona", their_person, "contact.persona", "champion")
        await writes.record_link(
            conn,
            workspace_id=other.workspace_id,
            connection_id=their_connection.connection_id,
            crm_object="company",
            crm_id="7777",
            created_by_clue=False,
            clue_entity_id=UUID(str(their_account)),
        )

        page = await _targets(world)
        assert [a.account_entity_id for a in page.accounts] == [str(mine)]
        assert [c.contact_entity_id for c in page.contacts] == [str(nick)]
        assert all(a.crm_record_id is None for a in page.accounts)

        # Their project read from this workspace: nothing, even with their account named.
        cross = await project_targets(
            conn,
            workspace_id=world.workspace_id,
            project_id=other.project_id,
            connection_id=their_connection.connection_id,
            provider="hubspot",
            settings=SETTINGS,
            account_ids=[str(their_account)],
        )
        assert cross.accounts == [] and cross.contacts == [] and cross.total_accounts == 0

        # The tool refuses another workspace's project by name rather than answering empty.
        tool = ReadCrmTargetsTool(settings=SETTINGS, conn_factory=conn_session_factory(conn))
        here = _ctx(conn, world.workspace_id)
        failures = await tool.preconditions(ReadCrmTargetsInput(project_id=other.project_id), here)
        assert [failure.reason_code for failure in failures] == ["project_not_found"]
        with pytest.raises(PreconditionFailed):
            await tool.invoke(ReadCrmTargetsInput(project_id=other.project_id), here)

        # An account id that is not this project's is simply not served.
        narrowed = await _targets(world, account_ids=[str(uuid4())])
        assert narrowed.accounts == [] and narrowed.total_accounts == 0

    _run(tmp_path, "isolation", body)


@_db
def test_a_rejected_claim_is_never_offered(tmp_path: Path) -> None:
    """A rejected claim (a reviewer's or the identity gate's verdict) is dropped before the latest
    is picked: it is never offered, never named in ``withheld``, and never hides an older live
    claim."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        fit = await world.fit("fit", account, 0.9, world.project_id)
        await record_verification(conn, fit, status=VerificationStatus.REJECTED)  # type: ignore[arg-type]

        wrong = await world.person(account, "Wrong Person")
        for label, field_key, value in (
            ("wrong_title", "contact.current_title", "Secret Title"),
            ("wrong_persona", "contact.persona", "champion"),
            (
                "wrong_email",
                "core.work_email",
                {"address": "secret@zafran.io", "status": "verified_smtp"},
            ),
        ):
            claim = await world.claim(label, wrong, field_key, value)
            await record_verification(conn, claim, status=VerificationStatus.REJECTED)  # type: ignore[arg-type]

        fixed = await world.person(account, "Fixed Title")
        older = await world.claim("fixed_old", fixed, "contact.current_title", "Director")
        newer = await world.claim("fixed_new", fixed, "contact.current_title", "Bogus Title")
        await record_verification(conn, newer, status=VerificationStatus.REJECTED)  # type: ignore[arg-type]

        page = await _targets(world)
        zafran = page.accounts[0]
        assert zafran.hubspot_icp_tier is None and zafran.fit_band is None
        assert zafran.withheld == ("fit: rejected",)

        by_last = {c.last_name.value: c for c in page.contacts}
        person = by_last["Person"]
        assert person.job_title is None and person.buying_role is None
        assert person.work_email is None
        assert set(person.withheld) >= {
            "title: rejected",
            "buying role: rejected",
            "email: rejected",
        }
        leaked = repr(person)
        assert "Secret Title" not in leaked and "secret@zafran.io" not in leaked

        title = by_last["Title"].job_title
        assert title is not None and title.value == "Director" and title.claim_ids == (older,)
        assert "Bogus Title" not in repr(by_last["Title"])

    _run(tmp_path, "rejected", body)


@_db
def test_a_superseded_email_is_not_offered(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(account, "Nick Fisher")
        replacement = await world.claim(
            "replacement",
            nick,
            "core.work_email",
            {"address": "nick@zafran.io", "status": "unverified"},
        )
        stale = await world.claim(
            "stale",
            nick,
            "core.work_email",
            {"address": "old-nick@zafran.io", "status": "verified_smtp"},
        )
        await supersede_with_existing(
            conn,
            stale,  # type: ignore[arg-type]
            replacement,  # type: ignore[arg-type]
            workspace_id=world.workspace_id,
            entity_id=nick,
        )
        contact = (await _targets(world)).contacts[0]
        assert contact.work_email is None
        assert contact.withheld == ("email: not verified (unverified)",)
        assert "old-nick@zafran.io" not in repr(contact)

    _run(tmp_path, "superseded", body)


@_db
def test_the_newest_work_email_wins(tmp_path: Path) -> None:
    """The newest live ``core.work_email`` claim is the mailbox's current verdict (the screens read
    it the same way): a newer unverified address hides an older verified one, and a newer verified
    address beats an older unverified one."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        demoted = await world.person(account, "Dee Moted")
        promoted = await world.person(account, "Pro Moted")
        await world.claim(
            "demoted_old",
            demoted,
            "core.work_email",
            {"address": "dee@zafran.io", "status": "verified_smtp"},
        )
        await world.claim(
            "demoted_new",
            demoted,
            "core.work_email",
            {"address": "dee@zafran.io", "status": "unverified"},
        )
        await world.claim(
            "promoted_old",
            promoted,
            "core.work_email",
            {"address": "pro@zafran.io", "status": "unverified"},
        )
        newest = await world.claim(
            "promoted_new",
            promoted,
            "core.work_email",
            {"address": "pro@zafran.io", "status": "verified_smtp"},
        )
        by_first = {c.first_name.value: c for c in (await _targets(world)).contacts if c.first_name}
        assert by_first["Dee"].work_email is None
        assert by_first["Dee"].withheld == ("email: not verified (unverified)",)
        email = by_first["Pro"].work_email
        assert email is not None and email.claim_ids == (newest,)

    _run(tmp_path, "newest-email", body)


@_db
def test_a_merged_away_account_and_contact_are_excluded(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        survivor = await world.account("Zafran Security", "zafran.io")
        loser = await world.account("Zafran Sec (dup)", "zafran-dup.example")
        await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
        kept = await world.person(survivor, "Nick Fisher")
        twin = await world.person(survivor, "Nick Fisher Twin")
        await world.claim("kept", kept, "contact.persona", "champion")
        await world.claim("twin", twin, "contact.persona", "champion")
        await mark_merged(conn, EntityType.CONTACT, twin, kept)

        page = await _targets(world)
        assert [a.account_entity_id for a in page.accounts] == [str(survivor)]
        assert page.total_accounts == 1
        assert [c.contact_entity_id for c in page.contacts] == [str(kept)]

    _run(tmp_path, "merged", body)


@_db
def test_paging_past_the_last_page_still_counts(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        await world.account("Zafran Security", "zafran.io")
        await world.account("Probook", "probook.example")
        first = await _targets(world, limit=1)
        assert len(first.accounts) == 1 and first.total_accounts == 2
        past = await _targets(world, offset=5, limit=1)
        assert past.accounts == [] and past.contacts == [] and past.total_accounts == 2

    _run(tmp_path, "paging", body)


@_db
def test_contacts_are_capped_per_page(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        for index in range(3):
            person = await world.person(account, f"Person Number{index}")
            await world.claim(f"p{index}", person, "contact.persona", "user")

        whole = await _targets(world)
        assert len(whole.contacts) == 3 and whole.total_contacts == 3
        assert whole.contacts_note is None

        cut = await _targets(world, contacts_limit=2)
        assert [c.contact_entity_id for c in cut.contacts] == [
            c.contact_entity_id for c in whole.contacts[:2]
        ]
        assert cut.total_contacts == 3
        assert cut.contacts_note is not None and "2 of the 3" in cut.contacts_note

        # Through the tool: the limit is capped at 200 and the count and note ride along.
        with pytest.raises(ValueError):
            ReadCrmTargetsInput(project_id=world.project_id, contacts_limit=201)
        tool = ReadCrmTargetsTool(settings=SETTINGS, conn_factory=conn_session_factory(conn))
        refs = (
            await tool.invoke(
                ReadCrmTargetsInput(project_id=world.project_id, contacts_limit=1),
                _ctx(conn, world.workspace_id),
            )
        ).references
        assert len(refs["contacts"]) == 1 and refs["total_contacts"] == 3
        assert "1 of the 3" in refs["contacts_note"]

    _run(tmp_path, "contacts-cap", body)


@_db
def test_linkedin_needs_a_confirmed_fact_about_the_person(tmp_path: Path) -> None:
    """On the committee through a claim this read does not use (a facet), with nothing read that
    confirms who they are: their LinkedIn URL is not offered."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        quiet = await world.person(
            account, "Quiet Person", linkedin="https://www.linkedin.com/in/quietperson"
        )
        await world.claim(
            "facet",
            quiet,
            "contact.facet.recent_post",
            {"text": "We shipped it"},
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        )
        contact = (await _targets(world)).contacts[0]
        assert contact.contact_entity_id == str(quiet)
        assert contact.linkedin_url is None
        assert contact.withheld == ("LinkedIn: nothing confirmed about this person",)
        assert "We shipped it" not in repr(contact)

    _run(tmp_path, "linkedin-vacuous", body)


@_db
def test_an_unverified_synthesis_is_held_back_when_verification_is_on(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(account, "Nick Fisher")
        await world.claim(
            "synth_title",
            nick,
            "contact.current_title",
            "Probably VP",
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        )
        verifying = Settings(_env_file=None, verification_enabled=True)
        held = (await _targets(world, settings=verifying)).contacts[0]
        assert held.job_title is None
        assert held.withheld == ("title: not yet verified",)
        relaxed = (
            await _targets(world, settings=Settings(_env_file=None, verification_enabled=False))
        ).contacts[0]
        assert relaxed.job_title is not None and relaxed.job_title.value == "Probably VP"

    _run(tmp_path, "tier4", body)


@_db
def test_a_salesforce_account_link_is_read_as_the_executor_stores_it(tmp_path: Path) -> None:
    """The executor records a created record's link with its action's ``object``: Salesforce's
    account create is ``account`` (HubSpot's company create is ``company``). The read uses the
    same object, so a Salesforce account Clue created is found again."""

    async def body(conn: Any, world: _World, seeded: Any) -> None:
        sf_create = write_spec("salesforce", "SALESFORCE_CREATE_ACCOUNT")
        assert sf_create is not None and sf_create.object == "account"
        connection = await _connect(conn, world.workspace_id, provider="salesforce")
        account = await world.account("Zafran Security", "zafran.io")
        await writes.record_link(
            conn,
            workspace_id=world.workspace_id,
            connection_id=connection.connection_id,
            crm_object=sf_create.object,
            crm_id="001XX0000001",
            created_by_clue=True,
            clue_entity_id=UUID(str(account)),
        )
        page = await _targets(world, provider="salesforce", connection=connection)
        assert page.accounts[0].crm_record_id == "001XX0000001"

    _run(tmp_path, "sf-link", body)
