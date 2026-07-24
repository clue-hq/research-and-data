"""Phase-C ingestion policy shape.

The policy is injected into the engine.  Prompt/tool inputs cannot raise these ceilings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_INGESTION_MEDIA_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/tiff",
    }
)


class IngestionPolicy(BaseModel):
    """Absolute upload and execution ceilings for C3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    allowed_media_types: frozenset[str] = DEFAULT_INGESTION_MEDIA_TYPES
    max_segments: int = Field(default=2_000, ge=1)
    max_retries: int = Field(default=3, ge=0)
    ocr_enabled: bool = True


DEFAULT_INGESTION_POLICY = IngestionPolicy()
