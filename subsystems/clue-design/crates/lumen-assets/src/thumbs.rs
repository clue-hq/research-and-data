//! Thumbnail derivation for raster assets.
//!
//! Rasters are resized to fit a bounding box and re-encoded as PNG; the
//! bytes go into the content-addressed store like any others. Vector
//! assets need no derived thumbnail — the sanitized SVG itself scales.

use image::imageops::FilterType;
use image::ImageReader;
use std::io::Cursor;

pub const THUMBNAIL_MAX_DIMENSION: u32 = 256;

#[derive(Clone, Debug)]
pub struct ThumbnailArtifact {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    pub pixel_width: u32,
    pub pixel_height: u32,
}

/// Derive a PNG thumbnail fitting `max_dimension`. Returns `None` when the
/// source does not decode or re-encoding fails; thumbnail failure is never
/// fatal to ingest.
pub fn derive_raster_thumbnail(bytes: &[u8], max_dimension: u32) -> Option<ThumbnailArtifact> {
    let reader = ImageReader::new(Cursor::new(bytes))
        .with_guessed_format()
        .ok()?;
    let image = reader.decode().ok()?;
    let resized = if image.width() <= max_dimension && image.height() <= max_dimension {
        image
    } else {
        image.resize(max_dimension, max_dimension, FilterType::Triangle)
    };

    let mut encoded = Vec::new();
    resized
        .write_to(&mut Cursor::new(&mut encoded), image::ImageFormat::Png)
        .ok()?;

    Some(ThumbnailArtifact {
        bytes: encoded,
        mime_type: "image/png".to_owned(),
        pixel_width: resized.width(),
        pixel_height: resized.height(),
    })
}
