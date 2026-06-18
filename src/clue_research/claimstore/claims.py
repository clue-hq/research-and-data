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
  :func:`clue_research.core.serialize_value_json` / :func:`parse_value_json`, so the typed payload
  has exactly one round-trip path (no JSON codec is reimplemented here).
* **Structural pre-checks before the round-trip.** The evidence-span / weak-binding promotion rule
  (:func:`clue_research.core.can_be_promoted`) is asserted before insert so a caller gets a clear
  error rather than a CHECK violation — and the DB CHECK is still there as the backstop.

M1.4 extends both the ``claim`` table and the INSERT here with the provenance-flavor columns
(``identity_binding``, ``use_class``, ``discovery_provenance``, ``claim_flavor``); M1.1 writes the
``_conventions.md`` §4 base envelope.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore.registry import validate_value
from clue_research.core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    VerificationStatus,
    can_be_promoted,
    parse_value_json,
    serialize_value_json,
)
from clue_research.core.field import FieldKey

_INSERT_SQL = text(
    """
    INSERT INTO claim (
        id, entity_id, entity_type, field_key, value_json, source_url, source_tier,
        extraction_method, evidence_span, confidence, corroborations, observed_at,
        collected_at, cost_cents, run_id, research_mode, superseded_by, verification_status,
        identity_binding, use_class, discovery_provenance, claim_flavor
    ) VALUES (
        :id, :entity_id, CAST(:entity_type AS entity_type), :field_key,
        CAST(:value_json AS jsonb), :source_url, :source_tier,
        CAST(:extraction_method AS extraction_method), :evidence_span,
        :confidence, :corroborations, :observed_at, :collected_at, :cost_cents, :run_id,
        CAST(:research_mode AS research_mode), :superseded_by,
        CAST(:verification_status AS verification_status),
        CAST(:identity_binding AS identity_binding), CAST(:use_class AS use_class),
        CAST(:discovery_provenance AS jsonb), CAST(:claim_flavor AS claim_flavor)
    )
    RETURNING id
    """
)

# Selected columns, in a stable order, for reconstructing a Claim. One list so the reader and any
# future column add stay in one place.
_SELECT_COLUMNS = (
    "id, entity_id, entity_type, field_key, value_json, source_url, source_tier, "
    "extraction_method, evidence_span, confidence, corroborations, observed_at, collected_at, "
    "cost_cents, run_id, research_mode, superseded_by, verification_status, "
    "identity_binding, use_class, discovery_provenance, claim_flavor"
)


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
    }


def _decode_jsonb(raw: object) -> object:
    """Decode a JSONB column value to a Python object.

    SQLAlchemy's asyncpg dialect returns ``jsonb`` *already decoded* (dict / list / str / int / …),
    so the value passes straight through. Only if a driver hands back raw ``bytes`` do we parse it,
    through the one ``core`` round-trip path.
    """
    if isinstance(raw, (bytes, bytearray)):
        return parse_value_json(bytes(raw))
    return raw


def _row_to_claim(row: dict[str, object]) -> Claim:
    """Rebuild a :class:`Claim` from a ``claim`` row mapping.

    Reconstruction re-runs the model validators, so a row that somehow violated an invariant is
    caught on read too (defense in depth).
    """
    value_json = _decode_jsonb(row["value_json"])
    discovery = _decode_jsonb(row.get("discovery_provenance"))
    return Claim.model_validate(
        {
            "id": row["id"],
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "field_key": row["field_key"],
            "value_json": value_json,
            "source_url": row["source_url"],
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
        }
    )


async def insert_claim(
    conn: AsyncConnection, claim: Claim, *, validate_field: bool = True
) -> ClaimId:
    """Insert one claim and return its id (the reference callers pass around).

    Run inside :func:`clue_research.db.transaction` when the write must be atomic with a
    supersession. ``collected_at`` is stamped at :class:`Claim` construction and
    ``verification_status`` defaults to ``unverified`` — both are persisted as-is.

    Two pre-checks run before the round-trip:

    * **payload validation** (when ``validate_field``, the default) — a *field-claim*'s
      ``value_json`` must match the field's ``value_schema`` in the registry (M1.3); an unregistered
      field is rejected. The registry is the single source of valid ``field_key``s (conventions §2).
      *Discovery* claims carry admission evidence, not a typed field value, so they skip this check.
      Pass ``validate_field=False`` for low-level tests that exercise the table directly.
    * **structural promotability** — a ``verified`` claim that is not promotable (tier-4 with no
      span, or a weak-binding contact claim) is refused early with a clear message; the DB CHECK is
      the backstop.
    """
    if validate_field and claim.claim_flavor is not ClaimFlavor.DISCOVERY:
        await validate_value(conn, claim.field_key, claim.value_json)
    if claim.verification_status is VerificationStatus.VERIFIED and not can_be_promoted(claim):
        raise ValueError(
            "cannot insert a 'verified' claim that is not promotable "
            "(tier-4 without evidence_span, or weak-binding contact claim) — substrate §1/§6"
        )
    result = await conn.execute(_INSERT_SQL, _insert_params(claim))
    return ClaimId(result.scalar_one())


async def supersede_claim(conn: AsyncConnection, old_id: ClaimId, new_claim: Claim) -> ClaimId:
    """Supersede ``old_id`` with ``new_claim``: insert the new row, then point the old row's
    ``superseded_by`` at it — atomically (the caller's transaction).

    This is the *only* permitted mutation of an existing claim besides verification-status /
    corroboration transitions: the immutable provenance of ``old_id`` is untouched; it simply gains
    a forward pointer. Append-only history is preserved (substrate §1).
    """
    new_id = await insert_claim(conn, new_claim)
    await conn.execute(
        text("UPDATE claim SET superseded_by = :new_id WHERE id = :old_id"),
        {"new_id": new_id, "old_id": old_id},
    )
    return new_id


async def claims_for(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: FieldKey | str | None = None,
    *,
    include_superseded: bool = False,
) -> Sequence[Claim]:
    """Raw claim history for an entity (audit / time-travel / provenance index).

    Returns the live claims by default (``superseded_by IS NULL``); pass
    ``include_superseded=True`` for the full append-only history. This is the *raw* reader — the
    deterministic "current truth" merge is :func:`clue_research.claimstore.current_value` (M1.2),
    not here.
    """
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE entity_id = :entity_id
          AND (CAST(:field_key AS text) IS NULL OR field_key = :field_key)
          AND (CAST(:include_superseded AS boolean) OR superseded_by IS NULL)
        ORDER BY collected_at DESC, id
        """
    )
    result = await conn.execute(
        stmt,
        {
            "entity_id": entity_id,
            "field_key": field_key,
            "include_superseded": include_superseded,
        },
    )
    return [_row_to_claim(dict(row)) for row in result.mappings().all()]
