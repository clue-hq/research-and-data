"""The claim write/read contract — the only sanctioned path into the substrate (M1.1).

Every resolver (M4), worker (M8), Stage-0 ingest (M5), and tier-4 synthesizer (M11) writes
through :func:`insert_claim` / :func:`supersede_claim` and returns the resulting ``claim_id``
*reference* — never a blob (conventions §2). No caller hand-writes SQL against ``claim``; the
underlying store (Postgres → anything) stays hidden behind these functions.

Design rules realized here (substrate §1, db/README "migration conventions checklist"):

* **Append-only.** A new observation is a new row. Supersession (:func:`supersede_claim`) inserts
  the new row and sets the *prior* row's ``superseded_by`` — the only permitted mutation, done
  atomically inside one transaction. The DB trigger rejects any other UPDATE; there is no in-place
  value mutation anywhere in the write path.
* **One serialization path.** ``value_json`` is (de)serialized with
  :func:`clue_core.serialize_value_json` / :func:`parse_value_json`, so the typed payload
  has exactly one round-trip path (no JSON codec is reimplemented here).
* **Structural pre-checks before the round-trip.** The evidence-span / weak-binding promotion rule
  (:func:`clue_core.can_be_promoted`) is asserted before insert so a caller gets a clear
  error rather than a CHECK violation — and the DB CHECK is still there as the backstop.

M1.4 extends both the ``claim`` table and the INSERT here with the provenance-flavor columns
(``identity_binding``, ``use_class``, ``discovery_provenance``, ``claim_flavor``); M1.1 writes the
``_conventions.md`` §4 base envelope.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    RunId,
    VerificationStatus,
    can_be_promoted,
    decode_jsonb,
    decode_jsonb_scalar,
    serialize_value_json,
)
from clue_core.field import FieldKey
from clue_research.claimstore.registry import check_claim_writable
from clue_research.claimstore.tenancy import WorkspaceScope

_INSERT_SQL = text(
    """
    INSERT INTO claim (
        id, entity_id, entity_type, field_key, value_json, source_url, source_key, artifact_key,
        source_operation_ref, source_snapshot_ref, source_request_ref,
        provenance_kind, source_tier,
        extraction_method, evidence_span, confidence, corroborations, observed_at,
        collected_at, cost_cents, run_id, research_mode, superseded_by, verification_status,
        identity_binding, use_class, discovery_provenance, claim_flavor, reuse_scope, workspace_id,
        product_id, signal_priority, outreach_safe, write_markers
    ) VALUES (
        :id, :entity_id, CAST(:entity_type AS entity_type), :field_key,
        CAST(:value_json AS jsonb), :source_url, :source_key, :artifact_key,
        :source_operation_ref, :source_snapshot_ref, :source_request_ref,
        CAST(:provenance_kind AS claim_provenance_kind), :source_tier,
        CAST(:extraction_method AS extraction_method), :evidence_span,
        :confidence, :corroborations, :observed_at, :collected_at, :cost_cents, :run_id,
        CAST(:research_mode AS research_mode), :superseded_by,
        CAST(:verification_status AS verification_status),
        CAST(:identity_binding AS identity_binding), CAST(:use_class AS use_class),
        CAST(:discovery_provenance AS jsonb), CAST(:claim_flavor AS claim_flavor),
        CAST(:reuse_scope AS reuse_scope), :workspace_id, :product_id,
        :signal_priority, :outreach_safe, CAST(:write_markers AS jsonb)
    )
    RETURNING id
    """
)

# Selected columns, in a stable order, for reconstructing a Claim. One list so the reader and any
# future column add stay in one place.
_SELECT_COLUMNS = (
    "id, entity_id, entity_type, field_key, value_json, source_url, source_key, artifact_key, "
    "source_operation_ref, source_snapshot_ref, source_request_ref, provenance_kind, "
    "source_tier, "
    "extraction_method, evidence_span, confidence, corroborations, observed_at, collected_at, "
    "cost_cents, run_id, research_mode, superseded_by, verification_status, "
    "identity_binding, use_class, discovery_provenance, claim_flavor, reuse_scope, workspace_id, "
    "product_id, signal_priority, outreach_safe, write_markers"
)


def _retention_eligible_sql(*, claim_alias: str = "claim") -> str:
    """SQL predicate for a consumer-visible claim.

    ``lawful_basis_record.retention_until`` is the authoritative retention horizon for personal
    claims.  The M10 sweep still performs the durable supersession-by-tombstone, but readers must
    fail closed during the interval between the horizon passing and that maintenance sweep running.
    Audit/history reads deliberately do not apply this predicate.

    ``claim_alias`` is supplied only by this module and the merge module as a static SQL identifier;
    it is never derived from request input.
    """
    return (
        "NOT EXISTS ("
        "SELECT 1 FROM lawful_basis_record retention "
        f"WHERE retention.claim_id = {claim_alias}.id "
        "AND retention.retention_until IS NOT NULL "
        "AND retention.retention_until <= :retention_at"
        ")"
    )


def _quality_eligible_sql(*, claim_alias: str = "claim") -> str:
    # Lazy import keeps the correction helper and read predicate behind the same substrate seam.
    from clue_research.claimstore.quality import eligible_sql

    return eligible_sql(claim_alias)


def _insert_params(claim: Claim) -> dict[str, object]:
    """Bind parameters for one INSERT, serializing the JSONB payloads through ``core``."""
    discovery = claim.discovery_provenance
    return {
        "id": claim.id,
        "entity_id": claim.entity_id,
        "entity_type": claim.entity_type.value,
        "field_key": claim.field_key,
        "value_json": serialize_value_json(claim.value_json),
        "source_url": claim.source_url,
        "source_key": claim.source_key,
        "artifact_key": claim.artifact_key,
        "source_operation_ref": claim.source_operation_ref,
        "source_snapshot_ref": claim.source_snapshot_ref,
        "source_request_ref": claim.source_request_ref,
        "provenance_kind": claim.provenance_kind.value if claim.provenance_kind else None,
        "source_tier": claim.source_tier,
        "extraction_method": claim.extraction_method.value,
        "evidence_span": claim.evidence_span,
        "confidence": claim.confidence,
        "corroborations": claim.corroborations,
        "observed_at": claim.observed_at,
        "collected_at": claim.collected_at,
        "cost_cents": claim.cost_cents,
        "run_id": claim.run_id,
        "research_mode": claim.research_mode.value,
        "superseded_by": claim.superseded_by,
        "verification_status": claim.verification_status.value,
        "identity_binding": claim.identity_binding.value if claim.identity_binding else None,
        "use_class": claim.use_class.value if claim.use_class else None,
        "discovery_provenance": (
            serialize_value_json(discovery.model_dump(mode="json"))
            if discovery is not None
            else None
        ),
        "claim_flavor": claim.claim_flavor.value,
        "reuse_scope": claim.reuse_scope.value,
        "workspace_id": claim.workspace_id,
        "product_id": claim.product_id,
        "signal_priority": claim.signal_priority,
        "outreach_safe": claim.outreach_safe,
        "write_markers": (
            None if claim.write_markers is None else serialize_value_json(claim.write_markers)
        ),
    }


def _row_to_claim(row: dict[str, object]) -> Claim:
    """Rebuild a :class:`Claim` from a ``claim`` row mapping.

    Reconstruction re-runs the model validators, so a row that somehow violated an invariant is
    caught on read too (defense in depth). ``value_json`` is a bare-scalar column (a decoded ``"x"``
    is the value, not JSON text), so it reads through the bytes-only ``decode_jsonb_scalar``.
    """
    value_json = decode_jsonb_scalar(row["value_json"])
    discovery = decode_jsonb_scalar(row.get("discovery_provenance"))
    return Claim.model_validate(
        {
            "id": row["id"],
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "field_key": row["field_key"],
            "value_json": value_json,
            "source_url": row["source_url"],
            "source_key": row.get("source_key"),
            "artifact_key": row.get("artifact_key"),
            "source_operation_ref": row.get("source_operation_ref"),
            "source_snapshot_ref": row.get("source_snapshot_ref"),
            "source_request_ref": row.get("source_request_ref"),
            "provenance_kind": row.get("provenance_kind"),
            "source_tier": row["source_tier"],
            "extraction_method": row["extraction_method"],
            "evidence_span": row["evidence_span"],
            "confidence": row["confidence"],
            "corroborations": row["corroborations"],
            "observed_at": row["observed_at"],
            "collected_at": row["collected_at"],
            "cost_cents": row["cost_cents"],
            "run_id": row["run_id"],
            "research_mode": row["research_mode"],
            "superseded_by": row["superseded_by"],
            "verification_status": row["verification_status"],
            "identity_binding": row.get("identity_binding"),
            "use_class": row.get("use_class"),
            "claim_flavor": row.get("claim_flavor", ClaimFlavor.FIELD_CLAIM),
            "discovery_provenance": discovery,
            "reuse_scope": row.get("reuse_scope", "public_footprint"),
            "workspace_id": row.get("workspace_id"),
            "product_id": row.get("product_id"),
            "signal_priority": row.get("signal_priority", 3),
            "outreach_safe": row.get("outreach_safe", True),
            "write_markers": decode_jsonb(row.get("write_markers")),
        }
    )


async def insert_claim(
    conn: AsyncConnection, claim: Claim, *, validate_field: bool = True
) -> ClaimId:
    """Insert one claim and return its id (the reference callers pass around).

    Run inside :func:`clue_db.transaction` when the write must be atomic with a
    supersession. ``collected_at`` is stamped at :class:`Claim` construction and
    ``verification_status`` defaults to ``unverified`` — both are persisted as-is.

    Two pre-checks run before the round-trip:

    * **field write check** (when ``validate_field``, the default) — a *field-claim*'s
      ``value_json`` must match the field's ``value_schema`` in the registry (M1.3), the field must
      be registered,
      and its declared/resolved ``reuse_scope`` must be consistent with the claim's (M2.5/ENG-165:
      fail-closed — a ``tenant_private`` field cannot be written with a ``public_footprint`` claim,
      and an undeclared ``<pack>.*`` field cannot be written at all). See
      :func:`~clue_research.claimstore.registry.check_claim_writable`. *Discovery* claims carry
      admission evidence, not a typed field value, so they skip this check. Pass
      ``validate_field=False`` for low-level tests that exercise the table directly.
    * **structural promotability** — a ``verified`` claim that is not promotable (a direct tier-4
      claim with no span, or a weak-binding contact claim) is refused early with a clear message;
      C7 derived claims instead prove support lineage in their deferred DB constraint.
    """
    if validate_field and claim.claim_flavor is not ClaimFlavor.DISCOVERY:
        await check_claim_writable(
            conn,
            field_key=claim.field_key,
            value_json=claim.value_json,
            reuse_scope=claim.reuse_scope,
            workspace_id=claim.workspace_id,
            product_id=claim.product_id,
        )
    if claim.verification_status is VerificationStatus.VERIFIED and not can_be_promoted(claim):
        raise ValueError(
            "cannot insert a 'verified' claim that is not promotable "
            "(direct tier-4 without evidence_span, or weak-binding contact claim, "
            "or a web/synthesis claim with no source_url) — "
            "substrate §1/§6"
        )
    result = await conn.execute(_INSERT_SQL, _insert_params(claim))
    return ClaimId(result.scalar_one())


async def supersede_claim(
    conn: AsyncConnection, old_id: ClaimId, new_claim: Claim, *, validate_field: bool = True
) -> ClaimId:
    """Supersede ``old_id`` with ``new_claim``: insert the new row, then point the old row's
    ``superseded_by`` at it — atomically (the caller's transaction).

    This is the *only* permitted mutation of an existing claim besides verification-status /
    corroboration transitions: the immutable provenance of ``old_id`` is untouched; it simply gains
    a forward pointer. Append-only history is preserved (substrate §1).

    ``validate_field`` is threaded to :func:`insert_claim`. It defaults ``True`` (the field-write
    check runs); sanctioned ``False`` callers are compliance-owned redaction/tombstone paths,
    including M10.5 DSAR and exact-source erasure. Their ``new_claim`` carries a deliberately
    *redacted* ``value_json`` (a redaction sentinel, not a real field value) that must bypass the
    registry ``value_schema`` check — the tombstone is written ``REJECTED`` so it can never win the
    merge regardless (substrate §6 / Doc D §4).
    """
    new_id = await insert_claim(conn, new_claim, validate_field=validate_field)
    await conn.execute(
        text("UPDATE claim SET superseded_by = :new_id WHERE id = :old_id"),
        {"new_id": new_id, "old_id": old_id},
    )
    return new_id


async def supersede_claims(
    conn: AsyncConnection,
    old_ids: Sequence[ClaimId],
    new_claim: Claim,
    *,
    validate_field: bool = True,
) -> ClaimId:
    """Supersede *every* claim in ``old_ids`` with a single ``new_claim`` — the many→one analogue of
    :func:`supersede_claim`: insert the new row once, then point each old row's ``superseded_by`` at
    it (the trigger-allowlisted forward pointer), atomically in the caller's transaction.

    For a re-resolution that collapses several live claims into one current value — e.g. M10.1
    re-resolving a contact's jurisdiction must retire *all* live ``contact.jurisdiction`` claims,
    not just the newest, so a stray/concurrent live sibling cannot keep contributing to
    ``current_value``. The immutable provenance of each old row is untouched; append-only history
    is preserved (substrate §1). ``old_ids`` may be empty — then it is exactly :func:`insert_claim`.

    ``validate_field`` is threaded to :func:`insert_claim` (default ``True``); see
    :func:`supersede_claim` for sanctioned compliance redaction/tombstone callers.
    """
    new_id = await insert_claim(conn, new_claim, validate_field=validate_field)
    ids = list(old_ids)
    if ids:
        stmt = text(
            "UPDATE claim SET superseded_by = :new_id "
            "WHERE id IN :old_ids AND superseded_by IS NULL"
        ).bindparams(bindparam("old_ids", expanding=True))
        await conn.execute(stmt, {"new_id": new_id, "old_ids": ids})
    return new_id


async def supersede_with_existing(
    conn: AsyncConnection,
    old_id: ClaimId,
    replacement_id: ClaimId,
    *,
    workspace_id: str,
    entity_id: EntityId,
) -> None:
    """Link an existing validated replacement while preserving both observations.

    This is the shared correction seam for callers that already wrote/reused an evidence-backed
    replacement. Locks and exact subject/field checks prevent cross-entity or stale replacement.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id,field_key,superseded_by FROM claim WHERE id=ANY(:ids) "
                    "AND workspace_id=:ws AND entity_id=:entity ORDER BY id FOR UPDATE"
                ),
                {"ids": sorted({old_id, replacement_id}), "ws": workspace_id, "entity": entity_id},
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != 2 or len({r["field_key"] for r in rows}) != 1:
        raise ValueError("supersession requires distinct claims on the same subject and field")
    if any(r["superseded_by"] is not None for r in rows):
        raise ValueError("supersession requires two live claims")
    await conn.execute(
        text("UPDATE claim SET superseded_by=:new WHERE id=:old"),
        {"new": replacement_id, "old": old_id},
    )


async def record_verification(
    conn: AsyncConnection,
    claim_id: ClaimId,
    *,
    status: VerificationStatus,
    corroborations: int | None = None,
) -> None:
    """Apply a verification verdict to an existing claim *in place* — the only mutation of a stored
    claim besides supersession.

    ``verification_status`` and ``corroborations`` are the trigger-allowlisted mutable columns
    (migrations 0002/0004/0008); every other provenance column (value, source, span, tier, …) stays
    immutable and the BEFORE-UPDATE trigger rejects any change to it. M9's verification layers write
    their verdict through this one helper so no caller hand-writes SQL against ``claim`` (substrate
    §1): the corroborator (M9.2) sets both ``status`` and ``corroborations``; the faithfulness judge
    (M9.3) and identity-binding gate (M9.4) set ``status`` alone (``corroborations`` omitted → left
    untouched). The ``claim_tier4_verified_requires_span`` CHECK (0002) stays the DB backstop, so a
    span-less tier-4 claim can never be flipped to ``verified`` even through this path.
    """
    if corroborations is None:
        await conn.execute(
            text(
                "UPDATE claim SET verification_status = CAST(:status AS verification_status) "
                "WHERE id = :id"
            ),
            {"status": status.value, "id": claim_id},
        )
    else:
        await conn.execute(
            text(
                "UPDATE claim SET verification_status = CAST(:status AS verification_status), "
                "corroborations = :corroborations WHERE id = :id"
            ),
            {"status": status.value, "corroborations": corroborations, "id": claim_id},
        )


async def claims_for(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: FieldKey | str | None = None,
    *,
    include_superseded: bool = False,
    scope: WorkspaceScope,
) -> Sequence[Claim]:
    """Raw claim history for an entity (audit / time-travel / provenance index).

    Returns the live claims by default (``superseded_by IS NULL``); pass
    ``include_superseded=True`` for the full append-only history, including invalid/unresolved
    observations. Ordinary reads honor recorded quality decisions. The
    deterministic "current truth" merge is :func:`clue_research.claimstore.current_value` (M1.2),
    not here. ``scope`` is **required** (M2.5 — fail-closed): there is no fail-open default, so no
    read path can accidentally cross tenants. An operator/audit caller passes
    :data:`ALL_WORKSPACES` explicitly; a tenant-facing caller passes its own scope.
    """
    scope_sql, scope_params = scope.predicate()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE entity_id = :entity_id
          AND (CAST(:field_key AS text) IS NULL OR field_key = :field_key)
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
          AND (CAST(:include_superseded AS boolean) OR {_quality_eligible_sql()})
          AND {scope_sql}
        ORDER BY collected_at DESC, id
        """
    )
    result = await conn.execute(
        stmt,
        {
            "entity_id": entity_id,
            "field_key": field_key,
            "include_superseded": include_superseded,
            **scope_params,
        },
    )
    return [_row_to_claim(dict(row)) for row in result.mappings().all()]


async def claims_for_entities(
    conn: AsyncConnection,
    entity_ids: Sequence[EntityId],
    field_keys: Sequence[FieldKey | str] | None = None,
    *,
    include_superseded: bool = False,
    scope: WorkspaceScope,
) -> Sequence[Claim]:
    """Batch sibling of :func:`claims_for`, retention-safe for live projection reads."""

    entities = tuple(dict.fromkeys(entity_ids))
    fields = tuple(dict.fromkeys(str(value) for value in (field_keys or ())))
    if not entities:
        return ()
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    field_clause = "AND field_key IN :field_keys" if fields else ""
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE entity_id IN :entity_ids
          {field_clause}
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
          AND (CAST(:include_superseded AS boolean) OR {_quality_eligible_sql()})
          AND (CAST(:include_superseded AS boolean) OR {retention_sql})
          AND {scope_sql}
        ORDER BY field_key, collected_at DESC, id
        """
    ).bindparams(
        bindparam("entity_ids", expanding=True),
        *((bindparam("field_keys", expanding=True),) if fields else ()),
    )
    params: dict[str, object] = {
        "entity_ids": list(entities),
        "include_superseded": include_superseded,
        "retention_at": datetime.now(UTC),
        **scope_params,
    }
    if fields:
        params["field_keys"] = list(fields)
    rows = (await conn.execute(stmt, params)).mappings()
    return tuple(_row_to_claim(dict(row)) for row in rows)


async def claims_by_ids(
    conn: AsyncConnection,
    claim_ids: Iterable[ClaimId],
    *,
    scope: WorkspaceScope,
    include_superseded: bool = False,
    include_expired: bool | None = None,
) -> dict[ClaimId, Claim]:
    """Resolve a set of ``claim_id``s to their :class:`Claim` rows in one query — the batch reader
    the M12.2 handoff ``provenance_index`` needs (it collects every claim id appearing anywhere in
    the assembled object — score-component evidence, profile claims, committee claims, narrative
    claims + their two-sided support — and resolves them to their source provenance in one round
    trip).

    Live and retention-eligible by default — the handoff's "every value points at a real,
    *non-superseded*, non-expired claim" invariant. A recorded retention horizon is enforced at
    read time even if the maintenance sweep has not tombstoned the claim yet. Pass
    ``include_superseded=True`` for audit/history, which also includes retention-expired rows by
    default. A bounded historical consumer that must preserve superseded provenance without
    reviving retention-expired personal data may pass ``include_expired=False`` explicitly.
    ``include_expired=True`` is rejected unless superseded history was also requested: there is no
    coherent consumer contract for current-only rows that bypasses retention.
    ``scope`` is **required** (M2.5, fail-closed), like :func:`claims_for`. A requested id
    **absent** from the returned map (unknown, superseded, expired, or out of scope) lets the caller
    detect a dangling reference and fail the build rather than silently drop it.
    """
    if include_expired is None:
        include_expired = include_superseded
    if include_expired and not include_superseded:
        raise ValueError("retention-expired claims require include_superseded=True")
    ids = [str(cid) for cid in claim_ids]
    if not ids:
        return {}
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE id IN :ids
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
          AND (CAST(:include_superseded AS boolean) OR {_quality_eligible_sql()})
          AND (CAST(:include_expired AS boolean) OR {retention_sql})
          AND {scope_sql}
        """
    ).bindparams(bindparam("ids", expanding=True))
    result = await conn.execute(
        stmt,
        {
            "ids": ids,
            "include_superseded": include_superseded,
            "include_expired": include_expired,
            "retention_at": datetime.now(UTC),
            **scope_params,
        },
    )
    out: dict[ClaimId, Claim] = {}
    for row in result.mappings().all():
        claim = _row_to_claim(dict(row))
        out[claim.id] = claim
    return out


async def entities_with_field_claim(
    conn: AsyncConnection,
    field_key: FieldKey | str,
    *,
    run_id: RunId | None = None,
    include_superseded: bool = False,
    scope: WorkspaceScope,
) -> list[EntityId]:
    """The distinct ``entity_id``s carrying a (live) claim on ``field_key`` — optionally narrowed to
    one ``run_id``.

    The set-shaped read the membership queries need (e.g. M6.3 enumerating the accounts admitted in
    a discovery run via ``core.discovery_provenance`` + that run's id, M6.5 the admitted-vs-seen
    counts) without anyone hand-writing SQL against ``claim`` (conventions §2 — the table stays
    behind this seam). ``scope`` is **required** (M2.5, fail-closed), like :func:`claims_for`; an
    operator/cross-tenant caller passes :data:`ALL_WORKSPACES`. Returns the surviving-or-not ids as
    stored — a caller that needs the merge survivor resolves each through ``identity.surviving_id``.
    Ordered by id for a deterministic result.
    """
    scope_sql, scope_params = scope.predicate()
    stmt = text(
        f"""
        SELECT DISTINCT entity_id
        FROM claim
        WHERE field_key = :field_key
          AND (CAST(:run_id AS uuid) IS NULL OR run_id = :run_id)
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
          AND (CAST(:include_superseded AS boolean) OR {_quality_eligible_sql()})
          AND {scope_sql}
        ORDER BY entity_id
        """
    )
    result = await conn.execute(
        stmt,
        {
            "field_key": field_key,
            "run_id": run_id,
            "include_superseded": include_superseded,
            **scope_params,
        },
    )
    return [EntityId(row[0]) for row in result.all()]


async def claims_for_runs(
    conn: AsyncConnection,
    run_ids: Iterable[RunId],
    *,
    scope: WorkspaceScope,
    include_superseded: bool = False,
) -> Sequence[Claim]:
    """All (live) claims written under a set of account ``run_id``s — the campaign-scoped scan.

    Every worker of an account run stamps its ``run_id`` on each claim it writes
    (``account_run.id`` == ``claim.run_id``), so the union of claims over a campaign's account
    ``run_id``s is exactly that campaign's deep-produced claims (account *and* contact). The M13.4
    observability surface uses this for the at-rest verification-health scan (tier-4 faithfulness,
    strong identity-binding share, corroboration) over one project run — the set-shaped sibling of
    :func:`entities_with_field_claim` and :func:`claims_by_ids`, so no caller hand-writes SQL
    against
    ``claim`` (conventions §2 — the table stays behind this seam).

    Live (``superseded_by IS NULL``) by default; ``scope`` is **required** (M2.5, fail-closed). An
    empty ``run_ids`` returns ``[]`` without a query. Ordered by ``(run_id, collected_at DESC, id)``
    for a deterministic result.
    """
    ids = [str(rid) for rid in run_ids]
    if not ids:
        return []
    scope_sql, scope_params = scope.predicate()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE run_id IN :run_ids
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
          AND (CAST(:include_superseded AS boolean) OR {_quality_eligible_sql()})
          AND {scope_sql}
        ORDER BY run_id, collected_at DESC, id
        """
    ).bindparams(bindparam("run_ids", expanding=True))
    result = await conn.execute(
        stmt, {"run_ids": ids, "include_superseded": include_superseded, **scope_params}
    )
    return [_row_to_claim(dict(row)) for row in result.mappings().all()]
