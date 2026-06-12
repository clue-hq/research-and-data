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
    build_paragraph, default_foreground, normalize_content, ParagraphRequest,
    UNBOUNDED_LAYOUT_WIDTH,
};
use lumen_core::{
    render_box_for_node, Color, CornerRadii, Diagnostic, DiagnosticSubject, EffectKind,
    ImageFitMode, ImageNode, Node, NodeId, NodeKind, Page, PageId, Paint, Phase, Scene, Stroke,
    StrokeAlign, StrokeCap, StrokeJoin, TextAlign, TextNode, TextWrap,
};
use lumen_export::{
    focal_crop_geometry, page_background_token_diagnostics, unresolved_brand_token_diagnostics,
    AssetByteResolver, PageRasterizer, RasterizeError, RasterizedPage, ResolvedAssetBytes,
};
use skia_safe::canvas::SaveLayerRec;
use skia_safe::textlayout::TextAlign as SkTextAlign;
use skia_safe::{
    gradient, image_filters, surfaces, Canvas, Color4f, Data, EncodedImageFormat, FontMgr, Image,
    ImageFilter, Matrix, Paint as SkPaint, PaintCap, PaintJoin, PaintStyle, PathEffect, Point,
    RRect, Rect as SkRect, SamplingOptions, Shader, TileMode,
};
use std::sync::Arc;

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

        let mut painter = PagePainter {
            scene,
            fonts: &self.fonts,
            resolver,
            diagnostics: Vec::new(),
        };

        {
            let canvas = surface.canvas();
            canvas.clear(skia_safe::Color::TRANSPARENT);
            canvas.scale((
                width as f32 / page.size.width.max(1.0) as f32,
                height as f32 / page.size.height.max(1.0) as f32,
            ));
            painter.paint_page(canvas, page);
        }

        let image = surface.image_snapshot();
        let png = image
            .encode(None, EncodedImageFormat::PNG, Some(100))
            .ok_or_else(|| {
                RasterizeError::new("raster.png_encode_failed", "PNG encoding failed")
            })?;

        Ok(RasterizedPage {
            png: png.as_bytes().to_vec(),
            diagnostics: painter.diagnostics,
        })
    }
}

struct PagePainter<'a> {
    scene: &'a Scene,
    fonts: &'a FontManager,
    resolver: Option<&'a dyn AssetByteResolver>,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> PagePainter<'a> {
    fn paint_page(&mut self, canvas: &Canvas, page: &Page) {
        self.diagnostics
            .extend(page_background_token_diagnostics(page));
        let page_rect = SkRect::from_wh(page.size.width as f32, page.size.height as f32);
        for fill in &page.background {
            if let Some(paint) =
                self.fill_paint(&fill.paint, page.size.width, page.size.height, None)
            {
                canvas.draw_rect(page_rect, &paint);
            }
        }

        for child_id in &page.children {
            self.paint_node(canvas, child_id, None);
        }
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
        let shadow_filter = self.shadow_image_filter(node);
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
                    self.paint_node(canvas, child_id, child_parent_origin);
                }
                if node.clip {
                    canvas.restore();
                }
            }
            NodeKind::Group => {
                for child_id in &node.children {
                    self.paint_node(canvas, child_id, child_parent_origin);
                }
            }
            NodeKind::Rect => {
                self.paint_rect_geometry(canvas, node, width, height);
            }
            NodeKind::Ellipse => {
                let rect = SkRect::from_wh(width as f32, height as f32);
                for fill in &node.fills {
                    if let Some(paint) = self.fill_paint(&fill.paint, width, height, Some(&node.id))
                    {
                        canvas.draw_oval(rect, &paint);
                    }
                }
                for stroke in &node.strokes {
                    if let Some(paint) =
                        self.stroke_paint(stroke, width, height, Some(&node.id), true)
                    {
                        let oval = aligned_rect(rect, stroke);
                        canvas.draw_oval(oval, &paint);
                    }
                }
            }
            NodeKind::Line(line) => {
                let from = Point::new(0.0, 0.0);
                let to = Point::new(line.x2 as f32, line.y2 as f32);
                for stroke in &node.strokes {
                    if let Some(paint) =
                        self.stroke_paint(stroke, width, height, Some(&node.id), false)
                    {
                        canvas.draw_line(from, to, &paint);
                    }
                }
            }
            NodeKind::Vector(vector) => {
                if let Some(path) = skia_safe::utils::parse_path::from_svg(&vector.path_data) {
                    for fill in &node.fills {
                        if let Some(paint) =
                            self.fill_paint(&fill.paint, width, height, Some(&node.id))
                        {
                            canvas.draw_path(&path, &paint);
                        }
                    }
                    for stroke in &node.strokes {
                        if let Some(paint) =
                            self.stroke_paint(stroke, width, height, Some(&node.id), false)
                        {
                            canvas.draw_path(&path, &paint);
                        }
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
            if let Some(paint) = self.fill_paint(&fill.paint, width, height, Some(&node.id)) {
                canvas.draw_rrect(corner_rrect(node, width, height), &paint);
            }
        }
        for stroke in &node.strokes {
            if let Some(paint) = self.stroke_paint(stroke, width, height, Some(&node.id), true) {
                let stroke_rect = aligned_rect(rect, stroke);
                let rrect =
                    corner_rrect_for(stroke_rect, &node.corner, stroke_radius_delta(stroke));
                canvas.draw_rrect(rrect, &paint);
            }
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

        let foreground = match node.fills.first() {
            Some(fill) => match self.fill_paint(&fill.paint, width, height, Some(&node.id)) {
                Some(paint) => paint,
                // Unresolved token fill: diagnostic already emitted; skip
                // painting (SVG renders fill="none").
                None => return,
            },
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
        if let Some(diagnostic) = resolution.diagnostic() {
            let diagnostic = Diagnostic {
                subject: Some(DiagnosticSubject::Node(node.id.clone())),
                ..diagnostic
            };
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

        let content = normalize_content(&text.content);
        let request = ParagraphRequest {
            content: &content,
            font_family: &resolution.family,
            font_size: text.font_size,
            font_weight: text.font_weight,
            line_height: text.line_height,
            letter_spacing: text.letter_spacing,
            max_lines: text.max_lines,
            direction: text.direction.clone(),
            align,
            foreground,
        };
        let mut paragraph = build_paragraph(&request, self.fonts);

        match text.wrap {
            TextWrap::Wrap => {
                // Same wrap width the measurer used for this box: breaks are
                // bit-identical with measurement by construction.
                paragraph.layout(width.max(0.0) as f32);
                paragraph.paint(canvas, Point::new(0.0, 0.0));
            }
            TextWrap::NoWrap => {
                // No soft wrapping: lay out unbounded to find the natural
                // width, relayout snugly so alignment math stays in small
                // coordinates, then place the block per alignment — the
                // same per-line anchoring the SVG exporter emits.
                paragraph.layout(UNBOUNDED_LAYOUT_WIDTH as f32);
                let natural = paragraph.longest_line().ceil() + 2.0;
                paragraph.layout(natural);
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => (width as f32 - natural) / 2.0,
                    TextAlign::Right => width as f32 - natural,
                };
                paragraph.paint(canvas, Point::new(x, 0.0));
            }
        }
        let _ = height;
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
            let font_mgr: FontMgr = FontMgr::new();
            match skia_safe::svg::Dom::from_bytes(&resolved.bytes, font_mgr) {
                Ok(mut dom) => {
                    canvas.save();
                    canvas.translate((dest.left, dest.top));
                    dom.set_container_size((dest.width(), dest.height()));
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

    /// Layered drop shadows with spread as one merged image filter:
    /// bottom-most shadow first, source graphic on top — the same stacking
    /// the SVG renderer's feMerge produces (first effect = topmost shadow).
    fn shadow_image_filter(&mut self, node: &Node) -> Option<ImageFilter> {
        if node.effects.is_empty() {
            return None;
        }

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
            } = &effect.kind;
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

    fn fill_paint(
        &mut self,
        paint: &Paint,
        width: f64,
        height: f64,
        node_id: Option<&NodeId>,
    ) -> Option<SkPaint> {
        let mut sk_paint = SkPaint::default();
        sk_paint.set_anti_alias(true);
        sk_paint.set_style(PaintStyle::Fill);
        self.apply_paint_source(&mut sk_paint, paint, width, height, node_id)?;
        Some(sk_paint)
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
    ) -> Option<SkPaint> {
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

        self.apply_paint_source(&mut sk_paint, &stroke.paint, width, height, node_id)?;
        Some(sk_paint)
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
    let radius = if uniform { corner.top_left as f32 } else { 0.0 };
    let radius = if radius > 0.0 {
        (radius + radius_delta).max(0.0)
    } else {
        0.0
    };
    if radius <= 0.0 {
        RRect::new_rect(rect)
    } else {
        RRect::new_rect_xy(rect, radius, radius)
    }
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
