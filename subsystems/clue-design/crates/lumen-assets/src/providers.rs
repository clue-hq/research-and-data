//! Generation and vectorization provider contracts (Phase E slice E8).
//!
//! Providers are adapters, not architecture: every provider returns a
//! [`ProviderArtifact`] that the shared ingest pipeline normalizes into a
//! first-class `AssetRecord` with provenance and licensing captured at
//! ingest (Decision 5). QR is the first concrete provider; AI image and
//! vectorization providers ship as deterministic stubs proving the seam,
//! so enabling a real model is configuration, not surgery.

use crate::qr::{generate_qr, QrRequest};
use lumen_core::{
    AssetGenerationRequest, AssetKind, AssetLicense, AssetVectorizationRequest, Diagnostic, Phase,
};
use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::sync::Arc;

#[derive(Clone, Debug)]
pub struct ProviderArtifact {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    pub kind: AssetKind,
    pub license: AssetLicense,
    pub provenance_notes: Vec<String>,
    pub provider_metadata: BTreeMap<String, String>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug)]
pub struct ProviderError {
    pub code: &'static str,
    pub message: String,
    pub diagnostic: Diagnostic,
}

impl ProviderError {
    pub fn new(code: &'static str, diagnostic_code: &str, message: String) -> Self {
        Self {
            code,
            message: message.clone(),
            diagnostic: Diagnostic::error(Phase::Validation, diagnostic_code, message, None),
        }
    }
}

impl fmt::Display for ProviderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for ProviderError {}

/// Source bytes handed to a vectorization provider. Resolution from the
/// asset store happens adapter-side; providers never touch storage.
#[derive(Clone, Debug)]
pub struct ProviderSourceBytes {
    pub mime_type: String,
    pub bytes: Vec<u8>,
}

pub trait AssetGenerationProvider: fmt::Debug + Send + Sync {
    fn id(&self) -> &'static str;
    fn generate(
        &self,
        request: &AssetGenerationRequest,
    ) -> Result<ProviderArtifact, Box<ProviderError>>;
}

pub trait AssetVectorizationProvider: fmt::Debug + Send + Sync {
    fn id(&self) -> &'static str;
    fn vectorize(
        &self,
        request: &AssetVectorizationRequest,
        source: &ProviderSourceBytes,
    ) -> Result<ProviderArtifact, Box<ProviderError>>;
}

fn generated_license(name: &str) -> AssetLicense {
    AssetLicense {
        name: name.to_owned(),
        allow_export: true,
        allow_modification: true,
        allow_embedding: true,
        allow_subsetting: true,
        source_url: None,
        restrictions: Vec::new(),
    }
}

/// QR codes adapted onto the generation seam: the request prompt is the
/// QR payload. The dedicated `generate_qr` surface remains the richer
/// entry point (EC levels, print sizing); this adapter proves that the
/// first concrete provider speaks the same contract as future AI ones.
#[derive(Clone, Debug, Default)]
pub struct QrGenerationProvider;

impl AssetGenerationProvider for QrGenerationProvider {
    fn id(&self) -> &'static str {
        "qr-v1"
    }

    fn generate(
        &self,
        request: &AssetGenerationRequest,
    ) -> Result<ProviderArtifact, Box<ProviderError>> {
        let output = generate_qr(&QrRequest {
            data: request.prompt.clone(),
            ec_level: None,
            print: false,
            target_width_mm: None,
        })
        .map_err(|error| {
            Box::new(ProviderError::new(
                error.code,
                &error.diagnostic.code.clone(),
                error.message.clone(),
            ))
        })?;

        let mut provider_metadata = BTreeMap::new();
        provider_metadata.insert("ec_level".to_owned(), output.ec_level.as_str().to_owned());
        provider_metadata.insert("module_count".to_owned(), output.module_count.to_string());
        provider_metadata.insert(
            "quiet_zone_modules".to_owned(),
            output.quiet_zone_modules.to_string(),
        );

        Ok(ProviderArtifact {
            bytes: output.svg.into_bytes(),
            mime_type: "image/svg+xml".to_owned(),
            kind: AssetKind::Vector,
            license: generated_license("generated_qr"),
            provenance_notes: vec![format!(
                "deterministic QR encode of {} data bytes",
                request.prompt.trim().len()
            )],
            provider_metadata,
            diagnostics: output.diagnostics,
        })
    }
}

/// Deterministic stand-in for an AI image provider: a solid-color PNG
/// derived from the prompt hash at the requested dimensions. Real
/// providers replace this implementation behind the same trait.
#[derive(Clone, Debug, Default)]
pub struct StubImageProvider;

impl AssetGenerationProvider for StubImageProvider {
    fn id(&self) -> &'static str {
        "stub-image-v0"
    }

    fn generate(
        &self,
        request: &AssetGenerationRequest,
    ) -> Result<ProviderArtifact, Box<ProviderError>> {
        if request.prompt.trim().is_empty() {
            return Err(Box::new(ProviderError::new(
                "provider.empty_prompt",
                "LUMA0702",
                "image generation requires a non-empty prompt".to_owned(),
            )));
        }
        let width = request.constraints.width.unwrap_or(512).clamp(1, 2048);
        let height = request.constraints.height.unwrap_or(512).clamp(1, 2048);

        let digest = crate::sha256_hex(request.prompt.trim().as_bytes());
        let red = u8::from_str_radix(&digest[0..2], 16).unwrap_or(0);
        let green = u8::from_str_radix(&digest[2..4], 16).unwrap_or(0);
        let blue = u8::from_str_radix(&digest[4..6], 16).unwrap_or(0);
        let alpha = if request.constraints.transparent_background == Some(true) {
            128
        } else {
            255
        };

        let mut buffer = image::RgbaImage::new(width, height);
        for pixel in buffer.pixels_mut() {
            *pixel = image::Rgba([red, green, blue, alpha]);
        }
        let mut bytes = Vec::new();
        image::DynamicImage::ImageRgba8(buffer)
            .write_to(
                &mut std::io::Cursor::new(&mut bytes),
                image::ImageFormat::Png,
            )
            .map_err(|error| {
                Box::new(ProviderError::new(
                    "provider.encode_failed",
                    "LUMA0604",
                    format!("stub image encoding failed: {error}"),
                ))
            })?;

        let mut provider_metadata = BTreeMap::new();
        provider_metadata.insert("prompt_digest".to_owned(), digest);
        provider_metadata.insert("width".to_owned(), width.to_string());
        provider_metadata.insert("height".to_owned(), height.to_string());

        Ok(ProviderArtifact {
            bytes,
            mime_type: "image/png".to_owned(),
            kind: AssetKind::RasterImage,
            license: generated_license("stub_generated"),
            provenance_notes: vec![format!(
                "stub image provider rendered a deterministic placeholder for prompt ({} chars)",
                request.prompt.trim().len()
            )],
            provider_metadata,
            diagnostics: Vec::new(),
        })
    }
}

/// Deterministic stand-in for raster-to-vector tracing: emits an SVG
/// placeholder carrying the source digest, proving the request/result
/// plumbing end to end without an actual tracer.
#[derive(Clone, Debug, Default)]
pub struct StubVectorizationProvider;

impl AssetVectorizationProvider for StubVectorizationProvider {
    fn id(&self) -> &'static str {
        "stub-vectorize-v0"
    }

    fn vectorize(
        &self,
        request: &AssetVectorizationRequest,
        source: &ProviderSourceBytes,
    ) -> Result<ProviderArtifact, Box<ProviderError>> {
        if source.bytes.is_empty() {
            return Err(Box::new(ProviderError::new(
                "provider.empty_source",
                "LUMA0604",
                format!(
                    "vectorization of asset {} received no source bytes",
                    request.source_asset_id
                ),
            )));
        }
        let digest = crate::sha256_hex(&source.bytes);
        let fill = format!("#{}", &digest[0..6]);
        let svg = format!(
            concat!(
                "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" ",
                "viewBox=\"0 0 64 64\">",
                "<rect width=\"64\" height=\"64\" fill=\"{fill}\"/>",
                "<path d=\"M8,8h48v48h-48z\" fill=\"none\" stroke=\"#000000\"/>",
                "</svg>"
            ),
            fill = fill,
        );

        let mut provider_metadata = BTreeMap::new();
        provider_metadata.insert("source_digest".to_owned(), digest);
        provider_metadata.insert("source_mime_type".to_owned(), source.mime_type.clone());
        provider_metadata.insert(
            "preserve_colors".to_owned(),
            request.preserve_colors.to_string(),
        );

        Ok(ProviderArtifact {
            bytes: svg.into_bytes(),
            mime_type: "image/svg+xml".to_owned(),
            kind: AssetKind::Vector,
            license: generated_license("stub_vectorized"),
            provenance_notes: vec![format!(
                "stub vectorization of source asset {}",
                request.source_asset_id
            )],
            provider_metadata,
            diagnostics: Vec::new(),
        })
    }
}

/// Provider lookup by id. Real providers are registered here by
/// configuration; unknown ids are typed errors, never panics.
#[derive(Clone, Debug, Default)]
pub struct ProviderRegistry {
    generators: BTreeMap<&'static str, Arc<dyn AssetGenerationProvider>>,
    vectorizers: BTreeMap<&'static str, Arc<dyn AssetVectorizationProvider>>,
}

impl ProviderRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_default_providers() -> Self {
        let mut registry = Self::new();
        registry.register_generator(Arc::new(QrGenerationProvider));
        registry.register_generator(Arc::new(StubImageProvider));
        registry.register_vectorizer(Arc::new(StubVectorizationProvider));
        registry
    }

    pub fn register_generator(&mut self, provider: Arc<dyn AssetGenerationProvider>) {
        self.generators.insert(provider.id(), provider);
    }

    pub fn register_vectorizer(&mut self, provider: Arc<dyn AssetVectorizationProvider>) {
        self.vectorizers.insert(provider.id(), provider);
    }

    pub fn generator_ids(&self) -> Vec<&'static str> {
        self.generators.keys().copied().collect()
    }

    pub fn generate(
        &self,
        provider_id: &str,
        request: &AssetGenerationRequest,
    ) -> Result<ProviderArtifact, Box<ProviderError>> {
        let provider = self.generators.get(provider_id).ok_or_else(|| {
            Box::new(ProviderError::new(
                "provider.unknown",
                "LUMA0602",
                format!(
                    "unknown generation provider {provider_id:?}; available: {:?}",
                    self.generator_ids()
                ),
            ))
        })?;
        provider.generate(request)
    }

    pub fn vectorize(
        &self,
        provider_id: &str,
        request: &AssetVectorizationRequest,
        source: &ProviderSourceBytes,
    ) -> Result<ProviderArtifact, Box<ProviderError>> {
        let provider = self.vectorizers.get(provider_id).ok_or_else(|| {
            Box::new(ProviderError::new(
                "provider.unknown",
                "LUMA0602",
                format!("unknown vectorization provider {provider_id:?}"),
            ))
        })?;
        provider.vectorize(request, source)
    }
}
