use crate::scene::{
    Orientation, Page, PageOutputSize, PagePreset, PageSize, PageSizeSource, PhysicalPageSize,
    PhysicalUnit, RasterPageSize, Rect, Unit,
};

pub const POINTS_PER_INCH: f64 = 72.0;
pub const MM_PER_INCH: f64 = 25.4;

#[derive(Clone, Debug, PartialEq)]
pub struct PageGeometry {
    pub layout: Rect,
    pub source: Option<PageSizeSource>,
    pub physical: Option<PhysicalPageSize>,
    pub raster: Option<RasterPageSize>,
    pub canonical: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PageSizeInput {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
    pub preset: Option<PagePreset>,
    pub orientation: Orientation,
}

impl PageSizeInput {
    pub fn new(
        width: f64,
        height: f64,
        unit: Unit,
        preset: Option<PagePreset>,
        orientation: Orientation,
    ) -> Self {
        Self {
            width,
            height,
            unit,
            preset,
            orientation,
        }
    }
}

pub fn page_geometry(page: &Page) -> PageGeometry {
    let output = page.size.output.clone().unwrap_or(PageOutputSize {
        physical: None,
        raster: None,
    });
    PageGeometry {
        layout: Rect {
            x: 0.0,
            y: 0.0,
            width: page.size.width,
            height: page.size.height,
        },
        source: page
            .size
            .source
            .clone()
            .or_else(|| legacy_source_for(&page.size)),
        physical: output.physical,
        raster: output.raster,
        canonical: is_canonical_page_size(&page.size),
    }
}

pub fn is_canonical_page_size(size: &PageSize) -> bool {
    matches!(size.unit, Unit::Pt)
}

pub fn normalize_page_size(input: PageSizeInput) -> PageSize {
    let layout_width = unit_to_points(input.width, &input.unit);
    let layout_height = unit_to_points(input.height, &input.unit);
    let source = Some(PageSizeSource {
        width: input.width,
        height: input.height,
        unit: input.unit.clone(),
    });
    let output = output_for_source(input.width, input.height, &input.unit);

    PageSize {
        width: layout_width,
        height: layout_height,
        unit: Unit::Pt,
        preset: input.preset,
        orientation: input.orientation,
        source,
        output,
    }
}

pub fn page_size_for_preset(preset: &PagePreset, orientation: &Orientation) -> PageSize {
    let (base_width, base_height, unit): (f64, f64, Unit) = match preset {
        PagePreset::A4 => (210.0, 297.0, Unit::Mm),
        PagePreset::UsLetter => (8.5, 11.0, Unit::In),
        PagePreset::LinkedinAd => (1200.0, 627.0, Unit::Px),
        PagePreset::EnvelopeDl => (220.0, 110.0, Unit::Mm),
        PagePreset::Custom => (210.0, 297.0, Unit::Mm),
    };
    let short_side = base_width.min(base_height);
    let long_side = base_width.max(base_height);
    let (width, height) = match orientation {
        Orientation::Portrait => (short_side, long_side),
        Orientation::Landscape => (long_side, short_side),
    };

    normalize_page_size(PageSizeInput::new(
        width,
        height,
        unit,
        Some(preset.clone()),
        orientation.clone(),
    ))
}

pub fn unit_to_points(value: f64, unit: &Unit) -> f64 {
    match unit {
        Unit::Pt | Unit::Px => value,
        Unit::Mm => value * POINTS_PER_INCH / MM_PER_INCH,
        Unit::In => value * POINTS_PER_INCH,
    }
}

pub fn points_to_physical(value_pt: f64, unit: &PhysicalUnit) -> f64 {
    match unit {
        PhysicalUnit::Mm => value_pt / POINTS_PER_INCH * MM_PER_INCH,
        PhysicalUnit::In => value_pt / POINTS_PER_INCH,
    }
}

pub fn physical_to_inches(value: f64, unit: &PhysicalUnit) -> f64 {
    match unit {
        PhysicalUnit::Mm => value / MM_PER_INCH,
        PhysicalUnit::In => value,
    }
}

pub fn physical_page_size_inches(size: &PhysicalPageSize) -> (f64, f64) {
    (
        physical_to_inches(size.width, &size.unit),
        physical_to_inches(size.height, &size.unit),
    )
}

pub fn unit_to_inches(value: f64, unit: &Unit, dpi: f64) -> f64 {
    match unit {
        Unit::Pt => value / POINTS_PER_INCH,
        Unit::Px => value / dpi,
        Unit::Mm => value / MM_PER_INCH,
        Unit::In => value,
    }
}

pub fn page_size_points(page: &Page) -> (f64, f64) {
    if is_canonical_page_size(&page.size) {
        (page.size.width, page.size.height)
    } else {
        (
            unit_to_points(page.size.width, &page.size.unit),
            unit_to_points(page.size.height, &page.size.unit),
        )
    }
}

pub fn page_rect_points(page: &Page, include_bleed: bool) -> Rect {
    let scale = if is_canonical_page_size(&page.size) {
        1.0
    } else {
        unit_to_points(1.0, &page.size.unit)
    };
    let rect = if include_bleed {
        page.bleed.clone().unwrap_or(Rect {
            x: 0.0,
            y: 0.0,
            width: page.size.width,
            height: page.size.height,
        })
    } else {
        Rect {
            x: 0.0,
            y: 0.0,
            width: page.size.width,
            height: page.size.height,
        }
    };
    Rect {
        x: rect.x * scale,
        y: rect.y * scale,
        width: rect.width * scale,
        height: rect.height * scale,
    }
}

fn output_for_source(width: f64, height: f64, unit: &Unit) -> Option<PageOutputSize> {
    match unit {
        Unit::Pt => None,
        Unit::Px => Some(PageOutputSize {
            physical: None,
            raster: raster_size(width, height),
        }),
        Unit::Mm => Some(PageOutputSize {
            physical: Some(PhysicalPageSize {
                width,
                height,
                unit: PhysicalUnit::Mm,
            }),
            raster: None,
        }),
        Unit::In => Some(PageOutputSize {
            physical: Some(PhysicalPageSize {
                width,
                height,
                unit: PhysicalUnit::In,
            }),
            raster: None,
        }),
    }
}

fn raster_size(width: f64, height: f64) -> Option<RasterPageSize> {
    if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
        return None;
    }
    Some(RasterPageSize {
        width_px: width.round().max(1.0) as u32,
        height_px: height.round().max(1.0) as u32,
    })
}

fn legacy_source_for(size: &PageSize) -> Option<PageSizeSource> {
    if is_canonical_page_size(size) {
        return None;
    }
    Some(PageSizeSource {
        width: size.width,
        height: size.height,
        unit: size.unit.clone(),
    })
}
