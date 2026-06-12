use crate::assets::AssetStatus;
use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{AssetId, NodeId, PageId, SlotId, SlotKey};
use crate::operations::{
    FieldPatch, NodePatch, Operation, OperationError, OperationReport, OptionalFieldPatch,
    PagePatch,
};
use crate::scene::{
    AutoLayoutProps, Color, CornerRadii, Fill, Node, NodeKind, PageSize, Paint, ParentRef, Rect,
    Scene, SizeSpec, Stroke, TextAlign, TextDirection, TextNode, TextWrap, Transform,
};
use crate::slots::Slot;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

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
    pub line_height_token: OptionalFieldPatch<String>,
    pub letter_spacing_token: OptionalFieldPatch<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct NodeEditPatch {
    pub name: OptionalFieldPatch<String>,
    pub transform: FieldPatch<Transform>,
    pub size: FieldPatch<SizeSpec>,
    pub fills: FieldPatch<Vec<Fill>>,
    pub strokes: FieldPatch<Vec<Stroke>>,
    pub corner: FieldPatch<CornerRadii>,
    pub opacity: FieldPatch<f64>,
    pub opacity_token: OptionalFieldPatch<String>,
    pub clip: FieldPatch<bool>,
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
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct AssetEditPatch {
    pub label: FieldPatch<String>,
    pub status: FieldPatch<AssetStatus>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
pub enum EditPatch {
    Node(NodeEditPatch),
    Page(PageEditPatch),
    Slot(SlotEditPatch),
    Asset(AssetEditPatch),
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
    match (target, patch) {
        (EditTargetRef::Node(node_id), EditPatch::Node(patch)) => {
            build_node_modify(scene, node_id, patch)
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
        (target, _) => Err(EditError::new(
            EditErrorKind::UnsupportedTarget,
            format!("patch cannot be applied to target {:?}", target),
        )
        .with_target(target)),
    }
}

pub fn build_node_modify(
    scene: &Scene,
    node_id: NodeId,
    patch: NodeEditPatch,
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

    let mut node_patch = NodePatch {
        name: patch.name,
        transform: patch.transform,
        size: patch.size,
        fills: patch.fills,
        strokes: patch.strokes,
        corner: patch.corner,
        opacity: patch.opacity,
        opacity_token: patch.opacity_token,
        source_asset_id: patch.source_asset_id,
        asset_placement: patch.asset_placement,
        clip: patch.clip,
        layout: patch.layout,
        computed: OptionalFieldPatch::Unchanged,
        locked: patch.locked,
        ..NodePatch::default()
    };

    if let Some(text_patch) = patch.text {
        let NodeKind::Text(current_text) = &node.kind else {
            return Err(EditError::new(
                EditErrorKind::UnsupportedProperty,
                format!("text patch cannot be applied to non-text node {}", node_id),
            )
            .with_target(EditTargetRef::Node(node_id)));
        };
        let next_text = apply_text_edit_patch(current_text.clone(), text_patch);
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

fn apply_text_edit_patch(mut text: TextNode, patch: TextEditPatch) -> TextNode {
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
    apply_optional_patch(&mut text.line_height_token, patch.line_height_token);
    apply_optional_patch(&mut text.letter_spacing_token, patch.letter_spacing_token);
    text
}

fn node_patch_affects_render(patch: &NodePatch) -> bool {
    !matches!(patch.kind, FieldPatch::Unchanged)
        || !matches!(patch.transform, FieldPatch::Unchanged)
        || !matches!(patch.size, FieldPatch::Unchanged)
        || !matches!(patch.fills, FieldPatch::Unchanged)
        || !matches!(patch.strokes, FieldPatch::Unchanged)
        || !matches!(patch.corner, FieldPatch::Unchanged)
        || !matches!(patch.opacity, FieldPatch::Unchanged)
        || !matches!(patch.opacity_token, OptionalFieldPatch::Unchanged)
        || !matches!(patch.source_asset_id, OptionalFieldPatch::Unchanged)
        || !matches!(patch.asset_placement, OptionalFieldPatch::Unchanged)
        || !matches!(patch.clip, FieldPatch::Unchanged)
        || !matches!(patch.layout, OptionalFieldPatch::Unchanged)
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
