//! Brand kit → web theme compiler.
//!
//! Maps kit color roles onto a small closed set of web token names (plus the
//! kit's remaining colors preserved under sanitized names), and the kit's
//! perceptual type ramp onto a base-layer stylesheet of variant and button
//! defaults — so agent-authored classes carry only *deviations* from the
//! brand, never the brand itself. Emitted as a Tailwind v4 `@theme` block
//! (editor runtime + future static compile) and a plain base CSS layer.
//!
//! The same idea runs over *geometry*: the kit's measured corner radii,
//! elevations, hairlines and rhythm resolve onto a closed set of ten web
//! utilities (`rounded-button`, `shadow-brand`, `border-w-card`,
//! `py-section`, …) so a brand's real shape is expressible by name. That
//! channel is `WebTheme::geometry` — deliberately NOT `tokens`, which stays
//! colors-only because it doubles as the class lint's color vocabulary and
//! the inspector's swatch grid.

use crate::doc::WebThemeRef;
use lumen_core::{
    platform_default_brand_kit, BrandKit, ColorTokenValue, Diagnostic, NumberToken,
    NumberTokenValue, NumberUnit, Phase, TypographyTokenValue,
};
use std::collections::BTreeMap;

/// Semantic web token names, in emission order. These are the vocabulary the
/// class lint checks against and the skill teaches first.
const SEMANTIC_TOKENS: &[(&str, &[&str])] = &[
    ("primary", &["surface.brand", "palette.primary.600", "palette.primary.500"]),
    ("accent", &["surface.accent", "palette.primary.400"]),
    ("dark", &["text.primary", "palette.neutral.900"]),
    ("light", &["surface.page", "palette.neutral.50"]),
    ("card", &["surface.card", "surface.canvas"]),
    ("muted", &["text.secondary", "palette.neutral.500"]),
    ("border", &["border.default", "palette.neutral.200"]),
    ("inverse", &["text.inverse"]),
];

const ALIAS_DEPTH_CAP: usize = 8;

/// Which of the kit's number/shadow token groups a geometry chain reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum GeometryGroup {
    Radii,
    StrokeWidths,
    Spacing,
    Shadows,
}

/// The brand-geometry vocabulary: one row per web utility, in the order the
/// grammar teaches them. Each row is `(utility, css var name without `--`,
/// kit token group, resolution chain, platform fallback)`.
///
/// The chains exist because ingestion mints geometry unevenly: `shadow.card`
/// is never minted at all, shadows are minted ONLY when measured (a flat site
/// and the platform kit carry none), and `space.stack.*` is never measurable.
/// Every utility therefore always resolves to *something* — chain result or
/// the platform constant — so a class in the grammar can never silently
/// no-op. Resolution is provenance-BLIND: measured or derived, the value is
/// the value.
const GEOMETRY_UTILITIES: &[(&str, &str, GeometryGroup, &[&str], &str)] = &[
    (
        "rounded-button",
        "radius-button",
        GeometryGroup::Radii,
        &["radius.button", "radius.control", "radius.md"],
        "10px",
    ),
    (
        "rounded-card",
        "radius-card",
        GeometryGroup::Radii,
        &["radius.card", "radius.lg"],
        "16px",
    ),
    (
        "rounded-badge",
        "radius-badge",
        GeometryGroup::Radii,
        &["radius.badge", "radius.full"],
        "999px",
    ),
    (
        "shadow-brand",
        "shadow-brand",
        GeometryGroup::Shadows,
        &["shadow.brand", "shadow.md", "shadow.sm", "shadow.lg"],
        PLATFORM_SHADOW,
    ),
    (
        "shadow-card",
        "shadow-card",
        GeometryGroup::Shadows,
        &["shadow.card", "shadow.md", "shadow.sm"],
        PLATFORM_SHADOW,
    ),
    (
        "border-w-card",
        "border-width-card",
        GeometryGroup::StrokeWidths,
        &["stroke.width.card", "stroke.width.default", "stroke.width.thin"],
        "1px",
    ),
    (
        "border-w-divider",
        "border-width-divider",
        GeometryGroup::StrokeWidths,
        &["stroke.width.divider", "stroke.width.thin"],
        "1px",
    ),
    (
        "py-section",
        "spacing-section",
        GeometryGroup::Spacing,
        &["space.section"],
        "48px",
    ),
    (
        "gap-stack",
        "spacing-stack",
        GeometryGroup::Spacing,
        &["space.stack.default", "space.lg"],
        "16px",
    ),
    (
        "p-card",
        "spacing-card",
        GeometryGroup::Spacing,
        &["space.card.padding"],
        "24px",
    ),
];

/// The one elevation the platform owns. Shadows have no fallback anywhere in
/// the kit model (the platform kit carries zero), so without this constant
/// `shadow-brand`/`shadow-card` would resolve to nothing on every unmeasured
/// brand.
const PLATFORM_SHADOW: &str = "0 2px 8px 0 #00000014";

/// Geometry names outside a Tailwind v4 namespace need an explicit `@utility`
/// rule. `--radius-*`, `--shadow-*` and `--spacing-*` compile natively from
/// the `@theme` block; `border-w-*` has no namespace at all. Built here so no
/// consumer (Python export, the editor) ever hand-writes these rules.
const GEOMETRY_UTILITY_RULES: &[(&str, &str, &str)] = &[
    ("border-w-card", "border-width", "border-width-card"),
    ("border-w-divider", "border-width", "border-width-divider"),
];

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebTheme {
    /// Token name -> resolved CSS color. The lint's vocabulary.
    ///
    /// COLORS ONLY, always. This map is also the inspector's color swatch grid
    /// and the agent-prompt token vocabulary — geometry lives in `geometry`.
    pub tokens: BTreeMap<String, String>,
    /// CSS variable name (without `--`, e.g. `radius-button`) -> CSS value.
    /// Always carries every entry of `GEOMETRY_UTILITIES`.
    pub geometry: BTreeMap<String, String>,
    pub display_family: String,
    pub body_family: String,
    /// Tailwind v4 `@theme { … }` block (color + font + geometry variables),
    /// followed by the `@utility` rules for geometry names outside a Tailwind
    /// namespace.
    pub theme_block: String,
    /// The `@utility` rules alone (the tail of `theme_block`), so the static
    /// export compile can place them after its own `@theme` block.
    pub utility_css: String,
    /// Plain CSS base layer: body defaults, text-variant defaults, button
    /// variant styles. Agent classes override via utilities.
    pub base_css: String,
}

#[derive(Clone, Debug, Default)]
pub struct WebThemeOptions {
    /// Pre-built `@font-face` CSS (the API owns font-serving URLs).
    pub font_face_css: Option<String>,
    /// Pre-concatenated, ALREADY-SCOPED CSS for the cloned-section fragments
    /// this render references (clone-fidelity F1.3). The API owns fragment
    /// resolution — it reads each artifact from the registry, keeps the
    /// per-fragment blocks identifiable, and hands the whole sheet here.
    ///
    /// It rides the theme's base layer deliberately: that puts it in the head
    /// BEFORE any compiled utility sheet (and, in editor mode, inside
    /// `@layer base`), so a compiled Tailwind utility wins a tie. That is
    /// acceptable only because every fragment selector is scoped under
    /// `.lumen-frag-<hex>`; the API emits a diagnostic when a fragment class
    /// is also a live utility, which is the one case the scoping cannot save.
    pub fragment_css: Option<String>,
}

struct ResolvedType {
    family: String,
    size: f64,
    weight: u16,
    line_height: f64,
    letter_spacing: Option<f64>,
}

pub fn compile_web_theme(
    kit: Option<&BrandKit>,
    theme_ref: &WebThemeRef,
    options: &WebThemeOptions,
) -> (WebTheme, Vec<Diagnostic>) {
    let mut diagnostics = Vec::new();
    // An EXPLICIT kit that exhausts a geometry chain is worth reporting; the
    // platform-default path lands on platform values by definition, so it is
    // silent.
    let kit_is_explicit = kit.is_some();
    let fallback_kit;
    let kit = match kit {
        Some(kit) => kit,
        None => match platform_default_brand_kit() {
            Ok(default_kit) => {
                fallback_kit = default_kit;
                &fallback_kit
            }
            Err(err) => {
                // Unreachable in practice (the platform kit is a vetted
                // constant); fail loud rather than silently unthemed.
                diagnostics.push(Diagnostic::error(
                    Phase::Web,
                    "LUMW0300",
                    format!("platform default brand kit failed to load: {err}"),
                    None,
                ));
                return (WebTheme::default(), diagnostics);
            }
        },
    };

    let mut tokens: BTreeMap<String, String> = BTreeMap::new();
    for (web_name, kit_chain) in SEMANTIC_TOKENS {
        let resolved = kit_chain
            .iter()
            .find_map(|kit_name| resolve_color(kit, kit_name, 0));
        match resolved {
            Some(css) => {
                tokens.insert((*web_name).to_owned(), css);
            }
            None => {
                let fallback = semantic_fallback(*web_name, &tokens);
                diagnostics.push(
                    Diagnostic::advice(
                        Phase::Web,
                        "LUMW0301",
                        format!(
                            "kit has no color for web token `{web_name}` (looked for {}); using {fallback}",
                            kit_chain.join(", ")
                        ),
                        None,
                    ),
                );
                tokens.insert((*web_name).to_owned(), fallback);
            }
        }
    }

    // Preserve every other kit color under a sanitized name.
    for name in kit.tokens.colors.keys() {
        let web_name = sanitize_token_name(name);
        if web_name.is_empty() || tokens.contains_key(&web_name) {
            continue;
        }
        match resolve_color(kit, name, 0) {
            Some(css) => {
                tokens.insert(web_name, css);
            }
            None => diagnostics.push(Diagnostic::warning(
                Phase::Web,
                "LUMW0302",
                format!("kit color token `{name}` did not resolve to a concrete color; skipped"),
                None,
            )),
        }
    }

    // Per-document overrides win last. Values are constrained to a plain
    // CSS-color charset: token values are embedded into <style> payloads, so
    // anything richer is a markup-injection vector, not a color.
    for (name, value) in &theme_ref.overrides {
        if css_color_value_ok(value) {
            tokens.insert(sanitize_token_name(name), value.clone());
        } else {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Web,
                    "LUMW0304",
                    format!("theme override `{name}` is not a plain color value; ignored"),
                    None,
                )
                .with_hint("Overrides must be CSS colors like #14B8A6 or oklch(0.7 0.1 200)."),
            );
        }
    }

    // Typography ramp.
    let body = resolve_type_chain(kit, &["type.body"]).unwrap_or_else(|| {
        diagnostics.push(Diagnostic::advice(
            Phase::Web,
            "LUMW0303",
            "kit has no type.body token; using 18px system defaults",
            None,
        ));
        ResolvedType {
            family: String::new(),
            size: 18.0,
            weight: 400,
            line_height: 1.6,
            letter_spacing: None,
        }
    });
    let headline = resolve_type_chain(kit, &["type.headline", "type.display"]);
    let display = resolve_type_chain(kit, &["type.display", "type.headline"]);
    let title = resolve_type_chain(kit, &["type.title"]);
    let subtitle = resolve_type_chain(kit, &["type.subtitle"]);
    let cta = resolve_type_chain(kit, &["type.cta"]);

    let body_family = font_stack(&body.family);
    let display_family = font_stack(
        headline
            .as_ref()
            .map(|t| t.family.as_str())
            .filter(|family| !family.is_empty())
            .unwrap_or(&body.family),
    );

    let geometry = compile_geometry(kit, kit_is_explicit, &mut diagnostics);
    let utility_css = build_utility_css();

    let theme_block =
        build_theme_block(&tokens, &geometry, &display_family, &body_family, &utility_css);
    let base_css = build_base_css(
        &tokens,
        &display_family,
        &body_family,
        &body,
        display.as_ref(),
        headline.as_ref(),
        title.as_ref(),
        subtitle.as_ref(),
        cta.as_ref(),
        control_radius(kit),
        options,
    );

    (
        WebTheme {
            tokens,
            geometry,
            display_family,
            body_family,
            theme_block,
            utility_css,
            base_css,
        },
        diagnostics,
    )
}

/// Resolve every brand-geometry utility against the kit, falling back down its
/// chain and finally onto the platform constant. Always returns one entry per
/// `GEOMETRY_UTILITIES` row.
fn compile_geometry(
    kit: &BrandKit,
    kit_is_explicit: bool,
    diagnostics: &mut Vec<Diagnostic>,
) -> BTreeMap<String, String> {
    let mut geometry: BTreeMap<String, String> = BTreeMap::new();
    for (utility, var_name, group, chain, fallback) in GEOMETRY_UTILITIES {
        let resolved = chain
            .iter()
            .find_map(|token_name| resolve_geometry_value(kit, *group, token_name));
        let value = match resolved {
            Some(value) => value,
            None => {
                if kit_is_explicit {
                    diagnostics.push(Diagnostic::advice(
                        Phase::Web,
                        "LUMW0305",
                        format!(
                            "kit has no geometry for `{utility}` (looked for {}); using the \
                             platform default {fallback}",
                            chain.join(", ")
                        ),
                        None,
                    ));
                }
                (*fallback).to_owned()
            }
        };
        geometry.insert((*var_name).to_owned(), value);
    }
    geometry
}

/// One chain rung. `None` means the rung failed (absent, wrong unit,
/// unresolvable alias, or a value that fails the charset gate) — the caller
/// continues down the chain.
fn resolve_geometry_value(kit: &BrandKit, group: GeometryGroup, name: &str) -> Option<String> {
    let value = match group {
        GeometryGroup::Shadows => resolve_shadow(kit, name)?,
        GeometryGroup::Radii => format_px(resolve_number(&kit.tokens.radii, name, 0)?),
        GeometryGroup::StrokeWidths => {
            format_px(resolve_number(&kit.tokens.stroke_widths, name, 0)?)
        }
        GeometryGroup::Spacing => format_px(resolve_number(&kit.tokens.spacing, name, 0)?),
    };
    // Geometry values land verbatim inside <style> payloads exactly like
    // colors do — same charset gate, same reason (LUMW0304's posture): a kit
    // string must never be able to close the block or open a <script>.
    css_color_value_ok(&value).then_some(value)
}

/// A kit number token as a plain scalar. Aliases are followed within the same
/// token group; only `Px`/`Unitless` are geometry-usable (a `%`/`ratio`/`mm`
/// number is not a CSS length here).
fn resolve_number(
    group: &BTreeMap<String, NumberToken>,
    name: &str,
    depth: usize,
) -> Option<f64> {
    if depth > ALIAS_DEPTH_CAP {
        return None;
    }
    match &group.get(name)?.value.default {
        NumberTokenValue::Number { value, unit } => {
            matches!(unit, NumberUnit::Px | NumberUnit::Unitless).then_some(*value)
        }
        NumberTokenValue::Alias { token } => resolve_number(group, token, depth + 1),
    }
}

/// A kit shadow token as a CSS `box-shadow` value. `ShadowValue` has no alias
/// form, so there is no chain to follow inside a rung.
fn resolve_shadow(kit: &BrandKit, name: &str) -> Option<String> {
    let shadow = &kit.tokens.shadows.get(name)?.value.default;
    let color = shadow.color.trim();
    if !css_color_value_ok(color) {
        return None;
    }
    Some(format!(
        "{} {} {} {} {color}",
        format_px(shadow.x),
        format_px(shadow.y),
        format_px(shadow.blur),
        format_px(shadow.spread),
    ))
}

/// `4.0 -> "4px"`, `15.93 -> "15.93px"`, `0.0 -> "0"` — a whole number never
/// carries a trailing `.0` (byte-determinism of the theme block is a test),
/// and a zero length drops its unit the way CSS and a designer both write it
/// (mirrors `lumen_agent.brand_brief::_geometry_value`, so the elevation the
/// author prompt quotes as a brand fact is byte-identical to the CSS it gets).
fn format_px(value: f64) -> String {
    if value == 0.0 {
        "0".to_owned()
    } else if value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{}px", value as i64)
    } else {
        format!("{value}px")
    }
}

fn build_utility_css() -> String {
    let mut out = String::new();
    for (utility, property, var_name) in GEOMETRY_UTILITY_RULES {
        out.push_str(&format!(
            "@utility {utility} {{ {property}: var(--{var_name}); }}\n"
        ));
    }
    out
}

fn semantic_fallback(web_name: &str, resolved: &BTreeMap<String, String>) -> String {
    match web_name {
        "primary" => "#0F172A".to_owned(),
        "accent" => resolved
            .get("primary")
            .cloned()
            .unwrap_or_else(|| "#0F172A".to_owned()),
        "dark" => "#111827".to_owned(),
        "light" => "#FFFFFF".to_owned(),
        "card" => resolved
            .get("light")
            .cloned()
            .unwrap_or_else(|| "#FFFFFF".to_owned()),
        "muted" => "#6B7280".to_owned(),
        "border" => "#E5E7EB".to_owned(),
        "inverse" => resolved
            .get("light")
            .cloned()
            .unwrap_or_else(|| "#FFFFFF".to_owned()),
        _ => "#111827".to_owned(),
    }
}

/// Token values land verbatim inside <style> payloads; restrict them to a
/// plain color-value charset so no color path can smuggle markup or extra
/// declarations (`;`, `}`, `<` are all excluded).
fn css_color_value_ok(value: &str) -> bool {
    let trimmed = value.trim();
    !trimmed.is_empty()
        && trimmed.len() <= 128
        && trimmed.chars().all(|ch| {
            ch.is_ascii_alphanumeric()
                || matches!(ch, '#' | '%' | '.' | ',' | ' ' | '(' | ')' | '-' | '/' | '+')
        })
}

fn resolve_color(kit: &BrandKit, name: &str, depth: usize) -> Option<String> {
    if depth > ALIAS_DEPTH_CAP {
        return None;
    }
    let token = kit.tokens.colors.get(name)?;
    match &token.value.default {
        ColorTokenValue::Hex { value } => Some(value.clone()).filter(|v| css_color_value_ok(v)),
        ColorTokenValue::Oklch { l, c, h, alpha } => Some(if (*alpha - 1.0).abs() < f64::EPSILON {
            format!("oklch({l} {c} {h})")
        } else {
            format!("oklch({l} {c} {h} / {alpha})")
        }),
        ColorTokenValue::Alias { token } => resolve_color(kit, token, depth + 1),
    }
}

fn resolve_type_chain(kit: &BrandKit, chain: &[&str]) -> Option<ResolvedType> {
    chain.iter().find_map(|name| resolve_type(kit, name, 0))
}

fn resolve_type(kit: &BrandKit, name: &str, depth: usize) -> Option<ResolvedType> {
    if depth > ALIAS_DEPTH_CAP {
        return None;
    }
    let token = kit.tokens.typography.get(name)?;
    match &token.value.default {
        TypographyTokenValue::Style {
            font_family,
            font_size,
            font_weight,
            line_height,
            letter_spacing,
            ..
        } => Some(ResolvedType {
            family: font_family.clone(),
            size: *font_size,
            weight: *font_weight,
            line_height: line_height.unwrap_or(1.3),
            letter_spacing: *letter_spacing,
        }),
        TypographyTokenValue::Alias { token } => resolve_type(kit, token, depth + 1),
    }
}

fn control_radius(kit: &BrandKit) -> f64 {
    for name in ["radius.control", "radius.button", "control", "radius.md", "md"] {
        if let Some(token) = kit.tokens.radii.get(name) {
            if let NumberTokenValue::Number { value, unit } = &token.value.default {
                if matches!(unit, NumberUnit::Px | NumberUnit::Unitless) {
                    return *value;
                }
            }
        }
    }
    10.0
}

fn sanitize_token_name(name: &str) -> String {
    let mut out = String::with_capacity(name.len());
    for ch in name.chars() {
        match ch {
            'a'..='z' | '0'..='9' | '-' => out.push(ch),
            'A'..='Z' => out.push(ch.to_ascii_lowercase()),
            '.' | '_' | ' ' => out.push('-'),
            _ => {}
        }
    }
    out.trim_matches('-').to_owned()
}

fn font_stack(family: &str) -> String {
    let trimmed = family.trim();
    if trimmed.is_empty() {
        return "ui-sans-serif, system-ui, sans-serif".to_owned();
    }
    let quoted = if trimmed.contains(' ') && !trimmed.starts_with('"') {
        format!("\"{trimmed}\"")
    } else {
        trimmed.to_owned()
    };
    format!("{quoted}, ui-sans-serif, system-ui, sans-serif")
}

fn build_theme_block(
    tokens: &BTreeMap<String, String>,
    geometry: &BTreeMap<String, String>,
    display_family: &str,
    body_family: &str,
    utility_css: &str,
) -> String {
    let mut out = String::from("@theme {\n");
    for (name, value) in tokens {
        out.push_str(&format!("  --color-{name}: {value};\n"));
    }
    out.push_str(&format!("  --font-display: {display_family};\n"));
    out.push_str(&format!("  --font-body: {body_family};\n"));
    for (name, value) in geometry {
        out.push_str(&format!("  --{name}: {value};\n"));
    }
    out.push_str("}\n");
    // `@utility` is a top-level at-rule, so it rides AFTER the block. The
    // browser runtime and the static compiler both accept `@theme` +
    // `@utility` in one stylesheet.
    out.push_str(utility_css);
    out
}

/// Perceived luminance from a hex color; `None` for non-hex (oklch etc.).
fn hex_luminance(css: &str) -> Option<f64> {
    let hex = css.trim().strip_prefix('#')?;
    if hex.len() < 6 {
        return None;
    }
    let r = u8::from_str_radix(&hex[0..2], 16).ok()? as f64;
    let g = u8::from_str_radix(&hex[2..4], 16).ok()? as f64;
    let b = u8::from_str_radix(&hex[4..6], 16).ok()? as f64;
    Some((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)
}

fn contrast_for(css: &str, tokens: &BTreeMap<String, String>) -> String {
    let dark = tokens.get("dark").cloned().unwrap_or_else(|| "#111827".to_owned());
    let light = tokens.get("light").cloned().unwrap_or_else(|| "#FFFFFF".to_owned());
    match hex_luminance(css) {
        Some(luminance) if luminance > 0.6 => dark,
        Some(_) => light,
        // Non-hex color spaces: assume a saturated brand color, pick light.
        None => light,
    }
}

fn fluid_size(size: f64) -> String {
    // Hits the authored size at a 1440px viewport, floors at 55% for phones.
    let min = (size * 0.55).round();
    let preferred = size / 14.4;
    format!("clamp({min}px, {preferred:.2}vw, {size}px)")
}

// Platform defaults apply to native nodes and the outer fragment container only.
// Captured descendants retain their source rules and browser defaults. :where()
// keeps the exclusion at zero specificity; unlike @scope it adds no proximity
// priority and does not change native equal-specificity/layer conflicts.
const NATIVE_SUBJECT: &str = ":not(:where([data-lumen-fragment=\"true\"] *))";

fn type_rule(selector: &str, family: &str, resolved: &ResolvedType, fluid: bool) -> String {
    let size = if fluid {
        fluid_size(resolved.size)
    } else {
        format!("{}px", resolved.size)
    };
    let letter_spacing = resolved
        .letter_spacing
        .map(|value| format!(" letter-spacing: {value}em;"))
        .unwrap_or_default();
    format!(
        "{selector}{NATIVE_SUBJECT} {{ font-family: {family}; font-size: {size}; font-weight: {}; line-height: {};{letter_spacing} }}\n",
        resolved.weight, resolved.line_height
    )
}

#[allow(clippy::too_many_arguments)]
fn build_base_css(
    tokens: &BTreeMap<String, String>,
    display_family: &str,
    body_family: &str,
    body: &ResolvedType,
    display: Option<&ResolvedType>,
    headline: Option<&ResolvedType>,
    title: Option<&ResolvedType>,
    subtitle: Option<&ResolvedType>,
    cta: Option<&ResolvedType>,
    radius: f64,
    options: &WebThemeOptions,
) -> String {
    let mut css = String::new();
    if let Some(font_face_css) = &options.font_face_css {
        css.push_str(font_face_css);
        css.push('\n');
    }
    css.push_str(&format!(
        "*{NATIVE_SUBJECT}, *{NATIVE_SUBJECT}::before, *{NATIVE_SUBJECT}::after {{ box-sizing: border-box; }}\n\
         body {{ margin: 0; font-family: {body_family}; color: var(--color-dark); \
         background: var(--color-light); font-size: {}px; line-height: {}; \
         -webkit-font-smoothing: antialiased; }}\n\
         img{NATIVE_SUBJECT} {{ max-width: 100%; display: block; }}\n\
         [data-tv]{NATIVE_SUBJECT} {{ margin: 0; }}\n\
         [data-tv=\"body\"] > :where(p, ul, ol){NATIVE_SUBJECT}, \
         [data-tv=\"small\"] > :where(p, ul, ol){NATIVE_SUBJECT} {{ margin: 0; }}\n\
         [data-tv=\"body\"] > :where(p, ul, ol) + :where(p, ul, ol){NATIVE_SUBJECT}, \
         [data-tv=\"small\"] > :where(p, ul, ol) + :where(p, ul, ol){NATIVE_SUBJECT} {{ margin-top: 0.75em; }}\n\
         [data-tv=\"body\"] :where(ul, ol){NATIVE_SUBJECT}, \
         [data-tv=\"small\"] :where(ul, ol){NATIVE_SUBJECT} {{ padding-left: 1.5em; }}\n\
         [data-tv=\"body\"] :where(ul){NATIVE_SUBJECT}, \
         [data-tv=\"small\"] :where(ul){NATIVE_SUBJECT} {{ list-style-type: disc; }}\n\
         [data-tv=\"body\"] :where(ol){NATIVE_SUBJECT}, \
         [data-tv=\"small\"] :where(ol){NATIVE_SUBJECT} {{ list-style-type: decimal; }}\n\
         [data-tv=\"body\"] :where(li) + li{NATIVE_SUBJECT}, \
         [data-tv=\"small\"] :where(li) + li{NATIVE_SUBJECT} {{ margin-top: 0.25em; }}\n",
        body.size, body.line_height
    ));

    // Text-variant ramp. Derived steps keep the ramp complete when the kit
    // lacks a role; every value can still be overridden per node via classes.
    let display_type = display.cloned_or(ResolvedType {
        family: String::new(),
        size: (body.size * 4.0).min(76.0),
        weight: 800,
        line_height: 1.02,
        letter_spacing: Some(-0.02),
    });
    let h1 = headline.cloned_or(ResolvedType {
        family: String::new(),
        size: (body.size * 3.1).min(60.0),
        weight: 800,
        line_height: 1.06,
        letter_spacing: Some(-0.01),
    });
    let h2 = title.cloned_or(ResolvedType {
        family: String::new(),
        size: (body.size * 2.0).min(40.0),
        weight: 750,
        line_height: 1.12,
        letter_spacing: Some(-0.005),
    });
    let h3 = subtitle.cloned_or(ResolvedType {
        family: String::new(),
        size: (body.size * 1.33).min(26.0),
        weight: 650,
        line_height: 1.24,
        letter_spacing: None,
    });
    let h4 = ResolvedType {
        family: String::new(),
        size: (h3.size * 0.85).max(body.size),
        weight: 650,
        line_height: 1.3,
        letter_spacing: None,
    };
    css.push_str(&type_rule("[data-tv=\"display\"]", display_family, &display_type, true));
    css.push_str(&type_rule("[data-tv=\"h1\"]", display_family, &h1, true));
    css.push_str(&type_rule("[data-tv=\"h2\"]", display_family, &h2, true));
    css.push_str(&type_rule("[data-tv=\"h3\"]", display_family, &h3, false));
    css.push_str(&type_rule("[data-tv=\"h4\"]", display_family, &h4, false));
    css.push_str(&format!(
        "[data-tv=\"body\"]{NATIVE_SUBJECT} {{ font-size: {}px; line-height: {}; }}\n\
         [data-tv=\"small\"]{NATIVE_SUBJECT} {{ font-size: {}px; line-height: 1.5; }}\n\
         [data-tv=\"overline\"]{NATIVE_SUBJECT} {{ font-size: {}px; font-weight: 600; text-transform: uppercase; \
         letter-spacing: 0.08em; }}\n",
        body.size,
        body.line_height,
        (body.size * 0.875).round(),
        (body.size * 0.72).round(),
    ));

    // Button variants.
    let primary = tokens
        .get("primary")
        .cloned()
        .unwrap_or_else(|| "#0F172A".to_owned());
    let primary_contrast = contrast_for(&primary, tokens);
    let dark = tokens.get("dark").cloned().unwrap_or_else(|| "#111827".to_owned());
    let dark_contrast = contrast_for(&dark, tokens);
    let cta_size = cta.map(|t| t.size).unwrap_or_else(|| body.size.min(17.0));
    let cta_weight = cta.map(|t| t.weight).unwrap_or(600);
    css.push_str(&format!(
        "[data-btn]{NATIVE_SUBJECT} {{ display: inline-flex; align-items: center; justify-content: center; \
         gap: 0.5rem; font-family: {body_family}; font-size: {cta_size}px; font-weight: {cta_weight}; \
         line-height: 1; text-decoration: none; border-radius: {radius}px; \
         padding: 0.75rem 1.5rem; border: 1px solid transparent; cursor: pointer; \
         transition: filter 0.15s ease, background-color 0.15s ease; }}\n\
         [data-btn]{NATIVE_SUBJECT}:hover {{ filter: brightness(1.06); }}\n\
         [data-btn=\"primary\"]{NATIVE_SUBJECT} {{ background: var(--color-primary); color: {primary_contrast}; }}\n\
         [data-btn=\"secondary\"]{NATIVE_SUBJECT} {{ background: var(--color-dark); color: {dark_contrast}; }}\n\
         [data-btn=\"outline\"]{NATIVE_SUBJECT} {{ border-color: var(--color-dark); color: var(--color-dark); background: transparent; }}\n\
         [data-btn=\"ghost\"]{NATIVE_SUBJECT} {{ color: var(--color-dark); background: transparent; }}\n\
         [data-btn=\"ghost\"]{NATIVE_SUBJECT}:hover {{ background: color-mix(in srgb, var(--color-dark) 8%, transparent); filter: none; }}\n\
         [data-btn=\"link\"]{NATIVE_SUBJECT} {{ padding: 0; border: none; background: none; border-radius: 0; \
         color: var(--color-primary); text-decoration: underline; text-underline-offset: 3px; }}\n"
    ));
    css.push_str(
        "@media (prefers-reduced-motion: reduce) {\n  *, *::before, *::after { \
         animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; \
         transition-duration: 0.01ms !important; scroll-behavior: auto !important; }\n}\n",
    );
    // Keep source CSS unchanged and last. Native defaults above exclude clone
    // interiors; missing source declarations must retain browser defaults too.
    // Source CSS stays in the base layer, below deliberate compiled utilities.
    if let Some(fragment_css) = &options.fragment_css {
        css.push_str("/* lumen-fragment css */\n");
        css.push_str(fragment_css);
        css.push('\n');
    }
    css
}

trait ClonedOr {
    fn cloned_or(&self, fallback: ResolvedType) -> ResolvedType;
}

impl ClonedOr for Option<&ResolvedType> {
    fn cloned_or(&self, fallback: ResolvedType) -> ResolvedType {
        match self {
            Some(resolved) => ResolvedType {
                family: resolved.family.clone(),
                size: resolved.size,
                weight: resolved.weight,
                line_height: resolved.line_height,
                letter_spacing: resolved.letter_spacing,
            },
            None => fallback,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::WebThemeRef;

    fn compile_platform() -> (WebTheme, Vec<Diagnostic>) {
        compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default())
    }

    #[test]
    fn platform_kit_compiles_semantic_tokens() {
        let (theme, _diagnostics) = compile_platform();
        for name in ["primary", "accent", "dark", "light", "card", "muted", "border", "inverse"] {
            assert!(theme.tokens.contains_key(name), "missing token {name}");
        }
        assert!(theme.theme_block.contains("--color-primary:"));
        assert!(theme.theme_block.contains("--font-display:"));
    }

    #[test]
    fn kit_extras_are_preserved_with_sanitized_names() {
        let (theme, _) = compile_platform();
        assert!(theme.tokens.keys().any(|name| name.starts_with("palette-primary-")));
    }

    #[test]
    fn base_css_has_variant_ramp_and_buttons() {
        let (theme, _) = compile_platform();
        assert!(theme.base_css.contains("[data-tv=\"display\"]"));
        assert!(theme.base_css.contains("[data-tv=\"overline\"]"));
        assert!(theme.base_css.contains("list-style-type: disc"));
        assert!(theme.base_css.contains("list-style-type: decimal"));
        assert!(theme.base_css.contains("[data-btn=\"primary\"]"));
        assert!(theme.base_css.contains("prefers-reduced-motion"));
    }

    #[test]
    fn overrides_win() {
        let mut theme_ref = WebThemeRef::default();
        theme_ref
            .overrides
            .insert("primary".to_owned(), "#123456".to_owned());
        let (theme, _) =
            compile_web_theme(None, &theme_ref, &WebThemeOptions::default());
        assert_eq!(theme.tokens.get("primary").unwrap(), "#123456");
    }

    #[test]
    fn non_color_override_values_are_ignored_with_warning() {
        let mut theme_ref = WebThemeRef::default();
        theme_ref.overrides.insert(
            "primary".to_owned(),
            "red;}</style><script>alert(1)</script>".to_owned(),
        );
        let (theme, diagnostics) =
            compile_web_theme(None, &theme_ref, &WebThemeOptions::default());
        assert_ne!(
            theme.tokens.get("primary").unwrap(),
            "red;}</style><script>alert(1)</script>"
        );
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0304"));
        assert!(!theme.theme_block.contains("<script"));
    }

    #[test]
    fn deterministic_output() {
        let (a, _) = compile_platform();
        let (b, _) = compile_platform();
        assert_eq!(a.theme_block, b.theme_block);
        assert_eq!(a.base_css, b.base_css);
    }

    // ── brand geometry ──────────────────────────────────────────────────────

    /// A kit carrying only the token groups a test names. Everything else is
    /// empty, which is the honest shape of a thin/flat brand.
    fn kit_with(tokens: serde_json::Value) -> BrandKit {
        serde_json::from_value(serde_json::json!({
            "id": "kit_geometry_fixture",
            "version": 1,
            "name": "Geometry fixture",
            "description": null,
            "provenance": null,
            "tokens": tokens,
        }))
        .expect("geometry fixture kit")
    }

    fn number(value: f64) -> serde_json::Value {
        serde_json::json!({
            "value": {"default": {"kind": "number", "value": value, "unit": "px"}, "modes": {}},
        })
    }

    fn number_with_unit(value: f64, unit: &str) -> serde_json::Value {
        serde_json::json!({
            "value": {"default": {"kind": "number", "value": value, "unit": unit}, "modes": {}},
        })
    }

    fn number_alias(token: &str) -> serde_json::Value {
        serde_json::json!({
            "value": {"default": {"kind": "alias", "token": token}, "modes": {}},
        })
    }

    fn shadow(x: f64, y: f64, blur: f64, spread: f64, color: &str) -> serde_json::Value {
        serde_json::json!({
            "value": {
                "default": {"x": x, "y": y, "blur": blur, "spread": spread, "color": color},
                "modes": {},
            },
        })
    }

    /// The measured/derived MIX ingestion really emits, ported verbatim from
    /// `apps/agent_runtime/tests/test_brand_brief_consumption.py::GEOMETRY`
    /// (Stripe v4 shapes). Provenance is deliberately absent — geometry
    /// resolution is provenance-blind, so measured and derived look the same
    /// from here.
    fn stripe_mixed_kit() -> BrandKit {
        kit_with(serde_json::json!({
            "radii": {
                "radius.button": number(4.0),
                "radius.card": number(6.0),
                "radius.lg": number(12.0),
            },
            "stroke_widths": {
                "stroke.width.focus": number(3.0),
                "stroke.width.firm": number(2.0),
            },
            "spacing": {
                "space.section": number(96.0),
                "space.xl": number(24.0),
            },
            "shadows": {
                "shadow.brand": shadow(0.0, 15.93, 31.86, -8.0, "#32325D1F"),
            },
        }))
    }

    fn compile_kit(kit: &BrandKit) -> (WebTheme, Vec<Diagnostic>) {
        compile_web_theme(Some(kit), &WebThemeRef::default(), &WebThemeOptions::default())
    }

    fn geometry_advice(diagnostics: &[Diagnostic]) -> Vec<&Diagnostic> {
        diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "LUMW0305")
            .collect()
    }

    #[test]
    fn measured_geometry_reaches_the_theme_vars() {
        let (theme, _) = compile_kit(&stripe_mixed_kit());
        assert_eq!(theme.geometry.get("radius-button").unwrap(), "4px");
        assert_eq!(theme.geometry.get("radius-card").unwrap(), "6px");
        assert_eq!(theme.geometry.get("spacing-section").unwrap(), "96px");
        assert_eq!(
            theme.geometry.get("shadow-brand").unwrap(),
            "0 15.93px 31.86px -8px #32325D1F"
        );
    }

    #[test]
    fn every_utility_always_has_a_value() {
        for kit in [stripe_mixed_kit(), kit_with(serde_json::json!({}))] {
            let (theme, _) = compile_kit(&kit);
            for (utility, var_name, _, _, _) in GEOMETRY_UTILITIES {
                let value = theme
                    .geometry
                    .get(*var_name)
                    .unwrap_or_else(|| panic!("`{utility}` has no `--{var_name}`"));
                assert!(!value.is_empty(), "`{utility}` resolved to an empty value");
            }
        }
    }

    #[test]
    fn a_chain_rung_resolves_without_advice() {
        // No `radius.badge` and no `shadow.card` in the Stripe mix: the badge
        // has no chain rung left (constant) but `rounded-card` falls to
        // `radius.lg` and `shadow-card` falls to nothing... so assert the two
        // that DO have a live rung, and that neither reports.
        let kit = kit_with(serde_json::json!({
            "radii": {"radius.lg": number(12.0), "radius.full": number(9999.0)},
            "stroke_widths": {"stroke.width.thin": number(1.0)},
            "spacing": {"space.section": number(96.0), "space.lg": number(20.0)},
            "shadows": {"shadow.md": shadow(0.0, 15.93, 31.86, -8.0, "#32325D1F")},
        }));
        let (theme, diagnostics) = compile_kit(&kit);
        assert_eq!(theme.geometry.get("radius-card").unwrap(), "12px");
        assert_eq!(theme.geometry.get("radius-badge").unwrap(), "9999px");
        assert_eq!(theme.geometry.get("spacing-stack").unwrap(), "20px");
        assert_eq!(theme.geometry.get("border-width-card").unwrap(), "1px");
        // `shadow.card` is never minted; the chain's `shadow.md` rung carries it.
        assert_eq!(
            theme.geometry.get("shadow-card").unwrap(),
            "0 15.93px 31.86px -8px #32325D1F"
        );
        for utility in ["rounded-card", "rounded-badge", "gap-stack", "shadow-card"] {
            assert!(
                !geometry_advice(&diagnostics)
                    .iter()
                    .any(|diagnostic| diagnostic.message.contains(utility)),
                "a resolved chain must not report: {diagnostics:?}"
            );
        }
    }

    #[test]
    fn an_exhausted_chain_falls_back_with_advice() {
        // Zero shadows anywhere (the flat-brand and platform-kit shape) and no
        // `space.section`.
        let kit = kit_with(serde_json::json!({
            "radii": {"radius.button": number(4.0)},
        }));
        let (theme, diagnostics) = compile_kit(&kit);
        assert_eq!(theme.geometry.get("shadow-brand").unwrap(), PLATFORM_SHADOW);
        assert_eq!(theme.geometry.get("shadow-card").unwrap(), PLATFORM_SHADOW);
        assert_eq!(theme.geometry.get("spacing-section").unwrap(), "48px");

        let advice = geometry_advice(&diagnostics);
        for utility in ["shadow-brand", "shadow-card", "py-section"] {
            let hit = advice
                .iter()
                .find(|diagnostic| diagnostic.message.contains(utility))
                .unwrap_or_else(|| panic!("no LUMW0305 for `{utility}`: {diagnostics:?}"));
            assert_eq!(hit.severity, lumen_core::DiagnosticSeverity::Advice);
        }
        // The one utility the kit DOES answer never reports.
        assert!(!advice
            .iter()
            .any(|diagnostic| diagnostic.message.contains("rounded-button")));
        // Advice only — this task adds no error/warning anywhere.
        assert!(!diagnostics.iter().any(|diagnostic| diagnostic.code == "LUMW0305"
            && diagnostic.severity != lumen_core::DiagnosticSeverity::Advice));
    }

    #[test]
    fn the_advice_names_the_primary_token_and_the_fallback() {
        let (_, diagnostics) = compile_kit(&kit_with(serde_json::json!({})));
        let advice = geometry_advice(&diagnostics);
        let section = advice
            .iter()
            .find(|diagnostic| diagnostic.message.contains("py-section"))
            .expect("py-section advice");
        assert!(section.message.contains("space.section"), "{section:?}");
        assert!(section.message.contains("48px"), "{section:?}");
    }

    #[test]
    fn the_platform_path_is_complete_and_silent() {
        let (theme, diagnostics) = compile_platform();
        for (utility, var_name, _, _, _) in GEOMETRY_UTILITIES {
            assert!(
                theme.geometry.contains_key(*var_name),
                "platform theme is missing `{utility}` (`--{var_name}`)"
            );
        }
        // The platform kit answers eight of the ten from its own tokens; the
        // two shadows land on the constant. None of that is worth reporting.
        assert!(
            geometry_advice(&diagnostics).is_empty(),
            "the platform path must be silent: {diagnostics:?}"
        );
        assert_eq!(theme.geometry.get("radius-button").unwrap(), "10px");
        assert_eq!(theme.geometry.get("radius-card").unwrap(), "16px");
        assert_eq!(theme.geometry.get("radius-badge").unwrap(), "999px");
        assert_eq!(theme.geometry.get("border-width-card").unwrap(), "1px");
        assert_eq!(theme.geometry.get("border-width-divider").unwrap(), "1px");
        assert_eq!(theme.geometry.get("spacing-section").unwrap(), "48px");
        assert_eq!(theme.geometry.get("spacing-stack").unwrap(), "16px");
        assert_eq!(theme.geometry.get("spacing-card").unwrap(), "24px");
        assert_eq!(theme.geometry.get("shadow-brand").unwrap(), PLATFORM_SHADOW);
        assert_eq!(theme.geometry.get("shadow-card").unwrap(), PLATFORM_SHADOW);
    }

    #[test]
    fn geometry_never_enters_the_color_vocabulary() {
        for kit in [stripe_mixed_kit(), kit_with(serde_json::json!({}))] {
            let (theme, _) = compile_kit(&kit);
            for (_, var_name, _, _, _) in GEOMETRY_UTILITIES {
                assert!(
                    !theme.tokens.contains_key(*var_name),
                    "`{var_name}` leaked into the color token map"
                );
            }
            for name in theme.tokens.keys() {
                assert!(
                    !name.starts_with("radius-")
                        && !name.starts_with("shadow-")
                        && !name.starts_with("spacing-")
                        && !name.starts_with("border-width-"),
                    "geometry-shaped name `{name}` in the color token map"
                );
            }
        }
    }

    #[test]
    fn the_theme_block_carries_geometry_and_utility_rules() {
        let (theme, _) = compile_platform();
        assert!(theme.theme_block.contains("--radius-button:"));
        assert!(theme.theme_block.contains("--shadow-brand:"));
        assert!(theme.theme_block.contains("--spacing-section:"));
        assert!(theme.theme_block.contains("--border-width-card:"));
        assert!(theme
            .theme_block
            .contains("@utility border-w-card { border-width: var(--border-width-card); }"));
        assert!(theme
            .theme_block
            .contains("@utility border-w-divider { border-width: var(--border-width-divider); }"));
        assert_eq!(theme.utility_css, build_utility_css());
        // The `@utility` rules ride AFTER the `@theme` block's closing brace.
        let brace = theme.theme_block.find("}\n").expect("closing brace");
        assert!(theme.theme_block.find("@utility").unwrap() > brace);
    }

    #[test]
    fn a_non_px_unit_or_dead_alias_fails_its_rung() {
        let kit = kit_with(serde_json::json!({
            "radii": {
                "radius.button": number_with_unit(0.5, "ratio"),
                "radius.control": number_alias("radius.nowhere"),
                "radius.md": number(7.0),
            },
        }));
        let (theme, _) = compile_kit(&kit);
        assert_eq!(theme.geometry.get("radius-button").unwrap(), "7px");
    }

    #[test]
    fn an_alias_chain_resolves_within_its_group() {
        let kit = kit_with(serde_json::json!({
            "radii": {
                "radius.button": number_alias("radius.hop"),
                "radius.hop": number_alias("radius.md"),
                "radius.md": number(3.0),
            },
        }));
        let (theme, _) = compile_kit(&kit);
        assert_eq!(theme.geometry.get("radius-button").unwrap(), "3px");
    }

    #[test]
    fn a_cyclic_alias_cannot_hang_the_compile() {
        let kit = kit_with(serde_json::json!({
            "radii": {
                "radius.button": number_alias("radius.control"),
                "radius.control": number_alias("radius.button"),
            },
        }));
        let (theme, _) = compile_kit(&kit);
        assert_eq!(theme.geometry.get("radius-button").unwrap(), "10px");
    }

    #[test]
    fn a_hostile_shadow_color_never_reaches_the_style_payload() {
        let kit = kit_with(serde_json::json!({
            "shadows": {
                "shadow.brand": shadow(
                    0.0, 2.0, 8.0, 0.0, "red;}</style><script>alert(1)</script>"
                ),
                "shadow.md": shadow(0.0, 3.0, 9.0, 0.0, "#00000022"),
            },
        }));
        let (theme, _) = compile_kit(&kit);
        // The poisoned rung fails; the chain's next rung carries the value.
        assert_eq!(
            theme.geometry.get("shadow-brand").unwrap(),
            "0 3px 9px 0 #00000022"
        );
        assert!(!theme.theme_block.contains("<script"));
        assert!(!theme.theme_block.contains("</style>"));
    }

    #[test]
    fn geometry_emission_is_deterministic() {
        let kit = stripe_mixed_kit();
        let (a, _) = compile_kit(&kit);
        let (b, _) = compile_kit(&kit);
        assert_eq!(a.theme_block, b.theme_block);
        assert_eq!(a.geometry, b.geometry);
    }

    #[test]
    fn every_geometry_utility_lints_clean_against_the_platform_theme() {
        let (theme, _) = compile_platform();
        for (utility, _, _, _, _) in GEOMETRY_UTILITIES {
            let diagnostics = crate::classes::lint_classes(
                utility,
                None,
                &crate::classes::ClassLintContext {
                    color_tokens: &theme.tokens,
                    // Briefed: a brand utility must stay clean on exactly the
                    // kit whose brief makes raw geometry advisable (LUMW0306).
                    briefed: true,
                },
            );
            assert!(
                diagnostics.is_empty(),
                "`{utility}` does not lint clean: {diagnostics:?}"
            );
        }
    }
}
