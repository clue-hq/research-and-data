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
from clue_config import Settings
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    new_run_id,
)
from clue_research.claimstore.run_lineage import record_run_lineage
from clue_research.identity import insert_account_entity, insert_contact_entity
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
    world: _World, *, provider: str | None = "hubspot", connection: Any = None
) -> ProjectTargets:
    return await project_targets(
        world.conn,
        workspace_id=world.workspace_id,
        project_id=world.project_id,
        connection_id=connection.connection_id if connection is not None else None,
        provider=provider,  # type: ignore[arg-type]
        settings=SETTINGS,
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
def test_only_a_verified_smtp_email_is_offered(tmp_path: Path) -> None:
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(account, "Nick Fisher")
        vari = await world.person(account, "Vari Bindra")
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
            {"address": "vari@zafran.io", "status": "catch_all_valid"},
        )

        page = await _targets(world)
        by_last = {contact.last_name.value: contact for contact in page.contacts}
        assert by_last["Fisher"].work_email is not None
        assert by_last["Fisher"].work_email.value == "nick@zafran.io"
        assert by_last["Fisher"].work_email.claim_ids == (verified,)
        assert by_last["Bindra"].work_email is None
        assert "email: not verified (catch_all_valid)" in by_last["Bindra"].withheld

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
    async def body(conn: Any, world: _World, seeded: Any) -> None:
        account = await world.account("Zafran Security", "zafran.io")
        nick = await world.person(account, "Nick Fisher")
        await world.claim("nick_persona", nick, "contact.persona", "champion")

        page = await project_targets(
            conn,
            workspace_id="ws-crmt-someone-else",
            project_id=world.project_id,
            connection_id=None,
            provider=None,
            settings=SETTINGS,
        )
        assert page.accounts == [] and page.contacts == [] and page.total_accounts == 0

        # The tool refuses another workspace's project by name rather than answering empty.
        tool = ReadCrmTargetsTool(settings=SETTINGS, conn_factory=conn_session_factory(conn))
        foreign = _ctx(conn, "ws-crmt-someone-else")
        failures = await tool.preconditions(
            ReadCrmTargetsInput(project_id=world.project_id), foreign
        )
        assert [failure.reason_code for failure in failures] == ["project_not_found"]
        with pytest.raises(PreconditionFailed):
            await tool.invoke(ReadCrmTargetsInput(project_id=world.project_id), foreign)

        # An account id that is not this project's is simply not served.
        narrowed = await project_targets(
            conn,
            workspace_id=world.workspace_id,
            project_id=world.project_id,
            connection_id=None,
            provider=None,
            settings=SETTINGS,
            account_ids=[str(uuid4())],
        )
        assert narrowed.accounts == [] and narrowed.total_accounts == 0

    _run(tmp_path, "isolation", body)
