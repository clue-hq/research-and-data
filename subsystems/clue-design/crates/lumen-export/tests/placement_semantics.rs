use lumen_core::{
    AssetDigest, AssetId, AssetKind, AssetLicense, AssetMediaMetadata, AssetPlacement,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, FocalPoint, ImageFitMode, ImageNode,
    LogoAssetMetadata, Node, NodeId, NodeKind, Page, PageId, PagePreset, PageSize, PdfIntent,
    RasterAssetMetadata, Rect, Scene, SizeSpec, Transform, Unit,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter};
use std::sync::Arc;

const LOGO_PNG: &[u8] = include_bytes!("../fixtures/assets/acme-logo-8x8-red.png");

fn wide_asset_record(asset_id: &str) -> AssetRecord {
    AssetRecord {
        id: AssetId::from(asset_id),
        label: "Wide hero".to_owned(),
        kind: AssetKind::RasterImage,
        status: AssetStatus::Ready,
        source: AssetSource::Uploaded {
            asset_id: None,
            filename: Some("hero.png".to_owned()),
            uploaded_by: None,
        },
        media: AssetMediaMetadata {
            mime_type: Some("image/png".to_owned()),
            filename: Some("hero.png".to_owned()),
            byte_length: Some(LOGO_PNG.len() as u64),
            digest: Some(AssetDigest {
                algorithm: "sha256".to_owned(),
                value: "0".repeat(64),
            }),
            location: None,
            thumbnail: None,
        },
        raster: Some(RasterAssetMetadata {
            pixel_width: 1600,
            pixel_height: 900,
            dpi_x: Some(144.0),
            dpi_y: Some(144.0),
            has_alpha: Some(false),
            color_profile: None,
            aspect_ratio: None,
        }),
        vector: None,
        font: None,
        logo: None,
        license: None,
        provenance: AssetProvenance::default(),
        tags: Vec::new(),
    }
}

fn base_scene(unit: Unit, safe_area: Option<Rect>) -> Scene {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_placement"),
        "Placement scene",
    );
    scene.pages.insert(
        PageId::from("page_1"),
        Page {
            id: PageId::from("page_1"),
            name: "Page".to_owned(),
            size: PageSize {
                width: 100.0,
                height: 100.0,
                unit,
                preset: Some(PagePreset::Custom),
                orientation: lumen_core::Orientation::Portrait,
                source: None,
                output: None,
            },
            children: Vec::new(),
            bleed: None,
            safe_area,
            background: Vec::new(),
        },
    );
    scene
}

fn image_node(
    id: &str,
    asset_id: &str,
    fit: Option<ImageFitMode>,
    focal: Option<FocalPoint>,
) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from(asset_id),
            alt: None,
        }),
    );
    node.transform = Transform {
        x: 20.0,
        y: 20.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(60.0, 60.0);
    node.asset_placement = Some(AssetPlacement {
        fit,
        focal_point: focal,
        preserve_transparency: None,
        alt_text: None,
    });
    node
}

fn attach(scene: &mut Scene, node: Node) {
    let node_id = node.id.clone();
    scene.nodes.insert(node_id.clone(), node);
    scene
        .pages
        .get_mut(&PageId::from("page_1"))
        .unwrap()
        .children
        .push(node_id);
}

fn resolver(asset_id: &str) -> Arc<FixtureAssetResolver> {
    Arc::new(FixtureAssetResolver::new().with_asset_bytes(asset_id, "image/png", LOGO_PNG.to_vec()))
}

fn svg_request(purpose: ExportPurpose, pdf_intent: Option<PdfIntent>) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "placement".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent,
            raster: None,
            include_bleed: false,
            embed_fonts: true,
        },
        page_ids: vec![PageId::from("page_1")],
        purpose,
    }
}

fn export_svg(
    scene: &Scene,
    request: &ExportRequest,
    asset_id: &str,
) -> (String, Vec<lumen_core::Diagnostic>) {
    let adapter = LumenExportAdapter::with_resolver(resolver(asset_id));
    let result = adapter.export(scene, request).expect("export");
    (
        String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8"),
        result.diagnostics,
    )
}

#[test]
fn contain_and_cover_fits_map_to_preserve_aspect_ratio() {
    let mut scene = base_scene(Unit::Px, None);
    scene
        .assets
        .insert(AssetId::from("asset_hero"), wide_asset_record("asset_hero"));
    attach(
        &mut scene,
        image_node(
            "node_contain",
            "asset_hero",
            Some(ImageFitMode::Contain),
            None,
        ),
    );
    let (svg, _) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_hero",
    );
    assert!(
        svg.contains("preserveAspectRatio=\"xMidYMid meet\""),
        "{svg}"
    );

    let mut scene = base_scene(Unit::Px, None);
    scene
        .assets
        .insert(AssetId::from("asset_hero"), wide_asset_record("asset_hero"));
    attach(
        &mut scene,
        image_node("node_cover", "asset_hero", Some(ImageFitMode::Cover), None),
    );
    let (svg, _) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_hero",
    );
    assert!(
        svg.contains("preserveAspectRatio=\"xMidYMid slice\""),
        "{svg}"
    );
}

#[test]
fn focal_point_cover_crops_an_explicit_window() {
    let mut scene = base_scene(Unit::Px, None);
    scene
        .assets
        .insert(AssetId::from("asset_hero"), wide_asset_record("asset_hero"));
    // 16:9 asset in a 60x60 box, focused on the right edge: the drawn
    // image is 106.6667x60 shifted fully left (offset 46.6667).
    attach(
        &mut scene,
        image_node(
            "node_focal",
            "asset_hero",
            Some(ImageFitMode::Cover),
            Some(FocalPoint { x: 1.0, y: 0.5 }),
        ),
    );

    let (svg, _) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_hero",
    );

    assert!(svg.contains("data-lumen-image-fit=\"focal-crop\""), "{svg}");
    assert!(
        svg.contains("<image x=\"-46.6667\" y=\"0\" width=\"106.6667\" height=\"60\" preserveAspectRatio=\"none\""),
        "focal crop window should be explicit: {svg}"
    );
    assert!(svg.contains("clip-path=\"url(#lumen-image-clip-node_focal)\""));
    assert!(svg.contains("<clipPath id=\"lumen-image-clip-node_focal\">"));
}

#[test]
fn centered_focal_point_centers_the_window() {
    let mut scene = base_scene(Unit::Px, None);
    scene
        .assets
        .insert(AssetId::from("asset_hero"), wide_asset_record("asset_hero"));
    attach(
        &mut scene,
        image_node(
            "node_focal_center",
            "asset_hero",
            Some(ImageFitMode::Crop),
            Some(FocalPoint { x: 0.5, y: 0.5 }),
        ),
    );

    let (svg, _) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_hero",
    );
    assert!(
        svg.contains("<image x=\"-23.3333\" y=\"0\" width=\"106.6667\" height=\"60\""),
        "{svg}"
    );
}

#[test]
fn low_effective_dpi_warns_on_print_exports_only() {
    // 1600px rendered across 60mm = ~677 DPI is fine; shrink the asset
    // to force the warning: 8px over 60mm = ~3 DPI.
    let mut record = wide_asset_record("asset_tiny");
    record.raster.as_mut().unwrap().pixel_width = 8;
    record.raster.as_mut().unwrap().pixel_height = 8;

    let mut scene = base_scene(Unit::Mm, None);
    scene.assets.insert(AssetId::from("asset_tiny"), record);
    attach(
        &mut scene,
        image_node("node_tiny", "asset_tiny", Some(ImageFitMode::Cover), None),
    );

    let (_, diagnostics) = export_svg(
        &scene,
        &svg_request(ExportPurpose::UserDownload, Some(PdfIntent::Print)),
        "asset_tiny",
    );
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0220"));

    let (_, preview_diagnostics) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_tiny",
    );
    assert!(!preview_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0220"));
}

#[test]
fn logo_safe_area_violation_warns() {
    let mut record = wide_asset_record("asset_logo");
    record.kind = AssetKind::Logo;
    record.logo = Some(LogoAssetMetadata {
        pixel_width: Some(1600),
        pixel_height: Some(900),
        width: None,
        height: None,
        dpi_x: None,
        dpi_y: None,
        has_transparency: Some(true),
        color_mode: None,
        clearspace: Some(8.0),
    });

    let safe_area = Some(Rect {
        x: 10.0,
        y: 10.0,
        width: 80.0,
        height: 80.0,
    });

    // At (20,20) sized 60x60 with 8 clearspace the logo needs 12..88 —
    // it escapes the 10..90 safe area? 20-8=12 >= 10 and 80+8=88 <= 90:
    // fits. Move it to the corner to violate.
    let mut scene = base_scene(Unit::Px, safe_area.clone());
    scene
        .assets
        .insert(AssetId::from("asset_logo"), record.clone());
    let mut node = image_node("node_logo", "asset_logo", Some(ImageFitMode::Contain), None);
    node.transform.x = 4.0;
    node.transform.y = 4.0;
    attach(&mut scene, node);

    let (_, diagnostics) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_logo",
    );
    let violation = diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUME0221")
        .expect("safe-area violation");
    assert!(violation.message.contains("safe area"));
    assert!(violation.message.contains("clearspace"));

    // Inside the safe area (with clearspace) no warning fires.
    let mut scene = base_scene(Unit::Px, safe_area);
    scene.assets.insert(AssetId::from("asset_logo"), record);
    attach(
        &mut scene,
        image_node("node_logo", "asset_logo", Some(ImageFitMode::Contain), None),
    );
    let (_, diagnostics) = export_svg(
        &scene,
        &svg_request(ExportPurpose::AgentCritique, None),
        "asset_logo",
    );
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0221"));
}

#[test]
fn license_forbidden_assets_block_enforced_exports_and_warn_previews() {
    let mut record = wide_asset_record("asset_restricted");
    record.license = Some(AssetLicense {
        name: "editorial_only".to_owned(),
        allow_export: false,
        allow_modification: false,
        allow_embedding: false,
        allow_subsetting: false,
        source_url: None,
        restrictions: vec!["no commercial export".to_owned()],
    });

    let mut scene = base_scene(Unit::Px, None);
    scene
        .assets
        .insert(AssetId::from("asset_restricted"), record);
    attach(
        &mut scene,
        image_node(
            "node_restricted",
            "asset_restricted",
            Some(ImageFitMode::Cover),
            None,
        ),
    );

    let adapter = LumenExportAdapter::with_resolver(resolver("asset_restricted"));

    // Enforced export (user download) is rejected with a precise subject.
    let error = adapter
        .export(
            &scene,
            &svg_request(ExportPurpose::UserDownload, Some(PdfIntent::Print)),
        )
        .expect_err("licensing must block enforced exports");
    assert_eq!(error.code, "export.license_forbidden");
    let rejection = error
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUME0212")
        .expect("LUME0212");
    assert!(rejection.message.contains("asset_restricted"));
    assert!(rejection.message.contains("editorial_only"));

    // Critic previews still render, carrying the warning.
    let result = adapter
        .export(&scene, &svg_request(ExportPurpose::AgentCritique, None))
        .expect("preview export succeeds");
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUME0212"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Warning
    }));
}
