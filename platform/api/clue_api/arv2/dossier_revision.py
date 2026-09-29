"""Atomic revisions of an imported dossier, using existing claim-store history/events."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.dossier_import import import_research_dossier
from clue_api.arv2.dossier_json import parse_json_dossier
from clue_core import ClaimId, EntityId
from clue_obs import get_logger
from clue_research.claimstore.claims import supersede_with_existing
from clue_research.claimstore.quality import assess_claim
from clue_storage import StorageBackend

log = get_logger("arv2.dossier_revision")


async def claim_versions(
    conn: AsyncConnection,
    scope: JobScope,
    context_id: UUID,
    entries: Iterable[dict[str, Any]],
) -> dict[str, int]:
    ids = sorted(UUID(e["claim_id"]) for e in entries)
    rows = (
        (
            await conn.execute(
                text("""SELECT c.id, c.superseded_by, q.revision
        FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
        JOIN arv2_quality_proposal p ON p.claim_id=c.id
        WHERE c.id=ANY(:ids) AND c.workspace_id=:ws AND c.entity_id=:subject
        AND q.context_id=:context AND p.job_id=:job ORDER BY c.id FOR UPDATE OF c"""),
                {
                    "ids": ids,
                    "ws": scope.workspace_id,
                    "subject": scope.person_subject_id or scope.account_id,
                    "context": context_id,
                    "job": scope.job_id,
                },
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(ids) or any(r["superseded_by"] for r in rows):
        raise ValueError("Dossier baseline contains unavailable or already replaced claims")
    return {str(r["id"]): r["revision"] for r in rows}


def revision_plan(saved: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """Propagate changed targets through references, including reciprocal conflicts."""
    revision = saved["revision"]
    base = parse_json_dossier(json.dumps(revision["base_document"]).encode())
    current = parse_json_dossier(json.dumps(saved["document"]).encode())
    originals = {r.entry.id: r for r in base.records}
    receipts = {e["id"]: e for e in revision["base_receipt"]["entries"]}
    current_ids = {r.entry.id for r in current.records}
    removed = originals.keys() - current_ids
    withdrawals = revision["withdrawals"]
    if removed != withdrawals.keys():
        raise ValueError(
            "Removed findings must exactly match the explicit withdrawals; "
            "restore omitted entries or start a revision with withdrawal reasons"
        )
    reusable: dict[str, Any] = {}
    for record in current.records:
        old = originals.get(record.entry.id)
        if old and old.original == record.original and old.section == record.section:
            reusable[record.entry.id] = receipts[record.entry.id]
    while True:
        invalid = [
            r.entry.id
            for r in current.records
            if r.entry.id in reusable and not r.entry.dependencies() <= reusable.keys()
        ]
        if not invalid:
            break
        for identifier in invalid:
            del reusable[identifier]
    return reusable, receipts, removed


class RevisionImportFailed(ValueError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("Revision not applied; prior claims remain current")
        self.errors = errors


async def import_revision(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    authority: Any,
    saved: dict[str, Any],
    aliases: dict[str, UUID],
    body: bytes,
    digest: str,
    import_id: UUID,
) -> dict[str, Any]:
    revision = saved["revision"]
    reusable, baseline, _ = revision_plan(saved)
    try:
        # A revision is one replacement, not a series of partially published corrections.
        async with conn.begin_nested():
            versions = await claim_versions(conn, scope, authority.context_id, baseline.values())
            if versions != revision["claim_revisions"]:
                raise ValueError(
                    "Baseline claims changed since revision began; do not overwrite them"
                )
            receipt = await import_research_dossier(
                conn,
                storage,
                scope,
                authority.grant,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                import_id=import_id,
                body=body,
                expected_sha256=digest,
                source_aliases=aliases,
                reuse_entries=reusable,
            )
            if not receipt["complete"]:
                raise RevisionImportFailed(receipt["errors"])
            new_ids = {e["id"]: str(e["claim_id"]) for e in receipt["entries"]}
            changes = []
            for fid in sorted(baseline.keys() - reusable.keys()):
                old_id = UUID(baseline[fid]["claim_id"])
                new_id = UUID(new_ids[fid]) if fid in new_ids else None
                # A replaced draft may intentionally be uncertain or wrong-entity. Retire
                # the earlier version without falsely promoting the replacement to supported.
                await assess_claim(
                    conn,
                    workspace_id=scope.workspace_id,
                    entity_id=scope.person_subject_id or scope.account_id,
                    claim_id=old_id,
                    operation_id=uuid5(NAMESPACE_URL, f"dossier-revision:{import_id}:{fid}"),
                    expected_revision=versions[str(old_id)],
                    conclusion="invalid",
                    rationale_key=saved["artifact_key"],
                    actor_ref=authority.actor_ref,
                    support_artifacts=(),
                    context_id=authority.context_id,
                    kind="withdrawal",
                )
                if new_id:
                    await supersede_with_existing(
                        conn,
                        ClaimId(old_id),
                        ClaimId(new_id),
                        workspace_id=scope.workspace_id,
                        entity_id=EntityId(scope.person_subject_id or scope.account_id),
                    )
                changes.append(
                    {
                        "id": fid,
                        "previous_claim_id": str(old_id),
                        "claim_id": str(new_id) if new_id else None,
                        "action": "replaced" if new_id else "withdrawn",
                        "reason": revision["withdrawals"].get(fid, revision["reason"]),
                    }
                )
            receipt["changes"] = changes
            receipt["reused"] = len(reusable)
            receipt["added"] = len(new_ids.keys() - baseline.keys())
    except Exception as exc:
        log.warning(
            "arv2.dossier.revision_not_applied",
            job_id=str(scope.job_id),
            import_id=str(import_id),
            error_type=type(exc).__name__,
        )
        return {
            "complete": False,
            "entries": [],
            "stored": 0,
            "errors": getattr(exc, "errors", [{"error": str(exc)}]),
            "atomic_rollback": True,
        }
    log.info(
        "arv2.dossier.revision_applied",
        job_id=str(scope.job_id),
        import_id=str(import_id),
        reused=receipt["reused"],
        added=receipt["added"],
        replaced_or_withdrawn=len(changes),
    )
    return receipt
