//! Curated icon library for `svg(icon:name)` (Step 8 / Deviation D).
//!
//! Slice 0 ships a small, hand-verified set of **filled** icons rather than a
//! generative-vector model, because a curated set is reliable and crisp at any size
//! — a model garbles small flat marks. Each icon is a single SVG path authored in a
//! 24×24 viewBox; the DSL lowers `svg(icon:name)` to a [`crate::scene::VectorNode`]
//! carrying that path and the viewBox, and the renderers scale it (uniform, centered)
//! into the node's box. Every icon is a closed FILLED shape, so it recolors through
//! the node's `fill($color.*)` — no stroke bookkeeping required.
//!
//! The shapes here are either standard public icon geometry (star/heart/check/x —
//! the ubiquitous Material/Bootstrap forms) or simple constructed polygons; all are
//! covered by a parse test in `lumen-skia` so a malformed path can never ship.

/// One resolved icon: its path data and the source viewBox the path was authored in.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IconDef {
    pub path_data: &'static str,
    /// Source [width, height] the path is drawn against; renderers fit this to the box.
    pub view_box: [f64; 2],
}

const VIEW_BOX: [f64; 2] = [24.0, 24.0];

/// The curated registry: `(name, path_data)` in a 24×24 viewBox. Names are stable.
const ICONS: &[(&str, &str)] = &[
    // — geometric primitives (bullets, markers, dots) —
    ("circle", "M22 12C22 17.523 17.523 22 12 22C6.477 22 2 17.523 2 12C2 6.477 6.477 2 12 2C17.523 2 22 6.477 22 12Z"),
    ("dot", "M16 12C16 14.209 14.209 16 12 16C9.791 16 8 14.209 8 12C8 9.791 9.791 8 12 8C14.209 8 16 9.791 16 12Z"),
    ("square", "M3 3H21V21H3Z"),
    ("diamond", "M12 2L22 12L12 22L2 12Z"),
    ("triangle-up", "M12 4L21 20H3Z"),
    ("play", "M6 4L20 12L6 20Z"),
    ("star", "M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26Z"),
    ("heart", "M12 21.35L10.55 20.03C5.4 15.36 2 12.28 2 8.5C2 5.42 4.42 3 7.5 3C9.24 3 10.91 3.81 12 5.09C13.09 3.81 14.76 3 16.5 3C19.58 3 22 5.42 22 8.5C22 12.28 18.6 15.36 13.45 20.04L12 21.35Z"),
    ("bolt", "M13 2L4 14H11L10 22L20 9H13Z"),
    // — status / actions —
    ("check", "M9 16.17L4.83 12L3.41 13.41L9 19L21 7L19.59 5.59Z"),
    ("x", "M6 4L12 10L18 4L20 6L14 12L20 18L18 20L12 14L6 20L4 18L10 12L4 6Z"),
    ("plus", "M10 3H14V10H21V14H14V21H10V14H3V10H10Z"),
    ("minus", "M3 10H21V14H3Z"),
    // — directional (block arrows) —
    ("arrow-right", "M4 10H14V6L21 12L14 18V14H4Z"),
    ("arrow-left", "M20 10H10V6L3 12L10 18V14H20Z"),
    ("arrow-up", "M10 20V10H6L12 3L18 10H14V20Z"),
    ("arrow-down", "M10 4V14H6L12 21L18 14H14V4Z"),
    // — domain pictograms (trust/security, process steps, product) —
    // Same authoring rules as above: solid filled forms, no holes; overlapping
    // same-direction subpaths union under nonzero winding.
    ("shield", "M12 2L20 5V11C20 16.55 16.6 20.74 12 22C7.4 20.74 4 16.55 4 11V5Z"),
    ("lock", "M12 3C8.69 3 6 5.69 6 9V10H9V9C9 7.34 10.34 6 12 6C13.66 6 15 7.34 15 9V10H18V9C18 5.69 15.31 3 12 3ZM5 11H19V21H5Z"),
    ("key", "M12.65 10C11.83 7.67 9.61 6 7 6C3.69 6 1 8.69 1 12C1 15.31 3.69 18 7 18C9.61 18 11.83 16.33 12.65 14H17V18H21V14H23V10H12.65Z"),
    ("user", "M12 4C14.21 4 16 5.79 16 8C16 10.21 14.21 12 12 12C9.79 12 8 10.21 8 8C8 5.79 9.79 4 12 4ZM12 14C16.42 14 20 15.79 20 18V20H4V18C4 15.79 7.58 14 12 14Z"),
    ("layers", "M12 2L22 8L12 14L2 8ZM4.7 11.1L12 15.5L19.3 11.1L22 12.7L12 18.7L2 12.7Z"),
    ("pencil", "M3 17.25V21H6.75L17.81 9.94L14.06 6.19ZM20.71 7.04C21.1 6.65 21.1 6.02 20.71 5.63L18.37 3.29C17.98 2.9 17.35 2.9 16.96 3.29L15.13 5.12L18.88 8.87Z"),
    ("sparkles", "M12 2L13.9 8.1L20 10L13.9 11.9L12 18L10.1 11.9L4 10L10.1 8.1ZM19 14L19.9 16.6L22.5 17.5L19.9 18.4L19 21L18.1 18.4L15.5 17.5L18.1 16.6Z"),
    ("download", "M10 3H14V11H18.5L12 17.5L5.5 11H10ZM4 19H20V22H4Z"),
    ("chart-bar", "M4 10H8V20H4ZM10 4H14V20H10ZM16 13H20V20H16Z"),
    ("lightbulb", "M12 2C8.13 2 5 5.13 5 9C5 11.38 6.19 13.47 8 14.74V17H16V14.74C17.81 13.47 19 11.38 19 9C19 5.13 15.87 2 12 2ZM9 19H15V21H9Z"),
];

/// Resolve a curated icon by name (e.g. `"check"`), or `None` if unknown.
pub fn resolve_icon(name: &str) -> Option<IconDef> {
    ICONS
        .iter()
        .find(|(icon_name, _)| *icon_name == name)
        .map(|(_, path_data)| IconDef {
            path_data,
            view_box: VIEW_BOX,
        })
}

/// All available icon names, in registry order — for the agent and for the
/// `LUMD0703` "unknown icon" hint so a typo lists the real options.
pub fn icon_names() -> Vec<&'static str> {
    ICONS.iter().map(|(name, _)| *name).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_known_icons_and_rejects_unknown() {
        let check = resolve_icon("check").expect("check icon");
        assert!(check.path_data.starts_with('M'));
        assert_eq!(check.view_box, [24.0, 24.0]);
        assert!(resolve_icon("definitely-not-an-icon").is_none());
    }

    #[test]
    fn names_are_non_empty_and_unique() {
        let names = icon_names();
        assert!(names.len() >= 12);
        let mut sorted = names.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), names.len(), "icon names must be unique");
    }
}
