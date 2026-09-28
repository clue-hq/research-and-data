//! `SkiaSceneRenderer` (slice A3): direct scene→Skia painting for PNG
//! export and critic previews.
//!
//! This is the first instance of the write-once paint translation: the
//! renderer consumes the same scene + computed geometry the SVG exporter
//! consumes (`render_box_for_node`), shares the exact SkParagraph
//! construction with the A2 measurer (single source of truth for text line
//! breaks), and mirrors the SVG renderer's semantics for paint stacks,
//! gradients, dash/cap/join, layered shadows with spread, and Phase E
//! image placement (contain/cover/focal crop).
//!
//! Rasterization is pinned to the CPU backend (`surfaces::raster_n32_premul`)
//! so golden PNGs are machine-independent for a given Skia version + font
//! bytes.

use crate::fonts::FontManager;
use crate::measure::{
    build_paragraph, default_foreground, font_diagnostics, glyph_diagnostics, normalize_content,
    ParagraphRequest, ParagraphSegment, UNBOUNDED_LAYOUT_WIDTH,
};
use lumen_core::{
    normalize_content_mapped, page_geometry, paints_out_of_tree, pinned_paint_pass,
    render_box_for_node, transform_segments, valign_offset, Color, CornerRadii, Diagnostic,
    DiagnosticSubject, EffectKind, ImageFitMode, ImageNode, Node, NodeId, NodeKind, Page, PageId,
    Paint, Phase, Scene, Stroke, StrokeAlign, StrokeCap, StrokeJoin, TextAlign, TextNode, TextWrap,
    VerticalAlign,
};
use lumen_export::{
    focal_crop_geometry, page_background_token_diagnostics, unresolved_brand_token_diagnostics,
    AssetByteResolver, PageRasterizer, RasterizeError, RasterizedPage, ResolvedAssetBytes,
};
use skia_safe::canvas::SaveLayerRec;
use skia_safe::textlayout::TextAlign as SkTextAlign;
use skia_safe::{
    gradient, image_filters, surfaces, Canvas, Color4f, Data, EncodedImageFormat, Image,
    ImageFilter, Matrix, Paint as SkPaint, PaintCap, PaintJoin, PaintStyle, PathEffect, Point,
    RRect, Rect as SkRect, SamplingOptions, Shader, TileMode,
};
use std::sync::Arc;

/// Opaque magenta "missing paint" marker. Universally read as a rendering
/// fault (the classic missing-texture color) and fully opaque so it can never
/// itself read as black. Painted in place of any specified paint that fails to
/// resolve at raster, alongside the LUME0213 error.
const UNRESOLVED_PAINT_SENTINEL: Color4f = Color4f {
    r: 1.0,
    g: 0.0,
    b: 1.0,
    a: 1.0,
};

/// Direct scene rasterizer over the deterministic font set. Stateless apart
/// from the shared `FontManager`; safe to share across threads.
#[derive(Clone, Debug)]
pub struct SkiaSceneRenderer {
    fonts: Arc<FontManager>,
}

impl SkiaSceneRenderer {
    pub fn new(fonts: Arc<FontManager>) -> Self {
        Self { fonts }
    }

    /// Renderer over the bundled deterministic font set.
    pub fn bundled() -> Self {
        Self::new(Arc::new(FontManager::bundled()))
    }

    pub fn fonts(&self) -> &Arc<FontManager> {
        &self.fonts
    }
}

impl PageRasterizer for SkiaSceneRenderer {
    fn rasterize_page(
        &self,
        scene: &Scene,
        page_id: &PageId,
        width_px: u32,
        height_px: u32,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RasterizedPage, RasterizeError> {
        let page = scene.pages.get(page_id).ok_or_else(|| {
            RasterizeError::new(
                "raster.page_missing",
                format!("page {page_id} is not in the scene"),
            )
        })?;
        let region = page_geometry(page).layout;
        self.rasterize_page_region(scene, page_id, &region, width_px, height_px, resolver)
    }
}

impl SkiaSceneRenderer {
    /// Rasterize an arbitrary page-space region (layout units) at the given
    /// pixel size. The region may extend beyond the page rect — the bleed
    /// box for print export is the motivating case — in which case page
    /// background fills paint across the whole region (full-bleed
    /// semantics, matching the vector PDF writer's bleed MediaBox fill) and
    /// content nodes paint at their page-space positions, so edge-touching
    /// art that extends past trim is included.
    pub fn rasterize_page_region(
        &self,
        scene: &Scene,
        page_id: &PageId,
        region: &lumen_core::Rect,
        width_px: u32,
        height_px: u32,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RasterizedPage, RasterizeError> {
        self.rasterize_page_region_with(scene, page_id, region, width_px, height_px, resolver, None)
    }

    /// [`Self::rasterize_page_region`] plus optional crop marks (print
    /// W2/W3): the flattened PDF path rasterizes marks into the page image.
    #[allow(clippy::too_many_arguments)]
    pub fn rasterize_page_region_with(
        &self,
        scene: &Scene,
        page_id: &PageId,
        region: &lumen_core::Rect,
        width_px: u32,
        height_px: u32,
        resolver: Option<&dyn AssetByteResolver>,
        overlay: Option<&PrintOverlay>,
    ) -> Result<RasterizedPage, RasterizeError> {
        let page = scene.pages.get(page_id).ok_or_else(|| {
            RasterizeError::new(
                "raster.page_missing",
                format!("page {page_id} is not in the scene"),
            )
        })?;

        lumen_export::ensure_raster_within_budget(
            width_px,
            height_px,
            &format!("rasterizing page {page_id}"),
        )?;

        let width = i32::try_from(width_px.max(1))
            .map_err(|_| RasterizeError::new("raster.size_invalid", "raster width exceeds i32"))?;
        let height = i32::try_from(height_px.max(1))
            .map_err(|_| RasterizeError::new("raster.size_invalid", "raster height exceeds i32"))?;

        // CPU backend, pinned: no GPU surface anywhere in this crate.
        let mut surface = surfaces::raster_n32_premul((width, height)).ok_or_else(|| {
            RasterizeError::new(
                "raster.surface_alloc_failed",
                format!("could not allocate {width}x{height} CPU raster surface"),
            )
        })?;

        let diagnostics = self.paint_page_region_onto(
            scene,
            page,
            region,
            surface.canvas(),
            width as f32,
            height as f32,
            resolver,
            overlay,
        );

        let image = surface.image_snapshot();
        let png = image
            .encode(None, EncodedImageFormat::PNG, Some(100))
            .ok_or_else(|| {
                RasterizeError::new("raster.png_encode_failed", "PNG encoding failed")
            })?;

        Ok(RasterizedPage {
            png: png.as_bytes().to_vec(),
            diagnostics,
        })
    }

    /// Paint one page region onto an arbitrary canvas — a raster surface or
    /// a PDF document page. `target_width`/`target_height` are in the
    /// canvas's own units (pixels for rasters, points for PDF pages); the
    /// layout-space region maps onto that extent.
    ///
    /// Opaque white "paper" is painted first, as a rect rather than
    /// `canvas.clear` because clear is a raster-backend concept a PDF canvas
    /// does not honor. A page is a physical artboard: every spot not covered
    /// by a resolved paint must read as blank paper, never black — an
    /// unpainted premultiplied surface is alpha-0 (RGB 0), which flattens to
    /// solid black in any viewer or critic that composites onto black (the
    /// empty-page and collapsed-token "black PNG" class). Declared page
    /// backgrounds and node fills still paint on top.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn paint_page_region_onto(
        &self,
        scene: &Scene,
        page: &Page,
        region: &lumen_core::Rect,
        canvas: &Canvas,
        target_width: f32,
        target_height: f32,
        resolver: Option<&dyn AssetByteResolver>,
        overlay: Option<&PrintOverlay>,
    ) -> Vec<Diagnostic> {
        let mut painter = PagePainter {
            scene,
            fonts: &self.fonts,
            resolver,
            diagnostics: Vec::new(),
        };

        canvas.save();
        let mut paper = SkPaint::default();
        paper.set_color(skia_safe::Color::WHITE);
        canvas.draw_rect(SkRect::from_wh(target_width, target_height), &paper);
        canvas.scale((
            target_width / region.width.max(1.0) as f32,
            target_height / region.height.max(1.0) as f32,
        ));
        canvas.translate((-region.x as f32, -region.y as f32));
        // Content paints only inside the bleed area (the print margin must
        // stay ink-free apart from marks and proof decor).
        if let Some(overlay) = overlay {
            let marks = &overlay.marks;
            canvas.save();
            canvas.clip_rect(
                SkRect::from_xywh(
                    marks.bleed.x as f32,
                    marks.bleed.y as f32,
                    marks.bleed.width as f32,
                    marks.bleed.height as f32,
                ),
                skia_safe::ClipOp::Intersect,
                true,
            );
            painter.paint_page(canvas, page, region);
            canvas.restore();
            draw_crop_marks(canvas, marks);
            if let Some(slug) = &overlay.slug {
                self.draw_proof_decor(canvas, marks, slug);
            }
        } else {
            painter.paint_page(canvas, page, region);
        }
        canvas.restore();

        painter.diagnostics
    }
}

impl SkiaSceneRenderer {
    /// Paint one page's trim content into a slot rect on an existing canvas
    /// (print W4 imposition): clip to the slot, map the page's layout space
    /// onto it, paint. No paper fill — the sheet painter owns the paper.
    pub(crate) fn paint_page_in_slot(
        &self,
        scene: &Scene,
        page: &Page,
        canvas: &Canvas,
        slot: SkRect,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Vec<Diagnostic> {
        let region = page_geometry(page).layout;
        let mut painter = PagePainter {
            scene,
            fonts: &self.fonts,
            resolver,
            diagnostics: Vec::new(),
        };
        canvas.save();
        canvas.clip_rect(slot, skia_safe::ClipOp::Intersect, true);
        canvas.translate((slot.left, slot.top));
        canvas.scale((
            slot.width() / region.width.max(1.0) as f32,
            slot.height() / region.height.max(1.0) as f32,
        ));
        painter.paint_page(canvas, page, &region);
        canvas.restore();
        painter.diagnostics
    }
}

/// Crop-mark geometry in layout coordinates (print W2/W3): `trim` is the
/// cut line, `bleed` the ink boundary; marks draw OUTSIDE the bleed, from
/// `gap` beyond it out to `margin` beyond it, aligned with the trim edges.
#[derive(Clone, Debug)]
pub struct CropMarks {
    pub trim: lumen_core::Rect,
    pub bleed: lumen_core::Rect,
    pub margin: f64,
    pub gap: f64,
    pub stroke_width: f64,
}

/// Print-margin decor for one page (W2 marks / W7 proof): crop marks
/// always; proof mode adds a slug line and an sRGB control strip in the
/// bottom margin strip.
#[derive(Clone, Debug)]
pub struct PrintOverlay {
    pub marks: CropMarks,
    /// Fully formatted slug ("doc · profile · page n/N · PROOF …");
    /// Some ⇒ proof mode (slug + control strip).
    pub slug: Option<String>,
}

/// sRGB control strip patches: black, 75/50/25% grays, then the additive
/// and subtractive primaries — enough to spot channel drift and tone
/// response on a physical proof of an sRGB-workflow file.
const CONTROL_STRIP: [skia_safe::Color; 10] = [
    skia_safe::Color::new(0xff000000),
    skia_safe::Color::new(0xff404040),
    skia_safe::Color::new(0xff808080),
    skia_safe::Color::new(0xffc0c0c0),
    skia_safe::Color::new(0xff00ffff),
    skia_safe::Color::new(0xffff00ff),
    skia_safe::Color::new(0xffffff00),
    skia_safe::Color::new(0xffff0000),
    skia_safe::Color::new(0xff00ff00),
    skia_safe::Color::new(0xff0000ff),
];

impl SkiaSceneRenderer {
    /// Slug line bottom-left, control strip bottom-right — both inside the
    /// bottom margin strip, outside the bleed, in layout coordinates.
    fn draw_proof_decor(&self, canvas: &Canvas, marks: &CropMarks, slug: &str) {
        let bleed_bottom = marks.bleed.y + marks.bleed.height;
        let strip_height = (marks.margin * 0.45) as f32;
        let strip_y = (bleed_bottom + marks.margin * 0.2) as f32;

        // Control strip, right-aligned to the trim's right edge.
        let patch_width = (marks.margin * 1.1) as f32;
        let trim_right = (marks.trim.x + marks.trim.width) as f32;
        let mut paint = SkPaint::default();
        paint.set_anti_alias(false);
        for (index, color) in CONTROL_STRIP.iter().enumerate() {
            paint.set_color(*color);
            let x = trim_right - (CONTROL_STRIP.len() - index) as f32 * patch_width;
            canvas.draw_rect(
                SkRect::from_xywh(x, strip_y, patch_width, strip_height),
                &paint,
            );
        }

        // Slug line, left-aligned to the trim's left edge.
        let family = self.fonts.default_family().to_owned();
        if let Some(typeface) = self.fonts.match_typeface(&family, 500, false) {
            let size = (marks.margin * 0.5) as f32;
            let font = skia_safe::Font::new(typeface, size);
            let mut text_paint = SkPaint::default();
            text_paint.set_color(skia_safe::Color::BLACK);
            text_paint.set_anti_alias(true);
            canvas.draw_str(
                slug,
                (marks.trim.x as f32, strip_y + strip_height * 0.85),
                &font,
                &text_paint,
            );
        }
    }
}

fn draw_crop_marks(canvas: &Canvas, marks: &CropMarks) {
    let mut paint = SkPaint::default();
    paint.set_color(skia_safe::Color::BLACK);
    paint.set_style(PaintStyle::Stroke);
    paint.set_stroke_width(marks.stroke_width as f32);
    paint.set_anti_alias(true);

    for ((x0, y0), (x1, y1)) in crop_mark_segments(marks) {
        canvas.draw_line(
            Point::new(x0 as f32, y0 as f32),
            Point::new(x1 as f32, y1 as f32),
            &paint,
        );
    }
}

/// The mark strokes for one page, in layout coordinates. Pure geometry so
/// the mark set is testable without rasterizing.
pub(crate) fn crop_mark_segments(marks: &CropMarks) -> Vec<((f64, f64), (f64, f64))> {
    let trim = &marks.trim;
    let bleed = &marks.bleed;
    let trim_right = trim.x + trim.width;
    let trim_bottom = trim.y + trim.height;
    let bleed_right = bleed.x + bleed.width;
    let bleed_bottom = bleed.y + bleed.height;

    // Trim (crop) marks: horizontal segments aligned with trim top/bottom
    // outside the left/right bleed edges, vertical segments aligned with
    // trim left/right outside the top/bottom bleed edges — two marks per
    // corner, eight total.
    let mut segments: Vec<((f64, f64), (f64, f64))> = vec![
        ((bleed.x - marks.margin, trim.y), (bleed.x - marks.gap, trim.y)),
        ((bleed_right + marks.gap, trim.y), (bleed_right + marks.margin, trim.y)),
        ((bleed.x - marks.margin, trim_bottom), (bleed.x - marks.gap, trim_bottom)),
        ((bleed_right + marks.gap, trim_bottom), (bleed_right + marks.margin, trim_bottom)),
        ((trim.x, bleed.y - marks.margin), (trim.x, bleed.y - marks.gap)),
        ((trim.x, bleed_bottom + marks.gap), (trim.x, bleed_bottom + marks.margin)),
        ((trim_right, bleed.y - marks.margin), (trim_right, bleed.y - marks.gap)),
        ((trim_right, bleed_bottom + marks.gap), (trim_right, bleed_bottom + marks.margin)),
    ];
    // Bleed marks (prepress convention, e.g. InDesign "Include Bleed
    // Marks"): the same tick shape aligned with the BLEED edges, so the
    // operator sees both boundaries. Only meaningful when the bleed box
    // actually differs from the trim (proof mode on a bleed-less page has
    // bleed == trim — a second identical set would just thicken the crop
    // marks).
    let has_distinct_bleed = (bleed.x - trim.x).abs() > f64::EPSILON
        || (bleed.y - trim.y).abs() > f64::EPSILON
        || (bleed.width - trim.width).abs() > f64::EPSILON
        || (bleed.height - trim.height).abs() > f64::EPSILON;
    if has_distinct_bleed {
        segments.extend([
            ((bleed.x - marks.margin, bleed.y), (bleed.x - marks.gap, bleed.y)),
            ((bleed_right + marks.gap, bleed.y), (bleed_right + marks.margin, bleed.y)),
            ((bleed.x - marks.margin, bleed_bottom), (bleed.x - marks.gap, bleed_bottom)),
            ((bleed_right + marks.gap, bleed_bottom), (bleed_right + marks.margin, bleed_bottom)),
            ((bleed.x, bleed.y - marks.margin), (bleed.x, bleed.y - marks.gap)),
            ((bleed.x, bleed_bottom + marks.gap), (bleed.x, bleed_bottom + marks.margin)),
            ((bleed_right, bleed.y - marks.margin), (bleed_right, bleed.y - marks.gap)),
            ((bleed_right, bleed_bottom + marks.gap), (bleed_right, bleed_bottom + marks.margin)),
        ]);
    }
    segments
}

struct PagePainter<'a> {
    scene: &'a Scene,
    fonts: &'a FontManager,
    resolver: Option<&'a dyn AssetByteResolver>,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> PagePainter<'a> {
    fn paint_page(&mut self, canvas: &Canvas, page: &Page, background_region: &lumen_core::Rect) {
        self.diagnostics
            .extend(page_background_token_diagnostics(page));
        let geometry = page_geometry(page);
        // Background fills cover the whole requested region (= the page rect
        // for plain rasters, the bleed box for print regions). Gradient
        // geometry stays sized to the page, so the bleed margin continues
        // the edge colors instead of rescaling the ramp.
        let background_rect = SkRect::from_xywh(
            background_region.x as f32,
            background_region.y as f32,
            background_region.width as f32,
            background_region.height as f32,
        );
        for fill in &page.background {
            let paint = self.fill_paint(
                &fill.paint,
                geometry.layout.width,
                geometry.layout.height,
                None,
            );
            canvas.draw_rect(background_rect, &paint);
        }

        for child_id in &page.children {
            if self.skips_inline_paint(child_id) {
                continue;
            }
            self.paint_node(canvas, child_id, None);
        }

        // Phase 1d freehand: pinned nodes escape every ancestor mask (only
        // the page clips — the Moda model). Inline painting skipped them;
        // they paint here in document order, above the in-flow content,
        // from page space (their computed geometry is page-space already).
        for node_id in pinned_paint_pass(self.scene, page) {
            self.paint_node(canvas, &node_id, None);
        }
    }

    /// Pinned nodes never paint inside their parent's tree — see
    /// [`pinned_paint_pass`].
    fn skips_inline_paint(&self, node_id: &NodeId) -> bool {
        self.scene
            .nodes
            .get(node_id)
            .is_some_and(paints_out_of_tree)
    }

    fn paint_node(
        &mut self,
        canvas: &Canvas,
        node_id: &NodeId,
        parent_computed_origin: Option<(f64, f64)>,
    ) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            self.diagnostics.push(Diagnostic::error(
                Phase::Export,
                "LUME0102",
                format!("scene references missing node {node_id}"),
                None,
            ));
            return;
        };

        self.diagnostics
            .extend(unresolved_brand_token_diagnostics(node));

        let render_box = render_box_for_node(node, parent_computed_origin);
        let width = render_box.width;
        let height = render_box.height;
        let child_parent_origin = node
            .computed
            .as_ref()
            .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));

        canvas.save();
        // Mirror the SVG transform list order exactly:
        // translate, rotate, skewX, skewY, scale(flip).
        canvas.translate((render_box.x as f32, render_box.y as f32));
        if node.transform.rotation != 0.0 {
            canvas.rotate(node.transform.rotation as f32, None);
        }
        if node.transform.skew_x != 0.0 {
            canvas.skew((node.transform.skew_x.to_radians().tan() as f32, 0.0));
        }
        if node.transform.skew_y != 0.0 {
            canvas.skew((0.0, node.transform.skew_y.to_radians().tan() as f32));
        }
        if node.transform.flip_x || node.transform.flip_y {
            canvas.scale((
                if node.transform.flip_x { -1.0 } else { 1.0 },
                if node.transform.flip_y { -1.0 } else { 1.0 },
            ));
        }

        // Group opacity + layered shadows ride one save_layer, matching the
        // SVG renderer's group-level opacity/filter attributes.
        let shadow_filter = self.effect_image_filter(node);
        let needs_layer = node.opacity < 1.0 || shadow_filter.is_some();
        if needs_layer {
            let mut layer_paint = SkPaint::default();
            layer_paint.set_alpha_f(node.opacity.clamp(0.0, 1.0) as f32);
            if let Some(filter) = shadow_filter {
                layer_paint.set_image_filter(filter);
            }
            canvas.save_layer(&SaveLayerRec::default().paint(&layer_paint));
        }

        match &node.kind {
            NodeKind::Frame | NodeKind::AutoLayout(_) => {
                self.paint_rect_geometry(canvas, node, width, height);
                if node.clip {
                    canvas.save();
                    canvas.clip_rrect(corner_rrect(node, width, height), None, true);
                }
                for child_id in &node.children {
                    if self.skips_inline_paint(child_id) {
                        continue;
                    }
                    self.paint_node(canvas, child_id, child_parent_origin);
                }
                if node.clip {
                    canvas.restore();
                }
            }
            NodeKind::Group => {
                for child_id in &node.children {
                    if self.skips_inline_paint(child_id) {
                        continue;
                    }
                    self.paint_node(canvas, child_id, child_parent_origin);
                }
            }
            NodeKind::Rect => {
                self.paint_rect_geometry(canvas, node, width, height);
            }
            NodeKind::Ellipse => {
                let rect = SkRect::from_wh(width as f32, height as f32);
                for fill in &node.fills {
                    let paint = self.fill_paint(&fill.paint, width, height, Some(&node.id));
                    canvas.draw_oval(rect, &paint);
                }
                for stroke in &node.strokes {
                    let paint = self.stroke_paint(stroke, width, height, Some(&node.id), true);
                    let oval = aligned_rect(rect, stroke);
                    canvas.draw_oval(oval, &paint);
                }
            }
            NodeKind::Line(line) => {
                let from = Point::new(0.0, 0.0);
                let to = Point::new(line.x2 as f32, line.y2 as f32);
                for stroke in &node.strokes {
                    let paint = self.stroke_paint(stroke, width, height, Some(&node.id), false);
                    canvas.draw_line(from, to, &paint);
                }
            }
            NodeKind::Vector(vector) => {
                if let Some(path) = skia_safe::utils::parse_path::from_svg(&vector.path_data) {
                    // A library icon carries its source viewBox: scale the path uniformly
                    // and center it within the node box (so an icon renders at the node's
                    // size, not its intrinsic 24px). Hand-authored vectors (view_box None)
                    // draw at raw node-local coordinates, unchanged.
                    let scaled = icon_fit_matrix(vector.view_box, width, height);
                    if let Some(matrix) = scaled {
                        canvas.save();
                        canvas.concat(&matrix);
                    }
                    for fill in &node.fills {
                        let paint = self.fill_paint(&fill.paint, width, height, Some(&node.id));
                        canvas.draw_path(&path, &paint);
                    }
                    for stroke in &node.strokes {
                        let paint = self.stroke_paint(stroke, width, height, Some(&node.id), false);
                        canvas.draw_path(&path, &paint);
                    }
                    if scaled.is_some() {
                        canvas.restore();
                    }
                } else {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Export,
                        "LUME0204",
                        format!("vector node {} has unparseable path data", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            NodeKind::Text(text) => {
                self.paint_text(canvas, node, text, width, height);
            }
            NodeKind::Image(image) => {
                self.paint_image(canvas, node, image, width, height);
            }
            NodeKind::Instance { source_node_id } => {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0203",
                    format!(
                        "instance node {} references source {} but instance expansion is not implemented",
                        node.id, source_node_id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ).with_hint("Expand instances in core or provide an instance resolver before export."));
            }
        }

        if needs_layer {
            canvas.restore();
        }
        canvas.restore();
    }

    /// Rect-shaped fills/strokes (Rect nodes and Frame/AutoLayout
    /// backgrounds): full paint stacks in order, corner radii, native
    /// inside/outside stroke alignment (cheap for rects).
    fn paint_rect_geometry(&mut self, canvas: &Canvas, node: &Node, width: f64, height: f64) {
        let rect = SkRect::from_wh(width as f32, height as f32);
        for fill in &node.fills {
            let paint = self.fill_paint(&fill.paint, width, height, Some(&node.id));
            canvas.draw_rrect(corner_rrect(node, width, height), &paint);
        }
        for stroke in &node.strokes {
            let paint = self.stroke_paint(stroke, width, height, Some(&node.id), true);
            let stroke_rect = aligned_rect(rect, stroke);
            let rrect = corner_rrect_for(stroke_rect, &node.corner, stroke_radius_delta(stroke));
            canvas.draw_rrect(rrect, &paint);
        }
    }

    fn paint_text(
        &mut self,
        canvas: &Canvas,
        node: &Node,
        text: &TextNode,
        width: f64,
        height: f64,
    ) {
        if node.fills.len() > 1 {
            self.diagnostics.push(
                Diagnostic::advice(
                    Phase::Export,
                    "LUME0211",
                    format!(
                        "text node {} has multiple fills; raster export renders the first fill only for text",
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Stacked text fills are out of V0 scope; use a single text fill."),
            );
        }
        // A6a D5: text strokes now render (first solid stroke, drawn behind the
        // fill). LUME0214 retired; multi/gradient/dash strokes advise via
        // LUME0215 through `text_stroke_paint`.
        let stroke_foreground = self.text_stroke_paint(node, width, height);

        let foreground = match node.fills.first() {
            // A specified but unresolved text fill paints the sentinel (magenta
            // glyphs) with the LUME0213 error rather than vanishing — invisible
            // text hides the resolution bug just as a black page would.
            Some(fill) => self.fill_paint(&fill.paint, width, height, Some(&node.id)),
            None => {
                self.diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0207",
                        format!(
                            "text node {} has no fill; raster export used the default visible text fill",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Set an explicit text fill before final export if this fallback is not intended.",
                    ),
                );
                default_foreground()
            }
        };

        let resolution = self.fonts.resolve_family(&text.font_family);
        // A6a D1: transform after normalization (see the measurer for the
        // literal-"\n" rationale) so painted glyphs match measured line boxes.
        let content = text
            .text_transform
            .apply(&normalize_content(&text.content))
            .into_owned();
        // Family/style resolution is independent of layout. Glyph outcomes are
        // collected below from the actual scalar or segmented paint paragraph.
        for diagnostic in font_diagnostics(
            self.fonts,
            &text.font_family,
            text.font_weight as i32,
            text.italic,
            Some(DiagnosticSubject::Node(node.id.clone())),
        ) {
            if !self.diagnostics.contains(&diagnostic) {
                self.diagnostics.push(diagnostic);
            }
        }

        // Justify is mapped to Left so SVG markup (which anchors at start)
        // and raster pixels agree; revisit when SVG export gains justify.
        let align = match text.align {
            TextAlign::Left | TextAlign::Justify => SkTextAlign::Left,
            TextAlign::Center => SkTextAlign::Center,
            TextAlign::Right => SkTextAlign::Right,
        };

        // A6b D7: spanned text paints one segmented paragraph (per-run fill /
        // weight / decoration; stroke pass keeps per-run weight but the single
        // stroke color). Only reached when spans exist, so the pre-A6b paths
        // below stay byte-identical. (Spans are not composed with paragraph
        // stacking in v1 — the segmented paragraph hard-breaks on `\n`.)
        if !text.spans.is_empty() {
            self.paint_text_spanned(
                canvas,
                node,
                text,
                &resolution.family,
                align,
                &foreground,
                stroke_foreground.as_ref(),
                width,
                height,
            );
            return;
        }

        // A6a D4: paint per-paragraph at stacked offsets when a positive gap
        // meets an actual break; otherwise the single-paragraph fast path is
        // byte-identical to pre-A6a. `max_lines` is a TOTAL cap across the
        // stack (review contract): each paragraph draws against the remaining
        // line budget so the raster never paints lines the measured geometry
        // (and the SVG markup) cut away.
        let paragraph_gap = text
            .paragraph_spacing
            .is_finite()
            .then_some(text.paragraph_spacing)
            .filter(|gap| *gap > 0.0)
            .unwrap_or(0.0);
        if paragraph_gap > 0.0 && content.contains('\n') {
            // A7a: valign shifts the whole stack, so the total painted content
            // height must be known BEFORE the paint loop. A measure pre-pass
            // replays the SAME budget/elision resolution, accumulating gaps
            // BETWEEN consecutive painted paragraphs only (gap-before, like
            // `measure_stacked`) — a trailing gap after the last painted
            // paragraph is not painted content, and counting it made raster/
            // CanvasKit disagree with SVG/PDF (whose `measured.height` is the
            // last visible line's bottom) by a full gap under a `max_lines`
            // cut (A7a adversarial-review Finding 1). The loop then seeds
            // `cursor_y` with the offset; at offset 0 the total equals the
            // final cursor exactly.
            let paragraphs: Vec<&str> = content.split('\n').collect();
            let last = paragraphs.len().saturating_sub(1);
            let mut plan: Vec<(std::borrow::Cow<str>, Option<u16>)> = Vec::new();
            let mut total_height = 0.0f32;
            let mut remaining = text.max_lines.map(usize::from);
            for (index, para) in paragraphs.iter().enumerate() {
                if remaining == Some(0) {
                    break;
                }
                // Resolve this paragraph's share of the total budget. When the
                // cut lands exactly on a paragraph boundary with more content
                // following, SkParagraph's native ellipsis cannot fire — carry
                // the "…" in the text instead (the elision pass drops it again
                // if it must make room).
                let mut para_text = std::borrow::Cow::Borrowed(*para);
                let para_max = match remaining {
                    None => None,
                    Some(budget) => {
                        let natural = self.paragraph_line_count(para, &resolution.family, text, width);
                        if natural < budget || (natural == budget && index == last) {
                            None
                        } else {
                            if natural == budget && text.truncate {
                                let mut owned = para.trim_end().to_owned();
                                owned.push('…');
                                para_text = std::borrow::Cow::Owned(owned);
                            }
                            Some(budget.min(u16::MAX as usize) as u16)
                        }
                    }
                };
                let (para_height, painted) =
                    self.paragraph_layout_metrics(&para_text, &resolution.family, text, width, para_max);
                remaining = remaining.map(|budget| budget.saturating_sub(painted));
                if !plan.is_empty() {
                    total_height += paragraph_gap as f32;
                }
                total_height += para_height;
                plan.push((para_text, para_max));
            }
            let mut cursor_y = valign_offset(height, total_height as f64, text.valign) as f32;
            for (index, (para_text, para_max)) in plan.iter().enumerate() {
                // Gap-before, mirroring the pre-pass and `measure_stacked`:
                // gaps land between consecutive painted paragraphs only.
                if index > 0 {
                    cursor_y += paragraph_gap as f32;
                }
                // Per-paragraph valign is `Top` (offset 0) — the stack offset is
                // already folded into the seeded `cursor_y`.
                let (para_height, _) = self.paint_text_paragraph(
                    canvas,
                    &node.id,
                    para_text,
                    &resolution.family,
                    text,
                    align,
                    &foreground,
                    stroke_foreground.as_ref(),
                    width,
                    height,
                    VerticalAlign::Top,
                    cursor_y,
                    *para_max,
                );
                cursor_y += para_height;
            }
        } else {
            self.paint_text_paragraph(
                canvas,
                &node.id,
                &content,
                &resolution.family,
                text,
                align,
                &foreground,
                stroke_foreground.as_ref(),
                width,
                height,
                text.valign,
                0.0,
                text.max_lines,
            );
        }
    }

    /// The natural (uncapped) line count of one paragraph at the same layout
    /// width the paint pass uses, so the stacking loop can budget the total
    /// `max_lines` cap across paragraphs exactly like the measurer does.
    fn paragraph_line_count(
        &self,
        para: &str,
        family: &str,
        text: &TextNode,
        box_width: f64,
    ) -> usize {
        let mut paragraph = build_paragraph(
            &ParagraphRequest {
                content: para,
                font_family: family,
                font_size: text.font_size,
                font_weight: text.font_weight,
                italic: text.italic,
                line_height: text.line_height,
                letter_spacing: text.letter_spacing,
                max_lines: None,
                direction: text.direction.clone(),
                align: SkTextAlign::Left,
                foreground: SkPaint::default(),
                underline: false,
                strikethrough: false,
                truncate: false,
                segments: None,
            },
            self.fonts,
        );
        let layout_width = match text.wrap {
            TextWrap::Wrap => box_width.max(0.0) as f32,
            TextWrap::NoWrap => UNBOUNDED_LAYOUT_WIDTH as f32,
        };
        paragraph.layout(layout_width);
        paragraph.line_number()
    }

    /// A7a: measure one paragraph's laid-out height + painted line count using
    /// the SAME layout-width choice `paint_text_paragraph` makes (height and
    /// line count are independent of the foreground paint and horizontal `x`),
    /// so the stacked-path valign pre-pass computes a total that matches the
    /// paint loop's cursor advancement byte-for-byte.
    fn paragraph_layout_metrics(
        &self,
        para: &str,
        family: &str,
        text: &TextNode,
        box_width: f64,
        max_lines: Option<u16>,
    ) -> (f32, usize) {
        let mut fill = build_paragraph(
            &ParagraphRequest {
                content: para,
                font_family: family,
                font_size: text.font_size,
                font_weight: text.font_weight,
                italic: text.italic,
                line_height: text.line_height,
                letter_spacing: text.letter_spacing,
                max_lines,
                direction: text.direction.clone(),
                align: SkTextAlign::Left,
                foreground: SkPaint::default(),
                underline: text.underline,
                strikethrough: text.strikethrough,
                truncate: text.truncate,
                segments: None,
            },
            self.fonts,
        );
        let layout_width = match text.wrap {
            TextWrap::Wrap => box_width.max(0.0) as f32,
            TextWrap::NoWrap if text.truncate => box_width.max(0.0) as f32,
            TextWrap::NoWrap => {
                fill.layout(UNBOUNDED_LAYOUT_WIDTH as f32);
                fill.longest_line().ceil() + 2.0
            }
        };
        fill.layout(layout_width);
        (fill.height(), fill.line_number())
    }

    /// Paint one paragraph's glyphs (stroke pass behind the fill pass) at a
    /// vertical offset, honoring wrap/alignment and A6a truncation. Returns the
    /// laid-out paragraph height and painted line count so the stacking loop
    /// can advance its cursor and spend its line budget.
    #[allow(clippy::too_many_arguments)]
    fn paint_text_paragraph(
        &mut self,
        canvas: &Canvas,
        node_id: &NodeId,
        para: &str,
        family: &str,
        text: &TextNode,
        align: SkTextAlign,
        fill_foreground: &SkPaint,
        stroke_foreground: Option<&SkPaint>,
        box_width: f64,
        box_height: f64,
        valign: VerticalAlign,
        y_offset: f32,
        max_lines: Option<u16>,
    ) -> (f32, usize) {
        let make_request = |foreground: SkPaint| ParagraphRequest {
            content: para,
            font_family: family,
            font_size: text.font_size,
            font_weight: text.font_weight,
            italic: text.italic,
            line_height: text.line_height,
            letter_spacing: text.letter_spacing,
            max_lines,
            direction: text.direction.clone(),
            align,
            foreground,
            underline: text.underline,
            strikethrough: text.strikethrough,
            truncate: text.truncate,
            segments: None,
        };

        // Resolve the layout width + horizontal placement exactly as the
        // single-paragraph path did (Wrap: box width at x=0; NoWrap: natural
        // width placed per alignment), with the A6a NoWrap+truncate case laid
        // out at the box width so SkParagraph's "…" fires.
        let request = make_request(fill_foreground.clone());
        let mut fill = build_paragraph(&request, self.fonts);
        let (layout_width, x) = match text.wrap {
            TextWrap::Wrap => (box_width.max(0.0) as f32, 0.0f32),
            TextWrap::NoWrap if text.truncate => {
                let bound = box_width.max(0.0) as f32;
                fill.layout(bound);
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => (box_width as f32 - fill.longest_line()) / 2.0,
                    TextAlign::Right => box_width as f32 - fill.longest_line(),
                };
                (bound, x)
            }
            TextWrap::NoWrap => {
                fill.layout(UNBOUNDED_LAYOUT_WIDTH as f32);
                let natural = fill.longest_line().ceil() + 2.0;
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => (box_width as f32 - natural) / 2.0,
                    TextAlign::Right => box_width as f32 - natural,
                };
                (natural, x)
            }
        };
        fill.layout(layout_width);

        self.diagnostics.extend(glyph_diagnostics(
            self.fonts,
            &request,
            &mut fill,
            Some(DiagnosticSubject::Node(node_id.clone())),
        ));

        // A7a: shift within the box's vertical slack. `valign` is `Top` on the
        // stacked path (the stack seeds `cursor_y` with the offset instead), so
        // this only adds a per-paragraph shift on the single-paragraph fast path.
        let voff = valign_offset(box_height, fill.height() as f64, valign) as f32;
        let y = y_offset + voff;

        // Stroke pass first (behind), then the fill glyphs — the display-type
        // "paint-order: stroke fill" convention the SVG exporter emits.
        if let Some(stroke) = stroke_foreground {
            let mut stroke_paragraph = build_paragraph(&make_request(stroke.clone()), self.fonts);
            stroke_paragraph.layout(layout_width);
            stroke_paragraph.paint(canvas, Point::new(x, y));
        }
        fill.paint(canvas, Point::new(x, y));
        (fill.height(), fill.line_number())
    }

    /// A6b D7: paint spanned text as one segmented paragraph. Fill pass styles
    /// each run with its resolved fill (span fill, else the node fill), weight
    /// (span override, else node weight), and decoration (node ∪ span). The
    /// stroke pass keeps per-run WEIGHT so the outline matches the filled glyph
    /// shape, but paints every run in the single stroke color — span FILLS only
    /// affect the fill pass (D7). Single-paragraph placement mirrors the A6a
    /// non-span path (Wrap/NoWrap/NoWrap+truncate).
    #[allow(clippy::too_many_arguments)]
    fn paint_text_spanned(
        &mut self,
        canvas: &Canvas,
        node: &Node,
        text: &TextNode,
        family: &str,
        align: SkTextAlign,
        base_fill: &SkPaint,
        stroke_foreground: Option<&SkPaint>,
        box_width: f64,
        box_height: f64,
    ) {
        let (normalized, map) = normalize_content_mapped(&text.content);
        let boundaries: Vec<(usize, usize)> = text
            .spans
            .iter()
            .map(|span| {
                let start = map.get(span.start).copied().unwrap_or(normalized.len());
                let end = map.get(span.end).copied().unwrap_or(normalized.len());
                (start.min(end), start.max(end))
            })
            .collect();
        let core = transform_segments(&normalized, &boundaries, text.text_transform);

        let mut fill_segments: Vec<ParagraphSegment> = Vec::new();
        let mut stroke_segments: Vec<ParagraphSegment> = Vec::new();
        for segment in &core {
            let span = segment.span.and_then(|index| text.spans.get(index));
            let weight = span.and_then(|span| span.font_weight).unwrap_or(text.font_weight);
            let underline = text.underline || span.and_then(|span| span.underline).unwrap_or(false);
            let strikethrough =
                text.strikethrough || span.and_then(|span| span.strikethrough).unwrap_or(false);
            // A7b D1: italic is an OVERRIDE merge, deliberately unlike the
            // union-merged decorations above — italic is a geometry channel (it
            // selects the face), so `italic(false)` on a span must be able to
            // de-italicize its run inside an italic block. Mirrors weight. This
            // resolution MUST match the measurer's per-run resolution byte-for-
            // byte (measure.rs measure_spanned) or paint drifts from geometry.
            let italic = span.and_then(|span| span.italic).unwrap_or(text.italic);
            // Span fill resolves like a node fill (D8): a $token span fill goes
            // through fill_paint (sentinel + LUME0213 if unresolved); no span
            // fill inherits the node's base fill paint.
            let foreground = match span.and_then(|span| span.fill.as_ref()) {
                Some(paint) => self.fill_paint(paint, box_width, box_height, Some(&node.id)),
                None => base_fill.clone(),
            };
            fill_segments.push(ParagraphSegment {
                text: segment.text.clone(),
                font_weight: weight,
                italic,
                underline,
                strikethrough,
                foreground,
            });
            if let Some(stroke) = stroke_foreground {
                stroke_segments.push(ParagraphSegment {
                    text: segment.text.clone(),
                    font_weight: weight,
                    italic,
                    underline,
                    strikethrough,
                    foreground: stroke.clone(),
                });
            }
        }

        let make_request = |segments: Vec<ParagraphSegment>| ParagraphRequest {
            content: "",
            font_family: family,
            font_size: text.font_size,
            font_weight: text.font_weight,
            // Ignored when segments are set (each run carries its resolved
            // italic); mirror the block value for honesty.
            italic: text.italic,
            line_height: text.line_height,
            letter_spacing: text.letter_spacing,
            max_lines: text.max_lines,
            direction: text.direction.clone(),
            align,
            foreground: SkPaint::default(),
            underline: false,
            strikethrough: false,
            truncate: text.truncate,
            segments: Some(segments),
        };

        let request = make_request(fill_segments);
        let mut fill = build_paragraph(&request, self.fonts);
        let (layout_width, x) = match text.wrap {
            TextWrap::Wrap => (box_width.max(0.0) as f32, 0.0f32),
            TextWrap::NoWrap if text.truncate => {
                let bound = box_width.max(0.0) as f32;
                fill.layout(bound);
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => (box_width as f32 - fill.longest_line()) / 2.0,
                    TextAlign::Right => box_width as f32 - fill.longest_line(),
                };
                (bound, x)
            }
            TextWrap::NoWrap => {
                fill.layout(UNBOUNDED_LAYOUT_WIDTH as f32);
                let natural = fill.longest_line().ceil() + 2.0;
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => (box_width as f32 - natural) / 2.0,
                    TextAlign::Right => box_width as f32 - natural,
                };
                (natural, x)
            }
        };
        fill.layout(layout_width);

        self.diagnostics.extend(glyph_diagnostics(
            self.fonts,
            &request,
            &mut fill,
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));

        // A7a: shift the segmented paragraph within the box's vertical slack.
        let voff = valign_offset(box_height, fill.height() as f64, text.valign) as f32;

        if !stroke_segments.is_empty() {
            let mut stroke_paragraph = build_paragraph(&make_request(stroke_segments), self.fonts);
            stroke_paragraph.layout(layout_width);
            stroke_paragraph.paint(canvas, Point::new(x, voff));
        }
        fill.paint(canvas, Point::new(x, voff));
    }

    /// A6a D5: the first solid text stroke as a Skia stroke-style foreground
    /// paint, drawn behind the fill glyphs. First-stroke-only + solid-only;
    /// additional strokes, gradient stroke paint, and dash all reduce to the
    /// LUME0215 advisory (the stroke still renders, from the first solid stop).
    fn text_stroke_paint(&mut self, node: &Node, width: f64, height: f64) -> Option<SkPaint> {
        let stroke = node.strokes.first()?;
        let gradient_or_dash = matches!(
            stroke.paint,
            Paint::LinearGradient { .. } | Paint::RadialGradient { .. }
        ) || stroke.dash.as_ref().is_some_and(|dash| !dash.is_empty());
        if node.strokes.len() > 1 || gradient_or_dash {
            self.diagnostics.push(
                Diagnostic::advice(
                    Phase::Export,
                    "LUME0215",
                    format!(
                        "text node {} renders the first solid stroke only; extra strokes, gradient stroke paint, and dashes on text strokes are ignored",
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Use a single solid text stroke; gradient/dash/multi-stroke text outlines are out of Typography v1 scope."),
            );
        }

        let color = match &stroke.paint {
            Paint::Solid { color } => self.resolve_color(color, Some(&node.id)),
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
                stops.first().and_then(|stop| self.resolve_color(&stop.color, Some(&node.id)))
            }
            Paint::Token { token } => {
                self.push_token_diag(&node.id, token);
                None
            }
        };
        let _ = (width, height);

        let mut paint = SkPaint::default();
        paint.set_anti_alias(true);
        paint.set_style(PaintStyle::Stroke);
        paint.set_stroke_width(stroke.width as f32);
        match color {
            Some(color) => paint.set_color4f(color, None),
            None => {
                self.push_unresolved_paint_error(Some(&node.id), "stroke");
                paint.set_color4f(UNRESOLVED_PAINT_SENTINEL, None)
            }
        };
        Some(paint)
    }

    fn paint_image(
        &mut self,
        canvas: &Canvas,
        node: &Node,
        image: &ImageNode,
        width: f64,
        height: f64,
    ) {
        let Some(resolved) = self.resolve_image_bytes(node, image) else {
            // Diagnostics already emitted; SVG renders an empty placeholder
            // group here, so pixels stay empty — parity preserved.
            return;
        };

        let record = self.scene.assets.get(&image.asset_id);
        let fit = node
            .asset_placement
            .as_ref()
            .and_then(|placement| placement.fit.as_ref());

        // Focal-point crops compute an explicit window from the asset's
        // natural aspect ratio (exact same math as the SVG exporter).
        if let Some(crop) = focal_crop_geometry(node, record, width, height) {
            canvas.save();
            canvas.clip_rrect(corner_rrect(node, width, height), None, true);
            self.draw_image_bytes(
                canvas,
                node,
                &resolved,
                SkRect::from_xywh(
                    crop.x as f32,
                    crop.y as f32,
                    crop.width as f32,
                    crop.height as f32,
                ),
            );
            canvas.restore();
            return;
        }

        let intrinsic_ratio = self
            .decoded_dimensions(&resolved)
            .or_else(|| record.and_then(|record| record.natural_aspect_ratio()));

        let dest = match (fit, intrinsic_ratio) {
            // Mirror preserveAspectRatio="xMidYMid slice".
            (Some(ImageFitMode::Cover) | Some(ImageFitMode::Crop), Some(ratio)) => {
                let (drawn_width, drawn_height) = if width / height < ratio {
                    (height * ratio, height)
                } else {
                    (width, width / ratio)
                };
                canvas.save();
                canvas.clip_rrect(corner_rrect(node, width, height), None, true);
                let rect = SkRect::from_xywh(
                    ((width - drawn_width) / 2.0) as f32,
                    ((height - drawn_height) / 2.0) as f32,
                    drawn_width as f32,
                    drawn_height as f32,
                );
                self.draw_image_bytes(canvas, node, &resolved, rect);
                canvas.restore();
                return;
            }
            // Mirror preserveAspectRatio="xMidYMid meet" (letterbox).
            (_, Some(ratio)) => {
                let (drawn_width, drawn_height) = if width / height < ratio {
                    (width, width / ratio)
                } else {
                    (height * ratio, height)
                };
                SkRect::from_xywh(
                    ((width - drawn_width) / 2.0) as f32,
                    ((height - drawn_height) / 2.0) as f32,
                    drawn_width as f32,
                    drawn_height as f32,
                )
            }
            // No intrinsic ratio available: fill the box.
            (_, None) => SkRect::from_wh(width as f32, height as f32),
        };
        self.draw_image_bytes(canvas, node, &resolved, dest);
    }

    /// Decode raster dimensions for aspect math; SVG assets have no decoded
    /// pixel size (their ratio comes from the asset record when present).
    fn decoded_dimensions(&self, resolved: &ResolvedAssetBytes) -> Option<f64> {
        if resolved.mime_type == "image/svg+xml" {
            return None;
        }
        let data = Data::new_copy(&resolved.bytes);
        let image = Image::from_encoded(data)?;
        Some(f64::from(image.width()) / f64::from(image.height().max(1)))
    }

    fn draw_image_bytes(
        &mut self,
        canvas: &Canvas,
        node: &Node,
        resolved: &ResolvedAssetBytes,
        dest: SkRect,
    ) {
        if resolved.mime_type == "image/svg+xml" {
            match crate::svg_dom::parse(&resolved.bytes) {
                Ok(mut dom) => {
                    canvas.save();
                    canvas.translate((dest.left, dest.top));
                    // Roots with absolute width/height render at their
                    // intrinsic size and ignore the container size; scale
                    // the canvas so the SVG always fills the dest box
                    // (Phase G: generated QR codes carry width/height).
                    let intrinsic = dom.root().intrinsic_size();
                    if intrinsic.width > 0.0 && intrinsic.height > 0.0 {
                        canvas.scale((
                            dest.width() / intrinsic.width,
                            dest.height() / intrinsic.height,
                        ));
                    } else {
                        dom.set_container_size((dest.width(), dest.height()));
                    }
                    dom.render(canvas);
                    canvas.restore();
                }
                Err(error) => {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Export,
                        "LUME0210",
                        format!(
                            "image node {} carries SVG bytes that did not parse: {error}",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            return;
        }

        let data = Data::new_copy(&resolved.bytes);
        match Image::from_encoded(data) {
            Some(image) => {
                let mut paint = SkPaint::default();
                paint.set_anti_alias(true);
                canvas.draw_image_rect_with_sampling_options(
                    &image,
                    None,
                    dest,
                    SamplingOptions::default(),
                    &paint,
                );
            }
            None => {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0210",
                    format!(
                        "image node {} bytes did not decode as {}",
                        node.id, resolved.mime_type
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
        }
    }

    /// Mirror of the SVG renderer's byte resolution incl. diagnostics
    /// (LUME0202 no resolver / LUME0211 no record / LUME0210 resolve error).
    fn resolve_image_bytes(
        &mut self,
        node: &Node,
        image: &ImageNode,
    ) -> Option<ResolvedAssetBytes> {
        let Some(resolver) = self.resolver else {
            self.diagnostics.push(Diagnostic::warning(
                Phase::Export,
                "LUME0202",
                format!(
                    "image node {} references asset {} but no asset resolver is configured",
                    node.id, image.asset_id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ).with_hint("Configure an asset byte resolver on the export adapter before treating image export as complete."));
            return None;
        };

        let Some(record) = self.scene.assets.get(&image.asset_id) else {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0211",
                    format!(
                        "image node {} references asset {} but the scene carries no asset record to resolve bytes from",
                        node.id, image.asset_id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Upsert the asset record into the scene before export."),
            );
            return None;
        };

        match resolver.resolve(record) {
            Ok(resolved) => Some(resolved),
            Err(error) => {
                self.diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0210",
                        format!(
                            "image node {} could not resolve bytes for asset {}: {}",
                            node.id, image.asset_id, error
                        ),
                        Some(DiagnosticSubject::Asset(image.asset_id.clone())),
                    )
                    .with_hint("Verify the asset bytes exist in the configured asset store."),
                );
                None
            }
        }
    }

    /// Build the node's effect stack as one image filter. A pure drop-shadow
    /// stack keeps the exact pre-A4 merge; a stack with glow / layer blur /
    /// inner shadow uses the A4 general pipeline honoring the D1 stacking
    /// contract (matched to the SVG exporter, pinned by the parity test).
    fn effect_image_filter(&mut self, node: &Node) -> Option<ImageFilter> {
        if node.effects.is_empty() {
            return None;
        }
        let has_new = node.effects.iter().any(|effect| {
            matches!(
                effect.kind,
                EffectKind::Glow { .. }
                    | EffectKind::LayerBlur { .. }
                    | EffectKind::InnerShadow { .. }
            )
        });
        if has_new {
            self.general_effect_filter(node)
        } else {
            self.drop_shadow_filter(node)
        }
    }

    /// Layered drop shadows with spread as one merged image filter:
    /// bottom-most shadow first, source graphic on top — the same stacking
    /// the SVG renderer's feMerge produces (first effect = topmost shadow).
    fn drop_shadow_filter(&mut self, node: &Node) -> Option<ImageFilter> {
        let mut shadow_filters = Vec::new();
        for effect in node.effects.iter().rev() {
            let EffectKind::DropShadow {
                color,
                opacity,
                x,
                y,
                blur,
                spread,
                ..
            } = &effect.kind
            else {
                continue;
            };
            let Some(base) = self.resolve_color(color, Some(&node.id)) else {
                continue;
            };
            let shadow_color = Color4f::new(base.r, base.g, base.b, base.a * (*opacity as f32));
            let spread_input = if *spread > 0.0 {
                image_filters::dilate((*spread as f32, *spread as f32), None, None)
            } else if *spread < 0.0 {
                image_filters::erode((-*spread as f32, -*spread as f32), None, None)
            } else {
                None
            };
            // SVG maps blur to stdDeviation = blur / 2.
            let sigma = (*blur as f32) / 2.0;
            shadow_filters.push(image_filters::drop_shadow_only(
                (*x as f32, *y as f32),
                (sigma, sigma),
                shadow_color.to_color(),
                None,
                spread_input,
                None,
            ));
        }

        if shadow_filters.is_empty() {
            return None;
        }
        // Source graphic on top.
        shadow_filters.push(None);
        image_filters::merge(shadow_filters, None)
    }

    /// A4 general pipeline. Source → layer blurs → outer shadows/glows beneath
    /// the blurred result → inner shadows over it. Merge order matches the SVG
    /// exporter's feMerge (outers reversed, base, inners reversed).
    fn general_effect_filter(&mut self, node: &Node) -> Option<ImageFilter> {
        // 1. Blurred base (None = the source graphic when there are no blurs).
        let mut base: Option<ImageFilter> = None;
        for effect in &node.effects {
            if let EffectKind::LayerBlur { radius } = &effect.kind {
                let sigma = (*radius as f32) / 2.0;
                base = image_filters::blur((sigma, sigma), None, base, None);
            }
        }

        // 2. Outer shadows/glows (vec order; first = topmost of the class).
        let mut outers = Vec::new();
        // 3. Inner shadows (vec order; first = topmost of the class).
        let mut inners = Vec::new();
        for effect in &node.effects {
            match &effect.kind {
                EffectKind::DropShadow {
                    color,
                    opacity,
                    x,
                    y,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(f) =
                        self.outer_effect_filter(node, color, *opacity, *x, *y, *blur, *spread, &base)
                    {
                        outers.push(f);
                    }
                }
                EffectKind::Glow {
                    color,
                    opacity,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(f) = self
                        .outer_effect_filter(node, color, *opacity, 0.0, 0.0, *blur, *spread, &base)
                    {
                        outers.push(f);
                    }
                }
                EffectKind::InnerShadow {
                    color,
                    opacity,
                    x,
                    y,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(f) =
                        self.inner_shadow_filter(node, color, *opacity, *x, *y, *blur, *spread, &base)
                    {
                        inners.push(f);
                    }
                }
                EffectKind::LayerBlur { .. } => {}
            }
        }

        if outers.is_empty() && inners.is_empty() {
            // Layer-blur only.
            return base;
        }

        // 4. Merge bottom-up: outers reversed (first outer topmost), the
        //    blurred base, inner shadows reversed (first inner topmost).
        let mut merge_list: Vec<Option<ImageFilter>> = Vec::new();
        for f in outers.into_iter().rev() {
            merge_list.push(Some(f));
        }
        merge_list.push(base);
        for f in inners.into_iter().rev() {
            merge_list.push(Some(f));
        }
        image_filters::merge(merge_list, None)
    }

    /// One outer shadow/glow: the shadow of the (blurred) base alpha, dilated
    /// or eroded by spread, offset and blurred, colored. `drop_shadow_only`
    /// yields only the shadow (not the source).
    #[allow(clippy::too_many_arguments)]
    fn outer_effect_filter(
        &mut self,
        node: &Node,
        color: &Color,
        opacity: f64,
        x: f64,
        y: f64,
        blur: f64,
        spread: f64,
        base: &Option<ImageFilter>,
    ) -> Option<ImageFilter> {
        let resolved = self.resolve_color(color, Some(&node.id))?;
        let shadow_color = Color4f::new(
            resolved.r,
            resolved.g,
            resolved.b,
            resolved.a * (opacity as f32),
        );
        let spread_input = if spread > 0.0 {
            image_filters::dilate((spread as f32, spread as f32), base.clone(), None)
        } else if spread < 0.0 {
            image_filters::erode((-spread as f32, -spread as f32), base.clone(), None)
        } else {
            base.clone()
        };
        let sigma = (blur as f32) / 2.0;
        image_filters::drop_shadow_only(
            (x as f32, y as f32),
            (sigma, sigma),
            shadow_color.to_color(),
            None,
            spread_input,
            None,
        )
    }

    /// One inner shadow via the standard alpha-invert composite: the region
    /// inside the (blurred) base alpha but outside the offset+blurred alpha,
    /// recolored to the shadow color. Spread erodes the shape inward first.
    #[allow(clippy::too_many_arguments)]
    fn inner_shadow_filter(
        &mut self,
        node: &Node,
        color: &Color,
        opacity: f64,
        x: f64,
        y: f64,
        blur: f64,
        spread: f64,
        base: &Option<ImageFilter>,
    ) -> Option<ImageFilter> {
        let resolved = self.resolve_color(color, Some(&node.id))?;
        let shadow_color = Color4f::new(
            resolved.r,
            resolved.g,
            resolved.b,
            resolved.a * (opacity as f32),
        );
        // Shape eroded inward by spread.
        let shape = if spread > 0.0 {
            image_filters::erode((spread as f32, spread as f32), base.clone(), None)
        } else {
            base.clone()
        };
        // Offset then blur the (eroded) shape.
        let offset = image_filters::offset((x as f32, y as f32), shape, None);
        let sigma = (blur as f32) / 2.0;
        let offset_blur = image_filters::blur((sigma, sigma), None, offset, None);
        // ring = base SrcOut offset_blur = inside base but outside the shifted
        // blurred alpha. blend(mode, background, foreground) computes
        // foreground <mode> background, so foreground = base, background = ring.
        let ring = image_filters::blend(
            skia_safe::BlendMode::SrcOut,
            offset_blur,
            base.clone(),
            None,
        )?;
        // Recolor the ring to the shadow color (SrcIn keeps the ring's alpha).
        let color_filter =
            skia_safe::color_filters::blend(shadow_color.to_color(), skia_safe::BlendMode::SrcIn)?;
        image_filters::color_filter(color_filter, ring, None)
    }

    /// Resolve a fill paint to an SkPaint. A *specified* fill never silently
    /// vanishes: when its source cannot resolve (unresolved token, unparseable
    /// hex, or degenerate gradient) this substitutes the visible sentinel and
    /// raises the loud LUME0213 error — the reviewer sees a wrong-but-obvious
    /// magenta region instead of a black hole that hides the resolution bug.
    fn fill_paint(
        &mut self,
        paint: &Paint,
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
    ) -> SkPaint {
        let mut sk_paint = SkPaint::default();
        sk_paint.set_anti_alias(true);
        sk_paint.set_style(PaintStyle::Fill);
        if self
            .apply_paint_source(&mut sk_paint, paint, width, height, node_id)
            .is_none()
        {
            self.push_unresolved_paint_error(node_id, "fill");
            sk_paint.set_color4f(UNRESOLVED_PAINT_SENTINEL, None);
            sk_paint.set_shader(None);
        }
        sk_paint
    }

    /// Stroke paint mirroring SVG attributes: width, dash array, cap, join.
    /// `alignment_native` is true for rect/ellipse geometry where inside/
    /// outside alignment is applied natively by adjusting the stroked rect;
    /// other geometry renders centered with the same advice diagnostic the
    /// SVG exporter emits.
    fn stroke_paint(
        &mut self,
        stroke: &Stroke,
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
        alignment_native: bool,
    ) -> SkPaint {
        let mut sk_paint = SkPaint::default();
        sk_paint.set_anti_alias(true);
        sk_paint.set_style(PaintStyle::Stroke);
        sk_paint.set_stroke_width(stroke.width as f32);
        if let Some(dash) = &stroke.dash {
            if !dash.is_empty() {
                let intervals = dash.iter().map(|value| *value as f32).collect::<Vec<f32>>();
                // SVG repeats odd-length dash arrays; Skia requires even.
                let intervals = if intervals.len() % 2 == 1 {
                    let mut doubled = intervals.clone();
                    doubled.extend_from_slice(&intervals);
                    doubled
                } else {
                    intervals
                };
                sk_paint.set_path_effect(PathEffect::dash(&intervals, 0.0));
            }
        }
        sk_paint.set_stroke_cap(match stroke.cap {
            StrokeCap::Butt => PaintCap::Butt,
            StrokeCap::Round => PaintCap::Round,
            StrokeCap::Square => PaintCap::Square,
        });
        sk_paint.set_stroke_join(match stroke.join {
            StrokeJoin::Miter => PaintJoin::Miter,
            StrokeJoin::Round => PaintJoin::Round,
            StrokeJoin::Bevel => PaintJoin::Bevel,
        });

        if stroke.align != StrokeAlign::Center && !alignment_native {
            if let Some(node_id) = node_id {
                self.diagnostics.push(
                    Diagnostic::advice(
                        Phase::Export,
                        "LUME0210",
                        format!(
                            "node {} stroke {} requests {:?} alignment; raster export renders this geometry centered",
                            node_id, stroke.id, stroke.align
                        ),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    )
                    .with_hint("Path-offset approximation is out of V0 scope for non-rectangular geometry; adjust geometry if exact alignment matters."),
                );
            }
        }

        if self
            .apply_paint_source(&mut sk_paint, &stroke.paint, width, height, node_id)
            .is_none()
        {
            // The stroke keeps its resolved width/dash/cap/join geometry but
            // paints in the sentinel so an unresolved stroke source is loud,
            // not invisible.
            self.push_unresolved_paint_error(node_id, "stroke");
            sk_paint.set_color4f(UNRESOLVED_PAINT_SENTINEL, None);
            sk_paint.set_shader(None);
        }
        sk_paint
    }

    /// Solid color or gradient shader; `None` for unresolved tokens (with
    /// the same diagnostics the SVG renderer emits).
    fn apply_paint_source(
        &mut self,
        sk_paint: &mut SkPaint,
        paint: &Paint,
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
    ) -> Option<()> {
        match paint {
            Paint::Solid { color } => {
                let color = self.resolve_color(color, node_id)?;
                sk_paint.set_color4f(color, None);
                Some(())
            }
            Paint::LinearGradient { angle, stops } => {
                let shader = self.linear_gradient_shader(*angle, stops, width, height, node_id)?;
                sk_paint.set_shader(shader);
                Some(())
            }
            Paint::RadialGradient { stops } => {
                let shader = self.radial_gradient_shader(stops, width, height, node_id)?;
                sk_paint.set_shader(shader);
                Some(())
            }
            Paint::Token { token } => {
                if let Some(node_id) = node_id {
                    self.push_token_diag(node_id, token);
                }
                None
            }
        }
    }

    /// Equivalent of the SVG `<linearGradient gradientTransform=rotate(a)>`
    /// in objectBoundingBox units: gradient vector (0,0)→(1,0) with a local
    /// matrix of scale(box) ∘ rotate(angle).
    fn linear_gradient_shader(
        &mut self,
        angle: f64,
        stops: &[lumen_core::scene::ColorStop],
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
    ) -> Option<Shader> {
        let (colors, positions) = self.gradient_stops(stops, node_id)?;
        let mut matrix = Matrix::scale((width as f32, height as f32));
        matrix.pre_concat(&Matrix::rotate_deg(angle as f32));
        gradient::shaders::linear_gradient(
            (Point::new(0.0, 0.0), Point::new(1.0, 0.0)),
            &gradient::Gradient::new(
                gradient::Colors::new(&colors, Some(&positions), TileMode::Clamp, None),
                gradient::Interpolation::default(),
            ),
            Some(&matrix),
        )
    }

    /// Equivalent of the SVG `<radialGradient>` defaults: center (0.5,0.5),
    /// radius 0.5 in objectBoundingBox units, scaled to the box.
    fn radial_gradient_shader(
        &mut self,
        stops: &[lumen_core::scene::ColorStop],
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
    ) -> Option<Shader> {
        let (colors, positions) = self.gradient_stops(stops, node_id)?;
        let matrix = Matrix::scale((width as f32, height as f32));
        gradient::shaders::radial_gradient(
            (Point::new(0.5, 0.5), 0.5),
            &gradient::Gradient::new(
                gradient::Colors::new(&colors, Some(&positions), TileMode::Clamp, None),
                gradient::Interpolation::default(),
            ),
            Some(&matrix),
        )
    }

    fn gradient_stops(
        &mut self,
        stops: &[lumen_core::scene::ColorStop],
        node_id: Option<&NodeId>,
    ) -> Option<(Vec<Color4f>, Vec<f32>)> {
        let mut colors = Vec::with_capacity(stops.len());
        let mut positions = Vec::with_capacity(stops.len());
        for stop in stops {
            let color = self.resolve_color(&stop.color, node_id)?;
            colors.push(color);
            positions.push(stop.position.clamp(0.0, 1.0) as f32);
        }
        if colors.is_empty() {
            return None;
        }
        Some((colors, positions))
    }

    fn resolve_color(&mut self, color: &Color, node_id: Option<&NodeId>) -> Option<Color4f> {
        match color {
            Color::Hex { value } => parse_hex_color(value).or_else(|| {
                if let Some(node_id) = node_id {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Export,
                        "LUME0206",
                        format!("node {node_id} has unparseable hex color {value}"),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    ));
                }
                None
            }),
            Color::Oklch { l, c, h, alpha } => Some(oklch_to_srgb(*l, *c, *h, *alpha)),
            Color::Token { token } => {
                if let Some(node_id) = node_id {
                    self.push_token_diag(node_id, token);
                }
                None
            }
        }
    }

    /// Loud, error-severity alarm (LUME0213) raised whenever a specified
    /// paint could not resolve and the sentinel was painted in its place. A
    /// raster carrying a sentinel region is not a shippable artifact; the
    /// error guarantees the reviewer/agent is told rather than silently
    /// shown a black (or, post-paper-fix, blank) surface. LUME0206 still
    /// records *which* token/hex failed; this code records that the failure
    /// was substituted with a visible marker so the export is not final.
    fn push_unresolved_paint_error(&mut self, node_id: Option<&NodeId>, context: &str) {
        let subject = node_id.map(|id| DiagnosticSubject::Node(id.clone()));
        let where_ = node_id
            .map(|id| format!("node {id}"))
            .unwrap_or_else(|| "page".to_owned());
        let diagnostic = Diagnostic::error(
            Phase::Export,
            "LUME0213",
            format!(
                "{where_} {context} paint did not resolve at raster; painted a magenta sentinel so the failure is visible — this PNG is not shippable"
            ),
            subject,
        )
        .with_hint(
            "Resolve the brand/token paint (run token resolution before export) or set an explicit color; see the paired LUME0206 for the specific token/hex that failed.",
        );
        if !self.diagnostics.contains(&diagnostic) {
            self.diagnostics.push(diagnostic);
        }
    }

    fn push_token_diag(&mut self, node_id: &NodeId, token: &str) {
        // Same code + message as the SVG renderer's unresolved-token path.
        let diagnostic = Diagnostic::warning(
            Phase::Export,
            "LUME0206",
            format!("node {node_id} references unresolved token {token}"),
            Some(DiagnosticSubject::Node(node_id.clone())),
        )
        .with_hint("Wire a brand/token resolver before treating tokenized export as final.");
        if !self.diagnostics.contains(&diagnostic) {
            self.diagnostics.push(diagnostic);
        }
    }
}

/// Rounded-rect for a node's corner radii, mirroring the SVG exporter's
/// policy: uniform radii render rounded; non-uniform radii fall back to
/// sharp corners (SVG emits no rx for those).
fn corner_rrect(node: &Node, width: f64, height: f64) -> RRect {
    corner_rrect_for(
        SkRect::from_wh(width as f32, height as f32),
        &node.corner,
        0.0,
    )
}

/// The transform that fits a vector node's source viewBox uniformly (centered) into
/// its rendered box, so a library icon renders at the node's size. `None` when the
/// node has no viewBox (a hand-authored vector path → draw at raw coordinates).
fn icon_fit_matrix(view_box: Option<[f64; 2]>, width: f64, height: f64) -> Option<Matrix> {
    let [vbw, vbh] = view_box?;
    if vbw <= 0.0 || vbh <= 0.0 {
        return None;
    }
    let scale = (width / vbw).min(height / vbh);
    let tx = (width - vbw * scale) / 2.0;
    let ty = (height - vbh * scale) / 2.0;
    let mut matrix = Matrix::translate((tx as f32, ty as f32));
    matrix.pre_scale((scale as f32, scale as f32), None);
    Some(matrix)
}

/// Corner-radius delta for natively aligned strokes: inside strokes shrink
/// the radius with the rect, outside strokes grow it, keeping the stroke
/// concentric with the fill geometry.
fn stroke_radius_delta(stroke: &Stroke) -> f32 {
    match stroke.align {
        StrokeAlign::Center => 0.0,
        StrokeAlign::Inside => -(stroke.width as f32) / 2.0,
        StrokeAlign::Outside => (stroke.width as f32) / 2.0,
    }
}

fn corner_rrect_for(rect: SkRect, corner: &CornerRadii, radius_delta: f32) -> RRect {
    let uniform = corner.top_left == corner.top_right
        && corner.top_left == corner.bottom_right
        && corner.top_left == corner.bottom_left;
    if uniform {
        let radius = corner.top_left as f32;
        let radius = if radius > 0.0 {
            (radius + radius_delta).max(0.0)
        } else {
            0.0
        };
        return if radius <= 0.0 {
            RRect::new_rect(rect)
        } else {
            RRect::new_rect_xy(rect, radius, radius)
        };
    }
    // Per-corner radii (A4): Skia's `new_rect_radii` applies the CSS overlap
    // clamp (proportional scale-down) natively, matching the SVG path's
    // explicit clamp. Order is [upper-left, upper-right, lower-right,
    // lower-left] — the same clockwise-from-top-left order as the DSL.
    // A zero-radius corner stays square regardless of stroke-alignment delta,
    // matching the uniform path above.
    let apply = |r: f64| {
        if r > 0.0 {
            ((r as f32) + radius_delta).max(0.0)
        } else {
            0.0
        }
    };
    let radii = [
        Point::new(apply(corner.top_left), apply(corner.top_left)),
        Point::new(apply(corner.top_right), apply(corner.top_right)),
        Point::new(apply(corner.bottom_right), apply(corner.bottom_right)),
        Point::new(apply(corner.bottom_left), apply(corner.bottom_left)),
    ];
    RRect::new_rect_radii(rect, &radii)
}

/// Native inside/outside stroke alignment for rect/ellipse geometry: the
/// stroked rect is inset (inside) or outset (outside) by half the stroke
/// width so the stroke edge lands exactly on the geometry bound.
fn aligned_rect(rect: SkRect, stroke: &Stroke) -> SkRect {
    let delta = match stroke.align {
        StrokeAlign::Center => 0.0,
        StrokeAlign::Inside => (stroke.width as f32) / 2.0,
        StrokeAlign::Outside => -(stroke.width as f32) / 2.0,
    };
    SkRect::from_ltrb(
        rect.left + delta,
        rect.top + delta,
        rect.right - delta,
        rect.bottom - delta,
    )
}

/// Parse #RGB, #RRGGBB, #RRGGBBAA (leading '#' optional).
fn parse_hex_color(value: &str) -> Option<Color4f> {
    let hex = value.trim_start_matches('#');
    let (r, g, b, a) = match hex.len() {
        3 => {
            let mut digits = hex.chars().map(|ch| ch.to_digit(16));
            let r = digits.next()??;
            let g = digits.next()??;
            let b = digits.next()??;
            ((r * 17) as u8, (g * 17) as u8, (b * 17) as u8, 255u8)
        }
        6 | 8 => {
            let r = u8::from_str_radix(hex.get(0..2)?, 16).ok()?;
            let g = u8::from_str_radix(hex.get(2..4)?, 16).ok()?;
            let b = u8::from_str_radix(hex.get(4..6)?, 16).ok()?;
            let a = if hex.len() == 8 {
                u8::from_str_radix(hex.get(6..8)?, 16).ok()?
            } else {
                255
            };
            (r, g, b, a)
        }
        _ => return None,
    };
    Some(Color4f::new(
        f32::from(r) / 255.0,
        f32::from(g) / 255.0,
        f32::from(b) / 255.0,
        f32::from(a) / 255.0,
    ))
}

/// OKLCH → sRGB (clamped). Standard OKLab inverse transform.
fn oklch_to_srgb(l: f64, c: f64, h: f64, alpha: f64) -> Color4f {
    let h_rad = h.to_radians();
    let a = c * h_rad.cos();
    let b = c * h_rad.sin();

    let l_ = l + 0.396_337_777_4 * a + 0.215_803_757_3 * b;
    let m_ = l - 0.105_561_345_8 * a - 0.063_854_172_8 * b;
    let s_ = l - 0.089_484_177_5 * a - 1.291_485_548_0 * b;

    let l3 = l_ * l_ * l_;
    let m3 = m_ * m_ * m_;
    let s3 = s_ * s_ * s_;

    let red = 4.076_741_662_1 * l3 - 3.307_711_591_3 * m3 + 0.230_969_929_2 * s3;
    let green = -1.268_438_004_6 * l3 + 2.609_757_401_1 * m3 - 0.341_319_396_5 * s3;
    let blue = -0.004_196_086_3 * l3 - 0.703_418_614_8 * m3 + 1.707_614_701_0 * s3;

    Color4f::new(
        linear_to_srgb(red),
        linear_to_srgb(green),
        linear_to_srgb(blue),
        alpha.clamp(0.0, 1.0) as f32,
    )
}

fn linear_to_srgb(linear: f64) -> f32 {
    let clamped = linear.clamp(0.0, 1.0);
    let srgb = if clamped <= 0.003_130_8 {
        12.92 * clamped
    } else {
        1.055 * clamped.powf(1.0 / 2.4) - 0.055
    };
    srgb as f32
}

#[cfg(test)]
mod crop_mark_tests {
    use super::{crop_mark_segments, CropMarks};
    use lumen_core::Rect;

    fn marks(bleed: Rect) -> CropMarks {
        CropMarks {
            trim: Rect {
                x: 0.0,
                y: 0.0,
                width: 200.0,
                height: 150.0,
            },
            bleed,
            margin: 14.0,
            gap: 3.0,
            stroke_width: 0.5,
        }
    }

    #[test]
    fn distinct_bleed_gets_trim_and_bleed_mark_sets() {
        let segments = crop_mark_segments(&marks(Rect {
            x: -9.0,
            y: -9.0,
            width: 218.0,
            height: 168.0,
        }));
        // 8 trim-aligned + 8 bleed-aligned ticks.
        assert_eq!(segments.len(), 16);
        // A bleed-aligned horizontal tick sits at the bleed's top edge
        // (y = -9), running through the margin left of the bleed box.
        assert!(segments.contains(&(((-9.0 - 14.0), -9.0), ((-9.0 - 3.0), -9.0))));
        // A trim-aligned vertical tick sits at the trim's left edge (x = 0),
        // above the bleed box.
        assert!(segments.contains(&((0.0, (-9.0 - 14.0)), (0.0, (-9.0 - 3.0)))));
    }

    #[test]
    fn coincident_bleed_draws_only_the_trim_set() {
        // Proof mode on a bleed-less page: bleed == trim; a second identical
        // set would just double-stroke the crop marks.
        let segments = crop_mark_segments(&marks(Rect {
            x: 0.0,
            y: 0.0,
            width: 200.0,
            height: 150.0,
        }));
        assert_eq!(segments.len(), 8);
    }
}
