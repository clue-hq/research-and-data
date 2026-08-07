//! Safety net for the curated icon library (Step 8): every shipped icon path must
//! parse and stay within its 24×24 viewBox — a garbled path can never reach a design.

use lumen_core::icons::{icon_names, resolve_icon};

#[test]
fn every_library_icon_path_parses_and_fits_its_view_box() {
    for name in icon_names() {
        let icon = resolve_icon(name).expect("registry name resolves");
        let path = skia_safe::utils::parse_path::from_svg(icon.path_data)
            .unwrap_or_else(|| panic!("icon {name:?} has unparseable path data: {}", icon.path_data));
        let bounds = path.bounds();
        let [vbw, vbh] = icon.view_box;
        assert!(
            bounds.left >= -0.5
                && bounds.top >= -0.5
                && bounds.right <= vbw as f32 + 0.5
                && bounds.bottom <= vbh as f32 + 0.5,
            "icon {name:?} bounds {bounds:?} escape its {vbw}x{vbh} viewBox"
        );
        // A real glyph, not an empty/degenerate path.
        assert!(
            bounds.width() > 1.0 && bounds.height() > 1.0,
            "icon {name:?} is degenerate ({bounds:?})"
        );
    }
}
