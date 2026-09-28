//! Slice 3 — the pure engine reconciler.
//!
//! `reconcile_subtree` diffs a container's **full intended child subtree**
//! (re-emitted declaratively by the agent) against the container's live
//! subtree in the scene and returns the MINIMAL operations that transform
//! the live tree into the intended one. It knows nothing about the DSL: it
//! operates on materialized [`Node`] trees and is unit-testable in isolation.
//!
//! Semantics (see `.context/slice3-reconcile/DESIGN.md`):
//! - an id present in both → `UpdateNode` with only the changed fields
//!   (field-level diff), plus `MoveNode` when parent/index changed;
//!   unchanged nodes yield zero ops (idempotence);
//! - an id only in the intended tree → `InsertNode` at its (parent, index);
//! - an id only in the live subtree → `RemoveNode` if agent-born, or KEPT
//!   with a note if protected (the human-content protection rule).
//!
//! Op ordering: removals first, then updates/moves/inserts together in intended
//! top-down order. A new parent must be inserted before an existing child moves
//! into it. Move decisions use a private cursor with each planned operation
//! applied, so earlier structural changes cannot leave stale sibling indices.
//! The whole batch applies through the session's checked path.

use crate::operations::{FieldPatch, NodePatch, OptionalFieldPatch};
use crate::scene::{ExplicitTextTokens, Node, NodeKind, ParentRef, Scene};
use crate::{NodeId, Operation};
use std::collections::{BTreeMap, BTreeSet};

/// The intended child subtree for a container, materialized as detached
/// [`Node`] values. `container_children` is the intended, ordered list of the
/// container's direct children; `nodes` holds every node in the intended
/// subtree keyed by id, each with its own `children` ids populated. The
/// container node itself is NOT included (its intended child order rides
/// `container_children`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IntendedSubtree {
    pub container_children: Vec<NodeId>,
    pub nodes: BTreeMap<NodeId, Node>,
}

/// A non-operation outcome the reconciler must surface (never silent). Each
/// note maps to a DSL diagnostic at the close site.
#[derive(Clone, Debug, PartialEq)]
pub enum ReconcileNote {
    /// A protected (seed-born / human) node was omitted from the intended
    /// block; it was KEPT rather than removed. Maps to LUMD0262.
    ProtectedKept(NodeId),
    /// Per-close summary of what the reconcile did. Maps to LUMD0263.
    Summary {
        container: NodeId,
        updated: usize,
        inserted: usize,
        removed: usize,
        moved: usize,
        kept_protected: usize,
    },
}

/// Diff `container_id`'s live subtree against `intended` and produce the
/// minimal operations plus notes. Pure: it does not mutate `scene`.
pub fn reconcile_subtree(
    scene: &Scene,
    container_id: &NodeId,
    intended: &IntendedSubtree,
    protected: &BTreeSet<NodeId>,
) -> (Vec<Operation>, Vec<ReconcileNote>) {
    // The set of ids that live under the container in the current scene.
    let live_descendants: BTreeSet<NodeId> =
        scene.descendants_of(container_id).into_iter().collect();
    // The set of ids the intended tree declares.
    let intended_ids: BTreeSet<NodeId> = intended.nodes.keys().cloned().collect();

    let mut operations: Vec<Operation> = Vec::new();
    let mut notes: Vec<ReconcileNote> = Vec::new();

    // Intended (parent, index) for every intended node, so moves/inserts can
    // be placed deterministically. The container's direct children carry
    // ParentRef::Node(container); deeper nodes carry their intended parent.
    let intended_placement = intended_placements(container_id, intended);

    // ---- Removals first ----------------------------------------------------
    // A live descendant absent from the intended tree is removed (agent-born)
    // or kept (protected). We only emit RemoveNode for the TOP of each removed
    // subtree: RemoveNode recurses, so removing an ancestor already takes its
    // descendants. Protected nodes anywhere in the omitted set block removal
    // of themselves; a protected node under an omitted agent-born ancestor
    // still cannot be silently destroyed, so its ancestor is NOT removed and
    // the protected node is reported kept (conservative: keep, warn).
    let mut removed_count = 0usize;
    let mut kept_count = 0usize;
    let omitted: BTreeSet<NodeId> = live_descendants
        .iter()
        .filter(|id| !intended_ids.contains(*id))
        .cloned()
        .collect();
    // Nodes that must survive: protected omitted nodes, plus every live
    // ancestor of such a node (so the protected node keeps a parent chain).
    let mut must_keep: BTreeSet<NodeId> = BTreeSet::new();
    for id in &omitted {
        if protected.contains(id) {
            must_keep.insert(id.clone());
            let mut cursor = id.clone();
            while let Some(ParentRef::Node(parent)) = scene.parent_of(&cursor) {
                if &parent == container_id || !live_descendants.contains(&parent) {
                    break;
                }
                must_keep.insert(parent.clone());
                cursor = parent;
            }
        }
    }
    for id in &omitted {
        if must_keep.contains(id) {
            if protected.contains(id) {
                notes.push(ReconcileNote::ProtectedKept(id.clone()));
                kept_count += 1;
            }
            continue;
        }
        // Emit a removal only for the shallowest omitted-and-removable node in
        // each chain: if a live ancestor is also being removed, this node is
        // taken by that ancestor's recursive RemoveNode.
        let ancestor_removed = live_ancestors(scene, id, container_id)
            .into_iter()
            .any(|ancestor| omitted.contains(&ancestor) && !must_keep.contains(&ancestor));
        if !ancestor_removed {
            operations.push(Operation::RemoveNode {
                node_id: id.clone(),
            });
            removed_count += 1;
        }
    }

    // One disposable clone tracks the actual intermediate placements. Use the
    // engine's own in-place operation implementation instead of duplicating its
    // parent/index rules or cloning the whole scene again for every operation.
    let mut cursor = scene.clone();
    for operation in &operations {
        if cursor.apply_operation_in_place(operation.clone()).is_err() {
            // Keep the failing operation for the checked caller to diagnose.
            return (operations, notes);
        }
    }

    // ---- Updates / moves / inserts (top-down) -----------------------------
    // Keep structural changes in ONE traversal: an existing child can move
    // into a newly declared parent only after that parent's insertion.
    let mut updated_count = 0usize;
    let mut moved_count = 0usize;
    let mut inserted_count = 0usize;
    let ordered_common = intended_topological_order(container_id, intended);
    for id in &ordered_common {
        let Some(intended_node) = intended.nodes.get(id) else {
            continue;
        };
        if !live_descendants.contains(id) {
            let Some((parent, index)) = intended_placement.get(id) else {
                continue;
            };
            // Insert childless; each later child's insert/move populates it.
            let mut node = intended_node.clone();
            node.children = Vec::new();
            let operation = Operation::InsertNode {
                parent: parent.clone(),
                index: *index,
                node,
            };
            inserted_count += 1;
            if !plan_operation(&mut cursor, &mut operations, operation) {
                break;
            }
            continue;
        }
        let Some(live) = scene.nodes.get(id) else {
            continue;
        };
        if let Some(patch) = diff_node(live, intended_node) {
            let operation = Operation::UpdateNode {
                node_id: id.clone(),
                patch,
            };
            updated_count += 1;
            if !plan_operation(&mut cursor, &mut operations, operation) {
                break;
            }
        }
        // Compare with the intermediate scene, not the original live indices.
        if let Some((intended_parent, intended_index)) = intended_placement.get(id) {
            let live_parent = cursor.parent_of(id);
            let live_index = live_child_index(&cursor, id);
            let parent_changed = live_parent.as_ref() != Some(intended_parent);
            let index_changed = live_index != Some(*intended_index);
            if parent_changed || index_changed {
                let operation = Operation::MoveNode {
                    node_id: id.clone(),
                    new_parent: intended_parent.clone(),
                    index: *intended_index,
                };
                moved_count += 1;
                if !plan_operation(&mut cursor, &mut operations, operation) {
                    break;
                }
            }
        }
    }

    notes.push(ReconcileNote::Summary {
        container: container_id.clone(),
        updated: updated_count,
        inserted: inserted_count,
        removed: removed_count,
        moved: moved_count,
        kept_protected: kept_count,
    });

    (operations, notes)
}

/// Keep even a failing operation in the plan so the caller's checked apply
/// reports the real engine error. The disposable cursor is never used again
/// after an error, and no partial cursor state is returned or persisted.
fn plan_operation(cursor: &mut Scene, operations: &mut Vec<Operation>, operation: Operation) -> bool {
    let applied = cursor.apply_operation_in_place(operation.clone()).is_ok();
    operations.push(operation);
    applied
}

/// Field-level diff of a live node against its intended counterpart. Returns
/// `Some(patch)` with ONLY the changed fields set, or `None` when the nodes
/// are field-identical (idempotence). `children` and `id` are structural and
/// handled by insert/move/remove, never by the patch.
fn diff_node(live: &Node, intended: &Node) -> Option<NodePatch> {
    let mut patch = NodePatch::default();
    let mut changed = false;

    if live.name != intended.name {
        patch.name = match &intended.name {
            Some(name) => OptionalFieldPatch::Set(name.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if !node_kind_eq(&live.kind, &intended.kind) {
        patch.kind = FieldPatch::Set(intended.kind.clone());
        // A declarative text kind is the complete intended state, including
        // identical bindings and explicit absence, not an inspector spread.
        if matches!(&intended.kind, NodeKind::Text(_)) {
            patch.explicit_text_tokens = Some(ExplicitTextTokens {
                style: true,
                font_size: true,
                line_height: true,
                letter_spacing: true,
            });
        }
        changed = true;
    }
    if live.transform != intended.transform {
        patch.transform = FieldPatch::Set(intended.transform.clone());
        changed = true;
    }
    if live.size != intended.size {
        patch.size = FieldPatch::Set(intended.size.clone());
        changed = true;
    }
    // Fills / strokes / effects compare as whole stacks (stack-level Set when
    // different — no per-paint diffing in v0).
    if live.fills != intended.fills {
        patch.fills = FieldPatch::Set(intended.fills.clone());
        changed = true;
    }
    if live.strokes != intended.strokes {
        patch.strokes = FieldPatch::Set(intended.strokes.clone());
        changed = true;
    }
    if live.effects != intended.effects {
        patch.effects = FieldPatch::Set(intended.effects.clone());
        changed = true;
    }
    if live.corner != intended.corner {
        patch.corner = FieldPatch::Set(intended.corner.clone());
        changed = true;
    }
    if live.opacity != intended.opacity {
        patch.opacity = FieldPatch::Set(intended.opacity);
        changed = true;
    }
    if live.opacity_token != intended.opacity_token {
        patch.opacity_token = match &intended.opacity_token {
            Some(token) => OptionalFieldPatch::Set(token.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if live.source_asset_id != intended.source_asset_id {
        patch.source_asset_id = match &intended.source_asset_id {
            Some(asset) => OptionalFieldPatch::Set(asset.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if live.asset_placement != intended.asset_placement {
        patch.asset_placement = match &intended.asset_placement {
            Some(placement) => OptionalFieldPatch::Set(placement.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if live.clip != intended.clip {
        patch.clip = FieldPatch::Set(intended.clip);
        changed = true;
    }
    if live.layout != intended.layout {
        patch.layout = match &intended.layout {
            Some(layout) => OptionalFieldPatch::Set(layout.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if live.locked != intended.locked {
        patch.locked = FieldPatch::Set(intended.locked);
        changed = true;
    }
    if live.position_mode != intended.position_mode {
        patch.position_mode = FieldPatch::Set(intended.position_mode);
        changed = true;
    }
    if live.absolute_box != intended.absolute_box {
        patch.absolute_box = match &intended.absolute_box {
            Some(rect) => OptionalFieldPatch::Set(rect.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    if live.base_anchor != intended.base_anchor {
        patch.base_anchor = match &intended.base_anchor {
            Some(rect) => OptionalFieldPatch::Set(rect.clone()),
            None => OptionalFieldPatch::Clear,
        };
        changed = true;
    }
    // `computed` is a solver artifact, not authored content: it is never
    // diffed here (the layout pass re-derives it after the batch applies).

    if changed {
        Some(patch)
    } else {
        None
    }
}

/// Structural kind comparison. NodeKind derives PartialEq, so this is a direct
/// equality — but we keep it behind a helper so the "kind compares
/// structurally" contract reads explicitly at the call site.
fn node_kind_eq(a: &NodeKind, b: &NodeKind) -> bool {
    a == b
}

/// The intended (parent, index) for every node in the intended subtree. The
/// container's direct children are parented to the container; deeper nodes are
/// parented to their intended parent at their position in that parent's
/// `children` list.
fn intended_placements(
    container_id: &NodeId,
    intended: &IntendedSubtree,
) -> BTreeMap<NodeId, (ParentRef, usize)> {
    let mut placements = BTreeMap::new();
    for (index, child) in intended.container_children.iter().enumerate() {
        placements.insert(child.clone(), (ParentRef::Node(container_id.clone()), index));
    }
    for node in intended.nodes.values() {
        for (index, child) in node.children.iter().enumerate() {
            placements.insert(child.clone(), (ParentRef::Node(node.id.clone()), index));
        }
    }
    placements
}

/// Intended nodes in top-down order (parents before children), rooted at the
/// container's direct children. Deterministic: children follow their parent's
/// intended child order.
fn intended_topological_order(container_id: &NodeId, intended: &IntendedSubtree) -> Vec<NodeId> {
    let mut order = Vec::new();
    let mut seen = BTreeSet::new();
    let _ = container_id;
    let mut stack: Vec<NodeId> = intended.container_children.iter().rev().cloned().collect();
    while let Some(id) = stack.pop() {
        if !seen.insert(id.clone()) {
            continue;
        }
        order.push(id.clone());
        if let Some(node) = intended.nodes.get(&id) {
            for child in node.children.iter().rev() {
                stack.push(child.clone());
            }
        }
    }
    order
}

/// The live ancestors of `node_id` up to (but excluding) `container_id`.
fn live_ancestors(scene: &Scene, node_id: &NodeId, container_id: &NodeId) -> Vec<NodeId> {
    let mut ancestors = Vec::new();
    let mut cursor = node_id.clone();
    while let Some(ParentRef::Node(parent)) = scene.parent_of(&cursor) {
        if &parent == container_id {
            break;
        }
        ancestors.push(parent.clone());
        cursor = parent;
    }
    ancestors
}

/// The index of `node_id` within its live parent's child list, if parented.
fn live_child_index(scene: &Scene, node_id: &NodeId) -> Option<usize> {
    match scene.parent_of(node_id)? {
        ParentRef::Node(parent) => scene
            .nodes
            .get(&parent)
            .and_then(|node| node.children.iter().position(|child| child == node_id)),
        ParentRef::Page(page) => scene
            .pages
            .get(&page)
            .and_then(|page| page.children.iter().position(|child| child == node_id)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{
        AutoLayoutNode, Page, PageSize, TextAlign, TextDirection, TextNode, TextWrap,
    };
    use crate::{
        AutoLayoutDirection, DocumentId, Operation, Orientation, PageId, PagePreset, SizeSpec, Unit,
    };

    fn scene_with_container() -> Scene {
        // A page holding one auto-layout container `band` with two agent-born
        // text children `a` and `b` (in that order). This is the live baseline
        // every unit test reconciles against.
        let mut scene = Scene::new(DocumentId::from("doc_reconcile"), "Reconcile");
        scene
            .apply_operation(Operation::AddPage {
                page: Page {
                    id: PageId::from("page"),
                    name: "Page".to_owned(),
                    size: PageSize {
                        width: 400.0,
                        height: 400.0,
                        unit: Unit::Px,
                        preset: Some(PagePreset::Custom),
                        orientation: Orientation::Portrait,
                        source: None,
                        output: None,
                    },
                    children: Vec::new(),
                    bleed: None,
                    safe_area: None,
                    background: Vec::new(),
                },
            })
            .unwrap();
        scene
            .apply_operation(Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page")),
                index: 0,
                node: container("band"),
            })
            .unwrap();
        scene
            .apply_operation(Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("band")),
                index: 0,
                node: text("a", "Alpha"),
            })
            .unwrap();
        scene
            .apply_operation(Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("band")),
                index: 1,
                node: text("b", "Bravo"),
            })
            .unwrap();
        scene
    }

    fn container(id: &str) -> Node {
        let mut node = Node::new(
            NodeId::from(id),
            NodeKind::AutoLayout(AutoLayoutNode {
                direction: AutoLayoutDirection::Column,
                wrap: false,
            }),
        );
        node.size = SizeSpec::fixed(400.0, 400.0);
        node
    }

    fn text(id: &str, content: &str) -> Node {
        let mut node = Node::new(
            NodeId::from(id),
            NodeKind::Text(TextNode {
                content: content.to_owned(),
                font_family: "Inter".to_owned(),
                font_size: 16.0,
                font_weight: 400,
                align: TextAlign::Left,
                line_height: 1.2,
                letter_spacing: 0.0,
                max_lines: None,
                wrap: TextWrap::NoWrap,
                direction: TextDirection::Ltr,
                style_token: None,
                font_size_token: None,
                line_height_token: None,
                letter_spacing_token: None,
                ..TextNode::default()
            }),
        );
        node.size = SizeSpec::fixed(300.0, 40.0);
        node
    }

    /// Build an intended subtree from the live children of `container` in
    /// `scene` (deep clone), so an unedited round-trip is trivially identical.
    fn intended_from_live(scene: &Scene, container_id: &NodeId) -> IntendedSubtree {
        let mut nodes = BTreeMap::new();
        let container = scene.nodes.get(container_id).expect("container exists");
        for descendant in scene.descendants_of(container_id) {
            nodes.insert(
                descendant.clone(),
                scene.nodes.get(&descendant).expect("descendant").clone(),
            );
        }
        IntendedSubtree {
            container_children: container.children.clone(),
            nodes,
        }
    }

    fn summary(notes: &[ReconcileNote]) -> (usize, usize, usize, usize, usize) {
        notes
            .iter()
            .find_map(|note| match note {
                ReconcileNote::Summary {
                    updated,
                    inserted,
                    removed,
                    moved,
                    kept_protected,
                    ..
                } => Some((*updated, *inserted, *removed, *moved, *kept_protected)),
                _ => None,
            })
            .expect("summary note present")
    }

    // Test 1 — idempotence: an identical intended tree yields zero operations.
    #[test]
    fn identical_intended_tree_yields_zero_operations() {
        let scene = scene_with_container();
        let intended = intended_from_live(&scene, &NodeId::from("band"));
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &BTreeSet::new());
        assert!(ops.is_empty(), "expected zero ops, got {:?}", ops);
        assert_eq!(summary(&notes), (0, 0, 0, 0, 0));
    }

    // Test 2 — one field changed on one child → exactly one UpdateNode with
    // exactly that field set.
    #[test]
    fn one_changed_field_yields_one_update_with_only_that_field() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        intended.nodes.get_mut(&NodeId::from("a")).unwrap().opacity = 0.5;
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &BTreeSet::new());
        assert_eq!(ops.len(), 1, "expected one op, got {:?}", ops);
        match &ops[0] {
            Operation::UpdateNode { node_id, patch } => {
                assert_eq!(node_id, &NodeId::from("a"));
                assert_eq!(patch.opacity, FieldPatch::Set(0.5));
                // Every other field is untouched.
                let mut baseline = patch.clone();
                baseline.opacity = FieldPatch::Unchanged;
                assert_eq!(baseline, NodePatch::default());
            }
            other => panic!("expected UpdateNode, got {:?}", other),
        }
        assert_eq!(summary(&notes), (1, 0, 0, 0, 0));
    }

    // Test 3 — new child id → InsertNode at the correct parent + index; order
    // respected.
    #[test]
    fn new_child_yields_insert_at_correct_index() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        // Insert `c` between `a` and `b`.
        intended
            .nodes
            .insert(NodeId::from("c"), text("c", "Charlie"));
        intended.container_children = vec![NodeId::from("a"), NodeId::from("c"), NodeId::from("b")];
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &BTreeSet::new());
        // `b` moves from index 1 to index 2; `c` inserts at index 1.
        let insert = ops
            .iter()
            .find_map(|op| match op {
                Operation::InsertNode {
                    parent,
                    index,
                    node,
                } if node.id == NodeId::from("c") => Some((parent.clone(), *index)),
                _ => None,
            })
            .expect("insert of c present");
        assert_eq!(insert, (ParentRef::Node(NodeId::from("band")), 1));
        let (updated, inserted, removed, _moved, kept) = summary(&notes);
        assert_eq!((updated, inserted, removed, kept), (0, 1, 0, 0));
    }

    // Test 4 — agent-born child omitted → RemoveNode.
    #[test]
    fn omitted_agent_born_child_yields_remove() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        intended.nodes.remove(&NodeId::from("b"));
        intended.container_children = vec![NodeId::from("a")];
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &BTreeSet::new());
        assert_eq!(
            ops,
            vec![Operation::RemoveNode {
                node_id: NodeId::from("b")
            }]
        );
        assert_eq!(summary(&notes), (0, 0, 1, 0, 0));
    }

    // Test 5 — protected child omitted → NO RemoveNode + a ProtectedKept note
    // (maps to LUMD0262).
    #[test]
    fn omitted_protected_child_is_kept_with_note() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        intended.nodes.remove(&NodeId::from("b"));
        intended.container_children = vec![NodeId::from("a")];
        let mut protected = BTreeSet::new();
        protected.insert(NodeId::from("b"));
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &protected);
        assert!(
            !ops.iter()
                .any(|op| matches!(op, Operation::RemoveNode { node_id } if node_id == &NodeId::from("b"))),
            "protected node must not be removed: {:?}",
            ops
        );
        assert!(notes
            .iter()
            .any(|note| note == &ReconcileNote::ProtectedKept(NodeId::from("b"))));
        assert_eq!(summary(&notes), (0, 0, 0, 0, 1));
    }

    // Test 6 — reorder without content change → MoveNode(s) only.
    #[test]
    fn reorder_without_content_change_yields_moves_only() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        // Swap the order of `a` and `b`.
        intended.container_children = vec![NodeId::from("b"), NodeId::from("a")];
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &BTreeSet::new());
        assert!(
            ops.iter().all(|op| matches!(op, Operation::MoveNode { .. })),
            "expected only moves, got {:?}",
            ops
        );
        assert!(!ops.is_empty(), "reorder should produce at least one move");
        let (updated, inserted, removed, moved, kept) = summary(&notes);
        assert_eq!((updated, inserted, removed, kept), (0, 0, 0, 0));
        assert!(moved >= 1);
    }

    // Test 7 — protected child INCLUDED with a change → ordinary UpdateNode
    // (the model re-authored it explicitly).
    #[test]
    fn included_protected_child_with_change_yields_ordinary_update() {
        let scene = scene_with_container();
        let mut intended = intended_from_live(&scene, &NodeId::from("band"));
        if let NodeKind::Text(text) = &mut intended.nodes.get_mut(&NodeId::from("b")).unwrap().kind {
            text.content = "Bravo edited".to_owned();
        }
        let mut protected = BTreeSet::new();
        protected.insert(NodeId::from("b"));
        let (ops, notes) =
            reconcile_subtree(&scene, &NodeId::from("band"), &intended, &protected);
        assert_eq!(ops.len(), 1, "expected one update, got {:?}", ops);
        match &ops[0] {
            Operation::UpdateNode { node_id, patch } => {
                assert_eq!(node_id, &NodeId::from("b"));
                assert!(matches!(patch.kind, FieldPatch::Set(NodeKind::Text(_))));
            }
            other => panic!("expected UpdateNode, got {:?}", other),
        }
        // Included + changed = update, NOT kept-protected.
        assert!(!notes
            .iter()
            .any(|note| matches!(note, ReconcileNote::ProtectedKept(_))));
        assert_eq!(summary(&notes), (1, 0, 0, 0, 0));
    }
}
