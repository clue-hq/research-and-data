use lumen_assets::{ingest, sanitize_svg, IngestRequest, THUMBNAIL_MAX_DIMENSION};
use lumen_core::AssetKind;

const LOGO_PNG: &[u8] = include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");

const HOSTILE_SVG: &str = r##"<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120px" height="60" viewBox="0 0 120 60">
  <script>alert('owned')</script>
  <rect x="0" y="0" width="120" height="60" fill="#0F766E" onload="alert('x')" onclick="steal()"/>
  <a href="javascript:alert(1)"><text x="10" y="30">click</text></a>
  <a href="java&#115;cript:alert(2)"><text x="10" y="50">sneaky</text></a>
  <foreignObject width="100" height="50"><body xmlns="http://www.w3.org/1999/xhtml"><iframe src="https://evil.example"/></body></foreignObject>
  <circle cx="30" cy="30" r="10" fill="#075E68"/>
</svg>
"##;

fn make_png(width: u32, height: u32) -> Vec<u8> {
    let mut buffer = image::RgbaImage::new(width, height);
    for pixel in buffer.pixels_mut() {
        *pixel = image::Rgba([20, 90, 160, 255]);
    }
    let mut bytes = Vec::new();
    image::DynamicImage::ImageRgba8(buffer)
        .write_to(
            &mut std::io::Cursor::new(&mut bytes),
            image::ImageFormat::Png,
        )
        .expect("png encode");
    bytes
}

#[test]
fn probe_fills_dimensions_dpi_and_transparency() {
    let output = ingest(&IngestRequest::new(LOGO_PNG)).expect("ingest");

    let raster = output.raster.expect("raster metadata");
    assert_eq!(raster.pixel_width, 8);
    assert_eq!(raster.pixel_height, 8);
    assert_eq!(raster.has_alpha, Some(true));
    // Fixture carries a pHYs chunk at 11811 ppm ~ 300.0 dpi.
    let dpi = raster.dpi_x.expect("dpi");
    assert!((dpi - 300.0).abs() < 0.5, "dpi was {dpi}");
    assert_eq!(raster.aspect_ratio, Some(1.0));
}

#[test]
fn hostile_svg_is_sanitized_with_diagnostic() {
    let output = ingest(&IngestRequest {
        declared_mime: Some("image/svg+xml"),
        filename: Some("hostile.svg"),
        ..IngestRequest::new(HOSTILE_SVG.as_bytes())
    })
    .expect("svg ingest");

    let sanitized = String::from_utf8(output.bytes.clone()).expect("utf8");
    assert!(!sanitized.contains("<script"), "{sanitized}");
    assert!(!sanitized.to_ascii_lowercase().contains("onload"));
    assert!(!sanitized.to_ascii_lowercase().contains("onclick"));
    assert!(!sanitized.to_ascii_lowercase().contains("foreignobject"));
    assert!(!sanitized.to_ascii_lowercase().contains("javascript:"));
    assert!(!sanitized.contains("evil.example"));
    // Benign content survives.
    assert!(sanitized.contains("<rect"));
    assert!(sanitized.contains("<circle"));
    assert!(sanitized.contains("#0F766E"));

    assert_eq!(output.kind, AssetKind::Vector);
    let vector = output.vector.expect("vector metadata");
    assert_eq!(vector.width, Some(120.0));
    assert_eq!(vector.height, Some(60.0));
    assert_eq!(vector.view_box, Some([0.0, 0.0, 120.0, 60.0]));

    let sanitize_warning = output
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUMA0603")
        .expect("sanitization diagnostic");
    assert!(sanitize_warning.message.contains("script element"));
    assert!(sanitize_warning.message.contains("foreignObject element"));
    assert!(sanitize_warning.message.contains("onload attribute"));
}

#[test]
fn sanitization_is_idempotent() {
    let first = sanitize_svg(HOSTILE_SVG.as_bytes()).expect("first pass");
    let second = sanitize_svg(&first.bytes).expect("second pass");

    assert!(second.removed.is_empty(), "{:?}", second.removed);
    assert_eq!(first.bytes, second.bytes);
}

#[test]
fn unparseable_svg_is_rejected_not_stored() {
    let error = ingest(&IngestRequest {
        declared_mime: Some("image/svg+xml"),
        ..IngestRequest::new(
            b"<svg><rect


// not xml at all <<<",
        )
    })
    .expect_err("broken svg must reject");

    assert_eq!(error.code, "ingest.svg_invalid");
    assert_eq!(error.diagnostic.code, "LUMA0604");
}

#[test]
fn large_raster_gets_bounded_thumbnail() {
    let png = make_png(600, 400);
    let output = ingest(&IngestRequest::new(&png)).expect("ingest");

    let thumbnail = output.thumbnail.expect("thumbnail");
    assert_eq!(thumbnail.mime_type, "image/png");
    assert!(thumbnail.pixel_width <= THUMBNAIL_MAX_DIMENSION);
    assert!(thumbnail.pixel_height <= THUMBNAIL_MAX_DIMENSION);
    // Aspect ratio preserved by fit-resize.
    assert_eq!(thumbnail.pixel_width, 256);
    assert!(thumbnail.pixel_height >= 169 && thumbnail.pixel_height <= 172);
    assert_eq!(
        lumen_assets::sniff_mime(&thumbnail.bytes),
        Some("image/png")
    );
}

#[test]
fn small_raster_thumbnail_keeps_original_size() {
    let output = ingest(&IngestRequest::new(LOGO_PNG)).expect("ingest");
    let thumbnail = output.thumbnail.expect("thumbnail");
    assert_eq!(thumbnail.pixel_width, 8);
    assert_eq!(thumbnail.pixel_height, 8);
}
