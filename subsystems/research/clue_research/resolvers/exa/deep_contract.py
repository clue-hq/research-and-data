"""Pinned, transport-free Exa Search Deep wire contract for M8B A0.

This module deliberately performs no HTTP request and registers no resolver.  E0 consumes these
strict request and additive-tolerant response models when it replaces the legacy neural/highlights
adapter.  A successful response is accepted only when it carries a request id, reported dollar
cost, structured output, and field-level grounding for every non-null output field.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal, cast

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

from clue_core import FieldKey

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
_FIELD_ALIAS = re.compile(r"f_[0-9a-f]+")
_PROMPT_FIELD_MAPPING = re.compile(
    r"(?<![A-Za-z0-9_])(f_[0-9a-f]+)=([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)(?![A-Za-z0-9_])"
)
_SAFE_NESTED_PROPERTY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

EXA_OUTPUT_MAX_PROPERTIES = 10
EXA_OUTPUT_MAX_DEPTH = 2
EXA_OUTPUT_MAX_FIELDS = 8
ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS = 10_000
_MAX_FIELD_ALIAS_CHARACTERS = 256
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


def exa_field_alias(field_key: str) -> str:
    """Encode a registry key into one reversible, field-path-safe provider property name.

    Exa reports grounding names as field paths. Sending a dotted registry key directly would make
    a literal property indistinguishable from a nested path, so the wire contract hex-encodes the
    validated ASCII key behind an ``f_`` prefix. The compiler also pins the readable mapping in the
    system prompt; E1 can persist the request without a separate mutable alias table.
    """

    if _FIELD_KEY.fullmatch(field_key) is None:
        raise ValueError(f"invalid registered field key {field_key!r}")
    alias = f"f_{field_key.encode('ascii').hex()}"
    if len(alias) > _MAX_FIELD_ALIAS_CHARACTERS:
        raise ValueError("registered field key is too long for the Exa provider alias contract")
    return alias


def field_key_from_exa_alias(alias: str) -> FieldKey:
    """Decode and revalidate a provider alias; malformed or non-canonical aliases fail closed."""

    if (
        _FIELD_ALIAS.fullmatch(alias) is None
        or len(alias) > _MAX_FIELD_ALIAS_CHARACTERS
        or len(alias.removeprefix("f_")) % 2 != 0
    ):
        raise ValueError(f"invalid Exa field alias {alias!r}")
    try:
        field_key = bytes.fromhex(alias.removeprefix("f_")).decode("ascii")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid Exa field alias {alias!r}") from exc
    if _FIELD_KEY.fullmatch(field_key) is None or exa_field_alias(field_key) != alias:
        raise ValueError(f"invalid Exa field alias {alias!r}")
    return field_key


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
        field_key_from_exa_alias(alias)
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
    """The accepted non-streaming account-deep request body sent to ``POST /search``."""

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
        required_instructions = ("exact account", "source url", "leave the field null")
        if any(instruction not in prompt for instruction in required_instructions):
            raise ValueError("systemPrompt is missing target-lock or grounding instructions")
        expected_mappings = {(alias, field_key_from_exa_alias(alias)) for alias in properties}
        prompt_mappings = set(_PROMPT_FIELD_MAPPING.findall(self.system_prompt))
        if prompt_mappings != expected_mappings:
            raise ValueError("systemPrompt must contain exactly the provider-alias field mappings")
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
                field_key_from_exa_alias(key)
        except ValueError as exc:
            raise ValueError("output content keys must be canonical Exa field aliases") from exc
        grounded_fields = tuple(item.field.removeprefix("content.") for item in self.grounding)
        try:
            for field in grounded_fields:
                field_key_from_exa_alias(field)
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
                f"structured output value for {field_key_from_exa_alias(alias)!r} "
                f"violates its admitted registry schema: {exc}"
            ) from exc


__all__ = [
    "ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS",
    "EXA_OUTPUT_MAX_DEPTH",
    "EXA_OUTPUT_MAX_FIELDS",
    "EXA_OUTPUT_MAX_PROPERTIES",
    "ExaDeepCitation",
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
    "exa_field_alias",
    "field_key_from_exa_alias",
    "validate_exa_deep_exchange",
    "validate_exa_output_schema",
    "validate_exa_output_value",
]
