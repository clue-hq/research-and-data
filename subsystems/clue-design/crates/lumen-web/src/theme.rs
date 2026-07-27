//! Brand kit → web theme compiler.
//!
//! Maps kit color roles onto a small closed set of web token names (plus the
//! kit's remaining colors preserved under sanitized names), and the kit's
//! perceptual type ramp onto a base-layer stylesheet of variant and button
//! defaults — so agent-authored classes carry only *deviations* from the
//! brand, never the brand itself. Emitted as a Tailwind v4 `@theme` block
//! (editor runtime + future static compile) and a plain base CSS layer.

use crate::doc::WebThemeRef;
use lumen_core::{
    platform_default_brand_kit, BrandKit, ColorTokenValue, Diagnostic, NumberTokenValue,
    NumberUnit, Phase, TypographyTokenValue,
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

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebTheme {
    /// Token name -> resolved CSS color. The lint's vocabulary.
    pub tokens: BTreeMap<String, String>,
    pub display_family: String,
    pub body_family: String,
    /// Tailwind v4 `@theme { … }` block (color + font variables).
    pub theme_block: String,
    /// Plain CSS base layer: body defaults, text-variant defaults, button
    /// variant styles. Agent classes override via utilities.
    pub base_css: String,
}

#[derive(Clone, Debug, Default)]
pub struct WebThemeOptions {
    /// Pre-built `@font-face` CSS (the API owns font-serving URLs).
    pub font_face_css: Option<String>,
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

    // Per-document overrides win last.
    for (name, value) in &theme_ref.overrides {
        tokens.insert(sanitize_token_name(name), value.clone());
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

    let theme_block = build_theme_block(&tokens, &display_family, &body_family);
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
            display_family,
            body_family,
            theme_block,
            base_css,
        },
        diagnostics,
    )
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

fn resolve_color(kit: &BrandKit, name: &str, depth: usize) -> Option<String> {
    if depth > ALIAS_DEPTH_CAP {
        return None;
    }
    let token = kit.tokens.colors.get(name)?;
    match &token.value.default {
        ColorTokenValue::Hex { value } => Some(value.clone()),
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
    display_family: &str,
    body_family: &str,
) -> String {
    let mut out = String::from("@theme {\n");
    for (name, value) in tokens {
        out.push_str(&format!("  --color-{name}: {value};\n"));
    }
    out.push_str(&format!("  --font-display: {display_family};\n"));
    out.push_str(&format!("  --font-body: {body_family};\n"));
    out.push_str("}\n");
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
        "{selector} {{ font-family: {family}; font-size: {size}; font-weight: {}; line-height: {};{letter_spacing} }}\n",
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
        "*, *::before, *::after {{ box-sizing: border-box; }}\n\
         body {{ margin: 0; font-family: {body_family}; color: var(--color-dark); \
         background: var(--color-light); font-size: {}px; line-height: {}; \
         -webkit-font-smoothing: antialiased; }}\n\
         img {{ max-width: 100%; display: block; }}\n\
         [data-tv] {{ margin: 0; }}\n",
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
        "[data-tv=\"body\"] {{ font-size: {}px; line-height: {}; }}\n\
         [data-tv=\"small\"] {{ font-size: {}px; line-height: 1.5; }}\n\
         [data-tv=\"overline\"] {{ font-size: {}px; font-weight: 600; text-transform: uppercase; \
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
        "[data-btn] {{ display: inline-flex; align-items: center; justify-content: center; \
         gap: 0.5rem; font-family: {body_family}; font-size: {cta_size}px; font-weight: {cta_weight}; \
         line-height: 1; text-decoration: none; border-radius: {radius}px; \
         padding: 0.75rem 1.5rem; border: 1px solid transparent; cursor: pointer; \
         transition: filter 0.15s ease, background-color 0.15s ease; }}\n\
         [data-btn]:hover {{ filter: brightness(1.06); }}\n\
         [data-btn=\"primary\"] {{ background: var(--color-primary); color: {primary_contrast}; }}\n\
         [data-btn=\"secondary\"] {{ background: var(--color-dark); color: {dark_contrast}; }}\n\
         [data-btn=\"outline\"] {{ border-color: var(--color-dark); color: var(--color-dark); background: transparent; }}\n\
         [data-btn=\"ghost\"] {{ color: var(--color-dark); background: transparent; }}\n\
         [data-btn=\"ghost\"]:hover {{ background: color-mix(in srgb, var(--color-dark) 8%, transparent); filter: none; }}\n\
         [data-btn=\"link\"] {{ padding: 0; border: none; background: none; border-radius: 0; \
         color: var(--color-primary); text-decoration: underline; text-underline-offset: 3px; }}\n"
    ));
    css.push_str(
        "@media (prefers-reduced-motion: reduce) {\n  *, *::before, *::after { \
         animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; \
         transition-duration: 0.01ms !important; scroll-behavior: auto !important; }\n}\n",
    );
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
    fn deterministic_output() {
        let (a, _) = compile_platform();
        let (b, _) = compile_platform();
        assert_eq!(a.theme_block, b.theme_block);
        assert_eq!(a.base_css, b.base_css);
    }
}
