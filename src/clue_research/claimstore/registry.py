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

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    FieldClass,
    FieldDef,
    PassKind,
    classify_field_key,
    decode_jsonb,
    field_namespace,
    serialize_value_json,
)
from clue_research.core.field import FieldKey


class UnknownFieldError(ValueError):
    """Raised when a ``field_key`` is not registered in ``field_definition``."""


class ValueSchemaError(ValueError):
    """Raised when a ``value_json`` payload does not match a field's ``value_schema``."""


class FieldRedefinitionError(ValueError):
    """Raised when registering an existing ``field_key`` with a *different* definition."""


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
    "field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, field_class, "
    "value_schema, corroboration_min, description, active, pack, version, created_at"
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
    )


_INSERT = text(
    """
    INSERT INTO field_definition (
        field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate,
        field_class, value_schema, corroboration_min, description, active, pack, version
    ) VALUES (
        :field_key, :value_type, CAST(:validation AS jsonb), CAST(:tier_plan AS jsonb),
        :freshness_ttl, CAST(:pass_kind AS field_pass), :gate, CAST(:field_class AS field_class),
        CAST(:value_schema AS jsonb), :corroboration_min, :description, :active, :pack, :version
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
    field_class: str,
    value_schema: Mapping[str, Any] | None,
    corroboration_min: int,
    description: str | None,
    active: bool,
    pack: str | None,
) -> dict[str, Any]:
    """A normalized view of a field definition's *semantic* columns (ignores version/created_at),
    so idempotent re-registration can be detected by equality."""
    return {
        "value_type": value_type,
        "validation": validation,
        "tier_plan": list(tier_plan),
        "freshness_ttl": freshness_ttl,
        "pass_kind": pass_kind,
        "gate": gate,
        "field_class": field_class,
        "value_schema": dict(value_schema) if value_schema is not None else None,
        "corroboration_min": corroboration_min,
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
    description: str | None = None,
    active: bool = True,
    version: int = 1,
    pack: str | None = None,
) -> None:
    """Register (or idempotently re-register) one field. See module docstring for the namespace
    and re-registration rules."""
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
        field_class=field_class.value,
        value_schema=value_schema,
        corroboration_min=corroboration_min,
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
            field_class=existing["field_class"],
            value_schema=decode_jsonb(existing["value_schema"]),
            corroboration_min=existing["corroboration_min"],
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
            "field_class": field_class.value,
            "value_schema": (
                serialize_value_json(value_schema) if value_schema is not None else None
            ),
            "corroboration_min": corroboration_min,
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
