"""The industry-pack catalog (M3.3 / ENG-115).

This is the framework that ties together staged-flow §9's two prior sets so a vertical is added by
**registration, not enumeration** (substrate §3 payoff 1; conventions §2/§3):

* the **field-set half** — ``<pack>.*`` ``field_definition`` rows authored into the M1.3 registry
  (this module *reuses* :func:`clue_research.claimstore.load_pack`; the registry stays the system of
  record — packs are authors, not a parallel store, preserving DRY);
* the **source-profile half** — weighted ``source_key`` priors stored as versioned config
  (:mod:`clue_research.icp.source_profile`).

A pack's ``pack_key`` (``healthcare_practice``) and its field-key ``namespace`` (``healthcare``)
differ on purpose (conventions §3). The two seams are kept distinct so "what to know" and "where to
look" evolve independently: :func:`get_pack_field_set` feeds M3.2's compiler;
:func:`get_pack_source_profile` (one pack) and :func:`serve_source_profile` (the whole ICP, every
enabled pack merged) feed M4's Source Planner.

Boundary: this module imports the shared claim-store substrate (M1) and the M3.3 source-profile
tables only. It never imports a resolver, a ``source_manifest``, the Source Planner, or a provider
SDK (all M4) — it references ``source_key``s by string and defers the existence check to
:func:`validate_pack` (conventions §2; M0.1 import rules).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    FieldClass,
    FieldDef,
    ICPSpec,
    classify_field_key,
    field_namespace,
    resolve_reuse_scope,
)
from clue_core import register_pack as register_namespace
from clue_research.claimstore import SeedField, get_field, list_fields, load_pack
from clue_research.icp.source_profile import (
    ResolvedSourceProfile,
    WeightedSource,
    get_source_profile,
    is_valid_source_key,
    register_source_profile,
)


class UnknownPackError(ValueError):
    """Raised when a ``pack_key`` is not present in the catalog."""


class PackRedefinitionError(ValueError):
    """Raised when registering an existing ``pack_key`` with a different definition.

    Mirrors :class:`clue_research.claimstore.FieldRedefinitionError`: an identical
    re-registration is an idempotent no-op; a changed pack must bump its ``version``.
    """


class PackValidationError(ValueError):
    """Raised by :func:`validate_pack` when a pack references a field-key not registered in the M1.3
    registry, or a ``source_key`` that is malformed / not in M4's manifest namespace."""


@dataclass(frozen=True)
class PackSourceSlot:
    """One authored source-profile slot; ``field_class=None`` is the pack-wide default."""

    sources: tuple[WeightedSource, ...]
    field_class: FieldClass | None = None


@dataclass(frozen=True)
class Pack:
    """An industry pack as authored data (staged-flow §9). Both halves live here; registering it
    (:func:`register_pack_catalog`) writes the field set into M1.3 and the source profile into the
    M3.3 config tables. Pure data — the framework is the only code (conventions §2)."""

    pack_key: str
    namespace: str
    title: str
    field_set: tuple[SeedField, ...] = ()
    source_profile: tuple[PackSourceSlot, ...] = ()
    description: str | None = None


class PackRecord(BaseModel):
    """A read view of a ``pack`` catalog row."""

    model_config = ConfigDict(frozen=True)

    pack_key: str
    namespace: str
    title: str
    description: str | None
    active: bool
    version: int
    created_at: datetime


# --- static validation of a pack definition --------------------------------
def _validate_pack_definition(pack: Pack) -> None:
    """Cheap, DB-free consistency checks before any write (clearer than the per-field error)."""
    if not is_valid_source_key(pack.namespace):
        raise PackValidationError(
            f"pack {pack.pack_key!r} has invalid namespace {pack.namespace!r} "
            "(expected a lowercase identifier such as 'healthcare')"
        )
    for seed in pack.field_set:
        key = seed.field_def.field_key
        if classify_field_key(key) is FieldClass.PACK:
            # A vertical field must sit under THIS pack's namespace and declare it.
            if field_namespace(key) != pack.namespace:
                raise PackValidationError(
                    f"pack {pack.pack_key!r} field {key!r} is not under namespace "
                    f"{pack.namespace!r}"
                )
            if seed.pack != pack.namespace:
                raise PackValidationError(
                    f"pack {pack.pack_key!r} field {key!r} must declare pack={pack.namespace!r}, "
                    f"got pack={seed.pack!r}"
                )
            # Fail-closed reuse classification (M2.5 / ENG-165 W5): a <pack>.* field has no safe
            # class default, so it MUST declare its reuse_scope or claims of it could silently
            # default into the shared cross-tenant base (substrate §2).
            if resolve_reuse_scope(seed.field_def) is None:
                raise PackValidationError(
                    f"pack {pack.pack_key!r} field {key!r} must declare a reuse_scope (a <pack>.* "
                    "field has no safe default — set reuse_scope=public_footprint or "
                    "tenant_private; fail-closed, ENG-165 W5)"
                )
            # Species likewise has no ratified default for a vertical pack (FI-2 P3 / §5.2), and
            # `register_field` refuses an undeclared one — so `validate_pack` must not return clean
            # for a pack `load_pack` will reject. `client.*` is exempt (workspace-scoped by
            # construction, ratified neutral).
            if seed.field_def.research_scope is None and pack.namespace != "client":
                raise PackValidationError(
                    f"pack {pack.pack_key!r} field {key!r} must declare a research_scope (a "
                    "<pack>.* field has no ratified species default — set "
                    "research_scope=project_neutral for a world-fact or project_relative for an "
                    "ICP/campaign-relative value; FI-2 P3)"
                )
        elif seed.pack is not None:
            # A canonical contribution (e.g. a registered account.resonance.* field — Doc C §2) is a
            # shared registry row, not pack-namespaced; it must not declare a pack.
            raise PackValidationError(
                f"pack {pack.pack_key!r} canonical field {key!r} must not declare pack="
                f"{seed.pack!r} (it is a shared field-class contribution)"
            )


# --- pack catalog row ------------------------------------------------------
_PACK_COLUMNS = "pack_key, namespace, title, description, active, version, created_at"


async def _get_pack_row(conn: AsyncConnection, pack_key: str) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text(f"SELECT {_PACK_COLUMNS} FROM pack WHERE pack_key = :pack_key"),
                {"pack_key": pack_key},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def _upsert_pack_row(conn: AsyncConnection, pack: Pack, *, version: int) -> None:
    existing = await _get_pack_row(conn, pack.pack_key)
    if existing is not None:
        same = (
            existing["namespace"] == pack.namespace
            and existing["title"] == pack.title
            and existing["description"] == pack.description
        )
        if same:
            return  # idempotent no-op
        raise PackRedefinitionError(
            f"pack {pack.pack_key!r} is already registered with a different definition; "
            "bump the version / change the pack_key instead of redefining it"
        )
    await conn.execute(
        text(
            "INSERT INTO pack (pack_key, namespace, title, description, version) "
            "VALUES (:pack_key, :namespace, :title, :description, :version)"
        ),
        {
            "pack_key": pack.pack_key,
            "namespace": pack.namespace,
            "title": pack.title,
            "description": pack.description,
            "version": version,
        },
    )


async def register_pack_catalog(conn: AsyncConnection, pack: Pack, *, version: int = 1) -> None:
    """Register a pack: catalog row + field set (into M1.3) + source profile (into M3.3 config).

    Idempotent end to end (re-registering the same pack is a no-op), so loading a pack twice — or
    re-running a migration-seed step — is safe. Run inside a transaction.
    """
    _validate_pack_definition(pack)
    await _upsert_pack_row(conn, pack, version=version)
    # Activate the dormant namespace seam (core.register_pack) so tooling distinguishes a known pack
    # namespace from a typo (M3.3 owns pack content; conventions §3).
    register_namespace(pack.namespace)
    # Field-set half: author the field_definition rows. REUSE load_pack — do not fork the registry.
    await load_pack(conn, pack.field_set)
    # Source-profile half: one row per authored slot (pack-wide default and/or per field-class).
    for slot in pack.source_profile:
        await register_source_profile(
            conn, pack.pack_key, slot.sources, field_class=slot.field_class, version=version
        )


# --- catalog read seam -----------------------------------------------------
async def list_packs(conn: AsyncConnection, *, active: bool | None = True) -> list[PackRecord]:
    """List cataloged packs, optionally filtered by the ``active`` flag (``None`` = all)."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_PACK_COLUMNS} FROM pack "
                    "WHERE (CAST(:active AS boolean) IS NULL OR active = CAST(:active AS boolean)) "
                    "ORDER BY pack_key"
                ),
                {"active": active},
            )
        )
        .mappings()
        .all()
    )
    return [PackRecord.model_validate(dict(row)) for row in rows]


async def get_pack(conn: AsyncConnection, pack_key: str) -> PackRecord | None:
    """Return the catalog row for ``pack_key``, or ``None`` if it is not registered."""
    row = await _get_pack_row(conn, pack_key)
    return PackRecord.model_validate(row) if row is not None else None


async def get_pack_field_set(conn: AsyncConnection, pack_key: str) -> list[FieldDef]:
    """The pack's ``<pack>.*`` field definitions (M3.2 composes these into the field plan).

    Returns the registry rows authored under the pack's namespace. Canonical contributions a pack
    may also register (e.g. an ``account.resonance.*`` field — Doc C §2) are shared rows in their
    own field-class, not ``<pack>.*``, so they are reached via ``list_fields(field_class=...)``.
    """
    rec = await get_pack(conn, pack_key)
    if rec is None:
        raise UnknownPackError(f"pack {pack_key!r} is not in the catalog")
    return await list_fields(conn, pack=rec.namespace)


async def get_pack_source_profile(
    conn: AsyncConnection,
    pack_key: str,
    *,
    workspace_id: str | None = None,
    icp_key: str | None = None,
) -> ResolvedSourceProfile:
    """The pack's resolved source profile (pack default ⊕ client/ICP override). Consumed by M4's
    Source Planner (staged-flow §7d); :func:`serve_source_profile` merges it across an ICP's
    packs."""
    rec = await get_pack(conn, pack_key)
    if rec is None:
        raise UnknownPackError(f"pack {pack_key!r} is not in the catalog")
    return await get_source_profile(conn, pack_key, workspace_id=workspace_id, icp_key=icp_key)


def _merge_slot(weighted_lists: Sequence[Sequence[WeightedSource]]) -> tuple[WeightedSource, ...]:
    """Merge per-pack weighted-source lists into one ordered slot.

    Dedup by ``source_key`` keeping the strongest weight (tie-break: lowest authored ``rank``), then
    order by weight prior DESC → rank ASC → key (deterministic). For a single-pack ICP this exactly
    reproduces the pack's staged-flow §7c ordering, since each pack authors its sources in
    weight-descending order.
    """
    best: dict[str, WeightedSource] = {}
    for lst in weighted_lists:
        for ws in lst:
            current = best.get(ws.source_key)
            if (
                current is None
                or ws.weight.prior > current.weight.prior
                or (ws.weight.prior == current.weight.prior and ws.rank < current.rank)
            ):
                best[ws.source_key] = ws
    return tuple(sorted(best.values(), key=lambda w: (-w.weight.prior, w.rank, w.source_key)))


async def serve_source_profile(
    conn: AsyncConnection,
    spec: ICPSpec,
    *,
    packs: Sequence[str] | None = None,
) -> ResolvedSourceProfile:
    """Resolve ``spec``'s effective source profile: every enabled pack, merged.

    The ICP-level analogue of :func:`get_pack_source_profile`. Each pack is resolved with the
    client/ICP override applied (:func:`get_pack_source_profile`, keyed by ``pack_key`` with
    ``workspace_id``/``icp_key`` from the spec — override > pack default). The merge unions the
    packs'
    weighted sets (see :func:`_merge_slot`). ``packs`` overrides ``spec.enabled_packs`` (for an
    audit of a subset); the default serves exactly the ICP's enabled packs. Consumed by M4's Source
    Planner (``clue_research.sources.resolve_allowed_set`` intersects the result with the registry).
    """
    pack_keys = tuple(packs) if packs is not None else tuple(spec.enabled_packs)
    profiles: list[ResolvedSourceProfile] = [
        await get_pack_source_profile(
            conn, pack_key, workspace_id=spec.workspace_id, icp_key=spec.icp_key
        )
        for pack_key in pack_keys
    ]

    explicit_fcs: set[FieldClass] = set()
    for profile in profiles:
        explicit_fcs.update(profile.by_field_class.keys())

    default = _merge_slot([profile.default for profile in profiles])
    by_field_class = {
        fc: _merge_slot([profile.for_field_class(fc) for profile in profiles])
        for fc in explicit_fcs
    }
    return ResolvedSourceProfile(packs=pack_keys, default=default, by_field_class=by_field_class)


async def validate_pack(
    conn: AsyncConnection,
    pack: Pack,
    *,
    known_source_keys: set[str] | None = None,
) -> None:
    """Validate a pack definition against the live registry and the source namespace.

    Raises :class:`PackValidationError` (naming the offender) if a declared ``field_key`` is not
    registered in the M1.3 registry, or a referenced ``source_key`` (from a source profile or a
    field's ``tier_plan``) is malformed or — when ``known_source_keys`` is supplied (by M4 once its
    ``source_manifest`` exists) — not in that namespace. ``known_source_keys=None`` skips the
    existence check (the M4 join is late-bound; M3.3 is not blocked by M4).
    """
    _validate_pack_definition(pack)
    for seed in pack.field_set:
        key = seed.field_def.field_key
        if await get_field(conn, key) is None:
            raise PackValidationError(
                f"pack {pack.pack_key!r} references field_key {key!r} which is not registered in "
                "the field registry (M1.3)"
            )
    source_keys = {s.source_key for slot in pack.source_profile for s in slot.sources}
    source_keys |= {sk for seed in pack.field_set for sk in seed.field_def.tier_plan}
    malformed = sorted(sk for sk in source_keys if not is_valid_source_key(sk))
    if malformed:
        raise PackValidationError(
            f"pack {pack.pack_key!r} references malformed source_key(s): {malformed}"
        )
    if known_source_keys is not None:
        unknown = sorted(source_keys - known_source_keys)
        if unknown:
            raise PackValidationError(
                f"pack {pack.pack_key!r} references source_key(s) not in the source manifest (M4): "
                f"{unknown}"
            )


__all__ = [
    "Pack",
    "PackSourceSlot",
    "PackRecord",
    "UnknownPackError",
    "PackRedefinitionError",
    "PackValidationError",
    "register_pack_catalog",
    "list_packs",
    "get_pack",
    "get_pack_field_set",
    "get_pack_source_profile",
    "serve_source_profile",
    "validate_pack",
]
