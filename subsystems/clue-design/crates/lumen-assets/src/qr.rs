//! Deterministic QR code generation (Phase E Decision 1).
//!
//! QR codes are the first generation provider: pure encode, no AI
//! dependency, directly demanded by the ABM premise (per-account QR codes
//! on physical mailers linking to personalized landing pages). The SVG
//! serializer is owned by Lumen rather than borrowed from the qrcode
//! crate so byte equality holds across runs and dependency upgrades:
//! fixed header, fixed viewBox arithmetic, one path of unit cells in
//! row-major order, explicit 4-module quiet zone.

use lumen_core::{Diagnostic, Phase};
use qrcode::{Color as QrColor, EcLevel, QrCode};
use std::error::Error;
use std::fmt;

pub const QR_QUIET_ZONE_MODULES: u32 = 4;
/// Below roughly 20mm printed width, consumer phone cameras start
/// failing to lock onto dense QR codes.
pub const QR_MIN_PRINT_WIDTH_MM: f64 = 20.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QrEcLevel {
    L,
    M,
    Q,
    H,
}

impl QrEcLevel {
    pub fn parse(value: &str) -> Result<Self, String> {
        match value.trim().to_ascii_lowercase().as_str() {
            "l" | "low" => Ok(Self::L),
            "m" | "medium" => Ok(Self::M),
            "q" | "quartile" => Ok(Self::Q),
            "h" | "high" => Ok(Self::H),
            other => Err(format!(
                "unknown QR error-correction level {other:?}; expected l, m, q, or h"
            )),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::L => "l",
            Self::M => "m",
            Self::Q => "q",
            Self::H => "h",
        }
    }

    fn to_qrcode(self) -> EcLevel {
        match self {
            Self::L => EcLevel::L,
            Self::M => EcLevel::M,
            Self::Q => EcLevel::Q,
            Self::H => EcLevel::H,
        }
    }
}

#[derive(Clone, Debug)]
pub struct QrRequest {
    pub data: String,
    /// Defaults to M, or H when `print` is set (Decision 1).
    pub ec_level: Option<QrEcLevel>,
    pub print: bool,
    /// Declared physical width on the target medium, for the print-size
    /// diagnostic.
    pub target_width_mm: Option<f64>,
}

#[derive(Clone, Debug)]
pub struct QrOutput {
    pub svg: String,
    /// Data modules per side (excluding the quiet zone).
    pub module_count: u32,
    pub quiet_zone_modules: u32,
    pub ec_level: QrEcLevel,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug)]
pub struct QrError {
    pub code: &'static str,
    pub message: String,
    pub diagnostic: Diagnostic,
}

impl QrError {
    fn new(code: &'static str, diagnostic_code: &str, message: String) -> Self {
        Self {
            code,
            message: message.clone(),
            diagnostic: Diagnostic::error(Phase::Validation, diagnostic_code, message, None),
        }
    }
}

impl fmt::Display for QrError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for QrError {}

/// Generate a deterministic QR SVG: identical input yields identical
/// bytes and therefore an identical content digest.
pub fn generate_qr(request: &QrRequest) -> Result<QrOutput, Box<QrError>> {
    let data = request.data.trim();
    if data.is_empty() {
        return Err(Box::new(QrError::new(
            "qr.empty_data",
            "LUMA0702",
            "QR generation requires non-empty data".to_owned(),
        )));
    }

    let ec_level = request.ec_level.unwrap_or(if request.print {
        QrEcLevel::H
    } else {
        QrEcLevel::M
    });

    let code = QrCode::with_error_correction_level(data.as_bytes(), ec_level.to_qrcode()).map_err(
        |error| {
            Box::new(QrError::new(
                "qr.encode_failed",
                "LUMA0701",
                format!(
                    "QR encoding failed at level {} for {} bytes of data: {error}",
                    ec_level.as_str(),
                    data.len()
                ),
            ))
        },
    )?;

    let module_count = code.width() as u32;
    let svg = render_svg(&code, module_count);

    let mut diagnostics = Vec::new();
    if let Some(width_mm) = request.target_width_mm {
        if width_mm < QR_MIN_PRINT_WIDTH_MM {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Validation,
                    "LUMA0700",
                    format!(
                        "QR code declared at {width_mm:.1}mm wide is below the ~{QR_MIN_PRINT_WIDTH_MM:.0}mm reliable-scan threshold for print media"
                    ),
                    None,
                )
                .with_hint("Reserve at least 20mm of printed width (plus quiet zone) for scannable QR codes."),
            );
        }
    }

    Ok(QrOutput {
        svg,
        module_count,
        quiet_zone_modules: QR_QUIET_ZONE_MODULES,
        ec_level,
        diagnostics,
    })
}

fn render_svg(code: &QrCode, module_count: u32) -> String {
    let total = module_count + 2 * QR_QUIET_ZONE_MODULES;
    let colors = code.to_colors();
    let mut path = String::new();
    for y in 0..module_count {
        for x in 0..module_count {
            let index = (y * module_count + x) as usize;
            if colors[index] == QrColor::Dark {
                let cell_x = x + QR_QUIET_ZONE_MODULES;
                let cell_y = y + QR_QUIET_ZONE_MODULES;
                path.push_str(&format!("M{cell_x},{cell_y}h1v1h-1z"));
            }
        }
    }

    format!(
        concat!(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{total}\" height=\"{total}\" ",
            "viewBox=\"0 0 {total} {total}\" shape-rendering=\"crispEdges\">",
            "<rect width=\"{total}\" height=\"{total}\" fill=\"#ffffff\"/>",
            "<path d=\"{path}\" fill=\"#000000\"/>",
            "</svg>"
        ),
        total = total,
        path = path,
    )
}
