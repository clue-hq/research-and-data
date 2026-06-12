//! Phase G instance derivation (slices G2-G4, G6).
//!
//! An instance is a DERIVED ARTIFACT: a pure function of
//! `(revision snapshot, binding set, asset records)`. Derivation never
//! replays operation logs and instances are never manually edited in V0 —
//! repairs happen on the template (a new draft revision) or on binding
//! values, both of which re-derive.
//!
//! Determinism is a tested property: the same inputs produce byte-identical
//! derived scene JSON. Everything here iterates `BTreeMap`s, consumes no
//! clocks, and records audit entries in slot order.

use crate::assets::AssetRecord;
use crate::binding::{validate_binding_set, BindingSet, BoundValue, ConditionalExpr};
use crate::diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use crate::editing::CloneLineage;
use crate::ids::{AssetId, NodeId, SlotKey};
use crate::layout::{layout_scene, LayoutOptions};
use crate::operations::{FieldPatch, NodePatch, Operation, OptionalFieldPatch};
use crate::scene::{DocumentStatus, NodeKind, Scene};
use crate::slots::{EmptyBehavior, ImagePolicy, OverflowPolicy, Slot};
use crate::text_measure::SharedTextMeasurer;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

/// Options for one derivation run. The measurer is injected exactly like
/// `LayoutOptions::measurer` (Wave 1 Track A Decision 5): `None` falls back
/// to the heuristic, the server injects Skia so fit verdicts are
/// shaping-true.
#[derive(Clone, Default)]
pub struct DeriveOptions {
    pub measurer: Option<SharedTextMeasurer>,
}

impl std::fmt::Debug for DeriveOptions {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DeriveOptions")
            .field("has_measurer", &self.measurer.is_some())
            .finish()
    }
}

/// Asset records available to a derivation: uploaded/library records for
/// `BoundValue::Asset` bindings plus pre-executed generated artifacts keyed
/// by their `generated.{name}` entry. Records only — bytes never enter the
/// scene; resolution happens at export through the asset store.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct DerivationAssets {
    #[serde(default)]
    pub records: BTreeMap<AssetId, AssetRecord>,
    #[serde(default)]
    pub generated: BTreeMap<String, AssetRecord>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstanceAuditKind {
    TextApplied,
    AssetPlaced,
    GeneratedAssetBound,
    ConditionalHidden,
    ConditionalFallback,
    ConditionalPreserved,
    ConditionalSatisfied,
    ValueIgnored,
    RepeaterExpanded,
    OverflowPolicyApplied,
    RepairRequested,
}

/// One audited derivation action. Entries are deterministic (slot order)
/// and carry enough context to answer "why does this instance look like
/// this" without replaying anything. Repeater expansions record the Phase D
/// clone lineage so clone ancestry never needs archaeology.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InstanceAuditEntry {
    pub kind: InstanceAuditKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_key: Option<SlotKey>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub node_ids: Vec<NodeId>,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lineage: Option<CloneLineage>,
}

impl InstanceAuditEntry {
    fn new(
        kind: InstanceAuditKind,
        slot_key: Option<SlotKey>,
        node_ids: Vec<NodeId>,
        message: String,
    ) -> Self {
        Self {
            kind,
            slot_key,
            node_ids,
            message,
            lineage: None,
        }
    }
}

/// Slot-level fit verdict for one derived instance (slice G6). This is the
/// honest-fit promise: every overflow surfaces here — nothing renders
/// silently broken.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SlotFitVerdict {
    /// Content fits the bound geometry as-is.
    Fits,
    /// Content fits after the slot's declared overflow policy executed
    /// (e.g. ShrinkFont applied a smaller size).
    FitsWithPolicy {
        policy: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        adjusted_font_size: Option<f64>,
    },
    /// Content overflows; `policy` names the declared response that was
    /// executed or exhausted.
    Overflow { policy: String, reason: String },
    /// The slot's region was hidden by a conditional or empty repeater.
    Hidden,
}

impl SlotFitVerdict {
    fn rank(&self) -> u8 {
        match self {
            Self::Fits | Self::Hidden => 0,
            Self::FitsWithPolicy { .. } => 1,
            Self::Overflow { .. } => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstanceFitStatus {
    Fits,
    FitsWithPolicy,
    Overflow,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SlotFitEntry {
    pub slot_key: SlotKey,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub node_id: Option<NodeId>,
    pub verdict: SlotFitVerdict,
    /// Diagnostic codes attached to this slot's fit evaluation.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub diagnostics: Vec<String>,
    /// True when the bound content exceeds the template's declared
    /// worst-case fixture — the instance carries content the template was
    /// never validated against.
    #[serde(default)]
    pub beyond_worst_case: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct InstanceFitReport {
    pub binding_set_id: String,
    pub status: InstanceFitStatus,
    pub slots: Vec<SlotFitEntry>,
}

impl InstanceFitReport {
    pub fn overflow_slots(&self) -> Vec<&SlotFitEntry> {
        self.slots
            .iter()
            .filter(|entry| matches!(entry.verdict, SlotFitVerdict::Overflow { .. }))
            .collect()
    }
}

/// A template-level repair request produced by `AskAgentToRepair`. Never an
/// instance mutation: the repair queue points agents at the template (a new
/// draft revision) or the binding values.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct TemplateRepairRequest {
    pub template_revision_id: crate::ids::TemplateRevisionId,
    pub slot_key: SlotKey,
    pub node_id: NodeId,
    pub binding_set_id: String,
    pub reason: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DerivedInstance {
    pub scene: Scene,
    pub diagnostics: Vec<Diagnostic>,
    pub audit: Vec<InstanceAuditEntry>,
    pub fit_report: InstanceFitReport,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub repair_requests: Vec<TemplateRepairRequest>,
}

impl DerivedInstance {
    pub fn has_errors(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    }
}

/// Derive an instance scene from a finalized revision snapshot, a binding
/// set, and the asset records the binding references.
///
/// The derived scene keeps the snapshot's finalized status (provenance);
/// mutation happens on a draft working copy through canonical operations so
/// derivation shares the exact semantics of the editing surface.
pub fn derive_instance(
    snapshot: &Scene,
    binding: &BindingSet,
    assets: &DerivationAssets,
    options: &DeriveOptions,
) -> DerivedInstance {
    let mut diagnostics = validate_binding_set(snapshot, binding);
    if has_errors(&diagnostics) {
        return DerivedInstance {
            scene: snapshot.clone(),
            diagnostics,
            audit: Vec::new(),
            fit_report: InstanceFitReport {
                binding_set_id: binding.binding_set_id.clone(),
                status: InstanceFitStatus::Overflow,
                slots: Vec::new(),
            },
            repair_requests: Vec::new(),
        };
    }

    let mut scene = snapshot.clone();
    let finalized_status = scene.meta.status.clone();
    // Canonical operations refuse to mutate finalized scenes; derivation
    // works on a draft copy and restores the finalized status afterwards so
    // the derived artifact keeps its revision provenance.
    scene.meta.status = DocumentStatus::Draft;

    let mut audit = Vec::new();
    let mut repair_requests = Vec::new();

    let suppressed = execute_conditionals(&mut scene, binding, &mut diagnostics, &mut audit);
    apply_scalar_values(
        &mut scene,
        binding,
        assets,
        &suppressed,
        &mut diagnostics,
        &mut audit,
    );
    bind_generated_assets(&mut scene, binding, assets, &mut diagnostics, &mut audit);

    // Pass 1: geometry for policy execution. Text-fit diagnostics are
    // withheld here — overflow policies have not executed yet, so pass-1
    // overflow signals would be false alarms.
    relayout_filtered(&mut scene, options, &mut diagnostics);

    // Execute declared overflow policies (Decision 5): ShrinkFont mutates
    // bounded by min/max under the injected measurer; AskAgentToRepair
    // queues template-level repairs.
    let applications = execute_overflow_policies(
        &mut scene,
        binding,
        options,
        &mut diagnostics,
        &mut audit,
        &mut repair_requests,
    );

    // Pass 2 (final): geometry plus full text-fit diagnostics, with
    // severity downgraded for sanctioned-content-loss policies.
    relayout_final(&mut scene, options, &mut diagnostics);

    let fit_report = build_fit_report(snapshot, &scene, binding, options, &applications);

    scene.meta.status = finalized_status;

    DerivedInstance {
        scene,
        diagnostics,
        audit,
        fit_report,
        repair_requests,
    }
}

/// Execute every conditional rule (slice G3). Returns the slot keys whose
/// values are suppressed because their condition evaluated false — the
/// `when_false` behavior owns those slots, not value application.
fn execute_conditionals(
    scene: &mut Scene,
    binding: &BindingSet,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) -> BTreeSet<SlotKey> {
    let mut suppressed = BTreeSet::new();

    for slot in slots_in_order(scene) {
        let Some(rule) = &slot.conditional else {
            continue;
        };
        // validate_binding_set already rejected unparseable expressions;
        // a parse failure here would be a validation gap, so skip safely.
        let Ok(expression) = ConditionalExpr::parse(&rule.expression) else {
            continue;
        };

        if expression.evaluate(binding) {
            audit.push(InstanceAuditEntry {
                kind: InstanceAuditKind::ConditionalSatisfied,
                slot_key: Some(slot.key.clone()),
                node_ids: Vec::new(),
                message: format!(
                    "conditional {} on slot {} evaluated true",
                    rule.expression, slot.key
                ),
                lineage: None,
            });
            continue;
        }

        suppressed.insert(slot.key.clone());
        if binding.values.contains_key(slot.key.as_str()) {
            audit.push(InstanceAuditEntry {
                kind: InstanceAuditKind::ValueIgnored,
                slot_key: Some(slot.key.clone()),
                node_ids: Vec::new(),
                message: format!(
                    "bound value for slot {} ignored: conditional {} evaluated false",
                    slot.key, rule.expression
                ),
                lineage: None,
            });
        }

        match rule.when_false {
            EmptyBehavior::HideRegion => {
                hide_region(scene, &slot, &rule.expression, diagnostics, audit);
            }
            EmptyBehavior::PreservePlaceholder => {
                audit.push(InstanceAuditEntry {
                    kind: InstanceAuditKind::ConditionalPreserved,
                    slot_key: Some(slot.key.clone()),
                    node_ids: slot.bound_nodes.clone(),
                    message: format!(
                        "slot {} keeps its placeholder content: {} evaluated false",
                        slot.key, rule.expression
                    ),
                    lineage: None,
                });
            }
            EmptyBehavior::UseFallback => {
                apply_fallback(scene, &slot, &rule.expression, diagnostics, audit);
            }
            EmptyBehavior::ValidationError => {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0311",
                    format!(
                        "conditional slot {} evaluated false with validation_error behavior ({})",
                        slot.key, rule.expression
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }
    }

    suppressed
}

/// HideRegion removes the bound subtree pre-layout (canonical RemoveNode,
/// which clears dangling slot bindings) and drops the slot record so the
/// derived scene stays structurally valid.
fn hide_region(
    scene: &mut Scene,
    slot: &Slot,
    expression: &str,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    let mut removed = Vec::new();
    for node_id in &slot.bound_nodes {
        if !scene.nodes.contains_key(node_id) {
            continue;
        }
        match scene.apply_operation_checked(Operation::RemoveNode {
            node_id: node_id.clone(),
        }) {
            Ok(report) => {
                diagnostics.extend(report.diagnostics);
                removed.push(node_id.clone());
            }
            Err(error) => diagnostics.push(operation_failure(
                &slot.key,
                Some(node_id),
                "hide region",
                error.code,
                &error.message,
            )),
        }
    }
    match scene.apply_operation_checked(Operation::RemoveSlot {
        slot_id: slot.id.clone(),
    }) {
        Ok(report) => diagnostics.extend(report.diagnostics),
        Err(error) => diagnostics.push(operation_failure(
            &slot.key,
            None,
            "hide region slot removal",
            error.code,
            &error.message,
        )),
    }
    audit.push(InstanceAuditEntry {
        kind: InstanceAuditKind::ConditionalHidden,
        slot_key: Some(slot.key.clone()),
        node_ids: removed,
        message: format!(
            "region for slot {} hidden: {expression} evaluated false",
            slot.key
        ),
        lineage: None,
    });
}

/// UseFallback substitutes the slot placeholder into bound text nodes.
fn apply_fallback(
    scene: &mut Scene,
    slot: &Slot,
    expression: &str,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    let Some(placeholder) = slot.placeholder.clone().filter(|text| !text.is_empty()) else {
        diagnostics.push(Diagnostic::warning(
            Phase::Validation,
            "LUMG0310",
            format!(
                "slot {} uses fallback behavior but has no placeholder content; nodes left unchanged",
                slot.key
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
        return;
    };
    apply_text_to_slot(scene, slot, &placeholder, diagnostics, audit);
    audit.push(InstanceAuditEntry {
        kind: InstanceAuditKind::ConditionalFallback,
        slot_key: Some(slot.key.clone()),
        node_ids: slot.bound_nodes.clone(),
        message: format!(
            "slot {} fell back to placeholder content: {expression} evaluated false",
            slot.key
        ),
        lineage: None,
    });
}

fn apply_scalar_values(
    scene: &mut Scene,
    binding: &BindingSet,
    assets: &DerivationAssets,
    suppressed: &BTreeSet<SlotKey>,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    for slot in slots_in_order(scene) {
        if suppressed.contains(&slot.key) {
            continue;
        }
        let Some(value) = binding.values.get(slot.key.as_str()) else {
            continue;
        };

        match value {
            BoundValue::Text { value: text } => {
                apply_text_to_slot(scene, &slot, text, diagnostics, audit);
            }
            BoundValue::Asset { asset_id } => {
                place_asset_in_slot(scene, &slot, asset_id, assets, diagnostics, audit);
            }
            BoundValue::List { items } => {
                expand_repeater(scene, &slot, items, diagnostics, audit);
            }
        }
    }
}

/// Expand a repeater group (slice G4): the template subtree is cloned per
/// item through Phase D clone machinery with deterministic per-item ids
/// (`{template}_item_{n}`), per-item slots via the `_item_{n}` suffix
/// policy, and `CloneLineage` recorded in the audit trail. Reflow happens
/// through the derivation relayout (`Stack`/`Wrap` ride the template's
/// auto-layout parent).
fn expand_repeater(
    scene: &mut Scene,
    slot: &Slot,
    items: &[BoundValue],
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    let Some(repeater) = slot.repeater.clone() else {
        diagnostics.push(Diagnostic::warning(
            Phase::Validation,
            "LUMG0312",
            format!(
                "slot {} received a list value but declares no repeater rule; items not applied",
                slot.key
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
        return;
    };

    let template_node_id = repeater.template_node_id.clone();
    if !scene.nodes.contains_key(&template_node_id) {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0313",
            format!(
                "repeater slot {} references missing template node {}",
                slot.key, template_node_id
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
        return;
    }

    if scene.slot_by_key(&repeater.item_slot_key).is_none() {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0314",
            format!(
                "repeater slot {} references missing item slot key {}",
                slot.key, repeater.item_slot_key
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
        return;
    }

    check_reflow_container(scene, slot, &repeater, diagnostics);

    // Empty list: the template subtree is the zero-th item; remove it so
    // the instance shows no items (cardinality validation already gated
    // min_items).
    if items.is_empty() {
        hide_repeater_template(scene, slot, &repeater, diagnostics, audit);
        return;
    }

    // Items 1..n clone the template subtree, anchored after the previous
    // item, with per-item slot suffixes.
    let mut clone_roots: Vec<NodeId> = Vec::new();
    let mut lineages: Vec<CloneLineage> = Vec::new();
    for index in 1..items.len() {
        let new_root_id = NodeId::from(format!("{template_node_id}_item_{index}"));
        let anchor = clone_roots
            .last()
            .cloned()
            .unwrap_or_else(|| template_node_id.clone());
        let request = crate::editing::CloneSubtreeRequest {
            source: template_node_id.clone(),
            new_root_id: new_root_id.clone(),
            placement: crate::editing::RelativePlacement::After { anchor },
            slot_policy: crate::editing::CloneSlotPolicy::Suffix(format!("_item_{index}")),
            computed_policy: crate::editing::ComputedClonePolicy::Clear,
        };
        match crate::editing::build_clone_subtree(scene, request) {
            Ok(batch) => {
                let lineage = batch.lineage.clone();
                match batch.apply_checked(scene) {
                    Ok(report) => {
                        diagnostics.extend(report.diagnostics);
                        clone_roots.push(new_root_id);
                        if let Some(lineage) = lineage {
                            lineages.push(lineage);
                        }
                    }
                    Err(error) => diagnostics.push(operation_failure(
                        &slot.key,
                        Some(&new_root_id),
                        "repeater clone",
                        error.kind.code(),
                        &error.message,
                    )),
                }
            }
            Err(error) => diagnostics.push(operation_failure(
                &slot.key,
                Some(&new_root_id),
                "repeater clone",
                error.kind.code(),
                &error.message,
            )),
        }
    }

    // Bind item content: item 0 through the template's item slot, item n
    // through the suffixed clone slot.
    for (index, item) in items.iter().enumerate() {
        let BoundValue::Text { value: text } = item else {
            // validate_binding_set already rejected non-text items.
            continue;
        };
        let item_key = if index == 0 {
            repeater.item_slot_key.clone()
        } else {
            SlotKey::from(format!("{}_item_{index}", repeater.item_slot_key))
        };
        let Some(item_slot) = scene.slot_by_key(&item_key).cloned() else {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0314",
                format!(
                    "repeater slot {} item {index} has no item slot {item_key}",
                    slot.key
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
            continue;
        };
        apply_text_to_slot(scene, &item_slot, text, diagnostics, audit);
    }

    for (offset, lineage) in lineages.iter().enumerate() {
        audit.push(InstanceAuditEntry {
            kind: InstanceAuditKind::RepeaterExpanded,
            slot_key: Some(slot.key.clone()),
            node_ids: vec![lineage.id_map[0].1.clone()],
            message: format!(
                "cloned repeater item {} of slot {} from template {}",
                offset + 1,
                slot.key,
                template_node_id
            ),
            lineage: Some(lineage.clone()),
        });
    }
    audit.push(InstanceAuditEntry::new(
        InstanceAuditKind::RepeaterExpanded,
        Some(slot.key.clone()),
        std::iter::once(template_node_id.clone())
            .chain(clone_roots.iter().cloned())
            .collect(),
        format!(
            "expanded repeater slot {} to {} item(s) with {:?} reflow",
            slot.key,
            items.len(),
            repeater.reflow
        ),
    ));
}

/// Stack/Wrap reflow rides the template's auto-layout parent; warn when
/// the template is not inside one, because clones would overlap instead of
/// reflowing.
fn check_reflow_container(
    scene: &Scene,
    slot: &Slot,
    repeater: &crate::slots::RepeaterRule,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let parent_is_auto_layout = match scene.parent_of(&repeater.template_node_id) {
        Some(crate::scene::ParentRef::Node(parent_id)) => scene
            .nodes
            .get(&parent_id)
            .is_some_and(|parent| matches!(parent.kind, NodeKind::AutoLayout(_))),
        _ => false,
    };
    if !parent_is_auto_layout {
        diagnostics.push(Diagnostic::warning(
            Phase::Layout,
            "LUMG0315",
            format!(
                "repeater slot {} template {} is not inside an auto-layout container; {:?} reflow cannot stack the clones",
                slot.key, repeater.template_node_id, repeater.reflow
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
    }
}

fn hide_repeater_template(
    scene: &mut Scene,
    slot: &Slot,
    repeater: &crate::slots::RepeaterRule,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    // One validated batch: removing only the template node would leave the
    // group slot's repeater rule dangling and fail scene validation.
    let mut operations = vec![Operation::RemoveNode {
        node_id: repeater.template_node_id.clone(),
    }];
    if let Some(item_slot) = scene.slot_by_key(&repeater.item_slot_key) {
        operations.push(Operation::RemoveSlot {
            slot_id: item_slot.id.clone(),
        });
    }
    operations.push(Operation::RemoveSlot {
        slot_id: slot.id.clone(),
    });
    match scene.apply_operations_checked(operations) {
        Ok(report) => diagnostics.extend(report.diagnostics),
        Err(error) => {
            diagnostics.push(operation_failure(
                &slot.key,
                Some(&repeater.template_node_id),
                "empty repeater removal",
                error.code,
                &error.message,
            ));
            return;
        }
    }
    audit.push(InstanceAuditEntry::new(
        InstanceAuditKind::RepeaterExpanded,
        Some(slot.key.clone()),
        vec![repeater.template_node_id.clone()],
        format!(
            "repeater slot {} received zero items; template subtree and repeater slots removed",
            slot.key
        ),
    ));
}

/// Set the bound text nodes' content through the canonical UpdateNode
/// operation so derivation shares operation semantics exactly.
fn apply_text_to_slot(
    scene: &mut Scene,
    slot: &Slot,
    text: &str,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    let mut applied_nodes = Vec::new();
    for node_id in &slot.bound_nodes {
        let Some(node) = scene.nodes.get(node_id) else {
            continue;
        };
        let NodeKind::Text(current) = &node.kind else {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMG0300",
                format!(
                    "slot {} binds non-text node {}; text value not applied there",
                    slot.key, node_id
                ),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
            continue;
        };

        let mut next = current.clone();
        next.content = text.to_owned();
        let operation = Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: NodePatch {
                kind: FieldPatch::Set(NodeKind::Text(next)),
                computed: OptionalFieldPatch::Clear,
                ..NodePatch::default()
            },
        };
        match scene.apply_operation_checked(operation) {
            Ok(report) => {
                diagnostics.extend(report.diagnostics);
                applied_nodes.push(node_id.clone());
            }
            Err(error) => diagnostics.push(operation_failure(
                &slot.key,
                Some(node_id),
                "text application",
                error.code,
                &error.message,
            )),
        }
    }

    if !applied_nodes.is_empty() {
        audit.push(InstanceAuditEntry {
            kind: InstanceAuditKind::TextApplied,
            slot_key: Some(slot.key.clone()),
            node_ids: applied_nodes,
            message: format!(
                "applied {} characters of bound text to slot {}",
                text.chars().count(),
                slot.key
            ),
            lineage: None,
        });
    }
}

/// Upsert the referenced asset record and place it through the canonical
/// PlaceAssetInSlot operation (existing Phase E semantics: fit/focal
/// placement comes from the slot's image policy).
fn place_asset_in_slot(
    scene: &mut Scene,
    slot: &Slot,
    asset_id: &AssetId,
    assets: &DerivationAssets,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    let record = assets
        .records
        .get(asset_id)
        .cloned()
        .or_else(|| scene.assets.get(asset_id).cloned());
    let Some(record) = record else {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0301",
            format!(
                "slot {} binds asset {} but no asset record was supplied",
                slot.key, asset_id
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
        return;
    };

    let operations = vec![
        Operation::UpsertAsset {
            asset: record.clone(),
        },
        Operation::PlaceAssetInSlot {
            slot_id: slot.id.clone(),
            asset_id: asset_id.clone(),
            placement: placement_from_policy(slot, &record),
        },
    ];
    match scene.apply_operations_checked(operations) {
        Ok(report) => {
            diagnostics.extend(report.diagnostics);
            audit.push(InstanceAuditEntry {
                kind: InstanceAuditKind::AssetPlaced,
                slot_key: Some(slot.key.clone()),
                node_ids: slot.bound_nodes.clone(),
                message: format!("placed asset {} into slot {}", asset_id, slot.key),
                lineage: None,
            });
        }
        Err(error) => diagnostics.push(operation_failure(
            &slot.key,
            None,
            "asset placement",
            error.code,
            &error.message,
        )),
    }
}

/// Bind pre-executed generated assets (Phase E provider registry output)
/// to their target slots. The records arrive through
/// [`DerivationAssets::generated`]; executing providers is the adapter
/// side's job (the helper), never core's.
fn bind_generated_assets(
    scene: &mut Scene,
    binding: &BindingSet,
    assets: &DerivationAssets,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    for (name, spec) in &binding.generated {
        let Some(slot) = scene.slot_by_key(&spec.bind_to_slot).cloned() else {
            // validate_binding_set already rejected unknown slots.
            continue;
        };
        let Some(record) = assets.generated.get(name).cloned() else {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0302",
                format!(
                    "generated entry {name:?} has no executed asset record; derivation requires provider output for every generated entry"
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
            continue;
        };

        let asset_id = record.id.clone();
        let operations = vec![
            Operation::UpsertAsset {
                asset: record.clone(),
            },
            Operation::PlaceAssetInSlot {
                slot_id: slot.id.clone(),
                asset_id: asset_id.clone(),
                placement: placement_from_policy(&slot, &record),
            },
        ];
        match scene.apply_operations_checked(operations) {
            Ok(report) => {
                diagnostics.extend(report.diagnostics);
                audit.push(InstanceAuditEntry {
                    kind: InstanceAuditKind::GeneratedAssetBound,
                    slot_key: Some(slot.key.clone()),
                    node_ids: slot.bound_nodes.clone(),
                    message: format!(
                        "bound generated asset {} (entry {name:?}, provider {}) to slot {}",
                        asset_id, spec.provider, slot.key
                    ),
                    lineage: None,
                });
            }
            Err(error) => diagnostics.push(operation_failure(
                &slot.key,
                None,
                "generated asset binding",
                error.code,
                &error.message,
            )),
        }
    }
}

fn placement_from_policy(slot: &Slot, record: &AssetRecord) -> crate::assets::AssetPlacement {
    let policy: Option<&ImagePolicy> = slot.image_policy.as_ref();
    crate::assets::AssetPlacement {
        fit: policy.map(|policy| policy.fit.clone()),
        focal_point: policy.and_then(|policy| policy.focal_point.clone()),
        preserve_transparency: policy.map(|policy| policy.preserve_transparency),
        alt_text: Some(record.label.clone()),
    }
}

/// Rerun layout over the derived scene and apply the computed geometry.
/// Slot fixture validation stays OFF here: fit verdicts for an instance
/// judge the actual bound content (the layout text checks), not the
/// template's authoring fixtures.
const TEXT_FIT_CODES: [&str; 3] = ["LUMV0902", "LUMV0903", "LUMV0904"];

/// Geometry pass without text-fit verdicts (pre-policy execution).
fn relayout_filtered(
    scene: &mut Scene,
    options: &DeriveOptions,
    diagnostics: &mut Vec<Diagnostic>,
) {
    run_layout(scene, options, diagnostics, |diagnostic| {
        !TEXT_FIT_CODES.contains(&diagnostic.code.as_str())
    });
}

/// Final geometry pass: text-fit verdicts included, with severity
/// downgraded to warning for nodes whose slot policy sanctions content
/// loss (Clip/Ellipsis) or defers to the repair queue (AskAgentToRepair) —
/// surfaced loudly in the fit report, but not instance-fatal.
fn relayout_final(scene: &mut Scene, options: &DeriveOptions, diagnostics: &mut Vec<Diagnostic>) {
    let mut staged = Vec::new();
    run_layout(scene, options, &mut staged, |_| true);
    for mut diagnostic in staged {
        if TEXT_FIT_CODES.contains(&diagnostic.code.as_str()) {
            if let Some(DiagnosticSubject::Node(node_id)) = &diagnostic.subject {
                if let Some(policy) = slot_policy_for_node(scene, node_id) {
                    if matches!(
                        policy,
                        OverflowPolicy::Clip
                            | OverflowPolicy::Ellipsis
                            | OverflowPolicy::AskAgentToRepair
                    ) {
                        diagnostic.severity = DiagnosticSeverity::Warning;
                    }
                }
            }
        }
        if !diagnostics.contains(&diagnostic) {
            diagnostics.push(diagnostic);
        }
    }
}

fn run_layout(
    scene: &mut Scene,
    options: &DeriveOptions,
    diagnostics: &mut Vec<Diagnostic>,
    keep: impl Fn(&Diagnostic) -> bool,
) {
    let layout = layout_scene(
        scene,
        LayoutOptions {
            validate_slots: false,
            measurer: options.measurer.as_ref().map(Arc::clone),
        },
    );
    for diagnostic in layout.diagnostics {
        if keep(&diagnostic) && !diagnostics.contains(&diagnostic) {
            diagnostics.push(diagnostic);
        }
    }
    let operations: Vec<Operation> = layout
        .geometry
        .into_iter()
        .map(|(node_id, computed)| Operation::UpdateNode {
            node_id,
            patch: NodePatch {
                computed: OptionalFieldPatch::Set(computed),
                ..NodePatch::default()
            },
        })
        .collect();
    if let Err(error) = scene.apply_operations_checked(operations) {
        diagnostics.push(Diagnostic::error(
            Phase::Layout,
            "LUMG0303",
            format!(
                "failed to apply derived layout geometry: {} {}",
                error.code, error.message
            ),
            Some(DiagnosticSubject::Document),
        ));
    }
}

fn slot_policy_for_node(scene: &Scene, node_id: &NodeId) -> Option<OverflowPolicy> {
    scene
        .slots
        .values()
        .find(|slot| slot.bound_nodes.contains(node_id))
        .map(|slot| slot.overflow.clone())
}

/// Whether a slot's content type carries text fit semantics.
fn is_text_slot(slot: &Slot) -> bool {
    matches!(
        slot.content_type,
        crate::slots::ContentType::TextShort
            | crate::slots::ContentType::TextLong
            | crate::slots::ContentType::RichTextLimited
            | crate::slots::ContentType::NumberStat
            | crate::slots::ContentType::Date
    )
}

#[derive(Clone, Debug)]
struct PolicyApplication {
    policy: String,
    adjusted_font_size: Option<f64>,
    exhausted: bool,
}

/// Measure one text node's actual content against its computed bounds.
fn node_fits(scene: &Scene, node_id: &NodeId, options: &DeriveOptions) -> Option<bool> {
    let node = scene.nodes.get(node_id)?;
    let NodeKind::Text(text) = &node.kind else {
        return None;
    };
    let bounds = node.computed.as_ref()?.layout_bounds.clone();
    let measurer: &dyn crate::text_measure::TextMeasurer = options
        .measurer
        .as_deref()
        .map(|measurer| measurer as &dyn crate::text_measure::TextMeasurer)
        .unwrap_or(&crate::text_measure::HeuristicTextMeasurer);
    let measured = measurer
        .measure(&crate::text_measure::TextMeasureInput::from_text_node(text).with_bounds(&bounds));
    let overflow_x = measured.overflow_x && matches!(text.wrap, crate::scene::TextWrap::NoWrap);
    Some(!overflow_x && !measured.overflow_y && !measured.exceeds_max_lines)
}

/// Execute the declared overflow policy for every text slot whose bound
/// content overflows after pass-1 layout. Only ShrinkFont mutates; all
/// other policies resolve at verdict time. Returns the applications for
/// the fit report.
fn execute_overflow_policies(
    scene: &mut Scene,
    binding: &BindingSet,
    options: &DeriveOptions,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
    repair_requests: &mut Vec<TemplateRepairRequest>,
) -> BTreeMap<SlotKey, PolicyApplication> {
    let mut applications = BTreeMap::new();
    let mut mutated = false;

    for slot in slots_in_order(scene) {
        if !is_text_slot(&slot) {
            continue;
        }
        for node_id in &slot.bound_nodes {
            let Some(fits) = node_fits(scene, node_id, options) else {
                continue;
            };
            if fits {
                continue;
            }

            match &slot.overflow {
                OverflowPolicy::ShrinkFont {
                    min_font_size,
                    max_font_size,
                } => {
                    let Some(node) = scene.nodes.get(node_id) else {
                        continue;
                    };
                    let NodeKind::Text(current) = &node.kind else {
                        continue;
                    };
                    let start = max_font_size
                        .map(|max| current.font_size.min(max))
                        .unwrap_or(current.font_size);
                    let outcome = shrink_to_fit(
                        scene,
                        node_id,
                        &slot,
                        start,
                        *min_font_size,
                        options,
                        diagnostics,
                        audit,
                    );
                    mutated = true;
                    applications.insert(slot.key.clone(), outcome);
                }
                OverflowPolicy::AskAgentToRepair => {
                    let reason = format!(
                        "slot {} content overflows node {}; template repair requested",
                        slot.key, node_id
                    );
                    diagnostics.push(Diagnostic::warning(
                        Phase::Layout,
                        "LUMG0325",
                        reason.clone(),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                    repair_requests.push(TemplateRepairRequest {
                        template_revision_id: binding.template_revision_id.clone(),
                        slot_key: slot.key.clone(),
                        node_id: node_id.clone(),
                        binding_set_id: binding.binding_set_id.clone(),
                        reason: reason.clone(),
                    });
                    audit.push(InstanceAuditEntry::new(
                        InstanceAuditKind::RepairRequested,
                        Some(slot.key.clone()),
                        vec![node_id.clone()],
                        reason,
                    ));
                }
                // Error / Wrap / Clip / Ellipsis / ExpandContainer resolve
                // at verdict time against final geometry.
                _ => {}
            }
        }
    }

    if mutated {
        relayout_filtered(scene, options, diagnostics);
    }

    applications
}

/// Deterministically step the font size down by 0.5 from `start` to
/// `min_font_size` until the content fits the node's pass-1 bounds.
/// Candidates are measured without mutating the scene; the fitting size is
/// applied once. Exhaustion applies the minimum (least-bad artifact) and
/// reports LUMG0321.
#[allow(clippy::too_many_arguments)]
fn shrink_to_fit(
    scene: &mut Scene,
    node_id: &NodeId,
    slot: &Slot,
    start: f64,
    min_font_size: f64,
    options: &DeriveOptions,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) -> PolicyApplication {
    let (text, bounds) = {
        let node = scene.nodes.get(node_id).expect("caller checked the node");
        let NodeKind::Text(text) = &node.kind else {
            unreachable!("caller checked the node is text");
        };
        (
            text.clone(),
            node.computed
                .as_ref()
                .expect("pass-1 layout left geometry")
                .layout_bounds
                .clone(),
        )
    };
    let measurer: &dyn crate::text_measure::TextMeasurer = options
        .measurer
        .as_deref()
        .map(|measurer| measurer as &dyn crate::text_measure::TextMeasurer)
        .unwrap_or(&crate::text_measure::HeuristicTextMeasurer);
    let candidate_fits = |font_size: f64| {
        let mut input =
            crate::text_measure::TextMeasureInput::from_text_node(&text).with_bounds(&bounds);
        input.font_size = font_size;
        let measured = measurer.measure(&input);
        let overflow_x = measured.overflow_x && matches!(text.wrap, crate::scene::TextWrap::NoWrap);
        !overflow_x && !measured.overflow_y && !measured.exceeds_max_lines
    };

    let mut candidate = start;
    loop {
        candidate = (candidate - 0.5).max(min_font_size);
        if candidate_fits(candidate) {
            apply_font_size(scene, node_id, candidate, diagnostics);
            audit.push(InstanceAuditEntry::new(
                InstanceAuditKind::OverflowPolicyApplied,
                Some(slot.key.clone()),
                vec![node_id.clone()],
                format!(
                    "shrink_font fit slot {} at {candidate} (policy min {min_font_size})",
                    slot.key
                ),
            ));
            return PolicyApplication {
                policy: "shrink_font".to_owned(),
                adjusted_font_size: Some(candidate),
                exhausted: false,
            };
        }
        if candidate <= min_font_size {
            apply_font_size(scene, node_id, min_font_size, diagnostics);
            diagnostics.push(Diagnostic::error(
                Phase::Layout,
                "LUMG0321",
                format!(
                    "slot {} content does not fit node {} even at min font size {min_font_size}",
                    slot.key, node_id
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
            audit.push(InstanceAuditEntry::new(
                InstanceAuditKind::OverflowPolicyApplied,
                Some(slot.key.clone()),
                vec![node_id.clone()],
                format!(
                    "shrink_font exhausted on slot {}: applied min font size {min_font_size}, content still overflows",
                    slot.key
                ),
            ));
            return PolicyApplication {
                policy: "shrink_font".to_owned(),
                adjusted_font_size: Some(min_font_size),
                exhausted: true,
            };
        }
    }
}

fn apply_font_size(
    scene: &mut Scene,
    node_id: &NodeId,
    font_size: f64,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    let NodeKind::Text(current) = &node.kind else {
        return;
    };
    let mut next = current.clone();
    next.font_size = font_size;
    let operation = Operation::UpdateNode {
        node_id: node_id.clone(),
        patch: NodePatch {
            kind: FieldPatch::Set(NodeKind::Text(next)),
            computed: OptionalFieldPatch::Clear,
            ..NodePatch::default()
        },
    };
    if let Err(error) = scene.apply_operation_checked(operation) {
        diagnostics.push(Diagnostic::error(
            Phase::Operation,
            "LUMG0304",
            format!(
                "font shrink for node {node_id} failed: {} {}",
                error.code, error.message
            ),
            Some(DiagnosticSubject::Node(node_id.clone())),
        ));
    }
}

/// Build the per-slot fit report from final geometry. Every slot on the
/// derived scene gets an entry; slots removed during derivation (hidden
/// regions, empty repeaters) report `Hidden`.
fn build_fit_report(
    snapshot: &Scene,
    scene: &Scene,
    binding: &BindingSet,
    options: &DeriveOptions,
    applications: &BTreeMap<SlotKey, PolicyApplication>,
) -> InstanceFitReport {
    let mut entries = Vec::new();

    for slot in slots_in_order(scene) {
        if !is_text_slot(&slot) {
            entries.push(SlotFitEntry {
                slot_key: slot.key.clone(),
                node_id: slot.bound_nodes.first().cloned(),
                verdict: SlotFitVerdict::Fits,
                diagnostics: Vec::new(),
                beyond_worst_case: false,
            });
            continue;
        }

        for node_id in &slot.bound_nodes {
            let Some(fits) = node_fits(scene, node_id, options) else {
                continue;
            };
            let application = applications.get(&slot.key);
            let policy_name = overflow_policy_name(&slot.overflow);
            let (verdict, codes) = if fits {
                match application {
                    Some(application) if !application.exhausted => (
                        SlotFitVerdict::FitsWithPolicy {
                            policy: application.policy.clone(),
                            adjusted_font_size: application.adjusted_font_size,
                        },
                        Vec::new(),
                    ),
                    _ => (SlotFitVerdict::Fits, Vec::new()),
                }
            } else {
                let (reason, codes) = match &slot.overflow {
                    OverflowPolicy::ShrinkFont { min_font_size, .. } => (
                        format!("content does not fit even at min font size {min_font_size}"),
                        vec!["LUMG0321".to_owned()],
                    ),
                    OverflowPolicy::Wrap { max_lines } => (
                        format!("content exceeds the wrap envelope (max_lines {max_lines:?})"),
                        vec!["LUMV0904".to_owned()],
                    ),
                    OverflowPolicy::Clip | OverflowPolicy::Ellipsis => (
                        "content overflows; policy clips it (sanctioned content loss)".to_owned(),
                        vec!["LUMG0322".to_owned()],
                    ),
                    OverflowPolicy::ExpandContainer => (
                        "content requires container expansion, which V0 does not execute"
                            .to_owned(),
                        vec!["LUMG0323".to_owned()],
                    ),
                    OverflowPolicy::Error => (
                        "content overflows and the slot policy is error".to_owned(),
                        vec!["LUMG0320".to_owned()],
                    ),
                    OverflowPolicy::AskAgentToRepair => (
                        "content overflows; template repair requested".to_owned(),
                        vec!["LUMG0325".to_owned()],
                    ),
                };
                (
                    SlotFitVerdict::Overflow {
                        policy: policy_name.clone(),
                        reason,
                    },
                    codes,
                )
            };

            entries.push(SlotFitEntry {
                slot_key: slot.key.clone(),
                node_id: Some(node_id.clone()),
                verdict,
                diagnostics: codes,
                beyond_worst_case: beyond_worst_case(scene, &slot, node_id),
            });
        }
    }

    // Slots present on the snapshot but absent from the derived scene were
    // hidden (conditional HideRegion, empty repeaters, suffix-free clones).
    for slot in snapshot.slots.values() {
        if scene.slot_by_key(&slot.key).is_none() {
            entries.push(SlotFitEntry {
                slot_key: slot.key.clone(),
                node_id: None,
                verdict: SlotFitVerdict::Hidden,
                diagnostics: Vec::new(),
                beyond_worst_case: false,
            });
        }
    }

    let status = match entries.iter().map(|entry| entry.verdict.rank()).max() {
        Some(2) => InstanceFitStatus::Overflow,
        Some(1) => InstanceFitStatus::FitsWithPolicy,
        _ => InstanceFitStatus::Fits,
    };

    InstanceFitReport {
        binding_set_id: binding.binding_set_id.clone(),
        status,
        slots: entries,
    }
}

fn overflow_policy_name(policy: &OverflowPolicy) -> String {
    match policy {
        OverflowPolicy::ShrinkFont { .. } => "shrink_font",
        OverflowPolicy::Wrap { .. } => "wrap",
        OverflowPolicy::Clip => "clip",
        OverflowPolicy::Ellipsis => "ellipsis",
        OverflowPolicy::ExpandContainer => "expand_container",
        OverflowPolicy::Error => "error",
        OverflowPolicy::AskAgentToRepair => "ask_agent_to_repair",
    }
    .to_owned()
}

/// Content beyond the template's declared worst-case fixture means the
/// instance carries text the template was never validated against.
fn beyond_worst_case(scene: &Scene, slot: &Slot, node_id: &NodeId) -> bool {
    let Some(worst_case) = &slot.validation.worst_case else {
        return false;
    };
    let Some(node) = scene.nodes.get(node_id) else {
        return false;
    };
    let NodeKind::Text(text) = &node.kind else {
        return false;
    };
    text.content.chars().count() > worst_case.chars().count()
}

fn slots_in_order(scene: &Scene) -> Vec<Slot> {
    scene.slots.values().cloned().collect()
}

fn operation_failure(
    slot_key: &SlotKey,
    node_id: Option<&NodeId>,
    action: &str,
    code: &str,
    message: &str,
) -> Diagnostic {
    Diagnostic::error(
        Phase::Operation,
        "LUMG0304",
        format!("{action} for slot {slot_key} failed: {code} {message}"),
        node_id.map(|node_id| DiagnosticSubject::Node(node_id.clone())),
    )
}

fn has_errors(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
}
