//! W1.2 — a vector asset gets a REAL raster thumbnail.
//!
//! Every consumer that can only read pixels (the agent's `view`, the describe
//! stage, the vision APIs) was blind to SVGs, so every logo in a brand kit was
//! invisible to the trio that has to decide whether to place it. `lumen-skia`
//! already rasterizes placed SVG assets during export; these tests pin the
//! small public function that does the same thing for one standalone asset.
//!
//! The dimension policy is `lumen-assets`' thumbnail policy — the two bounds
//! ride in as parameters (lumen-skia may not depend on lumen-assets), so the
//! CONSTANTS have exactly one home and the two regimes are pinned here.

use lumen_skia::rasterize_svg_thumbnail;
use skia_safe::{surfaces, Data, Image};

/// The `lumen-assets` constants, passed the way the helper passes them.
const MAX_DIMENSION: u32 = 256;
const MIN_SHORT_DIMENSION: u32 = 512;

fn wordmark_svg() -> Vec<u8> {
    br##"<svg xmlns="http://www.w3.org/2000/svg" width="240" height="48" viewBox="0 0 240 48"><rect x="0" y="0" width="240" height="48" fill="#ff0000"/></svg>"##.to_vec()
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
fn a_small_vector_rasterizes_up_to_the_vision_floor_and_carries_real_pixels() {
    let (png, width, height) =
        rasterize_svg_thumbnail(&wordmark_svg(), MAX_DIMENSION, MIN_SHORT_DIMENSION)
            .expect("a well-formed wordmark rasterizes");

    // 240x48 fits inside the 256 box, so the SMALL-source regime applies: the
    // short side is lifted to the 512 vision floor, aspect preserved.
    assert_eq!((width, height), (2560, 512));
    assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n", "PNG magic");

    let decoded = Image::from_encoded(Data::new_copy(&png)).expect("thumbnail decodes as PNG");
    assert_eq!((decoded.width(), decoded.height()), (2560, 512));

    // …and the SVG actually painted: the red plate covers the whole box.
    assert_eq!(pixel(&png, 1280, 256), [255, 0, 0, 255]);
}

#[test]
fn a_large_vector_fits_into_the_max_dimension_box() {
    let svg = br##"<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="500" viewBox="0 0 1000 500"><rect width="1000" height="500" fill="#0000ff"/></svg>"##;

    let (_png, width, height) = rasterize_svg_thumbnail(svg, MAX_DIMENSION, MIN_SHORT_DIMENSION)
        .expect("a large vector rasterizes");

    assert_eq!((width, height), (256, 128));
}

#[test]
fn a_viewbox_only_vector_takes_its_aspect_from_the_view_box() {
    // Percentage width/height: `intrinsic_size()` resolves to 0, exactly the
    // shape a hand-authored logo.svg takes. The viewBox still establishes the
    // aspect, so the thumbnail is not squashed into a square.
    let svg = br##"<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 100 50"><rect width="100" height="50" fill="#00ff00"/></svg>"##;

    let (png, width, height) = rasterize_svg_thumbnail(svg, MAX_DIMENSION, MIN_SHORT_DIMENSION)
        .expect("a viewBox-only vector rasterizes");

    assert_eq!((width, height), (1024, 512));
    assert_eq!(pixel(&png, 512, 256), [0, 255, 0, 255]);
}

#[test]
fn a_sizeless_vector_falls_back_to_a_square_at_the_vision_floor() {
    // No width/height, no viewBox: nothing establishes an aspect ratio, so the
    // container is a square at the floor rather than a fabricated shape.
    let svg = br##"<svg xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#123456"/></svg>"##;

    let (_png, width, height) = rasterize_svg_thumbnail(svg, MAX_DIMENSION, MIN_SHORT_DIMENSION)
        .expect("a sizeless vector still rasterizes");

    assert_eq!((width, height), (512, 512));
}

#[test]
fn transparency_is_preserved_rather_than_flattened_onto_invented_paper() {
    // A logo's transparent ground is the SAME shape a transparent PNG logo
    // already takes through this pipeline — inventing white paper here would
    // wreck every mark drawn for a dark background.
    let svg = br##"<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect x="0" y="0" width="32" height="64" fill="#ff0000"/></svg>"##;

    let (png, width, _height) =
        rasterize_svg_thumbnail(svg, MAX_DIMENSION, MIN_SHORT_DIMENSION).expect("rasterizes");

    assert_eq!(pixel(&png, 10, 256)[3], 255, "painted half is opaque");
    assert_eq!(
        pixel(&png, width as i32 - 10, 256)[3],
        0,
        "unpainted half stays transparent"
    );
}

#[test]
fn bytes_that_are_not_a_parseable_vector_return_none_instead_of_failing() {
    // Ingest must never fail because a thumbnail could not be derived — the
    // caller falls back, silently, exactly as it did before this slice.
    assert!(
        rasterize_svg_thumbnail(b"not an svg at all", MAX_DIMENSION, MIN_SHORT_DIMENSION).is_none()
    );
    assert!(rasterize_svg_thumbnail(b"", MAX_DIMENSION, MIN_SHORT_DIMENSION).is_none());
}

#[test]
fn the_result_is_deterministic() {
    let first = rasterize_svg_thumbnail(&wordmark_svg(), MAX_DIMENSION, MIN_SHORT_DIMENSION)
        .expect("rasterizes");
    let second = rasterize_svg_thumbnail(&wordmark_svg(), MAX_DIMENSION, MIN_SHORT_DIMENSION)
        .expect("rasterizes");
    assert_eq!(first, second);
}
