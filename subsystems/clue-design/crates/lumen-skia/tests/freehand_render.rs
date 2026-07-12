//! Phase 1d gate — the freehand render policy (user decision 2026-07-03,
//! from the Moda reference screenshots): a pinned node escapes every
//! ancestor mask and paints in a page-level pass above the in-flow content;
//! only the page clips it. Managed content keeps ancestor clip semantics.
//! Pinned by pixels on the Skia rasterizer and by markup order on the SVG
//! exporter so every export surface agrees.

use lumen_core::{
    layout_operations, Color, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, LayoutOptions, Node, NodeId, NodeKind, Operation,
    Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, PositionMode,
    RasterScale, Rect, Scene, SizeSpec, Unit,
};
use lumen_export::{LumenExportAdapter, SvgExportAdapter};
use lumen_skia::{FontManager, SkiaSceneRenderer, SkiaTextMeasurer};
use skia_safe::{surfaces, Data, Image};
use std::sync::Arc;

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

fn rect_node(id: &str, width: f64, height: f64, fill: &str) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.size = SizeSpec::fixed(width, height);
    node.fills = vec![solid_fill(&format!("paint_{id}"), fill)];
    node
}

fn insert(scene: &mut Scene, parent: ParentRef, node: Node) {
    let index = match &parent {
        ParentRef::Page(page_id) => scene.pages[page_id].children.len(),
        ParentRef::Node(node_id) => scene.nodes[node_id].children.len(),
    };
    scene
        .apply_operation(Operation::InsertNode {
            parent,
            index,
            node,
        })
        .unwrap();
}

/// 300×300 white page. A clipping gray card at (20,20,100,100) holds a blue
/// child that overflows its right edge (stays masked) and a red child
/// pinned at (200,200,50,40) — entirely outside the card. A green rect,
/// LATER in tree order, overlaps the pinned box at (195,195,60,60).
fn freehand_scene() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_freehand_render"), "Freehand Render");
    scene
        .apply_operation(Operation::AddPage {
            page: Page {
                id: PageId::from("page"),
                name: "Page".to_owned(),
                size: PageSize {
                    width: 300.0,
                    height: 300.0,
                    unit: Unit::Px,
                    preset: Some(PagePreset::Custom),
                    orientation: Orientation::Landscape,
                    source: None,
                    output: None,
                },
                children: Vec::new(),
                bleed: None,
                safe_area: None,
                background: vec![solid_fill("paint_page_bg", "#ffffff")],
            },
        })
        .unwrap();

    let mut card = Node::new(NodeId::from("card"), NodeKind::Frame);
    card.transform.x = 20.0;
    card.transform.y = 20.0;
    card.size = SizeSpec::fixed(100.0, 100.0);
    card.clip = true;
    card.fills = vec![solid_fill("paint_card", "#cccccc")];
    insert(&mut scene, ParentRef::Page(PageId::from("page")), card);

    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect_node("wide_managed", 150.0, 40.0, "#0000ff"),
    );

    let mut pinned = rect_node("pinned_out", 50.0, 40.0, "#ff0000");
    pinned.position_mode = PositionMode::Absolute;
    pinned.absolute_box = Some(Rect {
        x: 200.0,
        y: 200.0,
        width: 50.0,
        height: 40.0,
    });
    insert(&mut scene, ParentRef::Node(NodeId::from("card")), pinned);

    let mut cover = rect_node("cover", 60.0, 60.0, "#00ff00");
    cover.transform.x = 195.0;
    cover.transform.y = 195.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), cover);

    let operations = layout_operations(&scene, LayoutOptions::default());
    scene.apply_operations(operations).unwrap();
    scene
}

fn png_request() -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "freehand_preview".to_owned(),
            format: ExportFormat::Png,
            pdf_intent: None,
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(96),
            }),
            include_bleed: false,
            embed_fonts: true,
        include_marks: false,
        },
        page_ids: vec![PageId::from("page")],
        purpose: ExportPurpose::AgentCritique,
    }
}

fn svg_request() -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "freehand_svg".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        include_marks: false,
        },
        page_ids: vec![PageId::from("page")],
        purpose: ExportPurpose::AgentCritique,
    }
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
fn pinned_node_escapes_clipping_ancestor_and_paints_above_in_flow_content() {
    let scene = freehand_scene();
    let fonts = Arc::new(FontManager::bundled());
    let result = LumenExportAdapter::new()
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::new(fonts)))
        .export(&scene, &png_request())
        .expect("export");
    let png = &result.artifacts[0].bytes;

    // Managed masking intact: the blue child paints inside the card's clip
    // and its overflow past the card's right edge (x=120) is cut off.
    assert_eq!(pixel(png, 110, 30), [0, 0, 255, 255]);
    assert_eq!(pixel(png, 130, 30), [255, 255, 255, 255]);

    // The pinned child escaped the card's mask entirely — without the
    // page-level pass this pixel is green (or white pre-1b): the red box
    // is a child of the clipping card yet paints at its page-space pin,
    // above the green rect that comes later in tree order.
    assert_eq!(pixel(png, 225, 220), [255, 0, 0, 255]);
    // The green rect still paints where the pinned box does not cover it.
    assert_eq!(pixel(png, 252, 250), [0, 255, 0, 255]);
}

#[test]
fn svg_emits_pinned_nodes_after_in_flow_content_outside_clip_groups() {
    let scene = freehand_scene();
    let result = SvgExportAdapter::new()
        .export(&scene, &svg_request())
        .expect("export");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8 svg");

    // Managed clipping intact.
    assert!(svg.contains("clip-path=\"url(#"), "{svg}");

    // The pinned node is emitted after every in-flow element (page-level
    // pass), so it paints above the green rect that follows it in tree
    // order — and therefore outside the card's clip group.
    let red = svg.find("#ff0000").expect("pinned rect present");
    let green = svg.find("#00ff00").expect("cover rect present");
    let blue = svg.find("#0000ff").expect("managed child present");
    assert!(
        red > green && green > blue,
        "paint order must be blue (clipped) < green (in-flow) < red (pinned pass): {svg}"
    );

    // And its geometry is page-space at the pin.
    assert!(
        svg.contains("translate(200 200)") || svg.contains("translate(200, 200)"),
        "pinned node renders at its page-space box: {svg}"
    );
}
