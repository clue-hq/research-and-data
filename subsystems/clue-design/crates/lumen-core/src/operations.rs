use crate::diagnostics::DiagnosticSeverity;
use crate::export_contract::ExportProfile;
use crate::ids::{BrandKitId, NodeId, PageId, SlotId, TemplateRevisionId};
use crate::scene::{
    AutoLayoutProps, BrandKitRef, ComputedGeometry, CornerRadii, DocumentStatus, Fill, Medium,
    Node, NodeKind, PageSize, Rect, Scene, SizeSpec, Stroke, Transform,
};
use crate::slots::Slot;
use crate::validation::validate_scene;
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

pub type OperationResult<T> = Result<T, OperationError>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationError {
    pub code: &'static str,
    pub message: String,
}

impl OperationError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for OperationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for OperationError {}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum ParentRef {
    Page(PageId),
    Node(NodeId),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum FieldPatch<T> {
    Unchanged,
    Set(T),
}

impl<T> Default for FieldPatch<T> {
    fn default() -> Self {
        Self::Unchanged
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum OptionalFieldPatch<T> {
    Unchanged,
    Set(T),
    Clear,
}

impl<T> Default for OptionalFieldPatch<T> {
    fn default() -> Self {
        Self::Unchanged
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
    pub transform: FieldPatch<Transform>,
    pub size: FieldPatch<SizeSpec>,
    pub fills: FieldPatch<Vec<Fill>>,
    pub strokes: FieldPatch<Vec<Stroke>>,
    pub corner: FieldPatch<CornerRadii>,
    pub opacity: FieldPatch<f64>,
    pub clip: FieldPatch<bool>,
    pub layout: OptionalFieldPatch<AutoLayoutProps>,
    pub computed: OptionalFieldPatch<ComputedGeometry>,
    pub locked: FieldPatch<bool>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
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

    pub fn apply_operations(
        &mut self,
        operations: impl IntoIterator<Item = Operation>,
    ) -> OperationResult<()> {
        for operation in operations {
            self.apply_operation(operation)?;
        }
        Ok(())
    }

    pub fn is_finalized(&self) -> bool {
        matches!(self.meta.status, DocumentStatus::Finalized { .. })
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

        for child_id in &node.children {
            if !self.nodes.contains_key(child_id) {
                return Err(OperationError::new(
                    "op.child_missing",
                    format!(
                        "inserted node {} references missing child {}",
                        node.id, child_id
                    ),
                ));
            }
            if self.find_parent_of(child_id).is_some() {
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

        let old_parent = self.find_parent_of(node_id);
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

        let node = self.nodes.get_mut(node_id).expect("node checked above");
        apply_optional_patch(&mut node.name, patch.name);
        apply_field_patch(&mut node.kind, patch.kind);
        apply_field_patch(&mut node.transform, patch.transform);
        apply_field_patch(&mut node.size, patch.size);
        apply_field_patch(&mut node.fills, patch.fills);
        apply_field_patch(&mut node.strokes, patch.strokes);
        apply_field_patch(&mut node.corner, patch.corner);
        apply_field_patch(&mut node.opacity, patch.opacity);
        apply_field_patch(&mut node.clip, patch.clip);
        apply_optional_patch(&mut node.layout, patch.layout);
        apply_optional_patch(&mut node.computed, patch.computed);
        apply_field_patch(&mut node.locked, patch.locked);

        Ok(())
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
        {
            return Err(OperationError::new(
                "op.finalize_invalid_scene",
                format!(
                    "cannot finalize invalid scene: {} {}",
                    error.code, error.message
                ),
            ));
        }

        if let Some(required_placeholder) = diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code == "LUMV0501")
        {
            return Err(OperationError::new(
                "op.finalize_missing_required_slot_placeholder",
                format!(
                    "cannot finalize scene with incomplete required slot: {}",
                    required_placeholder.message
                ),
            ));
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

    fn find_parent_of(&self, node_id: &NodeId) -> Option<ParentRef> {
        for page in self.pages.values() {
            if page.children.contains(node_id) {
                return Some(ParentRef::Page(page.id.clone()));
            }
        }
        for node in self.nodes.values() {
            if node.children.contains(node_id) {
                return Some(ParentRef::Node(node.id.clone()));
            }
        }
        None
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
        let Some(node) = self.nodes.get(ancestor) else {
            return false;
        };

        for child_id in &node.children {
            if child_id == possible_descendant
                || self.is_descendant_of(possible_descendant, child_id)
            {
                return true;
            }
        }

        false
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
