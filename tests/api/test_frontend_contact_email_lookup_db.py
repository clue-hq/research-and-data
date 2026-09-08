"""FI-2 Slice 10 durable Contact email acquisition acceptance."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from clue_api.frontend_read.contact_email_lookup import (
    ContactEmailLookupService,
    EmailLookupState,
    EmailLookupTarget,
    ProviderArtifact,
    ProviderProgress,
    ProviderState,
    read_contact_email_lookup,
)
from clue_core import AccountStatus, EntityId
from clue_research.adapters.exa_websets import EXA_WEBSETS_SOURCE_KEY
from clue_research.compliance import DataSubjectRightsImpl, ErasureScope
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-slice10-email"
_OTHER_WS = "fi2-slice10-email-other"


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        raise AssertionError(f"lookup must not presign {key!r} for {expires_in}s")

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", datetime.min.replace(tzinfo=UTC)


class _ImmediateProvider:
    def __init__(self, source_key: str, email: str | None) -> None:
        self.source_key = source_key
        self.email = email
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    def request_json(self, target: EmailLookupTarget) -> dict[str, str]:
        return {"profileUrl": target.linkedin_url, "fieldKey": "core.work_email"}

    async def start(self, target: EmailLookupTarget, *, external_id: str) -> ProviderProgress:
        self.calls += 1
        payload = json.dumps(
            {
                "source": self.source_key,
                "profile": target.linkedin_url,
                "email": self.email,
            },
            sort_keys=True,
        ).encode()
        return ProviderProgress(
            state=ProviderState.AVAILABLE if self.email else ProviderState.NO_RESULT,
            provider_operation_id=f"{self.source_key}-{external_id}",
            email=self.email,
            source_url=target.linkedin_url,
            observed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            credits_used=Decimal(10 if self.email else 0),
            artifacts=(
                ProviderArtifact(
                    kind="fixture_provider_result",
                    content=payload,
                    source_url=target.linkedin_url,
                    request_id=f"request-{self.source_key}",
                ),
            ),
        )

    async def poll(self, target: EmailLookupTarget, attempt: object) -> ProviderProgress:
        del target, attempt
        raise AssertionError("an immediate provider is never polled")


def test_durable_matching_results_are_unverified_governed_and_replay_safe() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            await seed_workspace(conn, _OTHER_WS)
            account_id = await insert_account_entity(
                conn,
                canonical_name="Northstar Health",
                primary_domain="northstar.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WS,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Dana Buyer",
                linkedin_url="https://www.linkedin.com/in/dana-buyer",
                status=AccountStatus.ACTIVE,
            )
            target = EmailLookupTarget(
                workspace_id=_WS,
                account_id=uuid.UUID(str(account_id)),
                contact_id=uuid.UUID(str(contact_id)),
                full_name="Dana Buyer",
                linkedin_url="https://www.linkedin.com/in/dana-buyer",
                account_name="Northstar Health",
                primary_domain="northstar.example",
            )
            exa = _ImmediateProvider(EXA_WEBSETS_SOURCE_KEY, "Dana@Northstar.example")
            sumble = _ImmediateProvider(PEOPLE_SOURCE_KEY, "dana@northstar.example")
            lock = asyncio.Lock()

            @asynccontextmanager
            async def _conn_factory():
                async with lock:
                    yield conn

            storage = _MemoryStorage()
            service = ContactEmailLookupService(
                providers=(exa, sumble),
                storage=storage,
                conn_factory=_conn_factory,
            )

            first = await service.start(target=target, requested_by="usr-founder")
            replay = await service.start(target=target, requested_by="usr-founder")

            assert first == replay
            assert first.state is EmailLookupState.AVAILABLE
            assert [item.value for item in first.emails] == ["dana@northstar.example"]
            assert {source.label for source in first.emails[0].sources} == {"Exa", "Sumble"}
            assert exa.calls == sumble.calls == 1

            lookup_row = (
                await conn.execute(
                    text(
                        "SELECT requested_by, policy_version FROM contact_email_lookup WHERE id=:id"
                    ),
                    {"id": first.lookup_id},
                )
            ).one()
            assert tuple(lookup_row) == ("usr-founder", 1)

            claims = (
                await conn.execute(
                    text(
                        """
                        SELECT source_key, value_json, verification_status, identity_binding,
                               use_class, reuse_scope, workspace_id
                        FROM claim
                        WHERE source_operation_ref=:lookup_id
                        ORDER BY source_key
                        """
                    ),
                    {"lookup_id": str(first.lookup_id)},
                )
            ).all()
            assert len(claims) == 2
            assert {str(row[0]) for row in claims} == {EXA_WEBSETS_SOURCE_KEY, PEOPLE_SOURCE_KEY}
            # D4-b decision 6: the stored value is the address with the verdict that grades it.
            # Neither acquisition source probes a mailbox, so both write ``unverified`` — the same
            # thing ``verification_status`` says one column over, and the reason the chip offers a
            # lookup rather than presenting these addresses as verified.
            assert all(
                row[1] == {"address": "dana@northstar.example", "status": "unverified"}
                for row in claims
            )
            governance_rows = [
                (str(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6])) for row in claims
            ]
            assert (
                governance_rows
                == [
                    (
                        "unverified",
                        "strong",
                        "professional-public",
                        "tenant_private",
                        _WS,
                    )
                ]
                * 2
            )
            assert (
                await conn.execute(
                    text("SELECT verified_email FROM contact_entity WHERE id=:id"),
                    {"id": contact_id},
                )
            ).scalar_one() is None
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM use_decision WHERE claim_id IN "
                        "(SELECT id FROM claim WHERE source_operation_ref=:lookup_id)"
                    ),
                    {"lookup_id": str(first.lookup_id)},
                )
            ).scalar_one() == 2
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM lawful_basis_record WHERE claim_id IN "
                        "(SELECT id FROM claim WHERE source_operation_ref=:lookup_id)"
                    ),
                    {"lookup_id": str(first.lookup_id)},
                )
            ).scalar_one() == 2
            assert len(storage.blobs) == 2
            assert (
                await read_contact_email_lookup(
                    conn, workspace_id=_OTHER_WS, lookup_id=first.lookup_id
                )
                is None
            )

            erased = await DataSubjectRightsImpl(
                _WS,
                conn_factory=_conn_factory,
                storage=storage,
            ).erase(
                EntityId(contact_id),
                ErasureScope(field_keys=frozenset({"core.work_email"})),
            )
            assert len(erased.tombstoned_claim_ids) == 2
            after_erasure = await read_contact_email_lookup(
                conn,
                workspace_id=_WS,
                lookup_id=first.lookup_id,
            )
            assert after_erasure is not None
            assert after_erasure.state is EmailLookupState.WITHHELD
            assert after_erasure.emails == ()
            assert storage.blobs == {}

    run_async(_run())


def test_channel_suppression_prevents_provider_dispatch() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            account_id = await insert_account_entity(
                conn,
                canonical_name="Suppressed Account",
                primary_domain="suppressed.example",
                workspace_id=_WS,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Suppressed Person",
                linkedin_url="https://www.linkedin.com/in/suppressed-person",
            )
            await conn.execute(
                text(
                    "INSERT INTO contact_channel_suppression "
                    "(workspace_id, contact_id, channel, reason) "
                    "VALUES (:workspace_id, :contact_id, 'email', 'erasure')"
                ),
                {"workspace_id": _WS, "contact_id": contact_id},
            )
            exa = _ImmediateProvider(EXA_WEBSETS_SOURCE_KEY, "person@example.com")
            sumble = _ImmediateProvider(PEOPLE_SOURCE_KEY, "person@example.com")

            @asynccontextmanager
            async def _conn_factory():
                yield conn

            service = ContactEmailLookupService(
                providers=(exa, sumble),
                storage=_MemoryStorage(),
                conn_factory=_conn_factory,
            )
            target = EmailLookupTarget(
                workspace_id=_WS,
                account_id=uuid.UUID(str(account_id)),
                contact_id=uuid.UUID(str(contact_id)),
                full_name="Suppressed Person",
                linkedin_url="https://www.linkedin.com/in/suppressed-person",
                account_name="Suppressed Account",
                primary_domain="suppressed.example",
            )
            with pytest.raises(PermissionError, match="suppressed"):
                await service.start(target=target, requested_by="usr-founder")
            assert exa.calls == sumble.calls == 0
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM contact_email_lookup WHERE contact_id=:contact_id"),
                    {"contact_id": contact_id},
                )
            ).scalar_one() == 0

    run_async(_run())
