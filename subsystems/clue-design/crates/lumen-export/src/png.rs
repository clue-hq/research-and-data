use crate::sidecar::build_sidecar;
use crate::svg::resolve_page_ids;
use lumen_core::{
    Color, Diagnostic, DiagnosticSubject, ExportAdapter, ExportArtifact, ExportError, ExportFormat,
    ExportRequest, ExportResult, Fill, Node, NodeId, NodeKind, Page, Paint, Phase, Scene, Unit,
};

#[derive(Clone, Debug, Default)]
pub struct PngExportAdapter;

impl ExportAdapter for PngExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError> {
        let resolved = resolve_page_ids(scene, &request.page_ids);
        if resolved
            .diagnostics
            .iter()
            .any(|diagnostic| matches!(diagnostic.severity, lumen_core::DiagnosticSeverity::Error))
        {
            return Err(ExportError::new(
                "export.invalid_pages",
                "export request references missing pages",
            )
            .with_diagnostics(resolved.diagnostics));
        }

        let mut diagnostics = resolved.diagnostics;
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0301",
                "PNG export uses the built-in conservative raster fallback",
                Some(DiagnosticSubject::Document),
            )
            .with_hint(
                "SVG remains the fidelity baseline until a full SVG rasterizer backend is added.",
            ),
        );

        let mut artifacts = Vec::new();
        for page_id in &resolved.page_ids {
            let Some(page) = scene.pages.get(page_id) else {
                continue;
            };
            let mut renderer = PngPageRenderer::new(scene, page, request);
            let png = renderer.render_page();
            diagnostics.extend(renderer.diagnostics);

            let sidecar = build_sidecar(scene, &[page_id.clone()], &request.profile.name);
            let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

            artifacts.push(ExportArtifact {
                format: ExportFormat::Png,
                page_id: Some(page_id.clone()),
                asset_id: None,
                mime_type: "image/png".to_owned(),
                bytes: png,
                sidecar_json,
            });
        }

        Ok(ExportResult {
            artifacts,
            diagnostics,
        })
    }
}

struct PngPageRenderer<'a> {
    scene: &'a Scene,
    page: &'a Page,
    width: u32,
    height: u32,
    scale_x: f64,
    scale_y: f64,
    pixels: Vec<u8>,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> PngPageRenderer<'a> {
    fn new(scene: &'a Scene, page: &'a Page, request: &ExportRequest) -> Self {
        let dpi = request
            .profile
            .raster
            .as_ref()
            .and_then(|raster| raster.dpi)
            .unwrap_or(96) as f64;
        let scale = request
            .profile
            .raster
            .as_ref()
            .map(|raster| raster.scale)
            .unwrap_or(1.0);
        let (width, height) = page_pixel_size(page, dpi, scale);
        let pixels = vec![0; width as usize * height as usize * 4];

        Self {
            scene,
            page,
            width,
            height,
            scale_x: width as f64 / page.size.width.max(1.0),
            scale_y: height as f64 / page.size.height.max(1.0),
            pixels,
            diagnostics: Vec::new(),
        }
    }

    fn render_page(&mut self) -> Vec<u8> {
        for fill in &self.page.background {
            if let Some(color) = self.fill_color(fill, None) {
                self.fill_rect(0.0, 0.0, self.page.size.width, self.page.size.height, color);
            }
        }

        for child_id in &self.page.children {
            self.render_node(child_id, 0.0, 0.0);
        }

        encode_png(self.width, self.height, &self.pixels)
    }

    fn render_node(&mut self, node_id: &NodeId, parent_x: f64, parent_y: f64) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            self.diagnostics.push(Diagnostic::error(
                Phase::Export,
                "LUME0102",
                format!("page {} references missing node {}", self.page.id, node_id),
                Some(DiagnosticSubject::Page(self.page.id.clone())),
            ));
            return;
        };

        let x = parent_x + node.transform.x;
        let y = parent_y + node.transform.y;
        let (width, height) = crate::svg::node_size(node);

        match &node.kind {
            NodeKind::Frame | NodeKind::AutoLayout(_) | NodeKind::Rect => {
                if let Some(fill) = node.fills.first() {
                    if let Some(color) = self.fill_color(fill, Some(node)) {
                        self.fill_rect(x, y, width, height, color);
                    }
                }
                for child_id in &node.children {
                    self.render_node(child_id, x, y);
                }
            }
            NodeKind::Group => {
                for child_id in &node.children {
                    self.render_node(child_id, x, y);
                }
            }
            NodeKind::Text(_) => self.warn_unsupported_node(node, "text"),
            NodeKind::Ellipse => self.warn_unsupported_node(node, "ellipse"),
            NodeKind::Line(_) => self.warn_unsupported_node(node, "line"),
            NodeKind::Vector(_) => self.warn_unsupported_node(node, "vector path"),
            NodeKind::Image(_) => self.warn_unsupported_node(node, "image"),
            NodeKind::Instance { .. } => self.warn_unsupported_node(node, "instance"),
        }
    }

    fn fill_color(&mut self, fill: &Fill, node: Option<&Node>) -> Option<[u8; 4]> {
        match &fill.paint {
            Paint::Solid { color } => parse_color(color).or_else(|| {
                self.warn_unsupported_paint(node, "solid fill color");
                None
            }),
            Paint::Token { token } => {
                self.warn_token(node, token);
                None
            }
            Paint::LinearGradient { .. } | Paint::RadialGradient { .. } => {
                self.warn_unsupported_paint(node, "gradient fill");
                None
            }
        }
    }

    fn fill_rect(&mut self, x: f64, y: f64, width: f64, height: f64, color: [u8; 4]) {
        let start_x = (x * self.scale_x).floor().max(0.0) as u32;
        let start_y = (y * self.scale_y).floor().max(0.0) as u32;
        let end_x = ((x + width) * self.scale_x).ceil().min(self.width as f64) as u32;
        let end_y = ((y + height) * self.scale_y).ceil().min(self.height as f64) as u32;

        for py in start_y..end_y {
            for px in start_x..end_x {
                let idx = ((py * self.width + px) * 4) as usize;
                self.pixels[idx..idx + 4].copy_from_slice(&color);
            }
        }
    }

    fn warn_token(&mut self, node: Option<&Node>, token: &str) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0302",
            format!("PNG export cannot resolve token {}", token),
            node.map(|node| DiagnosticSubject::Node(node.id.clone()))
                .or_else(|| Some(DiagnosticSubject::Page(self.page.id.clone()))),
        ));
    }

    fn warn_unsupported_paint(&mut self, node: Option<&Node>, feature: &str) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0303",
            format!(
                "PNG conservative raster fallback does not yet render {}",
                feature
            ),
            node.map(|node| DiagnosticSubject::Node(node.id.clone()))
                .or_else(|| Some(DiagnosticSubject::Page(self.page.id.clone()))),
        ));
    }

    fn warn_unsupported_node(&mut self, node: &Node, feature: &str) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0304",
            format!(
                "PNG conservative raster fallback does not yet render {} node {}",
                feature, node.id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));
    }
}

fn page_pixel_size(page: &Page, dpi: f64, scale: f64) -> (u32, u32) {
    let (width_in, height_in) = match page.size.unit {
        Unit::Px => (page.size.width / dpi, page.size.height / dpi),
        Unit::Mm => (page.size.width / 25.4, page.size.height / 25.4),
        Unit::In => (page.size.width, page.size.height),
    };

    (
        (width_in * dpi * scale).round().max(1.0) as u32,
        (height_in * dpi * scale).round().max(1.0) as u32,
    )
}

fn parse_color(color: &Color) -> Option<[u8; 4]> {
    match color {
        Color::Hex { value } => {
            let value = value.trim_start_matches('#');
            if value.len() != 6 && value.len() != 8 {
                return None;
            }
            let r = u8::from_str_radix(&value[0..2], 16).ok()?;
            let g = u8::from_str_radix(&value[2..4], 16).ok()?;
            let b = u8::from_str_radix(&value[4..6], 16).ok()?;
            let a = if value.len() == 8 {
                u8::from_str_radix(&value[6..8], 16).ok()?
            } else {
                255
            };
            Some([r, g, b, a])
        }
        Color::Oklch { .. } | Color::Token { .. } => None,
    }
}

fn encode_png(width: u32, height: u32, rgba: &[u8]) -> Vec<u8> {
    let mut raw = Vec::with_capacity((width as usize * 4 + 1) * height as usize);
    for row in 0..height as usize {
        raw.push(0);
        let start = row * width as usize * 4;
        let end = start + width as usize * 4;
        raw.extend_from_slice(&rgba[start..end]);
    }

    let compressed = zlib_uncompressed(&raw);
    let mut png = Vec::new();
    png.extend_from_slice(b"\x89PNG\r\n\x1a\n");

    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&width.to_be_bytes());
    ihdr.extend_from_slice(&height.to_be_bytes());
    ihdr.extend_from_slice(&[8, 6, 0, 0, 0]);
    write_chunk(&mut png, b"IHDR", &ihdr);
    write_chunk(&mut png, b"IDAT", &compressed);
    write_chunk(&mut png, b"IEND", &[]);
    png
}

fn zlib_uncompressed(data: &[u8]) -> Vec<u8> {
    let mut out = vec![0x78, 0x01];
    let mut remaining = data;
    while !remaining.is_empty() {
        let chunk_len = remaining.len().min(u16::MAX as usize);
        let final_block = chunk_len == remaining.len();
        out.push(if final_block { 0x01 } else { 0x00 });
        let len = chunk_len as u16;
        out.extend_from_slice(&len.to_le_bytes());
        out.extend_from_slice(&(!len).to_le_bytes());
        out.extend_from_slice(&remaining[..chunk_len]);
        remaining = &remaining[chunk_len..];
    }
    out.extend_from_slice(&adler32(data).to_be_bytes());
    out
}

fn write_chunk(png: &mut Vec<u8>, kind: &[u8; 4], data: &[u8]) {
    png.extend_from_slice(&(data.len() as u32).to_be_bytes());
    png.extend_from_slice(kind);
    png.extend_from_slice(data);
    let mut crc_input = Vec::with_capacity(kind.len() + data.len());
    crc_input.extend_from_slice(kind);
    crc_input.extend_from_slice(data);
    png.extend_from_slice(&crc32(&crc_input).to_be_bytes());
}

fn adler32(data: &[u8]) -> u32 {
    const MOD: u32 = 65521;
    let mut a = 1u32;
    let mut b = 0u32;
    for byte in data {
        a = (a + *byte as u32) % MOD;
        b = (b + a) % MOD;
    }
    (b << 16) | a
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for byte in data {
        crc ^= *byte as u32;
        for _ in 0..8 {
            let mask = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xedb8_8320 & mask);
        }
    }
    !crc
}
