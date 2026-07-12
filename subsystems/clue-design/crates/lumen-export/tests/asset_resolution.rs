use lumen_core::{
    AssetDigest, AssetId, AssetKind, AssetLocation, AssetMediaMetadata, AssetPlacement,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, Color, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, Fill, ImageFitMode, ImageNode, Node, NodeId,
    NodeKind, Page, PageId, PagePreset, PageSize, Paint, PaintId, Phase, RasterAssetMetadata,
    Scene, SizeSpec, Transform, Unit,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter, SvgExportAdapter};
use std::sync::Arc;

const LOGO_PNG: &[u8] = include_bytes!("../fixtures/assets/acme-logo-8x8-red.png");
const LOGO_DIGEST: &str = "8e5491753553a973d4e82a8ae675fdfbd6c7b06c87629d365a30c7bc659d2195";

fn logo_asset_record(asset_id: &str) -> AssetRecord {
    AssetRecord {
        id: AssetId::from(asset_id),
        label: "Acme logo".to_owned(),
        kind: AssetKind::Logo,
        status: AssetStatus::Ready,
        source: AssetSource::Uploaded {
            asset_id: None,
            filename: Some("acme-logo-8x8-red.png".to_owned()),
            uploaded_by: Some("designer".to_owned()),
        },
        media: AssetMediaMetadata {
            mime_type: Some("image/png".to_owned()),
            filename: Some("acme-logo-8x8-red.png".to_owned()),
            byte_length: Some(LOGO_PNG.len() as u64),
            digest: Some(AssetDigest {
                algorithm: "sha256".to_owned(),
                value: LOGO_DIGEST.to_owned(),
            }),
            location: Some(AssetLocation {
                provider: "local-store".to_owned(),
                opaque_ref: format!("sha256/8e/{LOGO_DIGEST}"),
                url: None,
            }),
            thumbnail: None,
        },
        raster: Some(RasterAssetMetadata {
            pixel_width: 8,
            pixel_height: 8,
            dpi_x: Some(300.0),
            dpi_y: Some(300.0),
            has_alpha: Some(true),
            color_profile: Some("srgb".to_owned()),
            aspect_ratio: Some(1.0),
        }),
        vector: None,
        font: None,
        logo: None,
        license: None,
        provenance: AssetProvenance::default(),
        tags: vec!["logo".to_owned()],
    }
}

fn scene_with_image_node(asset_id: &str, register_record: bool) -> Scene {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_assets"), "Asset scene");

    let mut image_node = Node::new(
        NodeId::from("node_image"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from(asset_id),
            alt: Some("Acme logo".to_owned()),
        }),
    );
    image_node.transform = Transform {
        x: 20.0,
        y: 20.0,
        ..Transform::default()
    };
    image_node.size = SizeSpec::fixed(60.0, 60.0);
    image_node.asset_placement = Some(AssetPlacement {
        fit: Some(ImageFitMode::Cover),
        ..AssetPlacement::default()
    });
    scene.nodes.insert(image_node.id.clone(), image_node);

    scene.pages.insert(
        PageId::from("page_1"),
        Page {
            id: PageId::from("page_1"),
            name: "Page".to_owned(),
            size: PageSize {
                width: 100.0,
                height: 100.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: lumen_core::Orientation::Portrait,
                source: None,
                output: None,
            },
            children: vec![NodeId::from("node_image")],
            bleed: None,
            safe_area: None,
            background: vec![Fill {
                id: PaintId::from("paint_page_bg"),
                paint: Paint::Solid {
                    color: Color::Hex {
                        value: "#ffffff".to_owned(),
                    },
                },
            }],
        },
    );

    if register_record {
        let record = logo_asset_record(asset_id);
        scene.assets.insert(record.id.clone(), record);
    }

    scene
}

fn svg_request() -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "asset_svg".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        },
        page_ids: vec![PageId::from("page_1")],
        purpose: ExportPurpose::AgentCritique,
    }
}

fn logo_resolver() -> Arc<FixtureAssetResolver> {
    Arc::new(FixtureAssetResolver::new().with_asset_bytes(
        "asset_logo",
        "image/png",
        LOGO_PNG.to_vec(),
    ))
}

#[test]
fn svg_export_embeds_real_png_data_uri() {
    let scene = scene_with_image_node("asset_logo", true);
    let adapter = SvgExportAdapter::with_resolver(logo_resolver());

    let result = adapter.export(&scene, &svg_request()).expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8");

    let expected_prefix = "data:image/png;base64,";
    assert!(
        svg.contains(expected_prefix),
        "svg should embed a png data uri: {svg}"
    );
    assert!(
        svg.contains("preserveAspectRatio=\"xMidYMid slice\""),
        "cover placement should map to slice: {svg}"
    );
    assert!(
        svg.contains("data-lumen-asset-id=\"asset_logo\""),
        "image element should carry the asset id"
    );
    assert!(
        !svg.contains("data-lumen-unsupported=\"image\""),
        "resolved image should not render a placeholder"
    );
    assert!(
        !result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0202"
                || diagnostic.code == "LUME0210"
                || diagnostic.code == "LUME0211"),
        "no asset diagnostics expected: {:?}",
        result.diagnostics
    );
}

#[test]
fn svg_export_without_resolver_keeps_placeholder_and_warning() {
    let scene = scene_with_image_node("asset_logo", true);
    let adapter = SvgExportAdapter::new();

    let result = adapter.export(&scene, &svg_request()).expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8");

    assert!(svg.contains("data-lumen-unsupported=\"image\""));
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0202" && diagnostic.phase == Phase::Export));
}

#[test]
fn missing_bytes_emit_diagnostic_not_panic() {
    let scene = scene_with_image_node("asset_logo", true);
    let empty_resolver = Arc::new(FixtureAssetResolver::new());
    let adapter = SvgExportAdapter::with_resolver(empty_resolver);

    let result = adapter.export(&scene, &svg_request()).expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8");

    assert!(
        svg.contains("data-lumen-unsupported=\"image\""),
        "unresolved image should fall back to placeholder"
    );
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUME0210" && diagnostic.message.contains("asset.bytes_missing")
    }));
}

#[test]
fn missing_asset_record_emits_diagnostic() {
    let scene = scene_with_image_node("asset_logo", false);
    let adapter = SvgExportAdapter::with_resolver(logo_resolver());

    let result = adapter.export(&scene, &svg_request()).expect("export");

    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0211"));
}

#[test]
fn digest_keyed_bytes_resolve_for_records_sharing_content() {
    let scene = scene_with_image_node("asset_logo", true);
    let resolver = Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        LOGO_DIGEST,
        "image/png",
        LOGO_PNG.to_vec(),
    ));
    let adapter = SvgExportAdapter::with_resolver(resolver);

    let result = adapter.export(&scene, &svg_request()).expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8");

    assert!(svg.contains("data:image/png;base64,"));
}

#[test]
fn critic_preview_path_renders_real_logo_without_asset_warnings() {
    // Gate for slice E1: the agent-critique preview (SVG + PNG through the
    // top-level adapter) consumes real bytes instead of placeholders.
    let scene = scene_with_image_node("asset_logo", true);
    let adapter = LumenExportAdapter::with_resolver(logo_resolver());

    let svg_result = adapter.export(&scene, &svg_request()).expect("svg export");
    let svg = String::from_utf8(svg_result.artifacts[0].bytes.clone()).expect("utf8");
    assert!(svg.contains("data:image/png;base64,"));

    // The PNG half of the critic preview path (real rasterizer composed)
    // is covered in lumen-skia's raster_export tests since slice A4.
    assert!(
        !svg_result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0202"
                || diagnostic.code == "LUME0210"
                || diagnostic.code == "LUME0211"),
        "critic preview should not carry unresolved-asset diagnostics: {:?}",
        svg_result.diagnostics
    );
}

const PHASE_E_CONFORMANCE_SCENE: &str =
    include_str!("../../lumen-core/fixtures/conformance/phase_e_asset_scene.json");

/// Conformance for slice E9: the committed fixture scene exports with a
/// stable placeholder baseline when bytes are unavailable, and with real
/// embedded bytes when they are — the fixture-first guarantee from the
/// gap analysis ("preserve fixture assets for deterministic tests")
/// alongside the production path.
#[test]
fn conformance_fixture_exports_placeholder_baseline_and_real_bytes() {
    let scene: Scene = serde_json::from_str(PHASE_E_CONFORMANCE_SCENE).expect("fixture parses");
    let request = ExportRequest {
        profile: ExportProfile {
            name: "phase_e_conformance".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        },
        page_ids: vec![PageId::from("page_a4")],
        purpose: ExportPurpose::AgentCritique,
    };

    // Fixture baseline: no resolver, deterministic placeholder markup.
    let baseline = LumenExportAdapter::new()
        .export(&scene, &request)
        .expect("baseline export");
    let baseline_svg = String::from_utf8(baseline.artifacts[0].bytes.clone()).expect("utf8");
    assert!(baseline_svg.contains("data-lumen-unsupported=\"image\""));
    assert!(baseline
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0202"));

    // Real-byte path: digest-keyed resolution embeds the focal crop.
    let resolver = Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        LOGO_DIGEST,
        "image/png",
        LOGO_PNG.to_vec(),
    ));
    let real = LumenExportAdapter::with_resolver(resolver)
        .export(&scene, &request)
        .expect("real export");
    let real_svg = String::from_utf8(real.artifacts[0].bytes.clone()).expect("utf8");
    assert!(real_svg.contains("data:image/png;base64,"));
    assert!(real_svg.contains("data-lumen-image-fit=\"focal-crop\""));
    assert!(!real_svg.contains("data-lumen-unsupported=\"image\""));
    assert!(!real
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0202"
            || diagnostic.code == "LUME0210"
            || diagnostic.code == "LUME0211"));

    // Unrelated markup is byte-identical across the two paths: asset
    // resolution must not perturb sibling nodes or the page envelope.
    let text_line = |svg: &str| -> String {
        svg.lines()
            .find(|line| line.contains("node_contact_name"))
            .expect("text node line")
            .to_owned()
    };
    assert_eq!(text_line(&baseline_svg), text_line(&real_svg));
    let svg_open = |svg: &str| -> String { svg.lines().next().expect("svg open tag").to_owned() };
    assert_eq!(svg_open(&baseline_svg), svg_open(&real_svg));
}
