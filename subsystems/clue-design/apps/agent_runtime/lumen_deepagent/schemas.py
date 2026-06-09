from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


JsonObject = Dict[str, Any]


class CritiqueCategory(str, Enum):
    hierarchy = "hierarchy"
    spacing = "spacing"
    alignment = "alignment"
    contrast = "contrast"
    clipping = "clipping"
    overflow = "overflow"
    brand_fit = "brand_fit"
    visual_balance = "visual_balance"
    semantic_slot_coverage = "semantic_slot_coverage"
    request_satisfaction = "request_satisfaction"
    compiler_repair = "compiler_repair"


class VisualTarget(BaseModel):
    page_id: Optional[str] = None
    node_id: Optional[str] = None
    slot_key: Optional[str] = None


class VisualIssue(BaseModel):
    severity: Literal["info", "warning", "error"] = "warning"
    category: CritiqueCategory
    target: Optional[VisualTarget] = None
    message: str
    suggested_repair: str


class VisualCritique(BaseModel):
    accepted: bool
    summary: str
    issues: List[VisualIssue] = Field(default_factory=list)
    repair_instruction: Optional[str] = None
    acceptance_notes: List[str] = Field(default_factory=list)


class KnowledgeSnippet(BaseModel):
    path: str
    title: str
    score: int
    excerpt: str


class PreviewArtifact(BaseModel):
    format: str
    mime_type: str
    page_id: Optional[str] = None
    byte_len: int
    text_path: Optional[str] = None


class LumenRunTraceEvent(BaseModel):
    run_id: str
    iteration: int
    actor: str
    event: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    diagnostics: List[JsonObject] = Field(default_factory=list)
    payload: JsonObject = Field(default_factory=dict)


def new_run_id() -> str:
    return f"run_{uuid4().hex}"
