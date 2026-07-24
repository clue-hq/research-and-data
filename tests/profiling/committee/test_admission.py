"""M8.3 committee existence gate (DB-gated).

The make-or-break: a candidate resolves under the account (reuse or insert) or is dropped; a
strong-key-less (fabricated) candidate dies at the gate with no entity and no claim.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from clue_core import EntityType, ResearchMode
from clue_research.claimstore import PUBLIC_ONLY, claims_for
from clue_research.identity import get_contact, insert_contact_entity
from clue_research.profiling.committee.admission import (
    DISCOVERY_PROVENANCE_FIELD,
    AdmissionStatus,
    admit_candidate,
)
from tests._workspace import DEFAULT_TEST_WORKSPACE, seed_workspace

from ..conftest import insert_test_account, make_candidate, rollback_conn, run_async

_RUN = UUID("11111111-1111-1111-1111-111111111111")
_RUN2 = UUID("1a1a1a1a-1a1a-1a1a-1a1a-1a1a1a1a1a1a")


def test_fabricated_person_dropped_at_gate(require_profiling_db: None) -> None:
    """A candidate with no strong key has nothing to resolve to → dropped, no entity, no claim."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            candidate = make_candidate(
                source_url="https://acme.example/team", full_name="Ghost Person", title="CTO"
            )
            outcome = await admit_candidate(conn, account, candidate, run_id=_RUN)
            assert outcome.status is AdmissionStatus.DROPPED
            assert outcome.contact_entity_id is None
            assert outcome.discovery_claim_id is None

    run_async(scenario())


def test_strong_key_miss_inserts_contact_under_account(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="Chief Financial Officer",
                source_url="https://acme.example/team",
            )
            outcome = await admit_candidate(conn, account, candidate, run_id=_RUN)
            assert outcome.status is AdmissionStatus.ADMITTED
            assert outcome.reused_existing is False
            assert outcome.contact_entity_id is not None
            # the contact resolves UNDER the account (no orphan).
            contact = await get_contact(conn, outcome.contact_entity_id)
            assert contact is not None
            assert contact.account_entity_id == account.id
            # discovery-provenance written with the committee mode.
            claims = await claims_for(
                conn, outcome.contact_entity_id, DISCOVERY_PROVENANCE_FIELD, scope=PUBLIC_ONLY
            )
            assert len(claims) == 1
            assert claims[0].research_mode is ResearchMode.COMMITTEE_DISCOVERY
            assert claims[0].entity_type is EntityType.CONTACT
            assert claims[0].discovery_provenance is not None
            assert claims[0].discovery_provenance.found_via == candidate.source_key

    run_async(scenario())


def test_deterministic_hit_reuses_existing_contact(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            existing_id = await insert_contact_entity(
                conn,
                account_entity_id=account.id,
                full_name="Jane CFO",
                linkedin_url="https://linkedin.com/in/jane-cfo",
            )
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="CFO",
            )
            outcome = await admit_candidate(conn, account, candidate, run_id=_RUN)
            assert outcome.status is AdmissionStatus.ADMITTED
            assert outcome.reused_existing is True
            assert outcome.contact_entity_id == existing_id

    run_async(scenario())


def test_discovery_provenance_idempotent_in_run(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="CFO",
                source_url="https://acme.example/team",
            )
            first = await admit_candidate(conn, account, candidate, run_id=_RUN)
            second = await admit_candidate(conn, account, candidate, run_id=_RUN)
            # reused, not double-written
            assert first.discovery_claim_id == second.discovery_claim_id
            claims = await claims_for(
                conn, first.contact_entity_id, DISCOVERY_PROVENANCE_FIELD, scope=PUBLIC_ONLY
            )
            assert len(claims) == 1

    run_async(scenario())


def test_discovery_provenance_separate_across_runs(require_profiling_db: None) -> None:
    """Idempotency is per-run: the same person admitted under two runs resolves to the same contact
    but records a distinct discovery-provenance claim per run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="CFO",
                source_url="https://acme.example/team",
            )
            first = await admit_candidate(conn, account, candidate, run_id=_RUN)
            second = await admit_candidate(conn, account, candidate, run_id=_RUN2)
            assert first.contact_entity_id == second.contact_entity_id  # same resolved person
            assert first.discovery_claim_id != second.discovery_claim_id  # one provenance per run
            claims = await claims_for(
                conn, first.contact_entity_id, DISCOVERY_PROVENANCE_FIELD, scope=PUBLIC_ONLY
            )
            assert {c.run_id for c in claims} == {_RUN, _RUN2}

    run_async(scenario())


def test_admitted_committee_contact_inherits_account_workspace(require_profiling_db: None) -> None:
    """A contact admitted under a workspace-stamped account inherits that workspace: admission
    derives ``workspace_id = account.workspace_id`` and ``insert_contact_entity`` auto-stamps the
    contact from its parent account (accounts/contacts are workspace-local; [B3×research])."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, DEFAULT_TEST_WORKSPACE)
            account = await insert_test_account(conn, workspace_id=ws)
            assert account.workspace_id == ws
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="CFO",
                source_url="https://acme.example/team",
            )
            outcome = await admit_candidate(conn, account, candidate, run_id=_RUN)
            assert outcome.status is AdmissionStatus.ADMITTED
            assert outcome.contact_entity_id is not None
            contact = await get_contact(conn, outcome.contact_entity_id)
            assert contact is not None
            assert contact.workspace_id == ws  # auto-inherited from the parent account

    run_async(scenario())


def test_admit_candidate_rejects_unstamped_account(require_profiling_db: None) -> None:
    """An account with no ``workspace_id`` cannot admit a committee contact — admission fails loud
    (committee contacts are workspace-local and must derive their workspace from the account)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            unstamped = account.model_copy(update={"workspace_id": None})
            candidate = make_candidate(
                linkedin_url="https://linkedin.com/in/jane-cfo",
                full_name="Jane CFO",
                title="CFO",
                source_url="https://acme.example/team",
            )
            with pytest.raises(ValueError, match="workspace"):
                await admit_candidate(conn, unstamped, candidate, run_id=_RUN)

    run_async(scenario())
