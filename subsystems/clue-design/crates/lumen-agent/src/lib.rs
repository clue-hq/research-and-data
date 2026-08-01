//! Deterministic agent-loop contracts for the ABM Design Engine.
//!
//! This crate is the engine-facing agent harness. It does not run LLM
//! providers, own persistence, or process asset binaries. Python/FastAPI can
//! wrap this layer later without reimplementing compile, operation, preflight,
//! export-preview, or visual-critique semantics.

use lumen_core::{
    platform_default_brand_kit, preflight_scene, scene_has_token_references, AssetId, BrandKit,
    BrandKitId, ComputedGeometry, ContentType, Diagnostic, DiagnosticSeverity, DiagnosticSubject,
    DocumentStatus, DslCompileOutput, DslCompileSession, DslDiagnostic, ExportAdapter,
    ExportArtifact, ExportError, ExportFormat, ExportProfile, ExportPurpose, ExportRequest,
    ExportResult, NodeId, NodeKind, Operation, OperationError, PageId, ParentRef, PdfIntent,
    PreflightOptions, RasterScale, Scene, SizeSpec, SlotKey, Transform, Unit,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq)]
pub struct AgentSession {
    scene: Scene,
    dsl_session: DslCompileSession,
    operation_log: Vec<Operation>,
    active_brand_kit: Option<ActiveBrandKit>,
}

impl AgentSession {
    pub fn new(scene: Scene) -> Self {
        Self {
            dsl_session: DslCompileSession::new(scene.clone()),
            scene,
            operation_log: Vec::new(),
            active_brand_kit: None,
        }
    }

    pub fn scene(&self) -> &Scene {
        &self.scene
    }

    pub fn operation_log(&self) -> &[Operation] {
        &self.operation_log
    }

    pub fn into_scene(self) -> Scene {
        self.scene
    }

    fn record_operations(&mut self, operations: &[Operation]) {
        self.operation_log.extend_from_slice(operations);
    }

    fn reset_dsl_session(&mut self) {
        self.dsl_session = DslCompileSession::new(self.scene.clone());
    }

    fn sync_dsl_scene_preserving_context(&mut self) {
        self.dsl_session
            .sync_scene_preserving_context(self.scene.clone());
    }
}

#[derive(Clone, Debug, PartialEq)]
struct ActiveBrandKit {
    source: AgentBrandKitSource,
    brand_kit: BrandKit,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AgentLoopOptions {
    pub max_iterations: usize,
    pub run_visual_critique: bool,
    pub use_platform_default_brand_kit: bool,
    pub commit_preflight_operations: bool,
    pub allow_visual_repairs_without_preflight_commit: bool,
    pub preflight: PreflightOptions,
    pub export_format: ExportFormat,
    pub export_profile_name: String,
    pub raster: Option<RasterScale>,
    pub include_bleed: bool,
    pub embed_fonts: bool,
}

impl Default for AgentLoopOptions {
    fn default() -> Self {
        Self {
            max_iterations: 3,
            run_visual_critique: true,
            use_platform_default_brand_kit: true,
            commit_preflight_operations: true,
            allow_visual_repairs_without_preflight_commit: false,
            preflight: PreflightOptions::default(),
            export_format: ExportFormat::Png,
            export_profile_name: "agent_critique_preview".to_owned(),
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(96),
            }),
            include_bleed: false,
            embed_fonts: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct AgentTurnInput {
    pub prompt: String,
    pub instruction_context: AgentInstructionContext,
    pub edit: AgentEdit,
    pub brand_kit: Option<BrandKit>,
    pub page_ids: Vec<PageId>,
    pub options: AgentLoopOptions,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AgentInstructionContext {
    pub user_request: String,
    #[serde(default)]
    pub trusted_system_context: Vec<AgentContextItem>,
    #[serde(default)]
    pub untrusted_source_material: Vec<AgentContextItem>,
    #[serde(default)]
    pub brand_notes: Vec<String>,
    pub artifact_goal: Option<String>,
    #[serde(default)]
    pub critique_notes: Vec<String>,
}

impl AgentInstructionContext {
    pub fn from_user_request(user_request: impl Into<String>) -> Self {
        Self {
            user_request: user_request.into(),
            ..Self::default()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentContextItem {
    pub label: String,
    pub content: String,
    pub provenance: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AgentEditIntent {
    pub request: String,
    pub asset_generation_or_placement: bool,
    pub creation_or_composition: bool,
    pub requires_external_planner: bool,
    pub targets: AgentEditTargets,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AgentEditTargets {
    #[serde(default)]
    pub node_ids: Vec<NodeId>,
    #[serde(default)]
    pub slot_keys: Vec<SlotKey>,
    #[serde(default)]
    pub page_ids: Vec<PageId>,
    #[serde(default)]
    pub export_profile_names: Vec<String>,
    #[serde(default)]
    pub brand_kit_ids: Vec<BrandKitId>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EditSurfaceRecommendation {
    Dsl,
    StructuredOps,
    AssetTool,
    ExternalPlanner,
}

pub fn recommend_edit_surface(
    intent: &AgentEditIntent,
    _context: &AgentInstructionContext,
) -> EditSurfaceRecommendation {
    if intent.requires_external_planner {
        return EditSurfaceRecommendation::ExternalPlanner;
    }

    if intent.asset_generation_or_placement {
        return EditSurfaceRecommendation::AssetTool;
    }

    if !intent.targets.node_ids.is_empty()
        || !intent.targets.slot_keys.is_empty()
        || !intent.targets.page_ids.is_empty()
        || !intent.targets.export_profile_names.is_empty()
        || !intent.targets.brand_kit_ids.is_empty()
    {
        return EditSurfaceRecommendation::StructuredOps;
    }

    if intent.creation_or_composition {
        return EditSurfaceRecommendation::Dsl;
    }

    EditSurfaceRecommendation::ExternalPlanner
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AgentEdit {
    DslBlock { source: String },
    StructuredOps { operations: Vec<Operation> },
    AssetTool { request: AgentAssetRequest },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentStopReason {
    Completed,
    DslHalted,
    OperationFailed,
    AssetToolFailed,
    PreflightFailed,
    ExportFailed,
    CritiqueFailed,
    MaxIterations,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AgentTurnResult {
    pub initial_scene: Scene,
    pub final_scene: Scene,
    pub last_preflight_scene: Option<Scene>,
    pub final_brand_kit: Option<AgentBrandKitSummary>,
    pub operations: Vec<Operation>,
    pub engine_diagnostics: Vec<Diagnostic>,
    pub dsl_diagnostics: Vec<DslDiagnostic>,
    pub agent_diagnostics: Vec<AgentDiagnostic>,
    pub preview_artifacts: Vec<ExportArtifact>,
    pub iterations: Vec<AgentIteration>,
    pub stop_reason: AgentStopReason,
}

impl AgentTurnResult {
    fn new(initial_scene: Scene) -> Self {
        Self {
            final_scene: initial_scene.clone(),
            initial_scene,
            last_preflight_scene: None,
            final_brand_kit: None,
            operations: Vec::new(),
            engine_diagnostics: Vec::new(),
            dsl_diagnostics: Vec::new(),
            agent_diagnostics: Vec::new(),
            preview_artifacts: Vec::new(),
            iterations: Vec::new(),
            stop_reason: AgentStopReason::Completed,
        }
    }

    pub fn has_errors(&self) -> bool {
        self.engine_diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
            || self
                .dsl_diagnostics
                .iter()
                .any(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error)
            || self
                .agent_diagnostics
                .iter()
                .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    }

    pub fn diagnostic_views(&self) -> DiagnosticViews {
        DiagnosticViews::from_parts(
            all_diagnostic_dtos(
                &self.engine_diagnostics,
                &self.dsl_diagnostics,
                &self.agent_diagnostics,
            ),
            Vec::new(),
        )
    }

    pub fn to_dto(&self) -> AgentTurnResultDto {
        AgentTurnResultDto::from(self)
    }

    fn finish(
        mut self,
        session: &AgentSession,
        iteration: AgentIteration,
        stop_reason: AgentStopReason,
    ) -> Self {
        self.stop_reason = stop_reason;
        self.final_scene = session.scene.clone();
        self.iterations.push(iteration);
        self.final_brand_kit = self
            .iterations
            .iter()
            .rev()
            .find_map(|iteration| iteration.brand_kit.clone());
        self
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct AgentIteration {
    pub index: usize,
    pub edit: AgentEdit,
    pub applied_operations: Vec<Operation>,
    pub preflight_operations: Vec<Operation>,
    pub dsl_output: Option<DslCompileOutput>,
    pub asset_result: Option<AgentAssetResult>,
    pub preflight_diagnostics: Vec<Diagnostic>,
    pub export_request: Option<ExportRequest>,
    pub export_result: Option<ExportResult>,
    pub visual_critique: Option<VisualCritiqueResult>,
    pub brand_kit_source: Option<AgentBrandKitSource>,
    pub brand_kit: Option<AgentBrandKitSummary>,
    pub stop_reason: Option<AgentStopReason>,
}

impl AgentIteration {
    fn new(index: usize, edit: AgentEdit) -> Self {
        Self {
            index,
            edit,
            applied_operations: Vec::new(),
            preflight_operations: Vec::new(),
            dsl_output: None,
            asset_result: None,
            preflight_diagnostics: Vec::new(),
            export_request: None,
            export_result: None,
            visual_critique: None,
            brand_kit_source: None,
            brand_kit: None,
            stop_reason: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentDiagnostic {
    pub severity: DiagnosticSeverity,
    pub code: String,
    pub message: String,
    pub subject: Option<DiagnosticSubject>,
    pub hint: Option<String>,
}

impl AgentDiagnostic {
    pub fn error(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            severity: DiagnosticSeverity::Error,
            code: code.into(),
            message: message.into(),
            subject: None,
            hint: None,
        }
    }

    pub fn warning(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            severity: DiagnosticSeverity::Warning,
            code: code.into(),
            message: message.into(),
            subject: None,
            hint: None,
        }
    }

    pub fn with_subject(mut self, subject: DiagnosticSubject) -> Self {
        self.subject = Some(subject);
        self
    }

    pub fn with_hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentDiagnosticSource {
    Engine,
    Dsl,
    Agent,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentDiagnosticDto {
    pub source: AgentDiagnosticSource,
    pub severity: DiagnosticSeverity,
    pub phase: Option<String>,
    pub code: String,
    pub message: String,
    pub subject: Option<DiagnosticSubject>,
    pub hint: Option<String>,
    pub line: Option<usize>,
    pub column: Option<usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct DiagnosticViews {
    pub audit: Vec<AgentDiagnosticDto>,
    pub current: Vec<AgentDiagnosticDto>,
    pub latest: Vec<AgentDiagnosticDto>,
}

impl DiagnosticViews {
    pub fn from_parts(audit: Vec<AgentDiagnosticDto>, current: Vec<AgentDiagnosticDto>) -> Self {
        let latest = latest_diagnostics(&audit);
        Self {
            audit,
            current,
            latest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentTurnStatus {
    Applied,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentTurnResultDto {
    pub schema_version: u32,
    pub document_id: String,
    pub status: AgentTurnStatus,
    pub stop_reason: AgentStopReason,
    pub operation_count: usize,
    pub operations: Vec<OperationSummary>,
    pub diagnostics: DiagnosticViews,
    pub iterations: Vec<AgentIterationDto>,
    pub preview: Option<PreviewArtifactSummary>,
    pub brand_kit: Option<AgentBrandKitSummary>,
    pub repair_loop: RepairLoopStatus,
}

impl From<&AgentTurnResult> for AgentTurnResultDto {
    fn from(result: &AgentTurnResult) -> Self {
        let diagnostics = result.diagnostic_views();
        Self {
            schema_version: 1,
            document_id: result.final_scene.meta.id.to_string(),
            status: if result.has_errors() {
                AgentTurnStatus::Failed
            } else {
                AgentTurnStatus::Applied
            },
            stop_reason: result.stop_reason.clone(),
            operation_count: result.operations.len(),
            operations: result
                .operations
                .iter()
                .enumerate()
                .map(|(index, operation)| OperationSummary {
                    sequence: index + 1,
                    kind: operation_kind(operation).to_owned(),
                })
                .collect(),
            diagnostics,
            iterations: result
                .iterations
                .iter()
                .map(AgentIterationDto::from)
                .collect(),
            preview: result
                .preview_artifacts
                .first()
                .map(PreviewArtifactSummary::from),
            brand_kit: result.final_brand_kit.clone(),
            repair_loop: RepairLoopStatus {
                iterations: result.iterations.len(),
                stop_reason: result.stop_reason.clone(),
                max_iterations_reached: result.stop_reason == AgentStopReason::MaxIterations,
            },
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentIterationDto {
    pub index: usize,
    pub edit_surface: EditSurfaceRecommendation,
    pub stop_reason: Option<AgentStopReason>,
    pub operation_application: OperationApplicationSummary,
    pub dsl: Option<DslCompileSummary>,
    pub preview: Option<PreviewArtifactSummary>,
    pub brand_kit: Option<AgentBrandKitSummary>,
    pub diagnostics: DiagnosticViews,
}

impl From<&AgentIteration> for AgentIterationDto {
    fn from(iteration: &AgentIteration) -> Self {
        let audit = iteration_diagnostic_dtos(iteration);
        let preview = iteration
            .export_result
            .as_ref()
            .and_then(|result| result.artifacts.first())
            .map(PreviewArtifactSummary::from);
        Self {
            index: iteration.index,
            edit_surface: edit_surface_for_edit(&iteration.edit),
            stop_reason: iteration.stop_reason.clone(),
            operation_application: OperationApplicationSummary {
                applied_operations: iteration.applied_operations.len(),
                preflight_operations: iteration.preflight_operations.len(),
            },
            dsl: iteration.dsl_output.as_ref().map(DslCompileSummary::from),
            preview,
            brand_kit: iteration.brand_kit.clone(),
            diagnostics: DiagnosticViews::from_parts(audit.clone(), audit),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DslCompileSummary {
    pub operation_count: usize,
    pub diagnostic_count: usize,
    pub has_errors: bool,
    pub halted_at_line: Option<usize>,
    pub halted_code: Option<String>,
}

impl From<&DslCompileOutput> for DslCompileSummary {
    fn from(output: &DslCompileOutput) -> Self {
        Self {
            operation_count: output.operations.len(),
            diagnostic_count: output.diagnostics.len(),
            has_errors: output.has_errors(),
            halted_at_line: output.halted_at.as_ref().map(|halt| halt.line),
            halted_code: output.halted_at.as_ref().map(|halt| halt.code.clone()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct OperationApplicationSummary {
    pub applied_operations: usize,
    pub preflight_operations: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct OperationSummary {
    pub sequence: usize,
    pub kind: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PreviewArtifactSummary {
    pub format: ExportFormat,
    pub mime_type: String,
    pub page_id: Option<PageId>,
    pub asset_id: Option<AssetId>,
    pub byte_len: usize,
    pub has_sidecar: bool,
}

impl From<&ExportArtifact> for PreviewArtifactSummary {
    fn from(artifact: &ExportArtifact) -> Self {
        Self {
            format: artifact.format.clone(),
            mime_type: artifact.mime_type.clone(),
            page_id: artifact.page_id.clone(),
            asset_id: artifact.asset_id.clone(),
            byte_len: artifact.bytes.len(),
            has_sidecar: artifact.sidecar_json.is_some(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RepairLoopStatus {
    pub iterations: usize,
    pub stop_reason: AgentStopReason,
    pub max_iterations_reached: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentBrandKitSource {
    Provided,
    PlatformDefault,
    DocumentReference,
    NoneRequired,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SceneSummary {
    pub document_id: String,
    pub title: String,
    pub status: DocumentStatus,
    pub node_count: usize,
    pub page_count: usize,
    pub slot_count: usize,
    pub pages: Vec<PageSummary>,
    pub slots: Vec<SlotSummary>,
}

impl SceneSummary {
    pub fn from_scene(scene: &Scene) -> Self {
        Self {
            document_id: scene.meta.id.to_string(),
            title: scene.meta.title.clone(),
            status: scene.meta.status.clone(),
            node_count: scene.nodes.len(),
            page_count: scene.pages.len(),
            slot_count: scene.slots.len(),
            pages: scene
                .pages
                .values()
                .map(|page| PageSummary {
                    page_id: page.id.to_string(),
                    name: page.name.clone(),
                    width: page.size.width,
                    height: page.size.height,
                    unit: page.size.unit.clone(),
                    child_count: page.children.len(),
                })
                .collect(),
            slots: scene
                .slots
                .values()
                .map(|slot| SlotSummary {
                    slot_id: slot.id.to_string(),
                    key: slot.key.to_string(),
                    label: slot.label.clone(),
                    content_type: slot.content_type.clone(),
                    required: slot.required,
                    bound_node_count: slot.bound_nodes.len(),
                    placeholder: slot.placeholder.clone(),
                })
                .collect(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageSummary {
    pub page_id: String,
    pub name: String,
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
    pub child_count: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SlotSummary {
    pub slot_id: String,
    pub key: String,
    pub label: String,
    pub content_type: ContentType,
    pub required: bool,
    pub bound_node_count: usize,
    pub placeholder: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageReadSummary {
    pub page: PageSummary,
    pub root_nodes: Vec<NodeSummary>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NodeSummary {
    pub node_id: NodeId,
    pub name: Option<String>,
    pub kind: String,
    pub child_count: usize,
    pub slot_keys: Vec<SlotKey>,
    pub locked: bool,
    pub geometry: GeometrySummary,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NodeTreeSummary {
    pub page_id: PageId,
    pub nodes: Vec<NodeTreeEntry>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NodeTreeEntry {
    pub node_id: NodeId,
    pub parent: ParentRef,
    pub depth: usize,
    pub kind: String,
    pub name: Option<String>,
    pub children: Vec<NodeId>,
    pub slot_keys: Vec<SlotKey>,
    pub geometry: GeometrySummary,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GeometrySummary {
    pub node_id: NodeId,
    pub transform: Transform,
    pub size: SizeSpec,
    pub computed: Option<ComputedGeometry>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SlotBindingSummary {
    pub slot: SlotSummary,
    pub bound_nodes: Vec<NodeSummary>,
}

pub fn summarize_document(scene: &Scene) -> SceneSummary {
    SceneSummary::from_scene(scene)
}

pub fn summarize_page(scene: &Scene, page_id: &PageId) -> Option<PageReadSummary> {
    let page = scene.page(page_id)?;
    Some(PageReadSummary {
        page: PageSummary {
            page_id: page.id.to_string(),
            name: page.name.clone(),
            width: page.size.width,
            height: page.size.height,
            unit: page.size.unit.clone(),
            child_count: page.children.len(),
        },
        root_nodes: page
            .children
            .iter()
            .filter_map(|node_id| summarize_node(scene, node_id))
            .collect(),
    })
}

pub fn summarize_slots(scene: &Scene) -> Vec<SlotSummary> {
    SceneSummary::from_scene(scene).slots
}

pub fn summarize_node_tree(scene: &Scene, page_id: &PageId) -> Option<NodeTreeSummary> {
    let page = scene.page(page_id)?;
    let mut nodes = Vec::new();
    for child_id in &page.children {
        collect_node_tree_entries(
            scene,
            child_id,
            ParentRef::Page(page.id.clone()),
            0,
            &mut nodes,
        );
    }
    Some(NodeTreeSummary {
        page_id: page.id.clone(),
        nodes,
    })
}

pub fn query_geometry(scene: &Scene, node_id: &NodeId) -> Option<GeometrySummary> {
    scene.node(node_id).map(|node| GeometrySummary {
        node_id: node.id.clone(),
        transform: node.transform.clone(),
        size: node.size.clone(),
        computed: node.computed.clone(),
    })
}

pub fn query_slot_bindings(scene: &Scene, slot_key: &SlotKey) -> Option<SlotBindingSummary> {
    let slot = scene.slot_by_key(slot_key)?;
    Some(SlotBindingSummary {
        slot: SlotSummary {
            slot_id: slot.id.to_string(),
            key: slot.key.to_string(),
            label: slot.label.clone(),
            content_type: slot.content_type.clone(),
            required: slot.required,
            bound_node_count: slot.bound_nodes.len(),
            placeholder: slot.placeholder.clone(),
        },
        bound_nodes: scene
            .bound_nodes_for_slot(&slot.id)
            .into_iter()
            .map(|node| node_summary_from_node(scene, node))
            .collect(),
    })
}

fn summarize_node(scene: &Scene, node_id: &NodeId) -> Option<NodeSummary> {
    scene
        .node(node_id)
        .map(|node| node_summary_from_node(scene, node))
}

fn node_summary_from_node(scene: &Scene, node: &lumen_core::Node) -> NodeSummary {
    NodeSummary {
        node_id: node.id.clone(),
        name: node.name.clone(),
        kind: node_kind_name(&node.kind).to_owned(),
        child_count: node.children.len(),
        slot_keys: scene
            .slots_for_node(&node.id)
            .into_iter()
            .map(|slot| slot.key.clone())
            .collect(),
        locked: node.locked,
        geometry: GeometrySummary {
            node_id: node.id.clone(),
            transform: node.transform.clone(),
            size: node.size.clone(),
            computed: node.computed.clone(),
        },
    }
}

fn collect_node_tree_entries(
    scene: &Scene,
    node_id: &NodeId,
    parent: ParentRef,
    depth: usize,
    entries: &mut Vec<NodeTreeEntry>,
) {
    let Some(node) = scene.node(node_id) else {
        return;
    };
    entries.push(NodeTreeEntry {
        node_id: node.id.clone(),
        parent,
        depth,
        kind: node_kind_name(&node.kind).to_owned(),
        name: node.name.clone(),
        children: node.children.clone(),
        slot_keys: scene
            .slots_for_node(&node.id)
            .into_iter()
            .map(|slot| slot.key.clone())
            .collect(),
        geometry: GeometrySummary {
            node_id: node.id.clone(),
            transform: node.transform.clone(),
            size: node.size.clone(),
            computed: node.computed.clone(),
        },
    });
    for child_id in &node.children {
        collect_node_tree_entries(
            scene,
            child_id,
            ParentRef::Node(node.id.clone()),
            depth + 1,
            entries,
        );
    }
}

fn node_kind_name(kind: &NodeKind) -> &'static str {
    match kind {
        NodeKind::Frame => "frame",
        NodeKind::Group => "group",
        NodeKind::Rect => "rect",
        NodeKind::Ellipse => "ellipse",
        NodeKind::Line(_) => "line",
        NodeKind::Text(_) => "text",
        NodeKind::Image(_) => "image",
        NodeKind::Vector(_) => "vector",
        NodeKind::AutoLayout(_) => "autolayout",
        NodeKind::Instance { .. } => "instance",
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentBrandKitSummary {
    pub source: AgentBrandKitSource,
    pub brand_kit_id: Option<String>,
    pub version: Option<u32>,
    pub name: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VisualCritiqueRequest {
    pub prompt: String,
    pub instruction_context: AgentInstructionContext,
    pub iteration_index: usize,
    pub scene: SceneSummary,
    pub page_ids: Vec<PageId>,
    pub brand_kit: AgentBrandKitSummary,
    pub diagnostics: Vec<Diagnostic>,
    pub diagnostic_views: DiagnosticViews,
    pub preview_artifacts: Vec<ExportArtifact>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VisualCritiqueResult {
    pub verdict: VisualCritiqueVerdict,
    pub issues: Vec<VisualIssue>,
    pub repair_edit: Option<AgentEdit>,
    pub diagnostics: Vec<AgentDiagnostic>,
}

impl VisualCritiqueResult {
    pub fn pass() -> Self {
        Self {
            verdict: VisualCritiqueVerdict::Pass,
            issues: Vec::new(),
            repair_edit: None,
            diagnostics: Vec::new(),
        }
    }

    pub fn needs_repair(issues: Vec<VisualIssue>, repair_edit: Option<AgentEdit>) -> Self {
        Self {
            verdict: VisualCritiqueVerdict::NeedsRepair,
            issues,
            repair_edit,
            diagnostics: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VisualCritiqueVerdict {
    Pass,
    NeedsRepair,
    Reject,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VisualIssue {
    pub category: VisualIssueCategory,
    pub severity: DiagnosticSeverity,
    pub message: String,
    pub subject: Option<DiagnosticSubject>,
    pub suggested_fix: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VisualIssueCategory {
    Hierarchy,
    Spacing,
    Contrast,
    BrandFit,
    Composition,
    Readability,
    PrintSafety,
    PlaceholderCredibility,
    Imagery,
}

pub trait VisualCritic {
    fn critique(&self, request: &VisualCritiqueRequest) -> VisualCritiqueResult;
}

#[derive(Clone, Debug, Default)]
pub struct AcceptingVisualCritic;

impl VisualCritic for AcceptingVisualCritic {
    fn critique(&self, _request: &VisualCritiqueRequest) -> VisualCritiqueResult {
        VisualCritiqueResult::pass()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AgentAssetRequest {
    GenerateImage {
        prompt: String,
        target_slot_key: Option<SlotKey>,
        suggested_asset_id: Option<AssetId>,
    },
    GenerateSvg {
        prompt: String,
        target_slot_key: Option<SlotKey>,
        suggested_asset_id: Option<AssetId>,
    },
    VectorizeImage {
        source_asset_id: AssetId,
        suggested_asset_id: Option<AssetId>,
    },
    PlaceAsset {
        asset_id: AssetId,
        node_id: NodeId,
        alt: Option<String>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentToolStatus {
    Completed,
    Unavailable,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentAssetResult {
    pub status: AgentToolStatus,
    pub asset_id: Option<AssetId>,
    pub mime_type: Option<String>,
    pub provenance: Option<AgentAssetProvenance>,
    pub license: Option<AgentAssetLicense>,
    pub operations: Vec<Operation>,
    pub diagnostics: Vec<AgentDiagnostic>,
}

impl AgentAssetResult {
    pub fn completed(asset_id: Option<AssetId>, operations: Vec<Operation>) -> Self {
        Self {
            status: AgentToolStatus::Completed,
            asset_id,
            mime_type: None,
            provenance: None,
            license: None,
            operations,
            diagnostics: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentAssetProvenance {
    pub source: String,
    pub model: Option<String>,
    pub confidence: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentAssetLicense {
    pub name: String,
    pub allow_export: bool,
    pub allow_modification: bool,
    pub restrictions: Vec<String>,
}

pub trait AssetTool {
    fn execute(&self, request: &AgentAssetRequest) -> AgentAssetResult;
}

#[derive(Clone, Debug, Default)]
pub struct UnavailableAssetTool;

impl AssetTool for UnavailableAssetTool {
    fn execute(&self, request: &AgentAssetRequest) -> AgentAssetResult {
        AgentAssetResult {
            status: AgentToolStatus::Unavailable,
            asset_id: None,
            mime_type: None,
            provenance: None,
            license: None,
            operations: Vec::new(),
            diagnostics: vec![AgentDiagnostic::error(
                "LUMA0400",
                format!("asset tool is not available for request: {request:?}"),
            )
            .with_hint("Wire this request to assets/pipeline-v0 or provide a mock asset tool.")],
        }
    }
}

pub struct AgentDesignLoop<'a> {
    export_adapter: &'a dyn ExportAdapter,
    visual_critic: &'a dyn VisualCritic,
    asset_tool: &'a dyn AssetTool,
}

impl<'a> AgentDesignLoop<'a> {
    pub fn new(
        export_adapter: &'a dyn ExportAdapter,
        visual_critic: &'a dyn VisualCritic,
        asset_tool: &'a dyn AssetTool,
    ) -> Self {
        Self {
            export_adapter,
            visual_critic,
            asset_tool,
        }
    }

    pub fn run_turn(&self, session: &mut AgentSession, input: AgentTurnInput) -> AgentTurnResult {
        let AgentTurnInput {
            prompt,
            instruction_context,
            edit,
            brand_kit,
            page_ids,
            options,
        } = input;
        let mut result = AgentTurnResult::new(session.scene.clone());
        let mut next_edit = Some(edit);
        let max_iterations = options.max_iterations.max(1);
        let mut iteration_index = 0;

        while let Some(edit) = next_edit.take() {
            iteration_index += 1;
            let mut iteration = AgentIteration::new(iteration_index, edit.clone());

            let apply = self.apply_edit(session, edit);
            let mut current_engine_diagnostics = apply.engine_diagnostics.clone();
            let current_dsl_diagnostics = apply.dsl_diagnostics.clone();
            let mut current_agent_diagnostics = apply.agent_diagnostics.clone();
            iteration.applied_operations = apply.operations.clone();
            iteration.dsl_output = apply.dsl_output;
            iteration.asset_result = apply.asset_result;
            result.operations.extend(apply.operations);
            result.engine_diagnostics.extend(apply.engine_diagnostics);
            result.dsl_diagnostics.extend(apply.dsl_diagnostics);
            result.agent_diagnostics.extend(apply.agent_diagnostics);

            if let Some(stop_reason) = apply.stop_reason {
                iteration.stop_reason = Some(stop_reason.clone());
                return result.finish(session, iteration, stop_reason);
            }

            let effective_brand_kit = match choose_effective_brand_kit(
                session,
                brand_kit.as_ref(),
                options.use_platform_default_brand_kit,
            ) {
                Ok(brand) => brand,
                Err(diagnostic) => {
                    result.agent_diagnostics.push(diagnostic);
                    iteration.stop_reason = Some(AgentStopReason::PreflightFailed);
                    return result.finish(session, iteration, AgentStopReason::PreflightFailed);
                }
            };
            iteration.brand_kit_source = Some(effective_brand_kit.summary.source.clone());
            iteration.brand_kit = Some(effective_brand_kit.summary.clone());

            let preflight = preflight_scene(
                session.scene.clone(),
                effective_brand_kit.brand_kit.as_ref(),
                options.preflight.clone(),
            );
            iteration.preflight_diagnostics = preflight.diagnostics.clone();
            current_engine_diagnostics.extend(preflight.diagnostics.clone());
            result
                .engine_diagnostics
                .extend(preflight.diagnostics.clone());
            result.last_preflight_scene = Some(preflight.scene.clone());

            if preflight.has_errors() {
                iteration.stop_reason = Some(AgentStopReason::PreflightFailed);
                return result.finish(session, iteration, AgentStopReason::PreflightFailed);
            }

            let preflight_operations = collect_preflight_operations(&preflight);
            if options.commit_preflight_operations {
                session.scene = preflight.scene.clone();
                session.sync_dsl_scene_preserving_context();
                session.record_operations(&preflight_operations);
                iteration.preflight_operations = preflight_operations.clone();
                result.operations.extend(preflight_operations);
            }

            let export_page_ids = resolve_export_page_ids(&preflight.scene, &page_ids);
            let export_request = critique_export_request(&options, export_page_ids.clone());
            iteration.export_request = Some(export_request.clone());

            let export_result = match self
                .export_adapter
                .export(&preflight.scene, &export_request)
            {
                Ok(export_result) => export_result,
                Err(error) => {
                    let ExportError {
                        code,
                        message,
                        diagnostics,
                    } = error;
                    result.engine_diagnostics.extend(diagnostics.clone());
                    result.agent_diagnostics.push(AgentDiagnostic::error(
                        "LUMA0300",
                        format!("preview export failed with {code}: {message}"),
                    ));
                    iteration.preflight_diagnostics.extend(diagnostics);
                    iteration.stop_reason = Some(AgentStopReason::ExportFailed);
                    return result.finish(session, iteration, AgentStopReason::ExportFailed);
                }
            };

            result
                .engine_diagnostics
                .extend(export_result.diagnostics.clone());
            current_engine_diagnostics.extend(export_result.diagnostics.clone());
            result.preview_artifacts = export_result.artifacts.clone();
            iteration.export_result = Some(export_result.clone());

            if has_engine_errors(&export_result.diagnostics) {
                iteration.stop_reason = Some(AgentStopReason::ExportFailed);
                return result.finish(session, iteration, AgentStopReason::ExportFailed);
            }

            if !options.run_visual_critique {
                iteration.stop_reason = Some(AgentStopReason::Completed);
                return result.finish(session, iteration, AgentStopReason::Completed);
            }

            let preview_diagnostics = validate_preview_artifacts(&export_result, &export_request);
            if !preview_diagnostics.is_empty() {
                current_agent_diagnostics.extend(preview_diagnostics.clone());
                result.agent_diagnostics.extend(preview_diagnostics);
                iteration.stop_reason = Some(AgentStopReason::ExportFailed);
                return result.finish(session, iteration, AgentStopReason::ExportFailed);
            }

            let current_diagnostics = all_diagnostic_dtos(
                &current_engine_diagnostics,
                &current_dsl_diagnostics,
                &current_agent_diagnostics,
            );
            let diagnostic_views = DiagnosticViews::from_parts(
                all_diagnostic_dtos(
                    &result.engine_diagnostics,
                    &result.dsl_diagnostics,
                    &result.agent_diagnostics,
                ),
                current_diagnostics,
            );
            let critique_request = VisualCritiqueRequest {
                prompt: prompt.clone(),
                instruction_context: instruction_context.clone(),
                iteration_index,
                scene: SceneSummary::from_scene(&preflight.scene),
                page_ids: export_page_ids,
                brand_kit: effective_brand_kit.summary,
                diagnostics: current_engine_diagnostics.clone(),
                diagnostic_views,
                preview_artifacts: export_result.artifacts.clone(),
            };
            let critique = self.visual_critic.critique(&critique_request);
            result
                .agent_diagnostics
                .extend(critique.diagnostics.clone());
            iteration.visual_critique = Some(critique.clone());

            match critique.verdict {
                VisualCritiqueVerdict::Pass => {
                    iteration.stop_reason = Some(AgentStopReason::Completed);
                    return result.finish(session, iteration, AgentStopReason::Completed);
                }
                VisualCritiqueVerdict::Reject => {
                    iteration.stop_reason = Some(AgentStopReason::CritiqueFailed);
                    return result.finish(session, iteration, AgentStopReason::CritiqueFailed);
                }
                VisualCritiqueVerdict::NeedsRepair => {
                    let Some(repair_edit) = critique.repair_edit else {
                        result.agent_diagnostics.push(
                            AgentDiagnostic::error(
                                "LUMA0500",
                                "visual critic requested repair but did not provide a repair edit",
                            )
                            .with_hint(
                                "Return structured operations or a DSL block for the next repair pass.",
                            ),
                        );
                        iteration.stop_reason = Some(AgentStopReason::CritiqueFailed);
                        return result.finish(session, iteration, AgentStopReason::CritiqueFailed);
                    };

                    if !options.commit_preflight_operations
                        && !options.allow_visual_repairs_without_preflight_commit
                    {
                        result.agent_diagnostics.push(
                            AgentDiagnostic::error(
                                "LUMA0600",
                                "visual repair loop cannot continue when preflight operations are not committed",
                            )
                            .with_hint(
                                "Set commit_preflight_operations=true, disable visual repair, or explicitly allow repairs without preflight commit.",
                            ),
                        );
                        iteration.stop_reason = Some(AgentStopReason::CritiqueFailed);
                        return result.finish(session, iteration, AgentStopReason::CritiqueFailed);
                    }

                    if iteration_index >= max_iterations {
                        iteration.stop_reason = Some(AgentStopReason::MaxIterations);
                        return result.finish(session, iteration, AgentStopReason::MaxIterations);
                    }

                    next_edit = Some(repair_edit);
                    result.iterations.push(iteration);
                }
            }
        }

        result.stop_reason = AgentStopReason::Completed;
        result.final_scene = session.scene.clone();
        result
    }

    fn apply_edit(&self, session: &mut AgentSession, edit: AgentEdit) -> ApplyEditOutcome {
        match edit {
            AgentEdit::DslBlock { source } => apply_dsl_block(session, &source),
            AgentEdit::StructuredOps { operations } => apply_structured_ops(session, operations),
            AgentEdit::AssetTool { request } => {
                let asset_result = self.asset_tool.execute(&request);
                let mut outcome = ApplyEditOutcome {
                    asset_result: Some(asset_result.clone()),
                    agent_diagnostics: asset_result.diagnostics.clone(),
                    ..ApplyEditOutcome::default()
                };

                if asset_result.status != AgentToolStatus::Completed {
                    outcome.stop_reason = Some(AgentStopReason::AssetToolFailed);
                    return outcome;
                }

                let structured = apply_structured_ops(session, asset_result.operations.clone());
                outcome.operations = structured.operations;
                outcome.engine_diagnostics = structured.engine_diagnostics;
                outcome
                    .agent_diagnostics
                    .extend(structured.agent_diagnostics);
                outcome.stop_reason = structured.stop_reason;
                outcome
            }
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
struct ApplyEditOutcome {
    operations: Vec<Operation>,
    dsl_output: Option<DslCompileOutput>,
    asset_result: Option<AgentAssetResult>,
    engine_diagnostics: Vec<Diagnostic>,
    dsl_diagnostics: Vec<DslDiagnostic>,
    agent_diagnostics: Vec<AgentDiagnostic>,
    stop_reason: Option<AgentStopReason>,
}

fn apply_dsl_block(session: &mut AgentSession, source: &str) -> ApplyEditOutcome {
    let output = session.dsl_session.compile_block(source);
    let operations = output.operations.clone();
    session.record_operations(&operations);
    session.scene = session.dsl_session.scene().clone();

    let stop_reason = if output.has_errors() {
        Some(AgentStopReason::DslHalted)
    } else {
        None
    };

    ApplyEditOutcome {
        operations,
        dsl_diagnostics: output.diagnostics.clone(),
        dsl_output: Some(output),
        stop_reason,
        ..ApplyEditOutcome::default()
    }
}

fn apply_structured_ops(
    session: &mut AgentSession,
    operations: Vec<Operation>,
) -> ApplyEditOutcome {
    let mut draft = session.scene.clone();
    match draft.apply_operations_checked(operations.clone()) {
        Ok(report) => {
            session.scene = draft;
            session.reset_dsl_session();
            session.record_operations(&operations);
            ApplyEditOutcome {
                operations,
                engine_diagnostics: report.diagnostics,
                ..ApplyEditOutcome::default()
            }
        }
        Err(error) => operation_error_outcome(error),
    }
}

fn operation_error_outcome(error: OperationError) -> ApplyEditOutcome {
    let OperationError {
        code,
        message,
        diagnostics,
    } = error;
    ApplyEditOutcome {
        engine_diagnostics: diagnostics,
        agent_diagnostics: vec![AgentDiagnostic::error(
            "LUMA0200",
            format!("structured operation application failed with {code}: {message}"),
        )],
        stop_reason: Some(AgentStopReason::OperationFailed),
        ..ApplyEditOutcome::default()
    }
}

#[derive(Clone, Debug, PartialEq)]
struct EffectiveBrandKit {
    brand_kit: Option<BrandKit>,
    summary: AgentBrandKitSummary,
}

fn choose_effective_brand_kit(
    session: &mut AgentSession,
    provided: Option<&BrandKit>,
    use_platform_default: bool,
) -> Result<EffectiveBrandKit, AgentDiagnostic> {
    if let Some(brand_kit) = provided {
        session.active_brand_kit = Some(ActiveBrandKit {
            source: AgentBrandKitSource::Provided,
            brand_kit: brand_kit.clone(),
        });
        return Ok(EffectiveBrandKit {
            brand_kit: Some(brand_kit.clone()),
            summary: brand_summary(AgentBrandKitSource::Provided, Some(brand_kit)),
        });
    }

    if let Some(active) = &session.active_brand_kit {
        return Ok(EffectiveBrandKit {
            brand_kit: Some(active.brand_kit.clone()),
            summary: brand_summary(active.source.clone(), Some(&active.brand_kit)),
        });
    }

    if scene_has_token_references(&session.scene) && use_platform_default {
        if session.active_brand_kit.is_none() {
            let brand_kit = platform_default_brand_kit().map_err(|error| {
                AgentDiagnostic::error(
                    "LUMA0100",
                    format!("failed to load platform default brand kit: {error}"),
                )
            })?;
            session.active_brand_kit = Some(ActiveBrandKit {
                source: AgentBrandKitSource::PlatformDefault,
                brand_kit,
            });
        }
        let active = session
            .active_brand_kit
            .as_ref()
            .expect("active brand kit set");
        return Ok(EffectiveBrandKit {
            brand_kit: Some(active.brand_kit.clone()),
            summary: brand_summary(active.source.clone(), Some(&active.brand_kit)),
        });
    }

    if let Some(brand_ref) = &session.scene.meta.brand_kit {
        return Ok(EffectiveBrandKit {
            brand_kit: None,
            summary: AgentBrandKitSummary {
                source: AgentBrandKitSource::DocumentReference,
                brand_kit_id: Some(brand_ref.id.to_string()),
                version: Some(brand_ref.version),
                name: None,
            },
        });
    }

    Ok(EffectiveBrandKit {
        brand_kit: None,
        summary: brand_summary(AgentBrandKitSource::NoneRequired, None),
    })
}

fn brand_summary(
    source: AgentBrandKitSource,
    brand_kit: Option<&BrandKit>,
) -> AgentBrandKitSummary {
    AgentBrandKitSummary {
        source,
        brand_kit_id: brand_kit.map(|kit| kit.id.to_string()),
        version: brand_kit.map(|kit| kit.version),
        name: brand_kit.map(|kit| kit.name.clone()),
    }
}

fn collect_preflight_operations(preflight: &lumen_core::PreflightResult) -> Vec<Operation> {
    preflight
        .brand_ref_operations
        .iter()
        .chain(preflight.token_operations.iter())
        .chain(preflight.layout_operations.iter())
        .cloned()
        .collect()
}

fn resolve_export_page_ids(scene: &Scene, requested: &[PageId]) -> Vec<PageId> {
    if requested.is_empty() {
        scene.pages.keys().cloned().collect()
    } else {
        requested.to_vec()
    }
}

fn critique_export_request(options: &AgentLoopOptions, page_ids: Vec<PageId>) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: options.export_profile_name.clone(),
            format: options.export_format.clone(),
            pdf_intent: Some(PdfIntent::Preview),
            raster: if options.export_format == ExportFormat::Png {
                options.raster.clone()
            } else {
                None
            },
            include_bleed: options.include_bleed,
            embed_fonts: options.embed_fonts,
            include_marks: false,
            imposition: None,
            proof: false,
            color: None,
        },
        page_ids,
        purpose: ExportPurpose::AgentCritique,
    }
}

fn has_engine_errors(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
}

fn validate_preview_artifacts(
    export_result: &ExportResult,
    request: &ExportRequest,
) -> Vec<AgentDiagnostic> {
    let mut diagnostics = Vec::new();

    if !is_visual_preview_format(&request.profile.format) {
        diagnostics.push(
            AgentDiagnostic::error(
                "LUMA0313",
                format!(
                    "export format {:?} is not a visual preview format for critique",
                    request.profile.format
                ),
            )
            .with_hint("Use PNG or SVG for visual critique previews."),
        );
        return diagnostics;
    }

    if export_result.artifacts.is_empty() {
        diagnostics.push(AgentDiagnostic::error(
            "LUMA0310",
            "preview export returned no artifacts",
        ));
        return diagnostics;
    }

    let matching_artifacts = export_result
        .artifacts
        .iter()
        .filter(|artifact| artifact.format == request.profile.format)
        .collect::<Vec<_>>();
    if matching_artifacts.is_empty() {
        diagnostics.push(
            AgentDiagnostic::error(
                "LUMA0311",
                format!(
                    "preview export returned no {:?} artifacts for critique",
                    request.profile.format
                ),
            )
            .with_hint("Return at least one artifact matching the requested preview format."),
        );
        return diagnostics;
    }

    for artifact in matching_artifacts {
        if artifact.bytes.is_empty() {
            diagnostics.push(
                AgentDiagnostic::error(
                    "LUMA0312",
                    format!(
                        "preview artifact for page {:?} has empty bytes",
                        artifact.page_id
                    ),
                )
                .with_hint("Critique requires a non-empty rendered preview artifact."),
            );
        }
    }

    diagnostics
}

fn is_visual_preview_format(format: &ExportFormat) -> bool {
    matches!(format, ExportFormat::Png | ExportFormat::Svg)
}

fn all_diagnostic_dtos(
    engine: &[Diagnostic],
    dsl: &[DslDiagnostic],
    agent: &[AgentDiagnostic],
) -> Vec<AgentDiagnosticDto> {
    let mut diagnostics = Vec::new();
    diagnostics.extend(engine.iter().map(engine_diagnostic_dto));
    diagnostics.extend(dsl.iter().map(dsl_diagnostic_dto));
    diagnostics.extend(agent.iter().map(agent_diagnostic_dto));
    diagnostics
}

fn iteration_diagnostic_dtos(iteration: &AgentIteration) -> Vec<AgentDiagnosticDto> {
    let mut diagnostics = Vec::new();
    if let Some(dsl_output) = &iteration.dsl_output {
        diagnostics.extend(dsl_output.diagnostics.iter().map(dsl_diagnostic_dto));
    }
    diagnostics.extend(
        iteration
            .preflight_diagnostics
            .iter()
            .map(engine_diagnostic_dto),
    );
    if let Some(export_result) = &iteration.export_result {
        diagnostics.extend(export_result.diagnostics.iter().map(engine_diagnostic_dto));
    }
    if let Some(asset_result) = &iteration.asset_result {
        diagnostics.extend(asset_result.diagnostics.iter().map(agent_diagnostic_dto));
    }
    if let Some(critique) = &iteration.visual_critique {
        diagnostics.extend(critique.diagnostics.iter().map(agent_diagnostic_dto));
    }
    diagnostics
}

fn engine_diagnostic_dto(diagnostic: &Diagnostic) -> AgentDiagnosticDto {
    AgentDiagnosticDto {
        source: AgentDiagnosticSource::Engine,
        severity: diagnostic.severity.clone(),
        phase: Some(phase_name(&diagnostic.phase).to_owned()),
        code: diagnostic.code.clone(),
        message: diagnostic.message.clone(),
        subject: diagnostic.subject.clone(),
        hint: diagnostic.hint.clone(),
        line: None,
        column: None,
    }
}

fn dsl_diagnostic_dto(diagnostic: &DslDiagnostic) -> AgentDiagnosticDto {
    AgentDiagnosticDto {
        source: AgentDiagnosticSource::Dsl,
        severity: diagnostic.diagnostic.severity.clone(),
        phase: Some(phase_name(&diagnostic.diagnostic.phase).to_owned()),
        code: diagnostic.diagnostic.code.clone(),
        message: diagnostic.diagnostic.message.clone(),
        subject: diagnostic.diagnostic.subject.clone(),
        hint: diagnostic.diagnostic.hint.clone(),
        line: Some(diagnostic.span.line),
        column: Some(diagnostic.span.column),
    }
}

fn agent_diagnostic_dto(diagnostic: &AgentDiagnostic) -> AgentDiagnosticDto {
    AgentDiagnosticDto {
        source: AgentDiagnosticSource::Agent,
        severity: diagnostic.severity.clone(),
        phase: None,
        code: diagnostic.code.clone(),
        message: diagnostic.message.clone(),
        subject: diagnostic.subject.clone(),
        hint: diagnostic.hint.clone(),
        line: None,
        column: None,
    }
}

fn latest_diagnostics(audit: &[AgentDiagnosticDto]) -> Vec<AgentDiagnosticDto> {
    let mut latest = BTreeMap::new();
    for diagnostic in audit {
        latest.insert(diagnostic_key(diagnostic), diagnostic.clone());
    }
    latest.into_values().collect()
}

fn diagnostic_key(diagnostic: &AgentDiagnosticDto) -> String {
    format!(
        "{:?}:{:?}:{}:{:?}:{}:{}",
        diagnostic.source,
        diagnostic.severity,
        diagnostic.code,
        diagnostic.subject,
        diagnostic.line.unwrap_or_default(),
        diagnostic.column.unwrap_or_default()
    )
}

fn phase_name(phase: &lumen_core::Phase) -> &'static str {
    match phase {
        lumen_core::Phase::Contract => "contract",
        lumen_core::Phase::Operation => "operation",
        lumen_core::Phase::Validation => "validation",
        lumen_core::Phase::Brand => "brand",
        lumen_core::Phase::Dsl => "dsl",
        lumen_core::Phase::Layout => "layout",
        lumen_core::Phase::Export => "export",
        lumen_core::Phase::Web => "web",
    }
}

fn edit_surface_for_edit(edit: &AgentEdit) -> EditSurfaceRecommendation {
    match edit {
        AgentEdit::DslBlock { .. } => EditSurfaceRecommendation::Dsl,
        AgentEdit::StructuredOps { .. } => EditSurfaceRecommendation::StructuredOps,
        AgentEdit::AssetTool { .. } => EditSurfaceRecommendation::AssetTool,
    }
}

fn operation_kind(operation: &Operation) -> &'static str {
    match operation {
        Operation::AddPage { .. } => "add_page",
        Operation::RemovePage { .. } => "remove_page",
        Operation::UpdateDocument { .. } => "update_document",
        Operation::UpdatePage { .. } => "update_page",
        Operation::InsertNode { .. } => "insert_node",
        Operation::RemoveNode { .. } => "remove_node",
        Operation::MoveNode { .. } => "move_node",
        Operation::UpdateNode { .. } => "update_node",
        Operation::UpsertSlot { .. } => "upsert_slot",
        Operation::RemoveSlot { .. } => "remove_slot",
        Operation::BindNodeToSlot { .. } => "bind_node_to_slot",
        Operation::UnbindNodeFromSlot { .. } => "unbind_node_from_slot",
        Operation::SetBrandKitRef { .. } => "set_brand_kit_ref",
        Operation::UpsertExportProfile { .. } => "upsert_export_profile",
        Operation::RemoveExportProfile { .. } => "remove_export_profile",
        Operation::UpsertAsset { .. } => "upsert_asset",
        Operation::RemoveAsset { .. } => "remove_asset",
        Operation::PlaceAssetInNode { .. } => "place_asset_in_node",
        Operation::PlaceAssetInSlot { .. } => "place_asset_in_slot",
        Operation::FinalizeTemplate { .. } => "finalize_template",
    }
}
