//! lumen-wasm: thin wasm-bindgen bindings over lumen-core for the browser
//! editor (Wave 2 Track E).
//!
//! Golden rule (Decision 1): this crate has zero semantics of its own. The
//! WASM module owns the local scene in its memory; JS sends operations and
//! structured edits in and receives results, deltas, and diagnostics out.
//! Full scene snapshots cross the boundary only on init, reconcile, and
//! undo frames — never per keystroke.
//!
//! Text honesty (Decision 3): in-browser measurement is the lumen-core
//! heuristic fallback (skia-safe cannot target wasm32). Server-computed
//! geometry stays authoritative for text-dependent layout; `version()`
//! reports `text_measurement: "heuristic"` so callers cannot mistake this
//! for shaped parity.

mod engine;

pub use engine::{version_payload, Engine, TEXT_MEASUREMENT};

use wasm_bindgen::prelude::*;

/// Handshake payload: `{ schema_version, engine_commit, text_measurement }`.
#[wasm_bindgen(js_name = engineVersion)]
pub fn engine_version() -> String {
    engine::version_payload().to_string()
}

/// Deterministic slot id derivation (lumen-core `slot_id_for_key`). The
/// editor keeps a synchronous TS mirror of this hash; its test suite pins
/// the mirror against this binding so drift fails CI.
#[wasm_bindgen(js_name = slotIdForKey)]
pub fn slot_id_for_key(key: &str) -> String {
    lumen_core::slot_id_for_key(&lumen_core::SlotKey::from(key)).to_string()
}

#[wasm_bindgen]
pub struct LumenEngine {
    inner: Engine,
}

#[wasm_bindgen]
impl LumenEngine {
    /// Initialize the engine with a full scene snapshot.
    #[wasm_bindgen(constructor)]
    pub fn new(scene_json: &str) -> Result<LumenEngine, JsError> {
        Engine::from_scene_json(scene_json)
            .map(|inner| LumenEngine { inner })
            .map_err(|message| JsError::new(&message))
    }

    /// Replace the local scene (reconcile / undo-frame path).
    #[wasm_bindgen(js_name = loadScene)]
    pub fn load_scene(&mut self, scene_json: &str) -> Result<(), JsError> {
        self.inner
            .load_scene(scene_json)
            .map_err(|message| JsError::new(&message))
    }

    /// Full scene snapshot out (init/reconcile/undo frames only).
    #[wasm_bindgen(js_name = sceneJson)]
    pub fn scene_json(&self) -> String {
        self.inner.scene_json()
    }

    #[wasm_bindgen(js_name = setRenderContext)]
    pub fn set_render_context(&mut self, context_json: &str) -> String {
        self.inner.set_render_context(context_json)
    }

    #[wasm_bindgen(js_name = presentationJson)]
    pub fn presentation_json(&self) -> String {
        self.inner.presentation_json()
    }

    /// Apply a JSON array of canonical operations; returns a result with
    /// report, diagnostics, inverse operations, and a scene delta.
    #[wasm_bindgen(js_name = applyOperations)]
    pub fn apply_operations(&mut self, operations_json: &str) -> String {
        self.inner.apply_operations(operations_json)
    }

    /// Apply a structured edit instruction; returns the canonical batch
    /// result (operations, inverses, touched targets) plus a scene delta.
    #[wasm_bindgen(js_name = applyStructuredEdit)]
    pub fn apply_structured_edit(&mut self, edit_json: &str) -> String {
        self.inner.apply_structured_edit(edit_json)
    }

    /// Compile a DSL block against the local scene, keeping the compile
    /// session in module state.
    #[wasm_bindgen(js_name = compileDslBlock)]
    pub fn compile_dsl_block(&mut self, source: &str) -> String {
        self.inner.compile_dsl_block(source)
    }

    /// Heuristic layout geometry (read-only; server geometry authoritative).
    #[wasm_bindgen(js_name = layoutGeometry)]
    pub fn layout_geometry(&self) -> String {
        self.inner.layout_geometry()
    }

    /// Read-only preflight subset under the heuristic measurer.
    pub fn preflight(&self) -> String {
        self.inner.preflight()
    }

    /// Structural scene validation diagnostics.
    pub fn validate(&self) -> String {
        self.inner.validate()
    }

    /// Point→node hit-test in absolute page space (Wave 3 C3a). Returns
    /// `{ hit: string|null, stack: string[] }` (stack is bottom-to-top).
    #[wasm_bindgen(js_name = hitTest)]
    pub fn hit_test(&self, page_id: &str, x: f64, y: f64) -> String {
        self.inner.hit_test(page_id, x, y)
    }

    /// Install editor-supplied SkParagraph text metrics and relayout, so text
    /// `computed` becomes Skia-faithful (Wave 3 C4 measure-then-inject). Empty
    /// payload clears the override. Returns `{ ok, count }` or an error object.
    #[wasm_bindgen(js_name = setMeasurements)]
    pub fn set_measurements(&mut self, measurements_json: &str) -> String {
        self.inner.set_measurements(measurements_json)
    }

    /// Handshake payload, also exposed on the instance for convenience.
    pub fn version(&self) -> String {
        engine::version_payload().to_string()
    }
}
