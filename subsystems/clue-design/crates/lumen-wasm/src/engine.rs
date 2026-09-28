//! The browser engine state: lumen-core driven by JSON requests.
//!
//! This module is deliberately free of wasm-bindgen types so the exact code
//! the browser runs is testable with native `cargo test -p lumen-wasm`. It
//! contains zero edit semantics of its own (Track E Decision 1): every
//! request routes to a lumen-core entry point, and the only logic here is
//! serialization plus the mechanical before/after scene diff that keeps the
//! JS render snapshot in sync without per-keystroke full-scene
//! serialization.

use lumen_core::brand::{validate_requested_brand_mode, BrandKit, BrandMode};
use lumen_core::preflight::token_options_for_scene_medium;
use lumen_core::validation::validate_scene;
use lumen_core::{
    build_structured_edit_batch, compile_dsl_into_scene_with_session, hit_stack, layout_scene,
    measure_key, preflight_scene, DslCompileSessionSnapshot, LayoutOptions, Operation, PageId,
    PreflightOptions, ProvidedLine, ProvidedMetrics, ProvidedTextMeasurer, Scene,
    SharedTextMeasurer, StructuredEditInstruction, TextDirection, TextMeasureInput, TextTransform,
    TextWrap,
};
use lumen_core::{BrandKitRef, Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::sync::Arc;

/// Text measurement honesty (Track E Decision 3): skia-safe cannot target
/// wasm32, so the in-browser engine measures with the heuristic fallback.
/// Server-computed geometry stays authoritative for text-dependent layout.
pub const TEXT_MEASUREMENT: &str = "heuristic";

/// Drop the LUMS0102 "measured heuristically" notice from wasm read-only
/// diagnostics. In the browser, heuristic measurement is the DECLARED,
/// documented mode (`text_measurement: "heuristic"` rides every payload), and
/// the editor already synthesizes its own loud client-side
/// EDITOR_HEURISTIC_MEASUREMENT signal from that field. Surfacing LUMS0102 here
/// too would double-report the identical fact. lumen-core still emits it — this
/// suppression is scoped to the wasm boundary, where it is redundant, not to
/// the diagnostic itself.
fn without_heuristic_measurement_notice(
    diagnostics: Vec<lumen_core::Diagnostic>,
) -> Vec<lumen_core::Diagnostic> {
    diagnostics
        .into_iter()
        .filter(|diagnostic| diagnostic.code != "LUMS0102")
        .collect()
}

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

/// Plan 4 item F: one editor-measured line box (see `ProvidedLine`).
#[derive(Deserialize)]
struct ProvidedMeasurementLine {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    baseline: f64,
}

/// One editor-supplied text measurement (Wave 3 C4): the measurement input
/// fields plus the SkParagraph width/height the editor measured for them.
#[derive(Deserialize)]
struct ProvidedMeasurement {
    #[serde(default)]
    node_id: Option<String>,
    #[serde(default)]
    font_size_override: Option<f64>,
    content: String,
    font_family: String,
    font_size: f64,
    font_weight: u16,
    // A7b: italic is a geometry input (selects the italic face). Defaulted so
    // pre-A7b editor payloads deserialize unchanged; the key mirrors layout.
    #[serde(default)]
    italic: bool,
    line_height: f64,
    letter_spacing: f64,
    wrap: TextWrap,
    #[serde(default)]
    max_lines: Option<u16>,
    direction: TextDirection,
    #[serde(default)]
    max_width: Option<f64>,
    #[serde(default)]
    max_height: Option<f64>,
    // A6a: geometry-affecting typography fields; defaulted so pre-A6a editor
    // payloads deserialize unchanged. The key must mirror the layout side.
    #[serde(default)]
    text_transform: TextTransform,
    #[serde(default)]
    truncate: bool,
    #[serde(default)]
    paragraph_spacing: f64,
    /// A6b review fix: the bridge carries raw spans so the editor's
    /// SkParagraph measurement can key spanned nodes — without this the
    /// engine-side spans digest can never match and spanned text silently
    /// falls back to the heuristic (which does not soft-wrap spans).
    #[serde(default)]
    spans: Vec<lumen_core::TextSpan>,
    width: f64,
    height: f64,
    /// Plan 4 item F: the painted line boxes measured at this record's
    /// `max_width` (paragraph-relative, left-aligned). Optional so the
    /// unconstrained records keep their shape.
    #[serde(default)]
    lines: Option<Vec<ProvidedMeasurementLine>>,
}

impl ProvidedMeasurement {
    fn input(&self) -> TextMeasureInput {
        TextMeasureInput {
            node_id: self.node_id.clone(),
            font_size_override: self.font_size_override,
            content: self.content.clone(),
            font_family: self.font_family.clone(),
            font_size: self.font_size,
            font_weight: self.font_weight,
            italic: self.italic,
            line_height: self.line_height,
            letter_spacing: self.letter_spacing,
            wrap: self.wrap.clone(),
            max_lines: self.max_lines,
            direction: self.direction.clone(),
            max_width: self.max_width,
            max_height: self.max_height,
            text_transform: self.text_transform,
            truncate: self.truncate,
            paragraph_spacing: self.paragraph_spacing,
            spans: self.spans.clone(),
        }
    }
}

#[derive(Clone, Deserialize)]
struct RenderContext {
    context_key: String,
    document_id: String,
    scene_brand_ref: Option<BrandKitRef>,
    scene_medium: Option<lumen_core::Medium>,
    brand_kit: Option<BrandKit>,
    mode: Option<BrandMode>,
    #[serde(default)]
    diagnostics: Vec<Diagnostic>,
}

pub struct Engine {
    scene: Scene,
    presentation: Scene,
    context: Option<RenderContext>,
    context_enabled: bool,
    context_error: Option<Diagnostic>,
    revision: u64,
    status: &'static str,
    diagnostics: Vec<Diagnostic>,
    dsl_session: Option<DslCompileSessionSnapshot>,
    /// Wave 3 C4: editor-supplied SkParagraph metrics. When set, `relayout`
    /// measures text with these (Skia-faithful), making editor `computed`
    /// match export. `None` → the heuristic fallback.
    measurer: Option<SharedTextMeasurer>,
}

impl Engine {
    /// Initialize from a full scene snapshot (serialization in: init).
    /// The scene is relaid-out once so the editor starts from a coherent,
    /// whole-tree `computed` baseline (the idempotence anchor that keeps
    /// later edits from perturbing unrelated nodes).
    pub fn from_scene_json(scene_json: &str) -> Result<Self, String> {
        let scene: Scene = serde_json::from_str(scene_json)
            .map_err(|error| format!("invalid scene JSON: {error}"))?;
        let mut engine = Self {
            presentation: scene.clone(),
            scene,
            context: None,
            context_enabled: false,
            context_error: None,
            revision: 1,
            status: "ready",
            diagnostics: Vec::new(),
            dsl_session: None,
            measurer: None,
        };
        engine.relayout();
        Ok(engine)
    }

    /// Replace the local scene (serialization in: reconcile / undo frames).
    /// Resets the DSL session: it indexed the previous scene state. The
    /// reconciled scene is relaid-out so editor render geometry stays
    /// single-source (local measurements) and never inherits the server's Skia
    /// `computed` directly, which would jump text on every reconcile.
    pub fn load_scene(&mut self, scene_json: &str) -> Result<(), String> {
        let scene: Scene = serde_json::from_str(scene_json)
            .map_err(|error| format!("invalid scene JSON: {error}"))?;
        self.scene = scene;
        self.revision += 1;
        self.dsl_session = None;
        // Canonical inputs must be remeasured after reconciliation. Legacy
        // standalone callers remeasure only when text changes, so retain their
        // keyed metrics across same-text geometry/undo snapshots.
        if self.context_enabled {
            self.measurer = None;
        }
        self.relayout();
        Ok(())
    }

    /// Refresh `computed` geometry for the whole scene from one heuristic
    /// layout pass. `computed` is a derived render cache: the parent and its
    /// children are always laid out together, so they can never disagree
    /// (the fix for the drag/edit coordinate desync). This writes geometry
    /// directly onto nodes — it does NOT emit operations, so the recomputed
    /// geometry never enters the authored edits sent to the server (which
    /// recomputes geometry canonically under Skia). The pass is idempotent:
    /// re-laying out an already-laid-out scene leaves unedited nodes
    /// unchanged, so an edit only moves the node it touched and that node's
    /// true layout dependents.
    fn relayout(&mut self) {
        let mut authored = self.scene.clone();
        for node in authored.nodes.values_mut() {
            node.computed = None;
        }
        self.diagnostics.clear();
        self.status = "ready";
        let layout = LayoutOptions {
            measurer: self.measurer.clone(),
            ..LayoutOptions::default()
        };
        let mut resolved = None;
        if self.context_enabled {
            if let Some(error) = &self.context_error {
                self.status = "invalid";
                self.diagnostics.push(error.clone());
            } else if let Some(context) = &self.context {
                self.diagnostics.extend(context.diagnostics.clone());
                if context.document_id != authored.meta.id.to_string()
                    || context.scene_brand_ref != authored.meta.brand_kit
                    || context.scene_medium != authored.meta.medium
                {
                    self.status = "pending";
                    self.diagnostics.push(context_diagnostic(
                        "EDITOR_RENDER_CONTEXT_STALE",
                        "Document pin or medium changed; awaiting fresh canonical render context",
                    ));
                    self.measurer = None;
                } else {
                    let mut options = PreflightOptions {
                        layout: layout.clone(),
                        ..PreflightOptions::default()
                    };
                    options.token_resolution.mode = context.mode.clone().unwrap_or_default();
                    options.token_resolution =
                        token_options_for_scene_medium(&authored, &options.token_resolution);
                    if let Some(kit) = &context.brand_kit {
                        self.diagnostics.extend(validate_requested_brand_mode(
                            kit,
                            &options.token_resolution.mode,
                        ));
                    }
                    if !self
                        .diagnostics
                        .iter()
                        .any(|d| d.severity == DiagnosticSeverity::Error)
                    {
                        let result =
                            preflight_scene(authored.clone(), context.brand_kit.as_ref(), options);
                        self.diagnostics.extend(result.diagnostics);
                        if result.layout_result.is_some() {
                            resolved = Some(result.scene);
                        }
                    }
                    if resolved.is_none() {
                        self.status = "invalid";
                    }
                }
            } else {
                self.status = "pending";
                self.diagnostics.push(context_diagnostic(
                    "EDITOR_RENDER_CONTEXT_PENDING",
                    "Canonical render context is unavailable; showing authored literals",
                ));
            }
        }
        self.presentation = resolved.unwrap_or_else(|| {
            // Explicit degraded preview. Never keep geometry or metrics from a previous context.
            let options = if self.status == "ready" {
                layout
            } else {
                LayoutOptions::default()
            };
            let result = layout_scene(&authored, options);
            self.diagnostics.extend(result.diagnostics);
            for (id, computed) in result.geometry {
                if let Some(node) = authored.nodes.get_mut(&id) {
                    node.computed = Some(computed);
                }
            }
            authored
        });
        for (id, node) in &mut self.scene.nodes {
            node.computed = self
                .presentation
                .nodes
                .get(id)
                .and_then(|node| node.computed.clone());
        }
    }

    pub fn set_render_context(&mut self, context_json: &str) -> String {
        self.revision += 1;
        self.context_enabled = true;
        self.context = None;
        self.context_error = None;
        self.measurer = None;
        match serde_json::from_str::<Option<RenderContext>>(context_json) {
            Ok(context) => self.context = context,
            Err(error) => {
                self.context_error = Some(context_diagnostic(
                    "EDITOR_RENDER_CONTEXT_INVALID",
                    &error.to_string(),
                ))
            }
        }
        self.relayout();
        self.presentation_json()
    }

    fn derivation(&self) -> Value {
        json!({"context_key": self.context.as_ref().map(|c| &c.context_key),
            "input_revision": self.revision, "status": self.status,
            "diagnostics": without_heuristic_measurement_notice(self.diagnostics.clone())})
    }

    pub fn presentation_json(&self) -> String {
        let mut value = self.derivation();
        value["scene"] = to_value(&self.presentation);
        value.to_string()
    }

    /// Wave 3 C4 (measure-then-inject): install editor-supplied SkParagraph
    /// metrics and relayout, so text `computed` becomes Skia-faithful. The
    /// payload is `[{ content, font_family, font_size, font_weight,
    /// line_height, letter_spacing, wrap, max_lines, direction, max_width?,
    /// max_height?, width, height, lines? }]` — `lines` (Plan 4 item F) being
    /// the painted line boxes `[{ x, y, width, height, baseline }]` the editor
    /// measured at this record's `max_width`, which replace the heuristic
    /// per-line detail when present. The engine keys each entry by the same
    /// measurement input it lays out with. An empty payload clears the
    /// override (back to the heuristic).
    pub fn set_measurements(&mut self, measurements_json: &str) -> String {
        let entries: Vec<ProvidedMeasurement> = match serde_json::from_str(measurements_json) {
            Ok(entries) => entries,
            Err(error) => {
                return json!({
                    "ok": false,
                    "error": { "code": "EDITOR_WASM_MEASUREMENTS_INVALID", "message": error.to_string() }
                })
                .to_string()
            }
        };
        let mut overrides = HashMap::with_capacity(entries.len());
        for entry in &entries {
            overrides.insert(
                measure_key(&entry.input()),
                ProvidedMetrics {
                    width: entry.width,
                    height: entry.height,
                    lines: entry.lines.as_ref().map(|lines| {
                        lines
                            .iter()
                            .map(|line| ProvidedLine {
                                x: line.x,
                                y: line.y,
                                width: line.width,
                                height: line.height,
                                baseline: line.baseline,
                            })
                            .collect()
                    }),
                },
            );
        }
        let provided = Arc::new(ProvidedTextMeasurer::new(overrides));
        self.measurer = if provided.is_empty() {
            None
        } else {
            Some(provided.clone())
        };
        self.relayout();
        json!({ "ok": true, "count": entries.len(), "missing": provided.missing_inputs() })
            .to_string()
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
        let before_presentation = self.presentation.clone();
        let inverse_operations = self.scene.invert_operations(&operations).ok().flatten();
        match self.scene.apply_operations_checked(operations) {
            Ok(report) => {
                self.revision += 1;
                // Refresh derived geometry so the delta carries a coherent
                // whole-tree `computed` for the optimistic render. The
                // authored operations the editor persists are unaffected.
                self.relayout();
                json!({
                    "ok": true,
                    "applied_operations": report.applied_operations,
                    "diagnostics": report.diagnostics,
                    "inverse_operations": inverse_operations,
                    "delta": scene_delta(&before, &self.scene),
                    "presentation_delta": scene_delta(&before_presentation, &self.presentation),
                    "derivation": self.derivation(),
                })
                .to_string()
            }
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
        let before_presentation = self.presentation.clone();
        match batch.apply_checked(&mut self.scene) {
            Ok(report) => {
                self.revision += 1;
                self.relayout();
                json!({
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
                    "presentation_delta": scene_delta(&before_presentation, &self.presentation),
                    "derivation": self.derivation(),
                })
                .to_string()
            }
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
        let before_presentation = self.presentation.clone();
        let result =
            compile_dsl_into_scene_with_session(source, &mut self.scene, self.dsl_session.take());
        self.dsl_session = Some(result.session_snapshot);
        self.revision += 1;
        // A compiled block creates/edits nodes; refresh geometry so the
        // editor renders the new tree from one coherent layout pass.
        self.relayout();
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
                    "presentation_delta": scene_delta(&before_presentation, &self.presentation),
                    "derivation": self.derivation(),
        })
        .to_string()
    }

    /// Heuristic layout pass over the local scene (read-only). Decision E3:
    /// this is the wasm fallback measurer; server geometry stays
    /// authoritative for text-dependent layout.
    pub fn layout_geometry(&self) -> String {
        let geometry: std::collections::BTreeMap<_, _> = self
            .presentation
            .nodes
            .iter()
            .filter_map(|(id, node)| node.computed.as_ref().map(|c| (id, c)))
            .collect();
        json!({"geometry": geometry,
            "diagnostics": without_heuristic_measurement_notice(self.diagnostics.clone()),
            "text_measurement": TEXT_MEASUREMENT, "derivation": self.derivation()})
        .to_string()
    }

    /// Context-aware diagnostics for the current browser measurer; server export remains authoritative.
    pub fn preflight(&self) -> String {
        let diagnostics = if self.context_enabled {
            self.diagnostics.clone()
        } else {
            preflight_scene(
                self.scene.clone(),
                None,
                PreflightOptions {
                    layout: LayoutOptions {
                        measurer: self.measurer.clone(),
                        ..LayoutOptions::default()
                    },
                    ..PreflightOptions::default()
                },
            )
            .diagnostics
        };
        json!({"has_errors": diagnostics.iter().any(|d| d.severity == DiagnosticSeverity::Error),
            "diagnostics": without_heuristic_measurement_notice(diagnostics),
            "text_measurement": TEXT_MEASUREMENT, "derivation": self.derivation()})
        .to_string()
    }

    /// Scene validation diagnostics (structural, wasm-clean).
    pub fn validate(&self) -> String {
        json!({ "diagnostics": validate_scene(&self.scene) }).to_string()
    }

    /// Point→node hit-test in absolute page space (Wave 3 C3a). Returns
    /// `{ "hit": <topmost node id or null>, "stack": [<bottom-to-top>] }`.
    /// `hit` is the single-click target (deepest-first); `stack` lets the
    /// gesture layer drill in / cycle overlapping nodes. One traversal.
    pub fn hit_test(&self, page_id: &str, x: f64, y: f64) -> String {
        let page = PageId::from(page_id);
        let stack: Vec<String> = hit_stack(&self.presentation, &page, x, y)
            .iter()
            .map(|id| id.to_string())
            .collect();
        let hit = stack.last().cloned();
        json!({ "hit": hit, "stack": stack }).to_string()
    }
}

fn context_diagnostic(code: &str, message: &str) -> Diagnostic {
    Diagnostic::error(
        Phase::Brand,
        code,
        message,
        Some(DiagnosticSubject::Document),
    )
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
