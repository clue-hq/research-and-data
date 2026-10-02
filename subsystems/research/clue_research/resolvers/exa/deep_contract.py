"""Pinned, transport-free Exa Search Deep wire contract for M8B A0.

This module deliberately performs no HTTP request and registers no resolver.  E0 consumes these
strict request and additive-tolerant response models when it replaces the legacy neural/highlights
adapter.  A successful response is accepted only when it carries a request id, reported dollar
cost, structured output, and field-level grounding for every non-null output field.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import blake2s
from math import isfinite
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_core import EntityId, FieldKey, normalize_host

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BoundedQueryStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
BoundedPromptStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8000),
]
_FIELD_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_LEGACY_FIELD_ALIAS = re.compile(r"f_[0-9a-f]+")
_SHORT_FIELD_ALIAS = re.compile(r"k_[0-9a-v]{8}")
_PROMPT_FIELD_MAPPING = re.compile(
    r"(?<![A-Za-z0-9_])(f_[0-9a-f]+|k_[0-9a-v]{8})"
    r"=([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)(?![A-Za-z0-9_])"
)
_SAFE_NESTED_PROPERTY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

EXA_OUTPUT_MAX_PROPERTIES = 10
EXA_OUTPUT_MAX_DEPTH = 2
EXA_OUTPUT_MAX_FIELDS = 8
ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS = 10_000
_MAX_FIELD_ALIAS_CHARACTERS = 256
# One short alias is ``k_`` plus eight base32 digits of a 40-bit field-key digest.
_SHORT_ALIAS_DIGITS = 8
_SHORT_ALIAS_ALPHABET = "0123456789abcdefghijklmnopqrstuv"
EXA_FIELD_ALIAS_CHARACTERS = 2 + _SHORT_ALIAS_DIGITS
# 40 bits over at most eight bundle members never collides in practice; the salted retry keeps
# the assignment total and deterministic anyway rather than raising on an astronomical draw.
_MAX_ALIAS_COLLISION_SALTS = 64
_EXA_SCHEMA_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array"})
_COMMON_SCHEMA_KEYS = frozenset({"type", "enum", "description", "title"})
_TYPE_SCHEMA_KEYS: dict[str, frozenset[str]] = {
    "string": frozenset({"maxLength"}),
    "integer": frozenset({"minimum", "maximum"}),
    "number": frozenset({"minimum", "maximum"}),
    "boolean": frozenset(),
    "object": frozenset({"properties", "required", "additionalProperties"}),
    "array": frozenset({"items", "maxItems"}),
}


def normalize_exa_profile_url(value: str) -> str:
    """Canonicalize one professional-profile URL for exact target-lock comparison.

    Query strings and fragments are not identity.  The path is case-folded and trailing slashes
    are removed, matching the platform's strong-key comparison semantics without importing an
    identity or verification implementation into the provider package.
    """

    host = normalize_host(value)
    if not host:
        raise ValueError("contact target profile URL must contain a host")
    parsed = urlsplit(value)
    if parsed.hostname is None:
        parsed = urlsplit("//" + value)
    path = parsed.path.rstrip("/").casefold()
    if not path or path == "/":
        raise ValueError("contact target profile URL must identify one profile path")
    return urlunsplit(("https", host, path, "", ""))


class ExaDeepContactTargetLock(BaseModel):
    """Exact canonical person and employer context for one contact Search request.

    This value is not sent as an extra provider member.  The contact compiler renders it into the
    documented query/system-prompt fields and C4 will persist it beside the wire request.  Keeping
    the typed value available locally lets response normalization reject a same-name result even
    when the provider emitted schema-valid JSON.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    employer_account_id: EntityId
    canonical_full_name: NonEmptyStr
    canonical_profile_url: NonEmptyStr
    employer_name: NonEmptyStr
    employer_domain: NonEmptyStr
    current_title: NonEmptyStr | None = None
    job_function: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    approved_profile_hosts: tuple[NonEmptyStr, ...] = ("linkedin.com",)
    preferred_source_guidance: tuple[NonEmptyStr, ...] = (
        "the canonical professional profile",
        "official employer biographies and leadership pages",
        "primary publication, conference, podcast, or event pages",
    )
    forbidden_source_guidance: tuple[NonEmptyStr, ...] = (
        "people-search aggregators without inspectable primary evidence",
        "unattributed snippets",
        "email or phone enrichment",
    )
    start_published_date: datetime | None = None
    end_published_date: datetime | None = None

    @model_validator(mode="after")
    def _exact_person_and_employer_are_strong(self) -> ExaDeepContactTargetLock:
        canonical_profile = normalize_exa_profile_url(str(self.canonical_profile_url))
        profile_host = normalize_host(canonical_profile)
        approved_hosts = tuple(normalize_host(host) for host in self.approved_profile_hosts)
        if not approved_hosts or any(not host for host in approved_hosts):
            raise ValueError("contact target requires approved professional-profile hosts")
        if len(approved_hosts) != len(set(approved_hosts)):
            raise ValueError("approved professional-profile hosts must be unique")
        if profile_host not in set(approved_hosts):
            raise ValueError("contact target profile host is not approved by policy")
        employer_domain = normalize_host(self.employer_domain)
        if not employer_domain:
            raise ValueError("contact target requires a canonical employer domain")
        for label, values in (
            ("preferred source guidance", self.preferred_source_guidance),
            ("forbidden source guidance", self.forbidden_source_guidance),
        ):
            folded = tuple(value.casefold() for value in values)
            if len(folded) != len(set(folded)):
                raise ValueError(f"contact target {label} must be unique")
        if (
            self.start_published_date is not None
            and self.end_published_date is not None
            and self.start_published_date > self.end_published_date
        ):
            raise ValueError("contact target publication window is inverted")
        return self

    @property
    def normalized_profile_url(self) -> str:
        return normalize_exa_profile_url(str(self.canonical_profile_url))

    @property
    def normalized_employer_domain(self) -> str:
        return normalize_host(self.employer_domain)


def legacy_exa_field_alias(field_key: str) -> str:
    """Encode a registry key the frozen v1 way: ``f_`` plus the hex of the validated ASCII key.

    Production stopped compiling these because the provider must copy the property name verbatim
    into its structured answer, and a 50-80 character hex run is exactly the kind of meaningless
    token a generator drops or rewrites characters in. The encoding stays here because every
    persisted v1 request and retained response still names its fields this way, and replay,
    snapshot materialization, and the retained-response recovery path must keep resolving them.
    """

    if _FIELD_KEY.fullmatch(field_key) is None:
        raise ValueError(f"invalid registered field key {field_key!r}")
    alias = f"f_{field_key.encode('ascii').hex()}"
    if len(alias) > _MAX_FIELD_ALIAS_CHARACTERS:
        raise ValueError("registered field key is too long for the Exa provider alias contract")
    return alias


def _short_field_alias(field_key: str, *, salt: int) -> str:
    digest = blake2s(f"{salt}:{field_key}".encode("ascii"), digest_size=5).digest()
    number = int.from_bytes(digest, "big")
    digits: list[str] = []
    for _ in range(_SHORT_ALIAS_DIGITS):
        number, remainder = divmod(number, len(_SHORT_ALIAS_ALPHABET))
        digits.append(_SHORT_ALIAS_ALPHABET[remainder])
    return "k_" + "".join(reversed(digits))


def exa_field_alias(field_key: str) -> str:
    """The canonical short provider property name for one registry field key.

    Exa reports grounding names as field paths, so a dotted registry key cannot be sent literally.
    The wire contract therefore aliases it, and the alias is a fixed ten characters — a ``k_``
    prefix over eight base32 digits of a 40-bit digest — so the provider has a token it can copy
    exactly instead of a hex run whose length grew with the field name. The readable mapping is
    pinned in the system prompt, which is what makes the alias resolvable without a mutable table.

    This is the assignment for a field key considered alone. A request bundle must use
    :func:`exa_field_aliases`, which resolves the (vanishingly rare) in-bundle digest collision.
    """

    if _FIELD_KEY.fullmatch(field_key) is None:
        raise ValueError(f"invalid registered field key {field_key!r}")
    return _short_field_alias(field_key, salt=0)


def exa_field_aliases(field_keys: Iterable[str]) -> dict[FieldKey, str]:
    """Assign one collision-free short alias per field key of a single request bundle.

    Assignment walks the sorted key set, so the table depends only on the bundle's membership and
    never on the caller's ordering. A digest collision inside one bundle bumps a salt rather than
    failing the request; the loser of the draw is decided by that same sorted order, so recompiling
    or revalidating the bundle reproduces the identical table.
    """

    keys = tuple(str(field_key) for field_key in field_keys)
    if not keys:
        raise ValueError("an Exa request bundle must declare at least one field key")
    if len(set(keys)) != len(keys):
        raise ValueError("Exa request bundle field keys must be unique")
    assigned: dict[FieldKey, str] = {}
    taken: set[str] = set()
    for field_key in sorted(keys):
        if _FIELD_KEY.fullmatch(field_key) is None:
            raise ValueError(f"invalid registered field key {field_key!r}")
        for salt in range(_MAX_ALIAS_COLLISION_SALTS):
            alias = _short_field_alias(field_key, salt=salt)
            if alias not in taken:
                break
        else:  # pragma: no cover - unreachable below 2**40 distinct digests per bundle
            raise ValueError("Exa provider alias assignment could not be made collision-free")
        taken.add(alias)
        assigned[field_key] = alias
    return assigned


def validate_exa_field_alias(alias: str) -> None:
    """Fail closed on any property name that is not a canonical provider alias.

    A short alias carries no field key of its own, so only its shape can be checked here; the
    request's own declared table (:func:`exa_alias_field_keys`) is what binds it to a field. A
    legacy hex alias is still fully round-tripped, so no v1 strictness is lost.
    """

    if _SHORT_FIELD_ALIAS.fullmatch(alias) is not None:
        return
    field_key_from_exa_alias(alias)


def field_key_from_exa_alias(alias: str) -> FieldKey:
    """Decode and revalidate a legacy v1 alias; malformed or non-canonical aliases fail closed.

    A short v2 alias is deliberately refused here: it is resolvable only against the bundle that
    declared it, which is what :func:`exa_alias_field_keys` reads off the persisted request.
    """

    if _SHORT_FIELD_ALIAS.fullmatch(alias) is not None:
        raise ValueError(
            f"Exa field alias {alias!r} is a short bundle alias and resolves only through the "
            "declared alias table of the request that asked for it"
        )
    if (
        _LEGACY_FIELD_ALIAS.fullmatch(alias) is None
        or len(alias) > _MAX_FIELD_ALIAS_CHARACTERS
        or len(alias.removeprefix("f_")) % 2 != 0
    ):
        raise ValueError(f"invalid Exa field alias {alias!r}")
    try:
        field_key = bytes.fromhex(alias.removeprefix("f_")).decode("ascii")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid Exa field alias {alias!r}") from exc
    if _FIELD_KEY.fullmatch(field_key) is None or legacy_exa_field_alias(field_key) != alias:
        raise ValueError(f"invalid Exa field alias {alias!r}")
    return field_key


def exa_alias_field_keys(
    *,
    system_prompt: str,
    aliases: Iterable[str],
) -> dict[str, FieldKey]:
    """Recover the exact alias-to-field-key table one wire request declares.

    Every compiled request pins ``alias=field.key`` for each output member in its own system
    prompt, and construction proves that pin matches the output schema. That makes the persisted
    request self-describing under either alias generation: a v1 request is checked by decoding its
    hex aliases, and a v2 request is checked by recompiling its bundle assignment. Retained
    responses, snapshot replay, and the quarantined-response recovery path therefore read whichever
    generation the stored request actually asked for, and never the compiler's current one.
    """

    declared = tuple(str(alias) for alias in aliases)
    if not declared:
        raise ValueError("wire request must declare at least one provider field alias")
    if len(set(declared)) != len(declared):
        raise ValueError("wire request must declare unique provider field aliases")
    # A repeat of the *same* pin is not a contradiction — the prompt may embed untrusted prior
    # research context, and the frozen v1 validator compared a set of pairs. Only a second key for
    # one alias is a real conflict.
    table: dict[str, FieldKey] = {}
    for alias, field_key in _PROMPT_FIELD_MAPPING.findall(system_prompt):
        if table.setdefault(alias, field_key) != field_key:
            raise ValueError("systemPrompt maps one provider alias to two field keys")
    if set(table) != set(declared):
        raise ValueError("systemPrompt must contain exactly the provider-alias field mappings")
    if len(set(table.values())) != len(table):
        raise ValueError("systemPrompt maps two provider aliases to one field key")
    short = tuple(alias for alias in declared if _SHORT_FIELD_ALIAS.fullmatch(alias) is not None)
    if short and len(short) != len(declared):
        raise ValueError("one wire request cannot mix provider alias generations")
    if short:
        if exa_field_aliases(table.values()) != {key: alias for alias, key in table.items()}:
            raise ValueError("systemPrompt aliases are not this bundle's canonical assignment")
    else:
        for alias, field_key in table.items():
            if field_key_from_exa_alias(alias) != field_key:
                raise ValueError("systemPrompt maps a provider alias to a different field key")
    return {alias: table[alias] for alias in declared}


def _declared_schema_types(schema: Mapping[str, JsonValue], *, path: str) -> frozenset[str]:
    raw = schema.get("type")
    declared: tuple[str, ...]
    if isinstance(raw, str):
        declared = (raw,)
    elif isinstance(raw, list) and raw and all(isinstance(item, str) for item in raw):
        declared = tuple(cast(str, item) for item in raw)
    else:
        raise ValueError(f"{path}.type must be one type or a non-empty type list")
    if len(declared) != len(set(declared)):
        raise ValueError(f"{path}.type cannot contain duplicates")
    non_null = set(declared) - {"null"}
    if len(non_null) != 1 or not non_null.issubset(_EXA_SCHEMA_TYPES):
        raise ValueError(f"{path}.type must declare exactly one supported non-null type")
    if set(declared) - non_null - {"null"}:
        raise ValueError(f"{path}.type contains an unsupported type")
    return frozenset(declared)


def _validate_exa_schema_node(
    schema: Mapping[str, JsonValue],
    *,
    path: str,
    property_depth: int,
) -> int:
    declared = _declared_schema_types(schema, path=path)
    non_null_type = next(item for item in declared if item != "null")
    unsupported = set(schema) - _COMMON_SCHEMA_KEYS - _TYPE_SCHEMA_KEYS[non_null_type]
    if unsupported:
        raise ValueError(f"{path} contains unsupported schema keywords {sorted(unsupported)!r}")

    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            raise ValueError(f"{path}.enum must be a non-empty array")
        if "null" in declared and None not in enum:
            raise ValueError(f"{path}.enum must include null when the field is nullable")

    if non_null_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError(f"{path}.properties must be a non-empty object")
        additional = schema.get("additionalProperties")
        if additional not in (None, False):
            raise ValueError(f"{path}.additionalProperties must be false when present")
        required = schema.get("required", [])
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
            or not set(required).issubset(properties)
        ):
            raise ValueError(f"{path}.required must name unique declared properties")
        total = 0
        for name, child in properties.items():
            if not isinstance(name, str) or _SAFE_NESTED_PROPERTY.fullmatch(name) is None:
                raise ValueError(f"{path} contains a provider-unsafe property name {name!r}")
            if not isinstance(child, dict):
                raise ValueError(f"{path}.{name} must be a schema object")
            child_depth = property_depth + 1
            if child_depth > EXA_OUTPUT_MAX_DEPTH:
                raise ValueError(
                    f"{path}.{name} exceeds Exa's maximum output property depth "
                    f"{EXA_OUTPUT_MAX_DEPTH}"
                )
            total += 1 + _validate_exa_schema_node(
                child,
                path=f"{path}.{name}",
                property_depth=child_depth,
            )
        return total

    if non_null_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{path}.items must be one schema object")
        maximum = schema.get("maxItems")
        if maximum is not None and (
            not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1
        ):
            raise ValueError(f"{path}.maxItems must be a positive integer")
        return _validate_exa_schema_node(
            items,
            path=f"{path}.items",
            property_depth=property_depth,
        )

    if non_null_type == "string":
        maximum = schema.get("maxLength")
        if maximum is not None and (
            not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1
        ):
            raise ValueError(f"{path}.maxLength must be a positive integer")
    if non_null_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and (
            not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
        ):
            raise ValueError(f"{path}.minimum must be numeric")
        if maximum is not None and (
            not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
        ):
            raise ValueError(f"{path}.maximum must be numeric")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"{path}.minimum must not exceed maximum")
    return 0


def validate_exa_output_schema(schema: Mapping[str, JsonValue]) -> None:
    """Enforce Exa's documented two-level, ten-property structured-output budget."""

    unsupported_root = set(schema) - {
        "type",
        "properties",
        "required",
        "additionalProperties",
    }
    if unsupported_root:
        raise ValueError(
            f"outputSchema contains unsupported root keywords {sorted(unsupported_root)!r}"
        )
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("outputSchema must be a closed object schema")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("outputSchema must contain at least one provider field alias")
    if len(properties) > EXA_OUTPUT_MAX_FIELDS:
        raise ValueError(
            f"outputSchema must contain at most {EXA_OUTPUT_MAX_FIELDS} provider field aliases"
        )
    required = schema.get("required")
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or len(required) != len(set(required))
        or set(required) != set(properties)
    ):
        raise ValueError("outputSchema must require every provider field alias exactly once")

    total_properties = 0
    for alias, child in properties.items():
        if not isinstance(alias, str):
            raise ValueError("outputSchema property aliases must be strings")
        validate_exa_field_alias(alias)
        if not isinstance(child, dict):
            raise ValueError(f"outputSchema.{alias} must be a schema object")
        if "null" not in _declared_schema_types(
            child,
            path=f"outputSchema.properties.{alias}",
        ):
            raise ValueError(f"outputSchema.{alias} must admit null for an evidence miss")
        total_properties += 1 + _validate_exa_schema_node(
            child,
            path=f"outputSchema.properties.{alias}",
            property_depth=1,
        )
    if total_properties > EXA_OUTPUT_MAX_PROPERTIES:
        raise ValueError(
            "outputSchema exceeds Exa's maximum of "
            f"{EXA_OUTPUT_MAX_PROPERTIES} total properties ({total_properties})"
        )


def _enum_contains(enum: list[JsonValue], value: JsonValue) -> bool:
    """JSON-aware enum equality: booleans never alias integers, while 1 and 1.0 may agree."""

    for candidate in enum:
        if isinstance(candidate, bool) or isinstance(value, bool):
            if type(candidate) is type(value) and candidate == value:
                return True
            continue
        if candidate == value:
            return True
    return False


def validate_exa_output_value(
    value: JsonValue,
    schema: Mapping[str, JsonValue],
    *,
    path: str,
) -> None:
    """Validate one returned value against the exact provider-safe request-schema subset.

    E0-R1 already rejects schema keywords outside this subset. Keeping the matching value
    validator here means a provider cannot return a type/enum/range/shape that the registry did not
    admit and leave that mismatch for E2 to discover after a paid response has been materialized.
    """

    declared = _declared_schema_types(schema, path=path)
    if value is None:
        if "null" not in declared:
            raise ValueError(f"{path} does not admit null")
        enum = schema.get("enum")
        if isinstance(enum, list) and not _enum_contains(enum, value):
            raise ValueError(f"{path} is not one of the admitted enum values")
        return

    non_null_type = next(item for item in declared if item != "null")
    valid_type = False
    if non_null_type == "string":
        valid_type = isinstance(value, str)
    elif non_null_type == "integer":
        valid_type = isinstance(value, int) and not isinstance(value, bool)
        valid_type = valid_type or (
            isinstance(value, float) and isfinite(value) and value.is_integer()
        )
    elif non_null_type == "number":
        valid_type = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or isfinite(value))
        )
    elif non_null_type == "boolean":
        valid_type = isinstance(value, bool)
    elif non_null_type == "object":
        valid_type = isinstance(value, dict)
    elif non_null_type == "array":
        valid_type = isinstance(value, list)
    if not valid_type:
        raise ValueError(f"{path} is not a valid {non_null_type} value")

    enum = schema.get("enum")
    if isinstance(enum, list) and not _enum_contains(enum, value):
        raise ValueError(f"{path} is not one of the admitted enum values")

    if non_null_type == "string":
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(cast(str, value)) > maximum:
            raise ValueError(f"{path} exceeds maxLength={maximum}")
        return

    if non_null_type in {"integer", "number"}:
        number = cast(int | float, value)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and number < minimum:
            raise ValueError(f"{path} is below minimum={minimum}")
        if isinstance(maximum, (int, float)) and number > maximum:
            raise ValueError(f"{path} exceeds maximum={maximum}")
        return

    if non_null_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):  # independently safe after request-schema validation
            raise ValueError(f"{path}.items is not a schema object")
        array = cast(list[JsonValue], value)
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(array) > maximum:
            raise ValueError(f"{path} exceeds maxItems={maximum}")
        for index, item in enumerate(array):
            validate_exa_output_value(item, items, path=f"{path}[{index}]")
        return

    if non_null_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):  # independently safe after request-schema validation
            raise ValueError(f"{path}.properties is not an object")
        obj = cast(dict[str, JsonValue], value)
        required = schema.get("required", [])
        if not isinstance(required, list):  # independently safe after request-schema validation
            raise ValueError(f"{path}.required is not an array")
        missing = sorted(set(cast(list[str], required)) - set(obj))
        if missing:
            raise ValueError(f"{path} is missing required properties {missing!r}")
        extra = sorted(set(obj) - set(properties))
        if schema.get("additionalProperties") is False and extra:
            raise ValueError(f"{path} contains additional properties {extra!r}")
        for name, child_value in obj.items():
            child_schema = properties.get(name)
            if child_schema is None:
                continue
            if not isinstance(child_schema, dict):
                raise ValueError(f"{path}.{name} is not governed by a schema object")
            validate_exa_output_value(child_value, child_schema, path=f"{path}.{name}")


class ExaDeepFailureClass(StrEnum):
    RETRYABLE = "retryable"
    HARD = "hard"
    BUDGET = "budget"
    SPEND_UNKNOWN = "spend_unknown"


class ExaDeepFieldSpec(BaseModel):
    """One admitted effective-registry field and its exact value schema.

    A2 supplies directional text later; it never supplies schema members. E1 resolves these specs
    from the effective field registry before compiling a provider request. Keeping the schema
    beside the validated key makes E0 independent of database/directive implementation details and
    prevents a fallback to guesses from ``FieldDef.value_type``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value_schema: dict[str, JsonValue]

    @field_validator("value_schema")
    @classmethod
    def _requires_typed_registry_schema(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        schema_type = value.get("type")
        if isinstance(schema_type, str):
            return value
        if (
            isinstance(schema_type, list)
            and schema_type
            and all(isinstance(item, str) for item in schema_type)
        ):
            return value
        raise ValueError("effective field value_schema must declare a JSON schema type")


class ExaDeepTextOptions(BaseModel):
    """Bounded full-text retrieval options accepted by the current Search API."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    max_characters: int = Field(alias="maxCharacters", ge=1, le=ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS)


class ExaDeepHighlightOptions(BaseModel):
    """Bounded, query-guided highlight options with no deprecated sentence/count knobs."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    query: BoundedQueryStr
    max_characters: int = Field(alias="maxCharacters", ge=1, le=ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS)


class ExaDeepContents(BaseModel):
    """The exact content payload E0-R1 permits on account-profile Search calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: ExaDeepTextOptions
    highlights: ExaDeepHighlightOptions


def classify_exa_deep_http_failure(
    status_code: int | None,
    *,
    dispatched: bool,
) -> ExaDeepFailureClass:
    """Fail-safe A0 classification; a post-dispatch ambiguous response never claims zero spend."""

    if status_code is None:
        return ExaDeepFailureClass.SPEND_UNKNOWN if dispatched else ExaDeepFailureClass.RETRYABLE
    if status_code == 402:
        return ExaDeepFailureClass.BUDGET
    if status_code in {408, 425, 429} or 500 <= status_code <= 599:
        return ExaDeepFailureClass.SPEND_UNKNOWN if dispatched else ExaDeepFailureClass.RETRYABLE
    if 400 <= status_code <= 499:
        return ExaDeepFailureClass.HARD
    return ExaDeepFailureClass.SPEND_UNKNOWN if dispatched else ExaDeepFailureClass.HARD


class ExaDeepSearchRequest(BaseModel):
    """The accepted non-streaming account/contact-deep body sent to ``POST /search``."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    query: BoundedQueryStr
    search_type: Literal["deep", "deep-reasoning"] = Field(alias="type")
    num_results: int = Field(alias="numResults", ge=1, le=50)
    # Exa accepts this member only when it has 1-10 entries. ``None`` represents the zero-query
    # case and must be omitted (or serialized as the documented nullable value) by the transport;
    # an empty JSON array is not a valid wire request.
    additional_queries: tuple[BoundedQueryStr, ...] | None = Field(
        default=None, alias="additionalQueries", min_length=1, max_length=10
    )
    system_prompt: BoundedPromptStr = Field(alias="systemPrompt")
    output_schema: dict[str, JsonValue] = Field(alias="outputSchema")
    contents: ExaDeepContents
    stream: Literal[False] = False

    @field_validator("additional_queries")
    @classmethod
    def _unique_queries(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return value
        if len(value) != len(set(value)):
            raise ValueError("additionalQueries must be unique")
        return value

    @model_validator(mode="after")
    def _bounded_structured_target_lock(self) -> ExaDeepSearchRequest:
        schema = self.output_schema
        validate_exa_output_schema(schema)
        properties = schema.get("properties")
        if not isinstance(properties, dict):  # independently type-safe after the validator above
            raise ValueError("outputSchema properties must be an object")
        prompt = self.system_prompt.casefold()
        required_instructions = ("source url", "leave the field null")
        target_locked = "exact account" in prompt or (
            "exact person" in prompt and "exact employer" in prompt
        )
        if not target_locked or any(
            instruction not in prompt for instruction in required_instructions
        ):
            raise ValueError("systemPrompt is missing target-lock or grounding instructions")
        exa_alias_field_keys(system_prompt=self.system_prompt, aliases=properties)
        return self

    @property
    def field_key_by_alias(self) -> dict[str, FieldKey]:
        """This request's own alias table, in output-schema property order.

        Everything that reads a response — exchange validation, normalization, snapshot replay,
        governed field partitioning — resolves aliases through here rather than through a global
        decoder, so a request compiled under the legacy hex generation keeps resolving after the
        compiler moved to short aliases.
        """

        properties = self.output_schema.get("properties")
        if not isinstance(properties, dict):  # independently safe after construction
            raise ValueError("outputSchema properties must be an object")
        return exa_alias_field_keys(system_prompt=self.system_prompt, aliases=properties)


class ExaDeepContactSearchRequest(ExaDeepSearchRequest):
    """Additive contact wire variant with the documented publication-date filters."""

    start_published_date: datetime | None = Field(default=None, alias="startPublishedDate")
    end_published_date: datetime | None = Field(default=None, alias="endPublishedDate")

    @model_validator(mode="after")
    def _published_window_is_ordered(self) -> ExaDeepContactSearchRequest:
        if (
            self.start_published_date is not None
            and self.end_published_date is not None
            and self.start_published_date > self.end_published_date
        ):
            raise ValueError("published-date filter window is inverted")
        return self


class ExaDeepCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    url: HttpUrl
    title: NonEmptyStr


class ExaDeepGrounding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    field: NonEmptyStr
    citations: tuple[ExaDeepCitation, ...] = Field(min_length=1)
    # Some responses may add a confidence label, but it is not part of the documented required
    # grounding shape and therefore cannot be required for settlement.
    confidence: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _citation_urls_are_unique(self) -> ExaDeepGrounding:
        urls = tuple(str(citation.url) for citation in self.citations)
        if len(urls) != len(set(urls)):
            raise ValueError("one field grounding cannot repeat a citation URL")
        return self


class ExaDeepOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    content: dict[str, JsonValue]
    # A paid all-null response is a valid hard miss and may contain no grounding rows. The model
    # validator below still requires every non-null field to have exactly one grounding row.
    grounding: tuple[ExaDeepGrounding, ...] = ()

    @model_validator(mode="after")
    def _every_non_null_field_is_grounded(self) -> ExaDeepOutput:
        try:
            for key in self.content:
                validate_exa_field_alias(key)
        except ValueError as exc:
            raise ValueError("output content keys must be canonical Exa field aliases") from exc
        grounded_fields = tuple(item.field.removeprefix("content.") for item in self.grounding)
        try:
            for field in grounded_fields:
                validate_exa_field_alias(field)
        except ValueError as exc:
            raise ValueError("grounding fields must be canonical Exa field aliases") from exc
        if len(grounded_fields) != len(set(grounded_fields)):
            raise ValueError("grounding cannot repeat a field")
        unknown = sorted(set(grounded_fields) - set(self.content))
        if unknown:
            raise ValueError(f"grounding names fields absent from output content: {unknown}")
        grounded = set(grounded_fields)
        missing = sorted(
            key for key, value in self.content.items() if value is not None and key not in grounded
        )
        if missing:
            raise ValueError(f"non-null output fields lack grounding: {missing}")
        return self


class ExaDeepResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    title: NonEmptyStr
    url: HttpUrl
    text: str | None = None
    highlights: tuple[str, ...] = ()


class ExaDeepCostDollars(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    total: Decimal = Field(ge=0)


class ExaDeepSearchResponse(BaseModel):
    """A successful, settleable structured response retained as the immutable raw snapshot."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    request_id: NonEmptyStr = Field(alias="requestId")
    results: tuple[ExaDeepResult, ...] = ()
    output: ExaDeepOutput
    cost_dollars: ExaDeepCostDollars = Field(alias="costDollars")

    @model_validator(mode="after")
    def _grounding_resolves_to_inspectable_results(self) -> ExaDeepSearchResponse:
        all_null = all(value is None for value in self.output.content.values())
        if not self.results and (not all_null or self.output.grounding):
            raise ValueError("results may be empty only for an all-null response without grounding")
        urls = tuple(str(result.url) for result in self.results)
        if len(urls) != len(set(urls)):
            raise ValueError("successful response cannot repeat a retained result URL")
        result_by_url = {str(result.url): result for result in self.results}
        for grounding in self.output.grounding:
            for citation in grounding.citations:
                result = result_by_url.get(str(citation.url))
                if result is None:
                    raise ValueError(
                        f"grounding citation {citation.url} has no matching retained result"
                    )
                has_text = result.text is not None and bool(result.text.strip())
                has_highlight = any(highlight.strip() for highlight in result.highlights)
                if not (has_text or has_highlight):
                    raise ValueError(
                        f"grounding citation {citation.url} has no inspectable text or highlight"
                    )
        return self


def validate_exa_deep_exchange(
    request: ExaDeepSearchRequest,
    response: ExaDeepSearchResponse,
) -> None:
    """Prove a successful response answers exactly the request's bounded field schema."""

    properties = request.output_schema.get("properties")
    # Construction already enforces this shape; retaining the guard here makes the exchange
    # validator independently type-safe if the model's internals are ever changed.
    if not isinstance(properties, dict):
        raise ValueError("request outputSchema properties are not an object")
    expected = set(properties)
    returned = set(response.output.content)
    if returned != expected:
        raise ValueError(
            "structured output fields do not match the request schema "
            f"(missing={sorted(expected - returned)}, extra={sorted(returned - expected)})"
        )
    field_key_by_alias = request.field_key_by_alias
    for alias, value in response.output.content.items():
        field_schema = properties[alias]
        if not isinstance(field_schema, dict):  # independently safe after request validation
            raise ValueError(f"request schema for {alias!r} is not an object")
        try:
            validate_exa_output_value(
                value,
                field_schema,
                path=f"output.content.{alias}",
            )
        except ValueError as exc:
            raise ValueError(
                f"structured output value for {field_key_by_alias[alias]!r} "
                f"violates its admitted registry schema: {exc}"
            ) from exc


__all__ = [
    "ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS",
    "EXA_FIELD_ALIAS_CHARACTERS",
    "EXA_OUTPUT_MAX_DEPTH",
    "EXA_OUTPUT_MAX_FIELDS",
    "EXA_OUTPUT_MAX_PROPERTIES",
    "ExaDeepCitation",
    "ExaDeepContactTargetLock",
    "ExaDeepContactSearchRequest",
    "ExaDeepContents",
    "ExaDeepCostDollars",
    "ExaDeepFieldSpec",
    "ExaDeepFailureClass",
    "ExaDeepGrounding",
    "ExaDeepHighlightOptions",
    "ExaDeepOutput",
    "ExaDeepResult",
    "ExaDeepSearchRequest",
    "ExaDeepSearchResponse",
    "ExaDeepTextOptions",
    "classify_exa_deep_http_failure",
    "exa_alias_field_keys",
    "exa_field_alias",
    "exa_field_aliases",
    "field_key_from_exa_alias",
    "legacy_exa_field_alias",
    "normalize_exa_profile_url",
    "validate_exa_deep_exchange",
    "validate_exa_field_alias",
    "validate_exa_output_schema",
    "validate_exa_output_value",
]
