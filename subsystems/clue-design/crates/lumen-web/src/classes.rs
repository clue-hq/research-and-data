//! Class grammar lint — the grammar-level brand constraint.
//!
//! Color-bearing utilities must reference theme tokens (or
//! `white|black|transparent|current|inherit`), so off-brand color is
//! *inexpressible*, not merely discouraged: raw values (`bg-[#231d40]`) and
//! stock Tailwind palette colors (`text-red-500`) are hard errors with a
//! nearest-token suggestion. Non-color arbitrary values (`max-w-[1380px]`)
//! pass. Unknown non-color utilities are warnings only: a false accept is
//! harmless (the browser ignores the class), while a false reject would burn
//! author retries — color is the axis that must never loosen.
//!
//! Brand geometry has its own closed vocabulary alongside the color one:
//! `rounded-button|card|badge`, `shadow-brand|card`, `border-w-card|divider`,
//! `py-section`, `gap-stack`, `p-card`. These are NOT color references — each
//! resolves through the compiled theme's geometry channel
//! (`theme.rs::compile_web_theme` → `--radius-*` / `--shadow-*` /
//! `--border-width-*` / `--spacing-*`) onto the pinned kit's measured geometry,
//! with a platform fallback, so a brand's real corner radius, elevation,
//! hairline and rhythm are expressible by name and never as a raw value. Six of
//! them already pass through the `rounded-`/`p-`/`py-`/`gap-` prefixes below;
//! the four that land in a color-capable namespace (`shadow-`, `border-`) are
//! listed as non-color suffixes there.

use lumen_core::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, NodeId, Phase};
use std::collections::BTreeMap;

pub struct ClassLintContext<'a> {
    /// Theme token name -> resolved CSS color (used for membership checks and
    /// nearest-token suggestions).
    pub color_tokens: &'a BTreeMap<String, String>,
    /// The pinned kit carries a Creative Brief — its shape (radius, elevation)
    /// was MEASURED off the brand, not guessed, so a raw stock step where a
    /// brand utility exists is visible drift worth naming. Advice only: it
    /// reaches the authoring agent and nothing else, and can never reject.
    /// `false` (a kit with no brief) is byte-identical to the pre-brief lint.
    pub briefed: bool,
}

const ALLOWED_VARIANT_PREFIXES: &[&str] = &["md", "lg", "hover", "focus"];

const COLOR_BUILTINS: &[&str] = &["white", "black", "transparent", "current", "inherit"];

/// Stock Tailwind palette families — referencing these instead of theme
/// tokens is exactly the drift the lint exists to block.
const TAILWIND_PALETTES: &[&str] = &[
    "slate", "gray", "zinc", "neutral", "stone", "red", "orange", "amber", "yellow", "lime",
    "green", "emerald", "teal", "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia",
    "pink", "rose",
];

/// Tailwind v3 names that silently do nothing in v4. Mutiny TEACHES this
/// list because their pipeline cannot enforce it; ours can — a dead class
/// is invisible drift, so it is an error with the rename, not a warning.
/// Entries ending in `-` are prefixes (the suffix carries over verbatim).
const DEAD_UTILITIES: &[(&str, &str)] = &[
    ("flex-shrink-", "shrink-"),
    ("flex-shrink", "shrink"),
    ("flex-grow-", "grow-"),
    ("flex-grow", "grow"),
    ("blur-0", "blur-none"),
    ("overflow-ellipsis", "text-ellipsis"),
    ("decoration-slice", "box-decoration-slice"),
    ("decoration-clone", "box-decoration-clone"),
];

/// Color-capable utility namespaces with their known non-color suffixes.
/// Longest prefix wins (`border-x-` before `border-`).
const COLOR_PREFIXES: &[(&str, &[&str])] = &[
    ("bg-", &[
        "none", "auto", "cover", "contain", "center", "top", "bottom", "left", "right", "fixed",
        "local", "scroll", "repeat", "no-repeat", "repeat-x", "repeat-y", "clip-border",
        "clip-padding", "clip-content", "clip-text", "origin-border", "origin-padding",
        "origin-content",
    ]),
    ("text-", &[
        "xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl", "7xl", "8xl", "9xl",
        "left", "center", "right", "justify", "start", "end", "wrap", "nowrap", "balance",
        "pretty", "ellipsis", "clip",
    ]),
    ("border-x-", &["0", "2", "4", "8"]),
    ("border-y-", &["0", "2", "4", "8"]),
    ("border-t-", &["0", "2", "4", "8"]),
    ("border-r-", &["0", "2", "4", "8"]),
    ("border-b-", &["0", "2", "4", "8"]),
    ("border-l-", &["0", "2", "4", "8"]),
    ("border-", &[
        "0", "2", "4", "8", "t", "r", "b", "l", "x", "y", "solid", "dashed", "dotted", "double",
        "hidden", "none", "collapse", "separate",
        // Brand-geometry border widths (theme `--border-width-*`). Spelled
        // `border-w-*` deliberately: `border-card` would resolve as a COLOR
        // (`card` is a semantic color token).
        "w-card", "w-divider",
    ]),
    ("from-", &[]),
    ("via-", &[]),
    ("to-", &[]),
    ("ring-", &["0", "1", "2", "4", "8", "inset"]),
    ("ring-offset-", &["0", "1", "2", "4", "8"]),
    ("fill-", &["none"]),
    ("stroke-", &["0", "1", "2", "none"]),
    ("decoration-", &[
        "0", "1", "2", "4", "8", "auto", "solid", "double", "dotted", "dashed", "wavy",
        "from-font",
    ]),
    ("outline-", &["0", "1", "2", "4", "8", "none", "dashed", "dotted", "double", "offset-0",
        "offset-1", "offset-2", "offset-4", "offset-8"]),
    ("divide-", &["0", "2", "4", "8", "x", "y", "solid", "dashed", "dotted", "double", "none"]),
    ("accent-", &["auto"]),
    ("caret-", &[]),
    // `brand`/`card` are brand-geometry elevations (theme `--shadow-*`), not
    // shadow colors.
    ("shadow-", &["sm", "md", "lg", "xl", "2xl", "inner", "none", "brand", "card"]),
];

/// Known non-color utility vocabulary. Entries ending in `-` are prefixes;
/// bare entries match exactly.
const KNOWN_UTILITIES: &[&str] = &[
    // display / layout
    "flex", "inline-flex", "grid", "inline-grid", "block", "inline-block", "inline", "hidden",
    "contents", "flow-root", "isolate", "container",
    "items-", "justify-", "content-", "self-", "place-",
    "gap-", "space-x-", "space-y-", "order-", "col-", "row-", "grid-cols-", "grid-rows-",
    "grow", "grow-", "shrink", "shrink-", "basis-", "flex-",
    // sizing
    "w-", "h-", "min-w-", "min-h-", "max-w-", "max-h-", "size-", "aspect-",
    // spacing
    "p-", "px-", "py-", "pt-", "pr-", "pb-", "pl-",
    "m-", "mx-", "my-", "mt-", "mr-", "mb-", "ml-",
    // typography (non-color)
    "font-", "leading-", "tracking-", "align-",
    "uppercase", "lowercase", "capitalize", "normal-case",
    "italic", "not-italic", "underline", "line-through", "no-underline",
    "underline-offset-", "truncate", "whitespace-", "break-", "hyphens-", "list-", "indent-",
    // borders / radius (non-color handled above; radius here)
    "rounded", "rounded-",
    "border", // bare border = 1px width
    "ring",   // bare ring
    "outline",
    // effects / filters
    "shadow", "opacity-", "blur", "blur-", "brightness-", "contrast-", "grayscale", "grayscale-",
    "saturate-", "sepia", "sepia-", "invert", "invert-", "backdrop-", "mix-blend-",
    "drop-shadow", "drop-shadow-",
    // motion
    "transition", "transition-", "duration-", "ease-", "delay-", "animate-",
    "scale-", "rotate-", "translate-x-", "translate-y-", "skew-x-", "skew-y-", "transform",
    "origin-",
    // position
    "relative", "absolute", "fixed", "sticky", "static",
    "inset-", "inset-x-", "inset-y-", "top-", "right-", "bottom-", "left-", "z-",
    // overflow / scroll
    "overflow-", "overscroll-", "scroll-", "snap-",
    // misc
    "object-", "cursor-", "select-", "pointer-events-", "resize", "resize-",
    "sr-only", "not-sr-only", "appearance-", "will-change-", "columns-", "break-inside-",
    "break-before-", "break-after-", "line-clamp-",
    "box-decoration-slice", "box-decoration-clone", "box-border", "box-content",
];

/// Stock all-corner radius steps — the WHOLE v4 ramp, `xs` and `4xl` included.
/// Both are legal Tailwind v4 names that lint clean, so leaving either out
/// would hand the author a silent way to dodge the advice. Side/corner variants
/// (`rounded-t-*`, `rounded-tl-*`) are deliberately absent: a side radius is
/// compositional and has no brand utility to prefer.
const STOCK_RADIUS_STEPS: &[&str] = &[
    "none", "xs", "sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "full",
];

/// Stock elevation steps. `none` is absent on purpose — removing a shadow is a
/// legitimate design decision, not drift away from the brand's measured one.
const STOCK_SHADOW_STEPS: &[&str] = &["sm", "md", "lg", "xl", "2xl", "inner"];

pub fn lint_classes(
    classes: &str,
    node: Option<&NodeId>,
    ctx: &ClassLintContext<'_>,
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for token in classes.split_whitespace() {
        lint_class_token(token, node, ctx, &mut diagnostics);
    }
    diagnostics
}

/// Append `incoming` to `sink`, dropping advice `sink` already carries.
///
/// Advice is a per-outcome observation, not a per-node defect: a forty-card
/// page whose every card says `rounded-2xl` earns ONE line naming the class,
/// not forty naming nodes. Errors and warnings are never deduped — they are
/// node-keyed work items.
pub fn extend_deduping_advice(sink: &mut Vec<Diagnostic>, incoming: Vec<Diagnostic>) {
    for diagnostic in incoming {
        if diagnostic.severity == DiagnosticSeverity::Advice
            && sink.iter().any(|existing| {
                existing.severity == DiagnosticSeverity::Advice
                    && existing.code == diagnostic.code
                    && existing.message == diagnostic.message
            })
        {
            continue;
        }
        sink.push(diagnostic);
    }
}

/// The brand-shape axes: where the brief measured a real value AND a named
/// utility exists to spend it. Returns the utilities to prefer.
///
/// Deliberately narrow. Spacing, gaps and border widths have utilities too, but
/// legitimate non-brand uses dominate them (a one-off `py-20` is not drift), so
/// only radius and elevation — the two axes a brand's shape is actually read
/// from — are named here. The prompt teaches the rest.
fn raw_brand_shape(base: &str) -> Option<&'static str> {
    let arbitrary = |namespace: &str| {
        base.strip_prefix(namespace)
            .is_some_and(|rest| rest.starts_with('['))
    };
    if base == "rounded"
        || arbitrary("rounded-")
        || base
            .strip_prefix("rounded-")
            .is_some_and(|step| STOCK_RADIUS_STEPS.contains(&step))
    {
        return Some("`rounded-button`/`rounded-card`/`rounded-badge`");
    }
    if base == "shadow"
        || arbitrary("shadow-")
        || base
            .strip_prefix("shadow-")
            .is_some_and(|step| STOCK_SHADOW_STEPS.contains(&step))
    {
        return Some("`shadow-brand`/`shadow-card`");
    }
    None
}

fn subject(node: Option<&NodeId>) -> Option<DiagnosticSubject> {
    node.map(|id| DiagnosticSubject::Node(id.clone()))
}

fn lint_class_token(
    token: &str,
    node: Option<&NodeId>,
    ctx: &ClassLintContext<'_>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let segments = split_prefixes(token);
    let (prefixes, base) = segments;
    for prefix in &prefixes {
        if *prefix == "dark" {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0201",
                    format!("`{token}`: the dark: variant is not supported in v0"),
                    subject(node),
                )
                .with_hint("Author light-mode only; dark mode is a later phase."),
            );
            return;
        }
        if *prefix == "sm" || *prefix == "xl" {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0203",
                    format!("`{token}`: the {prefix}: breakpoint is not part of the authoring grammar"),
                    subject(node),
                )
                .with_hint(
                    "Never author a breakpoint the review loop does not look at: 375px is the \
                     base layer, 768px is md:, 1440px is covered by lg:. Rewrite sm: styles into \
                     the base layer and xl: styles into lg:.",
                ),
            );
            return;
        }
        if !ALLOWED_VARIANT_PREFIXES.contains(prefix) {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0202",
                    format!("`{token}`: unknown variant prefix `{prefix}:`"),
                    subject(node),
                )
                .with_hint("Allowed prefixes: md: lg: hover: focus:"),
            );
            return;
        }
    }

    let base = base.strip_prefix('-').unwrap_or(base);
    if base.is_empty() {
        return;
    }

    // Brand-shape drift on a briefed kit. Advice: it never returns early, never
    // suppresses another diagnostic, and never rejects — the class is legal
    // Tailwind and stays exactly as authored. The subject is dropped so
    // identical advice from many nodes collapses to one line (the message names
    // the class, which is what the author greps for).
    if ctx.briefed {
        if let Some(prefer) = raw_brand_shape(base) {
            diagnostics.push(
                Diagnostic::advice(
                    Phase::Web,
                    "LUMW0306",
                    format!(
                        "`{token}`: this kit carries a Creative Brief — its shape is measured; \
                         prefer {prefer} (see BRAND GEOMETRY)"
                    ),
                    None,
                )
                .with_hint(
                    "Advisory only — nothing is blocked. Spend the brand utility where the shape \
                     IS a brand decision (controls, cards, badges, elevation); a raw step stays \
                     right where the shape is deliberately its own.",
                ),
            );
        }
    }

    // Tailwind v3 names that silently no-op in v4: a hard error with the
    // rename, so dead classes never masquerade as applied styling.
    for (dead, replacement) in DEAD_UTILITIES {
        let hit = if dead.ends_with('-') {
            base.starts_with(dead) && base.len() > dead.len()
        } else {
            base == *dead
        };
        if hit {
            let named_replacement = if dead.ends_with('-') {
                format!("{replacement}{}", &base[dead.len()..])
            } else {
                (*replacement).to_owned()
            };
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0221",
                    format!("`{token}`: `{dead}` is a Tailwind v3 name that does nothing in v4"),
                    subject(node),
                )
                .with_hint(format!("Use `{named_replacement}`.")),
            );
            return;
        }
    }

    // Arbitrary values: allowed unless a color lands in a color namespace.
    if let Some(bracket) = base.find('[') {
        let namespace = &base[..bracket];
        let value = base[bracket + 1..].trim_end_matches(']');
        let color_namespace = COLOR_PREFIXES
            .iter()
            .any(|(prefix, _)| namespace == prefix.trim_end_matches('-') || namespace == *prefix || format!("{namespace}-") == *prefix);
        if color_namespace && value_is_color(value) {
            let mut diagnostic = Diagnostic::error(
                Phase::Web,
                "LUMW0210",
                format!("`{token}`: raw color values are not allowed; use a theme token"),
                subject(node),
            );
            let utility_prefix = if namespace.ends_with('-') {
                namespace.to_owned()
            } else {
                format!("{namespace}-")
            };
            let hint = match nearest_token(value, ctx) {
                Some((name, css)) => format!(
                    "Nearest theme token: `{utility_prefix}{name}` ({css}). Tokens: {}",
                    token_list(ctx)
                ),
                None => format!("Theme tokens: {}", token_list(ctx)),
            };
            diagnostic = diagnostic.with_hint(hint);
            diagnostics.push(diagnostic);
        }
        return;
    }

    // Color-capable namespaces, longest prefix first.
    let mut color_match: Option<(&str, &[&str])> = None;
    for (prefix, allow) in COLOR_PREFIXES {
        if let Some(suffix) = base.strip_prefix(prefix) {
            if !suffix.is_empty() {
                match color_match {
                    Some((existing, _)) if existing.len() >= prefix.len() => {}
                    _ => color_match = Some((prefix, allow)),
                }
            }
        }
    }
    if let Some((prefix, non_color_allow)) = color_match {
        let suffix = base.strip_prefix(prefix).unwrap_or(base);
        lint_color_suffix(token, prefix, suffix, non_color_allow, node, ctx, diagnostics);
        return;
    }

    // Everything else: known vocabulary or a warning.
    let known = KNOWN_UTILITIES.iter().any(|entry| {
        if entry.ends_with('-') {
            base.starts_with(entry) && base.len() > entry.len()
        } else {
            base == *entry
        }
    });
    if !known {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Web,
                "LUMW0220",
                format!("`{token}`: unknown utility; it may render as nothing"),
                subject(node),
            )
            .with_hint("Check the web-authoring vocabulary; unknown classes are ignored by the browser."),
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn lint_color_suffix(
    token: &str,
    prefix: &str,
    suffix: &str,
    non_color_allow: &[&str],
    node: Option<&NodeId>,
    ctx: &ClassLintContext<'_>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    // Gradient direction utilities live in the bg- namespace.
    if prefix == "bg-" && (suffix.starts_with("linear-to") || suffix.starts_with("gradient-to")) {
        return;
    }
    // Gradient stop positions (from-10%, via-30%, to-90%) are positions,
    // not colors.
    if matches!(prefix, "from-" | "via-" | "to-")
        && suffix.strip_suffix('%').is_some_and(|stop| {
            !stop.is_empty() && stop.bytes().all(|byte| byte.is_ascii_digit())
        })
    {
        return;
    }
    if non_color_allow.contains(&suffix) {
        return;
    }
    // Split an opacity modifier: bg-primary/15.
    let (color_ref, opacity) = match suffix.split_once('/') {
        Some((color, opacity)) => (color, Some(opacity)),
        None => (suffix, None),
    };
    if let Some(opacity) = opacity {
        let valid = opacity
            .parse::<u32>()
            .map(|value| value <= 100)
            .unwrap_or(false);
        if !valid {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0213",
                    format!("`{token}`: invalid opacity modifier `/{opacity}`"),
                    subject(node),
                )
                .with_hint("Use an integer 0-100, e.g. bg-primary/15."),
            );
            return;
        }
    }
    if non_color_allow.contains(&color_ref) {
        return;
    }
    if COLOR_BUILTINS.contains(&color_ref) || ctx.color_tokens.contains_key(color_ref) {
        return;
    }
    // A stock Tailwind palette reference?
    let palette_hit = color_ref
        .rsplit_once('-')
        .map(|(family, stop)| {
            TAILWIND_PALETTES.contains(&family)
                && matches!(
                    stop,
                    "50" | "100" | "200" | "300" | "400" | "500" | "600" | "700" | "800" | "900"
                        | "950"
                )
        })
        .unwrap_or(false)
        || TAILWIND_PALETTES.contains(&color_ref);
    if palette_hit {
        diagnostics.push(
            Diagnostic::error(
                Phase::Web,
                "LUMW0211",
                format!(
                    "`{token}`: stock Tailwind palette colors are off-brand; use a theme token"
                ),
                subject(node),
            )
            .with_hint(format!("Theme tokens: {}", token_list(ctx))),
        );
        return;
    }
    diagnostics.push(
        Diagnostic::error(
            Phase::Web,
            "LUMW0212",
            format!("`{token}`: `{color_ref}` is not a theme token"),
            subject(node),
        )
        .with_hint(format!(
            "Theme tokens: {} (plus white/black/transparent/current).",
            token_list(ctx)
        )),
    );
}

/// Split variant prefixes on `:` while ignoring colons inside brackets.
fn split_prefixes(token: &str) -> (Vec<&str>, &str) {
    let mut prefixes = Vec::new();
    let mut depth = 0usize;
    let mut start = 0usize;
    for (index, ch) in token.char_indices() {
        match ch {
            '[' => depth += 1,
            ']' => depth = depth.saturating_sub(1),
            ':' if depth == 0 => {
                prefixes.push(&token[start..index]);
                start = index + 1;
            }
            _ => {}
        }
    }
    (prefixes, &token[start..])
}

fn value_is_color(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    lower.starts_with('#')
        || lower.starts_with("rgb(")
        || lower.starts_with("rgba(")
        || lower.starts_with("hsl(")
        || lower.starts_with("hsla(")
        || lower.starts_with("oklch(")
        || lower.starts_with("oklab(")
        || lower.starts_with("color(")
}

fn token_list(ctx: &ClassLintContext<'_>) -> String {
    let names: Vec<&str> = ctx.color_tokens.keys().map(String::as_str).collect();
    if names.is_empty() {
        "(none compiled)".to_owned()
    } else {
        names.join(", ")
    }
}

fn nearest_token<'a>(
    raw_value: &str,
    ctx: &'a ClassLintContext<'_>,
) -> Option<(&'a str, &'a str)> {
    let target = parse_hex(raw_value)?;
    let mut best: Option<(&str, &str, u32)> = None;
    for (name, css) in ctx.color_tokens {
        if let Some(candidate) = parse_hex(css) {
            let distance = target
                .iter()
                .zip(candidate.iter())
                .map(|(a, b)| {
                    let delta = *a as i32 - *b as i32;
                    (delta * delta) as u32
                })
                .sum();
            match best {
                Some((_, _, best_distance)) if best_distance <= distance => {}
                _ => best = Some((name.as_str(), css.as_str(), distance)),
            }
        }
    }
    best.map(|(name, css, _)| (name, css))
}

fn parse_hex(value: &str) -> Option<[u8; 3]> {
    let hex = value.trim().strip_prefix('#')?;
    match hex.len() {
        3 => {
            let bytes: Vec<u8> = hex
                .chars()
                .map(|c| c.to_digit(16).map(|d| (d * 17) as u8))
                .collect::<Option<Vec<u8>>>()?;
            Some([bytes[0], bytes[1], bytes[2]])
        }
        6 | 8 => {
            let r = u8::from_str_radix(&hex[0..2], 16).ok()?;
            let g = u8::from_str_radix(&hex[2..4], 16).ok()?;
            let b = u8::from_str_radix(&hex[4..6], 16).ok()?;
            Some([r, g, b])
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumen_core::DiagnosticSeverity;

    fn ctx_with_tokens() -> BTreeMap<String, String> {
        let mut tokens = BTreeMap::new();
        tokens.insert("primary".to_owned(), "#4FD3C8".to_owned());
        tokens.insert("dark".to_owned(), "#1A1625".to_owned());
        tokens.insert("light".to_owned(), "#FFFCF4".to_owned());
        tokens
    }

    fn run(classes: &str) -> Vec<Diagnostic> {
        let tokens = ctx_with_tokens();
        lint_classes(
            classes,
            None,
            &ClassLintContext {
                color_tokens: &tokens,
                briefed: false,
            },
        )
    }

    #[test]
    fn clean_branded_classes_pass() {
        let diagnostics = run(
            "flex flex-col gap-6 bg-light text-dark md:grid md:grid-cols-3 rounded-2xl \
             px-6 py-20 hover:bg-primary/15 max-w-[1380px] bg-linear-to-br from-primary to-dark",
        );
        assert!(diagnostics.is_empty(), "unexpected: {diagnostics:?}");
    }

    #[test]
    fn raw_hex_is_rejected_with_nearest_token() {
        let diagnostics = run("bg-[#4fd0c6]");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].code, "LUMW0210");
        assert_eq!(diagnostics[0].severity, DiagnosticSeverity::Error);
        assert!(diagnostics[0].hint.as_ref().unwrap().contains("bg-primary"));
    }

    #[test]
    fn stock_palette_is_rejected() {
        let diagnostics = run("text-red-500");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].code, "LUMW0211");
    }

    #[test]
    fn unknown_color_token_is_rejected() {
        let diagnostics = run("bg-brandish");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].code, "LUMW0212");
    }

    #[test]
    fn dark_prefix_rejected_unknown_prefix_rejected() {
        assert_eq!(run("dark:bg-primary")[0].code, "LUMW0201");
        let unknown = run("2xl:flex");
        assert_eq!(unknown[0].code, "LUMW0202");
        assert_eq!(
            unknown[0].hint.as_deref(),
            Some("Allowed prefixes: md: lg: hover: focus:")
        );
    }

    #[test]
    fn dead_utilities_error_with_rename() {
        for (input, replacement) in [
            ("flex-shrink-0", "shrink-0"),
            ("flex-shrink", "shrink"),
            ("flex-grow-0", "grow-0"),
            ("flex-grow", "grow"),
            ("blur-0", "blur-none"),
            ("overflow-ellipsis", "text-ellipsis"),
            ("decoration-slice", "box-decoration-slice"),
            ("decoration-clone", "box-decoration-clone"),
        ] {
            let diagnostics = run(input);
            assert_eq!(diagnostics.len(), 1, "for `{input}`: {diagnostics:?}");
            assert_eq!(diagnostics[0].code, "LUMW0221", "for `{input}`");
            assert_eq!(diagnostics[0].severity, DiagnosticSeverity::Error);
            assert!(
                diagnostics[0]
                    .hint
                    .as_ref()
                    .unwrap()
                    .contains(replacement),
                "for `{input}`: hint {:?} missing `{replacement}`",
                diagnostics[0].hint
            );
        }
    }

    #[test]
    fn dead_utility_prefix_splices_suffix() {
        let diagnostics = run("flex-shrink-0");
        assert_eq!(diagnostics[0].code, "LUMW0221");
        assert_eq!(diagnostics[0].hint.as_deref(), Some("Use `shrink-0`."));
    }

    #[test]
    fn correct_v4_names_are_clean() {
        assert!(run("box-decoration-slice box-border shrink-0 grow blur-none").is_empty());
    }

    #[test]
    fn dropped_breakpoints_get_review_loop_error() {
        for token in ["sm:flex", "xl:grid"] {
            let diagnostics = run(token);
            assert_eq!(diagnostics.len(), 1, "for `{token}`: {diagnostics:?}");
            assert_eq!(diagnostics[0].code, "LUMW0203", "for `{token}`");
            assert!(diagnostics[0]
                .hint
                .as_ref()
                .unwrap()
                .contains("the review loop does not look at"));
        }
    }

    #[test]
    fn supported_breakpoints_and_variants_pass() {
        assert!(run("md:grid lg:flex hover:bg-primary/15 focus:outline").is_empty());
    }

    #[test]
    fn bad_opacity_modifier_rejected() {
        assert_eq!(run("bg-primary/150")[0].code, "LUMW0213");
        assert!(run("bg-primary/15").is_empty());
    }

    #[test]
    fn non_color_arbitrary_values_pass() {
        assert!(run("max-w-[72rem] w-[42%] leading-[1.06]").is_empty());
    }

    #[test]
    fn gradient_stop_positions_pass() {
        assert!(run("from-primary from-10% via-30% to-dark to-90%").is_empty());
        assert_eq!(run("from-10x")[0].code, "LUMW0212");
    }

    #[test]
    fn text_size_and_alignment_are_not_colors() {
        assert!(run("text-5xl text-center text-balance").is_empty());
    }

    #[test]
    fn unknown_utility_is_warning_only() {
        let diagnostics = run("floop-3");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].code, "LUMW0220");
        assert_eq!(diagnostics[0].severity, DiagnosticSeverity::Warning);
    }

    #[test]
    fn builtin_colors_pass() {
        assert!(run("bg-white text-black border-transparent").is_empty());
    }

    #[test]
    fn brand_geometry_utilities_lint_clean() {
        for token in [
            "rounded-button",
            "rounded-card",
            "rounded-badge",
            "shadow-brand",
            "shadow-card",
            "border-w-card",
            "border-w-divider",
            "py-section",
            "gap-stack",
            "p-card",
        ] {
            let diagnostics = run(token);
            assert!(
                diagnostics.is_empty(),
                "brand-geometry utility `{token}` should lint clean: {diagnostics:?}"
            );
        }
    }

    #[test]
    fn brand_geometry_utilities_pass_under_variants() {
        assert!(run("md:py-section hover:shadow-brand lg:border-w-card").is_empty());
    }

    // --- LUMW0306: raw brand-shape geometry on a briefed kit -----------------

    fn run_briefed(classes: &str) -> Vec<Diagnostic> {
        let tokens = ctx_with_tokens();
        lint_classes(
            classes,
            None,
            &ClassLintContext {
                color_tokens: &tokens,
                briefed: true,
            },
        )
    }

    fn advice(classes: &str) -> Vec<Diagnostic> {
        run_briefed(classes)
            .into_iter()
            .filter(|diagnostic| diagnostic.code == "LUMW0306")
            .collect()
    }

    #[test]
    fn briefed_raw_radius_and_shadow_get_advice() {
        for token in [
            "rounded",
            "rounded-none",
            "rounded-xs",
            "rounded-sm",
            "rounded-md",
            "rounded-lg",
            "rounded-xl",
            "rounded-2xl",
            "rounded-3xl",
            "rounded-4xl",
            "rounded-full",
            "rounded-[13px]",
            "md:rounded-2xl",
            "shadow",
            "shadow-sm",
            "shadow-md",
            "shadow-lg",
            "shadow-xl",
            "shadow-2xl",
            "shadow-inner",
            "shadow-[0_2px_4px_rgba(0,0,0,0.1)]",
            "lg:shadow-lg",
        ] {
            let found = advice(token);
            assert_eq!(found.len(), 1, "expected advice for `{token}`: {found:?}");
            assert_eq!(found[0].severity, DiagnosticSeverity::Advice);
            assert!(
                found[0].message.contains(token),
                "advice must name `{token}`: {}",
                found[0].message
            );
            assert!(found[0].subject.is_none(), "advice is deduped, not node-keyed");
        }
    }

    #[test]
    fn briefed_advice_leaves_the_rest_of_the_grammar_alone() {
        for token in [
            // The brand utilities themselves.
            "rounded-button",
            "rounded-card",
            "rounded-badge",
            "shadow-brand",
            "shadow-card",
            // Removal is a decision, not drift.
            "shadow-none",
            // Side/corner radius is compositional — no utility exists.
            "rounded-t-lg",
            "rounded-tl-lg",
            "rounded-b-[4px]",
            // Deliberately out of scope: spacing, border widths, gaps.
            "py-20",
            "p-6",
            "gap-4",
            "border-2",
            "px-6",
            // Neighbours that merely start with the same letters.
            "drop-shadow-lg",
        ] {
            let found = advice(token);
            assert!(found.is_empty(), "`{token}` must not be advised: {found:?}");
        }
    }

    #[test]
    fn unbriefed_lint_is_unchanged() {
        for token in ["rounded-2xl", "shadow-lg", "rounded-[13px]", "shadow"] {
            assert!(
                run(token).is_empty(),
                "`{token}` must stay silent without a brief"
            );
        }
    }

    #[test]
    fn advice_rides_alongside_a_real_error() {
        // A raw shadow COLOR is still a hard error; the advice does not
        // replace it, and the error still rejects.
        let diagnostics = run_briefed("shadow-[#ff0000]");
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0210"
                && diagnostic.severity == DiagnosticSeverity::Error));
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0306"));
    }
}
