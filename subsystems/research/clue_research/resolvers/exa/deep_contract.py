"""Pinned, transport-free Exa Search Deep wire contract for M8B A0.

This module deliberately performs no HTTP request and registers no resolver.  E0 consumes these
strict request and additive-tolerant response models when it replaces the legacy neural/highlights
adapter.  A successful response is accepted only when it carries a request id, reported dollar
cost, structured output, and field-level grounding for every non-null output field.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

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

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_FIELD_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


class ExaDeepFailureClass(StrEnum):
    RETRYABLE = "retryable"
    HARD = "hard"
    BUDGET = "budget"
    SPEND_UNKNOWN = "spend_unknown"


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

    query: NonEmptyStr
    search_type: Literal["deep", "deep-reasoning"] = Field(alias="type")
    num_results: int = Field(alias="numResults", ge=1, le=50)
    # Exa accepts this member only when it has 1-10 entries. ``None`` represents the zero-query
    # case and must be omitted (or serialized as the documented nullable value) by the transport;
    # an empty JSON array is not a valid wire request.
    additional_queries: tuple[NonEmptyStr, ...] | None = Field(
        default=None, alias="additionalQueries", min_length=1, max_length=10
    )
    system_prompt: NonEmptyStr = Field(alias="systemPrompt")
    output_schema: dict[str, JsonValue] = Field(alias="outputSchema")
    contents: dict[str, JsonValue]
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
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("outputSchema must be a closed object schema")
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties or len(properties) > 8:
            raise ValueError("outputSchema must contain between one and eight field properties")
        if any(not isinstance(key, str) or not _FIELD_KEY.fullmatch(key) for key in properties):
            raise ValueError("outputSchema properties must be registered-field-key shaped")
        required = schema.get("required")
        if not isinstance(required, list) or set(required) != set(properties):
            raise ValueError("outputSchema must require every requested field")
        if self.contents.get("text") is not True or "highlights" not in self.contents:
            raise ValueError("account-deep requests require contents.text and highlights")
        prompt = self.system_prompt.casefold()
        required_instructions = ("exact account", "source url", "leave the field null")
        if any(instruction not in prompt for instruction in required_instructions):
            raise ValueError("systemPrompt is missing target-lock or grounding instructions")
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


class ExaDeepOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    content: dict[str, JsonValue]
    grounding: tuple[ExaDeepGrounding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _every_non_null_field_is_grounded(self) -> ExaDeepOutput:
        if any(not _FIELD_KEY.fullmatch(key) for key in self.content):
            raise ValueError("output content keys must be registered-field-key shaped")
        grounded_fields = tuple(item.field.removeprefix("content.") for item in self.grounding)
        if any(not _FIELD_KEY.fullmatch(field) for field in grounded_fields):
            raise ValueError("grounding fields must be registered-field-key shaped")
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
    results: tuple[ExaDeepResult, ...] = Field(min_length=1)
    output: ExaDeepOutput
    cost_dollars: ExaDeepCostDollars = Field(alias="costDollars")

    @model_validator(mode="after")
    def _grounding_resolves_to_inspectable_results(self) -> ExaDeepSearchResponse:
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


__all__ = [
    "ExaDeepCitation",
    "ExaDeepCostDollars",
    "ExaDeepFailureClass",
    "ExaDeepGrounding",
    "ExaDeepOutput",
    "ExaDeepResult",
    "ExaDeepSearchRequest",
    "ExaDeepSearchResponse",
    "classify_exa_deep_http_failure",
    "validate_exa_deep_exchange",
]
