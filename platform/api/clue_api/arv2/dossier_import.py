"""Deterministic research JSON -> shared claim store; no acquisition or model calls.

The caller supplies an immutable dossier, a run-bound grant and an import ID. It
owns the outer transaction. Each reference component uses a savepoint so one failed write does
not erase independent findings. Retrying the same import reuses durable receipts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.dossier_findings import Finding, assessment_for
from clue_api.arv2.dossier_json import DossierRecord, import_groups, parse_json_dossier
from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.import_storage import ImportStorage
from clue_api.arv2.quality_claims import FindingProposal, SourceSupport, submit_proposal
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    SourceRef,
    authorize_grant,
    resolve_source,
)
from clue_api.arv2.quality_policy import advisory_research
from clue_core import IdentityBinding, UseClass
from clue_core.equality import canonical_json
from clue_obs import critical_section, get_logger, observation
from clue_storage import StorageBackend

log = get_logger("arv2.dossier_import")


def finding_proposal(
    finding: Finding,
    refs: list[SourceRef],
    *,
    origin: dict[str, Any] | None,
    operation_key: str | None = None,
    key_prefix: str = "",
    subject_kind: Literal["account", "person"] = "account",
) -> FindingProposal:
    """Keep the trial and reusable importer on one lossless payload mapping."""
    payload = finding.model_dump(mode="json", exclude={"source_paths"})
    if origin is not None:
        payload["dossier_entry"] = origin
    payload["sources"] = [
        {
            "source_id": str(r.source_id),
            "path": source_path(r.model_dump()),
            "url": r.source_url,
            "kind": r.kind,
            "locator": r.origin_locator,
        }
        for r in refs
    ]
    # Preserve the existing writer's payload order for historical trial replay.
    # The new importer pins exact JSON bytes, so retries use the same object order.
    return FindingProposal(
        operation_key=operation_key
        or key_prefix + hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
        field_key=("contact" if subject_kind == "person" else "account") + ".research_finding",
        value=payload,
        claim_kind="attributed_statement"
        if finding.claim_type == "reported_statement"
        else "observation",
        support=tuple(SourceSupport(source_id=r.source_id) for r in refs),
        assessment=assessment_for(finding),
        identity_binding=IdentityBinding.WEAK if subject_kind == "person" else None,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE if subject_kind == "person" else None,
        outreach_safe=False,
    )


async def _import_research_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    grant: EvidenceGrant,
    *,
    context_id: UUID,
    actor_ref: str,
    import_id: UUID,
    body: bytes,
    expected_sha256: str,
    source_aliases: Mapping[str, UUID] | None = None,
    reuse_entries: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Import a frozen JSON snapshot and return one outcome per attempted finding.

    Aliases are for relocated trial sources; production paths resolve directly
    against the evidence grant. Alias targets undergo that same authorization.
    Duplicate/conflict labels are retained, not deduplicated or reconciled here.
    Subject comes from the bound job, never from model-authored JSON. Person
    imports retain public material without certifying identity or outreach use.
    This seam intentionally does not alter fleet/runtime selection.
    """
    if not advisory_research(scope):
        raise ValueError("Dossier import requires an advisory research scope")
    subject = scope.person_subject_id or scope.account_id
    if (
        grant.scope.workspace_id,
        grant.scope.run_id,
        grant.scope.job_id,
        grant.scope.account_id,
    ) != (scope.workspace_id, scope.run_id, scope.job_id, scope.account_id):
        raise ValueError("Dossier grant does not belong to this research job")
    if hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError("Frozen JSON dossier differs from the generation receipt")
    await authorize_grant(conn, grant)
    pinned = (
        await conn.execute(
            text(
                "SELECT context_id FROM arv2_research_run WHERE run_id=:run "
                "AND workspace_id=:ws AND project_id=:project"
            ),
            {"run": scope.run_id, "ws": scope.workspace_id, "project": scope.project_id},
        )
    ).scalar_one_or_none()
    if pinned != context_id:
        raise ValueError("Dossier requires the exact pinned research context")
    stored_subject = (
        await conn.execute(
            text(
                "SELECT COALESCE(subject_entity_id,account_entity_id) FROM arv2_research_job "
                "WHERE job_id=:job AND run_id=:run AND workspace_id=:ws"
            ),
            {"job": scope.job_id, "run": scope.run_id, "ws": scope.workspace_id},
        )
    ).scalar_one_or_none()
    if stored_subject != subject:
        raise ValueError("Dossier subject does not match the bound research job")
    parsed = parse_json_dossier(body)
    result: dict[str, Any] = {
        "import_id": str(import_id),
        "dossier_sha256": parsed.sha256,
        "findings_received": parsed.finding_count,
        "sections_received": parsed.section_count,
        "entries": [],
        "errors": list(parsed.errors),
        "stored": 0,
        "roundtrip_checks": [],
    }
    trace = {
        "workspace_id": scope.workspace_id,
        "run_id": str(scope.run_id),
        "job_id": str(scope.job_id),
        "account_id": str(scope.account_id),
        "subject_id": str(subject),
        "subject_kind": scope.subject_kind,
        "import_id": str(import_id),
        "dossier_sha256": parsed.sha256,
    }
    with observation(name="arv2.dossier.import", metadata=trace):
        log.info("arv2.dossier.import_started", **trace, finding_count=parsed.finding_count)
        # Serialize competing retries for this job/import before inspecting prior
        # claims. No long-running provider work occurs under this transaction.
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"dossier-import:{scope.job_id}:{import_id}"},
        )
        prior = (
            (
                await conn.execute(
                    text(
                        "SELECT c.id, c.value_json FROM arv2_quality_proposal p "
                        "JOIN claim c ON c.id=p.claim_id "
                        "WHERE p.workspace_id=:ws AND p.job_id=:job AND p.subject_id=:entity "
                        "AND c.value_json->'dossier_entry'->>'import_id'=:import"
                    ),
                    {
                        "ws": scope.workspace_id,
                        "job": scope.job_id,
                        "entity": subject,
                        "import": str(import_id),
                    },
                )
            )
            .mappings()
            .all()
        )
        if any(
            row["value_json"]["dossier_entry"]["dossier_sha256"] != parsed.sha256 for row in prior
        ):
            raise ValueError("Import ID already bound to different JSON; no implicit correction")
        prior_ids = {row["value_json"]["dossier_entry"]["id"]: str(row["id"]) for row in prior}
        allocated = {
            r.entry.id: str(
                (reuse_entries or {}).get(r.entry.id, {}).get("claim_id")
                or prior_ids.get(r.entry.id)
                or uuid5(
                    NAMESPACE_URL,
                    f"dossier-claim:{scope.workspace_id}:{scope.job_id}:{import_id}:{r.entry.id}",
                )
            )
            for r in parsed.records
        }
        mapping: dict[str, str] = {}
        for group in import_groups(parsed.records):
            members = {r.entry.id for r in group}
            dependencies = set().union(*(r.entry.dependencies() for r in group)) - members
            if dependencies - mapping.keys():
                result["errors"].extend(
                    {
                        "id": r.entry.id,
                        "location": r.location,
                        "error": "Referenced finding was not stored; retry after repair",
                    }
                    for r in group
                )
                continue
            staged_mapping: dict[str, str] = {}
            staged_entries: list[dict[str, Any]] = []
            staged_checks: list[dict[str, Any]] = []
            try:
                async with conn.begin_nested():
                    for record in group:
                        entry = record.entry
                        finding = entry.as_finding(allocated)
                        refs_by_id: dict[UUID, SourceRef] = {}
                        for path in entry.source_paths:
                            if source_aliases is not None and path not in source_aliases:
                                raise ValueError("Unknown source path in supplied source inventory")
                            ref = await resolve_source(
                                conn,
                                grant,
                                source_aliases[path] if source_aliases is not None else path,
                            )
                            refs_by_id[ref.source_id] = ref
                        refs = [refs_by_id[key] for key in sorted(refs_by_id)]
                        reuse = (reuse_entries or {}).get(entry.id)
                        if reuse is not None:
                            prior_value = (
                                await conn.execute(
                                    text("""SELECT c.value_json
                                FROM claim c JOIN arv2_quality_proposal p ON p.claim_id=c.id
                                JOIN claim_quality_current q ON q.claim_id=c.id
                                WHERE c.id=:id AND c.workspace_id=:ws AND c.entity_id=:entity
                                AND p.job_id=:job AND q.context_id=:context
                                AND c.superseded_by IS NULL"""),
                                    {
                                        "id": UUID(reuse["claim_id"]),
                                        "ws": scope.workspace_id,
                                        "entity": subject,
                                        "job": scope.job_id,
                                        "context": context_id,
                                    },
                                )
                            ).scalar_one_or_none()
                            if (
                                prior_value is None
                                or prior_value.get("dossier_entry", {}).get("original")
                                != record.original
                                or prior_value["dossier_entry"]["section"] != record.section
                            ):
                                raise ValueError(
                                    "Reusable finding differs from its stored original"
                                )
                            expected = finding_proposal(
                                finding,
                                refs,
                                origin=prior_value["dossier_entry"],
                                operation_key=f"dossier:{import_id}:{entry.id}",
                                subject_kind=scope.subject_kind,
                            )
                            if expected.value != prior_value:
                                raise ValueError(
                                    "Reusable finding has changed evidence or related claims"
                                )
                            staged_mapping[entry.id] = reuse["claim_id"]
                            staged_entries.append(
                                {**reuse, "location": record.location, "reused": True}
                            )
                            continue
                        origin = {
                            "id": entry.id,
                            "section": record.section,
                            "location": record.location,
                            "import_id": str(import_id),
                            "dossier_sha256": parsed.sha256,
                            "entry_sha256": hashlib.sha256(
                                canonical_json(record.original).encode()
                            ).hexdigest(),
                            "original": record.original,
                        }
                        proposal = finding_proposal(
                            finding,
                            refs,
                            origin=origin,
                            operation_key=f"dossier:{import_id}:{entry.id}",
                            subject_kind=scope.subject_kind,
                        )
                        receipt = await submit_proposal(
                            conn,
                            storage,
                            scope,
                            grant,
                            proposal,
                            context_id=context_id,
                            actor_ref=actor_ref,
                            purge_unevidenced=False,
                            claim_id=UUID(allocated[entry.id]),
                        )
                        if receipt.claim_id is None or receipt.error_code:
                            raise ValueError(
                                f"Claim write refused: {receipt.error_code or receipt.status}"
                            )
                        stored = (
                            await conn.execute(
                                text(
                                    "SELECT value_json FROM claim WHERE id=:id "
                                    "AND workspace_id=:ws AND entity_id=:entity"
                                ),
                                {
                                    "id": receipt.claim_id,
                                    "ws": scope.workspace_id,
                                    "entity": subject,
                                },
                            )
                        ).scalar_one()
                        if stored != proposal.value:
                            raise ValueError(
                                "Claim-store readback differs from the submitted finding"
                            )

                        staged_mapping[entry.id] = str(receipt.claim_id)
                        staged_entries.append(
                            {
                                "id": entry.id,
                                "section": record.section,
                                "location": record.location,
                                **asdict(receipt),
                            }
                        )
                        staged_checks.append(
                            {
                                "id": entry.id,
                                "claim_id": str(receipt.claim_id),
                                "content_and_metadata_equal": True,
                                "source_ids_equal": True,
                                "section_equal": True,
                            }
                        )

                mapping.update(staged_mapping)
                result["entries"].extend(staged_entries)
                result["roundtrip_checks"].extend(staged_checks)
                for entry_receipt in staged_entries:
                    log.info(
                        "arv2.dossier.finding_imported",
                        **trace,
                        finding_id=entry_receipt["id"],
                        claim_id=str(entry_receipt["claim_id"]),
                        replayed=entry_receipt.get("replayed", False),
                        reused=entry_receipt.get("reused", False),
                    )
            except Exception as exc:
                # Roll back mutually dependent findings together. Independent
                # components remain usable, and cancellation still propagates.
                result["errors"].extend(
                    {
                        "id": r.entry.id,
                        "location": r.location,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    }
                    for r in group
                )
                log.warning(
                    "arv2.dossier.finding_import_failed",
                    **trace,
                    finding_ids=sorted(members),
                    error_type=type(exc).__name__,
                )
        result["stored"] = len(mapping)
        result["complete"] = not result["errors"] and len(mapping) == parsed.finding_count
        log.info(
            "arv2.dossier.import_completed",
            **trace,
            stored=len(mapping),
            error_count=len(result["errors"]),
            complete=result["complete"],
        )
    return result


# Preserve the existing account caller while sharing one implementation with
# person replay. Scope and bound job determine the entity, not this historical name.
async def import_read_keys(
    conn: AsyncConnection,
    grant: EvidenceGrant,
    *,
    scope: JobScope,
    context_id: UUID,
    records: Sequence[DossierRecord],
    source_aliases: Mapping[str, UUID] | None,
) -> set[str]:
    """Every storage key the import will read: the context manifest and each cited source's
    artifact and original. Resolved exactly as the import resolves them; unresolvable paths are
    skipped here and refused by the import itself."""
    keys: set[str] = set()
    manifest = (
        await conn.execute(
            text(
                "SELECT manifest_key FROM arv2_research_context_pin "
                "WHERE context_id=:id AND workspace_id=:ws"
            ),
            {"id": context_id, "ws": scope.workspace_id},
        )
    ).scalar_one_or_none()
    if manifest:
        keys.add(manifest)
    paths = {path for record in records for path in record.entry.source_paths}
    for path in sorted(paths):
        reference = source_aliases.get(path) if source_aliases is not None else path
        if reference is None:
            continue
        try:
            ref = await resolve_source(conn, grant, reference)
        except EvidenceUnavailable:
            continue
        keys.add(ref.artifact_key)
        if ref.original_key:
            keys.add(ref.original_key)
    return keys


async def import_research_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    grant: EvidenceGrant,
    *,
    context_id: UUID,
    actor_ref: str,
    import_id: UUID,
    body: bytes,
    expected_sha256: str,
    source_aliases: Mapping[str, UUID] | None = None,
    reuse_entries: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Import a dossier with prefetched reads and concurrent uploads (research slowness fix
    2026-10-03, spec part 3b). The work itself is :func:`_import_research_dossier`, unchanged;
    only where its bytes come from and when they leave differ."""
    staged = ImportStorage(storage)
    with critical_section("arv2.dossier.import", job_id=str(scope.job_id)):
        try:
            records: Sequence[DossierRecord] = parse_json_dossier(body).records
        except Exception:  # noqa: BLE001 — the import itself raises the proper error below
            records = ()
        await staged.prefetch(
            await import_read_keys(
                conn,
                grant,
                scope=scope,
                context_id=context_id,
                records=records,
                source_aliases=source_aliases,
            )
        )
        result = await _import_research_dossier(
            conn,
            staged,
            scope,
            grant,
            context_id=context_id,
            actor_ref=actor_ref,
            import_id=import_id,
            body=body,
            expected_sha256=expected_sha256,
            source_aliases=source_aliases,
            reuse_entries=reuse_entries,
        )
        await staged.flush()
    return result


import_account_dossier = import_research_dossier
