use crate::assets::AssetStatus;
use crate::brand::{resolve_text_for_edit, BrandKit, TokenResolutionOptions};
use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::export_contract::{ExportFormat, PdfIntent, RasterScale};
use crate::ids::{AssetId, EffectId, NodeId, PageId, PaintId, SlotId, SlotKey};
use crate::operations::{
    DocumentPatch, FieldPatch, NodePatch, Operation, OperationError, OperationReport,
    OptionalFieldPatch, PagePatch,
};
use crate::scene::{
    AutoLayoutProps, Color, CornerRadii, Dimension, Effect, ExplicitTextTokens, Fill, LayoutMode,
    Node, NodeKind, PageSize, Paint, ParentRef, PositionMode, Rect, Scene, SizeSpec, Stroke,
    TextAlign, TextDirection, TextNode, TextSpan, TextTransform, TextWrap, Transform,
    VerticalAlign,
};
use crate::slots::{ImagePolicy, Slot};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

/// Optional pinned brand context for preserving effective text during edits.
/// Low-level callers without it retain their existing raw-field semantics.
#[derive(Clone, Copy)]
pub struct TextEditContext<'a> {
    pub brand_kit: &'a BrandKit,
    pub options: &'a TokenResolutionOptions,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum EditTargetRef {
    Document,
    Page(PageId),
    Node(NodeId),
    Slot(SlotId),
    SlotKey(SlotKey),
    Asset(AssetId),
    ExportProfile(String),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ResolvedEditTarget {
    pub target: EditTargetRef,
    pub parent: Option<ParentRef>,
    pub index: Option<usize>,
    pub node_kind: Option<NodeKind>,
    pub page_id: Option<PageId>,
    pub slot_bindings: Vec<NodeId>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EditErrorKind {
    TargetNotFound,
    AmbiguousTarget,
    UnsupportedTarget,
    UnsupportedProperty,
    LockedTarget,
    WouldCreateCycle,
    AnchorNotFound,
    IdCollision,
    IncompatibleReplacement,
    ProtectedSlot,
    RevisionMismatch,
    OperationFailed,
    ScopeViolation,
    LifecycleProtected,
}

impl EditErrorKind {
    pub fn code(&self) -> &'static str {
        match self {
            Self::TargetNotFound => "edit.target_not_found",
            Self::AmbiguousTarget => "edit.ambiguous_target",
            Self::UnsupportedTarget => "edit.unsupported_target",
            Self::UnsupportedProperty => "edit.unsupported_property",
            Self::LockedTarget => "edit.locked_target",
            Self::WouldCreateCycle => "edit.would_create_cycle",
            Self::AnchorNotFound => "edit.anchor_not_found",
            Self::IdCollision => "edit.id_collision",
            Self::IncompatibleReplacement => "edit.incompatible_replacement",
            Self::ProtectedSlot => "edit.protected_slot",
            Self::RevisionMismatch => "edit.revision_mismatch",
            Self::OperationFailed => "edit.operation_failed",
            Self::ScopeViolation => "edit.scope_violation",
            Self::LifecycleProtected => "edit.lifecycle_protected",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EditError {
    pub kind: EditErrorKind,
    pub message: String,
    pub target: Option<EditTargetRef>,
}

impl EditError {
    pub fn new(kind: EditErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            target: None,
        }
    }

    pub fn with_target(mut self, target: EditTargetRef) -> Self {
        self.target = Some(target);
        self
    }

    pub fn diagnostic(&self) -> Diagnostic {
        Diagnostic::error(
            Phase::Operation,
            self.kind.code(),
            self.message.clone(),
            self.target.as_ref().and_then(edit_target_subject),
        )
        .with_hint(
            "Build targeted edits through checked edit batches and repair only the failing target.",
        )
    }

    pub fn operation_error(&self) -> OperationError {
        OperationError::new(self.kind.code(), self.message.clone())
            .with_diagnostics(vec![self.diagnostic()])
    }
}

impl fmt::Display for EditError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind.code(), self.message)
    }
}

impl Error for EditError {}

/// Provenance for a cloned subtree: which source produced it and the
/// deterministic source-to-clone ID map, in subtree order. Persisted with
/// the edit envelope so repeater semantics (Phase G) and a future component
/// model can recover clone ancestry without archaeology.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CloneLineage {
    pub source_root: NodeId,
    pub id_map: Vec<(NodeId, NodeId)>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EditBatch {
    pub operations: Vec<Operation>,
    /// Inverse batch computed at build time against the pre-edit scene.
    /// `None` means the batch is not invertible (e.g. finalization).
    #[serde(default)]
    pub inverse_operations: Option<Vec<Operation>>,
    pub touched_targets: Vec<EditTargetRef>,
    pub checkpoint_label: Option<String>,
    pub intent: Option<String>,
    #[serde(default)]
    pub lineage: Option<CloneLineage>,
}

impl EditBatch {
    pub fn new(operations: Vec<Operation>, touched_targets: Vec<EditTargetRef>) -> Self {
        Self {
            operations,
            inverse_operations: None,
            touched_targets,
            checkpoint_label: None,
            intent: None,
            lineage: None,
        }
    }

    pub fn with_intent(mut self, intent: impl Into<String>) -> Self {
        self.intent = Some(intent.into());
        self
    }

    pub fn with_checkpoint(mut self, label: impl Into<String>) -> Self {
        self.checkpoint_label = Some(label.into());
        self
    }

    pub fn with_lineage(mut self, lineage: CloneLineage) -> Self {
        self.lineage = Some(lineage);
        self
    }

    /// Compute and attach the inverse batch against the pre-edit scene.
    /// Must be called while the scene still reflects the state this batch
    /// was built for; inverses are unobtainable later without replay.
    pub fn with_inverses(mut self, scene: &Scene) -> Result<Self, EditError> {
        let inverses = scene.invert_operations(&self.operations).map_err(|error| {
            EditError::new(
                EditErrorKind::OperationFailed,
                format!(
                    "failed to invert edit batch: {} {}",
                    error.code, error.message
                ),
            )
        })?;
        self.inverse_operations = inverses;
        Ok(self)
    }

    pub fn apply_checked(&self, scene: &mut Scene) -> Result<OperationReport, EditError> {
        scene
            .apply_operations_checked(self.operations.clone())
            .map_err(|error| {
                EditError::new(
                    EditErrorKind::OperationFailed,
                    format!("edit batch failed: {} {}", error.code, error.message),
                )
            })
    }
}

/// Declared edit scope for fail-closed agent repairs (Phase D decision:
/// strict for agents, advisory for humans).
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EditScopeMode {
    Strict,
    Advisory,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EditScope {
    pub mode: EditScopeMode,
    pub allowed: Vec<EditTargetRef>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ScopeViolation {
    pub operation_index: usize,
    pub target: EditTargetRef,
    pub reason: String,
}

impl ScopeViolation {
    pub fn diagnostic(&self) -> Diagnostic {
        Diagnostic::error(
            Phase::Operation,
            "edit.scope_violation",
            self.message(),
            edit_target_subject(&self.target),
        )
        .with_hint(
            "Declare every target the repair may touch, or narrow the patch to the declared targets.",
        )
    }

    pub fn advisory_diagnostic(&self) -> Diagnostic {
        Diagnostic::warning(
            Phase::Operation,
            "edit.scope_violation",
            self.message(),
            edit_target_subject(&self.target),
        )
        .with_hint("This edit touches targets outside the declared scope.")
    }

    fn message(&self) -> String {
        format!(
            "operation {} touches {:?} outside the declared edit scope: {}",
            self.operation_index, self.target, self.reason
        )
    }
}

/// Compute scope violations for an operation batch against declared allowed
/// targets. The allowed closure is:
///
/// - the declared targets themselves;
/// - descendants of every declared node (and nodes inserted under them
///   during this batch, which covers clone subtrees);
/// - child-list adjustments on the structural parent of a moved, inserted,
///   or removed node that is itself in closure — a same-parent reorder of an
///   allowed node is in scope, but moving it into an unrelated container is
///   not;
/// - slots whose bindings reference an allowed node (safe delete clears
///   bindings; clone may bind or derive slots for cloned nodes).
///
/// Declared targets must resolve; a missing declared target is an error,
/// not an empty scope.
pub fn batch_scope_violations(
    scene: &Scene,
    operations: &[Operation],
    allowed: &[EditTargetRef],
) -> Result<Vec<ScopeViolation>, EditError> {
    let mut allowed_nodes: BTreeSet<NodeId> = BTreeSet::new();
    let mut allowed_pages: BTreeSet<PageId> = BTreeSet::new();
    let mut allowed_slots: BTreeSet<SlotId> = BTreeSet::new();
    let mut allowed_assets: BTreeSet<AssetId> = BTreeSet::new();
    let mut allowed_profiles: BTreeSet<String> = BTreeSet::new();
    let mut document_allowed = false;

    for target in allowed {
        let resolved = resolve_edit_target(scene, target)?;
        match &resolved.target {
            EditTargetRef::Document => document_allowed = true,
            EditTargetRef::Page(page_id) => {
                allowed_pages.insert(page_id.clone());
            }
            EditTargetRef::Node(node_id) => {
                allowed_nodes.insert(node_id.clone());
                for descendant in scene.descendants_of(node_id) {
                    allowed_nodes.insert(descendant);
                }
            }
            EditTargetRef::Slot(slot_id) => {
                allowed_slots.insert(slot_id.clone());
            }
            EditTargetRef::SlotKey(_) => unreachable!("slot keys resolve to slot ids"),
            EditTargetRef::Asset(asset_id) => {
                allowed_assets.insert(asset_id.clone());
            }
            EditTargetRef::ExportProfile(name) => {
                allowed_profiles.insert(name.clone());
            }
        }
    }

    let node_allowed = |nodes: &BTreeSet<NodeId>, node_id: &NodeId| nodes.contains(node_id);
    let parent_allowed = |nodes: &BTreeSet<NodeId>, parent: &ParentRef| match parent {
        ParentRef::Page(page_id) => allowed_pages.contains(page_id),
        ParentRef::Node(node_id) => nodes.contains(node_id),
    };
    let slot_allowed = |nodes: &BTreeSet<NodeId>, slot_id: &SlotId| {
        if allowed_slots.contains(slot_id) {
            return true;
        }
        scene
            .slots
            .get(slot_id)
            .map(|slot| slot.bound_nodes.iter().any(|id| nodes.contains(id)))
            .unwrap_or(false)
    };

    let mut violations = Vec::new();
    let mut violation = |index: usize, target: EditTargetRef, reason: &str| {
        violations.push(ScopeViolation {
            operation_index: index,
            target,
            reason: reason.to_owned(),
        });
    };

    for (index, operation) in operations.iter().enumerate() {
        match operation {
            Operation::UpdateNode { node_id, .. } | Operation::RemoveNode { node_id } => {
                if !node_allowed(&allowed_nodes, node_id) {
                    violation(
                        index,
                        EditTargetRef::Node(node_id.clone()),
                        "node is not a declared target or descendant",
                    );
                }
            }
            Operation::InsertNode { parent, node, .. } => {
                if parent_allowed(&allowed_nodes, parent) {
                    allowed_nodes.insert(node.id.clone());
                } else {
                    violation(
                        index,
                        EditTargetRef::Node(node.id.clone()),
                        "insert parent is outside the declared scope",
                    );
                }
            }
            Operation::MoveNode {
                node_id,
                new_parent,
                ..
            } => {
                if !node_allowed(&allowed_nodes, node_id) {
                    violation(
                        index,
                        EditTargetRef::Node(node_id.clone()),
                        "moved node is not a declared target or descendant",
                    );
                } else {
                    let reorder_in_place = scene.parent_of(node_id).as_ref() == Some(new_parent);
                    if !reorder_in_place && !parent_allowed(&allowed_nodes, new_parent) {
                        violation(
                            index,
                            EditTargetRef::Node(node_id.clone()),
                            "move destination is outside the declared scope",
                        );
                    }
                }
            }
            Operation::UpdatePage { page_id, .. } => {
                if !allowed_pages.contains(page_id) {
                    violation(
                        index,
                        EditTargetRef::Page(page_id.clone()),
                        "page is not a declared target",
                    );
                }
            }
            Operation::AddPage { page } => {
                if !allowed_pages.contains(&page.id) {
                    violation(
                        index,
                        EditTargetRef::Page(page.id.clone()),
                        "page creation must be declared explicitly",
                    );
                }
            }
            Operation::RemovePage { page_id } => {
                if !allowed_pages.contains(page_id) {
                    violation(
                        index,
                        EditTargetRef::Page(page_id.clone()),
                        "page deletion must be declared explicitly",
                    );
                }
            }
            Operation::UpdateDocument { .. } | Operation::SetBrandKitRef { .. } => {
                if !document_allowed {
                    violation(
                        index,
                        EditTargetRef::Document,
                        "document-level changes must declare the document target",
                    );
                }
            }
            Operation::UpsertSlot { slot } => {
                let existing = scene.slots.contains_key(&slot.id);
                let bindings_in_scope = slot
                    .bound_nodes
                    .iter()
                    .all(|id| node_allowed(&allowed_nodes, id));
                let permitted = if existing {
                    slot_allowed(&allowed_nodes, &slot.id)
                } else {
                    // New slots (e.g. clone slots:suffix) are in scope when
                    // they bind only nodes inside the closure.
                    !slot.bound_nodes.is_empty() && bindings_in_scope
                };
                if !permitted {
                    violation(
                        index,
                        EditTargetRef::Slot(slot.id.clone()),
                        "slot is not declared and not bound to declared nodes",
                    );
                }
            }
            Operation::RemoveSlot { slot_id } => {
                if !slot_allowed(&allowed_nodes, slot_id) {
                    violation(
                        index,
                        EditTargetRef::Slot(slot_id.clone()),
                        "slot deletion must be declared or bound to declared nodes",
                    );
                }
            }
            Operation::BindNodeToSlot { slot_id, node_id }
            | Operation::UnbindNodeFromSlot { slot_id, node_id } => {
                if !slot_allowed(&allowed_nodes, slot_id) && !node_allowed(&allowed_nodes, node_id)
                {
                    violation(
                        index,
                        EditTargetRef::Slot(slot_id.clone()),
                        "binding change touches neither a declared slot nor a declared node",
                    );
                }
            }
            Operation::UpsertAsset { asset } => {
                if !allowed_assets.contains(&asset.id) {
                    violation(
                        index,
                        EditTargetRef::Asset(asset.id.clone()),
                        "asset is not a declared target",
                    );
                }
            }
            Operation::RemoveAsset { asset_id } => {
                if !allowed_assets.contains(asset_id) {
                    violation(
                        index,
                        EditTargetRef::Asset(asset_id.clone()),
                        "asset deletion must be declared explicitly",
                    );
                }
            }
            Operation::PlaceAssetInNode { node_id, .. } => {
                if !node_allowed(&allowed_nodes, node_id) {
                    violation(
                        index,
                        EditTargetRef::Node(node_id.clone()),
                        "asset placement target is not a declared node",
                    );
                }
            }
            Operation::PlaceAssetInSlot { slot_id, .. } => {
                if !slot_allowed(&allowed_nodes, slot_id) {
                    violation(
                        index,
                        EditTargetRef::Slot(slot_id.clone()),
                        "asset placement slot is not declared",
                    );
                }
            }
            Operation::UpsertExportProfile { profile } => {
                if !allowed_profiles.contains(&profile.name) {
                    violation(
                        index,
                        EditTargetRef::ExportProfile(profile.name.clone()),
                        "export profile is not a declared target",
                    );
                }
            }
            Operation::RemoveExportProfile { name } => {
                if !allowed_profiles.contains(name) {
                    violation(
                        index,
                        EditTargetRef::ExportProfile(name.clone()),
                        "export profile deletion must be declared explicitly",
                    );
                }
            }
            Operation::FinalizeTemplate { .. } => {
                violation(
                    index,
                    EditTargetRef::Document,
                    "finalization is a lifecycle action, never a scoped repair",
                );
            }
        }
    }

    Ok(violations)
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct TextEditPatch {
    pub content: FieldPatch<String>,
    pub font_family: FieldPatch<String>,
    pub font_size: FieldPatch<f64>,
    pub font_weight: FieldPatch<u16>,
    pub align: FieldPatch<TextAlign>,
    pub line_height: FieldPatch<f64>,
    pub letter_spacing: FieldPatch<f64>,
    pub max_lines: OptionalFieldPatch<u16>,
    pub wrap: FieldPatch<TextWrap>,
    pub direction: FieldPatch<TextDirection>,
    pub style_token: OptionalFieldPatch<String>,
    pub font_size_token: OptionalFieldPatch<String>,
    pub line_height_token: OptionalFieldPatch<String>,
    pub letter_spacing_token: OptionalFieldPatch<String>,
    // A6a typography v1. None of these are token channels, so they never
    // interact with `clear_stale_tokens`.
    pub text_transform: FieldPatch<TextTransform>,
    pub underline: FieldPatch<bool>,
    pub strikethrough: FieldPatch<bool>,
    /// A7b: italic style. A geometry channel (measurement input), but content
    /// edits PRESERVE it — like `valign` and unlike `spans` (whose offsets go
    /// stale). Not a token channel.
    pub italic: FieldPatch<bool>,
    pub truncate: FieldPatch<bool>,
    pub paragraph_spacing: FieldPatch<f64>,
    /// A7a: vertical alignment within the box. Not a token channel, so it never
    /// interacts with `clear_stale_tokens`.
    pub valign: FieldPatch<VerticalAlign>,
    /// A6b D4: rich-text spans. A patch that changes `content` without ALSO
    /// setting `spans` CLEARS spans — stale byte offsets are silent corruption,
    /// so a content edit that doesn't re-author its spans drops them (undo
    /// restores the prior spans through the existing inverse mechanism). A patch
    /// that sets both applies both.
    pub spans: FieldPatch<Vec<TextSpan>>,
}

impl TextEditPatch {
    fn explicit_tokens(&self) -> ExplicitTextTokens {
        ExplicitTextTokens {
            style: !self.style_token.is_unchanged(),
            font_size: !self.font_size_token.is_unchanged(),
            line_height: !self.line_height_token.is_unchanged(),
            letter_spacing: !self.letter_spacing_token.is_unchanged(),
        }
    }
}

/// One targeted edit against a fill/stroke/effect stack entry, addressed by
/// the entry's stable id (Effects Contract V0 / Phase D extension). Entry
/// edits compose: they apply in order on top of any whole-stack patch, and
/// unrelated entries are never touched.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StackEntryEdit<T, I> {
    /// Replace the entry currently addressed by `id` with `value` (the
    /// value's own id may differ to rename the entry).
    Set { id: I, value: T },
    /// Insert a new entry, at `index` or appended when omitted.
    Add {
        entry: T,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        index: Option<usize>,
    },
    /// Remove the entry addressed by `id`.
    Remove { id: I },
    /// Move the entry addressed by `id` to `index` (within the stack after
    /// the entry is detached).
    Reorder { id: I, index: usize },
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct NodeEditPatch {
    pub name: OptionalFieldPatch<String>,
    pub transform: FieldPatch<Transform>,
    pub size: FieldPatch<SizeSpec>,
    /// Phase 4c: pinned-node moves (`p()`/`s()` on `position_mode: absolute`
    /// targets) lower here instead of `transform`, since the solver lays
    /// pinned nodes out at `absolute_box`, page-space, and ignores
    /// `transform`. Skipped when unchanged so pinned pre-existing wire
    /// fixtures stay byte-identical (mirrors `NodePatch::absolute_box` in
    /// operations.rs).
    #[serde(skip_serializing_if = "OptionalFieldPatch::is_unchanged")]
    pub absolute_box: OptionalFieldPatch<Rect>,
    pub fills: FieldPatch<Vec<Fill>>,
    pub strokes: FieldPatch<Vec<Stroke>>,
    #[serde(skip_serializing_if = "FieldPatch::is_unchanged")]
    pub effects: FieldPatch<Vec<Effect>>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub fill_edits: Vec<StackEntryEdit<Fill, PaintId>>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub stroke_edits: Vec<StackEntryEdit<Stroke, PaintId>>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub effect_edits: Vec<StackEntryEdit<Effect, EffectId>>,
    pub corner: FieldPatch<CornerRadii>,
    pub opacity: FieldPatch<f64>,
    pub opacity_token: OptionalFieldPatch<String>,
    pub clip: FieldPatch<bool>,
    #[serde(skip_serializing_if = "FieldPatch::is_unchanged")]
    pub bleed: FieldPatch<bool>,
    pub layout: OptionalFieldPatch<AutoLayoutProps>,
    pub source_asset_id: OptionalFieldPatch<AssetId>,
    pub asset_placement: OptionalFieldPatch<crate::assets::AssetPlacement>,
    pub locked: FieldPatch<bool>,
    pub text: Option<TextEditPatch>,
    pub image_asset_id: OptionalFieldPatch<AssetId>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct PageEditPatch {
    pub name: FieldPatch<String>,
    pub size: FieldPatch<PageSize>,
    pub bleed: OptionalFieldPatch<Rect>,
    pub safe_area: OptionalFieldPatch<Rect>,
    pub background: FieldPatch<Vec<Fill>>,
}

impl From<PageEditPatch> for PagePatch {
    fn from(patch: PageEditPatch) -> Self {
        Self {
            name: patch.name,
            size: patch.size,
            bleed: patch.bleed,
            safe_area: patch.safe_area,
            background: patch.background,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct SlotEditPatch {
    pub label: FieldPatch<String>,
    pub required: FieldPatch<bool>,
    pub placeholder: OptionalFieldPatch<String>,
    pub sample: OptionalFieldPatch<String>,
    pub worst_case: OptionalFieldPatch<String>,
    pub bind_nodes: Vec<NodeId>,
    pub unbind_nodes: Vec<NodeId>,
    /// The author-reachable repair for `LUMV0820`. `Set` installs a policy on
    /// an image-like slot; `Clear` removes one (the only legitimate use is a
    /// slot that is no longer image-like). Reached from the DSL as
    /// `#slot:key image_policy(fit=cover, …)` / `image_policy(none)`.
    pub image_policy: OptionalFieldPatch<ImagePolicy>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct AssetEditPatch {
    pub label: FieldPatch<String>,
    pub status: FieldPatch<AssetStatus>,
}

/// Sparse patch over an existing export profile. Missing fields default to
/// unchanged; the patch lowers to `UpsertExportProfile` with the merged
/// profile.
///
/// This struct is a hand-written mirror of [`ExportProfile`]'s shape — the
/// completeness test in this module fails whenever the profile grows a
/// field the patch cannot express (the drift bit three times: this struct
/// missed four print features, and the API normalize whitelist dropped
/// `include_marks` and then `imposition`/`proof`).
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ExportProfileEditPatch {
    pub format: FieldPatch<ExportFormat>,
    pub pdf_intent: OptionalFieldPatch<PdfIntent>,
    pub raster: OptionalFieldPatch<RasterScale>,
    pub include_bleed: FieldPatch<bool>,
    pub embed_fonts: FieldPatch<bool>,
    pub include_marks: FieldPatch<bool>,
    pub imposition: OptionalFieldPatch<String>,
    pub proof: FieldPatch<bool>,
    pub color: OptionalFieldPatch<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
pub enum EditPatch {
    Node(NodeEditPatch),
    Page(PageEditPatch),
    Slot(SlotEditPatch),
    Asset(AssetEditPatch),
    Document(DocumentPatch),
    ExportProfile(ExportProfileEditPatch),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RelativePlacement {
    Before { anchor: NodeId },
    After { anchor: NodeId },
    ParentIndex { parent: ParentRef, index: usize },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CloneSlotPolicy {
    Detach,
    Copy,
    Suffix(String),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ComputedClonePolicy {
    Clear,
    Preserve,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CloneSubtreeRequest {
    pub source: NodeId,
    pub new_root_id: NodeId,
    pub placement: RelativePlacement,
    pub slot_policy: CloneSlotPolicy,
    pub computed_policy: ComputedClonePolicy,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplaceSlotPolicy {
    Detach,
    PreserveCompatible,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplaceNodeRequest {
    pub target: NodeId,
    pub replacement: NodeId,
    pub slot_policy: ReplaceSlotPolicy,
}

pub fn resolve_edit_target(
    scene: &Scene,
    target: &EditTargetRef,
) -> Result<ResolvedEditTarget, EditError> {
    match target {
        EditTargetRef::Document => Ok(ResolvedEditTarget {
            target: target.clone(),
            parent: None,
            index: None,
            node_kind: None,
            page_id: None,
            slot_bindings: Vec::new(),
        }),
        EditTargetRef::Page(page_id) => {
            let page = scene.pages.get(page_id).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("page {} does not exist", page_id),
                )
                .with_target(target.clone())
            })?;
            Ok(ResolvedEditTarget {
                target: target.clone(),
                parent: None,
                index: None,
                node_kind: None,
                page_id: Some(page.id.clone()),
                slot_bindings: Vec::new(),
            })
        }
        EditTargetRef::Node(node_id) => {
            let node = scene.nodes.get(node_id).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("node {} does not exist", node_id),
                )
                .with_target(target.clone())
            })?;
            let parent = scene.parent_of(node_id);
            let index = parent
                .as_ref()
                .and_then(|parent| children_for_parent(scene, parent).ok())
                .and_then(|children| children.iter().position(|id| id == node_id));
            Ok(ResolvedEditTarget {
                target: target.clone(),
                parent: parent.clone(),
                index,
                node_kind: Some(node.kind.clone()),
                page_id: parent
                    .as_ref()
                    .and_then(|parent| page_for_parent(scene, parent)),
                slot_bindings: Vec::new(),
            })
        }
        EditTargetRef::Slot(slot_id) => {
            let slot = scene.slots.get(slot_id).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("slot {} does not exist", slot_id),
                )
                .with_target(target.clone())
            })?;
            Ok(ResolvedEditTarget {
                target: target.clone(),
                parent: None,
                index: None,
                node_kind: None,
                page_id: None,
                slot_bindings: slot.bound_nodes.clone(),
            })
        }
        EditTargetRef::SlotKey(slot_key) => {
            let slot = scene.slot_by_key(slot_key).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("slot key {} does not exist", slot_key),
                )
                .with_target(target.clone())
            })?;
            Ok(ResolvedEditTarget {
                target: EditTargetRef::Slot(slot.id.clone()),
                parent: None,
                index: None,
                node_kind: None,
                page_id: None,
                slot_bindings: slot.bound_nodes.clone(),
            })
        }
        EditTargetRef::Asset(asset_id) => {
            if !scene.assets.contains_key(asset_id) {
                return Err(EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("asset {} does not exist", asset_id),
                )
                .with_target(target.clone()));
            }
            Ok(ResolvedEditTarget {
                target: target.clone(),
                parent: None,
                index: None,
                node_kind: None,
                page_id: None,
                slot_bindings: Vec::new(),
            })
        }
        EditTargetRef::ExportProfile(name) => {
            if scene.export_profile(name).is_none() {
                return Err(EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("export profile {} does not exist", name),
                )
                .with_target(target.clone()));
            }
            Ok(ResolvedEditTarget {
                target: target.clone(),
                parent: None,
                index: None,
                node_kind: None,
                page_id: None,
                slot_bindings: Vec::new(),
            })
        }
    }
}

pub fn build_modify_operations(
    scene: &Scene,
    target: EditTargetRef,
    patch: EditPatch,
) -> Result<EditBatch, EditError> {
    build_modify_operations_with_text_context(scene, target, patch, None)
}

pub fn build_modify_operations_with_text_context(
    scene: &Scene,
    target: EditTargetRef,
    patch: EditPatch,
    context: Option<TextEditContext<'_>>,
) -> Result<EditBatch, EditError> {
    match (target, patch) {
        (EditTargetRef::Node(node_id), EditPatch::Node(patch)) => {
            build_node_modify_with_text_context(scene, node_id, patch, context)
        }
        (EditTargetRef::Page(page_id), EditPatch::Page(patch)) => {
            build_page_modify(scene, page_id, patch)
        }
        (EditTargetRef::Slot(slot_id), EditPatch::Slot(patch)) => {
            build_slot_modify(scene, EditTargetRef::Slot(slot_id), patch)
        }
        (EditTargetRef::SlotKey(slot_key), EditPatch::Slot(patch)) => {
            build_slot_modify(scene, EditTargetRef::SlotKey(slot_key), patch)
        }
        (EditTargetRef::Asset(asset_id), EditPatch::Asset(patch)) => {
            build_asset_modify(scene, asset_id, patch)
        }
        (EditTargetRef::Document, EditPatch::Document(patch)) => {
            build_document_modify(scene, patch)
        }
        (EditTargetRef::ExportProfile(name), EditPatch::ExportProfile(patch)) => {
            build_export_profile_modify(scene, name, patch)
        }
        (target, _) => Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!("patch cannot be applied to target {:?}", target),
        )
        .with_target(target)),
    }
}

pub fn build_document_modify(scene: &Scene, patch: DocumentPatch) -> Result<EditBatch, EditError> {
    EditBatch::new(
        vec![Operation::UpdateDocument { patch }],
        vec![EditTargetRef::Document],
    )
    .with_intent("modify_document")
    .with_inverses(scene)
}

pub fn build_export_profile_modify(
    scene: &Scene,
    name: String,
    patch: ExportProfileEditPatch,
) -> Result<EditBatch, EditError> {
    let mut profile = scene.export_profile(&name).cloned().ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("export profile {} does not exist", name),
        )
        .with_target(EditTargetRef::ExportProfile(name.clone()))
    })?;

    apply_field_patch(&mut profile.format, patch.format);
    apply_optional_patch(&mut profile.pdf_intent, patch.pdf_intent);
    apply_optional_patch(&mut profile.raster, patch.raster);
    apply_field_patch(&mut profile.include_bleed, patch.include_bleed);
    apply_field_patch(&mut profile.embed_fonts, patch.embed_fonts);
    apply_field_patch(&mut profile.include_marks, patch.include_marks);
    apply_optional_patch(&mut profile.imposition, patch.imposition);
    apply_field_patch(&mut profile.proof, patch.proof);
    apply_optional_patch(&mut profile.color, patch.color);

    EditBatch::new(
        vec![Operation::UpsertExportProfile { profile }],
        vec![EditTargetRef::ExportProfile(name)],
    )
    .with_intent("modify_export_profile")
    .with_inverses(scene)
}

pub fn build_node_modify(
    scene: &Scene,
    node_id: NodeId,
    patch: NodeEditPatch,
) -> Result<EditBatch, EditError> {
    build_node_modify_with_text_context(scene, node_id, patch, None)
}

fn build_node_modify_with_text_context(
    scene: &Scene,
    node_id: NodeId,
    patch: NodeEditPatch,
    context: Option<TextEditContext<'_>>,
) -> Result<EditBatch, EditError> {
    let node = scene.nodes.get(&node_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} does not exist", node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone()))
    })?;

    if node.locked && !matches!(patch.locked, FieldPatch::Set(false)) {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }

    let mut operations = Vec::new();

    if let OptionalFieldPatch::Set(asset_id) = &patch.image_asset_id {
        if !scene.assets.contains_key(asset_id) {
            return Err(EditError::new(
                EditErrorKind::TargetNotFound,
                format!("asset {} does not exist", asset_id),
            )
            .with_target(EditTargetRef::Asset(asset_id.clone())));
        }
        operations.push(Operation::PlaceAssetInNode {
            node_id: node_id.clone(),
            asset_id: asset_id.clone(),
            placement: match &patch.asset_placement {
                OptionalFieldPatch::Set(placement) => placement.clone(),
                _ => crate::assets::AssetPlacement::default(),
            },
        });
    }

    let fills = resolve_stack_patch(
        &node.fills,
        patch.fills,
        &patch.fill_edits,
        |fill| &fill.id,
        "fill",
        &node_id,
    )?;
    let strokes = resolve_stack_patch(
        &node.strokes,
        patch.strokes,
        &patch.stroke_edits,
        |stroke| &stroke.id,
        "stroke",
        &node_id,
    )?;
    let effects = resolve_stack_patch(
        &node.effects,
        patch.effects,
        &patch.effect_edits,
        |effect| &effect.id,
        "effect",
        &node_id,
    )?;

    let mut node_patch = NodePatch {
        name: patch.name,
        transform: patch.transform,
        size: patch.size,
        absolute_box: patch.absolute_box,
        fills,
        strokes,
        effects,
        corner: patch.corner,
        opacity: patch.opacity,
        opacity_token: patch.opacity_token,
        source_asset_id: patch.source_asset_id,
        asset_placement: patch.asset_placement,
        clip: patch.clip,
        bleed: patch.bleed,
        layout: patch.layout,
        computed: OptionalFieldPatch::Unchanged,
        locked: patch.locked,
        ..NodePatch::default()
    };

    let fills_changing =
        matches!(&node_patch.fills, FieldPatch::Set(fills) if *fills != node.fills);
    // A fills-only operation also carries text: its later replay may target an
    // authored role-bound node even when this working draft was preflighted.
    if patch.text.is_some() || (fills_changing && matches!(node.kind, NodeKind::Text(_))) {
        let text_patch = patch.text.unwrap_or_default();
        let NodeKind::Text(current_text) = &node.kind else {
            return Err(EditError::new(
                EditErrorKind::UnsupportedProperty,
                format!("text patch cannot be applied to non-text node {}", node_id),
            )
            .with_target(EditTargetRef::Node(node_id)));
        };
        let mut explicit = text_patch.explicit_tokens();
        let (source, prepared) = prepare_text_edit_source(
            scene,
            &node_id,
            current_text,
            &text_patch,
            fills_changing,
            context,
        )?;
        let mut next_text = apply_text_edit_patch(source, text_patch);
        if fills_changing && !explicit.style {
            next_text.style_token = None;
        }
        if prepared {
            // Preserved source tokens are intentional even when materializing
            // their raw fallback changed it relative to the authored scene.
            explicit.font_size |= next_text.font_size_token.is_some();
            explicit.line_height |= next_text.line_height_token.is_some();
            explicit.letter_spacing |= next_text.letter_spacing_token.is_some();
        }
        node_patch.explicit_text_tokens = (!explicit.is_empty()).then_some(explicit);
        node_patch.kind = FieldPatch::Set(NodeKind::Text(next_text));
    }

    if node_patch_affects_render(&node_patch)
        || !matches!(patch.image_asset_id, OptionalFieldPatch::Unchanged)
    {
        node_patch.computed = OptionalFieldPatch::Clear;
    }

    if node_patch_has_changes(&node_patch) {
        operations.push(Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: node_patch,
        });
    }

    if operations.is_empty() {
        return Ok(EditBatch::new(
            Vec::new(),
            vec![EditTargetRef::Node(node_id)],
        ));
    }

    EditBatch::new(operations, vec![EditTargetRef::Node(node_id)])
        .with_intent("modify_node")
        .with_inverses(scene)
}

fn prepare_text_edit_source(
    scene: &Scene,
    node_id: &NodeId,
    before: &TextNode,
    patch: &TextEditPatch,
    fills_changing: bool,
    context: Option<TextEditContext<'_>>,
) -> Result<(TextNode, bool), EditError> {
    let Some(context) = context else {
        return Ok((before.clone(), false));
    };
    let raw_type_edit = !patch.font_family.is_unchanged()
        || !patch.font_size.is_unchanged()
        || !patch.font_weight.is_unchanged()
        || !patch.line_height.is_unchanged()
        || !patch.letter_spacing.is_unchanged();
    if matches!(patch.style_token, OptionalFieldPatch::Set(_))
        || (!fills_changing
            && !raw_type_edit
            && !matches!(patch.style_token, OptionalFieldPatch::Clear))
    {
        return Ok((before.clone(), false));
    }
    let resolve = |text: &TextNode| {
        resolve_text_for_edit(scene, node_id, text, context.brand_kit, context.options).map_err(
            |diagnostics| {
                EditError::new(
                    EditErrorKind::UnsupportedProperty,
                    format!(
                        "cannot preserve effective typography: {}",
                        diagnostics
                            .iter()
                            .map(|diagnostic| diagnostic.message.as_str())
                            .collect::<Vec<_>>()
                            .join("; ")
                    ),
                )
                .with_target(EditTargetRef::Node(node_id.clone()))
            },
        )
    };
    let effective = resolve(before)?;
    let mut source = before.clone();
    source.font_family = effective.font_family;
    source.font_size = effective.font_size;
    source.font_weight = effective.font_weight;
    source.line_height = effective.line_height;
    source.letter_spacing = effective.letter_spacing;
    let after = apply_text_edit_patch(source.clone(), patch.clone());
    if !fills_changing
        && after.style_token == before.style_token
        && after.font_size_token == before.font_size_token
        && after.line_height_token == before.line_height_token
        && after.letter_spacing_token == before.letter_spacing_token
        && !matches!(patch.style_token, OptionalFieldPatch::Clear)
    {
        return Ok((before.clone(), false));
    }
    let mut detached = before.clone();
    detached.style_token = None;
    // Resolve the detached channels to ensure a token previously shadowed by
    // the role cannot wake up and replace the value the user saw.
    let detached = resolve(&detached)?;
    source.style_token = None;
    if detached.font_size != source.font_size {
        source.font_size_token = None;
    }
    if detached.line_height != source.line_height {
        source.line_height_token = None;
    }
    if detached.letter_spacing != source.letter_spacing {
        source.letter_spacing_token = None;
    }
    Ok((source, true))
}

pub fn build_page_modify(
    scene: &Scene,
    page_id: PageId,
    patch: PageEditPatch,
) -> Result<EditBatch, EditError> {
    if !scene.pages.contains_key(&page_id) {
        return Err(EditError::new(
            EditErrorKind::TargetNotFound,
            format!("page {} does not exist", page_id),
        )
        .with_target(EditTargetRef::Page(page_id)));
    }
    EditBatch::new(
        vec![Operation::UpdatePage {
            page_id: page_id.clone(),
            patch: patch.into(),
        }],
        vec![EditTargetRef::Page(page_id)],
    )
    .with_intent("modify_page")
    .with_inverses(scene)
}

pub fn build_slot_modify(
    scene: &Scene,
    target: EditTargetRef,
    patch: SlotEditPatch,
) -> Result<EditBatch, EditError> {
    let slot = match &target {
        EditTargetRef::Slot(slot_id) => scene.slots.get(slot_id),
        EditTargetRef::SlotKey(slot_key) => scene.slot_by_key(slot_key),
        _ => None,
    }
    .cloned()
    .ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("slot target {:?} does not exist", target),
        )
        .with_target(target.clone())
    })?;

    let mut next_slot = slot.clone();
    apply_field_patch(&mut next_slot.label, patch.label);
    apply_field_patch(&mut next_slot.required, patch.required);
    apply_optional_patch(&mut next_slot.placeholder, patch.placeholder);
    match patch.sample {
        OptionalFieldPatch::Unchanged => {}
        OptionalFieldPatch::Set(sample) => next_slot.validation.samples = vec![sample],
        OptionalFieldPatch::Clear => next_slot.validation.samples.clear(),
    }
    apply_optional_patch(&mut next_slot.validation.worst_case, patch.worst_case);
    apply_optional_patch(&mut next_slot.image_policy, patch.image_policy);

    let mut operations = vec![Operation::UpsertSlot {
        slot: next_slot.clone(),
    }];

    for node_id in patch.bind_nodes {
        if !scene.nodes.contains_key(&node_id) {
            return Err(EditError::new(
                EditErrorKind::TargetNotFound,
                format!(
                    "cannot bind missing node {} to slot {}",
                    node_id, next_slot.id
                ),
            )
            .with_target(EditTargetRef::Node(node_id)));
        }
        operations.push(Operation::BindNodeToSlot {
            slot_id: next_slot.id.clone(),
            node_id,
        });
    }

    for node_id in patch.unbind_nodes {
        operations.push(Operation::UnbindNodeFromSlot {
            slot_id: next_slot.id.clone(),
            node_id,
        });
    }

    EditBatch::new(operations, vec![EditTargetRef::Slot(next_slot.id)])
        .with_intent("modify_slot")
        .with_inverses(scene)
}

pub fn build_asset_modify(
    scene: &Scene,
    asset_id: AssetId,
    patch: AssetEditPatch,
) -> Result<EditBatch, EditError> {
    let mut asset = scene.assets.get(&asset_id).cloned().ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("asset {} does not exist", asset_id),
        )
        .with_target(EditTargetRef::Asset(asset_id.clone()))
    })?;

    apply_field_patch(&mut asset.label, patch.label);
    apply_field_patch(&mut asset.status, patch.status);

    EditBatch::new(
        vec![Operation::UpsertAsset {
            asset: asset.clone(),
        }],
        vec![EditTargetRef::Asset(asset.id)],
    )
    .with_intent("modify_asset")
    .with_inverses(scene)
}

pub fn build_safe_delete(scene: &Scene, node_id: NodeId) -> Result<EditBatch, EditError> {
    let node = scene.nodes.get(&node_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} does not exist", node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone()))
    })?;
    if node.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    for descendant_id in scene.descendants_of(&node_id) {
        if scene
            .nodes
            .get(&descendant_id)
            .map(|node| node.locked)
            .unwrap_or(false)
        {
            return Err(EditError::new(
                EditErrorKind::LockedTarget,
                format!("descendant node {} is locked", descendant_id),
            )
            .with_target(EditTargetRef::Node(descendant_id)));
        }
    }

    EditBatch::new(
        vec![Operation::RemoveNode {
            node_id: node_id.clone(),
        }],
        vec![EditTargetRef::Node(node_id)],
    )
    .with_intent("safe_delete")
    .with_inverses(scene)
}

/// Safe page delete (Phase D Decision 3): the last page is protected, node
/// subtrees cascade through the canonical RemovePage, slot bindings to
/// deleted nodes clear, and slot definitions survive so preflight flags the
/// personalization-contract gap visibly.
pub fn build_safe_delete_page(scene: &Scene, page_id: PageId) -> Result<EditBatch, EditError> {
    let page = scene.pages.get(&page_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("page {} does not exist", page_id),
        )
        .with_target(EditTargetRef::Page(page_id.clone()))
    })?;
    if scene.pages.len() <= 1 {
        return Err(EditError::new(
            EditErrorKind::LifecycleProtected,
            "cannot delete the last page of a document",
        )
        .with_target(EditTargetRef::Page(page_id)));
    }
    for child_id in &page.children {
        let mut subtree = vec![child_id.clone()];
        subtree.extend(scene.descendants_of(child_id));
        for node_id in subtree {
            if scene
                .nodes
                .get(&node_id)
                .map(|node| node.locked)
                .unwrap_or(false)
            {
                return Err(EditError::new(
                    EditErrorKind::LockedTarget,
                    format!("page contains locked node {}", node_id),
                )
                .with_target(EditTargetRef::Node(node_id)));
            }
        }
    }

    EditBatch::new(
        vec![Operation::RemovePage {
            page_id: page_id.clone(),
        }],
        vec![EditTargetRef::Page(page_id)],
    )
    .with_intent("delete_page")
    .with_inverses(scene)
}

/// Safe slot delete (Phase D Decision 4): hard delete in drafts (finalized
/// revisions reject all mutation), unbinds nodes by removing the slot
/// record, and never deletes the bound nodes themselves.
pub fn build_safe_delete_slot(
    scene: &Scene,
    target: EditTargetRef,
) -> Result<EditBatch, EditError> {
    let slot = match &target {
        EditTargetRef::Slot(slot_id) => scene.slots.get(slot_id),
        EditTargetRef::SlotKey(slot_key) => scene.slot_by_key(slot_key),
        _ => {
            return Err(EditError::new(
                EditErrorKind::UnsupportedTarget,
                "slot delete requires a slot or slot-key target",
            )
            .with_target(target));
        }
    }
    .ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("slot target {:?} does not exist", target),
        )
        .with_target(target.clone())
    })?;

    EditBatch::new(
        vec![Operation::RemoveSlot {
            slot_id: slot.id.clone(),
        }],
        vec![EditTargetRef::Slot(slot.id.clone())],
    )
    .with_intent("delete_slot")
    .with_inverses(scene)
}

/// Archive-first asset lifecycle (Phase D Decision 5). Archiving is a
/// metadata status change; bytes and storage lifecycle belong to Phase E.
pub fn build_archive_asset(scene: &Scene, asset_id: AssetId) -> Result<EditBatch, EditError> {
    let mut asset = scene.assets.get(&asset_id).cloned().ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("asset {} does not exist", asset_id),
        )
        .with_target(EditTargetRef::Asset(asset_id.clone()))
    })?;
    asset.status = AssetStatus::Archived;

    EditBatch::new(
        vec![Operation::UpsertAsset { asset }],
        vec![EditTargetRef::Asset(asset_id)],
    )
    .with_intent("archive_asset")
    .with_inverses(scene)
}

/// Hard asset delete rejects while the asset is referenced by any node
/// (image source or placement source). Archive is the default lifecycle.
pub fn build_hard_delete_asset(scene: &Scene, asset_id: AssetId) -> Result<EditBatch, EditError> {
    if !scene.assets.contains_key(&asset_id) {
        return Err(EditError::new(
            EditErrorKind::TargetNotFound,
            format!("asset {} does not exist", asset_id),
        )
        .with_target(EditTargetRef::Asset(asset_id)));
    }
    let referencing_node = scene.nodes.values().find(|node| {
        node.source_asset_id.as_ref() == Some(&asset_id)
            || matches!(&node.kind, NodeKind::Image(image) if image.asset_id == asset_id)
    });
    if let Some(node) = referencing_node {
        return Err(EditError::new(
            EditErrorKind::LifecycleProtected,
            format!(
                "asset {} is referenced by node {}; archive it instead of hard deleting",
                asset_id, node.id
            ),
        )
        .with_target(EditTargetRef::Asset(asset_id)));
    }

    EditBatch::new(
        vec![Operation::RemoveAsset {
            asset_id: asset_id.clone(),
        }],
        vec![EditTargetRef::Asset(asset_id)],
    )
    .with_intent("delete_asset")
    .with_inverses(scene)
}

/// Group: insert an empty Group container just above the topmost selected
/// sibling, then move the selection into it in z-order. The insert is empty
/// and the children arrive by `MoveNode`, so every operation is individually
/// invertible (an `InsertNode` adopting pre-existing children is not).
///
/// Geometry contract: when every grouped node is pinned (`Absolute`), the
/// group itself pins to the union of their page-space boxes — children keep
/// their boxes untouched and ungroup round-trips exactly. Otherwise the
/// group joins its parent's manual flow at the identity transform with Hug
/// size, so children's parent-relative transforms keep their meaning.
/// Grouping solver-managed children of a Stack container is rejected: their
/// positions are solved-and-discarded, and wrapping them in a plain Group
/// would collapse them onto its origin (detach to freehand first).
pub fn build_group(
    scene: &Scene,
    node_ids: &[NodeId],
    group_id: NodeId,
    name: Option<String>,
) -> Result<EditBatch, EditError> {
    if node_ids.is_empty() {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            "group requires at least one node",
        ));
    }
    let unique: BTreeSet<&NodeId> = node_ids.iter().collect();
    if unique.len() != node_ids.len() {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            "group selection contains duplicate nodes",
        ));
    }
    if scene.nodes.contains_key(&group_id) {
        return Err(EditError::new(
            EditErrorKind::OperationFailed,
            format!("group id {} already exists in the scene", group_id),
        )
        .with_target(EditTargetRef::Node(group_id)));
    }

    let mut parent: Option<ParentRef> = None;
    for node_id in node_ids {
        let node = require_node(scene, node_id)?;
        if node.locked {
            return Err(EditError::new(
                EditErrorKind::LockedTarget,
                format!("node {} is locked", node_id),
            )
            .with_target(EditTargetRef::Node(node_id.clone())));
        }
        let node_parent = scene.parent_of(node_id).ok_or_else(|| {
            EditError::new(
                EditErrorKind::TargetNotFound,
                format!("node {} has no parent", node_id),
            )
            .with_target(EditTargetRef::Node(node_id.clone()))
        })?;
        match &parent {
            None => parent = Some(node_parent),
            Some(existing) if *existing == node_parent => {}
            Some(_) => {
                return Err(EditError::new(
                    EditErrorKind::UnsupportedTarget,
                    "grouped nodes must share the same parent",
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
        }
    }
    let parent = parent.expect("non-empty selection has a parent");

    if let ParentRef::Node(parent_id) = &parent {
        let parent_node = require_node(scene, parent_id)?;
        let is_stack_container = matches!(parent_node.kind, NodeKind::AutoLayout(_))
            && parent_node
                .layout
                .as_ref()
                .is_none_or(|layout| layout.layout_mode == LayoutMode::Stack);
        if is_stack_container {
            let all_pinned = node_ids.iter().all(|node_id| {
                scene.nodes.get(node_id).is_some_and(|node| {
                    node.position_mode == PositionMode::Absolute && node.absolute_box.is_some()
                })
            });
            if !all_pinned {
                return Err(EditError::new(
                    EditErrorKind::LifecycleProtected,
                    format!(
                        "cannot group solver-managed children of auto-layout container {}; detach them to freehand first",
                        parent_id
                    ),
                )
                .with_target(EditTargetRef::Node(parent_id.clone())));
            }
        }
    }

    let siblings = children_for_parent(scene, &parent)?;
    let mut indexed: Vec<(usize, NodeId)> = Vec::with_capacity(node_ids.len());
    for node_id in node_ids {
        let index = siblings
            .iter()
            .position(|id| id == node_id)
            .ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("node {} is not in its parent", node_id),
                )
                .with_target(EditTargetRef::Node(node_id.clone()))
            })?;
        indexed.push((index, node_id.clone()));
    }
    indexed.sort_by_key(|(index, _)| *index);
    let insert_index = indexed.last().expect("non-empty").0 + 1;

    let mut group_node = Node::new(group_id.clone(), NodeKind::Group);
    group_node.name = name;
    let pinned_boxes: Option<Vec<&Rect>> = node_ids
        .iter()
        .map(|node_id| {
            scene.nodes.get(node_id).and_then(|node| {
                (node.position_mode == PositionMode::Absolute)
                    .then_some(node.absolute_box.as_ref())
                    .flatten()
            })
        })
        .collect();
    if let Some(boxes) = pinned_boxes {
        let min_x = boxes.iter().map(|b| b.x).fold(f64::INFINITY, f64::min);
        let min_y = boxes.iter().map(|b| b.y).fold(f64::INFINITY, f64::min);
        let max_x = boxes
            .iter()
            .map(|b| b.x + b.width)
            .fold(f64::NEG_INFINITY, f64::max);
        let max_y = boxes
            .iter()
            .map(|b| b.y + b.height)
            .fold(f64::NEG_INFINITY, f64::max);
        group_node.position_mode = PositionMode::Absolute;
        group_node.absolute_box = Some(Rect {
            x: min_x,
            y: min_y,
            width: max_x - min_x,
            height: max_y - min_y,
        });
        group_node.size = SizeSpec::fixed(max_x - min_x, max_y - min_y);
    } else {
        group_node.size = SizeSpec {
            width: Dimension::Hug,
            height: Dimension::Hug,
        };
    }

    let mut operations = vec![Operation::InsertNode {
        parent,
        index: insert_index,
        node: group_node,
    }];
    let mut touched = vec![EditTargetRef::Node(group_id.clone())];
    for (child_index, (_, node_id)) in indexed.iter().enumerate() {
        operations.push(Operation::MoveNode {
            node_id: node_id.clone(),
            new_parent: ParentRef::Node(group_id.clone()),
            index: child_index,
        });
        operations.push(Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: NodePatch {
                computed: OptionalFieldPatch::Clear,
                ..NodePatch::default()
            },
        });
        touched.push(EditTargetRef::Node(node_id.clone()));
    }

    EditBatch::new(operations, touched)
        .with_intent("group")
        .with_inverses(scene)
}

/// Ungroup: move the group's children to its parent at the group's index
/// (order preserved), then delete the emptied group. Auto-layout containers
/// are protected unless explicitly allowed, because dissolving them destroys
/// layout semantics. Moved children get stale computed geometry cleared so
/// preflight recomputes their positions.
pub fn build_ungroup(
    scene: &Scene,
    group_id: NodeId,
    allow_layout: bool,
) -> Result<EditBatch, EditError> {
    let group = scene.nodes.get(&group_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} does not exist", group_id),
        )
        .with_target(EditTargetRef::Node(group_id.clone()))
    })?;
    if !group.kind.can_have_children() {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!(
                "node {} is not a container and cannot be ungrouped",
                group_id
            ),
        )
        .with_target(EditTargetRef::Node(group_id)));
    }
    if matches!(group.kind, NodeKind::AutoLayout(_)) && !allow_layout {
        return Err(EditError::new(
            EditErrorKind::LifecycleProtected,
            format!(
                "node {} is an auto-layout container; ungrouping it destroys layout semantics (pass allow_layout to override)",
                group_id
            ),
        )
        .with_target(EditTargetRef::Node(group_id)));
    }
    if group.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked", group_id),
        )
        .with_target(EditTargetRef::Node(group_id)));
    }
    let parent = scene.parent_of(&group_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} has no parent", group_id),
        )
        .with_target(EditTargetRef::Node(group_id.clone()))
    })?;
    let group_index = children_for_parent(scene, &parent)?
        .iter()
        .position(|id| id == &group_id)
        .ok_or_else(|| {
            EditError::new(
                EditErrorKind::TargetNotFound,
                format!("node {} is not in its parent", group_id),
            )
            .with_target(EditTargetRef::Node(group_id.clone()))
        })?;

    let mut operations = Vec::new();
    for (offset, child_id) in group.children.iter().enumerate() {
        operations.push(Operation::MoveNode {
            node_id: child_id.clone(),
            new_parent: parent.clone(),
            index: group_index + offset,
        });
        operations.push(Operation::UpdateNode {
            node_id: child_id.clone(),
            patch: NodePatch {
                computed: OptionalFieldPatch::Clear,
                ..NodePatch::default()
            },
        });
    }
    operations.push(Operation::RemoveNode {
        node_id: group_id.clone(),
    });

    EditBatch::new(operations, vec![EditTargetRef::Node(group_id)])
        .with_intent("ungroup")
        .with_inverses(scene)
}

/// Export-profile delete (Phase D Decision 6): the only remaining profile is
/// protected, and an explicit replacement must name a different existing
/// profile so the document never loses its export contract.
pub fn build_delete_export_profile(
    scene: &Scene,
    name: String,
    replace_with: Option<String>,
) -> Result<EditBatch, EditError> {
    if scene.export_profile(&name).is_none() {
        return Err(EditError::new(
            EditErrorKind::TargetNotFound,
            format!("export profile {} does not exist", name),
        )
        .with_target(EditTargetRef::ExportProfile(name)));
    }
    if scene.export_profiles.len() <= 1 {
        return Err(EditError::new(
            EditErrorKind::LifecycleProtected,
            "cannot delete the only export profile; add a replacement profile first",
        )
        .with_target(EditTargetRef::ExportProfile(name)));
    }
    if let Some(replacement) = &replace_with {
        if replacement == &name {
            return Err(EditError::new(
                EditErrorKind::IncompatibleReplacement,
                "replacement profile must differ from the deleted profile",
            )
            .with_target(EditTargetRef::ExportProfile(name)));
        }
        if scene.export_profile(replacement).is_none() {
            return Err(EditError::new(
                EditErrorKind::TargetNotFound,
                format!("replacement export profile {} does not exist", replacement),
            )
            .with_target(EditTargetRef::ExportProfile(replacement.clone())));
        }
    }

    EditBatch::new(
        vec![Operation::RemoveExportProfile { name: name.clone() }],
        vec![EditTargetRef::ExportProfile(name)],
    )
    .with_intent("delete_export_profile")
    .with_inverses(scene)
}

pub fn build_move_before(
    scene: &Scene,
    node_id: NodeId,
    anchor_id: NodeId,
) -> Result<EditBatch, EditError> {
    build_relative_move(scene, node_id, anchor_id, false)
}

pub fn build_move_after(
    scene: &Scene,
    node_id: NodeId,
    anchor_id: NodeId,
) -> Result<EditBatch, EditError> {
    build_relative_move(scene, node_id, anchor_id, true)
}

pub fn build_move_to_parent(
    scene: &Scene,
    node_id: NodeId,
    new_parent: ParentRef,
    index: usize,
) -> Result<EditBatch, EditError> {
    validate_node_can_move(scene, &node_id, &new_parent)?;
    EditBatch::new(
        vec![Operation::MoveNode {
            node_id: node_id.clone(),
            new_parent,
            index,
        }],
        vec![EditTargetRef::Node(node_id)],
    )
    .with_intent("move_node")
    .with_inverses(scene)
}

/// Phase 1c freehand: detach a node from solver ownership. Pins the node at
/// its *solved* box (`absolute_box` = `base_anchor` = `computed.layout_bounds`),
/// so the detached node itself does not move; flow siblings close the vacated
/// slot on the next solve, as in Figma (freezing a whole section in place is
/// [`build_convert_container_layout`] with `Free`). Hug/Fill dimensions bake
/// to Fixed at the solved extent so the size spec matches what the human sees
/// (and what a later re-attach keeps).
pub fn build_detach_to_freehand(scene: &Scene, node_id: NodeId) -> Result<EditBatch, EditError> {
    let node = require_node(scene, &node_id)?;
    if node.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked; unlock it before detaching", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    if node.position_mode == PositionMode::Absolute {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!("node {} is already freehand", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    let solved = solved_bounds(node, &node_id, "detaching")?;

    let mut patch = NodePatch {
        position_mode: FieldPatch::Set(PositionMode::Absolute),
        absolute_box: OptionalFieldPatch::Set(solved.clone()),
        base_anchor: OptionalFieldPatch::Set(solved.clone()),
        computed: OptionalFieldPatch::Clear,
        ..NodePatch::default()
    };
    let baked = SizeSpec {
        width: bake_dimension(&node.size.width, solved.width),
        height: bake_dimension(&node.size.height, solved.height),
    };
    if baked != node.size {
        patch.size = FieldPatch::Set(baked);
    }

    EditBatch::new(
        vec![Operation::UpdateNode {
            node_id: node_id.clone(),
            patch,
        }],
        vec![EditTargetRef::Node(node_id)],
    )
    .with_intent("detach_to_freehand")
    .with_inverses(scene)
}

/// Phase 1c freehand: return a pinned node to solver ownership. Clears the
/// pin and the detach-time anchor; the next layout re-flows the node into
/// its parent's solve. The size baked at detach (or resized since) is kept —
/// the solver cannot know what Hug/Fill meant before the human took over.
pub fn build_reattach_to_layout(scene: &Scene, node_id: NodeId) -> Result<EditBatch, EditError> {
    let node = require_node(scene, &node_id)?;
    if node.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked; unlock it before re-attaching", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    if node.position_mode != PositionMode::Absolute {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!("node {} is not freehand; nothing to re-attach", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }

    let patch = NodePatch {
        position_mode: FieldPatch::Set(PositionMode::Managed),
        absolute_box: if node.absolute_box.is_some() {
            OptionalFieldPatch::Clear
        } else {
            OptionalFieldPatch::Unchanged
        },
        base_anchor: if node.base_anchor.is_some() {
            OptionalFieldPatch::Clear
        } else {
            OptionalFieldPatch::Unchanged
        },
        computed: OptionalFieldPatch::Clear,
        ..NodePatch::default()
    };

    EditBatch::new(
        vec![Operation::UpdateNode {
            node_id: node_id.clone(),
            patch,
        }],
        vec![EditTargetRef::Node(node_id)],
    )
    .with_intent("reattach_to_layout")
    .with_inverses(scene)
}

/// Phase 1c freehand: flip an auto-layout container between the flex solve
/// (`Stack`) and hand-placed children (`Free`). Converting to Free bakes
/// every managed child's transform to its solved offset inside the container
/// (and Hug/Fill sizes to Fixed, including the container's OWN Hug and Fill
/// dims) so the conversion is zero-motion; children already pinned Absolute
/// are left untouched — their page-space box keeps winning either way.
/// Converting back to Stack only flips the mode: the solve takes over and
/// re-stacks the children (baked sizes stay baked — a once-Hug container
/// returns as Fixed; undo, not re-convert, restores Hug).
pub fn build_convert_container_layout(
    scene: &Scene,
    node_id: NodeId,
    layout_mode: LayoutMode,
) -> Result<EditBatch, EditError> {
    let node = require_node(scene, &node_id)?;
    if node.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked; unlock it before converting", node_id),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    if !matches!(node.kind, NodeKind::AutoLayout(_)) {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!(
                "node {} is not an auto-layout container; layout mode does not apply",
                node_id
            ),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    let current_props = node.layout.clone().unwrap_or_default();
    if current_props.layout_mode == layout_mode {
        return Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!(
                "node {} is already {}",
                node_id,
                match layout_mode {
                    LayoutMode::Stack => "a stack container",
                    LayoutMode::Free => "a free container",
                }
            ),
        )
        .with_target(EditTargetRef::Node(node_id)));
    }

    let mut operations = Vec::new();
    let mut touched = vec![EditTargetRef::Node(node_id.clone())];

    // Leaving the solve bakes the container's own Hug/Fill dims alongside
    // its children (see `baked_container_size`); returning to Stack changes
    // no sizes — the solver re-owns them.
    let size = if layout_mode == LayoutMode::Free {
        let container_bounds =
            free_container_operations(scene, node, &node_id, &mut operations, &mut touched)?;
        baked_container_size(node, &container_bounds)
    } else {
        FieldPatch::Unchanged
    };

    operations.push(Operation::UpdateNode {
        node_id: node_id.clone(),
        patch: NodePatch {
            layout: OptionalFieldPatch::Set(AutoLayoutProps {
                layout_mode,
                ..current_props
            }),
            size,
            computed: OptionalFieldPatch::Clear,
            ..NodePatch::default()
        },
    });

    EditBatch::new(operations, touched)
        .with_intent("convert_container_layout")
        .with_inverses(scene)
}

/// Zero-motion child baking for a Stack→Free conversion: every managed
/// child's transform bakes to its solved offset inside the container, and
/// Hug/Fill sizes bake to Fixed; children already pinned Absolute are left
/// untouched (their page-space box keeps winning either way). Shared by the
/// single-container convert and the scene-wide freeze so the two cannot
/// drift.
fn free_container_operations(
    scene: &Scene,
    node: &Node,
    node_id: &NodeId,
    operations: &mut Vec<Operation>,
    touched: &mut Vec<EditTargetRef>,
) -> Result<Rect, EditError> {
    let container_bounds = solved_bounds(node, node_id, "freeing")?;
    for child_id in &node.children {
        let Some(child) = scene.nodes.get(child_id) else {
            continue;
        };
        if child.position_mode == PositionMode::Absolute {
            continue;
        }
        let child_bounds = solved_bounds(child, child_id, "freeing")?;

        let mut child_patch = NodePatch::default();
        let baked_transform = Transform {
            x: child_bounds.x - container_bounds.x,
            y: child_bounds.y - container_bounds.y,
            ..child.transform.clone()
        };
        if baked_transform != child.transform {
            child_patch.transform = FieldPatch::Set(baked_transform);
        }
        // K1 rider, narrowed to the HEIGHT axis (2026-09-20): a TEXT child
        // keeps a Hug HEIGHT through the freeze. Hug text re-measures
        // vertically — it cannot re-flow siblings once the container is
        // Free, so baking the height buys nothing — and at accept time the
        // solved extent may predate typography-token resolution (the
        // proposal ops insert skeleton text; the post-accept preflight
        // resolves the real family/size). Baking that skeleton measurement
        // froze an 80pt headline into a 17pt Fixed box (LUMV0903/0810 on
        // the K0 live-proof document). Its WIDTH does bake, though: the
        // width is the constraint the solve wrapped against, and a kept hug
        // width measures unbounded in Free mode and unwraps the paragraph
        // across the artboard. Non-text children bake on both axes.
        let is_text_child = matches!(child.kind, NodeKind::Text(_));
        let baked_size = SizeSpec {
            width: bake_dimension_for_child(
                &child.size.width,
                child_bounds.width,
                is_text_child,
                BakeAxis::Width,
            ),
            height: bake_dimension_for_child(
                &child.size.height,
                child_bounds.height,
                is_text_child,
                BakeAxis::Height,
            ),
        };
        if baked_size != child.size {
            child_patch.size = FieldPatch::Set(baked_size);
        }
        if node_patch_has_changes(&child_patch) {
            child_patch.computed = OptionalFieldPatch::Clear;
            operations.push(Operation::UpdateNode {
                node_id: child_id.clone(),
                patch: child_patch,
            });
            touched.push(EditTargetRef::Node(child_id.clone()));
        }
    }
    Ok(container_bounds)
}

/// The container's OWN size patch for a Stack→Free conversion. A container
/// leaving the solve keeps EXACTLY the extents the solve gave it — `Hug` and
/// `Fill` alike.
///
/// `Hug` means different things on the two sides: the Stack solve hugs
/// content PLUS padding, while the Free path natural-sizes from child
/// extents alone — so a padded hug container visibly contracts the moment
/// it is frozen (the Story-ad live-proof lost exactly its bottom padding,
/// and an EMPTY padded container collapses to 0×0).
///
/// `Fill` was formerly exempted ("a Free container's Fill still tracks its
/// parent"), and that was wrong twice over (2026-09-20): the Stack solve
/// treats a nested cross-axis `Fill` as hug — the children are built with no
/// definite parent size — while Free mode resolves `Fill` against the
/// parent's OUTER box, so a hugged pill row snapped to the artboard edge on
/// the human's first grab. Worse, this patch REPLACES the whole `SizeSpec`,
/// so the kept `Fill` also overwrote the Fixed extent the child bake in
/// `free_container_operations` had already recorded for the same node.
///
/// Fixed keeps its authored value; `Token` keeps its binding — the brand
/// pass rewrites resolvable dimension tokens to Fixed before layout ever
/// runs, so a token surviving here is the already-LUMV-warned unresolved
/// case, and severing brand governance to steady a broken binding is the
/// worse trade.
fn baked_container_size(node: &Node, container_bounds: &Rect) -> FieldPatch<SizeSpec> {
    // Same match as `bake_dimension` — a container's own dims and a child's
    // dims now leave the solve on identical terms. Keep them in step.
    let bake = |dimension: &Dimension, solved: f64| match dimension {
        Dimension::Hug | Dimension::Fill { .. } => Dimension::Fixed(solved),
        other => other.clone(),
    };
    let baked = SizeSpec {
        width: bake(&node.size.width, container_bounds.width),
        height: bake(&node.size.height, container_bounds.height),
    };
    if baked == node.size {
        FieldPatch::Unchanged
    } else {
        FieldPatch::Set(baked)
    }
}

/// Handoff-absolute (Moda model, MODA-EDITOR-PLAN §2): once the agent's turn
/// is done, the human edits a design that behaves purely absolute — no
/// solver ever re-flows siblings under their cursor. This bakes EVERY Stack
/// auto-layout container in the scene to Free in one invertible, zero-motion
/// batch (each container's children bake to their solved offsets via the
/// same helper the single convert uses). Locked containers and containers
/// already Free are skipped; a scene with nothing to freeze yields an empty
/// batch so callers may invoke this unconditionally at handoff. Layout
/// props (gap/padding/mode) are preserved, so a later agent turn can convert
/// containers back to Stack and re-enter the solve. Every solved dimension
/// bakes on the way out — a container's own `Fill` included — because the two
/// modes disagree about what `Fill` and `Hug` mean (see
/// `baked_container_size`); the one deliberate survivor is a TEXT child's
/// `Hug` HEIGHT (the K1 rider in `free_container_operations`).
pub fn build_freeze_layout(scene: &Scene) -> Result<EditBatch, EditError> {
    let mut operations = Vec::new();
    let mut touched = Vec::new();

    // BTreeMap iteration = deterministic op order across replays.
    for (node_id, node) in &scene.nodes {
        if !matches!(node.kind, NodeKind::AutoLayout(_)) || node.locked {
            continue;
        }
        let current_props = node.layout.clone().unwrap_or_default();
        if current_props.layout_mode == LayoutMode::Free {
            continue;
        }

        let container_bounds =
            free_container_operations(scene, node, node_id, &mut operations, &mut touched)?;
        operations.push(Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: NodePatch {
                layout: OptionalFieldPatch::Set(AutoLayoutProps {
                    layout_mode: LayoutMode::Free,
                    ..current_props
                }),
                // The container's own Hug/Fill dims bake with its children
                // — zero-motion includes the container's padded box itself,
                // and this patch is what would otherwise re-open a `Fill`
                // the child bake had already closed.
                size: baked_container_size(node, &container_bounds),
                computed: OptionalFieldPatch::Clear,
                ..NodePatch::default()
            },
        });
        touched.push(EditTargetRef::Node(node_id.clone()));
    }

    EditBatch::new(operations, touched)
        .with_intent("freeze_layout")
        .with_inverses(scene)
}

fn require_node<'a>(scene: &'a Scene, node_id: &NodeId) -> Result<&'a Node, EditError> {
    scene.nodes.get(node_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} does not exist", node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone()))
    })
}

/// Freehand builders read the node's solved box; they never lay out
/// themselves (the editor and helper both hold laid-out scenes, and an
/// internal solve here could disagree with the canonical measurer).
fn solved_bounds(node: &Node, node_id: &NodeId, verb: &str) -> Result<Rect, EditError> {
    node.computed
        .as_ref()
        .map(|computed| computed.layout_bounds.clone())
        .ok_or_else(|| {
            EditError::new(
                EditErrorKind::OperationFailed,
                format!(
                    "node {} has no computed geometry; run layout before {}",
                    node_id, verb
                ),
            )
            .with_target(EditTargetRef::Node(node_id.clone()))
        })
}

/// Hug/Fill bake to the solved extent at detach/free time; Fixed keeps its
/// authored value and Token dimensions keep their binding (baking a token
/// to a number would silently sever brand governance).
fn bake_dimension(dimension: &Dimension, solved: f64) -> Dimension {
    match dimension {
        Dimension::Hug | Dimension::Fill { .. } => Dimension::Fixed(solved),
        Dimension::Fixed(value) => Dimension::Fixed(*value),
        Dimension::Token { token } => Dimension::Token {
            token: token.clone(),
        },
    }
}

/// Which of a [`SizeSpec`]'s two dimensions is being baked. `layout::Axis`
/// is private to that module, and this only ever needs the two names.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum BakeAxis {
    Width,
    Height,
}

/// `bake_dimension`, except a text child's Hug HEIGHT survives the bake (see
/// the K1 rider comment at the call site): hug text re-measures vertically at
/// whatever width it is painted at, and baking that height can freeze a
/// pre-token-resolution measurement into a lying Fixed box.
///
/// Narrowed to the height axis on 2026-09-20: a hug WIDTH the Stack solve had
/// wrapped at the container width measures UNBOUNDED once the container is
/// Free, so a kept hug width unwrapped a paragraph across the whole artboard.
/// The width is the constraint the wrap was computed against — it has to
/// survive with the text.
fn bake_dimension_for_child(
    dimension: &Dimension,
    solved: f64,
    is_text: bool,
    axis: BakeAxis,
) -> Dimension {
    if is_text && axis == BakeAxis::Height && matches!(dimension, Dimension::Hug) {
        return Dimension::Hug;
    }
    bake_dimension(dimension, solved)
}

pub fn build_clone_subtree(
    scene: &Scene,
    request: CloneSubtreeRequest,
) -> Result<EditBatch, EditError> {
    let source = scene.nodes.get(&request.source).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("source node {} does not exist", request.source),
        )
        .with_target(EditTargetRef::Node(request.source.clone()))
    })?;
    if source.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("source node {} is locked", request.source),
        )
        .with_target(EditTargetRef::Node(request.source)));
    }

    let placement = resolve_clone_placement(scene, &request.placement)?;
    validate_node_can_move(scene, &request.source, &placement.parent)?;

    let source_ids = subtree_ids(scene, &request.source);
    let id_map = clone_id_map(scene, &source_ids, &request.new_root_id)?;
    let mut operations = Vec::new();

    let root_clone =
        clone_node_for_insert(scene, &request.source, &id_map, &request.computed_policy)?;
    operations.push(Operation::InsertNode {
        parent: placement.parent,
        index: placement.index,
        node: root_clone,
    });

    for original_id in source_ids.iter().skip(1) {
        let original_parent = scene.parent_of(original_id).ok_or_else(|| {
            EditError::new(
                EditErrorKind::TargetNotFound,
                format!("source descendant {} has no parent", original_id),
            )
        })?;
        let ParentRef::Node(original_parent_id) = original_parent else {
            return Err(EditError::new(
                EditErrorKind::UnsupportedTarget,
                "clone descendants must be parented by nodes",
            ));
        };
        let parent_clone_id = id_map
            .get(&original_parent_id)
            .expect("parent appears before child in subtree map")
            .clone();
        let child_index = scene.nodes[&original_parent_id]
            .children
            .iter()
            .position(|id| id == original_id)
            .unwrap_or(0);
        operations.push(Operation::InsertNode {
            parent: ParentRef::Node(parent_clone_id),
            index: child_index,
            node: clone_node_for_insert(scene, original_id, &id_map, &request.computed_policy)?,
        });
    }

    append_clone_slot_operations(
        scene,
        &source_ids,
        &id_map,
        &request.slot_policy,
        &mut operations,
    )?;

    let lineage = CloneLineage {
        source_root: request.source.clone(),
        id_map: source_ids
            .iter()
            .map(|source_id| (source_id.clone(), id_map[source_id].clone()))
            .collect(),
    };

    EditBatch::new(
        operations,
        vec![
            EditTargetRef::Node(request.source),
            EditTargetRef::Node(request.new_root_id),
        ],
    )
    .with_intent("clone_subtree")
    .with_lineage(lineage)
    .with_inverses(scene)
}

pub fn build_replace_node(
    scene: &Scene,
    request: ReplaceNodeRequest,
) -> Result<EditBatch, EditError> {
    if request.target == request.replacement {
        return Err(EditError::new(
            EditErrorKind::IncompatibleReplacement,
            "target and replacement must be different nodes",
        )
        .with_target(EditTargetRef::Node(request.target)));
    }
    let target_parent = scene.parent_of(&request.target).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("target node {} has no parent", request.target),
        )
        .with_target(EditTargetRef::Node(request.target.clone()))
    })?;
    let target_index = children_for_parent(scene, &target_parent)?
        .iter()
        .position(|id| id == &request.target)
        .ok_or_else(|| {
            EditError::new(
                EditErrorKind::TargetNotFound,
                format!("target node {} is not in its parent", request.target),
            )
            .with_target(EditTargetRef::Node(request.target.clone()))
        })?;
    if !scene.nodes.contains_key(&request.replacement) {
        return Err(EditError::new(
            EditErrorKind::TargetNotFound,
            format!("replacement node {} does not exist", request.replacement),
        )
        .with_target(EditTargetRef::Node(request.replacement)));
    }
    if scene
        .descendants_of(&request.target)
        .contains(&request.replacement)
        || scene
            .descendants_of(&request.replacement)
            .contains(&request.target)
    {
        return Err(EditError::new(
            EditErrorKind::IncompatibleReplacement,
            "target and replacement cannot contain each other",
        )
        .with_target(EditTargetRef::Node(request.target)));
    }

    let mut operations = vec![
        Operation::RemoveNode {
            node_id: request.target.clone(),
        },
        Operation::MoveNode {
            node_id: request.replacement.clone(),
            new_parent: target_parent,
            index: target_index,
        },
    ];

    if matches!(request.slot_policy, ReplaceSlotPolicy::PreserveCompatible) {
        for slot in scene.slots_for_node(&request.target) {
            operations.push(Operation::BindNodeToSlot {
                slot_id: slot.id.clone(),
                node_id: request.replacement.clone(),
            });
        }
    }

    EditBatch::new(
        operations,
        vec![
            EditTargetRef::Node(request.target),
            EditTargetRef::Node(request.replacement),
        ],
    )
    .with_intent("replace_node")
    .with_inverses(scene)
}

fn build_relative_move(
    scene: &Scene,
    node_id: NodeId,
    anchor_id: NodeId,
    after: bool,
) -> Result<EditBatch, EditError> {
    if node_id == anchor_id {
        return Err(EditError::new(
            EditErrorKind::AnchorNotFound,
            "target and anchor must be different nodes",
        )
        .with_target(EditTargetRef::Node(node_id)));
    }
    let anchor_parent = scene.parent_of(&anchor_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::AnchorNotFound,
            format!("anchor node {} has no parent", anchor_id),
        )
        .with_target(EditTargetRef::Node(anchor_id.clone()))
    })?;
    validate_node_can_move(scene, &node_id, &anchor_parent)?;

    let mut siblings = children_for_parent(scene, &anchor_parent)?.clone();
    siblings.retain(|id| id != &node_id);
    let anchor_index = siblings
        .iter()
        .position(|id| id == &anchor_id)
        .ok_or_else(|| {
            EditError::new(
                EditErrorKind::AnchorNotFound,
                format!("anchor node {} is not in its parent", anchor_id),
            )
            .with_target(EditTargetRef::Node(anchor_id))
        })?;
    let index = if after {
        anchor_index + 1
    } else {
        anchor_index
    };

    EditBatch::new(
        vec![Operation::MoveNode {
            node_id: node_id.clone(),
            new_parent: anchor_parent,
            index,
        }],
        vec![EditTargetRef::Node(node_id)],
    )
    .with_intent(if after { "move_after" } else { "move_before" })
    .with_inverses(scene)
}

fn validate_node_can_move(
    scene: &Scene,
    node_id: &NodeId,
    new_parent: &ParentRef,
) -> Result<(), EditError> {
    let node = scene.nodes.get(node_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("node {} does not exist", node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone()))
    })?;
    if node.locked {
        return Err(EditError::new(
            EditErrorKind::LockedTarget,
            format!("node {} is locked", node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone())));
    }
    match new_parent {
        ParentRef::Page(page_id) => {
            if !scene.pages.contains_key(page_id) {
                return Err(EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("parent page {} does not exist", page_id),
                )
                .with_target(EditTargetRef::Page(page_id.clone())));
            }
        }
        ParentRef::Node(parent_id) => {
            let parent = scene.nodes.get(parent_id).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("parent node {} does not exist", parent_id),
                )
                .with_target(EditTargetRef::Node(parent_id.clone()))
            })?;
            if !parent.kind.can_have_children() {
                return Err(EditError::new(
                    EditErrorKind::UnsupportedTarget,
                    format!("node {} cannot receive children", parent_id),
                )
                .with_target(EditTargetRef::Node(parent_id.clone())));
            }
            if parent_id == node_id || scene.descendants_of(node_id).contains(parent_id) {
                return Err(EditError::new(
                    EditErrorKind::WouldCreateCycle,
                    "cannot move a node under itself or a descendant",
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
        }
    }
    Ok(())
}

#[derive(Clone, Debug)]
struct ResolvedPlacement {
    parent: ParentRef,
    index: usize,
}

fn resolve_clone_placement(
    scene: &Scene,
    placement: &RelativePlacement,
) -> Result<ResolvedPlacement, EditError> {
    match placement {
        RelativePlacement::Before { anchor } => {
            let parent = scene.parent_of(anchor).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::AnchorNotFound,
                    format!("anchor node {} has no parent", anchor),
                )
                .with_target(EditTargetRef::Node(anchor.clone()))
            })?;
            let index = children_for_parent(scene, &parent)?
                .iter()
                .position(|id| id == anchor)
                .ok_or_else(|| {
                    EditError::new(
                        EditErrorKind::AnchorNotFound,
                        format!("anchor node {} is not in its parent", anchor),
                    )
                    .with_target(EditTargetRef::Node(anchor.clone()))
                })?;
            Ok(ResolvedPlacement { parent, index })
        }
        RelativePlacement::After { anchor } => {
            let mut resolved = resolve_clone_placement(
                scene,
                &RelativePlacement::Before {
                    anchor: anchor.clone(),
                },
            )?;
            resolved.index += 1;
            Ok(resolved)
        }
        RelativePlacement::ParentIndex { parent, index } => {
            let children = children_for_parent(scene, parent)?;
            if *index > children.len() {
                return Err(EditError::new(
                    EditErrorKind::AnchorNotFound,
                    format!("insert index {} is out of bounds", index),
                ));
            }
            Ok(ResolvedPlacement {
                parent: parent.clone(),
                index: *index,
            })
        }
    }
}

fn subtree_ids(scene: &Scene, root: &NodeId) -> Vec<NodeId> {
    let mut ids = vec![root.clone()];
    fn visit(scene: &Scene, id: &NodeId, ids: &mut Vec<NodeId>) {
        if let Some(node) = scene.nodes.get(id) {
            for child_id in &node.children {
                ids.push(child_id.clone());
                visit(scene, child_id, ids);
            }
        }
    }
    visit(scene, root, &mut ids);
    ids
}

fn clone_id_map(
    scene: &Scene,
    source_ids: &[NodeId],
    new_root_id: &NodeId,
) -> Result<BTreeMap<NodeId, NodeId>, EditError> {
    let mut map = BTreeMap::new();
    for (index, source_id) in source_ids.iter().enumerate() {
        let new_id = if index == 0 {
            new_root_id.clone()
        } else {
            NodeId::from(format!("{}__{}", new_root_id, source_id))
        };
        if scene.nodes.contains_key(&new_id) || map.values().any(|id| id == &new_id) {
            return Err(EditError::new(
                EditErrorKind::IdCollision,
                format!("clone node id {} already exists", new_id),
            )
            .with_target(EditTargetRef::Node(new_id)));
        }
        map.insert(source_id.clone(), new_id);
    }
    Ok(map)
}

fn clone_node_for_insert(
    scene: &Scene,
    original_id: &NodeId,
    id_map: &BTreeMap<NodeId, NodeId>,
    computed_policy: &ComputedClonePolicy,
) -> Result<Node, EditError> {
    let original = scene.nodes.get(original_id).ok_or_else(|| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("clone source node {} does not exist", original_id),
        )
    })?;
    let mut clone = original.clone();
    clone.id = id_map[original_id].clone();
    clone.children.clear();
    if matches!(computed_policy, ComputedClonePolicy::Clear) {
        clone.computed = None;
    }
    if let NodeKind::Instance { source_node_id } = &mut clone.kind {
        if let Some(mapped) = id_map.get(source_node_id) {
            *source_node_id = mapped.clone();
        }
    }
    Ok(clone)
}

fn append_clone_slot_operations(
    scene: &Scene,
    source_ids: &[NodeId],
    id_map: &BTreeMap<NodeId, NodeId>,
    slot_policy: &CloneSlotPolicy,
    operations: &mut Vec<Operation>,
) -> Result<(), EditError> {
    if matches!(slot_policy, CloneSlotPolicy::Detach) {
        return Ok(());
    }
    let source_set: BTreeSet<_> = source_ids.iter().cloned().collect();
    let mut cloned_slots = BTreeSet::new();
    for slot in scene.slots.values() {
        for bound_node_id in &slot.bound_nodes {
            if !source_set.contains(bound_node_id) {
                continue;
            }
            let cloned_node_id = id_map[bound_node_id].clone();
            match slot_policy {
                CloneSlotPolicy::Copy => {
                    operations.push(Operation::BindNodeToSlot {
                        slot_id: slot.id.clone(),
                        node_id: cloned_node_id,
                    });
                }
                CloneSlotPolicy::Suffix(suffix) => {
                    let cloned_slot = cloned_slot_with_suffix(slot, suffix);
                    if cloned_slots.insert(cloned_slot.id.clone()) {
                        operations.push(Operation::UpsertSlot {
                            slot: cloned_slot.clone(),
                        });
                    }
                    operations.push(Operation::BindNodeToSlot {
                        slot_id: cloned_slot.id,
                        node_id: cloned_node_id,
                    });
                }
                CloneSlotPolicy::Detach => {}
            }
        }
    }
    Ok(())
}

fn cloned_slot_with_suffix(slot: &Slot, suffix: &str) -> Slot {
    let suffix = sanitize_id_suffix(suffix);
    let mut cloned = slot.clone();
    cloned.id = SlotId::from(format!("{}{}", cloned.id, suffix));
    cloned.key = SlotKey::from(format!("{}{}", cloned.key, suffix));
    cloned.bound_nodes.clear();
    cloned
}

fn sanitize_id_suffix(suffix: &str) -> String {
    let mut sanitized = String::new();
    for b in suffix.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-') {
            sanitized.push(b as char);
        } else if b == b'.' {
            sanitized.push('_');
        }
    }
    if sanitized.is_empty() {
        "_clone".to_owned()
    } else if sanitized.starts_with('_') || sanitized.starts_with('-') {
        sanitized
    } else {
        format!("_{}", sanitized)
    }
}

/// Resolve a stack field (fills/strokes/effects) from a whole-stack patch
/// plus per-entry edits. Entry edits apply in order on top of the
/// whole-stack value (or the node's current stack when no whole-stack patch
/// is given), so unrelated entries always survive untouched.
fn resolve_stack_patch<T: Clone, I: Clone + Eq + fmt::Display>(
    current: &[T],
    whole: FieldPatch<Vec<T>>,
    edits: &[StackEntryEdit<T, I>],
    id_of: impl Fn(&T) -> &I,
    entity: &str,
    node_id: &NodeId,
) -> Result<FieldPatch<Vec<T>>, EditError> {
    if edits.is_empty() {
        return Ok(whole);
    }

    let mut stack = match whole {
        FieldPatch::Set(value) => value,
        FieldPatch::Unchanged => current.to_vec(),
    };

    for edit in edits {
        apply_stack_entry_edit(&mut stack, edit, &id_of, entity, node_id)?;
    }

    let mut seen = BTreeSet::new();
    for entry in &stack {
        if !seen.insert(id_of(entry).to_string()) {
            return Err(EditError::new(
                EditErrorKind::IdCollision,
                format!(
                    "{} stack on node {} would contain duplicate id {}",
                    entity,
                    node_id,
                    id_of(entry)
                ),
            )
            .with_target(EditTargetRef::Node(node_id.clone())));
        }
    }

    Ok(FieldPatch::Set(stack))
}

fn apply_stack_entry_edit<T: Clone, I: Clone + Eq + fmt::Display>(
    stack: &mut Vec<T>,
    edit: &StackEntryEdit<T, I>,
    id_of: &impl Fn(&T) -> &I,
    entity: &str,
    node_id: &NodeId,
) -> Result<(), EditError> {
    let position = |stack: &[T], id: &I| stack.iter().position(|entry| id_of(entry) == id);
    let missing = |id: &I| {
        EditError::new(
            EditErrorKind::TargetNotFound,
            format!("{} {} does not exist on node {}", entity, id, node_id),
        )
        .with_target(EditTargetRef::Node(node_id.clone()))
    };

    match edit {
        StackEntryEdit::Set { id, value } => {
            let index = position(stack, id).ok_or_else(|| missing(id))?;
            stack[index] = value.clone();
        }
        StackEntryEdit::Add { entry, index } => {
            if position(stack, id_of(entry)).is_some() {
                return Err(EditError::new(
                    EditErrorKind::IdCollision,
                    format!(
                        "{} {} already exists on node {}",
                        entity,
                        id_of(entry),
                        node_id
                    ),
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
            let index = index.unwrap_or(stack.len());
            if index > stack.len() {
                return Err(EditError::new(
                    EditErrorKind::AnchorNotFound,
                    format!(
                        "{} insert index {} is out of bounds on node {}",
                        entity, index, node_id
                    ),
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
            stack.insert(index, entry.clone());
        }
        StackEntryEdit::Remove { id } => {
            let index = position(stack, id).ok_or_else(|| missing(id))?;
            stack.remove(index);
        }
        StackEntryEdit::Reorder { id, index } => {
            let current_index = position(stack, id).ok_or_else(|| missing(id))?;
            let entry = stack.remove(current_index);
            if *index > stack.len() {
                return Err(EditError::new(
                    EditErrorKind::AnchorNotFound,
                    format!(
                        "{} reorder index {} is out of bounds on node {}",
                        entity, index, node_id
                    ),
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
            stack.insert(*index, entry);
        }
    }
    Ok(())
}

fn apply_text_edit_patch(mut text: TextNode, patch: TextEditPatch) -> TextNode {
    let before = text.clone();
    // A token field the patch addressed (set OR cleared) is an explicit
    // authoring decision; only untouched tokens are eligible for staleness.
    let explicit = patch.explicit_tokens();
    apply_field_patch(&mut text.content, patch.content);
    apply_field_patch(&mut text.font_family, patch.font_family);
    apply_field_patch(&mut text.font_size, patch.font_size);
    apply_field_patch(&mut text.font_weight, patch.font_weight);
    apply_field_patch(&mut text.align, patch.align);
    apply_field_patch(&mut text.line_height, patch.line_height);
    apply_field_patch(&mut text.letter_spacing, patch.letter_spacing);
    apply_optional_patch(&mut text.max_lines, patch.max_lines);
    apply_field_patch(&mut text.wrap, patch.wrap);
    apply_field_patch(&mut text.direction, patch.direction);
    apply_optional_patch(&mut text.style_token, patch.style_token);
    apply_optional_patch(&mut text.font_size_token, patch.font_size_token);
    apply_optional_patch(&mut text.line_height_token, patch.line_height_token);
    apply_optional_patch(&mut text.letter_spacing_token, patch.letter_spacing_token);
    apply_field_patch(&mut text.text_transform, patch.text_transform);
    apply_field_patch(&mut text.underline, patch.underline);
    apply_field_patch(&mut text.strikethrough, patch.strikethrough);
    apply_field_patch(&mut text.italic, patch.italic);
    apply_field_patch(&mut text.truncate, patch.truncate);
    apply_field_patch(&mut text.paragraph_spacing, patch.paragraph_spacing);
    apply_field_patch(&mut text.valign, patch.valign);
    // A6b D4: span honesty. A patch that sets spans applies them; otherwise, a
    // content change makes the existing spans' byte offsets stale garbage, so
    // they are cleared (silent corruption forbidden). Undo restores them via
    // the inverse patch, which sets `spans` from the pre-edit snapshot.
    let content_changed = text.content != before.content;
    match patch.spans {
        FieldPatch::Set(spans) => text.spans = spans,
        FieldPatch::Unchanged if content_changed => text.spans.clear(),
        FieldPatch::Unchanged => {}
    }
    text.clear_stale_tokens(&before, explicit);
    text
}

fn node_patch_affects_render(patch: &NodePatch) -> bool {
    !matches!(patch.kind, FieldPatch::Unchanged)
        || !matches!(patch.transform, FieldPatch::Unchanged)
        || !matches!(patch.size, FieldPatch::Unchanged)
        || !matches!(patch.fills, FieldPatch::Unchanged)
        || !matches!(patch.strokes, FieldPatch::Unchanged)
        || !matches!(patch.effects, FieldPatch::Unchanged)
        || !matches!(patch.corner, FieldPatch::Unchanged)
        || !matches!(patch.opacity, FieldPatch::Unchanged)
        || !matches!(patch.opacity_token, OptionalFieldPatch::Unchanged)
        || !matches!(patch.source_asset_id, OptionalFieldPatch::Unchanged)
        || !matches!(patch.asset_placement, OptionalFieldPatch::Unchanged)
        || !matches!(patch.clip, FieldPatch::Unchanged)
        || !matches!(patch.bleed, FieldPatch::Unchanged)
        || !matches!(patch.layout, OptionalFieldPatch::Unchanged)
        // Phase 1 freehand: pinning/unpinning or moving an absolute box moves
        // pixels, so stale computed geometry must be invalidated. Keep the TS
        // mirror (`nodePatchAffectsRender`, apps/editor operations.ts) in sync
        // when the editor starts emitting these fields (Phase 1d).
        || !matches!(patch.position_mode, FieldPatch::Unchanged)
        || !matches!(patch.absolute_box, OptionalFieldPatch::Unchanged)
        || !matches!(patch.base_anchor, OptionalFieldPatch::Unchanged)
}

fn node_patch_has_changes(patch: &NodePatch) -> bool {
    !matches!(patch.name, OptionalFieldPatch::Unchanged)
        || node_patch_affects_render(patch)
        || !matches!(patch.computed, OptionalFieldPatch::Unchanged)
        || !matches!(patch.locked, FieldPatch::Unchanged)
}

fn children_for_parent<'a>(
    scene: &'a Scene,
    parent: &ParentRef,
) -> Result<&'a Vec<NodeId>, EditError> {
    match parent {
        ParentRef::Page(page_id) => scene
            .pages
            .get(page_id)
            .map(|page| &page.children)
            .ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("page {} does not exist", page_id),
                )
                .with_target(EditTargetRef::Page(page_id.clone()))
            }),
        ParentRef::Node(node_id) => {
            let node = scene.nodes.get(node_id).ok_or_else(|| {
                EditError::new(
                    EditErrorKind::TargetNotFound,
                    format!("node {} does not exist", node_id),
                )
                .with_target(EditTargetRef::Node(node_id.clone()))
            })?;
            if !node.kind.can_have_children() {
                return Err(EditError::new(
                    EditErrorKind::UnsupportedTarget,
                    format!("node {} cannot have children", node_id),
                )
                .with_target(EditTargetRef::Node(node_id.clone())));
            }
            Ok(&node.children)
        }
    }
}

fn page_for_parent(scene: &Scene, parent: &ParentRef) -> Option<PageId> {
    match parent {
        ParentRef::Page(page_id) => Some(page_id.clone()),
        ParentRef::Node(node_id) => {
            let mut current = node_id.clone();
            loop {
                match scene.parent_of(&current)? {
                    ParentRef::Page(page_id) => return Some(page_id),
                    ParentRef::Node(parent_id) => current = parent_id,
                }
            }
        }
    }
}

fn edit_target_subject(target: &EditTargetRef) -> Option<DiagnosticSubject> {
    match target {
        EditTargetRef::Document => Some(DiagnosticSubject::Document),
        EditTargetRef::Page(page_id) => Some(DiagnosticSubject::Page(page_id.clone())),
        EditTargetRef::Node(node_id) => Some(DiagnosticSubject::Node(node_id.clone())),
        EditTargetRef::Slot(slot_id) => Some(DiagnosticSubject::Slot(slot_id.clone())),
        EditTargetRef::SlotKey(_) => None,
        EditTargetRef::Asset(asset_id) => Some(DiagnosticSubject::Asset(asset_id.clone())),
        EditTargetRef::ExportProfile(_) => None,
    }
}

fn apply_field_patch<T>(target: &mut T, patch: FieldPatch<T>) {
    if let FieldPatch::Set(value) = patch {
        *target = value;
    }
}

fn apply_optional_patch<T>(target: &mut Option<T>, patch: OptionalFieldPatch<T>) {
    match patch {
        OptionalFieldPatch::Unchanged => {}
        OptionalFieldPatch::Set(value) => *target = Some(value),
        OptionalFieldPatch::Clear => *target = None,
    }
}

pub fn solid_fill(id: impl Into<String>, value: impl Into<String>) -> Fill {
    Fill {
        id: crate::ids::PaintId::from(id.into()),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.into(),
            },
        },
    }
}

/// Wire-format structured edit instruction shared by every Lumen binding
/// surface (the API helper binary and the browser WASM core). This enum is
/// routing only: each variant maps to exactly one checked edit builder via
/// [`build_structured_edit_batch`]; the builders own all semantics. Keeping
/// the dispatch here means bindings cannot drift from each other.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
pub enum StructuredEditInstruction {
    Modify {
        target: EditTargetRef,
        patch: EditPatch,
    },
    Delete {
        target: EditTargetRef,
    },
    MoveBefore {
        node_id: NodeId,
        anchor: NodeId,
    },
    MoveAfter {
        node_id: NodeId,
        anchor: NodeId,
    },
    MoveToParent {
        node_id: NodeId,
        parent: ParentRef,
        index: usize,
    },
    CloneSubtree {
        request: CloneSubtreeRequest,
    },
    ReplaceNode {
        request: ReplaceNodeRequest,
    },
    ArchiveAsset {
        asset_id: AssetId,
    },
    HardDeleteAsset {
        asset_id: AssetId,
    },
    DeleteExportProfile {
        name: String,
        #[serde(default)]
        replace_with: Option<String>,
    },
    /// Phase 1c freehand: pin a node at its solved box (zero-motion detach).
    DetachToFreehand {
        node_id: NodeId,
    },
    /// Phase 1c freehand: return a pinned node to solver ownership.
    ReattachToLayout {
        node_id: NodeId,
    },
    /// Phase 1c freehand: flip a container between Stack and Free children.
    ConvertContainerLayout {
        node_id: NodeId,
        layout_mode: LayoutMode,
    },
    /// Phase 4b arrange: wrap same-parent siblings in a new Group container.
    /// The caller mints `group_id` so the operation replays deterministically.
    Group {
        node_ids: Vec<NodeId>,
        group_id: NodeId,
        #[serde(default)]
        name: Option<String>,
    },
    /// Phase 4b arrange: dissolve a container into its parent. Children keep
    /// their order and geometry; the emptied container is removed.
    Ungroup {
        node_id: NodeId,
        #[serde(default)]
        allow_layout: bool,
    },
    /// Handoff-absolute: bake every Stack container to Free in one
    /// zero-motion batch — the human edits pure absolute after an agent turn.
    FreezeLayout {},
}

impl StructuredEditInstruction {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Modify { .. } => "modify",
            Self::Delete { .. } => "delete",
            Self::MoveBefore { .. } => "move_before",
            Self::MoveAfter { .. } => "move_after",
            Self::MoveToParent { .. } => "move_to_parent",
            Self::CloneSubtree { .. } => "clone_subtree",
            Self::ReplaceNode { .. } => "replace_node",
            Self::ArchiveAsset { .. } => "archive_asset",
            Self::HardDeleteAsset { .. } => "hard_delete_asset",
            Self::DeleteExportProfile { .. } => "delete_export_profile",
            Self::DetachToFreehand { .. } => "detach_to_freehand",
            Self::ReattachToLayout { .. } => "reattach_to_layout",
            Self::ConvertContainerLayout { .. } => "convert_container_layout",
            Self::Group { .. } => "group",
            Self::Ungroup { .. } => "ungroup",
            Self::FreezeLayout {} => "freeze_layout",
        }
    }
}

/// Lower a structured edit instruction to a checked [`EditBatch`] against
/// the current scene. Asset deletes follow the archive-first lifecycle:
/// a plain `delete` on an asset target archives; `hard_delete_asset` is the
/// explicit unreferenced hard delete.
pub fn build_structured_edit_batch(
    scene: &Scene,
    edit: &StructuredEditInstruction,
) -> Result<EditBatch, EditError> {
    build_structured_edit_batch_with_text_context(scene, edit, None)
}

pub fn build_structured_edit_batch_with_text_context(
    scene: &Scene,
    edit: &StructuredEditInstruction,
    context: Option<TextEditContext<'_>>,
) -> Result<EditBatch, EditError> {
    match edit {
        StructuredEditInstruction::Modify { target, patch } => {
            build_modify_operations_with_text_context(scene, target.clone(), patch.clone(), context)
        }
        StructuredEditInstruction::Delete { target } => match target {
            EditTargetRef::Node(node_id) => build_safe_delete(scene, node_id.clone()),
            EditTargetRef::Page(page_id) => build_safe_delete_page(scene, page_id.clone()),
            EditTargetRef::Slot(_) | EditTargetRef::SlotKey(_) => {
                build_safe_delete_slot(scene, target.clone())
            }
            EditTargetRef::Asset(asset_id) => build_archive_asset(scene, asset_id.clone()),
            EditTargetRef::ExportProfile(name) => {
                build_delete_export_profile(scene, name.clone(), None)
            }
            EditTargetRef::Document => Err(EditError::new(
                EditErrorKind::UnsupportedTarget,
                "the document itself cannot be deleted through structured edits",
            )
            .with_target(target.clone())),
        },
        StructuredEditInstruction::ArchiveAsset { asset_id } => {
            build_archive_asset(scene, asset_id.clone())
        }
        StructuredEditInstruction::HardDeleteAsset { asset_id } => {
            build_hard_delete_asset(scene, asset_id.clone())
        }
        StructuredEditInstruction::DeleteExportProfile { name, replace_with } => {
            build_delete_export_profile(scene, name.clone(), replace_with.clone())
        }
        StructuredEditInstruction::MoveBefore { node_id, anchor } => {
            build_move_before(scene, node_id.clone(), anchor.clone())
        }
        StructuredEditInstruction::MoveAfter { node_id, anchor } => {
            build_move_after(scene, node_id.clone(), anchor.clone())
        }
        StructuredEditInstruction::MoveToParent {
            node_id,
            parent,
            index,
        } => build_move_to_parent(scene, node_id.clone(), parent.clone(), *index),
        StructuredEditInstruction::CloneSubtree { request } => {
            build_clone_subtree(scene, request.clone())
        }
        StructuredEditInstruction::ReplaceNode { request } => {
            build_replace_node(scene, request.clone())
        }
        StructuredEditInstruction::DetachToFreehand { node_id } => {
            build_detach_to_freehand(scene, node_id.clone())
        }
        StructuredEditInstruction::ReattachToLayout { node_id } => {
            build_reattach_to_layout(scene, node_id.clone())
        }
        StructuredEditInstruction::ConvertContainerLayout {
            node_id,
            layout_mode,
        } => build_convert_container_layout(scene, node_id.clone(), *layout_mode),
        StructuredEditInstruction::Group {
            node_ids,
            group_id,
            name,
        } => build_group(scene, node_ids, group_id.clone(), name.clone()),
        StructuredEditInstruction::Ungroup {
            node_id,
            allow_layout,
        } => build_ungroup(scene, node_id.clone(), *allow_layout),
        StructuredEditInstruction::FreezeLayout {} => build_freeze_layout(scene),
    }
}
