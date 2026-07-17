"""The field registry — the field set as data, not code (M1.3).

``field_definition`` rows ARE the contract (substrate §1/§3): every ``field_key`` declares its
type, validation, ordered tier plan, freshness TTL, scoring/deep pass, and gate. Adding a field or
a whole vertical is a :func:`register_field` call (+ a pack file), never a pipeline fork
(conventions §2 — open by registration, not enumeration). The registry is the single source of
valid ``field_key``s: :func:`validate_value` (called by :func:`insert_claim`) rejects a claim whose
payload does not match the field's ``value_schema``, and rejects an unregistered field outright.

Namespace rule (the "registered namespace" check): a ``field_key`` in a canonical namespace
(``core.`` / ``account.`` / ``account.resonance.`` / ``contact.`` / ``contact.facet.``) is always
admissible. Any other prefix is a *vertical pack* namespace and is admissible only if the caller
declares it via ``pack=`` (and the pack must equal the key's namespace) — so a typo like
``accont.foo`` with no declared pack is rejected, while ``healthcare.npi`` with
``pack="healthcare"`` is accepted. This keeps packs open-by-registration without a packs table.

Re-registration rule: registering a ``field_key`` that already exists with an *identical*
definition is an idempotent no-op (so a pack loads twice cleanly); registering it with a *different*
definition is rejected (a field's contract does not silently change underneath its claims).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    FieldClass,
    FieldDef,
    PassKind,
    ReuseScope,
    classify_field_key,
    decode_jsonb,
    field_namespace,
    resolve_reuse_scope,
    serialize_value_json,
)
from clue_core.field import FieldKey


class UnknownFieldError(ValueError):
    """Raised when a ``field_key`` is not registered in ``field_definition``."""


class ValueSchemaError(ValueError):
    """Raised when a ``value_json`` payload does not match a field's ``value_schema``."""


class FieldRedefinitionError(ValueError):
    """Raised when registering an existing ``field_key`` with a *different* definition."""


class ReuseScopeError(ValueError):
    """Raised by the claim-write boundary (:func:`check_claim_writable`) when a claim's
    ``reuse_scope`` is inconsistent with its field's *declared/resolved* scope (M2.5 / ENG-165 W5).

    Two fail-closed conditions: (1) the field has **no resolvable** reuse scope (an undeclared
    ``<pack>.*`` field) — we refuse to write a claim that cannot be tenant-classified rather than
    silently default it public; (2) the field is ``tenant_private`` but the claim is stamped
    ``public_footprint`` — refusing the write stops client-private data leaking into the shared
    cross-tenant base (substrate §2). A claim stamped *more* private than its field is allowed (a
    ``crm_import`` of a public-class field is correctly tenant-private)."""


# --- the value_schema validator --------------------------------------------
# A deliberately small JSON-shape vocabulary — enough for the seed pack and typed payloads, with no
# extra dependency. Supported: {"type": object|array|string|integer|number|boolean|null,
# "properties": {...}, "required": [...], "items": {...}, "enum": [...]}.
_SCALAR_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _validate_payload(value: Any, schema: Mapping[str, Any], path: str = "value") -> None:
    """Validate ``value`` against a small JSON-shape ``schema``; raise :class:`ValueSchemaError`."""
    if "enum" in schema and value not in schema["enum"]:
        raise ValueSchemaError(f"{path}: {value!r} is not one of {schema['enum']!r}")
    declared = schema.get("type")
    if declared is None:
        return
    if declared == "object":
        if not isinstance(value, dict):
            raise ValueSchemaError(f"{path}: expected object, got {type(value).__name__}")
        for required_key in schema.get("required", []):
            if required_key not in value:
                raise ValueSchemaError(f"{path}: missing required key {required_key!r}")
        for prop, subschema in schema.get("properties", {}).items():
            if prop in value:
                _validate_payload(value[prop], subschema, f"{path}.{prop}")
    elif declared == "array":
        if not isinstance(value, list):
            raise ValueSchemaError(f"{path}: expected array, got {type(value).__name__}")
        items = schema.get("items")
        if items is not None:
            for index, item in enumerate(value):
                _validate_payload(item, items, f"{path}[{index}]")
    else:
        check = _SCALAR_CHECKS.get(declared)
        if check is None:
            raise ValueSchemaError(f"{path}: unknown schema type {declared!r}")
        if not check(value):
            raise ValueSchemaError(f"{path}: expected {declared}, got {type(value).__name__}")


# --- row <-> FieldDef helpers ----------------------------------------------
_SELECT = (
    "field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, signal_class, "
    "reuse_scope, field_class, value_schema, corroboration_min, single_source_sufficient, "
    "equality_mode, description, active, pack, version, created_at"
)


def _row_to_field_def(row: Mapping[str, Any]) -> FieldDef:
    return FieldDef(
        field_key=row["field_key"],
        value_type=row["value_type"],
        validation=decode_jsonb(row["validation"]),
        tier_plan=tuple(decode_jsonb(row["tier_plan"]) or ()),
        freshness_ttl=row["freshness_ttl"],
        pass_kind=row["pass_kind"],
        gate=row["gate"],
        signal_class=row["signal_class"],
        reuse_scope=row["reuse_scope"],
    )


_INSERT = text(
    """
    INSERT INTO field_definition (
        field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, signal_class,
        reuse_scope, field_class, value_schema, corroboration_min, single_source_sufficient,
        equality_mode, description, active, pack, version
    ) VALUES (
        :field_key, :value_type, CAST(:validation AS jsonb), CAST(:tier_plan AS jsonb),
        :freshness_ttl, CAST(:pass_kind AS field_pass), :gate, :signal_class,
        CAST(:reuse_scope AS reuse_scope), CAST(:field_class AS field_class),
        CAST(:value_schema AS jsonb), :corroboration_min, :single_source_sufficient,
        CAST(:equality_mode AS equality_mode), :description, :active, :pack, :version
    )
    """
)


async def _get_row(conn: AsyncConnection, field_key: str) -> Mapping[str, Any] | None:
    result = await conn.execute(
        text(f"SELECT {_SELECT} FROM field_definition WHERE field_key = :k"),
        {"k": field_key},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _comparable(
    *,
    value_type: str,
    validation: JsonValue | None,
    tier_plan: Sequence[str],
    freshness_ttl: timedelta | None,
    pass_kind: str,
    gate: str | None,
    signal_class: str | None,
    reuse_scope: str | None,
    field_class: str,
    value_schema: Mapping[str, Any] | None,
    corroboration_min: int,
    single_source_sufficient: bool,
    equality_mode: str,
    description: str | None,
    active: bool,
    pack: str | None,
) -> dict[str, Any]:
    """A normalized view of a field definition's *semantic* columns (ignores version/created_at),
    so idempotent re-registration can be detected by equality. ``reuse_scope`` is part of the
    contract: changing a field's declared data-class is a redefinition (bump the version). The M9.2
    corroboration config (``corroboration_min`` / ``single_source_sufficient`` / ``equality_mode``)
    is contract too — changing how a field is verified is a redefinition (D7: tune via a version
    bump, not a silent overwrite under live claims)."""
    return {
        "value_type": value_type,
        "validation": validation,
        "tier_plan": list(tier_plan),
        "freshness_ttl": freshness_ttl,
        "pass_kind": pass_kind,
        "gate": gate,
        "signal_class": signal_class,
        "reuse_scope": reuse_scope,
        "field_class": field_class,
        "value_schema": dict(value_schema) if value_schema is not None else None,
        "corroboration_min": corroboration_min,
        "single_source_sufficient": single_source_sufficient,
        "equality_mode": equality_mode,
        "description": description,
        "active": active,
        "pack": pack,
    }


async def register_field(
    conn: AsyncConnection,
    field_def: FieldDef,
    *,
    value_schema: Mapping[str, Any] | None = None,
    corroboration_min: int = 1,
    single_source_sufficient: bool = False,
    equality_mode: str = "exact",
    description: str | None = None,
    active: bool = True,
    version: int = 1,
    pack: str | None = None,
) -> None:
    """Register (or idempotently re-register) one field. See module docstring for the namespace
    and re-registration rules.

    The M9.2 corroboration config is *data on the field* (conventions §2): ``corroboration_min`` is
    the # of independent tier≤3 sources required to promote a claim to ``verified`` (1 = a single
    confident claim suffices, the default — non-load-bearing fields are not blocked);
    ``single_source_sufficient`` lets a tier-1 deterministic claim verify alone (e.g. a registry
    ID); ``equality_mode`` (``exact`` / ``numeric_tol`` / ``semantic``) is how the corroborator
    decides two ``value_json`` payloads agree. They are stored here; the M9 corroborator reads them
    (:func:`get_corroboration_config`)."""
    field_class = classify_field_key(field_def.field_key)
    namespace = field_namespace(field_def.field_key)
    if field_class is FieldClass.PACK:
        if pack is None:
            raise ValueError(
                f"field_key {field_def.field_key!r} is in an unregistered namespace "
                f"{namespace!r}; declare the owning vertical via pack={namespace!r}"
            )
        if pack != namespace:
            raise ValueError(f"pack {pack!r} must equal the field_key namespace {namespace!r}")
    elif pack is not None:
        raise ValueError(
            f"field_key {field_def.field_key!r} is in canonical namespace {namespace!r}; "
            "it must not declare a pack"
        )

    incoming = _comparable(
        value_type=field_def.value_type,
        validation=field_def.validation,
        tier_plan=field_def.tier_plan,
        freshness_ttl=field_def.freshness_ttl,
        pass_kind=field_def.pass_kind.value,
        gate=field_def.gate,
        signal_class=field_def.signal_class,
        reuse_scope=field_def.reuse_scope.value if field_def.reuse_scope is not None else None,
        field_class=field_class.value,
        value_schema=value_schema,
        corroboration_min=corroboration_min,
        single_source_sufficient=single_source_sufficient,
        equality_mode=equality_mode,
        description=description,
        active=active,
        pack=pack,
    )

    existing = await _get_row(conn, field_def.field_key)
    if existing is not None:
        current = _comparable(
            value_type=existing["value_type"],
            validation=decode_jsonb(existing["validation"]),
            tier_plan=decode_jsonb(existing["tier_plan"]) or [],
            freshness_ttl=existing["freshness_ttl"],
            pass_kind=existing["pass_kind"],
            gate=existing["gate"],
            signal_class=existing["signal_class"],
            reuse_scope=existing["reuse_scope"],
            field_class=existing["field_class"],
            value_schema=decode_jsonb(existing["value_schema"]),
            corroboration_min=existing["corroboration_min"],
            single_source_sufficient=existing["single_source_sufficient"],
            equality_mode=existing["equality_mode"],
            description=existing["description"],
            active=existing["active"],
            pack=existing["pack"],
        )
        if current == incoming:
            return  # idempotent no-op
        raise FieldRedefinitionError(
            f"field_key {field_def.field_key!r} is already registered with a different "
            "definition; bump the version / change the field_key instead of redefining it"
        )

    await conn.execute(
        _INSERT,
        {
            "field_key": field_def.field_key,
            "value_type": field_def.value_type,
            "validation": (
                serialize_value_json(field_def.validation)
                if field_def.validation is not None
                else None
            ),
            "tier_plan": serialize_value_json(list(field_def.tier_plan)),
            "freshness_ttl": field_def.freshness_ttl,
            "pass_kind": field_def.pass_kind.value,
            "gate": field_def.gate,
            "signal_class": field_def.signal_class,
            "reuse_scope": (
                field_def.reuse_scope.value if field_def.reuse_scope is not None else None
            ),
            "field_class": field_class.value,
            "value_schema": (
                serialize_value_json(value_schema) if value_schema is not None else None
            ),
            "corroboration_min": corroboration_min,
            "single_source_sufficient": single_source_sufficient,
            "equality_mode": equality_mode,
            "description": description,
            "active": active,
            "pack": pack,
            "version": version,
        },
    )


async def get_field(conn: AsyncConnection, field_key: str) -> FieldDef | None:
    """Return the :class:`FieldDef` for ``field_key``, or ``None`` if it is not registered."""
    row = await _get_row(conn, field_key)
    return _row_to_field_def(row) if row is not None else None


class CorroborationConfig(BaseModel):
    """The per-field M9.2 corroboration policy, read off ``field_definition`` (conventions §2 —
    policy is data). Kept here, with plain-typed fields, so the claim-store substrate never imports
    the verification worker: ``equality_mode`` is the DB enum *string* (``exact`` / ``numeric_tol``
    / ``semantic``); the M9 corroborator maps it to its own ``EqualityMode`` enum. The corroborator
    reads this instead of the full :class:`FieldDef` (the corroboration columns are registry-local
    and deliberately not on the frozen ``core.FieldDef`` contract)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corroboration_min: int = 1
    single_source_sufficient: bool = False
    equality_mode: str = "exact"


async def get_corroboration_config(
    conn: AsyncConnection, field_key: str
) -> CorroborationConfig | None:
    """Return the :class:`CorroborationConfig` for ``field_key`` (the M9.2 corroborator's input), or
    ``None`` if the field is not registered. One small read of the corroboration columns — keeping
    the ``field_definition`` SQL in its owning module (the registry), as the merge layer's
    ``_freshness_ttl`` does for the TTL column."""
    row = await conn.execute(
        text(
            "SELECT corroboration_min, single_source_sufficient, equality_mode "
            "FROM field_definition WHERE field_key = :k"
        ),
        {"k": field_key},
    )
    found = row.mappings().first()
    if found is None:
        return None
    return CorroborationConfig(
        corroboration_min=found["corroboration_min"],
        single_source_sufficient=found["single_source_sufficient"],
        equality_mode=found["equality_mode"],
    )


def _normalize_field_class(field_class: FieldClass | str | None) -> str | None:
    if field_class is None:
        return None
    if isinstance(field_class, FieldClass):
        return field_class.value
    return field_class[:-2] if field_class.endswith(".*") else field_class


async def list_fields(
    conn: AsyncConnection,
    *,
    pass_kind: PassKind | str | None = None,
    field_class: FieldClass | str | None = None,
    pack: str | None = None,
    active: bool | None = True,
) -> list[FieldDef]:
    """List registered fields, optionally filtered by pass / field-class / pack / active flag."""
    stmt = text(
        f"""
        SELECT {_SELECT} FROM field_definition
        WHERE (CAST(:active AS boolean) IS NULL OR active = CAST(:active AS boolean))
          AND (CAST(:pass_kind AS text) IS NULL OR pass_kind = CAST(:pass_kind AS field_pass))
          AND (CAST(:field_class AS text) IS NULL
               OR field_class = CAST(:field_class AS field_class))
          AND (CAST(:pack AS text) IS NULL OR pack = :pack)
        ORDER BY field_key
        """
    )
    result = await conn.execute(
        stmt,
        {
            "active": active,
            "pass_kind": pass_kind.value if isinstance(pass_kind, PassKind) else pass_kind,
            "field_class": _normalize_field_class(field_class),
            "pack": pack,
        },
    )
    return [_row_to_field_def(dict(row)) for row in result.mappings().all()]


async def validate_value(
    conn: AsyncConnection, field_key: FieldKey | str, value_json: JsonValue
) -> None:
    """Validate ``value_json`` against the field's ``value_schema``.

    Raises :class:`UnknownFieldError` if the field is not registered and :class:`ValueSchemaError`
    if the payload does not match the declared shape. A field with no ``value_schema`` imposes no
    shape constraint (validation passes). Called by :func:`insert_claim`.
    """
    row = await _get_row(conn, field_key)
    if row is None:
        raise UnknownFieldError(
            f"field_key {field_key!r} is not registered; register it before writing claims "
            "(the registry is the single source of valid field_keys — conventions §2)"
        )
    schema = decode_jsonb(row["value_schema"])
    if schema is None:
        return
    _validate_payload(value_json, schema)


async def check_claim_writable(
    conn: AsyncConnection,
    *,
    field_key: FieldKey | str,
    value_json: JsonValue,
    reuse_scope: ReuseScope,
) -> None:
    """The field-claim write gate (M1.3 + M2.5/ENG-165 W5) — one registry lookup, two checks.

    Called by :func:`insert_claim` for every *field*-flavored claim (discovery-provenance claims
    carry admission evidence, not a typed value, and skip it). It enforces, in a single
    ``field_definition`` read:

    1. **payload validation** — the value matches the field's ``value_schema``; an unregistered
       field is rejected (:class:`UnknownFieldError`). The registry is the single source of valid
       field keys (conventions §2).
    2. **fail-closed reuse classification** (substrate §2) — the field must have a *resolvable*
       reuse scope (declared, or a class default; an undeclared ``<pack>.*`` field has none and is
       refused), and a field declared ``tenant_private`` must not be written with a
       ``public_footprint`` claim (that would leak client-private data into the shared base). A
       claim stamped *more* private than its field is allowed (e.g. a ``crm_import`` of a
       public-class field). Both raise :class:`ReuseScopeError`.

    This is the unbypassable backstop: even if a caller forgets :func:`identity.stamp_reuse`, a
    private field cannot be written public through :func:`insert_claim`.
    """
    row = await _get_row(conn, field_key)
    if row is None:
        raise UnknownFieldError(
            f"field_key {field_key!r} is not registered; register it before writing claims "
            "(the registry is the single source of valid field_keys — conventions §2)"
        )
    schema = decode_jsonb(row["value_schema"])
    if schema is not None:
        _validate_payload(value_json, schema)

    resolved = resolve_reuse_scope(_row_to_field_def(row))
    if resolved is None:
        raise ReuseScopeError(
            f"field_key {field_key!r} has no resolvable reuse_scope (an undeclared <pack>.* "
            "field); declare its reuse_scope before writing claims — refusing to write a claim "
            "that cannot be tenant-classified (fail-closed; substrate §2 / ENG-165)"
        )
    if resolved is ReuseScope.TENANT_PRIVATE and reuse_scope is ReuseScope.PUBLIC_FOOTPRINT:
        raise ReuseScopeError(
            f"field_key {field_key!r} is declared tenant_private but the claim is stamped "
            "public_footprint — refusing the write (it would leak tenant-private data into the "
            "shared cross-tenant base). Stamp it via identity.stamp_reuse with the run's tenant_id "
            "(substrate §2 / ENG-165)"
        )
