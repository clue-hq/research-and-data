use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use lumen_assets::{
    digest_relative_path, AssetStore, IngestRequest, LocalAssetStore, DEFAULT_MAX_BYTES,
};
use lumen_core::validation::validate_scene;
use lumen_core::SharedTextMeasurer;
use lumen_core::{
    batch_scope_violations, build_structured_edit_batch_with_text_context,
    compare_brand_kit_compatibility, compile_dsl_into_scene_with_text_context,
    compile_styles_brand_kit, derive_instance, generate_brand_kit, layout_scene,
    platform_default_brand_kit, preflight_scene, summarize_brand_kit_for_authoring,
    validate_binding_set, validate_brand_kit, validate_brand_kit_product_ready,
    validate_scene_brand_governance, AssetDigest, AssetId, AssetKind, AssetLicense, AssetLocation,
    AssetMediaMetadata, AssetProvenance, AssetRecord, AssetSource, AssetStatus, AssetThumbnail,
    BindingSet, BrandGovernanceStrictness, BrandKit, BrandKitId, BrandMode, BrandSeed,
    DerivationAssets, DeriveOptions, Diagnostic, DiagnosticSeverity, DocumentId,
    DslCompileSessionSnapshot, EditScope, EditScopeMode, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, Medium, NodeId, Operation, PageId, PdfIntent,
    PreflightOptions, RasterScale, Scene, ScopeViolation, StructuredEditInstruction,
    TemplateRevisionId, TextEditContext, TokenResolutionOptions,
};
use lumen_export::LumenExportAdapter;
use lumen_skia::{
    FontManager, SkiaFontFaceResolver, SkiaSceneRenderer, SkiaTextMeasurer, SkiaVectorPdfRenderer,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::io::{self, Read};
use std::sync::Arc;
use std::time::Instant;

mod store_resolver;

use store_resolver::{StoreBackedResolver, LOCAL_STORE_PROVIDER};

/// Brand-kit font faces for a request: sha256 digests of font assets in the
/// shared content-addressed store, each with the kit-DECLARED family name.
/// The caller (API / agent runtime) resolves kit
/// `assets.fonts[*].faces[].asset_id` to digests. The declared family is the
/// name scenes actually request, and it is routinely an alias over the
/// bytes' intrinsic name (`@font-face` aliasing: kit "Aeonik" over trial
/// bytes named "Aeonik TRIAL") — both must resolve.
#[derive(Debug, Deserialize)]
struct BrandFontsSpec {
    store_root: String,
    faces: Vec<BrandFontFaceSpec>,
}

#[derive(Debug, Deserialize)]
struct BrandFontFaceSpec {
    digest: String,
    #[serde(default)]
    family: Option<String>,
}

/// Read one spec's faces from the store into `faces`, degrading unreadable
/// entries to LUMS0101 warnings. `family_filter` is the library-fonts lazy
/// load: when set, a face loads only if its declared family appears in the
/// request's scene/kit JSON — the library is ~27 families and a request
/// typically uses two or three, so eager loading would read megabytes of
/// unused bytes per helper call. Substring matching over the serialized
/// request can only over-load (harmless), never under-load: scenes and kits
/// reference families by their exact declared name.
fn collect_font_faces(
    spec: &BrandFontsSpec,
    source_label: &str,
    family_filter: Option<&str>,
    seen_digests: &mut std::collections::HashSet<String>,
    faces: &mut Vec<(Vec<u8>, Option<String>)>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let store = LocalAssetStore::new(&spec.store_root);
    let mut unavailable = |digest: &str, detail: String| {
        diagnostics.push(
            Diagnostic::warning(
                lumen_core::Phase::Layout,
                "LUMS0101",
                format!("{source_label} font face sha256:{digest} is unavailable: {detail}"),
                None,
            )
            .with_hint(
                "Text in this family shapes with the bundled fallback; re-ingest the font asset to restore fidelity.",
            ),
        );
    };
    for face in &spec.faces {
        if let Some(scan) = family_filter {
            match face.family.as_deref() {
                Some(family) if !family.is_empty() && scan.contains(family) => {}
                _ => continue,
            }
        }
        if !seen_digests.insert(face.digest.clone()) {
            continue;
        }
        match digest_relative_path(&face.digest) {
            Ok(relative_path) => match store.get(&relative_path) {
                Ok(bytes) => faces.push((bytes, face.family.clone())),
                Err(error) => unavailable(&face.digest, error.to_string()),
            },
            Err(error) => unavailable(&face.digest, error.to_string()),
        }
    }
}

/// Build the request's font set: the bundled deterministic faces, any
/// brand-kit faces readable from the store, and the library faces whose
/// family the request actually mentions (`family_scan` = the serialized
/// scene + kit JSON). Unreadable or unparseable faces degrade to warning
/// diagnostics (LUMS0101) — a bad font must never take down shaping, and it
/// must never fail silently either.
fn load_request_fonts(
    brand: Option<&BrandFontsSpec>,
    library: Option<&BrandFontsSpec>,
    family_scan: &str,
) -> (Arc<FontManager>, Vec<Diagnostic>) {
    if brand.is_none() && library.is_none() {
        return (Arc::new(FontManager::bundled()), Vec::new());
    }
    let mut faces = Vec::new();
    let mut diagnostics = Vec::new();
    let mut seen_digests = std::collections::HashSet::new();
    if let Some(spec) = brand {
        collect_font_faces(spec, "brand", None, &mut seen_digests, &mut faces, &mut diagnostics);
    }
    if let Some(spec) = library {
        collect_font_faces(
            spec,
            "library",
            Some(family_scan),
            &mut seen_digests,
            &mut faces,
            &mut diagnostics,
        );
    }
    let (fonts, errors) = FontManager::bundled_with(faces);
    for error in errors {
        diagnostics.push(
            Diagnostic::warning(
                lumen_core::Phase::Layout,
                "LUMS0101",
                format!("font face is unavailable: {error}"),
                None,
            )
            .with_hint(
                "Text in this family shapes with the bundled fallback; re-ingest the font asset to restore fidelity.",
            ),
        );
    }
    (Arc::new(fonts), diagnostics)
}

/// The server-side text measurer: SkParagraph shaping over the request's
/// font set (Wave 1 Track A, Decision 5; K3 adds brand-kit faces). Every
/// helper path that measures text — preflight, layout geometry, export —
/// injects this; the heuristic remains only as the wasm fallback inside
/// lumen-core.
fn server_measurer_with(fonts: Arc<FontManager>) -> SharedTextMeasurer {
    Arc::new(SkiaTextMeasurer::new(fonts))
}

/// Export adapter composition for every server export path (slice A4):
/// Skia text measurement for SVG/PDF line breaks and the direct Skia scene
/// renderer for PNG rasters and PDF — measurer and renderer share one
/// FontManager, so critic previews and artifacts shape text identically to
/// preflight.
///
/// PDF renderer selection (print W2): the vector Skia-PDF renderer (live
/// text, embedded subset fonts, parity with PNG by shared paint) is the
/// default; `LUMEN_PDF_RENDERER=flattened` selects the W0 raster-flattened
/// baseline (D5: kept for comparison until the vector path has burned in).
/// Any other value falls through to vector — never a silent third mode.
fn server_export_adapter_with(
    adapter: LumenExportAdapter,
    fonts: Arc<FontManager>,
) -> LumenExportAdapter {
    let renderer = Arc::new(SkiaSceneRenderer::new(Arc::clone(&fonts)));
    let pdf_renderer: Arc<dyn lumen_export::ScenePdfRenderer> =
        match std::env::var("LUMEN_PDF_RENDERER").as_deref() {
            Ok("flattened") => Arc::clone(&renderer) as _,
            _ => Arc::new(SkiaVectorPdfRenderer::from_renderer((*renderer).clone())),
        };
    adapter
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(renderer)
        .with_pdf_renderer(pdf_renderer)
        // SVG font embedding shares the same FontManager as measurement and
        // paint: the embedded @font-face bytes are the faces that shaped and
        // painted — parity by construction.
        .with_font_resolver(Arc::new(SkiaFontFaceResolver::new(fonts)))
}
// NOTE: there is deliberately no fonts-defaulted variant of the measurer or
// adapter builders — every call site must state its font set explicitly.
// The bundled-Inter defaults were how derive_instance silently shipped
// wrong-typeface bulk runs.

#[derive(Debug, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
enum CoreRequest {
    NewScene {
        document_id: String,
        title: String,
        artifact_type: Option<String>,
        medium: Option<Value>,
    },
    ValidateScene {
        scene: Value,
    },
    ApplyOperations {
        scene: Value,
        operations: Vec<Value>,
        #[serde(default)]
        scope: Option<EditScope>,
    },
    ApplyStructuredEdit {
        scene: Value,
        edit: StructuredEditInstruction,
        #[serde(default)]
        scope: Option<EditScope>,
        #[serde(default)]
        brand_kit: Option<Value>,
        #[serde(default)]
        mode: Option<Value>,
    },
    CompileDslIntoScene {
        scene: Value,
        source: String,
        #[serde(default)]
        dsl_session: Option<Value>,
        /// Slice 3: seed-born / human node ids a `reconcile(...)` block must
        /// KEEP when omitted (LUMD0262). Defaulted empty (pure declarative).
        #[serde(default)]
        protected_node_ids: Vec<String>,
        #[serde(default)]
        brand_kit: Option<Value>,
        #[serde(default)]
        mode: Option<Value>,
    },
    PreflightScene {
        scene: Value,
        brand_kit: Option<Value>,
        #[serde(default)]
        mode: Option<Value>,
        #[serde(default)]
        brand_fonts: Option<BrandFontsSpec>,
        #[serde(default)]
        library_fonts: Option<BrandFontsSpec>,
    },
    ExportPreview {
        scene: Value,
        format: ExportFormat,
        page_ids: Vec<String>,
        #[serde(default)]
        profile: Option<Value>,
        #[serde(default)]
        asset_store_root: Option<String>,
        #[serde(default)]
        brand_fonts: Option<BrandFontsSpec>,
        #[serde(default)]
        library_fonts: Option<BrandFontsSpec>,
    },
    IngestAsset {
        store_root: String,
        bytes_base64: String,
        asset_id: String,
        label: String,
        #[serde(default)]
        declared_mime_type: Option<String>,
        #[serde(default)]
        filename: Option<String>,
        #[serde(default)]
        kind: Option<Value>,
        #[serde(default)]
        uploaded_by: Option<String>,
        #[serde(default)]
        license: Option<Value>,
        #[serde(default)]
        provenance: Option<Value>,
        #[serde(default)]
        source: Option<Value>,
        #[serde(default)]
        tags: Option<Vec<String>>,
        #[serde(default)]
        max_bytes: Option<u64>,
    },
    GenerateQr {
        store_root: String,
        data: String,
        asset_id: String,
        #[serde(default)]
        label: Option<String>,
        #[serde(default)]
        ec_level: Option<String>,
        #[serde(default)]
        print: bool,
        #[serde(default)]
        target_width_mm: Option<f64>,
    },
    GenerateAsset {
        store_root: String,
        provider: String,
        request: Value,
        asset_id: String,
        #[serde(default)]
        label: Option<String>,
    },
    FinalizeTemplate {
        scene: Value,
        template_revision_id: String,
    },
    PlatformDefaultBrandKit,
    ValidateBrandKit {
        brand_kit: Value,
        #[serde(default)]
        product_ready: bool,
    },
    CompileStylesBrandKit {
        source: String,
        brand_kit_id: String,
        version: u32,
        name: String,
    },
    GenerateBrandKit {
        seed: Value,
    },
    SummarizeBrandKit {
        brand_kit: Value,
    },
    ValidateSceneBrandGovernance {
        scene: Value,
        brand_kit: Value,
        strictness: BrandGovernanceStrictness,
    },
    CompareBrandKitCompatibility {
        from: Value,
        to: Value,
    },
    LayoutGeometry {
        scene: Value,
        #[serde(default)]
        brand_fonts: Option<BrandFontsSpec>,
        #[serde(default)]
        library_fonts: Option<BrandFontsSpec>,
    },
    ValidateBindingSet {
        scene: Value,
        binding_set: Value,
    },
    DeriveInstance {
        scene: Value,
        binding_set: Value,
        #[serde(default)]
        asset_records: Vec<Value>,
        #[serde(default)]
        store_root: Option<String>,
        /// Bulk-export formats rendered after a clean derivation
        /// ("svg" | "png" | "pdf"); artifacts store content-addressed.
        #[serde(default)]
        export_formats: Vec<String>,
        #[serde(default)]
        export_dpi: Option<u16>,
        /// Kit + library faces for shaping and artifact rendering. Without
        /// these every instance shapes with bundled Inter — the silent
        /// substitution that made bulk runs lie about the template's
        /// typography.
        #[serde(default)]
        brand_fonts: Option<BrandFontsSpec>,
        #[serde(default)]
        library_fonts: Option<BrandFontsSpec>,
        /// Full ExportProfile driving the bulk artifact for its format
        /// (print controls: bleed, marks, proof, imposition, CMYK, raster
        /// scale). Replaces the built-in default profile of the same
        /// format; other formats in `export_formats` keep their defaults.
        /// Malformed profiles fail loudly (`profile.invalid`).
        #[serde(default)]
        export_profile: Option<Value>,
    },
    BuildInfo,
    WebNewDoc {
        document_id: String,
        title: String,
        #[serde(default)]
        brand_kit_ref: Option<Value>,
    },
    WebValidate {
        doc: Value,
        #[serde(default)]
        brand_kit: Option<Value>,
    },
    WebIngestHtml {
        doc: Value,
        page_id: String,
        html: String,
        #[serde(default)]
        custom_css: Option<String>,
        #[serde(default)]
        brand_kit: Option<Value>,
    },
    WebApplyOps {
        doc: Value,
        operations: Vec<Value>,
    },
    WebRender {
        doc: Value,
        page_id: String,
        mode: String,
        #[serde(default)]
        asset_base_url: Option<String>,
        #[serde(default)]
        tailwind_runtime_src: Option<String>,
        #[serde(default)]
        bridge_script: Option<String>,
        #[serde(default)]
        custom_component_runtimes:
            std::collections::BTreeMap<String, lumen_web::CustomComponentRuntimeFrame>,
        #[serde(default)]
        brand_kit: Option<Value>,
        /// Pre-built @font-face CSS (the API owns font-serving URLs); folded
        /// into the theme base layer so kit typography renders everywhere.
        #[serde(default)]
        font_face_css: Option<String>,
        /// API-resolved fragment artifacts keyed by `frag_<16 hex>` id
        /// (clone-fidelity F1.3). An unresolved id renders the placeholder.
        #[serde(default)]
        fragments: std::collections::BTreeMap<String, lumen_web::FragmentContent>,
        /// The concatenated, already-scoped CSS of those fragments; folded
        /// into the theme base layer, so a compiled utility outranks it.
        #[serde(default)]
        fragment_css: Option<String>,
    },
    /// Parse a constrained-HTML fragment against `doc` WITHOUT mutating it:
    /// returns the would-be nodes + roots so callers can compose surgical
    /// RemoveNode/InsertNode batches (scoped edit turns).
    WebIngestFragment {
        doc: Value,
        html: String,
        #[serde(default)]
        brand_kit: Option<Value>,
    },
    /// Derive one account-personalized copy of `doc`. Pure (doc → doc, no
    /// render, no I/O): returns the derived doc, diagnostics, and a coverage
    /// report. An error-level diagnostic rejects the derive atomically (no
    /// `web_doc` on the response — the template is never mutated).
    WebDerive {
        doc: Value,
        #[serde(default)]
        values: std::collections::BTreeMap<String, Value>,
        #[serde(default)]
        assets: Vec<Value>,
        new_doc_id: String,
        #[serde(default)]
        new_title: Option<String>,
    },
}

#[derive(Debug, Serialize)]
struct CoreResponse {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    scene: Option<Value>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    diagnostics: Vec<Diagnostic>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<CoreError>,
    #[serde(skip_serializing_if = "Option::is_none")]
    applied_operations: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    preflight: Option<PreflightSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_kit: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_summary: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_generation: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_compatibility: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    geometry: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    operations: Option<Vec<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    edit: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    dsl: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    export: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    asset: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    instance: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    web_doc: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    html: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    inverse_operations: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    web_fragment: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    web_theme: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    coverage: Option<Value>,
    build_info: Option<Value>,
}

#[derive(Debug, Serialize)]
struct CoreError {
    code: String,
    message: String,
}

#[derive(Debug, Serialize)]
struct PreflightSummary {
    has_errors: bool,
    brand_ref_operations: Vec<Value>,
    token_operations: Vec<Value>,
    layout_operations: Vec<Value>,
}

fn main() {
    let start = Instant::now();
    let response = match read_request() {
        Ok(request) => {
            let action = request.action_name();
            helper_log(
                "core_helper_started",
                "info",
                Some(action),
                request_log_fields(&request),
            );
            let response = match handle_request(request) {
                Ok(response) => response,
                Err(error) => CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: Vec::new(),
                    error: Some(error),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                },
            };
            helper_log(
                "core_helper_completed",
                if response.ok { "info" } else { "warning" },
                Some(action),
                response_log_fields(&response, start),
            );
            response
        }
        Err(error) => {
            helper_log(
                "core_helper_completed",
                "error",
                None,
                json!({
                    "ok": false,
                    "duration_ms": elapsed_ms(start),
                    "diagnostic_count": 0,
                    "error_code": error.code.as_str(),
                }),
            );
            CoreResponse {
                ok: false,
                scene: None,
                diagnostics: Vec::new(),
                error: Some(error),
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            }
        }
    };

    println!(
        "{}",
        serde_json::to_string(&response).expect("helper response should serialize")
    );
}

impl CoreRequest {
    fn action_name(&self) -> &'static str {
        match self {
            CoreRequest::NewScene { .. } => "new_scene",
            CoreRequest::ValidateScene { .. } => "validate_scene",
            CoreRequest::ApplyOperations { .. } => "apply_operations",
            CoreRequest::ApplyStructuredEdit { .. } => "apply_structured_edit",
            CoreRequest::CompileDslIntoScene { .. } => "compile_dsl_into_scene",
            CoreRequest::PreflightScene { .. } => "preflight_scene",
            CoreRequest::ExportPreview { .. } => "export_preview",
            CoreRequest::IngestAsset { .. } => "ingest_asset",
            CoreRequest::GenerateQr { .. } => "generate_qr",
            CoreRequest::GenerateAsset { .. } => "generate_asset",
            CoreRequest::FinalizeTemplate { .. } => "finalize_template",
            CoreRequest::PlatformDefaultBrandKit => "platform_default_brand_kit",
            CoreRequest::ValidateBrandKit { .. } => "validate_brand_kit",
            CoreRequest::CompileStylesBrandKit { .. } => "compile_styles_brand_kit",
            CoreRequest::GenerateBrandKit { .. } => "generate_brand_kit",
            CoreRequest::SummarizeBrandKit { .. } => "summarize_brand_kit",
            CoreRequest::ValidateSceneBrandGovernance { .. } => "validate_scene_brand_governance",
            CoreRequest::CompareBrandKitCompatibility { .. } => "compare_brand_kit_compatibility",
            CoreRequest::LayoutGeometry { .. } => "layout_geometry",
            CoreRequest::ValidateBindingSet { .. } => "validate_binding_set",
            CoreRequest::DeriveInstance { .. } => "derive_instance",
            CoreRequest::BuildInfo => "build_info",
            CoreRequest::WebNewDoc { .. } => "web_new_doc",
            CoreRequest::WebValidate { .. } => "web_validate",
            CoreRequest::WebIngestHtml { .. } => "web_ingest_html",
            CoreRequest::WebApplyOps { .. } => "web_apply_ops",
            CoreRequest::WebRender { .. } => "web_render",
            CoreRequest::WebIngestFragment { .. } => "web_ingest_fragment",
            CoreRequest::WebDerive { .. } => "web_derive",
        }
    }
}

fn request_log_fields(request: &CoreRequest) -> Value {
    match request {
        CoreRequest::NewScene {
            artifact_type,
            medium,
            ..
        } => json!({
            "has_artifact_type": artifact_type.is_some(),
            "has_medium": medium.is_some(),
        }),
        CoreRequest::ValidateScene { .. } => json!({}),
        CoreRequest::ApplyOperations { operations, .. } => json!({
            "operation_count": operations.len(),
        }),
        CoreRequest::ApplyStructuredEdit { edit, .. } => json!({
            "edit_kind": edit.kind(),
        }),
        CoreRequest::CompileDslIntoScene {
            source,
            dsl_session,
            ..
        } => json!({
            "source_line_count": source.lines().count(),
            "has_dsl_session": dsl_session.is_some(),
        }),
        CoreRequest::PreflightScene {
            brand_kit, mode, ..
        } => json!({
            "has_brand_kit": brand_kit.is_some(),
            "has_mode": mode.is_some(),
        }),
        CoreRequest::ExportPreview {
            format,
            page_ids,
            profile,
            asset_store_root,
            ..
        } => json!({
            "format": format,
            "page_id_count": page_ids.len(),
            "has_profile": profile.is_some(),
            "has_asset_store_root": asset_store_root.is_some(),
        }),
        CoreRequest::IngestAsset {
            bytes_base64,
            declared_mime_type,
            kind,
            ..
        } => json!({
            "base64_length": bytes_base64.len(),
            "declared_mime_type": declared_mime_type,
            "has_kind": kind.is_some(),
        }),
        CoreRequest::GenerateQr {
            data,
            ec_level,
            print,
            target_width_mm,
            ..
        } => json!({
            "data_length": data.len(),
            "ec_level": ec_level,
            "print": print,
            "has_target_width_mm": target_width_mm.is_some(),
        }),
        CoreRequest::GenerateAsset { provider, .. } => json!({
            "provider": provider,
        }),
        CoreRequest::FinalizeTemplate { .. } => json!({}),
        CoreRequest::PlatformDefaultBrandKit => json!({}),
        CoreRequest::ValidateBrandKit { product_ready, .. } => json!({
            "product_ready": product_ready,
        }),
        CoreRequest::CompileStylesBrandKit {
            source,
            brand_kit_id,
            version,
            ..
        } => json!({
            "source_line_count": source.lines().count(),
            "brand_kit_id": brand_kit_id,
            "version": version,
        }),
        CoreRequest::GenerateBrandKit { .. } => json!({}),
        CoreRequest::SummarizeBrandKit { .. } => json!({}),
        CoreRequest::ValidateSceneBrandGovernance { strictness, .. } => json!({
            "strictness": strictness,
        }),
        CoreRequest::CompareBrandKitCompatibility { .. } => json!({}),
        CoreRequest::LayoutGeometry { .. } => json!({}),
        CoreRequest::ValidateBindingSet { .. } => json!({}),
        CoreRequest::DeriveInstance {
            asset_records,
            store_root,
            export_formats,
            ..
        } => json!({
            "asset_record_count": asset_records.len(),
            "has_store_root": store_root.is_some(),
            "export_formats": export_formats,
        }),
        CoreRequest::BuildInfo => json!({}),
        CoreRequest::WebNewDoc { brand_kit_ref, .. } => json!({
            "has_brand_kit_ref": brand_kit_ref.is_some(),
        }),
        CoreRequest::WebValidate { brand_kit, .. } => json!({
            "has_brand_kit": brand_kit.is_some(),
        }),
        CoreRequest::WebIngestHtml {
            html,
            custom_css,
            brand_kit,
            ..
        } => json!({
            "html_bytes": html.len(),
            "has_custom_css": custom_css.is_some(),
            "has_brand_kit": brand_kit.is_some(),
        }),
        CoreRequest::WebApplyOps { operations, .. } => json!({
            "operation_count": operations.len(),
        }),
        CoreRequest::WebRender {
            mode, brand_kit, ..
        } => json!({
            "mode": mode,
            "has_brand_kit": brand_kit.is_some(),
        }),
        CoreRequest::WebIngestFragment { html, brand_kit, .. } => json!({
            "html_bytes": html.len(),
            "has_brand_kit": brand_kit.is_some(),
        }),
        CoreRequest::WebDerive { values, assets, .. } => json!({
            "value_count": values.len(),
            "asset_count": assets.len(),
        }),
    }
}

fn response_log_fields(response: &CoreResponse, start: Instant) -> Value {
    json!({
        "ok": response.ok,
        "duration_ms": elapsed_ms(start),
        "diagnostic_count": response.diagnostics.len(),
        "has_error_diagnostics": has_error(&response.diagnostics),
        "applied_operations": response.applied_operations,
        "has_scene": response.scene.is_some(),
        "has_geometry": response.geometry.is_some(),
        "artifact_count": export_artifact_count(response.export.as_ref()),
        "error_code": response.error.as_ref().map(|error| error.code.as_str()),
    })
}

fn export_artifact_count(export: Option<&Value>) -> usize {
    export
        .and_then(|export| export.get("artifacts"))
        .and_then(Value::as_array)
        .map_or(0, Vec::len)
}

fn elapsed_ms(start: Instant) -> f64 {
    let elapsed = start.elapsed();
    (elapsed.as_secs_f64() * 1000.0 * 1000.0).round() / 1000.0
}

fn helper_log(event: &str, level: &str, action: Option<&str>, fields: Value) {
    if !helper_logging_enabled() {
        return;
    }
    let mut payload = serde_json::Map::new();
    payload.insert("source".to_owned(), json!("lumen-api-helper"));
    payload.insert("event".to_owned(), json!(event));
    payload.insert("level".to_owned(), json!(level));
    if let Some(action) = action {
        payload.insert("action".to_owned(), json!(action));
    }
    if let Ok(request_id) = env::var("LUMEN_REQUEST_ID") {
        if !request_id.is_empty() {
            payload.insert("request_id".to_owned(), json!(request_id));
        }
    }
    if let Ok(helper_call_id) = env::var("LUMEN_CORE_CALL_ID") {
        if !helper_call_id.is_empty() {
            payload.insert("helper_call_id".to_owned(), json!(helper_call_id));
        }
    }
    if let Some(fields) = fields.as_object() {
        for (key, value) in fields {
            payload.insert(key.clone(), value.clone());
        }
    }
    if let Ok(line) = serde_json::to_string(&Value::Object(payload)) {
        eprintln!("{line}");
    }
}

fn helper_logging_enabled() -> bool {
    env::var("LUMEN_CORE_HELPER_LOG").is_ok_and(|value| value != "0")
}

fn error_response(error: CoreError, diagnostics: Vec<Diagnostic>) -> CoreResponse {
    CoreResponse {
        ok: false,
        scene: None,
        diagnostics,
        error: Some(error),
        applied_operations: None,
        preflight: None,
        brand_kit: None,
        brand_summary: None,
        brand_generation: None,
        brand_compatibility: None,
        geometry: None,
        operations: None,
        edit: None,
        dsl: None,
        export: None,
        asset: None,
        instance: None,
        web_doc: None,
        html: None,
        inverse_operations: None,
        web_fragment: None,
        web_theme: None,
        coverage: None,
        build_info: None,
    }
}

/// Enforce a declared edit scope before mutation. Strict violations and
/// unresolvable declared targets fail closed with an error response; in
/// advisory mode violations become warning diagnostics that ride along with
/// the applied batch.
fn check_scope(
    scene: &Scene,
    operations: &[Operation],
    scope: Option<&EditScope>,
) -> Result<Vec<Diagnostic>, Box<CoreResponse>> {
    let Some(scope) = scope else {
        return Ok(Vec::new());
    };
    let violations = match batch_scope_violations(scene, operations, &scope.allowed) {
        Ok(violations) => violations,
        Err(error) => {
            return Err(Box::new(error_response(
                core_error(error.kind.code(), error.message.clone()),
                vec![error.diagnostic()],
            )));
        }
    };
    if violations.is_empty() {
        return Ok(Vec::new());
    }
    match scope.mode {
        EditScopeMode::Strict => Err(Box::new(error_response(
            core_error(
                "edit.scope_violation",
                format!(
                    "{} operation(s) touch targets outside the declared scope",
                    violations.len()
                ),
            ),
            violations.iter().map(ScopeViolation::diagnostic).collect(),
        ))),
        EditScopeMode::Advisory => Ok(violations
            .iter()
            .map(ScopeViolation::advisory_diagnostic)
            .collect()),
    }
}

fn read_request() -> Result<CoreRequest, CoreError> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|error| core_error("helper.stdin", error.to_string()))?;
    serde_json::from_str(&input).map_err(|error| core_error("helper.request", error.to_string()))
}

fn handle_request(request: CoreRequest) -> Result<CoreResponse, CoreError> {
    match request {
        CoreRequest::NewScene {
            document_id,
            title,
            artifact_type,
            medium,
        } => {
            let mut scene = Scene::new(DocumentId::from(document_id), title);
            scene.meta.artifact_type = artifact_type;
            scene.meta.medium = medium
                .map(serde_json::from_value::<Medium>)
                .transpose()
                .map_err(|error| core_error("helper.medium", error.to_string()))?;
            Ok(ok_scene(scene, Vec::new(), None))
        }
        CoreRequest::ValidateScene { scene } => {
            let scene = parse_scene(scene)?;
            let diagnostics = validate_scene(&scene);
            Ok(ok_scene(scene, diagnostics, None))
        }
        CoreRequest::ApplyOperations {
            scene,
            operations,
            scope,
        } => {
            let mut scene = parse_scene(scene)?;
            let operations = parse_operations(operations)?;
            let scope_diagnostics = match check_scope(&scene, &operations, scope.as_ref()) {
                Ok(diagnostics) => diagnostics,
                Err(response) => return Ok(*response),
            };
            let inverse_operations = scene
                .invert_operations(&operations)
                .ok()
                .flatten()
                .map(values)
                .transpose()?;
            match scene.apply_operations_checked(operations) {
                Ok(report) => {
                    let mut response =
                        ok_scene(scene, report.diagnostics, Some(report.applied_operations));
                    response.diagnostics.extend(scope_diagnostics);
                    response.edit = Some(json!({
                        "kind": "apply_operations",
                        "inverse_operations": inverse_operations,
                    }));
                    Ok(response)
                }
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::ApplyStructuredEdit {
            scene,
            edit,
            scope,
            brand_kit,
            mode,
        } => {
            let mut scene = parse_scene(scene)?;
            let brand_kit = brand_kit.map(parse_brand_kit).transpose()?;
            let options = edit_token_options(mode)?;
            let context = brand_kit.as_ref().map(|brand_kit| TextEditContext {
                brand_kit,
                options: &options,
            });
            let batch = build_structured_edit_batch_with_text_context(&scene, &edit, context)
                .map_err(|error| CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: vec![error.diagnostic()],
                    error: Some(core_error(error.kind.code(), error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: Some(to_value(&edit).unwrap_or_else(|_| json!({"kind": edit.kind()}))),
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                });
            let batch = match batch {
                Ok(batch) => batch,
                Err(response) => return Ok(response),
            };
            let operations = batch.operations.clone();
            let scope_diagnostics = match check_scope(&scene, &operations, scope.as_ref()) {
                Ok(diagnostics) => diagnostics,
                Err(mut response) => {
                    response.edit = Some(json!({
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                    }));
                    return Ok(*response);
                }
            };
            match batch.apply_checked(&mut scene) {
                Ok(report) => Ok(CoreResponse {
                    ok: true,
                    scene: Some(to_value(scene)?),
                    diagnostics: {
                        let mut diagnostics = report.diagnostics;
                        diagnostics.extend(scope_diagnostics);
                        diagnostics
                    },
                    error: None,
                    applied_operations: Some(report.applied_operations),
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: Some(values(operations)?),
                    edit: Some(json!({
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                        "inverse_operations": batch.inverse_operations,
                        "lineage": batch.lineage,
                    })),
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: vec![error.diagnostic()],
                    error: Some(core_error(error.kind.code(), error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: Some(values(operations)?),
                    edit: Some(json!({
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                        "inverse_operations": batch.inverse_operations,
                        "lineage": batch.lineage,
                    })),
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::CompileDslIntoScene {
            scene,
            source,
            dsl_session,
            protected_node_ids,
            brand_kit,
            mode,
        } => {
            let mut scene = parse_scene(scene)?;
            let brand_kit = brand_kit.map(parse_brand_kit).transpose()?;
            let options = edit_token_options(mode)?;
            let context = brand_kit.as_ref().map(|brand_kit| TextEditContext {
                brand_kit,
                options: &options,
            });
            let session = dsl_session
                .map(serde_json::from_value::<DslCompileSessionSnapshot>)
                .transpose()
                .map_err(|error| core_error("helper.dsl_session", error.to_string()))?;
            let protected: std::collections::BTreeSet<NodeId> =
                protected_node_ids.into_iter().map(NodeId::from).collect();
            let result = compile_dsl_into_scene_with_text_context(
                &source, &mut scene, session, protected, context,
            );
            let applied_operations = result
                .operation_report
                .as_ref()
                .map(|report| report.applied_operations);
            Ok(CoreResponse {
                ok: true,
                scene: Some(to_value(scene)?),
                diagnostics: Vec::new(),
                error: None,
                applied_operations,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: Some(json!({
                    "compile_output": dsl_compile_output_value(&result.compile_output)?,
                    "operation_report": operation_report_value(&result.operation_report),
                    "operation_error": operation_error_value(&result.operation_error),
                    "session_snapshot": to_value(result.session_snapshot)?,
                })),
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::PreflightScene {
            scene,
            brand_kit,
            mode,
            brand_fonts,
            library_fonts,
        } => {
            let family_scan = match &brand_kit {
                Some(kit) => format!("{scene}{kit}"),
                None => scene.to_string(),
            };
            let scene = parse_scene(scene)?;
            let brand_kit = brand_kit.map(parse_brand_kit).transpose()?;
            let (fonts, font_diagnostics) =
                load_request_fonts(brand_fonts.as_ref(), library_fonts.as_ref(), &family_scan);
            let mut options = PreflightOptions::default();
            options.layout.measurer = Some(server_measurer_with(fonts));
            if let Some(mode) = mode {
                options.token_resolution.mode = parse_brand_mode(mode)?;
            }
            let mut result = preflight_scene(scene, brand_kit.as_ref(), options);
            result.diagnostics.extend(font_diagnostics);
            let summary = PreflightSummary {
                has_errors: result.has_errors(),
                brand_ref_operations: values(result.brand_ref_operations)?,
                token_operations: values(result.token_operations)?,
                layout_operations: values(result.layout_operations)?,
            };
            Ok(CoreResponse {
                ok: true,
                scene: Some(to_value(result.scene)?),
                diagnostics: result.diagnostics,
                error: None,
                applied_operations: None,
                preflight: Some(summary),
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::ExportPreview {
            scene,
            format,
            page_ids,
            profile,
            asset_store_root,
            brand_fonts,
            library_fonts,
        } => {
            let family_scan = scene.to_string();
            let scene = parse_scene(scene)?;
            let profile = match profile {
                Some(profile) => {
                    serde_json::from_value::<ExportProfile>(profile).map_err(|error| {
                        core_error(
                            "profile.invalid",
                            format!("invalid export profile payload: {error}"),
                        )
                    })?
                }
                None => ExportProfile {
                    name: "agent_critique_preview".to_owned(),
                    format,
                    pdf_intent: Some(PdfIntent::Preview),
                    raster: Some(RasterScale {
                        scale: 1.0,
                        dpi: Some(96),
                    }),
                    include_bleed: false,
                    embed_fonts: true,
                    include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
            };
            let request = ExportRequest {
                profile,
                page_ids: page_ids.into_iter().map(PageId::from).collect(),
                purpose: ExportPurpose::AgentCritique,
            };
            let (fonts, font_diagnostics) =
                load_request_fonts(brand_fonts.as_ref(), library_fonts.as_ref(), &family_scan);
            let adapter = server_export_adapter_with(
                match asset_store_root {
                    Some(root) => {
                        LumenExportAdapter::with_resolver(Arc::new(StoreBackedResolver::new(root)))
                    }
                    None => LumenExportAdapter::new(),
                },
                fonts,
            );
            match adapter.export(&scene, &request) {
                Ok(result) => Ok(CoreResponse {
                    ok: true,
                    scene: None,
                    diagnostics: {
                        let mut diagnostics = result.diagnostics.clone();
                        diagnostics.extend(font_diagnostics);
                        diagnostics
                    },
                    error: None,
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: Some(to_value(result)?),
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::IngestAsset {
            store_root,
            bytes_base64,
            asset_id,
            label,
            declared_mime_type,
            filename,
            kind,
            uploaded_by,
            license,
            provenance,
            source,
            tags,
            max_bytes,
        } => {
            let bytes = BASE64
                .decode(bytes_base64.as_bytes())
                .map_err(|error| core_error("helper.asset_bytes", error.to_string()))?;
            let kind_hint = kind
                .map(serde_json::from_value::<AssetKind>)
                .transpose()
                .map_err(|error| core_error("helper.asset_kind", error.to_string()))?;
            let license = license
                .map(serde_json::from_value::<AssetLicense>)
                .transpose()
                .map_err(|error| core_error("helper.asset_license", error.to_string()))?;
            let provenance = provenance
                .map(serde_json::from_value::<AssetProvenance>)
                .transpose()
                .map_err(|error| core_error("helper.asset_provenance", error.to_string()))?;
            let source = source
                .map(serde_json::from_value::<AssetSource>)
                .transpose()
                .map_err(|error| core_error("helper.asset_source", error.to_string()))?;

            let ingest_request = IngestRequest {
                bytes: &bytes,
                declared_mime: declared_mime_type.as_deref(),
                filename: filename.as_deref(),
                kind_hint,
                max_bytes: max_bytes.unwrap_or(DEFAULT_MAX_BYTES),
            };
            let output = match lumen_assets::ingest(&ingest_request) {
                Ok(output) => output,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };

            let store = LocalAssetStore::new(&store_root);
            let stored = store
                .put(&output.bytes)
                .map_err(|error| core_error(error.code, error.message))?;

            let thumbnail = match &output.thumbnail {
                Some(artifact) => {
                    let stored_thumbnail = store
                        .put(&artifact.bytes)
                        .map_err(|error| core_error(error.code, error.message))?;
                    Some(AssetThumbnail {
                        location: AssetLocation {
                            provider: LOCAL_STORE_PROVIDER.to_owned(),
                            opaque_ref: stored_thumbnail.relative_path,
                            url: None,
                        },
                        mime_type: artifact.mime_type.clone(),
                        pixel_width: Some(artifact.pixel_width),
                        pixel_height: Some(artifact.pixel_height),
                    })
                }
                // A vector scales for the canvas but has no pixels for anything
                // that can only READ pixels — the agent's `view("asset:<id>")`,
                // the describe stage, the vision APIs — so every logo in a kit
                // was invisible to the trio deciding whether to place it (W1.2).
                // `lumen-assets` cannot rasterize (it is deliberately light: the
                // `image` crate only, no Skia), so the composition point that
                // has both crates does it, off the SANITIZED bytes, under the
                // same thumbnail bounds the raster path uses.
                None if output.sniffed_mime == "image/svg+xml" => {
                    // Rasterize, then store. EITHER step may decline — Skia
                    // will not parse the bytes, or paints nothing from them, or
                    // the store cannot commit the PNG — and neither may fail
                    // the ingest: deriving a thumbnail has never been fatal.
                    let rasterized = lumen_skia::rasterize_svg_thumbnail(
                        &output.bytes,
                        lumen_assets::THUMBNAIL_MAX_DIMENSION,
                        lumen_assets::THUMBNAIL_MIN_SHORT_DIMENSION,
                    )
                    .and_then(|(png, pixel_width, pixel_height)| {
                        let stored_thumbnail = store.put(&png).ok()?;
                        Some(AssetThumbnail {
                            location: AssetLocation {
                                provider: LOCAL_STORE_PROVIDER.to_owned(),
                                opaque_ref: stored_thumbnail.relative_path,
                                url: None,
                            },
                            mime_type: "image/png".to_owned(),
                            pixel_width: Some(pixel_width),
                            pixel_height: Some(pixel_height),
                        })
                    });
                    // Fall back to the legacy self-referential thumbnail — the
                    // vector is its own thumbnail for the canvas — silently:
                    // this slice adds no diagnostic, and the Python resolver
                    // degrades a non-raster thumbnail to the honest "no raster
                    // preview" message rather than a broken decode.
                    Some(rasterized.unwrap_or_else(|| AssetThumbnail {
                        location: AssetLocation {
                            provider: LOCAL_STORE_PROVIDER.to_owned(),
                            opaque_ref: stored.relative_path.clone(),
                            url: None,
                        },
                        mime_type: output.sniffed_mime.clone(),
                        pixel_width: None,
                        pixel_height: None,
                    }))
                }
                None => None,
            };

            let record = AssetRecord {
                id: AssetId::from(asset_id),
                label,
                kind: output.kind.clone(),
                status: AssetStatus::Ready,
                source: source.unwrap_or(AssetSource::Uploaded {
                    asset_id: None,
                    filename: filename.clone(),
                    uploaded_by,
                }),
                media: AssetMediaMetadata {
                    mime_type: Some(output.sniffed_mime.clone()),
                    filename,
                    byte_length: Some(stored.byte_length),
                    digest: Some(AssetDigest {
                        algorithm: "sha256".to_owned(),
                        value: stored.digest_value.clone(),
                    }),
                    location: Some(AssetLocation {
                        provider: LOCAL_STORE_PROVIDER.to_owned(),
                        opaque_ref: stored.relative_path.clone(),
                        url: None,
                    }),
                    thumbnail,
                },
                raster: output.raster.clone(),
                vector: output.vector.clone(),
                font: None,
                logo: None,
                license,
                provenance: provenance.unwrap_or_default(),
                tags: tags.unwrap_or_default(),
            };

            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: output.diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: Some(json!({
                    "record": to_value(record)?,
                    "deduplicated": stored.deduplicated,
                    "sniffed_mime": output.sniffed_mime,
                    "relative_path": stored.relative_path,
                    "digest_value": stored.digest_value,
                    "byte_length": stored.byte_length,
                })),
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::GenerateQr {
            store_root,
            data,
            asset_id,
            label,
            ec_level,
            print,
            target_width_mm,
        } => {
            let ec_level = ec_level
                .as_deref()
                .map(lumen_assets::QrEcLevel::parse)
                .transpose()
                .map_err(|message| core_error("helper.qr_ec_level", message))?;
            let qr_request = lumen_assets::QrRequest {
                data: data.clone(),
                ec_level,
                print,
                target_width_mm,
            };
            let output = match lumen_assets::generate_qr(&qr_request) {
                Ok(output) => output,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };
            let qr_diagnostics = output.diagnostics.clone();

            // Normalize through the shared ingest path (sanitize, store,
            // record assembly) so generated assets are first-class assets.
            let mut response = handle_request(CoreRequest::IngestAsset {
                store_root,
                bytes_base64: BASE64.encode(output.svg.as_bytes()),
                asset_id: asset_id.clone(),
                label: label.unwrap_or_else(|| format!("QR code ({data})")),
                declared_mime_type: Some("image/svg+xml".to_owned()),
                filename: Some(format!("{asset_id}.svg")),
                kind: Some(json!("vector")),
                uploaded_by: None,
                license: Some(json!({
                    "name": "generated_qr",
                    "allow_export": true,
                    "allow_modification": true,
                    "allow_embedding": true,
                    "allow_subsetting": true,
                    "source_url": null,
                    "restrictions": []
                })),
                provenance: Some(json!({
                    "created_by": "qr-v1",
                    "created_at": null,
                    "source_label": "generated:qr",
                    "confidence": 1.0,
                    "notes": [format!(
                        "deterministic QR encode: {} data bytes, ec level {}, {} modules",
                        data.len(),
                        output.ec_level.as_str(),
                        output.module_count
                    )]
                })),
                source: Some(json!({
                    "kind": "generated",
                    "request_id": asset_id,
                    "model": "qr-v1"
                })),
                tags: Some(vec!["qr".to_owned(), "generated".to_owned()]),
                max_bytes: None,
            })?;

            if response.ok {
                if let Some(asset) = response.asset.as_mut() {
                    asset["qr"] = json!({
                        "ec_level": output.ec_level.as_str(),
                        "module_count": output.module_count,
                        "quiet_zone_modules": output.quiet_zone_modules,
                    });
                }
                response.diagnostics.extend(qr_diagnostics);
            }
            Ok(response)
        }
        CoreRequest::GenerateAsset {
            store_root,
            provider,
            request,
            asset_id,
            label,
        } => {
            let generation_request =
                serde_json::from_value::<lumen_core::AssetGenerationRequest>(request)
                    .map_err(|error| core_error("helper.generation_request", error.to_string()))?;
            let registry = lumen_assets::ProviderRegistry::with_default_providers();
            let artifact = match registry.generate(&provider, &generation_request) {
                Ok(artifact) => artifact,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };
            let provider_diagnostics = artifact.diagnostics.clone();
            let provider_metadata = artifact.provider_metadata.clone();

            let mut response = handle_request(CoreRequest::IngestAsset {
                store_root,
                bytes_base64: BASE64.encode(&artifact.bytes),
                asset_id: asset_id.clone(),
                label: label.unwrap_or_else(|| format!("Generated asset ({provider})")),
                declared_mime_type: Some(artifact.mime_type.clone()),
                filename: None,
                kind: Some(to_value(&artifact.kind)?),
                uploaded_by: None,
                license: Some(to_value(&artifact.license)?),
                provenance: Some(json!({
                    "created_by": provider,
                    "created_at": null,
                    "source_label": format!("generated:{provider}"),
                    "confidence": 1.0,
                    "notes": artifact.provenance_notes,
                })),
                source: Some(json!({
                    "kind": "generated",
                    "request_id": generation_request.request_id,
                    "model": provider,
                })),
                tags: Some(vec!["generated".to_owned()]),
                max_bytes: None,
            })?;

            if response.ok {
                if let Some(asset) = response.asset.as_mut() {
                    asset["provider"] = json!({
                        "id": provider,
                        "metadata": provider_metadata,
                    });
                }
                response.diagnostics.extend(provider_diagnostics);
            }
            Ok(response)
        }
        CoreRequest::FinalizeTemplate {
            scene,
            template_revision_id,
        } => {
            let mut scene = parse_scene(scene)?;
            let operation = Operation::FinalizeTemplate {
                template_revision_id: TemplateRevisionId::from(template_revision_id),
            };
            match scene.apply_operation_checked(operation) {
                Ok(report) => Ok(ok_scene(
                    scene,
                    report.diagnostics,
                    Some(report.applied_operations),
                )),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::PlatformDefaultBrandKit => {
            let brand_kit = platform_default_brand_kit().map_err(|error| {
                core_error("helper.platform_default_brand_kit", error.to_string())
            })?;
            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: Vec::new(),
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::ValidateBrandKit {
            brand_kit,
            product_ready,
        } => {
            let brand_kit = parse_brand_kit(brand_kit)?;
            let diagnostics = if product_ready {
                validate_brand_kit_product_ready(&brand_kit)
            } else {
                validate_brand_kit(&brand_kit)
            };
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: None,
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::CompileStylesBrandKit {
            source,
            brand_kit_id,
            version,
            name,
        } => {
            match compile_styles_brand_kit(&source, BrandKitId::from(brand_kit_id), version, name) {
                Ok(brand_kit) => {
                    let summary = summarize_brand_kit_for_authoring(&brand_kit);
                    Ok(CoreResponse {
                        ok: true,
                        scene: None,
                        diagnostics: Vec::new(),
                        error: None,
                        applied_operations: None,
                        preflight: None,
                        brand_kit: Some(to_value(&brand_kit)?),
                        brand_summary: Some(to_value(summary)?),
                        brand_generation: None,
                        brand_compatibility: None,
                        geometry: None,
                        operations: None,
                        edit: None,
                        dsl: None,
                        export: None,
                        asset: None,
                        instance: None,
                        web_doc: None,
                        html: None,
                        inverse_operations: None,
                        web_fragment: None,
                        web_theme: None,
                        coverage: None,
                        build_info: None,
                    })
                }
                Err(diagnostics) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics,
                    error: Some(core_error(
                        "helper.brand_styles",
                        "styles source did not compile into a product-ready Brand Kit",
                    )),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                    asset: None,
                    instance: None,
                    web_doc: None,
                    html: None,
                    inverse_operations: None,
                    web_fragment: None,
                    web_theme: None,
                    coverage: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::GenerateBrandKit { seed } => {
            let seed = parse_brand_seed(seed)?;
            let report = generate_brand_kit(&seed);
            let diagnostics = report.diagnostics.clone();
            let brand_kit = report.brand_kit.as_ref().map(to_value).transpose()?;
            let brand_summary = report
                .brand_kit
                .as_ref()
                .map(summarize_brand_kit_for_authoring)
                .map(to_value)
                .transpose()?;
            let ok = report.brand_kit.is_some() && !has_error(&diagnostics);
            Ok(CoreResponse {
                ok,
                scene: None,
                diagnostics,
                error: if ok {
                    None
                } else {
                    Some(core_error(
                        "helper.brand_seed",
                        "brand seed did not generate a usable Brand Kit",
                    ))
                },
                applied_operations: None,
                preflight: None,
                brand_kit,
                brand_summary,
                brand_generation: Some(to_value(report)?),
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::SummarizeBrandKit { brand_kit } => {
            let brand_kit = parse_brand_kit(brand_kit)?;
            let summary = summarize_brand_kit_for_authoring(&brand_kit);
            Ok(CoreResponse {
                ok: summary.product_ready,
                scene: None,
                diagnostics: summary.diagnostics.clone(),
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: Some(to_value(summary)?),
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::ValidateSceneBrandGovernance {
            scene,
            brand_kit,
            strictness,
        } => {
            let scene = parse_scene(scene)?;
            let brand_kit = parse_brand_kit(brand_kit)?;
            let diagnostics = validate_scene_brand_governance(&scene, &brand_kit, strictness);
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: Some(to_value(scene)?),
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::CompareBrandKitCompatibility { from, to } => {
            let from = parse_brand_kit(from)?;
            let to = parse_brand_kit(to)?;
            let report = compare_brand_kit_compatibility(&from, &to);
            let diagnostics = report.diagnostics.clone();
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: None,
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: Some(to_value(report)?),
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::LayoutGeometry {
            scene,
            brand_fonts,
            library_fonts,
        } => {
            let family_scan = scene.to_string();
            let scene = parse_scene(scene)?;
            let (fonts, font_diagnostics) =
                load_request_fonts(brand_fonts.as_ref(), library_fonts.as_ref(), &family_scan);
            let result = layout_scene(
                &scene,
                lumen_core::LayoutOptions {
                    measurer: Some(server_measurer_with(fonts)),
                    ..Default::default()
                },
            );
            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: {
                    let mut diagnostics = result.diagnostics;
                    diagnostics.extend(font_diagnostics);
                    diagnostics
                },
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: Some(json!(result.geometry)),
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: None,
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::ValidateBindingSet { scene, binding_set } => {
            let scene = parse_scene(scene)?;
            let binding = parse_binding_set(binding_set)?;
            let diagnostics = validate_binding_set(&scene, &binding);
            let ok = !has_error(&diagnostics);
            Ok(CoreResponse {
                ok,
                scene: None,
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: Some(json!({
                    "binding_set_id": binding.binding_set_id,
                    "template_revision_id": binding.template_revision_id,
                    "valid": ok,
                })),
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        CoreRequest::DeriveInstance {
            scene,
            binding_set,
            asset_records,
            store_root,
            export_formats,
            export_dpi,
            brand_fonts,
            library_fonts,
            export_profile,
        } => {
            // The template's families live in the revision scene; binding
            // sets substitute content, never typography — so the scene JSON
            // alone is the family scan.
            let family_scan = scene.to_string();
            let scene = parse_scene(scene)?;
            let binding = parse_binding_set(binding_set)?;
            let export_profile: Option<ExportProfile> = export_profile
                .map(serde_json::from_value)
                .transpose()
                .map_err(|error| {
                    core_error(
                        "profile.invalid",
                        format!("invalid export profile payload: {error}"),
                    )
                })?;
            let (fonts, font_diagnostics) =
                load_request_fonts(brand_fonts.as_ref(), library_fonts.as_ref(), &family_scan);

            let mut assets = DerivationAssets::default();
            for value in asset_records {
                let record: AssetRecord = serde_json::from_value(value)
                    .map_err(|error| core_error("helper.asset_record", error.to_string()))?;
                assets.records.insert(record.id.clone(), record);
            }

            // Refuse early on invalid bindings so providers never execute
            // for inputs that cannot derive.
            let validation = validate_binding_set(&scene, &binding);
            if has_error(&validation) {
                return Ok(error_response(
                    core_error(
                        "instance.binding_invalid",
                        format!(
                            "binding set {} failed validation against the revision snapshot",
                            binding.binding_set_id
                        ),
                    ),
                    validation,
                ));
            }

            // Execute every generated.* spec through the Phase E surfaces
            // (QR through the dedicated deterministic encoder, everything
            // else through the provider registry), normalizing via the
            // shared ingest path. Asset ids are a pure function of
            // (binding_set_id, entry name) so re-derivation is idempotent.
            let mut generated_payloads = serde_json::Map::new();
            for (name, spec) in &binding.generated {
                let Some(store_root) = store_root.clone() else {
                    return Err(core_error(
                        "helper.store_root",
                        "derive_instance with generated entries requires store_root",
                    ));
                };
                let asset_id = deterministic_generated_asset_id(&binding.binding_set_id, name);
                let response = match spec.provider.as_str() {
                    "qr" => {
                        let url = spec
                            .input
                            .url_from
                            .as_deref()
                            .and_then(|path| binding.resolve_link_path(path))
                            .ok_or_else(|| {
                                core_error(
                                    "instance.generated_url",
                                    format!(
                                        "generated entry {name:?}: url_from did not resolve to a link"
                                    ),
                                )
                            })?
                            .to_owned();
                        handle_request(CoreRequest::GenerateQr {
                            store_root,
                            data: url.clone(),
                            asset_id: asset_id.clone(),
                            label: Some(format!("QR code ({url})")),
                            ec_level: spec.input.ec_level.clone(),
                            print: false,
                            target_width_mm: None,
                        })?
                    }
                    provider => handle_request(CoreRequest::GenerateAsset {
                        store_root,
                        provider: provider.to_owned(),
                        request: json!({
                            "request_id": asset_id.clone(),
                            "prompt": spec
                                .input
                                .prompt
                                .clone()
                                .or_else(|| spec
                                    .input
                                    .url_from
                                    .as_deref()
                                    .and_then(|path| binding.resolve_link_path(path))
                                    .map(str::to_owned))
                                .unwrap_or_default(),
                            "output_kind": "raster_image",
                            "target_node_id": null,
                            "target_slot_id": null,
                            "constraints": {
                                "width": null,
                                "height": null,
                                "mime_type": null,
                                "transparent_background": null,
                                "brand_notes": []
                            }
                        }),
                        asset_id: asset_id.clone(),
                        label: None,
                    })?,
                };

                if !response.ok {
                    let mut diagnostics = response.diagnostics;
                    let error = response.error.unwrap_or_else(|| {
                        core_error("instance.generated_failed", "provider execution failed")
                    });
                    return Ok(error_response(
                        core_error(
                            "instance.generated_failed",
                            format!(
                                "generated entry {name:?} (provider {}) failed: {} {}",
                                spec.provider, error.code, error.message
                            ),
                        ),
                        std::mem::take(&mut diagnostics),
                    ));
                }

                let record_value = response
                    .asset
                    .as_ref()
                    .and_then(|asset| asset.get("record"))
                    .cloned()
                    .ok_or_else(|| {
                        core_error(
                            "instance.generated_failed",
                            format!("generated entry {name:?} returned no asset record"),
                        )
                    })?;
                let mut record: AssetRecord = serde_json::from_value(record_value)
                    .map_err(|error| core_error("helper.asset_record", error.to_string()))?;
                // Provenance records which binding set produced this asset.
                record
                    .provenance
                    .notes
                    .push(format!("binding_set:{}", binding.binding_set_id));

                let mut payload = response.asset.clone().unwrap_or_else(|| json!({}));
                payload["record"] = to_value(&record)?;
                payload["provider_id"] = json!(spec.provider);
                generated_payloads.insert(name.clone(), payload);

                assets.generated.insert(name.clone(), record);
            }

            let derived = derive_instance(
                &scene,
                &binding,
                &assets,
                &DeriveOptions {
                    measurer: Some(server_measurer_with(Arc::clone(&fonts))),
                },
            );

            let mut diagnostics = derived.diagnostics.clone();
            diagnostics.extend(font_diagnostics);
            let mut artifacts: Vec<Value> = Vec::new();
            let mut export_skipped = false;
            if !export_formats.is_empty() || export_profile.is_some() {
                if derived.has_errors() {
                    // Failed instances never produce artifacts; the fit
                    // report and diagnostics carry the why.
                    export_skipped = true;
                } else {
                    let Some(store_root) = store_root.clone() else {
                        return Err(core_error(
                            "helper.store_root",
                            "derive_instance with export_formats requires store_root",
                        ));
                    };
                    artifacts = export_instance_artifacts(
                        &derived.scene,
                        &export_formats,
                        export_dpi.unwrap_or(300),
                        export_profile,
                        &store_root,
                        Arc::clone(&fonts),
                        &mut diagnostics,
                    )?;
                }
            }

            Ok(CoreResponse {
                ok: true,
                scene: Some(to_value(&derived.scene)?),
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
                asset: None,
                instance: Some(json!({
                    "binding_set_id": binding.binding_set_id,
                    "template_revision_id": binding.template_revision_id,
                    "has_errors": derived.has_errors(),
                    "audit": to_value(&derived.audit)?,
                    "fit_report": to_value(&derived.fit_report)?,
                    "repair_requests": to_value(&derived.repair_requests)?,
                    "generated": Value::Object(generated_payloads),
                    "artifacts": artifacts,
                    "export_skipped": export_skipped,
                })),
                web_doc: None,
                html: None,
                inverse_operations: None,
                web_fragment: None,
                web_theme: None,
                coverage: None,
                build_info: None,
            })
        }
        // W5 version handshake: the editor compares this against the WASM
        // module's version() and downgrades to server-only mode on any
        // mismatch — never mixed-version optimistic editing.
        CoreRequest::BuildInfo => Ok(CoreResponse {
            ok: true,
            scene: None,
            diagnostics: Vec::new(),
            error: None,
            applied_operations: None,
            preflight: None,
            brand_kit: None,
            brand_summary: None,
            brand_generation: None,
            brand_compatibility: None,
            geometry: None,
            operations: None,
            edit: None,
            dsl: None,
            export: None,
            asset: None,
            instance: None,
            web_doc: None,
            html: None,
            inverse_operations: None,
            web_fragment: None,
            web_theme: None,
            coverage: None,
            build_info: Some(json!({
                "schema_version": lumen_core::SCHEMA_VERSION,
                "engine_commit": env!("LUMEN_ENGINE_COMMIT"),
            })),
        }),
        CoreRequest::WebNewDoc {
            document_id,
            title,
            brand_kit_ref,
        } => {
            let brand_kit_ref = brand_kit_ref
                .map(serde_json::from_value::<lumen_core::BrandKitRef>)
                .transpose()
                .map_err(|error| core_error("helper.brand_kit_ref", error.to_string()))?;
            let doc = lumen_web::WebDoc::new(document_id, title, brand_kit_ref);
            Ok(ok_web(Some(&doc), None, None, None, Vec::new()))
        }
        CoreRequest::WebValidate { doc, brand_kit } => {
            let doc = parse_web_doc(doc)?;
            let briefed = kit_is_briefed(brand_kit.as_ref());
            let (theme, mut diagnostics) = web_theme_for(&doc, brand_kit, None, None)?;
            diagnostics.extend(lumen_web::validate_web_doc(&doc));
            diagnostics.extend(lint_web_doc_classes(&doc, &theme, briefed));
            let mut response = ok_web(Some(&doc), None, None, None, diagnostics);
            // Inspector surface: token pickers list exactly what the lint
            // accepts, from the same compile.
            response.web_theme = Some(web_theme_json(&theme));
            Ok(response)
        }
        CoreRequest::WebIngestHtml {
            doc,
            page_id,
            html,
            custom_css,
            brand_kit,
        } => {
            let mut doc = parse_web_doc(doc)?;
            let briefed = kit_is_briefed(brand_kit.as_ref());
            let (theme, mut diagnostics) = web_theme_for(&doc, brand_kit, None, None)?;
            let outcome = lumen_web::ingest_html_into_page_with(
                &mut doc,
                &lumen_core::PageId::from(page_id),
                &html,
                &theme,
                lumen_web::IngestOptions { briefed },
            );
            let installed = if outcome.has_errors() {
                None
            } else {
                if let Some(css) = custom_css {
                    doc.custom_css = css;
                }
                Some(outcome.nodes.len())
            };
            diagnostics.extend(outcome.diagnostics);
            if installed.is_some() {
                diagnostics.extend(lumen_web::validate_web_doc(&doc));
            }
            Ok(ok_web(Some(&doc), None, None, installed, diagnostics))
        }
        CoreRequest::WebApplyOps { doc, operations } => {
            let mut doc = parse_web_doc(doc)?;
            let operations: Vec<lumen_web::WebOperation> = operations
                .into_iter()
                .map(serde_json::from_value)
                .collect::<Result<_, _>>()
                .map_err(|error| core_error("helper.web_operations", error.to_string()))?;
            // Checked apply: a batch that would leave the document invalid is
            // rejected outright (ok:false + the validation diagnostics) — the
            // mutated doc is never returned, so callers cannot persist it.
            match lumen_web::apply_operations_checked(&mut doc, &operations) {
                Ok((inverses, diagnostics)) => {
                    let count = operations.len();
                    Ok(ok_web(
                        Some(&doc),
                        None,
                        Some(&inverses),
                        Some(count),
                        diagnostics,
                    ))
                }
                Err(error) => Ok(error_response(
                    core_error(error.code, error.message.clone()),
                    error.diagnostics,
                )),
            }
        }
        CoreRequest::WebRender {
            doc,
            page_id,
            mode,
            asset_base_url,
            tailwind_runtime_src,
            bridge_script,
            custom_component_runtimes,
            brand_kit,
            font_face_css,
            fragments,
            fragment_css,
        } => {
            let doc = parse_web_doc(doc)?;
            let (theme, theme_diagnostics) =
                web_theme_for(&doc, brand_kit, font_face_css, fragment_css)?;
            let mode = match mode.as_str() {
                "editor" => lumen_web::RenderMode::Editor,
                "delivery" => lumen_web::RenderMode::Delivery,
                other => {
                    return Err(core_error(
                        "helper.web_render_mode",
                        format!("unknown render mode `{other}` (editor|delivery)"),
                    ))
                }
            };
            let options = lumen_web::RenderOptions {
                mode,
                asset_base_url: asset_base_url.unwrap_or_else(|| "/asset-store".to_owned()),
                tailwind_runtime_src,
                bridge_script,
                custom_component_runtimes,
                fragments,
            };
            let output = lumen_web::render_page(
                &doc,
                &lumen_core::PageId::from(page_id),
                &theme,
                &options,
            )
            .map_err(|diagnostics| {
                let detail = diagnostics
                    .first()
                    .map(|diagnostic| format!("{}: {}", diagnostic.code, diagnostic.message))
                    .unwrap_or_else(|| "render failed".to_owned());
                core_error("web.render", detail)
            })?;
            let mut diagnostics = theme_diagnostics;
            diagnostics.extend(output.diagnostics);
            Ok(ok_web(None, Some(output.html), None, None, diagnostics))
        }
        CoreRequest::WebIngestFragment {
            doc,
            html,
            brand_kit,
        } => {
            let doc = parse_web_doc(doc)?;
            let briefed = kit_is_briefed(brand_kit.as_ref());
            let (theme, mut diagnostics) = web_theme_for(&doc, brand_kit, None, None)?;
            let outcome =
                lumen_web::ingest_html_with(&html, &theme, lumen_web::IngestOptions { briefed });
            // Same asset-reference discipline as the page ingest: a fragment
            // referencing unknown assets must fail loudly, not splice blind.
            for node in &outcome.nodes {
                if let lumen_web::WebNodeKind::Image { asset_id, .. } = &node.kind {
                    if !doc.assets.contains_key(asset_id) {
                        diagnostics.push(
                            Diagnostic::error(
                                lumen_core::Phase::Web,
                                "LUMW0120",
                                format!(
                                    "image node `{}` references unknown asset `{asset_id}`",
                                    node.id
                                ),
                                Some(lumen_core::DiagnosticSubject::Node(node.id.clone())),
                            )
                            .with_hint(
                                "Generate or import the asset first, then reference its id \
                                 via data-asset.",
                            ),
                        );
                    }
                }
            }
            diagnostics.extend(outcome.diagnostics.clone());
            let fragment = json!({
                "nodes": to_value(&outcome.nodes)?,
                "roots": to_value(&outcome.roots)?,
            });
            let mut response = ok_web(None, None, None, None, diagnostics);
            response.web_fragment = Some(fragment);
            Ok(response)
        }
        CoreRequest::WebDerive {
            doc,
            values,
            assets,
            new_doc_id,
            new_title,
        } => {
            let template = parse_web_doc(doc)?;
            let values: std::collections::BTreeMap<String, lumen_web::WebBoundValue> = values
                .into_iter()
                .map(|(key, value)| serde_json::from_value(value).map(|bound| (key, bound)))
                .collect::<Result<_, _>>()
                .map_err(|error| core_error("helper.web_values", error.to_string()))?;
            let assets: Vec<lumen_core::AssetRecord> = assets
                .into_iter()
                .map(serde_json::from_value)
                .collect::<Result<_, _>>()
                .map_err(|error| core_error("helper.web_assets", error.to_string()))?;
            let derived = lumen_web::derive_web_doc(
                &template,
                &values,
                &assets,
                &lumen_web::DeriveWebOptions {
                    new_doc_id,
                    new_title,
                },
            );
            let coverage = to_value(&derived.coverage)?;
            // Atomic gate mirroring the checked apply: an error-level diagnostic
            // rejects the derive and the (invalid) doc is never returned.
            if derived.has_errors() {
                let mut response = error_response(
                    core_error(
                        "web_derive.rejected",
                        "derivation produced an invalid document",
                    ),
                    derived.diagnostics,
                );
                response.coverage = Some(coverage);
                return Ok(response);
            }
            let mut response = ok_web(Some(&derived.doc), None, None, None, derived.diagnostics);
            response.coverage = Some(coverage);
            Ok(response)
        }
    }
}

fn parse_web_doc(value: Value) -> Result<lumen_web::WebDoc, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.web_doc", error.to_string()))
}

/// Compile the web theme from the provided kit JSON (or the platform default
/// when absent) against the document's theme ref (overrides).
fn web_theme_for(
    doc: &lumen_web::WebDoc,
    brand_kit: Option<Value>,
    font_face_css: Option<String>,
    fragment_css: Option<String>,
) -> Result<(lumen_web::WebTheme, Vec<Diagnostic>), CoreError> {
    let kit = brand_kit.map(parse_brand_kit).transpose()?;
    Ok(lumen_web::compile_web_theme(
        kit.as_ref(),
        &doc.theme,
        &lumen_web::WebThemeOptions {
            font_face_css,
            fragment_css,
        },
    ))
}

/// The compiled theme's inspector-facing surface: token map + families, plus
/// the brand-geometry channel the static export compile rebuilds its `@theme`
/// block from. `tokens` stays colors-only — geometry is a separate key so no
/// color consumer (swatch grid, class-lint vocabulary) ever sees it.
fn web_theme_json(theme: &lumen_web::WebTheme) -> Value {
    json!({
        "tokens": theme.tokens,
        "geometry": theme.geometry,
        "utility_css": theme.utility_css,
        "display_family": theme.display_family,
        "body_family": theme.body_family,
    })
}

fn lint_web_doc_classes(
    doc: &lumen_web::WebDoc,
    theme: &lumen_web::WebTheme,
    briefed: bool,
) -> Vec<Diagnostic> {
    let context = lumen_web::ClassLintContext {
        color_tokens: &theme.tokens,
        briefed,
    };
    let mut diagnostics: Vec<Diagnostic> = Vec::new();
    for page in &doc.pages {
        for node in page.nodes.values() {
            // Advice collapses across the whole document walk exactly as it
            // does across an ingest: one line per raw class, not per node.
            lumen_web::extend_deduping_advice(
                &mut diagnostics,
                lumen_web::lint_classes(&node.classes, Some(&node.id), &context),
            );
        }
    }
    diagnostics
}

/// Does the RAW kit JSON carry a Creative Brief?
///
/// Read off the untouched `Value` deliberately: `lumen_core::BrandKit` has no
/// `brief` field and serde drops the key, and the Python pipeline depends on
/// that (it re-attaches the brief after validation). So the one bit ingest
/// needs is lifted here, before `parse_brand_kit` consumes the value, rather
/// than by widening the engine's kit shape.
fn kit_is_briefed(brand_kit: Option<&Value>) -> bool {
    brand_kit
        .and_then(|kit| kit.get("brief"))
        .is_some_and(|brief| !brief.is_null())
}

fn ok_web(
    doc: Option<&lumen_web::WebDoc>,
    html: Option<String>,
    inverse_operations: Option<&[lumen_web::WebOperation]>,
    applied_operations: Option<usize>,
    diagnostics: Vec<Diagnostic>,
) -> CoreResponse {
    CoreResponse {
        ok: true,
        scene: None,
        diagnostics,
        error: None,
        applied_operations,
        preflight: None,
        brand_kit: None,
        brand_summary: None,
        brand_generation: None,
        brand_compatibility: None,
        geometry: None,
        operations: None,
        edit: None,
        dsl: None,
        export: None,
        asset: None,
        instance: None,
        web_doc: doc.map(|doc| to_value(doc).expect("web doc should serialize")),
        html,
        inverse_operations: inverse_operations
            .map(|inverses| to_value(inverses).expect("web operations should serialize")),
        web_fragment: None,
        web_theme: None,
        coverage: None,
        build_info: None,
    }
}

/// Deterministic per-instance generated asset id: a pure function of
/// (binding_set_id, generated entry name) so re-derivation produces the
/// same record and the content-addressed store deduplicates the bytes.
fn deterministic_generated_asset_id(binding_set_id: &str, entry: &str) -> String {
    let sanitize = |source: &str| {
        source
            .chars()
            .map(|ch| {
                if ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' {
                    ch
                } else {
                    '_'
                }
            })
            .collect::<String>()
    };
    format!("asset_gen_{}_{}", sanitize(binding_set_id), sanitize(entry))
}

/// Render one derived instance to the requested formats and store every
/// artifact content-addressed in the Phase E asset store (slice G7).
///
/// SVG/PNG ride the composed Skia adapter (license/print checks included,
/// purpose BulkRender). PDF follows the BINDING B3 verdict: license/print
/// checks run through the adapter first, then pages raster-flatten at the
/// requested DPI via lumen-skia — never the native vector PDF path.
fn export_instance_artifacts(
    scene: &Scene,
    formats: &[String],
    dpi: u16,
    custom_profile: Option<ExportProfile>,
    store_root: &str,
    fonts: Arc<FontManager>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Result<Vec<Value>, CoreError> {
    let store = LocalAssetStore::new(store_root);
    let resolver = Arc::new(StoreBackedResolver::new(store_root.to_owned()));
    // Same font set that shaped the derivation: measurement, paint, and
    // embedding all resolve the template's real faces, not bundled Inter.
    let adapter = server_export_adapter_with(
        LumenExportAdapter::with_resolver(
            Arc::clone(&resolver) as Arc<dyn lumen_export::AssetByteResolver>
        ),
        Arc::clone(&fonts),
    );
    let page_ids: Vec<PageId> = scene.pages.keys().cloned().collect();
    let mut artifacts = Vec::new();

    let push_error = |artifacts: &mut Vec<Value>, format: &str, code: &str, message: &str| {
        artifacts.push(json!({
            "format": format,
            "error": { "code": code, "message": message },
        }));
    };

    // Every artifact runs through the ONE export pipeline (adapter.export)
    // that interactive downloads use — bulk inherits vector PDF, bleed,
    // marks, proof, imposition, CMYK, X-4 finalize, the geometry tripwire,
    // and the print-ready report by construction. `formats` requests the
    // built-in default profiles; `custom_profile` (a full ExportProfile
    // from the request, usually a saved document profile resolved by the
    // API) replaces the default for its own format.
    let mut profiles: Vec<ExportProfile> = Vec::new();
    for format in formats {
        let profile = match format.as_str() {
            "svg" => ExportProfile {
                name: "instance_svg".to_owned(),
                format: ExportFormat::Svg,
                pdf_intent: None,
                raster: None,
                include_bleed: false,
                // SVG embeds fonts — instance previews render as images,
                // which cannot reach document fonts, and a resolver is
                // always wired here (name-only would warn LUME0216 into
                // the editor UI).
                embed_fonts: true,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
            },
            "png" => ExportProfile {
                name: "instance_png".to_owned(),
                format: ExportFormat::Png,
                pdf_intent: None,
                raster: Some(RasterScale {
                    scale: 1.0,
                    dpi: Some(dpi),
                }),
                include_bleed: false,
                embed_fonts: false,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
            },
            // Default PDF = the same vector print-intent deliverable an
            // interactive print download produces (live text, embedded
            // fonts, X-4). The W0-era raster-flattened default is gone —
            // flattened mode remains reachable only via the global
            // LUMEN_PDF_RENDERER=flattened comparison baseline.
            "pdf" => ExportProfile {
                name: "instance_pdf".to_owned(),
                format: ExportFormat::Pdf,
                pdf_intent: Some(PdfIntent::Print),
                raster: None,
                include_bleed: false,
                embed_fonts: true,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
            },
            other => {
                push_error(
                    &mut artifacts,
                    other,
                    "export.unknown_format",
                    "instance export supports svg, png, and pdf",
                );
                continue;
            }
        };
        // The custom profile owns its format; drop the default for it.
        if custom_profile
            .as_ref()
            .is_some_and(|custom| custom.format == profile.format)
        {
            continue;
        }
        profiles.push(profile);
    }
    if let Some(custom) = custom_profile {
        profiles.push(custom);
    }

    for profile in profiles {
        let format_label = match profile.format {
            ExportFormat::Svg => "svg",
            ExportFormat::Png => "png",
            ExportFormat::Pdf => "pdf",
            ExportFormat::FigmaManifest => "figma_manifest",
        };
        let profile_name = profile.name.clone();
        let request = ExportRequest {
            profile,
            page_ids: page_ids.clone(),
            purpose: ExportPurpose::BulkRender,
        };
        match adapter.export(scene, &request) {
            Ok(result) => {
                diagnostics.extend(result.diagnostics);
                // W6/L4 hard gate, now against the REAL request: a failed
                // print-ready report blocks the bulk artifact — one bad
                // instance fails loudly instead of joining a 400-copy run.
                if let Some(report) = &result.print_ready {
                    if report.failed() {
                        artifacts.push(json!({
                            "format": format_label,
                            "profile_name": profile_name,
                            "error": {
                                "code": "export.print_not_ready",
                                "message": "print-ready preflight failed; see print_ready report",
                            },
                            "print_ready": to_value(report)?,
                        }));
                        continue;
                    }
                }
                for artifact in result.artifacts {
                    let stored = store
                        .put(&artifact.bytes)
                        .map_err(|error| core_error(error.code, error.message))?;
                    let mut row = json!({
                        "format": format_label,
                        "profile_name": profile_name,
                        "page_id": artifact.page_id,
                        "mime_type": artifact.mime_type,
                        "byte_length": stored.byte_length,
                        "digest_value": stored.digest_value,
                        "relative_path": stored.relative_path,
                        "deduplicated": stored.deduplicated,
                    });
                    if let Some(report) = &result.print_ready {
                        row["print_ready"] = to_value(report)?;
                    }
                    artifacts.push(row);
                }
            }
            Err(error) => {
                diagnostics.extend(error.diagnostics.clone());
                push_error(&mut artifacts, format_label, error.code, &error.message);
            }
        }
    }

    Ok(artifacts)
}

fn parse_binding_set(value: Value) -> Result<BindingSet, CoreError> {
    serde_json::from_value(value)
        .map_err(|error| core_error("helper.binding_set", error.to_string()))
}

fn ok_scene(
    scene: Scene,
    diagnostics: Vec<Diagnostic>,
    applied_operations: Option<usize>,
) -> CoreResponse {
    CoreResponse {
        ok: true,
        scene: Some(to_value(scene).expect("scene should serialize")),
        diagnostics,
        error: None,
        applied_operations,
        preflight: None,
        brand_kit: None,
        brand_summary: None,
        brand_generation: None,
        brand_compatibility: None,
        geometry: None,
        operations: None,
        edit: None,
        dsl: None,
        export: None,
        asset: None,
        instance: None,
        web_doc: None,
        html: None,
        inverse_operations: None,
        web_fragment: None,
        web_theme: None,
        coverage: None,
        build_info: None,
    }
}

fn parse_scene(value: Value) -> Result<Scene, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.scene", error.to_string()))
}

fn parse_brand_kit(value: Value) -> Result<BrandKit, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.brand_kit", error.to_string()))
}

fn edit_token_options(mode: Option<Value>) -> Result<TokenResolutionOptions, CoreError> {
    let mut options = TokenResolutionOptions::default();
    if let Some(mode) = mode {
        options.mode = parse_brand_mode(mode)?;
    }
    Ok(options)
}

fn parse_brand_mode(value: Value) -> Result<BrandMode, CoreError> {
    serde_json::from_value(value)
        .map_err(|error| core_error("helper.brand_mode", error.to_string()))
}

fn parse_brand_seed(value: Value) -> Result<BrandSeed, CoreError> {
    serde_json::from_value(value)
        .map_err(|error| core_error("helper.brand_seed", error.to_string()))
}

fn parse_operations(values: Vec<Value>) -> Result<Vec<Operation>, CoreError> {
    values
        .into_iter()
        .map(|value| {
            serde_json::from_value(value)
                .map_err(|error| core_error("helper.operation", error.to_string()))
        })
        .collect()
}

fn values<T: Serialize>(items: Vec<T>) -> Result<Vec<Value>, CoreError> {
    items.into_iter().map(to_value).collect()
}

fn dsl_compile_output_value(output: &lumen_core::DslCompileOutput) -> Result<Value, CoreError> {
    Ok(json!({
        "operations": values(output.operations.clone())?,
        "checkpoint_label": output.checkpoint_label,
        "diagnostics": output
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
        "halted_at": output.halted_at.as_ref().map(|halt| json!({
            "line": halt.line,
            "code": halt.code,
        })),
    }))
}

fn operation_report_value(report: &Option<lumen_core::OperationReport>) -> Option<Value> {
    report.as_ref().map(|report| {
        json!({
            "applied_operations": report.applied_operations,
            "diagnostics": report.diagnostics,
        })
    })
}

fn operation_error_value(error: &Option<lumen_core::OperationError>) -> Option<Value> {
    error.as_ref().map(|error| {
        json!({
            "code": error.code,
            "message": error.message,
            "diagnostics": error.diagnostics,
        })
    })
}

fn to_value<T: Serialize>(value: T) -> Result<Value, CoreError> {
    serde_json::to_value(value).map_err(|error| core_error("helper.serialize", error.to_string()))
}

fn has_error(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
}

fn core_error(code: impl Into<String>, message: impl Into<String>) -> CoreError {
    CoreError {
        code: code.into(),
        message: message.into(),
    }
}
