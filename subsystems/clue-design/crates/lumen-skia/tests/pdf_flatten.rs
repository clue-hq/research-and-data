//! Print W0 gates: bleed-region rasterization and the raster-flattened PDF
//! seam (`ScenePdfRenderer`) over the real Skia renderer.

use lumen_core::{
    Color, ComputedGeometry, DocumentId, Fill, Node, NodeId, NodeKind, Orientation, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, Rect, Scene, SizeSpec, Unit,
};
use lumen_export::ScenePdfRenderer;
use lumen_skia::{raster_flattened_pdf, SkiaSceneRenderer};
use skia_safe::{surfaces, Data, Image};

fn solid_fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.to_owned(),
            },
        },
    }
}

/// 100×100 px page with a red background and a 20×20 blue rect at the
/// page origin — the corner probe for full-bleed vs content placement.
fn bleed_probe_scene(bleed: Option<Rect>) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_bleed_probe"), "Bleed Probe");
    scene.pages.insert(
        PageId::from("page_bleed"),
        Page {
            id: PageId::from("page_bleed"),
            name: "Bleed".to_owned(),
            size: PageSize {
                width: 100.0,
                height: 100.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Portrait,
                source: None,
                output: None,
            },
            children: vec![NodeId::from("node_corner_rect")],
            bleed,
            safe_area: None,
            background: vec![solid_fill("paint_page_bg", "#ff0000")],
        },
    );
    let mut node = Node::new(NodeId::from("node_corner_rect"), NodeKind::Rect);
    node.size = SizeSpec::fixed(20.0, 20.0);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 20.0,
            height: 20.0,
        },
        render_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 20.0,
            height: 20.0,
        },
        text_lines: Vec::new(),
    });
    node.fills = vec![solid_fill("paint_corner_rect", "#0000ff")];
    scene.nodes.insert(node.id.clone(), node);
    scene
}

fn pixel(png: &[u8], x: i32, y: i32) -> [u8; 4] {
    let image = Image::from_encoded(Data::new_copy(png)).expect("png decodes");
    let info = skia_safe::ImageInfo::new(
        (image.width(), image.height()),
        skia_safe::ColorType::RGBA8888,
        skia_safe::AlphaType::Unpremul,
        None,
    );
    let mut pixels = vec![0u8; (image.width() * image.height() * 4) as usize];
    let row_bytes = (image.width() * 4) as usize;
    let mut surface =
        surfaces::raster_n32_premul((image.width(), image.height())).expect("surface");
    surface.canvas().draw_image(&image, (0, 0), None);
    assert!(surface.image_snapshot().read_pixels(
        &info,
        &mut pixels,
        row_bytes,
        (0, 0),
        skia_safe::image::CachingHint::Disallow
    ));
    let index = ((y * image.width() + x) * 4) as usize;
    [
        pixels[index],
        pixels[index + 1],
        pixels[index + 2],
        pixels[index + 3],
    ]
}

#[test]
fn bleed_region_raster_paints_background_across_bleed_and_offsets_content() {
    let scene = bleed_probe_scene(None);
    let renderer = SkiaSceneRenderer::bundled();
    let region = Rect {
        x: -6.0,
        y: -6.0,
        width: 112.0,
        height: 112.0,
    };

    let raster = renderer
        .rasterize_page_region(&scene, &PageId::from("page_bleed"), &region, 112, 112, None)
        .expect("region raster");

    // The bleed margin carries the page background (full-bleed semantics),
    // not blank paper.
    assert_eq!(pixel(&raster.png, 2, 2), [255, 0, 0, 255]);
    // Content stays in page space: the origin-anchored rect starts at the
    // +6px region offset.
    assert_eq!(pixel(&raster.png, 8, 8), [0, 0, 255, 255]);
    assert_eq!(pixel(&raster.png, 4, 4), [255, 0, 0, 255]);
}

#[test]
fn flattened_pdf_expands_page_box_to_bleed_and_stays_deterministic() {
    let bleed = Some(Rect {
        x: -6.0,
        y: -6.0,
        width: 112.0,
        height: 112.0,
    });
    let scene = bleed_probe_scene(bleed);
    let renderer = SkiaSceneRenderer::bundled();

    // The engine maps Px 1:1 to pt (unit_to_points): trim 100px = 100pt,
    // bleed box 112px = 112pt — the same MediaBox contract as the vector
    // writer's PdfPageBox::for_page.
    let trimmed = raster_flattened_pdf(&renderer, &scene, &[], 72, false, false, None, None).expect("trim pdf");
    assert_eq!(trimmed.pages[0].width_pt, 100.0);
    assert_eq!(trimmed.pages[0].width_px, 100);

    let bled = raster_flattened_pdf(&renderer, &scene, &[], 72, true, false, None, None).expect("bleed pdf");
    assert!(bled.bytes.starts_with(b"%PDF"));
    assert_eq!(bled.pages[0].width_pt, 112.0);
    assert_eq!(bled.pages[0].height_pt, 112.0);
    assert_eq!(bled.pages[0].width_px, 112);

    let again = raster_flattened_pdf(&renderer, &scene, &[], 72, true, false, None, None).expect("bleed pdf 2");
    assert_eq!(bled.bytes, again.bytes, "flattened PDF must be deterministic");
}

#[test]
fn skia_renderer_implements_the_pdf_flattener_seam() {
    let scene = bleed_probe_scene(None);
    let renderer = SkiaSceneRenderer::bundled();
    let via_trait = (&renderer as &dyn ScenePdfRenderer)
        .render_pdf(
            &scene,
            &[PageId::from("page_bleed")],
            &lumen_export::PdfRenderOptions {
                dpi: 72,
                include_bleed: false,
                include_marks: false,
                booklet: false,
                proof_label: None,
            },
            None,
        )
        .expect("trait flatten");
    let direct = raster_flattened_pdf(
        &renderer,
        &scene,
        &[PageId::from("page_bleed")],
        72,
        false,
        false,
        None,
        None,
    )
    .expect("direct flatten");
    assert_eq!(via_trait.bytes, direct.bytes);
    assert_eq!(via_trait.pages, direct.pages);
}
