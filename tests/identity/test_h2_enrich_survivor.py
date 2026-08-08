"""FI-2 slice-0 H2 — an auto-merge onto an existing account keeps what the sighting knew.

The defect this pins (spec ``docs/specs/FI-2-workspace-account-layer.md`` §8.2): when
``disposition`` AUTO_MERGES an observation onto an account that already exists and there is no
pre-admitted ``subject_entity_id`` (the import / discovery-admission shape — the observation *is*
the loser), the only thing that ran was ``record_disposition``. The sighting's aliases, the registry
ids the account lacked, its geo — all discarded. ``update_account`` and ``plan_merge`` existed, but
only ``auto_merge`` (a real loser entity, i.e. the human-review path) could reach them, so an
account could be re-imported forever and never learn a thing.

The contract is deliberately conservative (founder-ratified): union what the survivor lacks, never
overwrite what it asserts, never rename it, and never let a strong-key collision fail the ingest.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import AccountStatus, EntityId, EntityType, new_run_id
from clue_research.discovery_scoring import AdmissionStatus, admit
from clue_research.discovery_scoring.discovery import CandidateHypothesis
from clue_research.identity import (
    CrossWorkspaceMergeError,
    DispositionOutcome,
    Observation,
    disposition,
    embed_account,
    enrich_account,
    enrich_survivor,
    get_account,
    insert_account_entity,
    resolve,
)
from clue_research.stage0 import ImportRow, import_accounts
from tests._workspace import seed_workspace
from tests.stage0._fakes import build_confirmed_icp
from tests.stage0.conftest import rollback_conn as stage0_rollback_conn

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")

_WS = "h2-enrich"


async def _seed_account(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    name: str = "Novaflow Robotics",
    domain: str | None = "novaflow.example",
    registry_ids: dict[str, str] | None = None,
    hq_geo: dict[str, object] | None = None,
) -> EntityId:
    """An account that already exists in the workspace — the survivor every case below lands on."""
    entity_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        registry_ids=registry_ids,
        hq_geo=hq_geo,
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    await embed_account(conn, entity_id)
    return entity_id


async def _auto_merge_onto(
    conn: AsyncConnection, observation: Observation, *, workspace_id: str
) -> EntityId:
    """Drive the real seam (resolve → disposition) and assert it took the auto-merge branch."""
    result = await resolve(conn, observation, workspace_id=workspace_id)
    decision = await disposition(conn, observation, result, workspace_id=workspace_id)
    assert decision.outcome is DispositionOutcome.AUTO_MERGED
    assert decision.entity_id is not None
    return decision.entity_id


async def _version(conn: AsyncConnection, entity_id: EntityId) -> int:
    account = await get_account(conn, entity_id)
    assert account is not None
    return account.canonical_version


def test_strong_key_match_absorbs_a_new_alias_and_a_registry_id_the_survivor_lacks() -> None:
    """(a) The core case: matched by domain, the survivor gains the sighting's alias and DUNS."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(conn, workspace_id=ws)
            before = await _version(conn, survivor)

            matched = await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics Inc",
                    domain="novaflow.example",
                    aliases=("Novaflow",),
                    registry_ids={"DUNS": "12-345-6789"},
                ),
                workspace_id=ws,
            )
            assert matched == survivor

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.registry_ids["DUNS"] == "123456789"  # canonicalized on the way in
            assert {"novaflow", "novaflow robotics inc"} <= set(account.aliases)
            assert account.canonical_version == before + 1

    run_async(_run())


def test_the_survivors_own_registry_id_wins_over_the_sightings() -> None:
    """(b) Survivor-wins on a namespace collision — its id is the already-resolved one."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(
                conn, workspace_id=ws, registry_ids={"DUNS": "111111111"}
            )

            await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics",
                    domain="novaflow.example",
                    registry_ids={"DUNS": "999999999"},
                ),
                workspace_id=ws,
            )

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.registry_ids == {"DUNS": "111111111"}

    run_async(_run())


def test_geo_fills_a_gap_but_never_overwrites() -> None:
    """(c) Both halves: an empty ``hq_geo`` is filled from the sighting, a populated one stands."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            empty = await _seed_account(conn, workspace_id=ws)
            await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics",
                    domain="novaflow.example",
                    geo={"country": "US", "city": "Austin"},
                ),
                workspace_id=ws,
            )
            filled = await get_account(conn, empty)
            assert filled is not None and filled.hq_geo == {"country": "US", "city": "Austin"}

            known = await _seed_account(
                conn,
                workspace_id=ws,
                name="Quietwave Systems",
                domain="quietwave.example",
                hq_geo={"country": "DE"},
            )
            await _auto_merge_onto(
                conn,
                Observation(
                    name="Quietwave Systems",
                    domain="quietwave.example",
                    geo={"country": "US", "city": "Austin"},
                ),
                workspace_id=ws,
            )
            untouched = await get_account(conn, known)
            assert untouched is not None and untouched.hq_geo == {"country": "DE"}

    run_async(_run())


def test_a_domain_gap_is_filled_but_an_asserted_domain_is_never_re_keyed() -> None:
    """The strong key follows the same gap-fill rule as geo — a domain-less account matched on its
    registry id learns its domain, but an account that already asserts one is never re-keyed by a
    sighting (re-keying is a merge decision, and merges route through ``auto_merge``)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            domainless = await _seed_account(
                conn, workspace_id=ws, domain=None, registry_ids={"DUNS": "123456789"}
            )
            await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics",
                    domain="https://www.Novaflow.example/careers",
                    registry_ids={"DUNS": "12-345-6789"},
                ),
                workspace_id=ws,
            )
            filled = await get_account(conn, domainless)
            assert filled is not None and filled.primary_domain == "novaflow.example"

            keyed = await _seed_account(
                conn, workspace_id=ws, name="Quietwave Systems", domain="quietwave.example"
            )
            assert not await enrich_account(
                conn, keyed, workspace_id=ws, primary_domain="quietwave-systems.example"
            )
            unchanged = await get_account(conn, keyed)
            assert unchanged is not None and unchanged.primary_domain == "quietwave.example"

    run_async(_run())


def test_a_domain_another_account_already_holds_is_skipped_not_raised() -> None:
    """The unique-index case: the fill is dropped, the enrichment still lands, nothing raises —
    an ingest is never failed by a strong key that belongs to a neighbour."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            await _seed_account(conn, workspace_id=ws, name="Holder", domain="contested.example")
            domainless = await _seed_account(
                conn, workspace_id=ws, name="Novaflow Robotics", domain=None
            )

            changed = await enrich_account(
                conn,
                domainless,
                workspace_id=ws,
                primary_domain="contested.example",
                add_aliases=("Novaflow",),
            )

            account = await get_account(conn, domainless)
            assert account is not None
            assert account.primary_domain is None  # the fill was skipped
            assert changed and "novaflow" in account.aliases  # the rest still landed

    run_async(_run())


def test_a_registry_id_another_account_already_holds_is_skipped_not_raised() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            await _seed_account(
                conn,
                workspace_id=ws,
                name="Holder",
                domain="holder.example",
                registry_ids={"DUNS": "123456789"},
            )
            survivor = await _seed_account(conn, workspace_id=ws)

            await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics",
                    domain="novaflow.example",
                    aliases=("Nova Flow Robotics",),
                    registry_ids={"DUNS": "123456789"},
                ),
                workspace_id=ws,
            )

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.registry_ids == {}  # someone else's strong key, skipped
            assert "nova flow robotics" in account.aliases  # the sighting still taught us something

    run_async(_run())


def test_the_canonical_name_is_never_changed_by_a_sighting() -> None:
    """(d) Even a longer, more informative name only becomes an *alias* — renaming an account is a
    canonicalization decision, and canonicalization needs a confirmed merge."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(conn, workspace_id=ws, name="Novaflow")

            await _auto_merge_onto(
                conn,
                Observation(
                    name="Novaflow Robotics International Corporation",
                    domain="novaflow.example",
                ),
                workspace_id=ws,
            )

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.canonical_name == "Novaflow"
            assert "novaflow robotics international" in account.aliases

    run_async(_run())


def test_a_sighting_that_adds_nothing_writes_nothing() -> None:
    """(e) ``canonical_version`` (C7 view identity) advances iff the account actually changed — a
    re-import of an identical row must not churn every saved view that cites the account."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(
                conn,
                workspace_id=ws,
                registry_ids={"DUNS": "123456789"},
                hq_geo={"country": "US"},
            )
            observation = Observation(
                name="Novaflow Robotics",
                domain="novaflow.example",
                registry_ids={"DUNS": "123456789"},
                geo={"country": "DE"},
            )
            await _auto_merge_onto(conn, observation, workspace_id=ws)
            settled = await _version(conn, survivor)

            assert not await enrich_survivor(
                conn, survivor_id=survivor, observation=observation, workspace_id=ws
            )
            assert await _version(conn, survivor) == settled

    run_async(_run())


def test_enrichment_refuses_to_cross_a_workspace() -> None:
    """Accounts are workspace-local; a hand-built cross-tenant call fails loud, never writes."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            other = await seed_workspace(conn, "h2-enrich-other")
            theirs = await _seed_account(conn, workspace_id=other)

            with pytest.raises(CrossWorkspaceMergeError):
                await enrich_account(conn, theirs, workspace_id=ws, add_aliases=("Nova",))

    run_async(_run())


def test_a_contact_observation_enriches_nothing() -> None:
    """Accounts only — a contact sighting has no gap-fill contract yet (committee work is M8)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(conn, workspace_id=ws)
            assert not await enrich_survivor(
                conn,
                survivor_id=survivor,
                observation=Observation(name="Jane Doe", entity_type=EntityType.CONTACT),
                workspace_id=ws,
            )

    run_async(_run())


# --- end to end, through the two production entry paths ----------------------
def test_import_row_matching_an_existing_account_enriches_it() -> None:
    """The import path end to end: a row whose domain hits an account already in the workspace
    contributes its alias, its registry id and its geo instead of being dropped on the floor."""

    async def _run() -> None:
        async with stage0_rollback_conn(workspace_id=_WS) as conn:
            client = await insert_account_entity(
                conn,
                canonical_name="Import Client",
                primary_domain="client-h2.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WS,
            )
            icp = await build_confirmed_icp(conn, workspace_id=_WS, icp_key="h2")
            survivor = await _seed_account(conn, workspace_id=_WS)

            result = await import_accounts(
                conn,
                [
                    ImportRow(
                        row_index=1,
                        name="Novaflow Robotics Incorporated",
                        domain="novaflow.example",
                        aliases=("Nova Flow",),
                        registry_ids={"DUNS": "12-345-6789"},
                        geo={"country": "US"},
                    )
                ],
                icp,
                workspace_id=_WS,
                client_entity_id=client,
            )
            assert [r.account_entity_id for r in result.resolved] == [survivor]

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.canonical_name == "Novaflow Robotics"  # unchanged
            assert account.registry_ids == {"DUNS": "123456789"}
            assert account.hq_geo == {"country": "US"}
            assert {"nova flow", "novaflow robotics incorporated"} <= set(account.aliases)

    run_async(_run())


def test_discovery_admission_matching_an_existing_account_enriches_it() -> None:
    """The discovery path end to end: re-discovering a known company through another channel adds
    that channel's name spelling as an alias and fills the geo the account lacked."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, _WS)
            survivor = await _seed_account(conn, workspace_id=ws)

            admitted = await admit(
                conn,
                CandidateHypothesis(
                    matched_channel="exa",
                    source_record_ref="rec:h2",
                    raw_name="Novaflow Robotics GmbH",
                    candidate_domain="novaflow.example",
                    candidate_geo={"country": "DE"},
                    matched_signal="series-b saas",
                    resolver_confidence=0.8,
                ),
                new_run_id(),
                workspace_id=ws,
            )
            assert admitted.status is AdmissionStatus.ADMITTED
            assert admitted.account_entity_id == survivor

            account = await get_account(conn, survivor)
            assert account is not None
            assert account.canonical_name == "Novaflow Robotics"
            assert account.hq_geo == {"country": "DE"}
            assert "novaflow robotics gmbh" in account.aliases

    run_async(_run())
