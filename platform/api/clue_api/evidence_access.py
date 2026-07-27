"""C7.4 current-policy evidence access boundary.

This API-root service is the only C7 component allowed to translate a safe evidence descriptor
into request-time access.  It revalidates actor/scope, the exact persisted action relation, the
current claim, retention/DSAR state, and artifact lifecycle before returning an opaque capability.
Source URLs, object keys, signed URLs, evidence spans, and bodies are never returned or audited.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast, runtime_checkable
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EvidenceAccessAuthorizer,
    EvidenceAccessRequest,
    EvidenceAccessResult,
    EvidenceActionKind,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_storage import StorageBackend, get_artifact

_MAX_PREVIEW_TTL_SECONDS = 300


@runtime_checkable
class EvidenceCapabilityBroker(Protocol):
    """Short-lived server-side target registry behind opaque response references."""

    def issue(self, target: str, *, expires_in: int) -> str: ...
    def resolve(self, access_ref: str) -> str | None: ...


class EphemeralEvidenceCapabilityBroker:
    """Process-local bounded capability registry.

    This is intentionally not durable state. A restart invalidates capabilities, expiry is
    server-controlled, and the signed/source target never crosses the C7 contract or audit log.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: dict[str, tuple[str, datetime]] = {}

    def issue(self, target: str, *, expires_in: int) -> str:
        now = self._clock()
        self._prune(now)
        access_ref = f"evidence-capability:{uuid4().hex}"
        self._entries[access_ref] = (target, now + timedelta(seconds=expires_in))
        return access_ref

    def resolve(self, access_ref: str) -> str | None:
        now = self._clock()
        self._prune(now)
        entry = self._entries.get(access_ref)
        return entry[0] if entry is not None else None

    def _prune(self, now: datetime) -> None:
        for key, (_target, expires_at) in tuple(self._entries.items()):
            if expires_at <= now:
                self._entries.pop(key, None)


class EvidenceAccessServiceImpl:
    """Resolve evidence under current authorization and lifecycle state."""

    def __init__(
        self,
        authorizer: EvidenceAccessAuthorizer,
        storage: StorageBackend,
        capabilities: EvidenceCapabilityBroker,
        *,
        conn_factory: ConnFactory = transaction,
        preview_ttl_seconds: int = _MAX_PREVIEW_TTL_SECONDS,
    ) -> None:
        self._authorizer = authorizer
        self._storage = storage
        self._capabilities = capabilities
        self._conn_factory = conn_factory
        self._preview_ttl_seconds = min(max(1, preview_ttl_seconds), _MAX_PREVIEW_TTL_SECONDS)

    async def request_access(self, request: EvidenceAccessRequest) -> EvidenceAccessResult:
        decision = await self._authorizer.authorize(request)
        if decision.claim_id != request.claim_id:
            return await self._deny(request, EvidenceActionKind.UNAVAILABLE, ("claim_mismatch",))
        if not decision.allowed:
            return await self._deny(
                request,
                decision.action_kind,
                tuple(decision.reason_codes),
            )
        if decision.action_kind is not request.desired_action:
            return await self._deny(request, EvidenceActionKind.UNAVAILABLE, ("action_mismatch",))

        async with self._conn_factory() as conn:
            action = await _load_exact_action(conn, request)
            if action is None:
                return await self._deny_with_conn(
                    conn, request, EvidenceActionKind.UNAVAILABLE, ("action_not_found",)
                )
            if action["action_kind"] != request.desired_action.value:
                return await self._deny_with_conn(
                    conn, request, EvidenceActionKind.UNAVAILABLE, ("action_mismatch",)
                )

            claims = await claims_by_ids(
                conn,
                (request.claim_id,),
                scope=WorkspaceScope.for_workspace(request.workspace_id),
            )
            claim = claims.get(request.claim_id)
            if claim is None:
                redacted = await _claim_was_erased(conn, request)
                return await self._deny_with_conn(
                    conn,
                    request,
                    (EvidenceActionKind.REDACTED if redacted else EvidenceActionKind.UNAVAILABLE),
                    ("claim_erased",) if redacted else ("claim_unavailable",),
                )
            if claim.entity_id != request.subject_entity_id:
                return await self._deny_with_conn(
                    conn, request, EvidenceActionKind.UNAVAILABLE, ("subject_mismatch",)
                )

            kind = request.desired_action
            provider_label = action["provider_label"] or claim.source_key
            media_type = action["media_type"]
            target: str | None = None
            if kind is EvidenceActionKind.OPEN_PUBLIC_SOURCE:
                if claim.source_url is None or not _safe_public_url(claim.source_url):
                    return await self._deny_with_conn(
                        conn, request, EvidenceActionKind.UNAVAILABLE, ("source_unavailable",)
                    )
                target = claim.source_url
            elif kind is EvidenceActionKind.VIEW_API_PROVENANCE:
                # The capability identifies a server endpoint; it never contains API response
                # bytes or the source's credential-bearing locator.
                target = f"api-provenance:{request.claim_id}"
            elif kind is EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW:
                if claim.artifact_key is None:
                    return await self._deny_with_conn(
                        conn, request, EvidenceActionKind.UNAVAILABLE, ("artifact_unavailable",)
                    )
                artifact = await get_artifact(conn, claim.artifact_key)
                if (
                    artifact is None
                    or artifact.erased_at is not None
                    or artifact.purged_at is not None
                    or (
                        artifact.workspace_id is not None
                        and artifact.workspace_id != request.workspace_id
                    )
                    or not _previewable_media_type(artifact.media_type)
                    or not await self._storage.exists(claim.artifact_key)
                ):
                    return await self._deny_with_conn(
                        conn,
                        request,
                        (
                            EvidenceActionKind.REDACTED
                            if artifact is not None and artifact.erased_at is not None
                            else EvidenceActionKind.UNAVAILABLE
                        ),
                        (
                            ("artifact_erased",)
                            if artifact is not None and artifact.erased_at is not None
                            else ("artifact_unavailable",)
                        ),
                    )
                media_type = artifact.media_type
                # Sole C7 presigning boundary (architecture-tested). The URL exists only behind
                # the ephemeral broker and never enters Postgres, a receipt, an event, or a tool
                # result.
                target = await self._storage.presign(
                    claim.artifact_key,
                    expires_in=self._preview_ttl_seconds,
                )
            else:  # pragma: no cover - core request validation excludes outcome-only kinds
                return await self._deny_with_conn(
                    conn, request, EvidenceActionKind.UNAVAILABLE, ("action_unsupported",)
                )

            access_ref = self._capabilities.issue(target, expires_in=self._preview_ttl_seconds)
            reasons = ("authorized",)
            await _write_audit(
                conn,
                request,
                outcome=kind,
                allowed=True,
                reason_codes=reasons,
            )
            return EvidenceAccessResult(
                action_kind=kind,
                claim_id=request.claim_id,
                access_ref=access_ref,
                provider_label=cast(str | None, provider_label),
                media_type=cast(str | None, media_type),
                reason_codes=reasons,
            )

    async def _deny(
        self,
        request: EvidenceAccessRequest,
        outcome: EvidenceActionKind,
        reasons: tuple[str, ...],
    ) -> EvidenceAccessResult:
        async with self._conn_factory() as conn:
            return await self._deny_with_conn(conn, request, outcome, reasons)

    async def _deny_with_conn(
        self,
        conn: AsyncConnection,
        request: EvidenceAccessRequest,
        outcome: EvidenceActionKind,
        reasons: tuple[str, ...],
    ) -> EvidenceAccessResult:
        bounded_reasons = _bounded_reason_codes(reasons)
        await _write_audit(
            conn,
            request,
            outcome=outcome,
            allowed=False,
            reason_codes=bounded_reasons,
        )
        return EvidenceAccessResult(
            action_kind=outcome,
            claim_id=request.claim_id,
            reason_codes=bounded_reasons,
        )


async def _load_exact_action(
    conn: AsyncConnection, request: EvidenceAccessRequest
) -> dict[str, object] | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT a.action_kind, a.provider_label, a.media_type
                FROM research_view_snapshot_evidence_action a
                JOIN research_view_snapshot_item i
                  ON i.snapshot_id = a.snapshot_id
                 AND i.section_ordinal = a.section_ordinal
                 AND i.ordinal = a.item_ordinal
                JOIN research_view_snapshot s ON s.snapshot_id = a.snapshot_id
                JOIN project p ON p.project_id = s.project_id
                WHERE a.action_id = :action_id
                  AND a.statement_id = :statement_id
                  AND a.claim_id = :claim_id
                  AND i.item_subject_entity_id = :subject_entity_id
                  AND s.workspace_id = :workspace_id
                  AND s.project_id = :project_id
                  AND p.workspace_id = :workspace_id
                ORDER BY s.created_at DESC
                LIMIT 1
                """
                ),
                {
                    "action_id": str(request.action_id),
                    "statement_id": str(request.statement_id),
                    "claim_id": str(request.claim_id),
                    "subject_entity_id": str(request.subject_entity_id),
                    "workspace_id": request.workspace_id,
                    "project_id": request.project_id,
                },
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def _claim_was_erased(conn: AsyncConnection, request: EvidenceAccessRequest) -> bool:
    result = await conn.execute(
        text(
            """
                SELECT EXISTS (
                    SELECT 1 FROM dsar_tombstone
                    WHERE erased_claim_id = :claim_id
                      AND workspace_id = :workspace_id
                      AND contact_entity_id = :subject_entity_id
                )
                """
        ),
        {
            "claim_id": str(request.claim_id),
            "workspace_id": request.workspace_id,
            "subject_entity_id": str(request.subject_entity_id),
        },
    )
    return bool(result.scalar_one())


async def _write_audit(
    conn: AsyncConnection,
    request: EvidenceAccessRequest,
    *,
    outcome: EvidenceActionKind,
    allowed: bool,
    reason_codes: tuple[str, ...],
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO evidence_access_audit (
                workspace_id, project_id, actor_id, subject_entity_id, statement_id,
                claim_id, action_id, requested_action, outcome_action, allowed, reason_codes
            ) VALUES (
                :workspace_id, :project_id, :actor_id, :subject_entity_id, :statement_id,
                :claim_id, :action_id, :requested_action, :outcome_action, :allowed, :reason_codes
            )
            """
        ),
        {
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "actor_id": request.actor_id,
            "subject_entity_id": str(request.subject_entity_id),
            "statement_id": str(request.statement_id),
            "claim_id": str(request.claim_id),
            "action_id": str(request.action_id),
            "requested_action": request.desired_action.value,
            "outcome_action": outcome.value,
            "allowed": allowed,
            "reason_codes": list(reason_codes),
        },
    )


def _safe_public_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _previewable_media_type(value: str) -> bool:
    media_type = value.lower().split(";", 1)[0].strip()
    return media_type.startswith(("text/", "image/", "audio/", "video/")) or media_type in {
        "application/pdf",
        "application/json",
    }


def _bounded_reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(values))
    return unique[:8] or ("policy_denied",)
