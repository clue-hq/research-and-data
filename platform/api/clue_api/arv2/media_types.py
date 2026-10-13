"""Versioned media contracts; offsets always index canonical Unicode code points."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Segment(MediaModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    speaker: str | None = None
    entity_id: UUID | None = None
    attribution: Literal["unknown", "metadata", "model_inferred", "evidence_backed", "conflict"] = (
        "unknown"
    )
    attribution_evidence: str | None = None
    time_s: float | None = Field(None, ge=0)
    end_time_s: float | None = Field(None, ge=0)
    timing: Literal["unavailable", "model_estimated", "source_supplied", "aligned"] = "unavailable"

    @model_validator(mode="after")
    def valid_span(self) -> Segment:
        if self.end <= self.start:
            raise ValueError("end must follow start")
        if (self.time_s is None) != (self.timing == "unavailable"):
            raise ValueError("timing provenance and timestamp disagree")
        if self.attribution == "evidence_backed" and not (
            self.entity_id and self.attribution_evidence
        ):
            raise ValueError("a speaker label alone is not identity evidence")
        return self


class Quality(MediaModel):
    coverage: Literal["full", "partial", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    finish_reason: str | None = None
    loop_report: dict[str, int | float | bool | None] = Field(default_factory=dict)


class TranscriptSource(MediaModel):
    kind: Literal["transcript_ref"] = "transcript_ref"
    version_ref: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_span(self) -> TranscriptSource:
        if self.end <= self.start or self.end - self.start > 60_000:
            raise ValueError(
                "transcript source must be a nonempty span of at most 60000 characters"
            )
        return self


class Candidate(MediaModel):
    url: str
    title: str = ""
    description: str = ""
    family: Literal["youtube", "feed", "page", "audio", "video", "transcript"] = "page"
    canonical_key: str | None = None
    duration_s: int | None = Field(None, gt=0)
    feed_url: str | None = None
    episode_id: str | None = None
    media_url: str | None = None
    transcript_url: str | None = None
    identity_evidence: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    recognized_subject_urls: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    transcript_type: str | None = None


class EmbeddingContract(MediaModel):
    model: str
    dimensions: int = Field(gt=0)
    route: str = "openrouter/embeddings"
    format: str = "retrieval-prefix-v1"
    normalization: str = "unit-l2-v1"
    chunker: str = "paragraph-word-offsets-v1"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def canonical_text(value: str) -> str:
    """newline-v1: no whitespace/Unicode normalization that could change quoted words."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
