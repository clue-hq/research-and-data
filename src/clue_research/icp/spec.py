"""The versioned ICP spec data model (M3.1 / ENG-104).

Durable, append-only storage for the ``ICPSpec`` contract (``clue_core.ICPSpec``;
conventions §4) — the single object M3.2 / M3.4 read and M5 writes, keyed
``(client_id, icp_key, version)``. This module is storage + versioning + reference validation ONLY:
no resolver, source, or LLM dependency (it sits cleanly below M4). It validates the *active field
set* against the M1.3 registry and the *enabled packs* against the M3.3 catalog at write; the
discovery-strategy / source-profile / scoring-rubric slots are stored opaquely (their internals are
owned by M6 / M4 / M3.4).

Versioning discipline (the same the claim store uses in M1): an ``active`` spec is immutable; an
edit appends a new ``version`` (``parent_version`` links the lineage); activating a version archives
the prior atomically (never deletes). A pinned ``(client_id, icp_key, version)`` re-reads
identically, so a campaign run (M7) is reproducible. ``icp_key`` distinguishes segments per client.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ICPCreatedFrom,
    ICPSpec,
    ICPStatus,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.claimstore import get_field
from clue_research.icp.catalog import get_pack


class ICPSpecValidationError(ValueError):
    """Raised at write when a spec references a ``field_key`` absent from the M1.3 registry or a
    pack absent from the M3.3 catalog (names the offender)."""


class UnknownICPSpecError(ValueError):
    """Raised when an addressed ``(client_id, icp_key, version)`` does not exist."""


class ICPSpecDiff(BaseModel):
    """The structural difference between two ICP-spec versions (``diff_icp``)."""

    model_config = ConfigDict(frozen=True)

    added_field_keys: tuple[str, ...] = ()
    removed_field_keys: tuple[str, ...] = ()
    added_packs: tuple[str, ...] = ()
    removed_packs: tuple[str, ...] = ()
    discovery_strategy_changed: bool = False
    source_profile_changed: bool = False
    scoring_rubric_changed: bool = False


# --- reference validation (consumes M1.3 registry + M3.3 catalog) -----------
async def validate_icp_references(
    conn: AsyncConnection,
    field_keys: Sequence[str],
    enabled_packs: Sequence[str],
) -> None:
    """Reject (naming the offender) any ``field_key`` not registered in M1.3 or pack absent from the
    M3.3 catalog. The only thing the data model knows of its neighbours — it reads, never calls."""
    missing_fields = [fk for fk in field_keys if await get_field(conn, fk) is None]
    if missing_fields:
        raise ICPSpecValidationError(
            f"ICP spec references field_key(s) not in the M1.3 registry: {sorted(missing_fields)}"
        )
    missing_packs = [pk for pk in enabled_packs if await get_pack(conn, pk) is None]
    if missing_packs:
        raise ICPSpecValidationError(
            f"ICP spec references pack(s) not in the M3.3 catalog: {sorted(missing_packs)}"
        )


# --- row <-> ICPSpec -------------------------------------------------------
_COLUMNS = (
    "client_id, icp_key, version, status, created_from, parent_version, label, description, "
    "field_keys, enabled_packs, discovery_strategy, source_profile_ref, scoring_rubric, "
    "created_by, created_at"
)

_INSERT = text(
    """
    INSERT INTO icp_spec (
        client_id, icp_key, version, status, created_from, parent_version, label, description,
        field_keys, enabled_packs, discovery_strategy, source_profile_ref, scoring_rubric,
        created_by
    ) VALUES (
        :client_id, :icp_key, :version, CAST(:status AS icp_status),
        CAST(:created_from AS icp_created_from), :parent_version, :label, :description,
        CAST(:field_keys AS jsonb), CAST(:enabled_packs AS jsonb),
        CAST(:discovery_strategy AS jsonb), CAST(:source_profile_ref AS jsonb),
        CAST(:scoring_rubric AS jsonb), :created_by
    )
    """
)


def _row_to_icp_spec(row: Mapping[str, Any]) -> ICPSpec:
    return ICPSpec(
        client_id=row["client_id"],
        icp_key=row["icp_key"],
        version=row["version"],
        status=ICPStatus(row["status"]),
        created_from=ICPCreatedFrom(row["created_from"]),
        parent_version=row["parent_version"],
        label=row["label"],
        description=row["description"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        field_keys=tuple(decode_jsonb(row["field_keys"]) or ()),
        enabled_packs=tuple(decode_jsonb(row["enabled_packs"]) or ()),
        discovery_strategy=decode_jsonb(row["discovery_strategy"]) or {},
        source_profile_ref=decode_jsonb(row["source_profile_ref"]) or {},
        scoring_rubric=decode_jsonb(row["scoring_rubric"]) or {},
    )


async def _max_version(conn: AsyncConnection, client_id: str, icp_key: str) -> int | None:
    result = await conn.execute(
        text("SELECT max(version) AS m FROM icp_spec WHERE client_id = :c AND icp_key = :k"),
        {"c": client_id, "k": icp_key},
    )
    row = result.mappings().first()
    if row is None:
        return None
    value = row["m"]
    return None if value is None else int(value)


async def _archive_active(conn: AsyncConnection, client_id: str, icp_key: str) -> None:
    await conn.execute(
        text(
            "UPDATE icp_spec SET status = 'archived' "
            "WHERE client_id = :c AND icp_key = :k AND status = 'active'"
        ),
        {"c": client_id, "k": icp_key},
    )


# --- write (append-only) ---------------------------------------------------
async def create_icp_spec(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str,
    created_from: ICPCreatedFrom,
    field_keys: Sequence[str] = (),
    enabled_packs: Sequence[str] = (),
    discovery_strategy: Mapping[str, JsonValue] | None = None,
    source_profile_ref: Mapping[str, JsonValue] | None = None,
    scoring_rubric: Mapping[str, JsonValue] | None = None,
    created_by: str | None = None,
    label: str | None = None,
    description: str | None = None,
    activate: bool = False,
) -> ICPSpec:
    """Append a new ICP-spec version for ``(client_id, icp_key)`` and return it.

    The first call yields ``version=1`` (``parent_version=None``); each subsequent call yields the
    next version with ``parent_version`` set to the prior latest (append-only lineage) — this is how
    an *edit* works (prior versions stay byte-identical). ``field_keys`` are validated against the
    M1.3 registry and ``enabled_packs`` against the M3.3 catalog (rejected at write, naming the
    offender); both are de-duplicated (first-seen order). With ``activate=True`` the new version is
    ``active`` and any prior active is archived atomically; otherwise it is a ``draft``.
    Run inside a transaction.
    """
    # The active field set is a set — canonicalize (dedupe, preserving first-seen order) so a pinned
    # version is canonical, not caller-shaped.
    field_keys = tuple(dict.fromkeys(field_keys))
    enabled_packs = tuple(dict.fromkeys(enabled_packs))
    await validate_icp_references(conn, field_keys, enabled_packs)

    prior_max = await _max_version(conn, client_id, icp_key)
    version = (prior_max or 0) + 1
    status = ICPStatus.ACTIVE if activate else ICPStatus.DRAFT
    if activate:
        await _archive_active(conn, client_id, icp_key)

    await conn.execute(
        _INSERT,
        {
            "client_id": client_id,
            "icp_key": icp_key,
            "version": version,
            "status": status.value,
            "created_from": created_from.value,
            "parent_version": prior_max,
            "label": label,
            "description": description,
            "field_keys": serialize_value_json(list(field_keys)),
            "enabled_packs": serialize_value_json(list(enabled_packs)),
            "discovery_strategy": serialize_value_json(dict(discovery_strategy or {})),
            "source_profile_ref": serialize_value_json(dict(source_profile_ref or {})),
            "scoring_rubric": serialize_value_json(dict(scoring_rubric or {})),
            "created_by": created_by,
        },
    )
    spec = await get_icp_version(conn, client_id, icp_key, version)
    assert spec is not None  # just inserted
    return spec


async def activate_icp_version(
    conn: AsyncConnection, client_id: str, icp_key: str, version: int
) -> ICPSpec:
    """Make ``version`` the single ``active`` spec for ``(client_id, icp_key)``, archiving the prior
    active atomically (idempotent if it is already active). Run inside a transaction."""
    target = await get_icp_version(conn, client_id, icp_key, version)
    if target is None:
        raise UnknownICPSpecError(
            f"icp_spec ({client_id!r}, {icp_key!r}, v{version}) does not exist"
        )
    if target.status is ICPStatus.ACTIVE:
        return target
    await _archive_active(conn, client_id, icp_key)
    await conn.execute(
        text(
            "UPDATE icp_spec SET status = 'active' "
            "WHERE client_id = :c AND icp_key = :k AND version = :v"
        ),
        {"c": client_id, "k": icp_key, "v": version},
    )
    spec = await get_icp_version(conn, client_id, icp_key, version)
    assert spec is not None
    return spec


# --- read ------------------------------------------------------------------
async def get_active_icp(conn: AsyncConnection, client_id: str, icp_key: str) -> ICPSpec | None:
    """The single ``active`` spec for ``(client_id, icp_key)``, or ``None`` if none is active."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM icp_spec "
            "WHERE client_id = :c AND icp_key = :k AND status = 'active'"
        ),
        {"c": client_id, "k": icp_key},
    )
    row = result.mappings().first()
    return _row_to_icp_spec(dict(row)) if row is not None else None


async def get_icp_version(
    conn: AsyncConnection, client_id: str, icp_key: str, version: int
) -> ICPSpec | None:
    """A pinned spec version (reproducible — returns the originally written content)."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM icp_spec "
            "WHERE client_id = :c AND icp_key = :k AND version = :v"
        ),
        {"c": client_id, "k": icp_key, "v": version},
    )
    row = result.mappings().first()
    return _row_to_icp_spec(dict(row)) if row is not None else None


async def list_icp_versions(conn: AsyncConnection, client_id: str, icp_key: str) -> list[ICPSpec]:
    """All versions for ``(client_id, icp_key)`` in lineage order (ascending version)."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM icp_spec "
            "WHERE client_id = :c AND icp_key = :k ORDER BY version"
        ),
        {"c": client_id, "k": icp_key},
    )
    return [_row_to_icp_spec(dict(row)) for row in result.mappings().all()]


async def list_icp_keys(conn: AsyncConnection, client_id: str) -> list[str]:
    """The distinct ``icp_key``s under a client (D5: a client may run several segments)."""
    result = await conn.execute(
        text("SELECT DISTINCT icp_key FROM icp_spec WHERE client_id = :c ORDER BY icp_key"),
        {"c": client_id},
    )
    return [str(row["icp_key"]) for row in result.mappings().all()]


def diff_icp(before: ICPSpec, after: ICPSpec) -> ICPSpecDiff:
    """A pure structural diff: added/removed field-keys and packs, and which slots changed."""
    before_fields, after_fields = set(before.field_keys), set(after.field_keys)
    before_packs, after_packs = set(before.enabled_packs), set(after.enabled_packs)
    return ICPSpecDiff(
        added_field_keys=tuple(sorted(after_fields - before_fields)),
        removed_field_keys=tuple(sorted(before_fields - after_fields)),
        added_packs=tuple(sorted(after_packs - before_packs)),
        removed_packs=tuple(sorted(before_packs - after_packs)),
        discovery_strategy_changed=before.discovery_strategy != after.discovery_strategy,
        source_profile_changed=before.source_profile_ref != after.source_profile_ref,
        scoring_rubric_changed=before.scoring_rubric != after.scoring_rubric,
    )


__all__ = [
    "ICPSpecDiff",
    "ICPSpecValidationError",
    "UnknownICPSpecError",
    "validate_icp_references",
    "create_icp_spec",
    "activate_icp_version",
    "get_active_icp",
    "get_icp_version",
    "list_icp_versions",
    "list_icp_keys",
    "diff_icp",
]
