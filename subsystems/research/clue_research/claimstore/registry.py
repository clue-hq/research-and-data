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

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    FieldClass,
    FieldDef,
    PassKind,
    ProductScopePolicy,
    ResearchScope,
    ReuseScope,
    classify_field_key,
    decode_jsonb,
    default_research_scope,
    field_namespace,
    is_valid_field_key,
    resolve_product_scope,
    resolve_research_scope,
    resolve_reuse_scope,
    serialize_value_json,
)
from clue_core.field import FieldKey

# The tenant-local dynamic Client-KB namespace (``stage0.fields.CLIENT_PACK``), repeated here
# rather than imported: the claim-store substrate must not depend on a milestone package.
_CLIENT_NAMESPACE = "client"


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


class ProductScopeError(ValueError):
    """A field claim's ``product_id`` violates the field registry's effective product policy."""


class ResearchScopeError(ValueError):
    """Raised by :func:`register_field` when a ``<pack>.*`` field declares no ``research_scope``
    (FI-2 P3 — the species attribute; spec §4/§5.2).

    A vertical pack's fields are authored outside the ratified species table, so there is no safe
    default for them: guessing neutral would let a project-relative pack field be reused across
    projects and shown in every lens, and guessing relative would re-buy world-facts per project.
    Pack authors declare per field, exactly as they already do for ``reuse_scope``. ``client.*``
    (the tenant-local dynamic Client-KB namespace) is excepted — those fields are workspace-scoped
    by construction and neutral by the ratified table."""


class FieldRegistryOrigin(StrEnum):
    """Which durable registry layer supplied an effective field definition."""

    GLOBAL = "global"
    WORKSPACE = "workspace"


class FieldRegistryScope(BaseModel):
    """Trusted tenant scope for effective registry reads.

    ``workspace_id=None`` is deliberately global-only. A caller never receives every workspace's
    definitions through this seam; privileged inventory/erasure code uses explicit store queries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str | None = None

    @classmethod
    def global_only(cls) -> FieldRegistryScope:
        return cls()

    @classmethod
    def for_workspace(cls, workspace_id: str) -> FieldRegistryScope:
        if not workspace_id:
            raise ValueError("workspace field-registry scope requires workspace_id")
        return cls(workspace_id=workspace_id)


class FieldFilters(BaseModel):
    """Deterministic filters shared by global and workspace registry list reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pass_kind: PassKind | None = None
    field_class: FieldClass | None = None
    pack: str | None = None
    active: bool | None = True


class ResolvedFieldDefinition(BaseModel):
    """One complete field contract plus the registry layer that owns it."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    field_def: FieldDef
    value_schema: dict[str, Any] | None = None
    corroboration_min: int = 1
    single_source_sufficient: bool = False
    equality_mode: str = "exact"
    description: str | None = None
    active: bool = True
    pack: str | None = None
    definition_version: int = 1
    origin: FieldRegistryOrigin
    workspace_id: str | None = None
    client_kb_role: str | None = None
    promoted_from_proposal_id: UUID | None = None
    promotion_policy_version: str | None = None
    promoted_by: str | None = None
    created_at: datetime | None = None
    label: str | None = None
    presentation: str = "text"


class WorkspaceFieldDefinitionError(ValueError):
    """A proposed workspace definition violates the tenant-local registry contract."""


class WorkspaceFieldRetiredError(ValueError):
    """A workspace field is absent/retired; never eligible for unknown-field registration."""


class ResearchFieldInputError(WorkspaceFieldDefinitionError):
    """Invalid label, description or entity in a human-authored research definition."""


class ResearchFieldKeyTaken(WorkspaceFieldDefinitionError):
    """A research key is reserved by platform vocabulary or a local definition."""


class WorkspaceDynamicClientKbErasedError(ValueError):
    """A C8 write was attempted after this workspace's dynamic Client-KB was erased."""


async def workspace_dynamic_client_kb_is_erased(
    conn: AsyncConnection, *, workspace_id: str
) -> bool:
    return (
        await conn.execute(
            text(
                "SELECT 1 FROM workspace_dynamic_client_kb_erasure "
                "WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
    ).scalar_one_or_none() is not None


async def assert_workspace_dynamic_client_kb_active(
    conn: AsyncConnection, *, workspace_id: str
) -> None:
    """Take the write-side workspace lock and enforce the no-resurrection marker.

    Workspace erasure takes ``FOR UPDATE`` on the same row. A racing C8 writer therefore either
    commits before the eraser scans it or waits, observes the marker, and fails closed.
    """

    workspace = (
        await conn.execute(
            text(
                "SELECT workspace_id FROM workspace WHERE workspace_id = :workspace_id "
                "FOR KEY SHARE"
            ),
            {"workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise WorkspaceFieldDefinitionError("workspace field-registry scope does not exist")
    if await workspace_dynamic_client_kb_is_erased(conn, workspace_id=workspace_id):
        raise WorkspaceDynamicClientKbErasedError(
            f"workspace {workspace_id!r} dynamic Client-KB has been erased"
        )


# --- the value_schema validator --------------------------------------------
# A deliberately small JSON-shape vocabulary — enough for the seed pack and typed payloads, with no
# extra dependency. Every accepted keyword is enforced at write time; accepting a constraint and
# silently ignoring it would make a policy-approved schema less restrictive than it appears.
_SCALAR_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_WORKSPACE_SCHEMA_MAX_BYTES = 65_536
_WORKSPACE_SCHEMA_MAX_DEPTH = 6
_WORKSPACE_SCHEMA_MAX_ITEMS = 256
_WORKSPACE_SCHEMA_MAX_STRING = 8_192
_COMMON_SCHEMA_KEYS = frozenset({"type", "enum"})
_TYPE_SCHEMA_KEYS = {
    "string": frozenset({"maxLength"}),
    "integer": frozenset({"minimum", "maximum"}),
    "number": frozenset({"minimum", "maximum"}),
    "boolean": frozenset(),
    "null": frozenset(),
    "array": frozenset({"maxItems", "items"}),
    "object": frozenset({"properties", "required", "additionalProperties"}),
}


def _is_json_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_workspace_schema(
    schema: Mapping[str, Any], *, path: str = "value_schema", depth: int = 0
) -> None:
    """Validate the bounded JSON-schema subset tenant-local fields may register."""

    if depth > _WORKSPACE_SCHEMA_MAX_DEPTH:
        raise WorkspaceFieldDefinitionError(f"{path}: schema nesting exceeds bounded depth")
    declared = schema.get("type")
    if declared not in {*_SCALAR_CHECKS, "object", "array"}:
        raise WorkspaceFieldDefinitionError(f"{path}: unsupported or missing schema type")
    unsupported = set(schema) - _COMMON_SCHEMA_KEYS - _TYPE_SCHEMA_KEYS[declared]
    if unsupported:
        raise WorkspaceFieldDefinitionError(
            f"{path}: unsupported schema keywords {sorted(unsupported)!r}"
        )
    enum = schema.get("enum")
    if "enum" in schema and (not isinstance(enum, list) or not enum or len(enum) > 128):
        raise WorkspaceFieldDefinitionError(f"{path}.enum must contain 1..128 values")
    if enum is not None:
        encoded_members = [serialize_value_json(member) for member in enum]
        if len(encoded_members) != len(set(encoded_members)):
            raise WorkspaceFieldDefinitionError(f"{path}.enum must not contain duplicates")
    if declared == "string":
        maximum = schema.get("maxLength")
        if "maxLength" in schema and (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= _WORKSPACE_SCHEMA_MAX_STRING
        ):
            raise WorkspaceFieldDefinitionError(
                f"{path}.maxLength must be in 1..{_WORKSPACE_SCHEMA_MAX_STRING}"
            )
        if enum is None and maximum is None:
            raise WorkspaceFieldDefinitionError(
                f"{path}: an open string requires maxLength in 1..{_WORKSPACE_SCHEMA_MAX_STRING}"
            )
    if declared in {"integer", "number"}:
        for keyword in ("minimum", "maximum"):
            bound = schema.get(keyword)
            if keyword in schema and (
                not _is_json_number(bound)
                or (isinstance(bound, float) and not math.isfinite(bound))
            ):
                raise WorkspaceFieldDefinitionError(
                    f"{path}.{keyword} must be a finite JSON number"
                )
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise WorkspaceFieldDefinitionError(f"{path}: minimum must not exceed maximum")
    if declared == "array":
        maximum = schema.get("maxItems")
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= _WORKSPACE_SCHEMA_MAX_ITEMS
        ):
            raise WorkspaceFieldDefinitionError(
                f"{path}: an array requires maxItems in 1..{_WORKSPACE_SCHEMA_MAX_ITEMS}"
            )
        items = schema.get("items")
        if not isinstance(items, dict):
            raise WorkspaceFieldDefinitionError(f"{path}: an array requires one items schema")
        _validate_workspace_schema(items, path=f"{path}.items", depth=depth + 1)
    if declared == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties or len(properties) > 64:
            raise WorkspaceFieldDefinitionError(
                f"{path}: object properties must contain 1..64 keys"
            )
        if schema.get("additionalProperties") is not False:
            raise WorkspaceFieldDefinitionError(
                f"{path}: bounded objects require additionalProperties=false"
            )
        required = schema.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(key, str) for key in required)
            or len(required) != len(set(required))
            or not set(required).issubset(properties)
        ):
            raise WorkspaceFieldDefinitionError(
                f"{path}.required must be unique property names declared by the object"
            )
        for key, child in properties.items():
            if not isinstance(key, str) or not key or not isinstance(child, dict):
                raise WorkspaceFieldDefinitionError(f"{path}: invalid object property schema")
            _validate_workspace_schema(child, path=f"{path}.{key}", depth=depth + 1)
    if enum is not None:
        for index, member in enumerate(enum):
            try:
                _validate_payload(member, schema, f"{path}.enum[{index}]")
            except ValueSchemaError as exc:
                raise WorkspaceFieldDefinitionError(str(exc)) from exc


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
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(schema.get("properties", {}))
            if unexpected:
                raise ValueSchemaError(f"{path}: unexpected keys {sorted(unexpected)!r}")
    elif declared == "array":
        if not isinstance(value, list):
            raise ValueSchemaError(f"{path}: expected array, got {type(value).__name__}")
        items = schema.get("items")
        if items is not None:
            for index, item in enumerate(value):
                _validate_payload(item, items, f"{path}[{index}]")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            raise ValueSchemaError(f"{path}: contains more than {schema['maxItems']} items")
    else:
        check = _SCALAR_CHECKS.get(declared)
        if check is None:
            raise ValueSchemaError(f"{path}: unknown schema type {declared!r}")
        if not check(value):
            raise ValueSchemaError(f"{path}: expected {declared}, got {type(value).__name__}")
        if declared in {"integer", "number"}:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueSchemaError(f"{path}: expected a finite {declared}")
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                raise ValueSchemaError(f"{path}: must be at least {minimum}")
            if maximum is not None and value > maximum:
                raise ValueSchemaError(f"{path}: must be at most {maximum}")
        if (
            declared == "string"
            and isinstance(schema.get("maxLength"), int)
            and len(value) > schema["maxLength"]
        ):
            raise ValueSchemaError(f"{path}: exceeds maxLength {schema['maxLength']}")


# --- row <-> FieldDef helpers ----------------------------------------------
_SELECT = (
    "field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, signal_class, "
    "reuse_scope, research_scope, product_scope, field_class, value_schema, corroboration_min, "
    "single_source_sufficient, equality_mode, description, active, pack, version, created_at"
)

_WORKSPACE_SELECT = (
    "w.field_key, w.value_type, w.validation, w.tier_plan, w.freshness_ttl, w.pass_kind, "
    "w.gate, w.signal_class, w.reuse_scope, w.research_scope, w.product_scope, w.field_class, "
    "w.value_schema, "
    "w.corroboration_min, w.single_source_sufficient, w.equality_mode, w.description, "
    "(w.active AND r.field_key IS NULL) AS active, w.pack, "
    "w.definition_version AS version, w.promoted_at AS created_at, w.workspace_id, "
    "w.client_kb_role, w.promoted_from_proposal_id, w.promotion_policy_version, w.promoted_by, "
    "w.label, w.presentation"
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
        research_scope=row["research_scope"],
        product_scope=row["product_scope"],
    )


def _row_to_resolved(
    row: Mapping[str, Any], *, origin: FieldRegistryOrigin
) -> ResolvedFieldDefinition:
    schema = decode_jsonb(row["value_schema"])
    return ResolvedFieldDefinition(
        field_def=_row_to_field_def(row),
        value_schema=dict(schema) if schema is not None else None,
        corroboration_min=row["corroboration_min"],
        single_source_sufficient=row["single_source_sufficient"],
        equality_mode=row["equality_mode"],
        description=row["description"],
        active=row["active"],
        pack=row["pack"],
        definition_version=row["version"],
        origin=origin,
        workspace_id=row.get("workspace_id"),
        client_kb_role=row.get("client_kb_role"),
        promoted_from_proposal_id=row.get("promoted_from_proposal_id"),
        promotion_policy_version=row.get("promotion_policy_version"),
        promoted_by=row.get("promoted_by"),
        created_at=row.get("created_at"),
        label=row.get("label"),
        presentation=row.get("presentation", "text"),
    )


def validate_workspace_field_schema(value_schema: Mapping[str, Any]) -> None:
    """Validate the bounded schema contract allowed for a tenant-local Client-KB field."""

    encoded_schema = serialize_value_json(value_schema)
    if len(encoded_schema.encode()) > _WORKSPACE_SCHEMA_MAX_BYTES:
        raise WorkspaceFieldDefinitionError("tenant-local field value_schema exceeds 65536 bytes")
    _validate_workspace_schema(value_schema)


def validate_value_against_schema(value_json: JsonValue, value_schema: Mapping[str, Any]) -> None:
    """Validate a candidate without requiring the field to be registered first."""

    _validate_payload(value_json, value_schema)


_INSERT = text(
    """
    INSERT INTO field_definition (
        field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, signal_class,
        reuse_scope, research_scope, product_scope, field_class, value_schema, corroboration_min,
        single_source_sufficient, equality_mode, description, active, pack, version
    ) VALUES (
        :field_key, :value_type, CAST(:validation AS jsonb), CAST(:tier_plan AS jsonb),
        :freshness_ttl, CAST(:pass_kind AS field_pass), :gate, :signal_class,
        CAST(:reuse_scope AS reuse_scope), :research_scope, :product_scope,
        CAST(:field_class AS field_class),
        CAST(:value_schema AS jsonb), :corroboration_min, :single_source_sufficient,
        CAST(:equality_mode AS equality_mode), :description, :active, :pack, :version
    )
    """
)

_WORKSPACE_INSERT = text(
    """
    INSERT INTO workspace_field_definition (
        workspace_id, field_key, value_type, validation, value_schema, tier_plan, freshness_ttl,
        pass_kind, gate, signal_class, reuse_scope, research_scope, product_scope, field_class,
        corroboration_min, single_source_sufficient, equality_mode, description, pack,
        client_kb_role, active, definition_version, promoted_from_proposal_id,
        promotion_policy_version, promoted_by
    ) VALUES (
        :workspace_id, :field_key, :value_type, CAST(:validation AS jsonb),
        CAST(:value_schema AS jsonb), CAST(:tier_plan AS jsonb), :freshness_ttl,
        CAST(:pass_kind AS field_pass), :gate, :signal_class,
        CAST(:reuse_scope AS reuse_scope), :research_scope, :product_scope,
        CAST(:field_class AS field_class),
        :corroboration_min, :single_source_sufficient, CAST(:equality_mode AS equality_mode),
        :description, :pack, :client_kb_role, :active, :definition_version,
        :promoted_from_proposal_id, :promotion_policy_version, :promoted_by
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


async def _get_workspace_row(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    include_retired: bool = False,
) -> Mapping[str, Any] | None:
    retired = "" if include_retired else "AND r.field_key IS NULL"
    result = await conn.execute(
        text(
            f"SELECT {_WORKSPACE_SELECT} FROM workspace_field_definition w "
            "LEFT JOIN workspace_field_retirement r "
            "ON r.workspace_id = w.workspace_id AND r.field_key = w.field_key "
            "WHERE w.workspace_id = :workspace_id AND w.field_key = :field_key "
            "AND NOT EXISTS (SELECT 1 FROM workspace_dynamic_client_kb_erasure e "
            "WHERE e.workspace_id = w.workspace_id) "
            f"{retired}"
        ),
        {"workspace_id": workspace_id, "field_key": field_key},
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
    research_scope: str | None,
    product_scope: str | None,
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
    contract: changing a field's declared data-class is a redefinition (bump the version), and so is
    ``research_scope`` — changing a field's species silently would change which project lens its
    live claims belong to and whether they may be reused across projects. The M9.2
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
        "research_scope": research_scope,
        "product_scope": product_scope,
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
        if field_def.research_scope is None and namespace != _CLIENT_NAMESPACE:
            raise ResearchScopeError(
                f"field_key {field_def.field_key!r} must declare a research_scope (a <pack>.* "
                "field has no ratified species default — set research_scope=project_neutral for a "
                "world-fact or project_relative for an ICP/campaign-relative value; FI-2 P3)"
            )
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
        research_scope=(
            field_def.research_scope.value if field_def.research_scope is not None else None
        ),
        product_scope=(
            field_def.product_scope.value if field_def.product_scope is not None else None
        ),
        field_class=field_class.value,
        value_schema=value_schema,
        corroboration_min=corroboration_min,
        single_source_sufficient=single_source_sufficient,
        equality_mode=equality_mode,
        description=description,
        active=active,
        pack=pack,
    )

    await _lock_field_registration(conn, field_def.field_key)
    if (
        await conn.execute(
            text("SELECT 1 FROM workspace_field_definition WHERE field_key = :key LIMIT 1"),
            {"key": field_def.field_key},
        )
    ).scalar_one_or_none() is not None:
        raise WorkspaceFieldDefinitionError("This key is reserved for workspace vocabulary.")
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
            research_scope=existing["research_scope"],
            product_scope=existing["product_scope"],
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
            "research_scope": (
                field_def.research_scope.value if field_def.research_scope is not None else None
            ),
            "product_scope": (
                field_def.product_scope.value if field_def.product_scope is not None else None
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


async def register_workspace_field(
    conn: AsyncConnection,
    field_def: FieldDef,
    *,
    workspace_id: str,
    promoted_from_proposal_id: UUID,
    promotion_policy_version: str,
    promoted_by: str,
    value_schema: Mapping[str, Any] | None = None,
    corroboration_min: int = 1,
    single_source_sufficient: bool = False,
    equality_mode: str = "exact",
    description: str | None = None,
    definition_version: int = 1,
) -> ResolvedFieldDefinition:
    """Register one immutable, tenant-local extended Client-KB field.

    The service forces every authority-bearing property instead of trusting the proposal payload:
    ``client.*`` namespace, ``pack=client``, ``tenant_private`` reuse, ``project_neutral`` species
    (a workspace's own dynamic Client-KB field is scoped to the workspace, not to a project — FI-2
    §5.2; the column is not CHECK-forced, so a declared-relative client field stays possible if the
    product ever needs one), extended-only role, and the owning workspace. A global collision is
    always refused; workspace rows never shadow platform vocabulary.
    """

    if not workspace_id:
        raise WorkspaceFieldDefinitionError("workspace field registration requires workspace_id")
    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    if not field_def.field_key.startswith("client."):
        raise WorkspaceFieldDefinitionError(
            "tenant-local Client-KB fields must use the client.* namespace"
        )
    if classify_field_key(field_def.field_key) is not FieldClass.PACK:
        raise WorkspaceFieldDefinitionError("tenant-local Client-KB fields must be pack fields")
    if field_def.reuse_scope is not ReuseScope.TENANT_PRIVATE:
        raise WorkspaceFieldDefinitionError(
            "tenant-local Client-KB fields must declare reuse_scope=tenant_private"
        )
    if value_schema is None:
        raise WorkspaceFieldDefinitionError("tenant-local Client-KB fields require value_schema")
    validate_workspace_field_schema(value_schema)
    await _lock_field_registration(conn, field_def.field_key)
    if await _get_row(conn, field_def.field_key) is not None:
        raise WorkspaceFieldDefinitionError(
            f"field_key {field_def.field_key!r} collides with platform-global vocabulary; "
            "propose a different workspace key"
        )

    incoming = _comparable(
        value_type=field_def.value_type,
        validation=field_def.validation,
        tier_plan=field_def.tier_plan,
        freshness_ttl=field_def.freshness_ttl,
        pass_kind=field_def.pass_kind.value,
        gate=field_def.gate,
        signal_class=field_def.signal_class,
        reuse_scope=ReuseScope.TENANT_PRIVATE.value,
        research_scope=ResearchScope.PROJECT_NEUTRAL.value,
        product_scope=ProductScopePolicy.FORBIDDEN.value,
        field_class=FieldClass.PACK.value,
        value_schema=value_schema,
        corroboration_min=corroboration_min,
        single_source_sufficient=single_source_sufficient,
        equality_mode=equality_mode,
        description=description,
        active=True,
        pack="client",
    )
    existing = await _get_workspace_row(
        conn, workspace_id=workspace_id, field_key=field_def.field_key, include_retired=True
    )
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
            research_scope=existing["research_scope"],
            product_scope=existing["product_scope"],
            field_class=existing["field_class"],
            value_schema=decode_jsonb(existing["value_schema"]),
            corroboration_min=existing["corroboration_min"],
            single_source_sufficient=existing["single_source_sufficient"],
            equality_mode=existing["equality_mode"],
            description=existing["description"],
            active=True,
            pack=existing["pack"],
        )
        if (
            current == incoming
            and existing["promoted_from_proposal_id"] == promoted_from_proposal_id
        ):
            return _row_to_resolved(existing, origin=FieldRegistryOrigin.WORKSPACE)
        raise FieldRedefinitionError(
            f"workspace field {workspace_id}/{field_def.field_key} is already registered; "
            "a material schema change requires a new field_key"
        )

    await conn.execute(
        _WORKSPACE_INSERT,
        {
            "workspace_id": workspace_id,
            "field_key": field_def.field_key,
            "value_type": field_def.value_type,
            "validation": (
                serialize_value_json(field_def.validation)
                if field_def.validation is not None
                else None
            ),
            "value_schema": (
                serialize_value_json(value_schema) if value_schema is not None else None
            ),
            "tier_plan": serialize_value_json(list(field_def.tier_plan)),
            "freshness_ttl": field_def.freshness_ttl,
            "pass_kind": field_def.pass_kind.value,
            "gate": field_def.gate,
            "signal_class": field_def.signal_class,
            "reuse_scope": ReuseScope.TENANT_PRIVATE.value,
            "research_scope": ResearchScope.PROJECT_NEUTRAL.value,
            "product_scope": ProductScopePolicy.FORBIDDEN.value,
            "field_class": FieldClass.PACK.value,
            "corroboration_min": corroboration_min,
            "single_source_sufficient": single_source_sufficient,
            "equality_mode": equality_mode,
            "description": description,
            "pack": "client",
            "client_kb_role": "extended",
            "active": True,
            "definition_version": definition_version,
            "promoted_from_proposal_id": promoted_from_proposal_id,
            "promotion_policy_version": promotion_policy_version,
            "promoted_by": promoted_by,
        },
    )
    created = await _get_workspace_row(
        conn, workspace_id=workspace_id, field_key=field_def.field_key
    )
    assert created is not None
    return _row_to_resolved(created, origin=FieldRegistryOrigin.WORKSPACE)


async def _lock_field_registration(conn: AsyncConnection, field_key: str) -> None:
    # Both global and workspace registration use this transaction lock, including absent keys.
    # No definition details from another workspace need to leave the substrate.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"field-registry:{field_key}"},
    )


async def _lock_workspace_field(
    conn: AsyncConnection, workspace_id: str, field_key: str, *, shared: bool = False
) -> bool:
    lock = "SHARE" if shared else "UPDATE"
    return (
        await conn.execute(
            text(
                "SELECT field_key FROM workspace_field_definition "
                "WHERE workspace_id = :ws AND field_key = :key FOR " + lock
            ),
            {"ws": workspace_id, "key": field_key},
        )
    ).scalar_one_or_none() is not None


def _research_text(value: str, *, label: bool) -> str:
    value = value.strip()
    limit = 200 if label else 2000
    if not value or len(value) > limit:
        name = "Name" if label else "Description"
        raise ResearchFieldInputError(f"{name} must contain 1–{limit} characters.")
    return value


def research_field_key(entity: str, label: str) -> str:
    if entity not in ("accounts", "contacts"):
        raise ResearchFieldInputError("Choose Accounts or Contacts.")
    slug = re.sub(r"[^a-z0-9]+", "_", _research_text(label, label=True).lower()).strip("_")
    if not slug:
        raise ResearchFieldInputError("Name must contain a letter or number.")
    return f"{entity[:-1]}.{slug}"


async def register_workspace_research_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity: str,
    label: str,
    description: str,
    created_by: str,
) -> ResolvedFieldDefinition:
    """Register a human's research instruction; the substrate owns all shape/scope properties."""
    if not created_by.startswith("human:") or not created_by.removeprefix("human:"):
        raise PermissionError("Research field creation requires human authority.")
    return await _register_research_field(
        conn,
        workspace_id=workspace_id,
        key=research_field_key(entity, label),
        label=label,
        description=description,
        created_by=created_by,
        policy="settings-v1",
    )


async def register_agent_research_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    run_id: str,
) -> ResolvedFieldDefinition:
    """A trusted research producer may propose neutral, tenant-local account/contact vocabulary.

    Field meaning must later be reviewed separately from any particular subject's observations.
    No model-supplied evidence or description enters either catalog through this path.
    """
    if not field_key.startswith(("account.", "contact.")) or not is_valid_field_key(field_key):
        raise WorkspaceFieldDefinitionError("Proposed research keys require account/contact scope")
    if not run_id:
        raise PermissionError("Research field proposal requires its producing run")
    await _lock_field_registration(conn, field_key)
    existing = await get_effective_field(
        conn, scope=FieldRegistryScope.for_workspace(workspace_id), field_key=field_key
    )
    if existing is not None:
        if not existing.active:
            raise WorkspaceFieldRetiredError("Research field is retired")
        return existing
    label = field_key.split(".", 1)[1].replace("_", " ").replace(".", " / ")
    return await _register_research_field(
        conn,
        workspace_id=workspace_id,
        key=field_key,
        label=label,
        description=f"Proposed research field: {label}. Meaning requires review; not evidence.",
        created_by=f"agent:{run_id}",
        policy="research-quality-v1",
    )


async def _register_research_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    key: str,
    label: str,
    description: str,
    created_by: str,
    policy: str,
) -> ResolvedFieldDefinition:
    label = _research_text(label, label=True)
    description = _research_text(description, label=False)
    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    await _lock_field_registration(conn, key)
    if await _get_row(conn, key) is not None:
        raise ResearchFieldKeyTaken(f"The platform field {key} already uses this name.")
    if (
        await _get_workspace_row(
            conn, workspace_id=workspace_id, field_key=key, include_retired=True
        )
        is not None
    ):
        raise ResearchFieldKeyTaken(
            "This name is already used, including retired fields. Add a qualifier."
        )
    await conn.execute(
        text("""
        INSERT INTO workspace_field_definition (
            workspace_id, field_key, value_type, pass_kind, field_class, pack,
            client_kb_role, promoted_from_proposal_id, promotion_policy_version,
            promoted_by, research_scope, product_scope, label, description
        ) VALUES (
            :ws, :key, 'json', 'deep', CAST(:kind AS field_class), NULL,
            'research', NULL, :policy, :by, 'project_neutral', 'forbidden',
            :label, :description
        )
    """),
        {
            "ws": workspace_id,
            "key": key,
            "kind": classify_field_key(key).value,
            "by": created_by,
            "policy": policy,
            "label": label,
            "description": description,
        },
    )
    row = await _get_workspace_row(conn, workspace_id=workspace_id, field_key=key)
    assert row is not None
    return _row_to_resolved(row, origin=FieldRegistryOrigin.WORKSPACE)


async def update_workspace_research_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    label: str | None = None,
    description: str | None = None,
) -> ResolvedFieldDefinition:
    """Only human-facing instruction text is mutable; key and claim shape never change."""
    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    await _lock_workspace_field(conn, workspace_id, field_key)
    row = await _get_workspace_row(conn, workspace_id=workspace_id, field_key=field_key)
    if row is None:
        raise WorkspaceFieldRetiredError("Research field is missing or retired.")
    if row["client_kb_role"] != "research":
        raise WorkspaceFieldDefinitionError("Only research field descriptions can be edited.")
    new_label = _research_text(label, label=True) if label is not None else row["label"]
    new_description = (
        _research_text(description, label=False) if description is not None else row["description"]
    )
    if (new_label, new_description) != (row["label"], row["description"]):
        await conn.execute(
            text("""
            UPDATE workspace_field_definition SET label=:label, description=:description,
                definition_version=definition_version+1
            WHERE workspace_id=:ws AND field_key=:key
        """),
            {
                "label": new_label,
                "description": new_description,
                "ws": workspace_id,
                "key": field_key,
            },
        )
    updated = await _get_workspace_row(conn, workspace_id=workspace_id, field_key=field_key)
    assert updated is not None
    return _row_to_resolved(updated, origin=FieldRegistryOrigin.WORKSPACE)


async def list_research_fields(
    conn: AsyncConnection, *, workspace_id: str, entity: Literal["accounts", "contacts"]
) -> tuple[ResolvedFieldDefinition, ...]:
    """The single research menu selection shared by Settings and account/person composition."""
    rows = await list_effective_fields(conn, scope=FieldRegistryScope.for_workspace(workspace_id))

    def selected(row: ResolvedFieldDefinition) -> bool:
        key = row.field_def.field_key
        if row.origin is FieldRegistryOrigin.WORKSPACE:
            return row.client_kb_role == "research" and key.startswith(f"{entity[:-1]}.")
        return (
            key.startswith(("account.", "core."))
            if entity == "accounts"
            else key.startswith("contact.") or key == "core.work_email"
        )

    return tuple(row for row in rows if selected(row))


async def retire_workspace_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    retired_by: str,
    reason: str,
) -> None:
    """Append one human governance retirement without rewriting the definition or its history."""

    if not retired_by.startswith("human:"):
        raise PermissionError("workspace field retirement requires human authority")
    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    await _lock_workspace_field(conn, workspace_id, field_key)
    existing = await _get_workspace_row(
        conn, workspace_id=workspace_id, field_key=field_key, include_retired=True
    )
    if existing is None:
        raise WorkspaceFieldRetiredError("workspace field not found")
    result = await conn.execute(
        text(
            "INSERT INTO workspace_field_retirement "
            "(workspace_id, field_key, retired_by, reason) "
            "VALUES (:workspace_id, :field_key, :retired_by, :reason) "
            "ON CONFLICT (workspace_id, field_key) DO NOTHING RETURNING field_key"
        ),
        {
            "workspace_id": workspace_id,
            "field_key": field_key,
            "retired_by": retired_by,
            "reason": reason,
        },
    )
    if result.scalar_one_or_none() is None:
        raise WorkspaceFieldRetiredError("workspace field is already retired")


async def get_field(conn: AsyncConnection, field_key: str) -> FieldDef | None:
    """Return a platform-global field, or ``None``.

    This is intentionally global-only compatibility for seed/pack and platform vocabulary paths.
    Tenant-aware business paths use :func:`get_effective_field` with trusted scope.
    """
    row = await _get_row(conn, field_key)
    return _row_to_field_def(row) if row is not None else None


async def get_workspace_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    include_retired: bool = False,
) -> ResolvedFieldDefinition | None:
    """Return exactly one workspace-owned field without falling back to global vocabulary."""

    row = await _get_workspace_row(
        conn,
        workspace_id=workspace_id,
        field_key=field_key,
        include_retired=include_retired,
    )
    return _row_to_resolved(row, origin=FieldRegistryOrigin.WORKSPACE) if row is not None else None


async def get_effective_field(
    conn: AsyncConnection,
    *,
    scope: FieldRegistryScope,
    field_key: str,
    include_retired: bool = False,
) -> ResolvedFieldDefinition | None:
    """Resolve workspace overlay then platform global, without cross-workspace disclosure."""

    if scope.workspace_id is not None:
        local = await get_workspace_field(
            conn,
            workspace_id=scope.workspace_id,
            field_key=field_key,
            include_retired=include_retired,
        )
        if local is not None:
            return local
    global_row = await _get_row(conn, field_key)
    return (
        _row_to_resolved(global_row, origin=FieldRegistryOrigin.GLOBAL)
        if global_row is not None
        else None
    )


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
    conn: AsyncConnection,
    field_key: str,
    *,
    scope: FieldRegistryScope | None = None,
) -> CorroborationConfig | None:
    """Return the :class:`CorroborationConfig` for ``field_key`` (the M9.2 corroborator's input), or
    ``None`` if the field is not registered. One small read of the corroboration columns — keeping
    the ``field_definition`` SQL in its owning module (the registry), as the merge layer's
    ``_freshness_ttl`` does for the TTL column."""
    definition = await get_effective_field(
        conn,
        scope=scope if scope is not None else FieldRegistryScope.global_only(),
        field_key=field_key,
    )
    if definition is None:
        return None
    return CorroborationConfig(
        corroboration_min=definition.corroboration_min,
        single_source_sufficient=definition.single_source_sufficient,
        equality_mode=definition.equality_mode,
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


async def list_effective_fields(
    conn: AsyncConnection,
    *,
    scope: FieldRegistryScope,
    filters: FieldFilters | None = None,
    include_retired: bool = False,
) -> tuple[ResolvedFieldDefinition, ...]:
    """List the deterministic global-plus-workspace registry visible in ``scope``.

    Workspace results carry origin metadata and never appear in global-only scope. A key collision
    is treated as corruption rather than silently choosing a meaning, even though the write service
    and migration both prevent that state.
    """

    selected = filters if filters is not None else FieldFilters()
    params = {
        "active": selected.active,
        "pass_kind": selected.pass_kind.value if selected.pass_kind is not None else None,
        "field_class": selected.field_class.value if selected.field_class is not None else None,
        "pack": selected.pack,
    }
    global_rows = (
        await conn.execute(
            text(
                f"""
                SELECT {_SELECT} FROM field_definition
                WHERE (CAST(:active AS boolean) IS NULL OR active = CAST(:active AS boolean))
                  AND (CAST(:pass_kind AS text) IS NULL
                       OR pass_kind = CAST(:pass_kind AS field_pass))
                  AND (CAST(:field_class AS text) IS NULL
                       OR field_class = CAST(:field_class AS field_class))
                  AND (CAST(:pack AS text) IS NULL OR pack = :pack)
                ORDER BY field_key
                """
            ),
            params,
        )
    ).mappings()
    resolved = [
        _row_to_resolved(dict(row), origin=FieldRegistryOrigin.GLOBAL) for row in global_rows.all()
    ]

    if scope.workspace_id is not None:
        active_expr = "(w.active AND r.field_key IS NULL)"
        retired_clause = "" if include_retired else "AND r.field_key IS NULL"
        local_rows = (
            await conn.execute(
                text(
                    f"""
                    SELECT {_WORKSPACE_SELECT}
                    FROM workspace_field_definition w
                    LEFT JOIN workspace_field_retirement r
                      ON r.workspace_id = w.workspace_id AND r.field_key = w.field_key
                    WHERE w.workspace_id = :workspace_id
                      AND NOT EXISTS (
                          SELECT 1 FROM workspace_dynamic_client_kb_erasure e
                          WHERE e.workspace_id = w.workspace_id
                      )
                      AND (CAST(:active AS boolean) IS NULL
                           OR {active_expr} = CAST(:active AS boolean))
                      AND (CAST(:pass_kind AS text) IS NULL
                           OR w.pass_kind = CAST(:pass_kind AS field_pass))
                      AND (CAST(:field_class AS text) IS NULL
                           OR w.field_class = CAST(:field_class AS field_class))
                      AND (CAST(:pack AS text) IS NULL OR w.pack = :pack)
                      {retired_clause}
                    ORDER BY w.field_key
                    """
                ),
                {**params, "workspace_id": scope.workspace_id},
            )
        ).mappings()
        locals_resolved = [
            _row_to_resolved(dict(row), origin=FieldRegistryOrigin.WORKSPACE)
            for row in local_rows.all()
        ]
        global_keys = {item.field_def.field_key for item in resolved}
        collision = next(
            (
                item.field_def.field_key
                for item in locals_resolved
                if item.field_def.field_key in global_keys
            ),
            None,
        )
        if collision is not None:
            raise WorkspaceFieldDefinitionError(
                f"workspace field {collision!r} shadows platform-global vocabulary"
            )
        resolved.extend(locals_resolved)

    return tuple(sorted(resolved, key=lambda item: item.field_def.field_key))


async def field_species(
    conn: AsyncConnection, *, workspace_id: str, field_keys: Sequence[str]
) -> dict[str, ResearchScope]:
    """Split ``field_keys`` by species, through the *effective* (global + workspace) registry.

    Always via :func:`~clue_core.resolve_research_scope`, never the raw
    ``field_definition.research_scope`` column: a global row may legitimately carry ``NULL`` and the
    ratified key rule decides (FI-2 slice-0 handoff).

    **Deactivated and retired declarations are included on purpose** (``active=None`` +
    ``include_retired``). Species is a property of the *declaration*, and a declaration outlives its
    activation: a field's live claims do not change meaning the moment the field stops being
    researched. The default active-only read would silently fold a deactivated
    ``project_relative`` pack field back to ``project_neutral`` and migrate its existing claims from
    a project section into ``neutralFacts`` — a bucket change with no data change, which is exactly
    the kind of silent drift the read layer must not produce, and the same reading the research
    economics must take when it decides whether a claim is the workspace's to borrow.

    A key with **no** registry row at all (its definition was deleted, not merely retired) falls
    back to :func:`~clue_core.default_research_scope`, the same ratified key rule
    ``resolve_research_scope`` applies to an undeclared field.

    Lives here, beside :func:`list_effective_fields`, because "is this field project-relative?" must
    have exactly one answer for four consumers that are otherwise unrelated: the FI-2 read layer's
    section routing, the account runtime's fresh-skip, the R5 execution guard, and the Sumble gap
    ladder. It was originally written in the read-layer module, which made a research-path module
    import a BFF module — the wrong direction, and the reason it moved.
    """
    if not field_keys:
        return {}
    registry = {
        item.field_def.field_key: resolve_research_scope(item.field_def)
        for item in await list_effective_fields(
            conn,
            scope=FieldRegistryScope.for_workspace(workspace_id),
            filters=FieldFilters(active=None),
            include_retired=True,
        )
    }
    return {
        key: registry.get(key, default_research_scope(classify_field_key(key), key))
        for key in field_keys
    }


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


async def validate_effective_value(
    conn: AsyncConnection,
    *,
    scope: FieldRegistryScope,
    field_key: FieldKey | str,
    value_json: JsonValue,
) -> ResolvedFieldDefinition:
    """Validate against the definition visible in trusted scope and return that definition."""

    resolved = await get_effective_field(conn, scope=scope, field_key=str(field_key))
    if resolved is None:
        raise UnknownFieldError(
            f"field_key {field_key!r} is not registered in the effective field registry"
        )
    if resolved.value_schema is not None:
        _validate_payload(value_json, resolved.value_schema)
    return resolved


async def check_claim_writable(
    conn: AsyncConnection,
    *,
    field_key: FieldKey | str,
    value_json: JsonValue,
    reuse_scope: ReuseScope,
    workspace_id: str | None,
    product_id: str | None,
) -> None:
    """The field-claim write gate — one registry lookup, three checks.

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
    3. **product binding** (FI context release closure R1) — a ``required`` field must carry a
       product id and a ``forbidden`` field must not. This shared boundary keeps company/product
       knowledge isolation independent of which resolver, interview path, or ingestion writer
       produced the claim. Violations raise :class:`ProductScopeError`.

    This is the unbypassable backstop: even if a caller forgets :func:`identity.stamp_reuse`, a
    private field cannot be written public through :func:`insert_claim`.
    """
    if reuse_scope is ReuseScope.TENANT_PRIVATE and workspace_id is None:
        raise ReuseScopeError(
            f"field_key {field_key!r} is being written tenant_private without workspace_id; "
            "refusing an unscoped private claim"
        )
    # Public claims can resolve only platform vocabulary. Private claims may use their workspace
    # overlay and then fall back to the same global vocabulary.
    scope = (
        FieldRegistryScope.for_workspace(workspace_id)
        if reuse_scope is ReuseScope.TENANT_PRIVATE and workspace_id is not None
        else FieldRegistryScope.global_only()
    )
    if scope.workspace_id is not None:
        # Preserve the existing global-claim API for historical scopes. A real workspace is
        # locked against erasure first, before its definition row, in the same order as editors.
        await conn.execute(
            text("SELECT workspace_id FROM workspace WHERE workspace_id=:ws FOR KEY SHARE"),
            {"ws": scope.workspace_id},
        )
        local = await _lock_workspace_field(conn, scope.workspace_id, str(field_key), shared=True)
        if (local or await _get_row(conn, str(field_key)) is None) and (
            await workspace_dynamic_client_kb_is_erased(conn, workspace_id=scope.workspace_id)
        ):
            raise WorkspaceDynamicClientKbErasedError("Workspace field access has been erased.")
        if (
            local
            and (
                await conn.execute(
                    text(
                        "SELECT 1 FROM workspace_field_retirement "
                        "WHERE workspace_id=:ws AND field_key=:key"
                    ),
                    {"ws": scope.workspace_id, "key": str(field_key)},
                )
            ).scalar_one_or_none()
            is not None
        ):
            raise WorkspaceFieldRetiredError("Research field is retired; new claims are refused.")
    definition = await validate_effective_value(
        conn, scope=scope, field_key=field_key, value_json=value_json
    )
    product_scope = resolve_product_scope(definition.field_def)
    if product_scope is ProductScopePolicy.REQUIRED and product_id is None:
        raise ProductScopeError(
            f"field_key {field_key!r} requires product_id; refusing a company-scoped write"
        )
    if product_scope is ProductScopePolicy.FORBIDDEN and product_id is not None:
        raise ProductScopeError(
            f"field_key {field_key!r} forbids product_id; refusing a product-scoped write"
        )
    declared_scope = resolve_reuse_scope(definition.field_def)
    if declared_scope is None:
        raise ReuseScopeError(
            f"field_key {field_key!r} has no resolvable reuse_scope (an undeclared <pack>.* "
            "field); declare its reuse_scope before writing claims — refusing to write a claim "
            "that cannot be tenant-classified (fail-closed; substrate §2 / ENG-165)"
        )
    if declared_scope is ReuseScope.TENANT_PRIVATE and reuse_scope is ReuseScope.PUBLIC_FOOTPRINT:
        raise ReuseScopeError(
            f"field_key {field_key!r} is declared tenant_private but the claim is stamped "
            "public_footprint — refusing the write (it would leak tenant-private data into the "
            "shared cross-tenant base). Stamp it via identity.stamp_reuse with the run's "
            "workspace_id "
            "(substrate §2 / ENG-165)"
        )
