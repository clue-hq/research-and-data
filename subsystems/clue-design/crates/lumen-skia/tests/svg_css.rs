//! CSS-bearing asset bytes must paint the same color in native previews and
//! exports as their equivalent presentation attributes, without rewriting the asset.

use base64::Engine;
use lumen_core::{
    AssetId, ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest, NodeId,
    PageId, PagePreset, RasterScale, Scene, SizeSpec, Transform, Unit,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter};
use lumen_skia::{rasterize_svg_thumbnail, SkiaSceneRenderer};
use skia_safe::{AlphaType, ColorType, Data, Image, ImageInfo};
use std::sync::Arc;

const CSS_MARK: &[u8] = br##"<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><style>.st0{fill:#C74634}</style><path class="st0" d="M4 4h24v24H4z"/></svg>"##;
const INLINE_MARK: &[u8] = br##"<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path fill="#C74634" d="M4 4h24v24H4z"/></svg>"##;

fn rgba(png: &[u8]) -> Vec<u8> {
    let image = Image::from_encoded(Data::new_copy(png)).expect("valid PNG");
    assert_eq!((image.width(), image.height()), (32, 32));
    let info = ImageInfo::new((32, 32), ColorType::RGBA8888, AlphaType::Unpremul, None);
    let mut pixels = vec![0; 32 * 32 * 4];
    assert!(image.read_pixels(
        &info,
        &mut pixels,
        32 * 4,
        (0, 0),
        skia_safe::image::CachingHint::Disallow,
    ));
    pixels
}

fn thumbnail(svg: &[u8]) -> Vec<u8> {
    let (png, width, height) = rasterize_svg_thumbnail(svg, 32, 32).expect("painted SVG");
    assert_eq!((width, height), (32, 32));
    rgba(&png)
}

fn asset_scene() -> Scene {
    let mut scene: Scene = serde_json::from_str(include_str!(
        "../../lumen-core/fixtures/conformance/phase_e_asset_scene.json"
    ))
    .unwrap();
    let image_id = NodeId::from("node_asset_logo");
    scene.nodes.retain(|id, _| id == &image_id);
    let image = scene.nodes.get_mut(&image_id).unwrap();
    image.size = SizeSpec::fixed(32.0, 32.0);
    image.transform = Transform::default();
    image.asset_placement = None;
    let page = scene.pages.get_mut(&PageId::from("page_a4")).unwrap();
    page.children = vec![image_id];
    page.size.width = 32.0;
    page.size.height = 32.0;
    page.size.unit = Unit::Px;
    page.size.preset = Some(PagePreset::Custom);
    page.safe_area = None;
    scene
}

fn request(format: ExportFormat) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "svg_css".to_owned(),
            format,
            pdf_intent: None,
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(96),
            }),
            include_bleed: false,
            embed_fonts: false,
            include_marks: false,
            imposition: None,
            proof: false,
            color: None,
        },
        page_ids: vec![PageId::from("page_a4")],
        purpose: ExportPurpose::AgentCritique,
    }
}

fn export_png(svg: &[u8]) -> Vec<u8> {
    let resolver = FixtureAssetResolver::new().with_asset_bytes(
        AssetId::from("asset_uploaded_logo"),
        "image/svg+xml",
        svg,
    );
    let exported = LumenExportAdapter::with_resolver(Arc::new(resolver))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::bundled()))
        .export(&asset_scene(), &request(ExportFormat::Png))
        .expect("native export");
    rgba(&exported.artifacts[0].bytes)
}

fn assert_red_mark(pixels: &[u8]) {
    // Literal source color, sampled well inside the path; removing CSS handling
    // turns this pixel opaque black in Skia even though parsing succeeds.
    assert_eq!(&pixels[(16 * 32 + 16) * 4..][..4], &[199, 70, 52, 255]);
}

#[test]
fn css_class_thumbnail_matches_inline_fill_pixels() {
    let inline = thumbnail(INLINE_MARK);
    assert_red_mark(&inline);
    assert_eq!(&inline[..4], &[0, 0, 0, 0]);
    let styled = thumbnail(CSS_MARK);
    assert_red_mark(&styled);
    assert_eq!(styled, inline);
}

#[test]
fn css_class_native_png_export_matches_inline_fill_pixels() {
    let inline = export_png(INLINE_MARK);
    assert_red_mark(&inline);
    let styled = export_png(CSS_MARK);
    assert_red_mark(&styled);
    assert_eq!(styled, inline);
}

#[test]
fn svg_styles_obey_cascade_and_inheritance_when_rasterized() {
    // Each case names a renderer break: stylesheet omission, lost selector
    // specificity/source order, attribute-order dependence, or lost inheritance.
    let cases = [
        ("group inheritance", "<style>.brand{fill:#C74634}</style><g class=\"brand\"><path d=\"M4 4h24v24H4z\"/></g>"),
        ("inline style before presentation attribute", "<style>.brand{fill:blue}</style><path class=\"brand\" style=\"fill:#C74634\" fill=\"green\" d=\"M4 4h24v24H4z\"/>"),
        ("important beats inline", "<style>.brand{fill:#C74634!important}</style><path class=\"brand\" style=\"fill:blue\" d=\"M4 4h24v24H4z\"/>"),
        ("inline important beats stylesheet important", "<style>#mark{fill:blue!important}</style><path id=\"mark\" style=\"fill:#C74634!important\" d=\"M4 4h24v24H4z\"/>"),
        ("id specificity beats later class", "<style>#mark{fill:#C74634}.brand{fill:blue}</style><path id=\"mark\" class=\"brand\" d=\"M4 4h24v24H4z\"/>"),
        ("later stylesheet wins equal specificity", "<style>.brand{fill:blue}</style><style><![CDATA[.brand { fill: #C74634; }]]></style><path class=\"brand\" d=\"M4 4h24v24H4z\"/>"),
        ("child selector and inherited currentColor", "<style>g.brand > path {fill:currentColor} .brand{color:#C74634}</style><g class=\"brand\"><path d=\"M4 4h24v24H4z\"/></g>"),
        ("invalid later declaration retains valid fill", "<style>.brand{fill:#C74634;fill:invalid-color}</style><path class=\"brand\" d=\"M4 4h24v24H4z\"/>"),
    ];
    let expected = thumbnail(INLINE_MARK);
    for (name, content) in cases {
        let svg = format!("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"32\" viewBox=\"0 0 32 32\">{content}</svg>");
        let actual = thumbnail(svg.as_bytes());
        assert_eq!(
            &actual[(16 * 32 + 16) * 4..][..4],
            &[199, 70, 52, 255],
            "{name}"
        );
        assert_eq!(actual, expected, "{name}");
    }
}

#[test]
fn inline_style_svg_with_a_doctype_keeps_existing_pixels() {
    let svg = br##"<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><path style="fill:#C74634" d="M4 4h24v24H4z"/></svg>"##;
    assert_eq!(thumbnail(svg), thumbnail(INLINE_MARK));
}

#[test]
fn embedded_styles_work_without_an_explicit_svg_namespace() {
    let svg = br##"<svg width="32" height="32"><style>.mark{fill:#C74634}</style><path class="mark" d="M4 4h24v24H4z"/></svg>"##;
    assert_eq!(thumbnail(svg), thumbnail(INLINE_MARK));
}

#[test]
fn svg_export_keeps_the_authentic_asset_bytes_after_native_rendering() {
    let scene = asset_scene();
    let original_scene = scene.clone();
    let adapter =
        LumenExportAdapter::with_resolver(Arc::new(FixtureAssetResolver::new().with_asset_bytes(
            AssetId::from("asset_uploaded_logo"),
            "image/svg+xml",
            CSS_MARK,
        )))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::bundled()));
    adapter.export(&scene, &request(ExportFormat::Png)).unwrap();
    let exported = adapter.export(&scene, &request(ExportFormat::Svg)).unwrap();
    let xml =
        roxmltree::Document::parse(std::str::from_utf8(&exported.artifacts[0].bytes).unwrap())
            .unwrap();
    let image = xml
        .descendants()
        .find(|node| node.has_tag_name("image"))
        .unwrap();
    let uri = image
        .attribute("href")
        .or_else(|| image.attribute(("http://www.w3.org/1999/xlink", "href")))
        .unwrap();
    let encoded = uri.strip_prefix("data:image/svg+xml;base64,").unwrap();
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(encoded)
        .unwrap();
    assert_eq!(decoded, CSS_MARK);
    assert_eq!(scene, original_scene);
}
