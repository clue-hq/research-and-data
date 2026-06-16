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
    page_dimensions = "page_dimensions"
    typography = "typography"
    brand_fit = "brand_fit"
    asset_use = "asset_use"
    visual_balance = "visual_balance"
    semantic_slot_coverage = "semantic_slot_coverage"
    request_satisfaction = "request_satisfaction"
    compiler_repair = "compiler_repair"
    tool_failure = "tool_failure"


class DiagnosticSeverity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"
    blocker = "blocker"


class VisualTarget(BaseModel):
    page_id: Optional[str] = None
    node_id: Optional[str] = None
    slot_key: Optional[str] = None


class VisualIssue(BaseModel):
    severity: DiagnosticSeverity = DiagnosticSeverity.warning
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
    requirement_coverage_notes: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class KnowledgeSnippet(BaseModel):
    path: str
    title: str
    score: int
    excerpt: str
    category: str = "reference"
    selected_reason: str = "keyword_match"


class DiagnosticSummary(BaseModel):
    severity: DiagnosticSeverity = DiagnosticSeverity.info
    code: Optional[str] = None
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    target_page_id: Optional[str] = None
    target_node_id: Optional[str] = None
    target_slot_id: Optional[str] = None
    target_slot_key: Optional[str] = None
    suggested_repair: Optional[str] = None


class ToolStatus(str, Enum):
    ok = "ok"
    error = "error"


class PreviewArtifact(BaseModel):
    format: str
    mime_type: str
    page_id: Optional[str] = None
    byte_len: int
    path: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    aspect_ratio: Optional[float] = None
    critic_input_path: Optional[str] = None
    valid: bool = True
    validation_errors: List[str] = Field(default_factory=list)


class KnowledgeLoadResult(BaseModel):
    status: ToolStatus = ToolStatus.ok
    query: str
    snippets: List[KnowledgeSnippet] = Field(default_factory=list)


class CompileSummary(BaseModel):
    status: ToolStatus = ToolStatus.ok
    applied_operations: int = 0
    operation_count: int = 0
    diagnostics: List[DiagnosticSummary] = Field(default_factory=list)
    halted_at: Optional[JsonObject] = None
    operation_error: Optional[JsonObject] = None


class CompileRepairContext(BaseModel):
    reason: str
    compile_summary: CompileSummary
    failing_source: Optional[str] = None
    exact_feedback: Optional[str] = None


class OperationApplicationSummary(BaseModel):
    status: ToolStatus = ToolStatus.ok
    applied_operations: int = 0
    diagnostics: List[DiagnosticSummary] = Field(default_factory=list)
    operation_error: Optional[JsonObject] = None


class PreflightSummary(BaseModel):
    status: ToolStatus = ToolStatus.ok
    has_errors: bool = False
    diagnostics: List[DiagnosticSummary] = Field(default_factory=list)
    brand_source: Optional[str] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[str] = None
    brand_mode: Optional[JsonObject] = None


class ExportSummary(BaseModel):
    status: ToolStatus = ToolStatus.ok
    requested_format: str
    diagnostics: List[DiagnosticSummary] = Field(default_factory=list)
    artifacts: List[PreviewArtifact] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)


class PreviewTarget(BaseModel):
    page_id: Optional[str] = None
    region_id: Optional[str] = None
    requested_width: Optional[float] = None
    requested_height: Optional[float] = None
    requested_aspect_ratio: Optional[float] = None
    purpose: str = "visual_critique"


class AgentActionMode(str, Enum):
    new_artifact = "new_artifact"
    full_page_rewrite = "full_page_rewrite"
    replace_artboard_subtree = "replace_artboard_subtree"
    layout_cluster_rewrite = "layout_cluster_rewrite"
    targeted_patch = "targeted_patch"
    accept = "accept"
    stop_with_gap = "stop_with_gap"


class AgentDirectorDecision(BaseModel):
    action_mode: AgentActionMode
    rationale: str
    target: Optional[VisualTarget] = None
    allowed_scope: JsonObject = Field(default_factory=dict)
    instructions_to_author: str = ""
    uses_full_context: bool = True


class AuthoringBlockRequest(BaseModel):
    iteration: int
    user_request: str
    preview_target: Optional[PreviewTarget] = None
    knowledge_paths: List[str] = Field(default_factory=list)
    knowledge_snippets: List[KnowledgeSnippet] = Field(default_factory=list)
    current_scene_summary: JsonObject = Field(default_factory=dict)
    repair_context: Optional[JsonObject] = None
    full_context: JsonObject = Field(default_factory=dict)
    director_decision: Optional[AgentDirectorDecision] = None


class AuthoringBlockResult(BaseModel):
    iteration: int
    source: str
    compile_summary: Optional[CompileSummary] = None


class QualityGateResult(BaseModel):
    accepted: bool
    stop_reason: Optional["StopReason"] = None
    critique: Optional[VisualCritique] = None
    export_summary: Optional[ExportSummary] = None


class EditSurfaceRecommendation(str, Enum):
    dsl = "dsl"
    structured_ops = "structured_ops"
    asset_tool = "asset_tool"
    external_planner = "external_planner"


class RepairClass(str, Enum):
    syntax_continuation = "syntax_continuation"
    targeted_node = "targeted_node"
    layout_cluster = "layout_cluster"
    slot_fixture = "slot_fixture"
    brand_token = "brand_token"
    asset_tool = "asset_tool"
    unsupported_gap = "unsupported_gap"


class LayoutClusterTarget(BaseModel):
    page_id: Optional[str] = None
    root_frame_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    descendant_node_ids: List[str] = Field(default_factory=list)
    background_node_id: Optional[str] = None
    diagnostic_codes: List[str] = Field(default_factory=list)


class RepairClassification(BaseModel):
    repair_class: RepairClass
    target: Optional[VisualTarget] = None
    cluster: Optional[LayoutClusterTarget] = None
    allowed_edit_surface: EditSurfaceRecommendation
    permissions: List[str] = Field(default_factory=list)
    prohibitions: List[str] = Field(default_factory=list)
    reason: str


class StopReason(str, Enum):
    accepted = "accepted"
    compile_failed = "compile_failed"
    preflight_failed = "preflight_failed"
    export_failed = "export_failed"
    preview_invalid = "preview_invalid"
    critic_failed = "critic_failed"
    reviewer_rejected = "reviewer_rejected"
    max_iterations_reached = "max_iterations_reached"
    unsupported_capability = "unsupported_capability"
    tool_failed = "tool_failed"


class RepairRequest(BaseModel):
    original_user_request: str
    exact_feedback: str
    diagnostics: List[DiagnosticSummary] = Field(default_factory=list)
    target: Optional[VisualTarget] = None
    repair_class: Optional[RepairClass] = None
    cluster: Optional[LayoutClusterTarget] = None
    scene_summary: JsonObject = Field(default_factory=dict)
    allowed_edit_surface: EditSurfaceRecommendation
    permissions: List[str] = Field(default_factory=list)
    prohibitions: List[str] = Field(default_factory=list)
    forbidden_changes: List[str] = Field(default_factory=list)


class GapArea(str, Enum):
    agent_protocol = "agent_protocol"
    knowledge_loading = "knowledge_loading"
    dsl_edit_language = "dsl_edit_language"
    layout = "layout"
    text_typography = "text_typography"
    design_system = "design_system"
    rendering_export_preview = "rendering_export_preview"
    assets = "assets"
    scene_model = "scene_model"
    model_provider = "model_provider"


class GapRecord(BaseModel):
    area: GapArea
    summary: str
    evidence: str
    suggested_phase: Optional[str] = None


class AgentIteration(BaseModel):
    index: int
    dsl_source: Optional[str] = None
    compile_summary: Optional[CompileSummary] = None
    preflight_summary: Optional[PreflightSummary] = None
    export_summary: Optional[ExportSummary] = None
    critique: Optional[VisualCritique] = None
    repair_request: Optional[RepairRequest] = None
    stop_reason: Optional[StopReason] = None


class AgentRunState(BaseModel):
    run_id: str
    user_request: str
    status: Literal["running", "accepted", "completed_with_warnings", "failed"] = "running"
    iterations: List[AgentIteration] = Field(default_factory=list)
    loaded_knowledge: List[KnowledgeSnippet] = Field(default_factory=list)
    effective_brand: Optional[JsonObject] = None
    current_iteration: int = 0
    stop_reason: Optional[StopReason] = None
    gaps: List[GapRecord] = Field(default_factory=list)


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
