//! End-to-end proof of the website-mode architecture:
//! authored constrained HTML → ingest (parse + lint + sanitize) → typed tree
//! → validate → render (editor + delivery) → edit via invertible ops → undo.

use lumen_core::{DiagnosticSeverity, NodeId, PageId};
use lumen_web::{
    apply_operations, compile_web_theme, ingest_html_into_page, render_page, validate_web_doc,
    RenderOptions, WebDoc, WebNodeKind, WebOperation, WebTheme, WebThemeOptions,
    WebThemeRef,
};

fn theme() -> WebTheme {
    compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default()).0
}

fn seed_asset(doc: &mut WebDoc, id: &str, digest: &str) {
    let record: lumen_core::AssetRecord = serde_json::from_value(serde_json::json!({
        "id": id,
        "label": id,
        "kind": "raster_image",
        "status": "ready",
        "source": {"kind": "generated", "model": "test-model", "request_id": null},
        "media": {
            "mime_type": "image/webp",
            "filename": null,
            "byte_length": null,
            "digest": {"algorithm": "sha256", "value": digest},
            "location": null
        }
    }))
    .expect("asset record");
    doc.assets.insert(lumen_core::AssetId::from(id), record);
}

/// A small but complete branded landing page in the authoring vocabulary:
/// header nav band, hero with accent span + dual CTA, feature cards with
/// icons, image band, footer. Uses theme tokens only, responsive prefixes,
/// and every element class the P1 skill will teach.
const LANDING_PAGE: &str = r##"
<header id="site_header" class="bg-light border-b border-border">
  <div class="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
    <p data-variant="overline" class="text-primary">Insight Health</p>
    <div class="hidden md:flex items-center gap-8">
      <p data-variant="small" class="text-muted">Product</p>
      <p data-variant="small" class="text-muted">Security</p>
      <a data-button="primary" href="https://insighthealth.ai/demo">Book a demo</a>
    </div>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <p data-variant="overline" class="text-primary">AI medical scribe</p>
    <h1 data-variant="display" class="max-w-[820px]">Documentation that writes itself, so you can <span class="text-primary">focus on care</span></h1>
    <p class="text-muted max-w-[640px]">Insight Health captures every visit and drafts compliant notes before the patient leaves the room.</p>
    <div class="flex flex-col sm:flex-row gap-4">
      <a data-button="primary" href="https://insighthealth.ai/demo">Book a demo</a>
      <a data-button="outline" href="#features">Explore features</a>
    </div>
  </div>
</section>
<section id="features" class="bg-card">
  <div class="mx-auto max-w-[1200px] px-6 py-20 flex flex-col gap-12">
    <h2>Built for clinical reality</h2>
    <div class="grid md:grid-cols-3 gap-8">
      <div class="flex flex-col gap-3 p-6 bg-light rounded-2xl">
        <i data-icon="bolt" class="text-primary"></i>
        <h3>Fast capture</h3>
        <p data-variant="small" class="text-muted">Notes drafted in seconds, not evenings.</p>
      </div>
      <div class="flex flex-col gap-3 p-6 bg-light rounded-2xl">
        <i data-icon="shield" class="text-primary"></i>
        <h3>HIPAA first</h3>
        <p data-variant="small" class="text-muted">PHI never leaves your compliance boundary.</p>
      </div>
      <div class="flex flex-col gap-3 p-6 bg-light rounded-2xl">
        <i data-icon="check" class="text-primary"></i>
        <h3>EHR ready</h3>
        <p data-variant="small" class="text-muted">Pushes structured notes into your EHR.</p>
      </div>
    </div>
  </div>
</section>
<section id="product" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-20 flex flex-col items-center gap-8">
    <img data-asset="product_shot" alt="Insight Health scribe interface" class="rounded-2xl w-full max-w-[960px]">
  </div>
</section>
<footer id="site_footer" class="bg-dark">
  <div class="mx-auto max-w-[1200px] px-6 py-12 flex flex-col md:flex-row items-center justify-between gap-6">
    <p data-variant="small" class="text-inverse">Insight Health</p>
    <a data-button="link" href="https://insighthealth.ai/privacy">Privacy</a>
  </div>
</footer>
"##;

#[test]
fn full_pipeline_round_trip() {
    let theme = theme();
    let mut doc = WebDoc::new("doc_web_1", "Insight Health — AI Scribe", None);
    seed_asset(&mut doc, "product_shot", "deadbeef01");

    // 1. Ingest: parse + lint clean, tree installed.
    let page_id = PageId::from("home");
    let outcome = ingest_html_into_page(&mut doc, &page_id, LANDING_PAGE, &theme);
    assert!(
        !outcome.has_errors(),
        "ingest diagnostics: {:#?}",
        outcome.diagnostics
    );
    let page = doc.page(&page_id).expect("page");
    assert_eq!(page.node(&page.root).unwrap().children.len(), 5, "five sections");

    // 2. Validate: structurally sound, no errors.
    let validation = validate_web_doc(&doc);
    assert!(
        validation
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "validation: {validation:#?}"
    );

    // 3. Serde round-trip: the document of record survives storage.
    let stored = serde_json::to_string(&doc).expect("serialize");
    let reloaded: WebDoc = serde_json::from_str(&stored).expect("deserialize");
    assert_eq!(doc, reloaded);

    // 4. Editor render: instrumented, tokens + runtime present.
    let mut editor_options = RenderOptions::editor("/asset-store");
    editor_options.tailwind_runtime_src = Some("/vendor/tailwindcdn.js".to_owned());
    editor_options.bridge_script = Some("/* bridge */".to_owned());
    let editor = render_page(&doc, &page_id, &theme, &editor_options).expect("editor render");
    assert!(editor.diagnostics.is_empty(), "{:#?}", editor.diagnostics);
    assert!(editor.html.contains("data-node-id=\"hero\""));
    assert!(editor.html.contains("data-node-id=\"site_footer\""));
    assert!(editor.html.contains("text/tailwindcss"));
    assert!(editor.html.contains("/asset-store/deadbeef01"));

    // 5. Delivery render: clean output, zero instrumentation.
    let delivery = render_page(
        &doc,
        &page_id,
        &theme,
        &RenderOptions::delivery("/asset-store"),
    )
    .expect("delivery render");
    assert!(!delivery.html.contains("data-node-id"));
    assert!(!delivery.html.contains("<script"));
    assert!(delivery.html.contains("<header id=\"site_header\""));
    assert!(delivery.html.contains("<footer id=\"site_footer\""));
    assert!(delivery.html.contains("href=\"#features\""));
    assert!(delivery.html.contains("prefers-reduced-motion"));
    assert!(delivery.html.contains("focus on care"));

    // 6. Ops: a scoped edit (retitle + reorder), then undo restores exactly.
    let before_edit = doc.clone();
    let display_text_id = find_display_text(&doc, &page_id);
    let inverses = apply_operations(
        &mut doc,
        &[
            WebOperation::SetText {
                page_id: page_id.clone(),
                id: display_text_id,
                content: "Notes that <strong>write themselves</strong>".to_owned(),
            },
            WebOperation::MoveNode {
                page_id: page_id.clone(),
                id: NodeId::from("product"),
                new_parent: NodeId::from("root"),
                index: 2,
            },
        ],
    )
    .expect("apply edit ops");
    assert_ne!(doc, before_edit);
    let rendered = render_page(&doc, &page_id, &theme, &RenderOptions::delivery("/asset-store"))
        .expect("render after edit");
    assert!(rendered.html.contains("write themselves"));

    apply_operations(&mut doc, &inverses).expect("undo");
    assert_eq!(doc, before_edit, "inverse batch restores the exact document");
}

#[test]
fn violations_surface_precise_diagnostics_and_block_ingest() {
    let theme = theme();
    let mut doc = WebDoc::new("doc_web_2", "Bad input", None);
    let before = doc.clone();
    let page_id = PageId::from("home");
    let outcome = ingest_html_into_page(
        &mut doc,
        &page_id,
        r##"<section id="hero" class="bg-[#231d40]">
              <script>alert(1)</script>
              <img src="https://elsewhere.example/pic.png" alt="external">
              <a data-button="primary">Missing link</a>
              <p class="text-red-500">Off palette</p>
            </section>
            <div class="flex">top level container</div>"##,
        &theme,
    );
    assert!(outcome.has_errors());
    let codes: Vec<&str> = outcome
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect();
    for expected in [
        "LUMW0210", // raw hex
        "LUMW0101", // script
        "LUMW0110", // external image src
        "LUMW0107", // button without href
        "LUMW0211", // stock Tailwind palette
        "LUMW0102", // top-level non-section
    ] {
        assert!(codes.contains(&expected), "missing {expected} in {codes:?}");
    }
    // The nearest-token suggestion makes the raw-hex diagnostic repairable.
    let hex_diag = outcome
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUMW0210")
        .unwrap();
    assert!(hex_diag.hint.as_ref().unwrap().contains("Nearest theme token"));
    // And the document was never touched.
    assert_eq!(doc, before);
}

fn find_display_text(doc: &WebDoc, page_id: &PageId) -> NodeId {
    let page = doc.page(page_id).expect("page");
    page.nodes
        .values()
        .find_map(|node| match &node.kind {
            WebNodeKind::Text {
                variant: lumen_web::TextVariant::Display,
                ..
            } => Some(node.id.clone()),
            _ => None,
        })
        .expect("display text node")
}
