//! The browser engine state: lumen-core driven by JSON requests.
//!
//! This module is deliberately free of wasm-bindgen types so the exact code
//! the browser runs is testable with native `cargo test -p lumen-wasm`. It
//! contains zero edit semantics of its own (Track E Decision 1): every
//! request routes to a lumen-core entry point, and the only logic here is
//! serialization plus the mechanical before/after scene diff that keeps the
//! JS render snapshot in sync without per-keystroke full-scene
//! serialization.

use lumen_core::validation::validate_scene;
use lumen_core::{
    build_structured_edit_batch, compile_dsl_into_scene_with_session, layout_scene,
    preflight_scene, DslCompileSessionSnapshot, LayoutOptions, Operation, PreflightOptions, Scene,
    StructuredEditInstruction,
};
use serde::Serialize;
use serde_json::{json, Map, Value};

/// Text measurement honesty (Track E Decision 3): skia-safe cannot target
/// wasm32, so the in-browser engine measures with the heuristic fallback.
/// Server-computed geometry stays authoritative for text-dependent layout.
pub const TEXT_MEASUREMENT: &str = "heuristic";

/// Version handshake payload (Track E Decision 4). The editor compares this
/// against the API's build info and downgrades to server-only mode on any
/// mismatch.
pub fn version_payload() -> Value {
    json!({
        "schema_version": lumen_core::SCHEMA_VERSION,
        "engine_commit": env!("LUMEN_ENGINE_COMMIT"),
        "text_measurement": TEXT_MEASUREMENT,
    })
}

pub struct Engine {
    scene: Scene,
    dsl_session: Option<DslCompileSessionSnapshot>,
}

impl Engine {
    /// Initialize from a full scene snapshot (serialization in: init).
    pub fn from_scene_json(scene_json: &str) -> Result<Self, String> {
        let scene: Scene = serde_json::from_str(scene_json)
            .map_err(|error| format!("invalid scene JSON: {error}"))?;
        Ok(Self {
            scene,
            dsl_session: None,
        })
    }

    /// Replace the local scene (serialization in: reconcile / undo frames).
    /// Resets the DSL session: it indexed the previous scene state.
    pub fn load_scene(&mut self, scene_json: &str) -> Result<(), String> {
        let scene: Scene = serde_json::from_str(scene_json)
            .map_err(|error| format!("invalid scene JSON: {error}"))?;
        self.scene = scene;
        self.dsl_session = None;
        Ok(())
    }

    /// Full scene snapshot out. Reserved for init/reconcile/undo-frame
    /// paths; the per-edit channel is the delta in each apply result.
    pub fn scene_json(&self) -> String {
        serde_json::to_string(&self.scene).expect("scene serializes")
    }

    /// Apply a batch of canonical operations atomically (the checked core
    /// apply is draft-based: failures leave the scene untouched). The
    /// result carries the same inverse-operations contract as the API
    /// helper plus a mechanical scene delta for the JS render snapshot.
    pub fn apply_operations(&mut self, operations_json: &str) -> String {
        let operations: Vec<Operation> = match serde_json::from_str(operations_json) {
            Ok(operations) => operations,
            Err(error) => {
                return error_payload(
                    "wasm.operations",
                    format!("invalid operations JSON: {error}"),
                    Vec::new(),
                )
            }
        };
        let before = self.scene.clone();
        let inverse_operations = self.scene.invert_operations(&operations).ok().flatten();
        match self.scene.apply_operations_checked(operations) {
            Ok(report) => json!({
                "ok": true,
                "applied_operations": report.applied_operations,
                "diagnostics": report.diagnostics,
                "inverse_operations": inverse_operations,
                "delta": scene_delta(&before, &self.scene),
            })
            .to_string(),
            Err(error) => error_payload("wasm.apply", error.message, error.diagnostics),
        }
    }

    /// Lower and apply a structured edit through the shared lumen-core
    /// routing (`build_structured_edit_batch`) — the same path the API
    /// helper uses, so optimistic results match server results by
    /// construction. The response mirrors the helper's `apply_structured_edit`
    /// shape (operations + edit metadata) with a delta instead of the scene.
    pub fn apply_structured_edit(&mut self, edit_json: &str) -> String {
        let edit: StructuredEditInstruction = match serde_json::from_str(edit_json) {
            Ok(edit) => edit,
            Err(error) => {
                return error_payload(
                    "wasm.structured_edit",
                    format!("invalid structured edit JSON: {error}"),
                    Vec::new(),
                )
            }
        };
        let batch = match build_structured_edit_batch(&self.scene, &edit) {
            Ok(batch) => batch,
            Err(error) => {
                return error_payload(
                    error.kind.code(),
                    error.message.clone(),
                    vec![error.diagnostic()],
                )
            }
        };
        let before = self.scene.clone();
        match batch.apply_checked(&mut self.scene) {
            Ok(report) => json!({
                "ok": true,
                "applied_operations": report.applied_operations,
                "diagnostics": report.diagnostics,
                "operations": batch.operations,
                "edit": {
                    "kind": edit.kind(),
                    "touched_targets": batch.touched_targets,
                    "intent": batch.intent,
                    "checkpoint_label": batch.checkpoint_label,
                    "inverse_operations": batch.inverse_operations,
                    "lineage": batch.lineage,
                },
                "delta": scene_delta(&before, &self.scene),
            })
            .to_string(),
            Err(error) => error_payload(
                error.kind.code(),
                error.message.clone(),
                vec![error.diagnostic()],
            ),
        }
    }

    /// Compile a DSL block against the local scene, holding the compile
    /// session in engine state across calls (the module owns local state).
    pub fn compile_dsl_block(&mut self, source: &str) -> String {
        let before = self.scene.clone();
        let result =
            compile_dsl_into_scene_with_session(source, &mut self.scene, self.dsl_session.take());
        self.dsl_session = Some(result.session_snapshot);
        json!({
            "ok": true,
            "compile_output": {
                "operations": result.compile_output.operations,
                "checkpoint_label": result.compile_output.checkpoint_label,
                "diagnostics": result
                    .compile_output
                    .diagnostics
                    .iter()
                    .map(|diagnostic| json!({
                        "diagnostic": diagnostic.diagnostic,
                        "span": {
                            "line": diagnostic.span.line,
                            "column": diagnostic.span.column,
                            "length": diagnostic.span.length,
                        }
                    }))
                    .collect::<Vec<_>>(),
                "halted_at": result.compile_output.halted_at.as_ref().map(|halt| json!({
                    "line": halt.line,
                    "code": halt.code,
                })),
            },
            "operation_report": result.operation_report.map(|report| json!({
                "applied_operations": report.applied_operations,
                "diagnostics": report.diagnostics,
            })),
            "operation_error": result.operation_error.map(|error| json!({
                "code": error.code,
                "message": error.message,
                "diagnostics": error.diagnostics,
            })),
            "delta": scene_delta(&before, &self.scene),
        })
        .to_string()
    }

    /// Heuristic layout pass over the local scene (read-only). Decision E3:
    /// this is the wasm fallback measurer; server geometry stays
    /// authoritative for text-dependent layout.
    pub fn layout_geometry(&self) -> String {
        let result = layout_scene(&self.scene, LayoutOptions::default());
        json!({
            "geometry": result.geometry,
            "diagnostics": result.diagnostics,
            "text_measurement": TEXT_MEASUREMENT,
        })
        .to_string()
    }

    /// Read-only preflight subset: diagnostics under the heuristic
    /// measurer, no brand kit resolution, scene untouched. The canonical
    /// preflight (Skia measurement, brand kits) remains the server's.
    pub fn preflight(&self) -> String {
        let result = preflight_scene(self.scene.clone(), None, PreflightOptions::default());
        json!({
            "has_errors": result.has_errors(),
            "diagnostics": result.diagnostics,
            "text_measurement": TEXT_MEASUREMENT,
        })
        .to_string()
    }

    /// Scene validation diagnostics (structural, wasm-clean).
    pub fn validate(&self) -> String {
        json!({ "diagnostics": validate_scene(&self.scene) }).to_string()
    }
}

fn error_payload(
    code: impl Into<String>,
    message: impl Into<String>,
    diagnostics: Vec<lumen_core::Diagnostic>,
) -> String {
    json!({
        "ok": false,
        "error": { "code": code.into(), "message": message.into() },
        "diagnostics": diagnostics,
    })
    .to_string()
}

/// Mechanical before/after diff of the scene's entity maps. Pure
/// comparison — no knowledge of operation semantics — so it cannot drift
/// from the core's behavior. Removed entries serialize as `null`.
fn scene_delta(before: &Scene, after: &Scene) -> Value {
    let mut delta = Map::new();
    if before.meta != after.meta {
        delta.insert("meta".to_owned(), to_value(&after.meta));
    }
    insert_map_delta(&mut delta, "pages", &before.pages, &after.pages);
    insert_map_delta(&mut delta, "nodes", &before.nodes, &after.nodes);
    insert_map_delta(&mut delta, "slots", &before.slots, &after.slots);
    insert_map_delta(&mut delta, "assets", &before.assets, &after.assets);
    if before.export_profiles != after.export_profiles {
        delta.insert(
            "export_profiles".to_owned(),
            to_value(&after.export_profiles),
        );
    }
    Value::Object(delta)
}

fn insert_map_delta<K, V>(
    delta: &mut Map<String, Value>,
    field: &str,
    before: &std::collections::BTreeMap<K, V>,
    after: &std::collections::BTreeMap<K, V>,
) where
    K: Ord + std::fmt::Display,
    V: PartialEq + Serialize,
{
    let mut changes = Map::new();
    for (key, value) in after {
        if before.get(key) != Some(value) {
            changes.insert(key.to_string(), to_value(value));
        }
    }
    for key in before.keys() {
        if !after.contains_key(key) {
            changes.insert(key.to_string(), Value::Null);
        }
    }
    if !changes.is_empty() {
        delta.insert(field.to_owned(), Value::Object(changes));
    }
}

fn to_value<T: Serialize>(value: &T) -> Value {
    serde_json::to_value(value).expect("core contract types serialize")
}
