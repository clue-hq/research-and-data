use crate::assets::{AssetKind, AssetPlacement, AssetRecord};
use crate::diagnostics::{Diagnostic, DiagnosticSeverity};
use crate::export_contract::ExportProfile;
use crate::ids::{AssetId, BrandKitId, NodeId, PageId, SlotId, TemplateRevisionId};
use crate::scene::{
    AutoLayoutProps, BrandKitRef, ComputedGeometry, CornerRadii, DocumentStatus, Effect,
    ExplicitTextTokens, Fill, ImageNode, Medium, Node, NodeKind, PageSize, ParentRef, PositionMode,
    Rect, Scene, SizeSpec, Stroke, Transform, VectorNode,
};
use crate::slots::ContentType;
use crate::slots::Slot;
use crate::validation::validate_scene;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

pub type OperationResult<T> = Result<T, OperationError>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationError {
    pub code: &'static str,
    pub message: String,
    pub diagnostics: Vec<Diagnostic>,
}

impl OperationError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            diagnostics: Vec::new(),
        }
    }

    pub fn with_diagnostics(mut self, diagnostics: Vec<Diagnostic>) -> Self {
        self.diagnostics = diagnostics;
        self
    }
}

impl fmt::Display for OperationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for OperationError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationReport {
    pub applied_operations: usize,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum FieldPatch<T> {
    #[default]
    Unchanged,
    Set(T),
}

impl<T> FieldPatch<T> {
    pub fn is_unchanged(&self) -> bool {
        matches!(self, Self::Unchanged)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum OptionalFieldPatch<T> {
    #[default]
    Unchanged,
    Set(T),
    Clear,
}

impl<T> OptionalFieldPatch<T> {
    pub fn is_unchanged(&self) -> bool {
        matches!(self, Self::Unchanged)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct DocumentPatch {
    pub title: FieldPatch<String>,
    pub artifact_type: OptionalFieldPatch<String>,
    pub medium: OptionalFieldPatch<Medium>,
    pub brand_kit: OptionalFieldPatch<BrandKitRef>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct PagePatch {
    pub name: FieldPatch<String>,
    pub size: FieldPatch<PageSize>,
    pub bleed: OptionalFieldPatch<Rect>,
    pub safe_area: OptionalFieldPatch<Rect>,
    pub background: FieldPatch<Vec<Fill>>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct NodePatch {
    pub name: OptionalFieldPatch<String>,
    pub kind: FieldPatch<NodeKind>,
    /// Token channels deliberately addressed by a text-kind replacement,
    /// including reapplying the same token. Absent on legacy/full-kind raw
    /// inspector edits, which retain value-difference staleness inference.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub explicit_text_tokens: Option<ExplicitTextTokens>,
    pub transform: FieldPatch<Transform>,
    pub size: FieldPatch<SizeSpec>,
    pub fills: FieldPatch<Vec<Fill>>,
    pub strokes: FieldPatch<Vec<Stroke>>,
    /// Effects Contract V0 addition. Skipped when unchanged so pinned
    /// pre-effects operation fixtures stay byte-identical.
    #[serde(default, skip_serializing_if = "FieldPatch::is_unchanged")]
    pub effects: FieldPatch<Vec<Effect>>,
    pub corner: FieldPatch<CornerRadii>,
    pub opacity: FieldPatch<f64>,
    #[serde(default)]
    pub opacity_token: OptionalFieldPatch<String>,
    #[serde(default)]
    pub source_asset_id: OptionalFieldPatch<AssetId>,
    #[serde(default)]
    pub asset_placement: OptionalFieldPatch<AssetPlacement>,
    pub clip: FieldPatch<bool>,
    /// Declared bleed intent (A4). Skipped when unchanged so pinned pre-A4
    /// operation fixtures stay byte-identical (mirrors `effects`).
    #[serde(default, skip_serializing_if = "FieldPatch::is_unchanged")]
    pub bleed: FieldPatch<bool>,
    pub layout: OptionalFieldPatch<AutoLayoutProps>,
    pub computed: OptionalFieldPatch<ComputedGeometry>,
    pub locked: FieldPatch<bool>,
    /// Phase 1 freehand fields. Skipped when unchanged so pinned pre-freehand
    /// operation fixtures stay byte-identical (mirrors `effects`).
    #[serde(default, skip_serializing_if = "FieldPatch::is_unchanged")]
    pub position_mode: FieldPatch<PositionMode>,
    #[serde(default, skip_serializing_if = "OptionalFieldPatch::is_unchanged")]
    pub absolute_box: OptionalFieldPatch<Rect>,
    #[serde(default, skip_serializing_if = "OptionalFieldPatch::is_unchanged")]
    pub base_anchor: OptionalFieldPatch<Rect>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
pub enum Operation {
    AddPage {
        page: crate::scene::Page,
    },
    RemovePage {
        page_id: PageId,
    },
    UpdateDocument {
        patch: DocumentPatch,
    },
    UpdatePage {
        page_id: PageId,
        patch: PagePatch,
    },
    InsertNode {
        parent: ParentRef,
        index: usize,
        node: Node,
    },
    RemoveNode {
        node_id: NodeId,
    },
    MoveNode {
        node_id: NodeId,
        new_parent: ParentRef,
        index: usize,
    },
    UpdateNode {
        node_id: NodeId,
        patch: NodePatch,
    },
    UpsertSlot {
        slot: Slot,
    },
    RemoveSlot {
        slot_id: SlotId,
    },
    UpsertAsset {
        asset: AssetRecord,
    },
    RemoveAsset {
        asset_id: AssetId,
    },
    PlaceAssetInNode {
        node_id: NodeId,
        asset_id: AssetId,
        placement: AssetPlacement,
    },
    PlaceAssetInSlot {
        slot_id: SlotId,
        asset_id: AssetId,
        placement: AssetPlacement,
    },
    BindNodeToSlot {
        slot_id: SlotId,
        node_id: NodeId,
    },
    UnbindNodeFromSlot {
        slot_id: SlotId,
        node_id: NodeId,
    },
    SetBrandKitRef {
        brand_kit_id: BrandKitId,
        version: u32,
    },
    UpsertExportProfile {
        profile: ExportProfile,
    },
    RemoveExportProfile {
        name: String,
    },
    FinalizeTemplate {
        template_revision_id: TemplateRevisionId,
    },
}

impl Operation {
    fn is_finalization(&self) -> bool {
        matches!(self, Self::FinalizeTemplate { .. })
    }
}

impl Scene {
    pub fn apply_operation(&mut self, operation: Operation) -> OperationResult<()> {
        let mut draft = self.clone();
        draft.apply_operation_in_place(operation)?;
        *self = draft;
        Ok(())
    }

    pub fn apply_operations(
        &mut self,
        operations: impl IntoIterator<Item = Operation>,
    ) -> OperationResult<()> {
        let mut draft = self.clone();
        for operation in operations {
            draft.apply_operation_in_place(operation)?;
        }
        *self = draft;
        Ok(())
    }

    pub fn apply_operation_checked(
        &mut self,
        operation: Operation,
    ) -> OperationResult<OperationReport> {
        self.apply_operations_checked([operation])
    }

    pub fn apply_operations_checked(
        &mut self,
        operations: impl IntoIterator<Item = Operation>,
    ) -> OperationResult<OperationReport> {
        let mut draft = self.clone();
        let mut applied_operations = 0;

        for operation in operations {
            draft.apply_operation_in_place(operation)?;
            applied_operations += 1;
        }

        let diagnostics = validate_scene(&draft);
        if diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        {
            return Err(OperationError::new(
                "op.validation_failed",
                "operation batch produced an invalid scene",
            )
            .with_diagnostics(diagnostics));
        }

        *self = draft;
        Ok(OperationReport {
            applied_operations,
            diagnostics,
        })
    }

    /// Internal mutation for disposable drafts. On error the caller must stop
    /// and discard the draft; public operation entry points remain atomic.
    pub(crate) fn apply_operation_in_place(&mut self, operation: Operation) -> OperationResult<()> {
        if self.is_finalized() && !operation.is_finalization() {
            return Err(OperationError::new(
                "op.finalized_scene",
                "cannot mutate a finalized template revision; create a new draft revision first",
            ));
        }

        match operation {
            Operation::AddPage { page } => self.add_page(page),
            Operation::RemovePage { page_id } => self.remove_page(&page_id),
            Operation::UpdateDocument { patch } => {
                apply_field_patch(&mut self.meta.title, patch.title);
                apply_optional_patch(&mut self.meta.artifact_type, patch.artifact_type);
                apply_optional_patch(&mut self.meta.medium, patch.medium);
                apply_optional_patch(&mut self.meta.brand_kit, patch.brand_kit);
                Ok(())
            }
            Operation::UpdatePage { page_id, patch } => self.update_page(&page_id, patch),
            Operation::InsertNode {
                parent,
                index,
                node,
            } => self.insert_node(parent, index, node),
            Operation::RemoveNode { node_id } => self.remove_node(&node_id),
            Operation::MoveNode {
                node_id,
                new_parent,
                index,
            } => self.move_node(&node_id, new_parent, index),
            Operation::UpdateNode { node_id, patch } => self.update_node(&node_id, patch),
            Operation::UpsertSlot { slot } => {
                self.slots.insert(slot.id.clone(), slot);
                Ok(())
            }
            Operation::RemoveSlot { slot_id } => {
                self.slots.remove(&slot_id);
                Ok(())
            }
            Operation::UpsertAsset { asset } => {
                self.assets.insert(asset.id.clone(), asset);
                Ok(())
            }
            Operation::RemoveAsset { asset_id } => {
                if let Some(reference) = self.asset_reference(&asset_id) {
                    return Err(OperationError::new(
                        "op.asset_in_use",
                        format!(
                            "cannot remove asset {} while it is referenced by {}",
                            asset_id, reference
                        ),
                    ));
                }
                self.assets.remove(&asset_id);
                Ok(())
            }
            Operation::PlaceAssetInNode {
                node_id,
                asset_id,
                placement,
            } => self.place_asset_in_node(&node_id, &asset_id, &placement),
            Operation::PlaceAssetInSlot {
                slot_id,
                asset_id,
                placement,
            } => self.place_asset_in_slot(&slot_id, &asset_id, &placement),
            Operation::BindNodeToSlot { slot_id, node_id } => {
                if !self.nodes.contains_key(&node_id) {
                    return Err(OperationError::new(
                        "op.node_missing",
                        format!("cannot bind missing node {}", node_id),
                    ));
                }
                let slot = self.slots.get_mut(&slot_id).ok_or_else(|| {
                    OperationError::new(
                        "op.slot_missing",
                        format!("cannot bind missing slot {}", slot_id),
                    )
                })?;
                if !slot.bound_nodes.contains(&node_id) {
                    slot.bound_nodes.push(node_id);
                }
                Ok(())
            }
            Operation::UnbindNodeFromSlot { slot_id, node_id } => {
                let slot = self.slots.get_mut(&slot_id).ok_or_else(|| {
                    OperationError::new(
                        "op.slot_missing",
                        format!("cannot unbind missing slot {}", slot_id),
                    )
                })?;
                slot.bound_nodes.retain(|id| id != &node_id);
                Ok(())
            }
            Operation::SetBrandKitRef {
                brand_kit_id,
                version,
            } => {
                self.meta.brand_kit = Some(BrandKitRef {
                    id: brand_kit_id,
                    version,
                });
                Ok(())
            }
            Operation::UpsertExportProfile { profile } => {
                if let Some(existing) = self
                    .export_profiles
                    .iter_mut()
                    .find(|candidate| candidate.name == profile.name)
                {
                    *existing = profile;
                } else {
                    self.export_profiles.push(profile);
                }
                Ok(())
            }
            Operation::RemoveExportProfile { name } => {
                self.export_profiles.retain(|profile| profile.name != name);
                Ok(())
            }
            Operation::FinalizeTemplate {
                template_revision_id,
            } => self.finalize_template(template_revision_id),
        }
    }

    fn add_page(&mut self, page: crate::scene::Page) -> OperationResult<()> {
        if self.pages.contains_key(&page.id) {
            return Err(OperationError::new(
                "op.page_exists",
                format!("page {} already exists", page.id),
            ));
        }
        self.pages.insert(page.id.clone(), page);
        Ok(())
    }

    fn remove_page(&mut self, page_id: &PageId) -> OperationResult<()> {
        let page = self.pages.remove(page_id).ok_or_else(|| {
            OperationError::new(
                "op.page_missing",
                format!("page {} does not exist", page_id),
            )
        })?;

        for node_id in page.children {
            self.remove_node_recursive(&node_id);
        }
        Ok(())
    }

    fn update_page(&mut self, page_id: &PageId, patch: PagePatch) -> OperationResult<()> {
        let page = self.pages.get_mut(page_id).ok_or_else(|| {
            OperationError::new(
                "op.page_missing",
                format!("page {} does not exist", page_id),
            )
        })?;

        apply_field_patch(&mut page.name, patch.name);
        apply_field_patch(&mut page.size, patch.size);
        apply_optional_patch(&mut page.bleed, patch.bleed);
        apply_optional_patch(&mut page.safe_area, patch.safe_area);
        apply_field_patch(&mut page.background, patch.background);
        Ok(())
    }

    fn insert_node(&mut self, parent: ParentRef, index: usize, node: Node) -> OperationResult<()> {
        if self.nodes.contains_key(&node.id) {
            return Err(OperationError::new(
                "op.node_exists",
                format!("node {} already exists", node.id),
            ));
        }

        if !node.kind.can_have_children() && !node.children.is_empty() {
            return Err(OperationError::new(
                "op.leaf_parent",
                format!("node {} cannot be inserted with children", node.id),
            ));
        }

        let mut seen_children = BTreeSet::new();
        for child_id in &node.children {
            if !seen_children.insert(child_id) {
                return Err(OperationError::new(
                    "op.duplicate_child",
                    format!("inserted node {} duplicates child {}", node.id, child_id),
                ));
            }
            if !self.nodes.contains_key(child_id) {
                return Err(OperationError::new(
                    "op.child_missing",
                    format!(
                        "inserted node {} references missing child {}",
                        node.id, child_id
                    ),
                ));
            }
            if self.parent_of(child_id).is_some() {
                return Err(OperationError::new(
                    "op.child_already_parented",
                    format!("child node {} is already parented", child_id),
                ));
            }
        }

        let children = self.children_mut_for_parent(&parent)?;
        if index > children.len() {
            return Err(OperationError::new(
                "op.index_out_of_bounds",
                format!("insert index {} is out of bounds", index),
            ));
        }

        let node_id = node.id.clone();
        children.insert(index, node_id.clone());
        self.nodes.insert(node_id, node);
        Ok(())
    }

    fn remove_node(&mut self, node_id: &NodeId) -> OperationResult<()> {
        if !self.nodes.contains_key(node_id) {
            return Err(OperationError::new(
                "op.node_missing",
                format!("node {} does not exist", node_id),
            ));
        }

        self.detach_node_from_parents(node_id);
        self.remove_node_recursive(node_id);
        Ok(())
    }

    fn move_node(
        &mut self,
        node_id: &NodeId,
        new_parent: ParentRef,
        index: usize,
    ) -> OperationResult<()> {
        if !self.nodes.contains_key(node_id) {
            return Err(OperationError::new(
                "op.node_missing",
                format!("node {} does not exist", node_id),
            ));
        }

        if let ParentRef::Node(parent_node_id) = &new_parent {
            if parent_node_id == node_id || self.is_descendant_of(parent_node_id, node_id) {
                return Err(OperationError::new(
                    "op.cycle",
                    "cannot move a node under itself or one of its descendants",
                ));
            }
        }

        let old_parent = self.parent_of(node_id);
        {
            let children = self.children_for_parent(&new_parent)?;
            if index > children.len() {
                return Err(OperationError::new(
                    "op.index_out_of_bounds",
                    format!("move index {} is out of bounds", index),
                ));
            }
        }

        self.detach_node_from_parents(node_id);
        let children = self.children_mut_for_parent(&new_parent)?;
        let same_parent = old_parent.as_ref() == Some(&new_parent);
        let insert_index = if same_parent && index > children.len() {
            children.len()
        } else if index <= children.len() {
            index
        } else {
            return Err(OperationError::new(
                "op.index_out_of_bounds",
                format!("move index {} is out of bounds after detach", index),
            ));
        };

        children.insert(insert_index, node_id.clone());
        Ok(())
    }

    fn update_node(&mut self, node_id: &NodeId, patch: NodePatch) -> OperationResult<()> {
        let current = self.nodes.get(node_id).ok_or_else(|| {
            OperationError::new(
                "op.node_missing",
                format!("node {} does not exist", node_id),
            )
        })?;

        if patch.explicit_text_tokens.is_some()
            && !matches!(&patch.kind, FieldPatch::Set(NodeKind::Text(_)))
        {
            return Err(OperationError::new(
                "op.text_token_intent",
                "explicit text token intent requires a text-kind replacement",
            ));
        }

        let next_kind = match &patch.kind {
            FieldPatch::Unchanged => current.kind.clone(),
            FieldPatch::Set(kind) => kind.clone(),
        };
        if !next_kind.can_have_children() && !current.children.is_empty() {
            return Err(OperationError::new(
                "op.leaf_parent",
                format!(
                    "node {} cannot become a leaf while it still has children",
                    node_id
                ),
            ));
        }

        // A kind replace carries whatever token fields the writer had in
        // hand; a token the write left untouched while moving its raw channel
        // is stale and must not re-resolve over the edit later.
        let previous_text = match (&patch.kind, &current.kind) {
            (FieldPatch::Set(NodeKind::Text(_)), NodeKind::Text(text)) => Some(text.clone()),
            _ => None,
        };
        // Token honesty for color: text color lives in node-level fills, and
        // the type role's baked color (plus contrast correction) re-resolves
        // over them — so a raw fills edit detaches `style_token` the same way
        // a raw typography edit does. A style_token the patch itself authored
        // survives, which is also how inverse operations restore the binding.
        let fills_changing =
            matches!(&patch.fills, FieldPatch::Set(fills) if *fills != current.fills);
        let fills_detach_style = fills_changing && fills_edit_detaches_style_token(current, &patch);

        let authored = patch.explicit_text_tokens.unwrap_or_default();
        let node = self.nodes.get_mut(node_id).expect("node checked above");
        apply_optional_patch(&mut node.name, patch.name);
        apply_field_patch(&mut node.kind, patch.kind);
        if let (Some(before), NodeKind::Text(after)) = (previous_text, &mut node.kind) {
            let explicit = ExplicitTextTokens {
                style: authored.style || after.style_token != before.style_token,
                font_size: authored.font_size || after.font_size_token != before.font_size_token,
                line_height: authored.line_height
                    || after.line_height_token != before.line_height_token,
                letter_spacing: authored.letter_spacing
                    || after.letter_spacing_token != before.letter_spacing_token,
            };
            after.clear_stale_tokens(&before, explicit);
            if fills_changing && !explicit.style {
                after.style_token = None;
            }
            // A6b D4 span honesty on the whole-kind path (review fix): a kind
            // replace that changes `content` while carrying the OLD spans
            // forward unchanged would leave stale byte offsets silently
            // mis-highlighting the new string. Identical spans on changed
            // content are indistinguishable from a stale carry-forward, so
            // honesty wins: they clear, exactly like clear_stale_tokens above.
            // A write that re-authors DIFFERENT spans alongside the new
            // content keeps them (and inverse operations restore cleared
            // spans on undo).
            if after.content != before.content && after.spans == before.spans {
                after.spans.clear();
            }
        }
        if fills_detach_style {
            if let NodeKind::Text(text) = &mut node.kind {
                text.style_token = None;
            }
        }
        apply_field_patch(&mut node.transform, patch.transform);
        apply_field_patch(&mut node.size, patch.size);
        apply_field_patch(&mut node.fills, patch.fills);
        apply_field_patch(&mut node.strokes, patch.strokes);
        apply_field_patch(&mut node.effects, patch.effects);
        apply_field_patch(&mut node.corner, patch.corner);
        apply_field_patch(&mut node.opacity, patch.opacity);
        apply_optional_patch(&mut node.opacity_token, patch.opacity_token);
        apply_optional_patch(&mut node.source_asset_id, patch.source_asset_id);
        apply_optional_patch(&mut node.asset_placement, patch.asset_placement);
        apply_field_patch(&mut node.clip, patch.clip);
        apply_field_patch(&mut node.bleed, patch.bleed);
        apply_optional_patch(&mut node.layout, patch.layout);
        apply_optional_patch(&mut node.computed, patch.computed);
        apply_field_patch(&mut node.locked, patch.locked);
        apply_field_patch(&mut node.position_mode, patch.position_mode);
        apply_optional_patch(&mut node.absolute_box, patch.absolute_box);
        apply_optional_patch(&mut node.base_anchor, patch.base_anchor);

        Ok(())
    }

    fn place_asset_in_node(
        &mut self,
        node_id: &NodeId,
        asset_id: &AssetId,
        placement: &AssetPlacement,
    ) -> OperationResult<()> {
        let asset = self.assets.get(asset_id).cloned().ok_or_else(|| {
            OperationError::new(
                "op.asset_missing",
                format!("cannot place missing asset {}", asset_id),
            )
        })?;

        let node = self.nodes.get_mut(node_id).ok_or_else(|| {
            OperationError::new(
                "op.node_missing",
                format!("cannot place asset into missing node {}", node_id),
            )
        })?;

        match &asset.kind {
            AssetKind::RasterImage | AssetKind::Logo => {
                ensure_leaf_asset_target(node)?;
                node.kind = NodeKind::Image(ImageNode {
                    asset_id: asset_id.clone(),
                    alt: placement
                        .alt_text
                        .clone()
                        .or_else(|| Some(asset.label.clone())),
                });
                node.source_asset_id = Some(asset_id.clone());
                node.asset_placement = Some(placement.clone());
                Ok(())
            }
            AssetKind::Vector => {
                ensure_leaf_asset_target(node)?;
                if let Some(path_data) = asset
                    .vector
                    .as_ref()
                    .and_then(|metadata| metadata.path_data.clone())
                {
                    node.kind = NodeKind::Vector(VectorNode {
                        path_data,
                        view_box: None,
                    });
                } else {
                    node.kind = NodeKind::Image(ImageNode {
                        asset_id: asset_id.clone(),
                        alt: placement
                            .alt_text
                            .clone()
                            .or_else(|| Some(asset.label.clone())),
                    });
                }
                node.source_asset_id = Some(asset_id.clone());
                node.asset_placement = Some(placement.clone());
                Ok(())
            }
            AssetKind::Font => {
                if !matches!(node.kind, NodeKind::Text(_)) {
                    return Err(OperationError::new(
                        "op.asset_incompatible",
                        format!("font asset {} can only be placed into text nodes", asset_id),
                    ));
                }
                node.source_asset_id = Some(asset_id.clone());
                node.asset_placement = Some(placement.clone());
                Ok(())
            }
            AssetKind::Document | AssetKind::Other => Err(OperationError::new(
                "op.asset_incompatible",
                format!("asset {} cannot be placed into a scene node", asset_id),
            )),
        }
    }

    fn place_asset_in_slot(
        &mut self,
        slot_id: &SlotId,
        asset_id: &AssetId,
        placement: &AssetPlacement,
    ) -> OperationResult<()> {
        let asset = self.assets.get(asset_id).ok_or_else(|| {
            OperationError::new(
                "op.asset_missing",
                format!("cannot place missing asset {}", asset_id),
            )
        })?;
        let slot = self.slots.get(slot_id).cloned().ok_or_else(|| {
            OperationError::new(
                "op.slot_missing",
                format!("cannot place asset into missing slot {}", slot_id),
            )
        })?;

        if slot.bound_nodes.is_empty() {
            return Err(OperationError::new(
                "op.slot_unbound",
                format!("cannot place asset into unbound slot {}", slot_id),
            ));
        }

        if !slot_accepts_asset_kind(&slot.content_type, &asset.kind) {
            return Err(OperationError::new(
                "op.asset_incompatible",
                format!(
                    "asset {} with kind {:?} is not compatible with {:?} slot {}",
                    asset_id, asset.kind, slot.content_type, slot.key
                ),
            ));
        }

        if matches!(slot.content_type, ContentType::Image) && !asset.is_image_compatible() {
            return Err(OperationError::new(
                "op.asset_incompatible",
                format!(
                    "asset {} is not compatible with image slot {}",
                    asset_id, slot.key
                ),
            ));
        }

        if matches!(slot.content_type, ContentType::Logo) && !asset.is_logo_compatible() {
            return Err(OperationError::new(
                "op.asset_incompatible",
                format!(
                    "asset {} is not compatible with logo slot {}",
                    asset_id, slot.key
                ),
            ));
        }

        for node_id in slot.bound_nodes {
            self.place_asset_in_node(&node_id, asset_id, placement)?;
        }

        Ok(())
    }

    fn asset_reference(&self, asset_id: &AssetId) -> Option<String> {
        for node in self.nodes.values() {
            if let NodeKind::Image(image) = &node.kind {
                if &image.asset_id == asset_id {
                    return Some(format!("image node {}", node.id));
                }
            }
            if node.source_asset_id.as_ref() == Some(asset_id) {
                return Some(format!("node {} source_asset_id", node.id));
            }
        }
        None
    }

    fn finalize_template(
        &mut self,
        template_revision_id: TemplateRevisionId,
    ) -> OperationResult<()> {
        if self.is_finalized() {
            return Err(OperationError::new(
                "op.already_finalized",
                "scene is already finalized",
            ));
        }

        if self.export_profiles.is_empty() {
            return Err(OperationError::new(
                "op.finalize_missing_export_profile",
                "cannot finalize a template without at least one export profile",
            ));
        }

        let diagnostics = validate_scene(self);
        if let Some(error) = diagnostics
            .iter()
            .find(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
            .cloned()
        {
            return Err(OperationError::new(
                "op.finalize_invalid_scene",
                format!(
                    "cannot finalize invalid scene: {} {}",
                    error.code, error.message
                ),
            )
            .with_diagnostics(diagnostics));
        }

        if let Some(required_placeholder) = diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code == "LUMV0501")
            .cloned()
        {
            return Err(OperationError::new(
                "op.finalize_missing_required_slot_placeholder",
                format!(
                    "cannot finalize scene with incomplete required slot: {}",
                    required_placeholder.message
                ),
            )
            .with_diagnostics(diagnostics));
        }

        self.meta.status = DocumentStatus::Finalized {
            template_revision_id,
        };
        Ok(())
    }

    fn children_for_parent(&self, parent: &ParentRef) -> OperationResult<&Vec<NodeId>> {
        match parent {
            ParentRef::Page(page_id) => self
                .pages
                .get(page_id)
                .map(|page| &page.children)
                .ok_or_else(|| {
                    OperationError::new(
                        "op.page_missing",
                        format!("parent page {} does not exist", page_id),
                    )
                }),
            ParentRef::Node(node_id) => {
                let node = self.nodes.get(node_id).ok_or_else(|| {
                    OperationError::new(
                        "op.node_missing",
                        format!("parent node {} does not exist", node_id),
                    )
                })?;
                if !node.kind.can_have_children() {
                    return Err(OperationError::new(
                        "op.leaf_parent",
                        format!("node {} cannot have children", node_id),
                    ));
                }
                Ok(&node.children)
            }
        }
    }

    fn children_mut_for_parent(&mut self, parent: &ParentRef) -> OperationResult<&mut Vec<NodeId>> {
        match parent {
            ParentRef::Page(page_id) => self
                .pages
                .get_mut(page_id)
                .map(|page| &mut page.children)
                .ok_or_else(|| {
                    OperationError::new(
                        "op.page_missing",
                        format!("parent page {} does not exist", page_id),
                    )
                }),
            ParentRef::Node(node_id) => {
                let node = self.nodes.get_mut(node_id).ok_or_else(|| {
                    OperationError::new(
                        "op.node_missing",
                        format!("parent node {} does not exist", node_id),
                    )
                })?;
                if !node.kind.can_have_children() {
                    return Err(OperationError::new(
                        "op.leaf_parent",
                        format!("node {} cannot have children", node_id),
                    ));
                }
                Ok(&mut node.children)
            }
        }
    }

    fn detach_node_from_parents(&mut self, node_id: &NodeId) {
        for page in self.pages.values_mut() {
            page.children.retain(|id| id != node_id);
        }
        for node in self.nodes.values_mut() {
            node.children.retain(|id| id != node_id);
        }
    }

    fn remove_node_recursive(&mut self, node_id: &NodeId) {
        let Some(node) = self.nodes.remove(node_id) else {
            return;
        };

        for child_id in node.children {
            self.remove_node_recursive(&child_id);
        }

        for slot in self.slots.values_mut() {
            slot.bound_nodes.retain(|id| id != node_id);
        }
    }

    fn is_descendant_of(&self, possible_descendant: &NodeId, ancestor: &NodeId) -> bool {
        let mut pending = vec![ancestor.clone()];
        let mut seen = BTreeSet::new();

        while let Some(current_id) = pending.pop() {
            if !seen.insert(current_id.clone()) {
                continue;
            }

            let Some(node) = self.nodes.get(&current_id) else {
                continue;
            };

            for child_id in &node.children {
                if child_id == possible_descendant {
                    return true;
                }
                pending.push(child_id.clone());
            }
        }

        false
    }
}

/// Does a raw fills write in `patch` detach `node`'s type role? True only
/// for a Text node holding a `style_token` while the patch leaves `kind`
/// untouched — a kind replace carries its own token intent and is covered
/// by the diff rule in `update_node`. Callers pair this with a fills
/// inequality check; apply and inverse must agree on the full condition so
/// undo restores the binding.
fn fills_edit_detaches_style_token(node: &Node, patch: &NodePatch) -> bool {
    if !matches!(patch.kind, FieldPatch::Unchanged) {
        return false;
    }
    matches!(&node.kind, NodeKind::Text(text) if text.style_token.is_some())
}

impl Scene {
    /// Compute the inverse operation batch for `operations` against this
    /// scene, stepping an internal draft through each operation so every
    /// inverse is computed against the exact intermediate state it must
    /// undo. Returns `Ok(None)` when the batch is not invertible
    /// (`FinalizeTemplate`, or an `InsertNode` adopting pre-existing
    /// children, which no edit builder emits). Inverses are returned in
    /// reverse application order, ready to apply as a single batch.
    pub fn invert_operations(
        &self,
        operations: &[Operation],
    ) -> OperationResult<Option<Vec<Operation>>> {
        let mut draft = self.clone();
        let mut inverse_groups: Vec<Vec<Operation>> = Vec::with_capacity(operations.len());

        for operation in operations {
            let Some(group) = draft.inverse_for_operation(operation)? else {
                return Ok(None);
            };
            draft.apply_operation_in_place(operation.clone())?;
            inverse_groups.push(group);
        }

        let mut inverses = Vec::new();
        for group in inverse_groups.into_iter().rev() {
            inverses.extend(group);
        }
        Ok(Some(inverses))
    }

    fn inverse_for_operation(
        &self,
        operation: &Operation,
    ) -> OperationResult<Option<Vec<Operation>>> {
        match operation {
            Operation::AddPage { page } => Ok(Some(vec![Operation::RemovePage {
                page_id: page.id.clone(),
            }])),
            Operation::RemovePage { page_id } => {
                let page = self.pages.get(page_id).ok_or_else(|| {
                    OperationError::new(
                        "op.page_missing",
                        format!("cannot invert removal of missing page {}", page_id),
                    )
                })?;
                let mut restored_page = page.clone();
                restored_page.children = Vec::new();
                let mut inverse = vec![Operation::AddPage {
                    page: restored_page,
                }];
                let mut removed = BTreeSet::new();
                for (index, child_id) in page.children.iter().enumerate() {
                    self.restore_subtree_operations(
                        ParentRef::Page(page_id.clone()),
                        index,
                        child_id,
                        &mut inverse,
                        &mut removed,
                    )?;
                }
                inverse.extend(self.slot_restore_operations(&removed));
                Ok(Some(inverse))
            }
            Operation::UpdateDocument { patch } => {
                let mut inverse = DocumentPatch::default();
                if !matches!(patch.title, FieldPatch::Unchanged) {
                    inverse.title = FieldPatch::Set(self.meta.title.clone());
                }
                if !matches!(patch.artifact_type, OptionalFieldPatch::Unchanged) {
                    inverse.artifact_type = optional_restore(&self.meta.artifact_type);
                }
                if !matches!(patch.medium, OptionalFieldPatch::Unchanged) {
                    inverse.medium = optional_restore(&self.meta.medium);
                }
                if !matches!(patch.brand_kit, OptionalFieldPatch::Unchanged) {
                    inverse.brand_kit = optional_restore(&self.meta.brand_kit);
                }
                Ok(Some(vec![Operation::UpdateDocument { patch: inverse }]))
            }
            Operation::UpdatePage { page_id, patch } => {
                let page = self.pages.get(page_id).ok_or_else(|| {
                    OperationError::new(
                        "op.page_missing",
                        format!("cannot invert update of missing page {}", page_id),
                    )
                })?;
                let mut inverse = PagePatch::default();
                if !matches!(patch.name, FieldPatch::Unchanged) {
                    inverse.name = FieldPatch::Set(page.name.clone());
                }
                if !matches!(patch.size, FieldPatch::Unchanged) {
                    inverse.size = FieldPatch::Set(page.size.clone());
                }
                if !matches!(patch.bleed, OptionalFieldPatch::Unchanged) {
                    inverse.bleed = optional_restore(&page.bleed);
                }
                if !matches!(patch.safe_area, OptionalFieldPatch::Unchanged) {
                    inverse.safe_area = optional_restore(&page.safe_area);
                }
                if !matches!(patch.background, FieldPatch::Unchanged) {
                    inverse.background = FieldPatch::Set(page.background.clone());
                }
                Ok(Some(vec![Operation::UpdatePage {
                    page_id: page_id.clone(),
                    patch: inverse,
                }]))
            }
            Operation::InsertNode { node, .. } => {
                if node.children.is_empty() {
                    Ok(Some(vec![Operation::RemoveNode {
                        node_id: node.id.clone(),
                    }]))
                } else {
                    // Removing the inserted node would also delete the
                    // adopted pre-existing children; there is no detach
                    // operation, so this insert form is not invertible.
                    Ok(None)
                }
            }
            Operation::RemoveNode { node_id } => {
                let Some(parent) = self.parent_of(node_id) else {
                    return Ok(None);
                };
                let index = self
                    .children_for_parent(&parent)?
                    .iter()
                    .position(|id| id == node_id)
                    .ok_or_else(|| {
                        OperationError::new(
                            "op.node_missing",
                            format!("node {} is not in its parent", node_id),
                        )
                    })?;
                let mut inverse = Vec::new();
                let mut removed = BTreeSet::new();
                self.restore_subtree_operations(
                    parent,
                    index,
                    node_id,
                    &mut inverse,
                    &mut removed,
                )?;
                inverse.extend(self.slot_restore_operations(&removed));
                Ok(Some(inverse))
            }
            Operation::MoveNode { node_id, .. } => {
                let Some(parent) = self.parent_of(node_id) else {
                    return Ok(None);
                };
                let index = self
                    .children_for_parent(&parent)?
                    .iter()
                    .position(|id| id == node_id)
                    .ok_or_else(|| {
                        OperationError::new(
                            "op.node_missing",
                            format!("node {} is not in its parent", node_id),
                        )
                    })?;
                Ok(Some(vec![Operation::MoveNode {
                    node_id: node_id.clone(),
                    new_parent: parent,
                    index,
                }]))
            }
            Operation::UpdateNode { node_id, patch } => {
                let node = self.nodes.get(node_id).ok_or_else(|| {
                    OperationError::new(
                        "op.node_missing",
                        format!("cannot invert update of missing node {}", node_id),
                    )
                })?;
                let mut inverse = NodePatch::default();
                if !matches!(patch.name, OptionalFieldPatch::Unchanged) {
                    inverse.name = optional_restore(&node.name);
                }
                if !matches!(patch.kind, FieldPatch::Unchanged) {
                    inverse.kind = FieldPatch::Set(node.kind.clone());
                }
                // A raw fills edit on a text node clears `style_token` as a
                // side effect (token honesty for color, `update_node`); the
                // inverse restores the whole kind so undo restores the
                // binding along with the fills.
                if matches!(&patch.fills, FieldPatch::Set(fills) if *fills != node.fills)
                    && fills_edit_detaches_style_token(node, patch)
                {
                    inverse.kind = FieldPatch::Set(node.kind.clone());
                }
                // Replaying an explicit reapplication backwards must retain
                // that intent too. Legacy inverses keep their wire shape.
                if matches!(&inverse.kind, FieldPatch::Set(NodeKind::Text(_))) {
                    inverse.explicit_text_tokens = patch.explicit_text_tokens;
                }
                if !matches!(patch.transform, FieldPatch::Unchanged) {
                    inverse.transform = FieldPatch::Set(node.transform.clone());
                }
                if !matches!(patch.size, FieldPatch::Unchanged) {
                    inverse.size = FieldPatch::Set(node.size.clone());
                }
                if !matches!(patch.fills, FieldPatch::Unchanged) {
                    inverse.fills = FieldPatch::Set(node.fills.clone());
                }
                if !matches!(patch.strokes, FieldPatch::Unchanged) {
                    inverse.strokes = FieldPatch::Set(node.strokes.clone());
                }
                if !matches!(patch.effects, FieldPatch::Unchanged) {
                    inverse.effects = FieldPatch::Set(node.effects.clone());
                }
                if !matches!(patch.corner, FieldPatch::Unchanged) {
                    inverse.corner = FieldPatch::Set(node.corner.clone());
                }
                if !matches!(patch.opacity, FieldPatch::Unchanged) {
                    inverse.opacity = FieldPatch::Set(node.opacity);
                }
                if !matches!(patch.opacity_token, OptionalFieldPatch::Unchanged) {
                    inverse.opacity_token = optional_restore(&node.opacity_token);
                }
                if !matches!(patch.source_asset_id, OptionalFieldPatch::Unchanged) {
                    inverse.source_asset_id = optional_restore(&node.source_asset_id);
                }
                if !matches!(patch.asset_placement, OptionalFieldPatch::Unchanged) {
                    inverse.asset_placement = optional_restore(&node.asset_placement);
                }
                if !matches!(patch.clip, FieldPatch::Unchanged) {
                    inverse.clip = FieldPatch::Set(node.clip);
                }
                if !matches!(patch.bleed, FieldPatch::Unchanged) {
                    inverse.bleed = FieldPatch::Set(node.bleed);
                }
                if !matches!(patch.layout, OptionalFieldPatch::Unchanged) {
                    inverse.layout = optional_restore(&node.layout);
                }
                if !matches!(patch.computed, OptionalFieldPatch::Unchanged) {
                    inverse.computed = optional_restore(&node.computed);
                }
                if !matches!(patch.locked, FieldPatch::Unchanged) {
                    inverse.locked = FieldPatch::Set(node.locked);
                }
                if !matches!(patch.position_mode, FieldPatch::Unchanged) {
                    inverse.position_mode = FieldPatch::Set(node.position_mode);
                }
                if !matches!(patch.absolute_box, OptionalFieldPatch::Unchanged) {
                    inverse.absolute_box = optional_restore(&node.absolute_box);
                }
                if !matches!(patch.base_anchor, OptionalFieldPatch::Unchanged) {
                    inverse.base_anchor = optional_restore(&node.base_anchor);
                }
                Ok(Some(vec![Operation::UpdateNode {
                    node_id: node_id.clone(),
                    patch: inverse,
                }]))
            }
            Operation::UpsertSlot { slot } => Ok(Some(match self.slots.get(&slot.id) {
                Some(prior) => vec![Operation::UpsertSlot {
                    slot: prior.clone(),
                }],
                None => vec![Operation::RemoveSlot {
                    slot_id: slot.id.clone(),
                }],
            })),
            Operation::RemoveSlot { slot_id } => Ok(Some(match self.slots.get(slot_id) {
                Some(prior) => vec![Operation::UpsertSlot {
                    slot: prior.clone(),
                }],
                None => Vec::new(),
            })),
            Operation::UpsertAsset { asset } => Ok(Some(match self.assets.get(&asset.id) {
                Some(prior) => vec![Operation::UpsertAsset {
                    asset: prior.clone(),
                }],
                None => vec![Operation::RemoveAsset {
                    asset_id: asset.id.clone(),
                }],
            })),
            Operation::RemoveAsset { asset_id } => Ok(Some(match self.assets.get(asset_id) {
                Some(prior) => vec![Operation::UpsertAsset {
                    asset: prior.clone(),
                }],
                None => Vec::new(),
            })),
            Operation::PlaceAssetInNode { node_id, .. } => {
                let node = self.nodes.get(node_id).ok_or_else(|| {
                    OperationError::new(
                        "op.node_missing",
                        format!("cannot invert placement into missing node {}", node_id),
                    )
                })?;
                Ok(Some(vec![node_restore_after_placement(node)]))
            }
            Operation::PlaceAssetInSlot { slot_id, .. } => {
                let slot = self.slots.get(slot_id).ok_or_else(|| {
                    OperationError::new(
                        "op.slot_missing",
                        format!("cannot invert placement into missing slot {}", slot_id),
                    )
                })?;
                let inverse = slot
                    .bound_nodes
                    .iter()
                    .filter_map(|node_id| self.nodes.get(node_id))
                    .map(node_restore_after_placement)
                    .collect();
                Ok(Some(inverse))
            }
            Operation::BindNodeToSlot { slot_id, .. }
            | Operation::UnbindNodeFromSlot { slot_id, .. } => {
                let slot = self.slots.get(slot_id).ok_or_else(|| {
                    OperationError::new(
                        "op.slot_missing",
                        format!("cannot invert binding change on missing slot {}", slot_id),
                    )
                })?;
                Ok(Some(vec![Operation::UpsertSlot { slot: slot.clone() }]))
            }
            Operation::SetBrandKitRef { .. } => Ok(Some(vec![Operation::UpdateDocument {
                patch: DocumentPatch {
                    brand_kit: optional_restore(&self.meta.brand_kit),
                    ..DocumentPatch::default()
                },
            }])),
            Operation::UpsertExportProfile { profile } => {
                Ok(Some(match self.export_profile(&profile.name) {
                    Some(prior) => vec![Operation::UpsertExportProfile {
                        profile: prior.clone(),
                    }],
                    None => vec![Operation::RemoveExportProfile {
                        name: profile.name.clone(),
                    }],
                }))
            }
            Operation::RemoveExportProfile { name } => Ok(Some(match self.export_profile(name) {
                Some(prior) => vec![Operation::UpsertExportProfile {
                    profile: prior.clone(),
                }],
                None => Vec::new(),
            })),
            Operation::FinalizeTemplate { .. } => Ok(None),
        }
    }

    fn restore_subtree_operations(
        &self,
        parent: ParentRef,
        index: usize,
        node_id: &NodeId,
        out: &mut Vec<Operation>,
        removed: &mut BTreeSet<NodeId>,
    ) -> OperationResult<()> {
        let node = self.nodes.get(node_id).ok_or_else(|| {
            OperationError::new(
                "op.node_missing",
                format!("cannot restore missing node {}", node_id),
            )
        })?;
        removed.insert(node_id.clone());
        let mut restored = node.clone();
        restored.children = Vec::new();
        out.push(Operation::InsertNode {
            parent,
            index,
            node: restored,
        });
        for (child_index, child_id) in node.children.iter().enumerate() {
            self.restore_subtree_operations(
                ParentRef::Node(node_id.clone()),
                child_index,
                child_id,
                out,
                removed,
            )?;
        }
        Ok(())
    }

    fn slot_restore_operations(&self, removed: &BTreeSet<NodeId>) -> Vec<Operation> {
        self.slots
            .values()
            .filter(|slot| slot.bound_nodes.iter().any(|id| removed.contains(id)))
            .map(|slot| Operation::UpsertSlot { slot: slot.clone() })
            .collect()
    }
}

fn node_restore_after_placement(node: &Node) -> Operation {
    Operation::UpdateNode {
        node_id: node.id.clone(),
        patch: NodePatch {
            kind: FieldPatch::Set(node.kind.clone()),
            source_asset_id: optional_restore(&node.source_asset_id),
            asset_placement: optional_restore(&node.asset_placement),
            ..NodePatch::default()
        },
    }
}

fn optional_restore<T: Clone>(prior: &Option<T>) -> OptionalFieldPatch<T> {
    match prior {
        Some(value) => OptionalFieldPatch::Set(value.clone()),
        None => OptionalFieldPatch::Clear,
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

fn ensure_leaf_asset_target(node: &Node) -> OperationResult<()> {
    if node.children.is_empty() {
        Ok(())
    } else {
        Err(OperationError::new(
            "op.leaf_parent",
            format!(
                "node {} cannot become an asset leaf while it still has children",
                node.id
            ),
        ))
    }
}

fn slot_accepts_asset_kind(content_type: &ContentType, asset_kind: &AssetKind) -> bool {
    match content_type {
        ContentType::Image | ContentType::Logo => matches!(
            asset_kind,
            AssetKind::RasterImage | AssetKind::Vector | AssetKind::Logo
        ),
        ContentType::TextShort | ContentType::TextLong | ContentType::RichTextLimited => {
            matches!(asset_kind, AssetKind::Font)
        }
        // Phase G: UrlQr slots receive generated QR codes, which the QR
        // provider always emits as sanitized vector assets.
        ContentType::UrlQr => matches!(asset_kind, AssetKind::Vector),
        ContentType::NumberStat
        | ContentType::Date
        | ContentType::List
        | ContentType::RepeaterGroup
        | ContentType::TableLike => false,
    }
}
