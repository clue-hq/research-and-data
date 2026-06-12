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
use crate::binding::{validate_binding_set, BindingSet, BoundValue};
use crate::diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use crate::ids::{AssetId, NodeId, SlotKey};
use crate::layout::{layout_scene, LayoutOptions};
use crate::operations::{FieldPatch, NodePatch, Operation, OptionalFieldPatch};
use crate::scene::{DocumentStatus, NodeKind, Scene};
use crate::slots::{ImagePolicy, Slot};
use crate::text_measure::SharedTextMeasurer;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
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
/// this" without replaying anything.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InstanceAuditEntry {
    pub kind: InstanceAuditKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_key: Option<SlotKey>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub node_ids: Vec<NodeId>,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DerivedInstance {
    pub scene: Scene,
    pub diagnostics: Vec<Diagnostic>,
    pub audit: Vec<InstanceAuditEntry>,
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
        };
    }

    let mut scene = snapshot.clone();
    let finalized_status = scene.meta.status.clone();
    // Canonical operations refuse to mutate finalized scenes; derivation
    // works on a draft copy and restores the finalized status afterwards so
    // the derived artifact keeps its revision provenance.
    scene.meta.status = DocumentStatus::Draft;

    let mut audit = Vec::new();

    apply_scalar_values(&mut scene, binding, assets, &mut diagnostics, &mut audit);
    bind_generated_assets(&mut scene, binding, assets, &mut diagnostics, &mut audit);

    relayout(&mut scene, options, &mut diagnostics);

    scene.meta.status = finalized_status;

    DerivedInstance {
        scene,
        diagnostics,
        audit,
    }
}

fn apply_scalar_values(
    scene: &mut Scene,
    binding: &BindingSet,
    assets: &DerivationAssets,
    diagnostics: &mut Vec<Diagnostic>,
    audit: &mut Vec<InstanceAuditEntry>,
) {
    for slot in slots_in_order(scene) {
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
            BoundValue::List { .. } => {
                // Repeater expansion is slice G4.
            }
        }
    }
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
fn relayout(scene: &mut Scene, options: &DeriveOptions, diagnostics: &mut Vec<Diagnostic>) {
    let layout = layout_scene(
        scene,
        LayoutOptions {
            validate_slots: false,
            measurer: options.measurer.as_ref().map(Arc::clone),
        },
    );
    for diagnostic in layout.diagnostics {
        if !diagnostics.contains(&diagnostic) {
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
