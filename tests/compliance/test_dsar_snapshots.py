"""PB-B2.5 — DSAR erasure reaches stored evidence snapshots (refcounted, ruling 2).

The exit gate: erase of the *only* claim citing a snapshot deletes the physical blob and stamps
``erased_at`` on the (retained, personal-content-free) artifact row; erase while another data
subject's live claim still cites the same snapshot leaves the blob — the last erasure removes it
(the Jana/Raj scenario). Retention age-out gets the same reach; without an injected backend the
behavior is exactly pre-B2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    AgeOutCandidate,
    Claim,
    EntityId,
    FieldKey,
    RawArtifact,
    UseClass,
    revalidate_with,
)
from clue_research.claimstore import insert_claim
from clue_research.compliance import DataSubjectRightsImpl, RetentionSweep
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse
from clue_storage import (
    FsStorage,
    SnapshotSink,
    StorageBackend,
    flush_snapshots,
    get_artifact,
)
from tests.compliance.test_dsar import (
    _CLIENT,
    _FACET,
    _contact,
    _facet_claim,
    _StubFreshness,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_compliance_db")

_PAGE = b"<html>Jana Doe runs the Berlin marathon. Raj Patel runs it too.</html>"


@asynccontextmanager
async def _yield(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


def _rights_with_storage(conn: AsyncConnection, storage: StorageBackend) -> DataSubjectRightsImpl:
    """The in-lane wiring (PB-B2 ruling 6): the api-root injection lands at integration."""
    return DataSubjectRightsImpl(_CLIENT, conn_factory=lambda: _yield(conn), storage=storage)


async def _snapshot(conn: AsyncConnection, storage: StorageBackend) -> str:
    """Store one evidence snapshot (blob + artifact row) in the controller's scope."""
    sink = SnapshotSink(workspace_id=_CLIENT)
    key = sink.capture(
        RawArtifact(ref="https://acme.de/team", media_type="text/html", content=_PAGE),
        source_key="firecrawl_site",
    )
    await flush_snapshots(conn, storage, sink)
    return key


async def _insert_cited_facet(conn: AsyncConnection, contact: EntityId, key: str) -> Claim:
    claim = revalidate_with(
        _facet_claim(contact, use_class=UseClass.PROFESSIONAL_PUBLIC), artifact_key=key
    )
    stamped = stamp_reuse(claim, workspace_id=_CLIENT)
    await insert_claim(conn, stamped)
    return stamped


async def _second_contact(conn: AsyncConnection) -> EntityId:
    account = await insert_account_entity(
        conn, canonical_name="Globex GmbH", primary_domain="globex.de", status=AccountStatus.ACTIVE
    )
    return await insert_contact_entity(
        conn, account_entity_id=account, full_name="Raj Patel", status=AccountStatus.ACTIVE
    )


def test_erase_deletes_the_orphaned_snapshot(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            jana = await _contact(conn)
            key = await _snapshot(conn, storage)
            await _insert_cited_facet(conn, jana, key)

            await _rights_with_storage(conn, storage).erase(jana)

            assert not await storage.exists(key)  # the blob is gone
            record = await get_artifact(conn, key)
            assert record is not None  # the audit row survives (no personal content)
            assert record.erased_at is not None

    run_async(scenario())


def test_shared_snapshot_survives_until_the_last_reference(tmp_path: object) -> None:
    """Jana's erasure severs her link but keeps the blob (Raj's live claim still cites it);
    erasing Raj too removes it — the refcount check via the claim→artifact link (ruling 2)."""

    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            jana = await _contact(conn)
            raj = await _second_contact(conn)
            key = await _snapshot(conn, storage)
            await _insert_cited_facet(conn, jana, key)
            await _insert_cited_facet(conn, raj, key)
            rights = _rights_with_storage(conn, storage)

            await rights.erase(jana)
            assert await storage.exists(key)  # Raj's evidence must survive
            record = await get_artifact(conn, key)
            assert record is not None and record.erased_at is None

            await rights.erase(raj)  # the last reference goes → the blob goes
            assert not await storage.exists(key)
            record = await get_artifact(conn, key)
            assert record is not None and record.erased_at is not None

    run_async(scenario())


def test_retention_sweep_reaches_snapshots(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            jana = await _contact(conn)
            key = await _snapshot(conn, storage)
            claim = await _insert_cited_facet(conn, jana, key)
            candidate = AgeOutCandidate(
                claim_id=claim.id,
                entity_id=jana,
                field_key=FieldKey(_FACET),
                age_days=40.0,
                retention_days=30.0,
            )
            sweep = RetentionSweep(
                _StubFreshness((candidate,)),
                conn_factory=lambda: _yield(conn),
                storage=storage,
            )

            result = await sweep.sweep_expired()
            assert result.tombstoned_claim_ids
            assert not await storage.exists(key)
            record = await get_artifact(conn, key)
            assert record is not None and record.erased_at is not None

    run_async(scenario())


def test_without_injected_storage_behavior_is_pre_b2(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            jana = await _contact(conn)
            key = await _snapshot(conn, storage)
            await _insert_cited_facet(conn, jana, key)

            rights = DataSubjectRightsImpl(_CLIENT, conn_factory=lambda: _yield(conn))
            await rights.erase(jana)  # no storage injected

            assert await storage.exists(key)  # blob untouched
            record = await get_artifact(conn, key)
            assert record is not None and record.erased_at is None

    run_async(scenario())
