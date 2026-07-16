//! SVG font embedding through the `FontFaceResolver` seam: `@font-face`
//! emission, the quoted family chain, usage collection (span overrides),
//! fail-loud resolution errors, and the LUME0216 name-only warning in both
//! declared states (`embed_fonts=false`, resolver absent).

use lumen_core::scene::TextNode;
use lumen_core::{
    Color, DocumentId, ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest,
    Fill, Node, NodeId, NodeKind, Operation, Orientation, Page, PageId, PagePreset, PageSize,
    Paint, PaintId, ParentRef, Scene, SizeSpec, TextSpan, Unit,
};
use lumen_export::{EmbeddedFontFace, FontEmbedError, FontFaceResolver, FontUsage, SvgExportAdapter};
use std::sync::{Arc, Mutex};

/// Deterministic stub: records the usages it receives and returns canned
/// faces (or a canned error).
#[derive(Debug, Default)]
struct StubFontResolver {
    seen: Mutex<Vec<FontUsage>>,
    faces: Vec<EmbeddedFontFace>,
    error: Option<FontEmbedError>,
}

impl FontFaceResolver for StubFontResolver {
    fn fallback_family(&self) -> String {
        "Inter".to_owned()
    }

    fn resolve_embeds(&self, usages: &[FontUsage]) -> Result<Vec<EmbeddedFontFace>, FontEmbedError> {
        self.seen.lock().unwrap().extend(usages.iter().cloned());
        if let Some(error) = &self.error {
            return Err(error.clone());
        }
        Ok(self.faces.clone())
    }
}

fn face(css_family: &str, weight: i32, bytes: &[u8]) -> EmbeddedFontFace {
    EmbeddedFontFace {
        css_family: css_family.to_owned(),
        weight,
        italic: false,
        bytes: bytes.to_vec(),
        mime_type: "font/ttf".to_owned(),
        unicode_range: None,
    }
}

fn page() -> Page {
    Page {
        id: PageId::from("page_embed"),
        name: "Embed".to_owned(),
        size: PageSize {
            width: 600.0,
            height: 200.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
            source: None,
            output: None,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: None,
        background: Vec::new(),
    }
}

fn text_node(id: &str, text: TextNode) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Text(text));
    node.size = SizeSpec::fixed(500.0, 60.0);
    node.fills = vec![Fill {
        id: PaintId::from("text_fill"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#111111".to_owned(),
            },
        },
    }];
    node
}

fn scene_with(node: Node) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_font_embed"), "Font embed SVG");
    scene
        .apply_operations([
            Operation::AddPage { page: page() },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_embed")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    scene
}

fn request(embed_fonts: bool) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "svg".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts,
            include_marks: false,
            imposition: None,
            proof: false,
            color: None,
        },
        page_ids: vec![PageId::from("page_embed")],
        purpose: ExportPurpose::UserDownload,
    }
}

fn simple_text(family: &str, weight: u16, content: &str) -> TextNode {
    TextNode {
        content: content.to_owned(),
        font_family: family.to_owned(),
        font_weight: weight,
        font_size: 20.0,
        ..TextNode::default()
    }
}

#[test]
fn embedding_emits_font_face_style_and_quoted_family_chain() {
    let resolver = Arc::new(StubFontResolver {
        faces: vec![face("Test Family", 800, b"FONTBYTES")],
        ..Default::default()
    });
    let scene = scene_with(text_node("t", simple_text("Test Family", 800, "Hi")));
    let result = SvgExportAdapter::new()
        .with_font_resolver(resolver)
        .export(&scene, &request(true))
        .expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).unwrap();

    // @font-face rule inside a <defs><style> block.
    assert!(svg.contains("<defs>\n<style type=\"text/css\">"), "style def:\n{svg}");
    assert!(
        svg.contains("@font-face { font-family: \"Test Family\"; font-weight: 800; font-style: normal;"),
        "font-face rule:\n{svg}"
    );
    // Data URI carries the stub bytes base64'd, with the format hint.
    assert!(
        svg.contains("src: url(\"data:font/ttf;base64,Rk9OVEJZVEVT\") format(\"truetype\");"),
        "data URI:\n{svg}"
    );
    // The text element carries the quoted two-family chain.
    assert!(
        svg.contains("font-family=\"'Test Family', 'Inter'\""),
        "family chain:\n{svg}"
    );
    // No viewer-font warning on the embedding path.
    assert!(
        !result.diagnostics.iter().any(|d| d.code == "LUME0216"),
        "no LUME0216 when embedding: {:?}",
        result.diagnostics
    );
}

#[test]
fn usage_collection_splits_span_weight_overrides() {
    let resolver = Arc::new(StubFontResolver {
        faces: vec![face("Test Family", 400, b"F")],
        ..Default::default()
    });
    let mut text = simple_text("Test Family", 400, "one two");
    // "two" [4,7) at weight 800.
    text.spans = vec![TextSpan {
        start: 4,
        end: 7,
        fill: None,
        font_weight: Some(800),
        underline: None,
        strikethrough: None,
        italic: None,
    }];
    let scene = scene_with(text_node("t", text));
    SvgExportAdapter::new()
        .with_font_resolver(resolver.clone())
        .export(&scene, &request(true))
        .expect("export");

    let seen = resolver.seen.lock().unwrap();
    assert_eq!(seen.len(), 2, "base + override usages: {seen:?}");
    let base = seen
        .iter()
        .find(|usage| usage.weight == 400)
        .expect("base usage");
    let accent = seen
        .iter()
        .find(|usage| usage.weight == 800)
        .expect("accent usage");
    assert_eq!(base.family, "Test Family");
    assert_eq!(accent.family, "Test Family");
    // Runs split around the span: "one " renders at 400, "two" at 800.
    assert!(base.chars.contains(&'o') && base.chars.contains(&'n') && base.chars.contains(&'e'));
    assert!(accent.chars.contains(&'t') && accent.chars.contains(&'w') && accent.chars.contains(&'o'));
    assert!(!accent.chars.contains(&'n'), "accent run carries only its own chars");
}

#[test]
fn resolver_error_fails_the_export_loudly() {
    let resolver = Arc::new(StubFontResolver {
        error: Some(FontEmbedError::new(
            "export.font_embed_restricted_license",
            "font \"Locked\" declares restricted-license embedding",
        )),
        ..Default::default()
    });
    let scene = scene_with(text_node("t", simple_text("Locked", 400, "Hi")));
    let error = SvgExportAdapter::new()
        .with_font_resolver(resolver)
        .export(&scene, &request(true))
        .expect_err("must fail");
    assert_eq!(error.code, "export.font_embed_restricted_license");
    assert!(error.message.contains("Locked"), "message: {}", error.message);
}

#[test]
fn resolver_returning_no_faces_fails_the_export() {
    let resolver = Arc::new(StubFontResolver::default());
    let scene = scene_with(text_node("t", simple_text("Ghost", 400, "Hi")));
    let error = SvgExportAdapter::new()
        .with_font_resolver(resolver)
        .export(&scene, &request(true))
        .expect_err("must fail");
    assert_eq!(error.code, "export.font_embed_empty");
}

#[test]
fn embed_fonts_false_emits_lume0216_and_no_style() {
    let resolver = Arc::new(StubFontResolver {
        faces: vec![face("Test Family", 400, b"F")],
        ..Default::default()
    });
    let scene = scene_with(text_node("t", simple_text("Test Family", 400, "Hi")));
    let result = SvgExportAdapter::new()
        .with_font_resolver(resolver)
        .export(&scene, &request(false))
        .expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).unwrap();
    assert!(!svg.contains("@font-face"), "no embedding when opted out:\n{svg}");
    // The historical unquoted markup stays byte-identical.
    assert!(svg.contains("font-family=\"Test Family\""), "markup:\n{svg}");
    let warning = result
        .diagnostics
        .iter()
        .find(|d| d.code == "LUME0216")
        .expect("LUME0216");
    assert!(warning.message.contains("Test Family"));
    assert!(warning.message.contains("embed_fonts=false"));
}

#[test]
fn missing_resolver_with_embedding_requested_emits_lume0216() {
    let scene = scene_with(text_node("t", simple_text("Test Family", 400, "Hi")));
    let result = SvgExportAdapter::new()
        .export(&scene, &request(true))
        .expect("export");
    let warning = result
        .diagnostics
        .iter()
        .find(|d| d.code == "LUME0216")
        .expect("LUME0216");
    assert!(warning.message.contains("no font resolver"));
}

#[test]
fn unicode_range_descriptor_is_emitted_for_fallback_faces() {
    let mut fallback_face = face("Inter", 400, b"FB");
    fallback_face.unicode_range = Some("U+2192".to_owned());
    let resolver = Arc::new(StubFontResolver {
        faces: vec![face("Test Family", 400, b"F"), fallback_face],
        ..Default::default()
    });
    let scene = scene_with(text_node("t", simple_text("Test Family", 400, "a→")));
    let result = SvgExportAdapter::new()
        .with_font_resolver(resolver)
        .export(&scene, &request(true))
        .expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).unwrap();
    assert!(
        svg.contains("unicode-range: U+2192;"),
        "range descriptor:\n{svg}"
    );
}

#[test]
fn text_free_page_embeds_nothing_and_warns_nothing() {
    let resolver = Arc::new(StubFontResolver {
        faces: vec![face("Unused", 400, b"F")],
        ..Default::default()
    });
    let mut scene = Scene::new(DocumentId::from("doc_font_embed"), "Font embed SVG");
    scene.apply_operations([Operation::AddPage { page: page() }]).unwrap();
    let result = SvgExportAdapter::new()
        .with_font_resolver(resolver.clone())
        .export(&scene, &request(true))
        .expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).unwrap();
    assert!(!svg.contains("@font-face"));
    assert!(!result.diagnostics.iter().any(|d| d.code == "LUME0216"));
    assert!(resolver.seen.lock().unwrap().is_empty(), "resolver never called");
}
