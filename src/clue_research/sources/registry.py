"""The Source Registry — sources as data, not code (M4.2 / ENG-111).

The swappability spine of the Source Intelligence Layer (staged-flow §7a), the sibling of the M1.3
field registry. A source is a ``source_manifest`` row; everything references it by ``source_key``:
the waterfall (M4.1) dispatches through it, ``field_definition.tier_plan`` (M1.3) names its keys,
M4.6's planner reads its tier/cost/binding/yields, and M3.3's source profiles reference its keys.
Adding/removing a provider is ``register_source`` / ``active=false`` — no caller changes, and
**nothing learns a provider's name** (``provider`` is billing/ops-only, never branched on).

Two seams live here:

* the **DB registry** (``register_source`` / ``get_source`` / ``list_sources`` / ``sources_for`` /
  ``registered_source_keys``) — the single source of valid ``source_key``s, with ``yields``
  validated against the live M1.3 field registry;
* the in-process **resolver binding** (``bind_resolver`` / ``get_resolver``) — the
  ``source_key -> Resolver`` map the waterfall dispatches through. A registered-but-unbound source
  (e.g. the tier-4 Exa/Parallel placeholders before M11) raises :class:`NoResolverBoundError`, which
  M4.1 maps to ``stop_reason=no_resolver`` — a correct empty result, never a crash.

This package never imports a resolver or a provider SDK: the binding is populated by resolvers
calling :func:`bind_resolver`, and ``sources`` → ``resolvers`` is forbidden by a dedicated one-way
import-linter contract ("source registry does not import resolvers"), so the seam cannot silently
invert. (``sources`` → ``icp`` stays permitted — decision #7, for the M4.6 planner.)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import get_field, list_fields
from clue_research.core import (
    EntityScope,
    FieldClass,
    IdentityBinding,
    Modality,
    Resolver,
    SourceManifest,
    classify_field_key,
    decode_jsonb,
    field_namespace,
    is_valid_field_key,
    serialize_value_json,
)
from clue_research.sources.manifest import RegistrySourceManifest


class SourceManifestRedefinitionError(ValueError):
    """Raised when re-registering a ``source_key`` with a different definition at the same version.

    Mirrors :class:`clue_research.claimstore.FieldRedefinitionError`: a re-registration is
    an idempotent no-op; a *changed* manifest must bump its ``version`` (which performs an update).
    """


class SourceYieldError(ValueError):
    """Raised when a manifest's ``yields`` names a field-key/class not in the M1.3 registry."""


class NoResolverBoundError(LookupError):
    """No concrete :class:`~clue_research.core.Resolver` is bound to a ``source_key``.

    The expected state for a registered-but-resolver-absent source (the tier-4 Exa/Parallel
    placeholders before M11). The waterfall (M4.1) maps this to ``stop_reason=no_resolver`` — a
    correct empty+flagged output, never a crash.
    """


# --- resolver binding (in-process; the source_key -> Resolver dispatch map) --
_RESOLVER_BINDINGS: dict[str, Resolver] = {}


def bind_resolver(source_key: str, resolver: Resolver) -> None:
    """Bind a concrete resolver to a ``source_key`` (called by M4.4/M4.5/M11 resolvers).

    Last write wins, so a test/config can swap the implementation behind a key. The registry never
    imports the resolver — the resolver registers itself here, keeping the seam one-directional.
    """
    _RESOLVER_BINDINGS[source_key] = resolver


def unbind_resolver(source_key: str) -> None:
    """Remove a resolver binding (no-op if absent)."""
    _RESOLVER_BINDINGS.pop(source_key, None)


def clear_resolver_bindings() -> None:
    """Drop all resolver bindings (test isolation)."""
    _RESOLVER_BINDINGS.clear()


def is_resolver_bound(source_key: str) -> bool:
    """True if a resolver is bound to ``source_key``."""
    return source_key in _RESOLVER_BINDINGS


def get_resolver(source_key: str) -> Resolver:
    """The resolver bound to ``source_key``; raise :class:`NoResolverBoundError` if none.

    The waterfall (M4.1) treats the error as ``stop_reason=no_resolver`` (e.g. a tier-4 placeholder
    whose resolver lands in M11), so a named-but-unbound source never fails a run.
    """
    resolver = _RESOLVER_BINDINGS.get(source_key)
    if resolver is None:
        raise NoResolverBoundError(
            f"no resolver bound to source_key {source_key!r} "
            "(registered but resolver-absent — e.g. a tier-4 placeholder until M11)"
        )
    return resolver


# --- yields validation + matching (against the M1.3 field registry) ----------
# The canonical field-classes (FieldClass minus PACK). A pack namespace (e.g. "healthcare") is the
# other class kind, validated against the registry by existence of fields under it.
_CANONICAL_CLASSES: frozenset[str] = frozenset(
    fc.value for fc in FieldClass if fc is not FieldClass.PACK
)
_SINGLE_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")


def _is_class_token(token: str) -> bool:
    """True if ``token`` denotes a field-CLASS (a canonical class or a single-segment pack ns)."""
    return token in _CANONICAL_CLASSES or bool(_SINGLE_SEGMENT.fullmatch(token))


def _key_in_class(key: str, cls: str) -> bool:
    """True if concrete field ``key`` belongs to class/namespace ``cls`` (by its actual class)."""
    if not is_valid_field_key(key):
        return False
    fc = classify_field_key(key)
    if fc is FieldClass.PACK:
        return field_namespace(key) == cls
    return fc.value == cls


def _yields_match(yields: tuple[str, ...], query: str) -> bool:
    """Does a source whose manifest ``yields`` these tokens cover ``query`` (a key or a class)?

    A ``"<class>.*"`` query is normalized to its class. A source matches when it yields the query
    exactly, OR yields a whole class that covers a concrete-key query, OR yields a concrete key that
    falls within a class query.
    """
    q = query[:-2] if query.endswith(".*") else query
    q_is_class = _is_class_token(q)
    for y in yields:
        if y == q:
            return True
        if not q_is_class and _is_class_token(y) and _key_in_class(q, y):
            return True
        if q_is_class and is_valid_field_key(y) and _key_in_class(y, q):
            return True
    return False


async def _yield_resolves(conn: AsyncConnection, token: str) -> bool:
    """True if a ``yields`` token resolves against the M1.3 registry (a class always resolves; a
    concrete key must be registered; a pack namespace must have ≥1 field)."""
    if token in _CANONICAL_CLASSES:
        return True
    if is_valid_field_key(token):  # concrete key (incl. a pack key such as healthcare.npi)
        return await get_field(conn, token) is not None
    # a single-segment pack namespace (e.g. "healthcare") — valid if any field is registered
    return bool(await list_fields(conn, pack=token, active=None))


async def _validate_yields_exist(conn: AsyncConnection, yields: tuple[str, ...]) -> None:
    """Reject (naming the offender) any ``yields`` token absent from the M1.3 field registry."""
    invalid = [token for token in yields if not await _yield_resolves(conn, token)]
    if invalid:
        raise SourceYieldError(
            f"yields reference field-key(s)/class(es) not registered in the field registry (M1.3): "
            f"{sorted(invalid)}"
        )


# --- row <-> RegistrySourceManifest -----------------------------------------
_COLUMNS = (
    "source_key, modality, entity_scope, yields, tier, cost_cents, latency_ms, geo_coverage, "
    "freshness_profile, identity_binding_strength, active, provider, auth_ref, rate_limit, "
    "requires_adapter, version, created_at"
)


def _row_to_entry(row: Mapping[str, Any]) -> RegistrySourceManifest:
    ib = row["identity_binding_strength"]
    manifest = SourceManifest(
        source_key=str(row["source_key"]),
        modality=Modality(row["modality"]),
        entity_scope=EntityScope(row["entity_scope"]),
        yields=tuple(decode_jsonb(row["yields"]) or ()),
        tier=int(row["tier"]),
        cost_cents=row["cost_cents"],  # asyncpg returns Decimal for a numeric column
        latency_ms=row["latency_ms"],
        geo_coverage=tuple(decode_jsonb(row["geo_coverage"]) or ()),
        freshness_profile=row["freshness_profile"],
        identity_binding_strength=IdentityBinding(ib) if ib is not None else None,
    )
    return RegistrySourceManifest(
        manifest=manifest,
        active=bool(row["active"]),
        provider=row["provider"],
        auth_ref=row["auth_ref"],
        rate_limit=decode_jsonb(row["rate_limit"]),
        requires_adapter=row["requires_adapter"],
        version=int(row["version"]),
        created_at=row["created_at"],
    )


def _params(entry: RegistrySourceManifest) -> dict[str, object]:
    m = entry.manifest
    ib = entry.identity_binding_strength
    return {
        "source_key": entry.source_key,
        "modality": entry.modality.value,
        "entity_scope": entry.entity_scope.value,
        "yields": serialize_value_json(list(entry.yields)),
        "tier": entry.tier,
        "cost_cents": m.cost_cents,
        "latency_ms": m.latency_ms,
        "geo_coverage": serialize_value_json(list(m.geo_coverage)),
        "freshness_profile": m.freshness_profile,
        "identity_binding_strength": ib.value if ib is not None else None,
        "active": entry.active,
        "provider": entry.provider,
        "auth_ref": entry.auth_ref,
        "rate_limit": (
            serialize_value_json(entry.rate_limit) if entry.rate_limit is not None else None
        ),
        "requires_adapter": entry.requires_adapter,
        "version": entry.version,
    }


_INSERT = text(
    """
    INSERT INTO source_manifest (
        source_key, modality, entity_scope, yields, tier, cost_cents, latency_ms, geo_coverage,
        freshness_profile, identity_binding_strength, active, provider, auth_ref, rate_limit,
        requires_adapter, version
    ) VALUES (
        :source_key, CAST(:modality AS modality), CAST(:entity_scope AS entity_scope),
        CAST(:yields AS jsonb), :tier, :cost_cents, :latency_ms, CAST(:geo_coverage AS jsonb),
        :freshness_profile, CAST(:identity_binding_strength AS identity_binding), :active,
        :provider, :auth_ref, CAST(:rate_limit AS jsonb), :requires_adapter, :version
    )
    """
)

_UPDATE = text(
    """
    UPDATE source_manifest SET
        modality = CAST(:modality AS modality),
        entity_scope = CAST(:entity_scope AS entity_scope),
        yields = CAST(:yields AS jsonb),
        tier = :tier,
        cost_cents = :cost_cents,
        latency_ms = :latency_ms,
        geo_coverage = CAST(:geo_coverage AS jsonb),
        freshness_profile = :freshness_profile,
        identity_binding_strength = CAST(:identity_binding_strength AS identity_binding),
        active = :active,
        provider = :provider,
        auth_ref = :auth_ref,
        rate_limit = CAST(:rate_limit AS jsonb),
        requires_adapter = :requires_adapter,
        version = :version
    WHERE source_key = :source_key
    """
)


def _same_ignoring_version(existing: RegistrySourceManifest, entry: RegistrySourceManifest) -> bool:
    """Content equality ignoring ``version`` and ``created_at`` (the registry bookkeeping)."""
    norm = {"version": 0, "created_at": None}
    return existing.model_copy(update=norm) == entry.model_copy(update=norm)


async def register_source(conn: AsyncConnection, entry: RegistrySourceManifest) -> None:
    """Register (or idempotently re-register / version-update) one source manifest.

    Rules (mirroring the field registry): ``yields`` must resolve against the M1.3 registry. An
    identical re-registration at the same version is a no-op; a *changed* manifest at the same
    version raises :class:`SourceManifestRedefinitionError` (bump the version); a manifest at a
    *higher* version performs a versioned update of the row. Run inside a transaction.

    Assumes a **single concurrent writer per ``source_key``** (the seed/admin path is serial) — like
    the sibling registries, the read-then-write is not race-hardened, so two concurrent inserts of
    the same new key surface the PK violation rather than the typed error. Harden with
    ``INSERT … ON CONFLICT`` / an advisory lock if that ever changes.
    """
    await _validate_yields_exist(conn, entry.manifest.yields)
    existing = await get_source(conn, entry.source_key)
    if existing is None:
        await conn.execute(_INSERT, _params(entry))
        return
    if entry.version == existing.version:
        if _same_ignoring_version(existing, entry):
            return  # exact no-op
        raise SourceManifestRedefinitionError(
            f"source {entry.source_key!r} is already registered at version {existing.version} with "
            "a different definition; bump the version to change it"
        )
    if entry.version > existing.version:
        await conn.execute(_UPDATE, _params(entry))  # versioned update
        return
    raise SourceManifestRedefinitionError(
        f"source {entry.source_key!r} is at version {existing.version}; cannot re-register at a "
        f"lower version {entry.version}"
    )


async def get_source(conn: AsyncConnection, source_key: str) -> RegistrySourceManifest | None:
    """Return the registry row for ``source_key``, or ``None`` if it is not registered."""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_COLUMNS} FROM source_manifest WHERE source_key = :k"),
                {"k": source_key},
            )
        )
        .mappings()
        .first()
    )
    return _row_to_entry(dict(row)) if row is not None else None


def _scope_value(scope: EntityScope | str | None) -> str | None:
    return scope.value if isinstance(scope, EntityScope) else scope


def _modality_value(modality: Modality | str | None) -> str | None:
    return modality.value if isinstance(modality, Modality) else modality


async def list_sources(
    conn: AsyncConnection,
    *,
    tier: int | None = None,
    modality: Modality | str | None = None,
    entity_scope: EntityScope | str | None = None,
    active: bool | None = True,
) -> list[RegistrySourceManifest]:
    """List registry rows, optionally filtered by tier / modality / entity_scope / active flag.

    ``entity_scope`` here is an EXACT filter; use :func:`sources_for` for the capability query that
    widens ``both``. ``active=None`` returns active and inactive rows.
    """
    stmt = text(
        f"""
        SELECT {_COLUMNS} FROM source_manifest
        WHERE (CAST(:active AS boolean) IS NULL OR active = CAST(:active AS boolean))
          AND (CAST(:tier AS int) IS NULL OR tier = CAST(:tier AS int))
          AND (CAST(:modality AS text) IS NULL OR modality = CAST(:modality AS modality))
          AND (CAST(:entity_scope AS text) IS NULL
               OR entity_scope = CAST(:entity_scope AS entity_scope))
        ORDER BY source_key
        """
    )
    rows = (
        (
            await conn.execute(
                stmt,
                {
                    "active": active,
                    "tier": tier,
                    "modality": _modality_value(modality),
                    "entity_scope": _scope_value(entity_scope),
                },
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_entry(dict(row)) for row in rows]


def _entity_scope_matches(scope: EntityScope, requested: str | None) -> bool:
    """A source serves the requested scope if it matches exactly or is ``both``."""
    return requested is None or scope.value == requested or scope is EntityScope.BOTH


async def sources_for(
    conn: AsyncConnection,
    field: str,
    *,
    tier: int | None = None,
    entity_scope: EntityScope | str | None = None,
    active: bool | None = True,
) -> list[str]:
    """The ``source_key``s that can populate ``field`` (a field-key or field-class), at the given
    tier / entity_scope — the lookup M4.6's planner uses to assemble a candidate set without
    hardcoding provider lists. An ``entity_scope`` filter widens to include ``both`` sources.
    """
    candidates = await list_sources(conn, tier=tier, active=active)
    requested_scope = _scope_value(entity_scope)
    return [
        s.source_key
        for s in candidates
        if _entity_scope_matches(s.entity_scope, requested_scope) and _yields_match(s.yields, field)
    ]


async def registered_source_keys(conn: AsyncConnection, *, active: bool | None = None) -> set[str]:
    """All registered ``source_key``s (the set M4.6 / ``catalog.validate_pack`` joins against)."""
    rows = await conn.execute(
        text(
            "SELECT source_key FROM source_manifest "
            "WHERE (CAST(:active AS boolean) IS NULL OR active = CAST(:active AS boolean))"
        ),
        {"active": active},
    )
    return set(rows.scalars().all())
