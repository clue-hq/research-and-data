//! Step 10 (S0/G0.4): a full-document golden SVG fixture for the blessed
//! **image hero + scrim + headline** idiom — the catalog block
//! `knowledge/design/blocks/patterns.md` "Image hero". This locks render
//! parity for the scrim recipe: a clipped frame holding a cover-fit image,
//! a semi-transparent scrim rect over it, and an inverse-fill headline over
//! the scrim (declaration order = z-order: image -> scrim -> text). Any
//! change to image cover-fit markup, node opacity, or stacking shows up as a
//! byte diff against the golden.
//!
//! Regenerate intentionally with:
//! `UPDATE_IMAGE_GOLDENS=1 cargo test -p lumen-export --test image_golden`

use lumen_core::{
    AssetDigest, AssetId, AssetKind, AssetLocation, AssetMediaMetadata, AssetPlacement,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, Color, DocumentId, ExportAdapter,
    ExportFormat, ExportProfile, ExportPurpose, ExportRequest, Fill, FocalPoint, ImageFitMode,
    ImageNode, Node, NodeId, NodeKind, Operation, Orientation, Page, PageId, PagePreset, PageSize,
    Paint, PaintId, ParentRef, RasterAssetMetadata, Scene, SizeSpec, TextAlign, TextNode, TextWrap,
    Transform, Unit,
};
use lumen_export::{FixtureAssetResolver, SvgExportAdapter};
use std::path::PathBuf;
use std::sync::Arc;

const HERO_PNG: &[u8] = include_bytes!("../fixtures/assets/acme-logo-8x8-red.png");
const HERO_DIGEST: &str = "8e5491753553a973d4e82a8ae675fdfbd6c7b06c87629d365a30c7bc659d2195";

fn solid(value: &str) -> Paint {
    Paint::Solid {
        color: Color::Hex {
            value: value.to_owned(),
        },
    }
}

fn fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: solid(value),
    }
}

/// A Ready, content-addressed raster record for the generated hero photo so
/// the export resolves real bytes (digest-keyed) instead of a placeholder.
fn hero_asset_record(asset_id: &str) -> AssetRecord {
    AssetRecord {
        id: AssetId::from(asset_id),
        label: "Hero photo".to_owned(),
        kind: AssetKind::RasterImage,
        status: AssetStatus::Ready,
        source: AssetSource::Generated {
            request_id: Some("req_hero".to_owned()),
            model: "image-gen-v1".to_owned(),
        },
        media: AssetMediaMetadata {
            mime_type: Some("image/png".to_owned()),
            filename: Some("hero.png".to_owned()),
            byte_length: Some(HERO_PNG.len() as u64),
            digest: Some(AssetDigest {
                algorithm: "sha256".to_owned(),
                value: HERO_DIGEST.to_owned(),
            }),
            location: Some(AssetLocation {
                provider: "local-store".to_owned(),
                opaque_ref: format!("sha256/8e/{HERO_DIGEST}"),
                url: None,
            }),
            thumbnail: None,
        },
        raster: Some(RasterAssetMetadata {
            pixel_width: 8,
            pixel_height: 8,
            dpi_x: Some(72.0),
            dpi_y: Some(72.0),
            has_alpha: Some(true),
            color_profile: Some("srgb".to_owned()),
            aspect_ratio: Some(1.0),
        }),
        vector: None,
        font: None,
        logo: None,
        license: None,
        provenance: AssetProvenance::default(),
        tags: vec!["hero".to_owned()],
    }
}

/// The "Image hero" idiom: a clipped artboard frame with three stacked
/// children — a cover-fit image, a dark scrim rect (node opacity 0.56), and an
/// inverse-fill headline anchored low over the scrim.
fn image_hero_scene() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_image_hero"), "Image hero");

    let page = Page {
        id: PageId::from("page_hero"),
        name: "Hero".to_owned(),
        size: PageSize {
            width: 1080.0,
            height: 1350.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Portrait,
            source: None,
            output: None,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: None,
        background: vec![fill("paint_page_bg", "#ffffff")],
    };

    let mut artboard = Node::new(NodeId::from("artboard"), NodeKind::Frame);
    artboard.size = SizeSpec::fixed(1080.0, 1350.0);
    artboard.clip = true;
    artboard.fills = vec![fill("fill_artboard", "#0e1a1f")];

    let mut photo = Node::new(
        NodeId::from("photo"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("hero_photo"),
            alt: Some("Care team at a clinic front desk".to_owned()),
        }),
    );
    photo.size = SizeSpec::fixed(1080.0, 1350.0);
    photo.asset_placement = Some(AssetPlacement {
        fit: Some(ImageFitMode::Cover),
        focal_point: Some(FocalPoint { x: 0.5, y: 0.38 }),
        alt_text: Some("Care team at a clinic front desk".to_owned()),
        ..AssetPlacement::default()
    });

    // Scrim: a full-bleed dark rect at scrim opacity (0.56) over the photo.
    let mut scrim = Node::new(NodeId::from("scrim"), NodeKind::Rect);
    scrim.size = SizeSpec::fixed(1080.0, 1350.0);
    scrim.fills = vec![fill("fill_scrim", "#0b1f24")];
    scrim.opacity = 0.56;
    scrim.opacity_token = Some("opacity.scrim".to_owned());

    // Headline: inverse (light) text over the scrim, anchored low.
    let mut headline = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(TextNode {
            content: "Faster triage, calmer clinics.".to_owned(),
            font_size: 64.0,
            font_weight: 700,
            align: TextAlign::Left,
            line_height: 1.06,
            wrap: TextWrap::Wrap,
            max_lines: Some(2),
            ..TextNode::default()
        }),
    );
    headline.transform = Transform {
        x: 80.0,
        y: 1090.0,
        ..Transform::default()
    };
    headline.size = SizeSpec::fixed(920.0, 180.0);
    headline.fills = vec![fill("fill_headline", "#ffffff")];

    scene
        .apply_operations([
            Operation::AddPage { page },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_hero")),
                index: 0,
                node: artboard,
            },
            Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("artboard")),
                index: 0,
                node: photo,
            },
            Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("artboard")),
                index: 1,
                node: scrim,
            },
            Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("artboard")),
                index: 2,
                node: headline,
            },
        ])
        .expect("image hero scene builds");

    let record = hero_asset_record("hero_photo");
    scene.assets.insert(record.id.clone(), record);
    scene
}

fn render_svg(scene: &Scene) -> String {
    let request = ExportRequest {
        profile: ExportProfile {
            name: "image_golden".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        },
        page_ids: vec![PageId::from("page_hero")],
        purpose: ExportPurpose::UserDownload,
    };
    let resolver = Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        HERO_DIGEST,
        "image/png",
        HERO_PNG.to_vec(),
    ));
    let result = SvgExportAdapter::with_resolver(resolver)
        .export(scene, &request)
        .expect("exports");
    String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8 svg")
}

fn assert_golden(name: &str, svg: &str) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/goldens")
        .join(format!("{name}.svg"));
    if std::env::var("UPDATE_IMAGE_GOLDENS").is_ok() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, svg).unwrap();
        return;
    }
    let expected = std::fs::read_to_string(&path)
        .unwrap_or_else(|_| panic!("missing golden {path:?}; run with UPDATE_IMAGE_GOLDENS=1"));
    assert_eq!(
        svg, expected,
        "golden {name} drifted; regenerate intentionally with UPDATE_IMAGE_GOLDENS=1"
    );
}

#[test]
fn golden_image_hero_scrim() {
    let svg = render_svg(&image_hero_scene());

    // Contract guards (beyond the byte-exact golden) that name the idiom's
    // invariants so a drift reads as a meaningful change, not a mystery diff.
    assert!(
        svg.contains("data:image/png;base64,"),
        "the hero image must embed real bytes, not a placeholder: {svg}"
    );
    assert!(
        !svg.contains("data-lumen-unsupported=\"image\""),
        "resolved hero image must not fall back to a placeholder: {svg}"
    );
    // Cover fit at a non-centered focal point routes through the focal-crop path.
    assert!(
        svg.contains("data-lumen-image-fit=\"focal-crop\""),
        "cover + focal must render as a focal crop: {svg}"
    );
    // Z-order: image is painted before the scrim, which is painted before the
    // headline — the legibility stack.
    let photo = svg.find("data-lumen-node-id=\"photo\"").expect("photo node");
    let scrim = svg.find("data-lumen-node-id=\"scrim\"").expect("scrim node");
    let headline = svg
        .find("data-lumen-node-id=\"headline\"")
        .expect("headline node");
    assert!(
        photo < scrim && scrim < headline,
        "stack order must be image -> scrim -> headline: {svg}"
    );
    // The scrim is semi-transparent (the legibility veil), the headline opaque.
    assert!(
        svg.contains("opacity=\"0.56\""),
        "scrim must render at scrim opacity 0.56: {svg}"
    );

    assert_golden("image_hero_scrim", &svg);

    // Deterministic: rendering twice yields identical markup.
    let second = render_svg(&image_hero_scene());
    assert_eq!(svg, second, "image hero export must be deterministic");
}
