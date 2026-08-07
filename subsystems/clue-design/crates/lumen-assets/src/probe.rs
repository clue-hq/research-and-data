//! Raster probing: dimensions, transparency, and physical density.
//!
//! The `image` crate supplies dimensions and color type; density is parsed
//! directly from container metadata (PNG `pHYs`, JPEG JFIF APP0) because
//! decoders do not expose it.

use image::ImageReader;
use lumen_core::RasterAssetMetadata;
use std::io::Cursor;

const METERS_PER_INCH: f64 = 0.0254;

/// Probe raster bytes. Returns `None` when the bytes do not decode.
pub fn probe_raster(bytes: &[u8]) -> Option<RasterAssetMetadata> {
    let reader = ImageReader::new(Cursor::new(bytes))
        .with_guessed_format()
        .ok()?;
    let image = reader.decode().ok()?;
    let pixel_width = image.width();
    let pixel_height = image.height();
    let has_alpha = image.color().has_alpha();
    let dpi = parse_png_dpi(bytes).or_else(|| parse_jpeg_dpi(bytes));

    Some(RasterAssetMetadata {
        pixel_width,
        pixel_height,
        dpi_x: dpi.map(|(x, _)| x),
        dpi_y: dpi.map(|(_, y)| y),
        has_alpha: Some(has_alpha),
        color_profile: None,
        aspect_ratio: (pixel_height > 0).then(|| f64::from(pixel_width) / f64::from(pixel_height)),
    })
}

/// Parse the PNG `pHYs` chunk (pixels per meter) into DPI.
pub fn parse_png_dpi(bytes: &[u8]) -> Option<(f64, f64)> {
    const SIGNATURE: &[u8] = &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
    let rest = bytes.strip_prefix(SIGNATURE)?;
    let mut offset = 0usize;
    while offset + 12 <= rest.len() {
        let length = u32::from_be_bytes(rest[offset..offset + 4].try_into().ok()?) as usize;
        let chunk_type = &rest[offset + 4..offset + 8];
        let data_start = offset + 8;
        let data_end = data_start.checked_add(length)?;
        if data_end + 4 > rest.len() {
            return None;
        }
        if chunk_type == b"pHYs" && length == 9 {
            let data = &rest[data_start..data_end];
            let pixels_per_meter_x = u32::from_be_bytes(data[0..4].try_into().ok()?);
            let pixels_per_meter_y = u32::from_be_bytes(data[4..8].try_into().ok()?);
            let unit = data[8];
            if unit == 1 {
                return Some((
                    f64::from(pixels_per_meter_x) * METERS_PER_INCH,
                    f64::from(pixels_per_meter_y) * METERS_PER_INCH,
                ));
            }
            return None;
        }
        if chunk_type == b"IDAT" || chunk_type == b"IEND" {
            return None;
        }
        offset = data_end + 4;
    }
    None
}

/// Parse JFIF APP0 density (dots per inch or per centimeter) into DPI.
pub fn parse_jpeg_dpi(bytes: &[u8]) -> Option<(f64, f64)> {
    if !bytes.starts_with(&[0xFF, 0xD8]) {
        return None;
    }
    let mut offset = 2usize;
    while offset + 4 <= bytes.len() {
        if bytes[offset] != 0xFF {
            return None;
        }
        let marker = bytes[offset + 1];
        // Standalone markers without a length payload.
        if marker == 0xD8 || (0xD0..=0xD7).contains(&marker) || marker == 0x01 {
            offset += 2;
            continue;
        }
        // Start of scan: no metadata beyond this point.
        if marker == 0xDA {
            return None;
        }
        let length = usize::from(u16::from_be_bytes([bytes[offset + 2], bytes[offset + 3]]));
        if length < 2 || offset + 2 + length > bytes.len() {
            return None;
        }
        if marker == 0xE0 {
            let segment = &bytes[offset + 4..offset + 2 + length];
            if segment.len() >= 12 && &segment[0..5] == b"JFIF\0" {
                let units = segment[7];
                let x_density = f64::from(u16::from_be_bytes([segment[8], segment[9]]));
                let y_density = f64::from(u16::from_be_bytes([segment[10], segment[11]]));
                return match units {
                    1 => Some((x_density, y_density)),
                    2 => Some((x_density * 2.54, y_density * 2.54)),
                    _ => None,
                };
            }
        }
        offset += 2 + length;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jfif_density_parses_inch_and_centimeter_units() {
        // Minimal JFIF header: SOI + APP0 with 300x300 dpi (units=1).
        let mut jpeg = vec![0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10];
        jpeg.extend_from_slice(b"JFIF\0");
        jpeg.extend_from_slice(&[0x01, 0x02, 0x01, 0x01, 0x2C, 0x01, 0x2C, 0x00, 0x00]);
        assert_eq!(parse_jpeg_dpi(&jpeg), Some((300.0, 300.0)));

        // Same header with dots-per-centimeter units (units byte).
        jpeg[13] = 0x02;
        let parsed = parse_jpeg_dpi(&jpeg).expect("cm density");
        assert!((parsed.0 - 300.0 * 2.54).abs() < 1e-9);

        // Aspect-ratio-only density (units=0) yields no DPI.
        jpeg[13] = 0x00;
        assert_eq!(parse_jpeg_dpi(&jpeg), None);
    }
}
