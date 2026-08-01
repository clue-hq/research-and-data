//! Thumbnail derivation for raster assets.
//!
//! Rasters are resized to fit a bounding box and re-encoded as PNG; the
//! bytes go into the content-addressed store like any others. Vector
//! assets need no derived thumbnail — the sanitized SVG itself scales.

use image::imageops::FilterType;
use image::ImageReader;
use std::io::Cursor;

pub const THUMBNAIL_MAX_DIMENSION: u32 = 256;

/// Minimum short-side dimension for the agent-facing thumbnail. Vision
/// providers (Grok-4.5 and others) reject images whose short side is under
/// 512px — an 8×8 kit-asset thumbnail killed sweep run A2 downstream. The
/// Python consumer (`tools/view.py`) now upscales sub-floor images defensively;
/// this floor fixes the PRODUCER so a degenerate thumbnail is never emitted in
/// the first place (defense in depth, same 512 value).
pub const THUMBNAIL_MIN_SHORT_DIMENSION: u32 = 512;

#[derive(Clone, Debug)]
pub struct ThumbnailArtifact {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    pub pixel_width: u32,
    pub pixel_height: u32,
}

/// Derive a PNG thumbnail for a raster asset. Two size regimes:
///
/// - **Large source** (either side exceeds `max_dimension`): fit-resized down
///   into `max_dimension` with a smooth filter — unchanged behavior.
/// - **Small source** (fits within `max_dimension`): if its short side is below
///   `min_short_dimension`, upscaled with **nearest-neighbor** (aspect
///   preserved) so the short side meets the vision floor and icon pixels stay
///   crisp rather than smeared. Otherwise kept as-is.
///
/// The two floors deliberately overlap (`max` 256 < `min_short` 512): the max
/// bounds downscaling of photographs for UI grids, while the min guarantees a
/// tiny icon is never emitted below the vision-provider minimum. A source that
/// downscales to `max` may still have a short side under the vision floor —
/// that is the intended "normal" behavior, and the agent-facing view path
/// upscales it just-in-time.
///
/// Returns `None` when the source does not decode or re-encoding fails;
/// thumbnail failure is never fatal to ingest.
pub fn derive_raster_thumbnail(
    bytes: &[u8],
    max_dimension: u32,
    min_short_dimension: u32,
) -> Option<ThumbnailArtifact> {
    let reader = ImageReader::new(Cursor::new(bytes))
        .with_guessed_format()
        .ok()?;
    let image = reader.decode().ok()?;
    let resized = if image.width() <= max_dimension && image.height() <= max_dimension {
        upscale_to_short_floor(image, min_short_dimension)
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

/// Upscale `image` with nearest-neighbor so its short side reaches
/// `min_short_dimension`, preserving aspect ratio. A no-op when the short side
/// already meets the floor (or is degenerate). Nearest-neighbor magnifies the
/// real pixels without inventing detail — icon edges stay crisp instead of
/// blurred, and the vision provider can never reject the block.
fn upscale_to_short_floor(
    image: image::DynamicImage,
    min_short_dimension: u32,
) -> image::DynamicImage {
    let short = image.width().min(image.height());
    if short == 0 || short >= min_short_dimension {
        return image;
    }
    let scale = f64::from(min_short_dimension) / f64::from(short);
    let width = ((f64::from(image.width()) * scale).round() as u32).max(1);
    let height = ((f64::from(image.height()) * scale).round() as u32).max(1);
    image.resize_exact(width, height, FilterType::Nearest)
}
