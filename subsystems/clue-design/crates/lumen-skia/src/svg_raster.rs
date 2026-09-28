//! Standalone SVG → PNG thumbnail rasterization (W1.2).
//!
//! A vector asset used to carry no pixels anywhere: `lumen-assets` derives a
//! thumbnail only for rasters ("the sanitized SVG itself scales"), which is
//! true for the *canvas* and false for everything that can only read pixels —
//! the agent's `view("asset:<id>")`, the describe stage, the vision APIs. Every
//! logo in a brand kit was therefore invisible to the trio deciding whether to
//! place it.
//!
//! The rasterization itself is not new: [`crate::render`] already paints placed
//! SVG assets through `skia_safe::svg::Dom`. This module exposes the same
//! machinery for ONE standalone asset, so the API helper can attach a real PNG
//! thumbnail at ingest. It lives here (not in `lumen-assets`) because
//! `lumen-assets` is deliberately light — the `image` crate only, never Skia —
//! and the helper is the composition point that already depends on both.

use lumen_export::ensure_raster_within_budget;
use skia_safe::{surfaces, AlphaType, ColorType, EncodedImageFormat, Image, ImageInfo};

/// Rasterize `svg_bytes` into a PNG thumbnail, returning
/// `(png_bytes, pixel_width, pixel_height)`.
///
/// `max_dimension` / `min_short_dimension` are the caller's thumbnail bounds —
/// the caller passes `lumen_assets::THUMBNAIL_MAX_DIMENSION` /
/// `THUMBNAIL_MIN_SHORT_DIMENSION`, so the CONSTANTS keep exactly one home
/// (this crate may not depend on `lumen-assets`). The size policy those bounds
/// drive mirrors `lumen_assets::thumbs::derive_raster_thumbnail` so a logo
/// delivered as SVG and the same logo delivered as PNG produce the same-sized
/// thumbnail — see [`thumbnail_target_size`].
///
/// Unlike the raster path there is no resize step: a vector has no real pixels
/// to resample, so it is painted DIRECTLY at the target size and every
/// thumbnail is crisp at its own resolution.
///
/// Returns `None` on any failure — unparseable bytes, an oversized target, a
/// surface or encode failure, **or a render that painted nothing at all**
/// (Skia's SVG support is minimal; see the guard below). Thumbnail derivation
/// is never fatal to ingest; the caller falls back to whatever it did before.
pub fn rasterize_svg_thumbnail(
    svg_bytes: &[u8],
    max_dimension: u32,
    min_short_dimension: u32,
) -> Option<(Vec<u8>, u32, u32)> {
    let mut dom = crate::svg_dom::parse(svg_bytes).ok()?;

    // A root with absolute width/height renders at its intrinsic size and
    // ignores the container size, so it is scaled; a root without one (a
    // percentage or omitted width, the common hand-authored `logo.svg` shape)
    // takes the container size instead. Both mirror `render.rs`'s SVG branch.
    let intrinsic = dom.root().intrinsic_size();
    let scaled = intrinsic.width > 0.0 && intrinsic.height > 0.0;
    let source = if scaled {
        Some((f64::from(intrinsic.width), f64::from(intrinsic.height)))
    } else {
        dom.root().view_box().and_then(|view_box| {
            let (width, height) = (f64::from(view_box.width()), f64::from(view_box.height()));
            (width > 0.0 && height > 0.0).then_some((width, height))
        })
    };

    let (width, height) = match source {
        Some((source_width, source_height)) => thumbnail_target_size(
            source_width,
            source_height,
            max_dimension,
            min_short_dimension,
        ),
        // Neither an intrinsic size nor a viewBox: nothing establishes an
        // aspect ratio, so a square at the vision floor is the honest guess
        // rather than a fabricated shape.
        None => (min_short_dimension.max(1), min_short_dimension.max(1)),
    };

    // The shared export ceiling, so an extreme aspect ratio degrades to "no
    // thumbnail" instead of asking for an unbounded pixel buffer.
    ensure_raster_within_budget(width, height, "rasterizing an SVG asset thumbnail").ok()?;

    if !scaled {
        dom.set_container_size((width as f32, height as f32));
    }

    // CPU backend, pinned, exactly as the scene rasterizer: identical bytes for
    // identical inputs. The surface is left transparent where the vector paints
    // nothing — a transparent PNG logo already flows through this pipeline the
    // same way, and inventing white paper here would wreck every mark drawn for
    // a dark ground.
    let mut surface =
        surfaces::raster_n32_premul((i32::try_from(width).ok()?, i32::try_from(height).ok()?))?;
    {
        let canvas = surface.canvas();
        if scaled {
            canvas.scale((
                width as f32 / intrinsic.width,
                height as f32 / intrinsic.height,
            ));
        }
        dom.render(canvas);
    }

    // Parsing is not painting. `skia_safe::svg::Dom` is a MINIMAL renderer: it
    // accepts plenty it cannot draw (filtered or masked groups, an embedded
    // `<image href>`, CSS it does not implement) and leaves the surface fully
    // transparent — which encodes into a perfectly valid, perfectly blank PNG.
    // Storing that would serve a blank rectangle as the asset's LOOK:
    // confidently wrong, where the honest outcome is no raster preview at all.
    // A vector that genuinely paints nothing is no more useful as a thumbnail,
    // so `None` is right for it too, and the caller falls back as it does for
    // bytes that never parsed.
    let image = surface.image_snapshot();
    if !painted_anything(&image) {
        return None;
    }

    let png = image.encode(None, EncodedImageFormat::PNG, Some(100))?;
    Some((png.as_bytes().to_vec(), width, height))
}

/// Whether `image` carries a single non-transparent pixel.
///
/// Read back unpremultiplied so alpha is the raw coverage byte. A read-back
/// that fails answers "no" — an image whose pixels cannot be inspected must
/// not be published as a thumbnail on the strength of an assumption.
///
/// ONE ROW at a time, into a single reused buffer, returning at the first
/// painted pixel. Reading the whole surface back doubled the peak memory of the
/// worst case this function exists to serve: a thin vector (a 2560x24 divider)
/// blows up to ~28 MP under the thumbnail floor, which the export budget admits
/// — and a full read-back then asked for a second buffer the same size as the
/// surface itself. The scan is byte-for-byte the same question, asked in
/// `width * 4` bytes.
fn painted_anything(image: &Image) -> bool {
    let row_bytes = match usize::try_from(image.width()) {
        Ok(width) => width * 4,
        Err(_) => return false,
    };
    if row_bytes == 0 || image.height() <= 0 {
        return false;
    }
    let info = ImageInfo::new(
        (image.width(), 1),
        ColorType::RGBA8888,
        AlphaType::Unpremul,
        None,
    );
    let mut row = vec![0u8; row_bytes];
    for y in 0..image.height() {
        if !image.read_pixels(
            &info,
            &mut row,
            row_bytes,
            (0, y),
            skia_safe::image::CachingHint::Disallow,
        ) {
            return false;
        }
        if row.chunks_exact(4).any(|pixel| pixel[3] != 0) {
            return true;
        }
    }
    false
}

/// The thumbnail size for a vector of intrinsic `width`×`height` user units.
///
/// Mirrors `lumen_assets::thumbs::derive_raster_thumbnail`'s two regimes so the
/// SVG and PNG deliveries of one logo agree:
///
/// - **Large source** (either side over `max_dimension`): fit into the
///   `max_dimension` box, aspect preserved.
/// - **Small source**: lift the short side to `min_short_dimension` (the vision
///   provider floor) when it is under it, aspect preserved; otherwise keep it.
///
/// The two bounds overlap deliberately (256 < 512) — see the policy note on
/// `lumen_assets::thumbs::THUMBNAIL_MIN_SHORT_DIMENSION`.
fn thumbnail_target_size(
    width: f64,
    height: f64,
    max_dimension: u32,
    min_short_dimension: u32,
) -> (u32, u32) {
    let max = f64::from(max_dimension);
    let scale = if width <= max && height <= max {
        let short = width.min(height);
        let floor = f64::from(min_short_dimension);
        if short <= 0.0 || short >= floor {
            1.0
        } else {
            floor / short
        }
    } else {
        (max / width).min(max / height)
    };
    (
        round_to_pixels(width * scale),
        round_to_pixels(height * scale),
    )
}

/// One rounded pixel dimension, never zero and never past `u32`.
fn round_to_pixels(value: f64) -> u32 {
    value.round().clamp(1.0, f64::from(u32::MAX)) as u32
}

#[cfg(test)]
mod tests {
    use super::thumbnail_target_size;

    #[test]
    fn the_size_policy_mirrors_the_raster_thumbnail_regimes() {
        // Large source → fit into the max box.
        assert_eq!(thumbnail_target_size(1000.0, 500.0, 256, 512), (256, 128));
        // Small source under the vision floor → short side lifted to it.
        assert_eq!(thumbnail_target_size(240.0, 48.0, 256, 512), (2560, 512));
        // Small source already over the floor cannot happen with a 256 max, but
        // the branch is real when a caller passes different bounds.
        assert_eq!(thumbnail_target_size(200.0, 100.0, 256, 64), (200, 100));
        // Degenerate sides never produce a zero dimension.
        assert_eq!(thumbnail_target_size(0.4, 0.4, 256, 512), (512, 512));
    }
}
