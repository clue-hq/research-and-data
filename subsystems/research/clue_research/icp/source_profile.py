"""The source-profile half of an industry pack (M3.3 / ENG-115).

staged-flow §9: a pack carries *two* prior sets. The field set ("what to know") is authored into the
M1.3 field registry; this module owns the **source profile** ("where to look") — per pack,
optionally per field-class, an ordered/weighted set of ``source_key``s with their trust weight
(staged-flow §7c: "arXiv high, Glassdoor low"). These are *priors, overridable per client*
(override > pack default) and the writable target of M13's learning loop — so they live as versioned
config rows (conventions §2, policy-is-data), not in code.

Two resolution levels share one type — :class:`ResolvedSourceProfile` — distinguished only by
``packs``: one pack key for a pack-level resolve (:func:`clue_research.icp.get_pack_source_profile`)
or every key in ``ICPSpec.enabled_packs`` after merge
(:func:`clue_research.icp.serve_source_profile` in ``catalog``). The merge function lives in
``catalog`` next to ``get_pack_source_profile`` so this module stays free of any ``ICPSpec``
dependency. The downstream M4 Source Planner intersects the served profile with the live registry
(``clue_research.sources.resolve_allowed_set``).

Boundary (conventions §2; M3.3 spec): a ``source_key`` is an opaque **string reference** into M4's
``source_manifest`` namespace. This module never imports a resolver, a manifest, the Source Planner,
or any provider SDK — exactly as ``field_definition.tier_plan`` names resolvers by string only. The
referential check ("does this source_key exist?") is late-bound to whenever M4's manifests exist
(see :func:`clue_research.icp.catalog.validate_pack`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldClass, decode_jsonb, serialize_value_json

# A source_key is the same shape as source_manifest.source_key / a resolver key: a lowercase
# identifier ("arxiv", "npi", "google_places"). Validated here so a malformed reference is caught
# at authoring time, not when M4 later tries to resolve it. (A pack namespace shares this shape.)
_SOURCE_KEY_RE = re.compile(r"[a-z][a-z0-9_]*")


def is_valid_source_key(value: str) -> bool:
    """True if ``value`` is a well-formed ``source_key`` (a lowercase identifier)."""
    return bool(_SOURCE_KEY_RE.fullmatch(value))


class SourceWeight(StrEnum):
    """The three-level ordinal trust prior the docs use (staged-flow §7c: high / medium / low).

    Ordinal by design: curated *priors* M13 later reweights from measured yield. :attr:`prior`
    exposes a numeric value for the Source Planner / learning loop without baking in a scale.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def prior(self) -> float:
        return _WEIGHT_PRIOR[self]


_WEIGHT_PRIOR: dict[SourceWeight, float] = {
    SourceWeight.HIGH: 1.0,
    SourceWeight.MEDIUM: 0.5,
    SourceWeight.LOW: 0.2,
}


class WeightedSource(BaseModel):
    """One ``source_key`` in a profile: its trust weight and its consult order (``rank``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    weight: SourceWeight
    rank: int  # 1-based consult order within the slot; lower rank = consulted first.

    @field_validator("source_key")
    @classmethod
    def _check_source_key(cls, value: str) -> str:
        if not is_valid_source_key(value):
            raise ValueError(
                f"invalid source_key {value!r}: expected a lowercase identifier such as 'arxiv'"
            )
        return value

    @field_validator("rank")
    @classmethod
    def _check_rank(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"rank must be >= 1, got {value}")
        return value


def slot_for(
    default: tuple[WeightedSource, ...],
    by_field_class: dict[FieldClass, tuple[WeightedSource, ...]],
    field_class: FieldClass | None,
) -> tuple[WeightedSource, ...]:
    """The effective weighted sources for ``field_class``: the specific slot, else the pack-wide
    default. The single definition of the slot-fallback rule, shared by every
    :class:`ResolvedSourceProfile` (DRY — one rule)."""
    if field_class is not None:
        specific = by_field_class.get(field_class)
        if specific is not None:
            return specific
    return default


class ResolvedSourceProfile(BaseModel):
    """A resolved source profile: weighted ``source_key`` priors after default ⊕ override.

    ``packs`` scopes the profile: a single pack key from :func:`get_source_profile`, or every
    enabled pack key after :func:`clue_research.icp.serve_source_profile` merges them.
    ``default`` is the pack-wide slot; ``by_field_class`` holds any field-class-specific slots. Call
    :meth:`for_field_class` to fall back to the pack-wide default when a field-class has no
    specific slot (starter packs author only the default, so it serves every field-class).
    """

    model_config = ConfigDict(frozen=True)

    packs: tuple[str, ...] = ()
    default: tuple[WeightedSource, ...] = ()
    by_field_class: dict[FieldClass, tuple[WeightedSource, ...]] = {}

    def for_field_class(self, field_class: FieldClass | None) -> tuple[WeightedSource, ...]:
        """The effective weighted sources for ``field_class`` (specific slot, else pack-wide)."""
        return slot_for(self.default, self.by_field_class, field_class)


class SourceProfileRedefinitionError(ValueError):
    """Raised when registering an existing source-profile slot/version with different content.

    Mirrors :class:`clue_research.claimstore.FieldRedefinitionError`: re-registering an identical
    slot is an idempotent no-op; changing it requires a new ``version`` (append-only — a pinned
    campaign must re-read the same profile).
    """


# --- (de)serialization helpers ---------------------------------------------
def _dump_sources(sources: Sequence[WeightedSource]) -> str:
    return serialize_value_json([s.model_dump(mode="json") for s in sources])


def _load_sources(raw: object) -> tuple[WeightedSource, ...]:
    parsed = decode_jsonb(raw) or []
    return tuple(WeightedSource.model_validate(item) for item in parsed)


def _field_class_value(field_class: FieldClass | str | None) -> str | None:
    if field_class is None:
        return None
    return field_class.value if isinstance(field_class, FieldClass) else field_class


# --- registration (append-only, idempotent) --------------------------------
_SELECT_DEFAULT = (
    "SELECT field_class, weighted_sources, version FROM source_profile WHERE pack_key = :pack_key "
    "AND field_class IS NOT DISTINCT FROM CAST(:field_class AS field_class) AND version = :version"
)
_INSERT_DEFAULT = text(
    "INSERT INTO source_profile (pack_key, field_class, weighted_sources, version) VALUES "
    "(:pack_key, CAST(:field_class AS field_class), CAST(:weighted_sources AS jsonb), :version)"
)


async def register_source_profile(
    conn: AsyncConnection,
    pack_key: str,
    sources: Sequence[WeightedSource],
    *,
    field_class: FieldClass | None = None,
    version: int = 1,
) -> None:
    """Register (or idempotently re-register) one source-profile slot for a pack.

    ``field_class=None`` is the pack-wide default slot. Re-registering an identical slot/version is
    a no-op; a different definition at the same version raises
    :class:`SourceProfileRedefinitionError` (bump ``version`` instead — append-only).
    """
    fc = _field_class_value(field_class)
    incoming = [s.model_dump(mode="json") for s in sources]
    existing = (
        (
            await conn.execute(
                text(_SELECT_DEFAULT),
                {"pack_key": pack_key, "field_class": fc, "version": version},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        current = decode_jsonb(existing["weighted_sources"]) or []
        if current == incoming:
            return
        raise SourceProfileRedefinitionError(
            f"source_profile for pack {pack_key!r} field_class {fc!r} version {version} is already "
            "registered with different sources; bump the version instead of redefining it"
        )
    await conn.execute(
        _INSERT_DEFAULT,
        {
            "pack_key": pack_key,
            "field_class": fc,
            "weighted_sources": _dump_sources(sources),
            "version": version,
        },
    )


_SELECT_OVERRIDE = (
    "SELECT weighted_sources FROM source_profile_override WHERE pack_key = :pack_key "
    "AND field_class IS NOT DISTINCT FROM CAST(:field_class AS field_class) "
    "AND workspace_id = :workspace_id AND icp_key IS NOT DISTINCT FROM :icp_key "
    "AND version = :version"
)
_INSERT_OVERRIDE = text(
    "INSERT INTO source_profile_override "
    "(pack_key, field_class, workspace_id, icp_key, weighted_sources, version) VALUES "
    "(:pack_key, CAST(:field_class AS field_class), :workspace_id, :icp_key, "
    "CAST(:weighted_sources AS jsonb), :version)"
)


async def register_source_profile_override(
    conn: AsyncConnection,
    pack_key: str,
    workspace_id: str,
    sources: Sequence[WeightedSource],
    *,
    field_class: FieldClass | None = None,
    icp_key: str | None = None,
    version: int = 1,
) -> None:
    """Register a per-client (optionally per-ICP) override of a pack source-profile slot.

    ``icp_key=None`` applies to every ICP of the client. Same append-only / idempotency discipline
    as :func:`register_source_profile`; the base pack profile is never mutated (override > default).
    """
    fc = _field_class_value(field_class)
    incoming = [s.model_dump(mode="json") for s in sources]
    existing = (
        (
            await conn.execute(
                text(_SELECT_OVERRIDE),
                {
                    "pack_key": pack_key,
                    "field_class": fc,
                    "workspace_id": workspace_id,
                    "icp_key": icp_key,
                    "version": version,
                },
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        current = decode_jsonb(existing["weighted_sources"]) or []
        if current == incoming:
            return
        raise SourceProfileRedefinitionError(
            f"source_profile_override for pack {pack_key!r} workspace {workspace_id!r} "
            f"icp {icp_key!r} "
            f"field_class {fc!r} v{version} already exists with different sources; bump version"
        )
    await conn.execute(
        _INSERT_OVERRIDE,
        {
            "pack_key": pack_key,
            "field_class": fc,
            "workspace_id": workspace_id,
            "icp_key": icp_key,
            "weighted_sources": _dump_sources(sources),
            "version": version,
        },
    )


# --- resolution (pack default ⊕ override) -----------------------------------
def _to_field_class(raw: object) -> FieldClass | None:
    return FieldClass(raw) if isinstance(raw, str) else None


async def get_source_profile(
    conn: AsyncConnection,
    pack_key: str,
    *,
    workspace_id: str | None = None,
    icp_key: str | None = None,
) -> ResolvedSourceProfile:
    """Resolve a pack's source profile: the latest pack default per slot, with any client/ICP
    override replacing the matching slot whole (override > pack default; specific field-class slot >
    pack-wide; a matching ``icp_key`` override > a client-wide ``icp_key IS NULL`` override).
    """
    # Latest pack-default row per field_class slot.
    default_rows = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (field_class) field_class, weighted_sources "
                    "FROM source_profile WHERE pack_key = :pack_key "
                    "ORDER BY field_class, version DESC"
                ),
                {"pack_key": pack_key},
            )
        )
        .mappings()
        .all()
    )
    slots: dict[FieldClass | None, tuple[WeightedSource, ...]] = {
        _to_field_class(row["field_class"]): _load_sources(row["weighted_sources"])
        for row in default_rows
    }

    if workspace_id is not None:
        slots = _apply_overrides(slots, await _override_rows(conn, pack_key, workspace_id, icp_key))

    return ResolvedSourceProfile(
        packs=(pack_key,),
        default=slots.get(None, ()),
        by_field_class={fc: src for fc, src in slots.items() if fc is not None},
    )


async def _override_rows(
    conn: AsyncConnection, pack_key: str, workspace_id: str, icp_key: str | None
) -> Sequence[Mapping[str, Any]]:
    """Candidate override rows for (client, icp), most-specific + latest-version first per slot:
    a matching ``icp_key`` outranks a client-wide ``NULL`` icp_key; newer version outranks older."""
    result = await conn.execute(
        text(
            "SELECT DISTINCT ON (field_class) field_class, weighted_sources "
            "FROM source_profile_override "
            "WHERE pack_key = :pack_key AND workspace_id = :workspace_id "
            "AND (icp_key = :icp_key OR icp_key IS NULL) "
            "ORDER BY field_class, (icp_key IS NOT NULL) DESC, version DESC"
        ),
        {"pack_key": pack_key, "workspace_id": workspace_id, "icp_key": icp_key},
    )
    return [dict(row) for row in result.mappings().all()]


def _apply_overrides(
    slots: dict[FieldClass | None, tuple[WeightedSource, ...]],
    override_rows: Sequence[Mapping[str, Any]],
) -> dict[FieldClass | None, tuple[WeightedSource, ...]]:
    merged = dict(slots)
    for row in override_rows:
        merged[_to_field_class(row["field_class"])] = _load_sources(row["weighted_sources"])
    return merged
