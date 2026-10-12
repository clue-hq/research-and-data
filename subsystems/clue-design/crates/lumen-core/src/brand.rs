use crate::assets::{AssetLicense, AssetSource};
use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{AssetId, BrandKitId, NodeId, PaintId};
use crate::operations::{FieldPatch, NodePatch, Operation, OptionalFieldPatch, PagePatch};
use crate::scene::{
    AutoLayoutProps, BrandKitRef, Color, CornerRadii, Dimension, Fill, Node, NodeKind, Paint,
    Scene, TextNode,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub const PLATFORM_DEFAULT_BRAND_KIT_JSON: &str =
    include_str!("../fixtures/brand_kits/platform_default.json");

const COLOR_STOPS: [(&str, f64); 11] = [
    ("50", 0.97),
    ("100", 0.93),
    ("200", 0.86),
    ("300", 0.78),
    ("400", 0.68),
    ("500", 0.58),
    ("600", 0.49),
    ("700", 0.40),
    ("800", 0.31),
    ("900", 0.23),
    ("950", 0.16),
];

const PRESENCE_STOPS: [(&str, &str); 9] = [
    ("hint", "50"),
    ("faint", "100"),
    ("subtle", "200"),
    ("soft", "300"),
    ("mid", "500"),
    ("firm", "600"),
    ("bold", "700"),
    ("strong", "800"),
    ("intense", "900"),
];

const TSHIRT_STOPS: [&str; 10] = [
    "none", "xs", "sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "5xl",
];

pub const REQUIRED_PRODUCT_READY_COLOR_TOKENS: &[&str] = &[
    "palette.primary.50",
    "palette.primary.100",
    "palette.primary.200",
    "palette.primary.300",
    "palette.primary.400",
    "palette.primary.500",
    "palette.primary.600",
    "palette.primary.700",
    "palette.primary.800",
    "palette.primary.900",
    "palette.primary.950",
    "palette.neutral.50",
    "palette.neutral.100",
    "palette.neutral.200",
    "palette.neutral.300",
    "palette.neutral.400",
    "palette.neutral.500",
    "palette.neutral.600",
    "palette.neutral.700",
    "palette.neutral.800",
    "palette.neutral.900",
    "palette.neutral.950",
    "surface.canvas",
    "surface.page",
    "surface.card",
    "surface.elevated",
    "surface.brand",
    "surface.brand.subtle",
    "surface.accent",
    "surface.muted",
    "surface.inverse",
    "text.primary",
    "text.secondary",
    "text.muted",
    "text.inverse",
    "text.brand",
    "text.accent",
    "border.subtle",
    "border.default",
    "border.strong",
    "border.brand",
    "focus.ring",
];

pub const REQUIRED_PRODUCT_READY_TYPOGRAPHY_TOKENS: &[&str] = &[
    "type.display",
    "type.headline",
    "type.title",
    "type.subtitle",
    "type.body",
    "type.body.small",
    "type.caption",
    "type.eyebrow",
    "type.label",
    "type.cta",
    "type.stat",
    "type.legal",
];

pub const REQUIRED_PRODUCT_READY_SPACING_TOKENS: &[&str] = &[
    "space.0",
    "space.1",
    "space.2",
    "space.3",
    "space.4",
    "space.5",
    "space.6",
    "space.8",
    "space.10",
    "space.12",
    "space.16",
    "space.stack.tight",
    "space.stack.default",
    "space.stack.loose",
    "space.section",
    "space.page.margin",
    "space.card.padding",
];

pub const REQUIRED_PRODUCT_READY_RADIUS_TOKENS: &[&str] = &[
    "radius.none",
    "radius.xs",
    "radius.sm",
    "radius.md",
    "radius.lg",
    "radius.xl",
    "radius.full",
    "radius.card",
    "radius.button",
    "radius.badge",
];

pub const REQUIRED_PRODUCT_READY_STROKE_WIDTH_TOKENS: &[&str] = &[
    "stroke.width.hairline",
    "stroke.width.thin",
    "stroke.width.default",
    "stroke.width.firm",
    "stroke.width.bold",
    "stroke.width.divider",
    "stroke.width.card",
    "stroke.width.focus",
];

pub const REQUIRED_PRODUCT_READY_OPACITY_TOKENS: &[&str] = &[
    "opacity.disabled",
    "opacity.subtle",
    "opacity.muted",
    "opacity.overlay",
    "opacity.scrim",
    "opacity.emphasis",
];

pub const REQUIRED_PRODUCT_READY_ASSET_TOKENS: &[&str] = &[
    "logo.primary",
    "logo.reversed",
    "logo.mark",
    "logo.wordmark",
    "asset.illustration.primary",
    "asset.texture.subtle",
    "asset.icon.primary",
];

const REQUIRED_MODE_AXES: &[(&str, &[&str])] = &[
    ("theme", &["light", "dark"]),
    ("density", &["comfortable", "compact"]),
    (
        "accessibility",
        &["standard", "high_contrast", "large_text"],
    ),
    ("medium", &["digital", "print"]),
];

const CRITICAL_MODE_COLOR_TOKENS: &[&str] = &[
    "surface.canvas",
    "surface.page",
    "surface.card",
    "surface.brand",
    "text.primary",
    "text.secondary",
    "text.inverse",
    "border.default",
    "focus.ring",
];

const CRITICAL_MODE_TYPOGRAPHY_TOKENS: &[&str] = &["type.headline", "type.body", "type.cta"];

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandKit {
    pub id: BrandKitId,
    pub version: u32,
    pub name: String,
    pub description: Option<String>,
    #[serde(default)]
    pub sources: Vec<BrandSource>,
    pub provenance: Option<BrandProvenance>,
    #[serde(default)]
    pub approval_status: BrandApprovalStatus,
    #[serde(default)]
    pub compatibility_policy: BrandCompatibilityPolicy,
    #[serde(default)]
    pub modes: BrandModeSpec,
    #[serde(default)]
    pub tokens: TokenCatalog,
    #[serde(default)]
    pub assets: BrandAssets,
    #[serde(default)]
    pub constraints: BrandConstraints,
}

impl BrandKit {
    pub fn brand_ref(&self) -> BrandKitRef {
        BrandKitRef {
            id: self.id.clone(),
            version: self.version,
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrandApprovalStatus {
    #[default]
    Draft,
    GeneratedUnreviewed,
    Approved,
    Deprecated,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandCompatibilityPolicy {
    pub allow_critical_mode_fallbacks: bool,
    pub allow_unapproved_asset_placeholders: bool,
    pub require_product_ready_tokens: bool,
}

impl Default for BrandCompatibilityPolicy {
    fn default() -> Self {
        Self {
            allow_critical_mode_fallbacks: false,
            allow_unapproved_asset_placeholders: true,
            require_product_ready_tokens: false,
        }
    }
}

pub fn platform_default_brand_kit() -> Result<BrandKit, serde_json::Error> {
    let mut brand_kit: BrandKit = serde_json::from_str(PLATFORM_DEFAULT_BRAND_KIT_JSON)?;
    complete_platform_default_brand_kit(&mut brand_kit);
    Ok(brand_kit)
}

fn complete_platform_default_brand_kit(brand_kit: &mut BrandKit) {
    brand_kit.approval_status = BrandApprovalStatus::Approved;
    brand_kit.compatibility_policy = BrandCompatibilityPolicy {
        allow_critical_mode_fallbacks: false,
        allow_unapproved_asset_placeholders: true,
        require_product_ready_tokens: true,
    };
    ensure_required_mode_axes(&mut brand_kit.modes);
    ensure_platform_color_tokens(brand_kit);
    ensure_platform_number_tokens(brand_kit);
    ensure_platform_typography_tokens(brand_kit);
    ensure_platform_asset_tokens(brand_kit);
}

fn ensure_required_mode_axes(modes: &mut BrandModeSpec) {
    for (axis, values) in REQUIRED_MODE_AXES {
        let axis_values = modes.axes.entry((*axis).to_owned()).or_default();
        for value in *values {
            if !axis_values.iter().any(|candidate| candidate == value) {
                axis_values.push((*value).to_owned());
            }
        }
        modes
            .defaults
            .entry((*axis).to_owned())
            .or_insert_with(|| values[0].to_owned());
    }
}

fn ensure_platform_color_tokens(brand_kit: &mut BrandKit) {
    let primary = [
        ("50", "#ECFEFF"),
        ("100", "#CFFAFE"),
        ("200", "#A5F3FC"),
        ("300", "#67E8F9"),
        ("400", "#22D3EE"),
        ("500", "#06B6D4"),
        ("600", "#0891B2"),
        ("700", "#0E7490"),
        ("800", "#155E75"),
        ("900", "#164E63"),
        ("950", "#083344"),
    ];
    let neutral = [
        ("50", "#F8FAFC"),
        ("100", "#F1F5F9"),
        ("200", "#E2E8F0"),
        ("300", "#CBD5E1"),
        ("400", "#94A3B8"),
        ("500", "#64748B"),
        ("600", "#475569"),
        ("700", "#334155"),
        ("800", "#1E293B"),
        ("900", "#0F172A"),
        ("950", "#020617"),
    ];
    for (stop, hex) in primary {
        ensure_color(
            brand_kit,
            &format!("palette.primary.{stop}"),
            hex,
            None,
            None,
            "palette",
            "Generated platform primary ramp",
        );
    }
    for (stop, hex) in neutral {
        ensure_color(
            brand_kit,
            &format!("palette.neutral.{stop}"),
            hex,
            None,
            None,
            "palette",
            "Generated platform neutral ramp",
        );
    }

    let semantic = [
        (
            "surface.canvas",
            "#F8FAFC",
            "#020617",
            "#FFFFFF",
            "Main digital canvas",
        ),
        (
            "surface.page",
            "#FFFFFF",
            "#0F172A",
            "#FFFFFF",
            "Artifact page surface",
        ),
        (
            "surface.card",
            "#FFFFFF",
            "#1E293B",
            "#FFFFFF",
            "Card or panel surface",
        ),
        (
            "surface.elevated",
            "#FFFFFF",
            "#334155",
            "#FFFFFF",
            "Raised surface",
        ),
        (
            "surface.brand",
            "#155E75",
            "#67E8F9",
            "#000000",
            "Primary branded surface",
        ),
        (
            "surface.brand.subtle",
            "#CFFAFE",
            "#164E63",
            "#FFFFFF",
            "Subtle branded surface",
        ),
        (
            "surface.accent",
            "#06B6D4",
            "#22D3EE",
            "#000000",
            "Accent surface",
        ),
        (
            "surface.muted",
            "#E2E8F0",
            "#334155",
            "#FFFFFF",
            "Muted surface",
        ),
        (
            "surface.inverse",
            "#0F172A",
            "#F8FAFC",
            "#000000",
            "Inverse surface",
        ),
        (
            "text.primary",
            "#0F172A",
            "#F8FAFC",
            "#000000",
            "Primary text",
        ),
        (
            "text.secondary",
            "#475569",
            "#CBD5E1",
            "#000000",
            "Secondary text",
        ),
        ("text.muted", "#64748B", "#94A3B8", "#000000", "Muted text"),
        (
            "text.inverse",
            "#FFFFFF",
            "#0F172A",
            "#FFFFFF",
            "Inverse text",
        ),
        ("text.brand", "#155E75", "#67E8F9", "#000000", "Brand text"),
        (
            "text.accent",
            "#0891B2",
            "#22D3EE",
            "#000000",
            "Accent text",
        ),
        (
            "border.subtle",
            "#E2E8F0",
            "#334155",
            "#000000",
            "Subtle border",
        ),
        (
            "border.default",
            "#CBD5E1",
            "#64748B",
            "#000000",
            "Default border",
        ),
        (
            "border.strong",
            "#64748B",
            "#CBD5E1",
            "#000000",
            "Strong border",
        ),
        (
            "border.brand",
            "#155E75",
            "#67E8F9",
            "#000000",
            "Brand border",
        ),
        ("focus.ring", "#06B6D4", "#67E8F9", "#000000", "Focus ring"),
    ];
    for (path, default, dark, high_contrast, description) in semantic {
        ensure_color(
            brand_kit,
            path,
            default,
            Some(dark),
            Some(high_contrast),
            token_role(path),
            description,
        );
    }
}

fn ensure_platform_number_tokens(brand_kit: &mut BrandKit) {
    let spacing = [
        ("space.0", 0.0, 0.0),
        ("space.1", 4.0, 3.0),
        ("space.2", 8.0, 6.0),
        ("space.3", 12.0, 10.0),
        ("space.4", 16.0, 14.0),
        ("space.5", 20.0, 16.0),
        ("space.6", 24.0, 20.0),
        ("space.8", 32.0, 28.0),
        ("space.10", 40.0, 36.0),
        ("space.12", 48.0, 40.0),
        ("space.16", 64.0, 56.0),
        ("space.stack.tight", 8.0, 6.0),
        ("space.stack.default", 16.0, 12.0),
        ("space.stack.loose", 24.0, 20.0),
        ("space.section", 48.0, 40.0),
        ("space.page.margin", 64.0, 48.0),
        ("space.card.padding", 24.0, 20.0),
        ("space.xs", 4.0, 3.0),
        ("space.sm", 8.0, 6.0),
        ("space.md", 12.0, 10.0),
        ("space.lg", 16.0, 14.0),
        ("space.xl", 24.0, 20.0),
    ];
    for (path, default, compact) in spacing {
        ensure_number(
            &mut brand_kit.tokens.spacing,
            path,
            default,
            NumberUnit::Px,
            Some(("density.compact", compact)),
            "spacing",
        );
    }

    for (path, value) in [
        ("radius.none", 0.0),
        ("radius.xs", 2.0),
        ("radius.sm", 4.0),
        ("radius.md", 8.0),
        ("radius.lg", 12.0),
        ("radius.xl", 20.0),
        ("radius.full", 999.0),
        ("radius.card", 16.0),
        ("radius.button", 10.0),
        ("radius.badge", 999.0),
    ] {
        ensure_number(
            &mut brand_kit.tokens.radii,
            path,
            value,
            NumberUnit::Px,
            None,
            "radius",
        );
    }

    for (path, value) in [
        ("stroke.width.hairline", 0.5),
        ("stroke.width.thin", 1.0),
        ("stroke.width.default", 1.5),
        ("stroke.width.firm", 2.0),
        ("stroke.width.bold", 3.0),
        ("stroke.width.divider", 1.0),
        ("stroke.width.card", 1.0),
        ("stroke.width.focus", 2.0),
    ] {
        ensure_number(
            &mut brand_kit.tokens.stroke_widths,
            path,
            value,
            NumberUnit::Px,
            None,
            "stroke",
        );
    }

    for (path, value) in [
        ("opacity.disabled", 0.38),
        ("opacity.subtle", 0.72),
        ("opacity.muted", 0.64),
        ("opacity.overlay", 0.88),
        ("opacity.scrim", 0.56),
        ("opacity.emphasis", 1.0),
    ] {
        ensure_number(
            &mut brand_kit.tokens.opacity,
            path,
            value,
            NumberUnit::Ratio,
            None,
            "visibility",
        );
    }

    // Decoupled type-size step ladder (mirrors Brilliant's $font.size.*). These
    // are pure scalars an author/block reaches for to pick a surface-appropriate
    // size — e.g. a 1080² social hero uses `font_size($type.size.7xl)` (80) so it
    // dominates, while an A4 heading keeps the role default. Resolution is
    // identity (no canvas coupling) → safe for human editor resizing.
    for (path, value) in [
        ("type.size.xs", 12.0),
        ("type.size.sm", 14.0),
        ("type.size.md", 16.0),
        ("type.size.lg", 20.0),
        ("type.size.xl", 24.0),
        ("type.size.2xl", 32.0),
        ("type.size.3xl", 36.0),
        ("type.size.4xl", 40.0),
        ("type.size.5xl", 48.0),
        ("type.size.6xl", 64.0),
        ("type.size.7xl", 80.0),
        ("type.size.8xl", 96.0),
        ("type.size.9xl", 128.0),
    ] {
        ensure_number(
            &mut brand_kit.tokens.numbers,
            path,
            value,
            NumberUnit::Px,
            None,
            "font_size",
        );
    }
}

fn ensure_platform_typography_tokens(brand_kit: &mut BrandKit) {
    for spec in [
        TypographySpec {
            path: "type.display",
            size: 72.0,
            weight: 850,
            line_height: 1.0,
            letter_spacing: -0.02,
            color: "text.primary",
            large_text_size: 80.0,
        },
        TypographySpec {
            path: "type.headline",
            size: 56.0,
            weight: 800,
            line_height: 1.06,
            letter_spacing: -0.01,
            color: "text.primary",
            large_text_size: 62.0,
        },
        TypographySpec {
            path: "type.title",
            size: 36.0,
            weight: 750,
            line_height: 1.12,
            letter_spacing: -0.005,
            color: "text.primary",
            large_text_size: 40.0,
        },
        TypographySpec {
            path: "type.subtitle",
            size: 24.0,
            weight: 650,
            line_height: 1.24,
            letter_spacing: 0.0,
            color: "text.secondary",
            large_text_size: 27.0,
        },
        TypographySpec {
            path: "type.body",
            size: 18.0,
            weight: 450,
            line_height: 1.42,
            letter_spacing: 0.0,
            color: "text.primary",
            large_text_size: 20.0,
        },
        TypographySpec {
            path: "type.body.small",
            size: 14.0,
            weight: 450,
            line_height: 1.4,
            letter_spacing: 0.0,
            color: "text.secondary",
            large_text_size: 16.0,
        },
        TypographySpec {
            path: "type.caption",
            size: 12.0,
            weight: 500,
            line_height: 1.35,
            letter_spacing: 0.02,
            color: "text.secondary",
            large_text_size: 14.0,
        },
        TypographySpec {
            path: "type.eyebrow",
            size: 13.0,
            weight: 750,
            line_height: 1.1,
            letter_spacing: 0.08,
            color: "text.accent",
            large_text_size: 15.0,
        },
        TypographySpec {
            path: "type.label",
            size: 14.0,
            weight: 700,
            line_height: 1.1,
            letter_spacing: 0.0,
            color: "text.primary",
            large_text_size: 16.0,
        },
        TypographySpec {
            path: "type.cta",
            size: 16.0,
            weight: 800,
            line_height: 1.05,
            letter_spacing: 0.0,
            color: "text.inverse",
            large_text_size: 18.0,
        },
        TypographySpec {
            path: "type.stat",
            size: 48.0,
            weight: 850,
            line_height: 1.0,
            letter_spacing: -0.02,
            color: "text.brand",
            large_text_size: 54.0,
        },
        TypographySpec {
            path: "type.legal",
            size: 10.0,
            weight: 450,
            line_height: 1.35,
            letter_spacing: 0.0,
            color: "text.muted",
            large_text_size: 12.0,
        },
    ] {
        ensure_typography(brand_kit, spec);
    }
}

fn ensure_platform_asset_tokens(brand_kit: &mut BrandKit) {
    for (path, value, description) in [
        (
            "logo.primary",
            AssetTokenValue::Logo {
                logo_id: "primary".to_owned(),
                variant: Some("full_color".to_owned()),
            },
            "Primary logo slot",
        ),
        (
            "logo.reversed",
            AssetTokenValue::Logo {
                logo_id: "primary".to_owned(),
                variant: Some("reversed".to_owned()),
            },
            "Reversed logo slot",
        ),
        (
            "logo.mark",
            AssetTokenValue::Logo {
                logo_id: "mark".to_owned(),
                variant: Some("mark".to_owned()),
            },
            "Brand mark slot",
        ),
        (
            "logo.wordmark",
            AssetTokenValue::Logo {
                logo_id: "wordmark".to_owned(),
                variant: Some("wordmark".to_owned()),
            },
            "Wordmark logo slot",
        ),
        (
            "asset.illustration.primary",
            AssetTokenValue::Asset {
                asset_id: AssetId::from("asset_platform_illustration_primary"),
            },
            "Primary illustration placeholder",
        ),
        (
            "asset.texture.subtle",
            AssetTokenValue::Asset {
                asset_id: AssetId::from("asset_platform_texture_subtle"),
            },
            "Subtle texture placeholder",
        ),
        (
            "asset.icon.primary",
            AssetTokenValue::Asset {
                asset_id: AssetId::from("asset_platform_icon_primary"),
            },
            "Primary icon placeholder",
        ),
    ] {
        brand_kit
            .tokens
            .assets
            .entry(path.to_owned())
            .or_insert_with(|| AssetToken {
                value: ModeValue {
                    default: value,
                    modes: BTreeMap::new(),
                },
                description: Some(description.to_owned()),
                provenance: Some(TokenProvenance {
                    source: "platform_default".to_owned(),
                    confidence: 0.8,
                }),
            });
    }
}

fn ensure_color(
    brand_kit: &mut BrandKit,
    path: &str,
    default: &str,
    dark: Option<&str>,
    high_contrast: Option<&str>,
    role: &str,
    description: &str,
) {
    let token = brand_kit
        .tokens
        .colors
        .entry(path.to_owned())
        .or_insert_with(|| ColorToken {
            value: ModeValue {
                default: ColorTokenValue::Hex {
                    value: default.to_owned(),
                },
                modes: BTreeMap::new(),
            },
            role: Some(role.to_owned()),
            description: Some(description.to_owned()),
            provenance: Some(TokenProvenance {
                source: "platform_default".to_owned(),
                confidence: 1.0,
            }),
        });
    if let Some(dark) = dark {
        token
            .value
            .modes
            .entry("theme.dark".to_owned())
            .or_insert_with(|| ColorTokenValue::Hex {
                value: dark.to_owned(),
            });
    }
    if let Some(high_contrast) = high_contrast {
        token
            .value
            .modes
            .entry("accessibility.high_contrast".to_owned())
            .or_insert_with(|| ColorTokenValue::Hex {
                value: high_contrast.to_owned(),
            });
    }
    token.role.get_or_insert_with(|| role.to_owned());
    token
        .description
        .get_or_insert_with(|| description.to_owned());
}

fn ensure_number(
    target: &mut BTreeMap<String, NumberToken>,
    path: &str,
    default: f64,
    unit: NumberUnit,
    mode: Option<(&str, f64)>,
    role: &str,
) {
    target.entry(path.to_owned()).or_insert_with(|| {
        let mut modes = BTreeMap::new();
        if let Some((mode_key, mode_value)) = mode {
            modes.insert(
                mode_key.to_owned(),
                NumberTokenValue::Number {
                    value: mode_value,
                    unit: unit.clone(),
                },
            );
        }
        NumberToken {
            value: ModeValue {
                default: NumberTokenValue::Number {
                    value: default,
                    unit,
                },
                modes,
            },
            role: Some(role.to_owned()),
            description: Some(format!("Platform default {role} token")),
            provenance: Some(TokenProvenance {
                source: "platform_default".to_owned(),
                confidence: 1.0,
            }),
        }
    });
}

struct TypographySpec<'a> {
    path: &'a str,
    size: f64,
    weight: u16,
    line_height: f64,
    letter_spacing: f64,
    color: &'a str,
    large_text_size: f64,
}

fn ensure_typography(brand_kit: &mut BrandKit, spec: TypographySpec<'_>) {
    brand_kit
        .tokens
        .typography
        .entry(spec.path.to_owned())
        .or_insert_with(|| {
            let mut modes = BTreeMap::new();
            modes.insert(
                "accessibility.large_text".to_owned(),
                TypographyTokenValue::Style {
                    font_family: "Inter".to_owned(),
                    font_size: spec.large_text_size,
                    font_weight: spec.weight,
                    line_height: Some((spec.line_height + 0.04).min(1.6)),
                    letter_spacing: Some(spec.letter_spacing),
                    color: Some(spec.color.to_owned()),
                    font_asset: Some("brand".to_owned()),
                },
            );
            TypographyToken {
                value: ModeValue {
                    default: TypographyTokenValue::Style {
                        font_family: "Inter".to_owned(),
                        font_size: spec.size,
                        font_weight: spec.weight,
                        line_height: Some(spec.line_height),
                        letter_spacing: Some(spec.letter_spacing),
                        color: Some(spec.color.to_owned()),
                        font_asset: Some("brand".to_owned()),
                    },
                    modes,
                },
                role: Some(
                    spec.path
                        .strip_prefix("type.")
                        .unwrap_or(spec.path)
                        .to_owned(),
                ),
                description: Some(format!("Platform default {} role", spec.path)),
                provenance: Some(TokenProvenance {
                    source: "platform_default".to_owned(),
                    confidence: 1.0,
                }),
            }
        });
}

fn token_role(path: &str) -> &str {
    path.split_once('.')
        .map(|(role, _)| role)
        .unwrap_or("semantic")
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum BrandSource {
    Manual {
        label: String,
        confidence: f64,
    },
    Website {
        url: String,
        captured_at: Option<String>,
        confidence: f64,
    },
    UploadedPdf {
        asset_id: AssetId,
        filename: String,
        confidence: f64,
    },
    StyleGuideImage {
        asset_id: AssetId,
        filename: String,
        confidence: f64,
    },
    LogoFile {
        asset_id: AssetId,
        filename: String,
        confidence: f64,
    },
    AgentExtract {
        model: String,
        confidence: f64,
    },
    DefaultSeed {
        reason: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandSeed {
    pub id: BrandKitId,
    #[serde(default = "default_brand_seed_version")]
    pub version: u32,
    pub name: String,
    pub primary_color: String,
    pub description: Option<String>,
    pub secondary_color: Option<String>,
    pub accent_color: Option<String>,
    pub neutral_color: Option<String>,
    #[serde(default)]
    pub preferred_fonts: Vec<String>,
    #[serde(default)]
    pub logo_refs: Vec<BrandSeedLogoRef>,
    #[serde(default)]
    pub tone_words: Vec<String>,
    pub website_url: Option<String>,
    #[serde(default)]
    pub style_guide_asset_ids: Vec<AssetId>,
    #[serde(default)]
    pub sources: Vec<BrandSource>,
    #[serde(default)]
    pub default_mode: BrandMode,
}

fn default_brand_seed_version() -> u32 {
    1
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandSeedLogoRef {
    pub logo_id: String,
    pub asset_id: AssetId,
    pub usage: LogoUsage,
    pub color_mode: LogoColorMode,
    pub variant: Option<String>,
    pub width: Option<f64>,
    pub height: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandGenerationReport {
    pub brand_kit: Option<BrandKit>,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
    #[serde(default)]
    pub missing_inputs: Vec<String>,
    pub confidence: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandKitAuthoringSummary {
    pub id: BrandKitId,
    pub version: u32,
    pub name: String,
    pub approval_status: BrandApprovalStatus,
    pub default_mode: BrandMode,
    pub mode_axes: BTreeMap<String, Vec<String>>,
    pub product_ready: bool,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
    pub tokens: BrandAuthoringTokenSummary,
    pub assets: BrandAuthoringAssetSummary,
    #[serde(default)]
    pub tone: Vec<String>,
    #[serde(default)]
    pub imagery: Vec<String>,
    #[serde(default)]
    pub iconography: Vec<String>,
    #[serde(default)]
    pub authoring_rules: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct BrandAuthoringTokenSummary {
    #[serde(default)]
    pub surface_tokens: Vec<String>,
    #[serde(default)]
    pub text_tokens: Vec<String>,
    #[serde(default)]
    pub border_tokens: Vec<String>,
    #[serde(default)]
    pub focus_tokens: Vec<String>,
    #[serde(default)]
    pub typography_tokens: Vec<String>,
    #[serde(default)]
    pub spacing_tokens: Vec<String>,
    #[serde(default)]
    pub radius_tokens: Vec<String>,
    #[serde(default)]
    pub stroke_width_tokens: Vec<String>,
    #[serde(default)]
    pub opacity_tokens: Vec<String>,
    #[serde(default)]
    pub asset_tokens: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct BrandAuthoringAssetSummary {
    #[serde(default)]
    pub font_families: Vec<String>,
    #[serde(default)]
    pub logo_tokens: Vec<String>,
    #[serde(default)]
    pub image_asset_tokens: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandProvenance {
    pub created_by: String,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub confidence: f64,
    #[serde(default)]
    pub notes: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandModeSpec {
    #[serde(default = "default_mode_axes")]
    pub axes: BTreeMap<String, Vec<String>>,
    #[serde(default = "default_mode_values")]
    pub defaults: BTreeMap<String, String>,
}

impl Default for BrandModeSpec {
    fn default() -> Self {
        Self {
            axes: default_mode_axes(),
            defaults: default_mode_values(),
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct BrandMode {
    #[serde(default)]
    pub values: BTreeMap<String, String>,
}

impl BrandMode {
    fn selector_keys(&self) -> Vec<String> {
        self.values
            .iter()
            .map(|(axis, value)| format!("{axis}.{value}"))
            .collect()
    }
}

fn default_mode_axes() -> BTreeMap<String, Vec<String>> {
    BTreeMap::from([
        (
            "accessibility".to_owned(),
            vec![
                "standard".to_owned(),
                "high_contrast".to_owned(),
                "large_text".to_owned(),
            ],
        ),
        (
            "density".to_owned(),
            vec!["comfortable".to_owned(), "compact".to_owned()],
        ),
        (
            "medium".to_owned(),
            vec!["digital".to_owned(), "print".to_owned()],
        ),
        (
            "theme".to_owned(),
            vec!["light".to_owned(), "dark".to_owned()],
        ),
    ])
}

fn default_mode_values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("accessibility".to_owned(), "standard".to_owned()),
        ("density".to_owned(), "comfortable".to_owned()),
        ("medium".to_owned(), "digital".to_owned()),
        ("theme".to_owned(), "light".to_owned()),
    ])
}

/// Validate requested context without changing canonical mode precedence or token fallback.
pub fn validate_requested_brand_mode(kit: &BrandKit, mode: &BrandMode) -> Vec<Diagnostic> {
    let implicit_axes = default_mode_axes();
    mode.values.iter().filter_map(|(axis, value)| {
        // Canonical preflight supplies the normalized scene medium even for
        // legacy kits that omit this axis. Only its built-in values are implicit;
        // an explicitly declared axis and every other requested axis stay strict.
        let supported = kit.modes.axes.get(axis).or_else(|| {
            if axis == "medium" { implicit_axes.get(axis) } else { None }
        }).is_some_and(|values| values.contains(value));
        if supported {
            None
        } else {
            Some(Diagnostic::error(Phase::Brand, "EDITOR_RENDER_MODE_UNSUPPORTED",
                format!("Brand Kit {}@{} does not declare mode {axis}.{value}", kit.id, kit.version),
                Some(DiagnosticSubject::Document)))
        }
    }).collect()
}

fn effective_mode(brand_kit: &BrandKit, requested: BrandMode) -> BrandMode {
    let mut values = brand_kit.modes.defaults.clone();
    for (axis, value) in requested.values {
        values.insert(axis, value);
    }
    BrandMode { values }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TokenCatalog {
    #[serde(default)]
    pub colors: BTreeMap<String, ColorToken>,
    #[serde(default)]
    pub typography: BTreeMap<String, TypographyToken>,
    #[serde(default)]
    pub numbers: BTreeMap<String, NumberToken>,
    #[serde(default)]
    pub spacing: BTreeMap<String, NumberToken>,
    #[serde(default)]
    pub radii: BTreeMap<String, NumberToken>,
    #[serde(default)]
    pub stroke_widths: BTreeMap<String, NumberToken>,
    #[serde(default)]
    pub opacity: BTreeMap<String, NumberToken>,
    #[serde(default)]
    pub shadows: BTreeMap<String, ShadowToken>,
    #[serde(default)]
    pub effects: BTreeMap<String, EffectToken>,
    #[serde(default)]
    pub assets: BTreeMap<String, AssetToken>,
    #[serde(default)]
    pub aliases: BTreeMap<String, TokenAlias>,
    /// Measured style values the typed groups cannot hold (Wave 2 A9): keywords (case, cursor,
    /// decoration, border style…), durations, easings, transforms, keyframes, animation and reveal
    /// entries, and button icons. Minted by ingestion only; omitted when empty, so every kit without
    /// them serializes exactly as before.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub styles: BTreeMap<String, StyleToken>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(bound(
    serialize = "T: Serialize",
    deserialize = "T: serde::de::DeserializeOwned"
))]
pub struct ModeValue<T> {
    pub default: T,
    #[serde(default)]
    pub modes: BTreeMap<String, T>,
}

impl<T: Clone> ModeValue<T> {
    fn value_for_mode(&self, mode: &BrandMode) -> T {
        let mut value = self.default.clone();
        for key in mode.selector_keys() {
            if let Some(mode_value) = self.modes.get(&key) {
                value = mode_value.clone();
            }
        }
        value
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ColorToken {
    pub value: ModeValue<ColorTokenValue>,
    pub role: Option<String>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ColorTokenValue {
    Hex { value: String },
    Oklch { l: f64, c: f64, h: f64, alpha: f64 },
    Alias { token: String },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NumberToken {
    pub value: ModeValue<NumberTokenValue>,
    pub role: Option<String>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NumberTokenValue {
    Number { value: f64, unit: NumberUnit },
    Alias { token: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NumberUnit {
    Unitless,
    Px,
    Mm,
    Percent,
    Ratio,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TypographyToken {
    pub value: ModeValue<TypographyTokenValue>,
    pub role: Option<String>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum TypographyTokenValue {
    Style {
        font_family: String,
        font_size: f64,
        font_weight: u16,
        line_height: Option<f64>,
        letter_spacing: Option<f64>,
        color: Option<String>,
        font_asset: Option<String>,
    },
    Alias {
        token: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ShadowToken {
    pub value: ModeValue<ShadowValue>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ShadowValue {
    pub x: f64,
    pub y: f64,
    pub blur: f64,
    pub spread: f64,
    pub color: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EffectToken {
    pub value: ModeValue<EffectValue>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EffectValue {
    Shadow { token: String },
    Blur { radius: f64 },
    BackdropBlur { radius: f64 },
    Alias { token: String },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetToken {
    pub value: ModeValue<AssetTokenValue>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AssetTokenValue {
    Asset {
        asset_id: AssetId,
    },
    Logo {
        logo_id: String,
        variant: Option<String>,
    },
    Font {
        font_id: String,
    },
    Alias {
        token: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TokenAlias {
    pub token: String,
    pub description: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TokenProvenance {
    pub source: String,
    pub confidence: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct StyleToken {
    pub value: ModeValue<StyleTokenValue>,
    pub description: Option<String>,
    pub provenance: Option<TokenProvenance>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct KeyframeStep {
    pub offset: f64,
    #[serde(default)]
    pub declarations: BTreeMap<String, String>,
}

/// One measured style value. Entries that combine others (`Animation`, `Reveal`) name them, the
/// way an effect names its shadow token.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StyleTokenValue {
    Keyword {
        property: String,
        value: String,
    },
    Duration {
        ms: f64,
    },
    Easing {
        function: String,
    },
    Transform {
        value: String,
    },
    Keyframes {
        frames: Vec<KeyframeStep>,
    },
    Animation {
        keyframes: String,
        duration: String,
        easing: String,
        #[serde(default)]
        delay: Option<String>,
        iterations: String,
        direction: String,
        fill_mode: String,
    },
    Reveal {
        #[serde(default)]
        from_opacity: Option<String>,
        #[serde(default)]
        from_transform: Option<String>,
        duration: String,
        easing: String,
    },
    Glyph {
        text: String,
    },
    Svg {
        markup: String,
        width: f64,
        height: f64,
    },
    Alias {
        token: String,
    },
}

/// The CSS properties a keyword token may carry. Each value is a plain keyword list
/// (`uppercase`, `pointer`, `underline`), never free CSS; `box-shadow` only ever as `none`
/// (a state that removes the rest shadow).
const STYLE_KEYWORD_PROPERTIES: &[&str] = &[
    "text-transform",
    "text-decoration-line",
    "text-decoration-thickness",
    "text-underline-offset",
    "cursor",
    "border-style",
    "outline-style",
    "transition-property",
    "filter",
    "box-shadow",
];
/// What a measured keyframe may animate: compositing and paint properties only.
const KEYFRAME_PROPERTIES: &[&str] = &[
    "opacity",
    "transform",
    "translate",
    "scale",
    "rotate",
    "filter",
    "color",
    "background-color",
    "border-color",
    "box-shadow",
    "background-position",
];
const ANIMATION_DIRECTIONS: &[&str] = &["normal", "reverse", "alternate", "alternate-reverse"];
const ANIMATION_FILL_MODES: &[&str] = &["none", "forwards", "backwards", "both"];
const MAX_STYLE_TEXT: usize = 400;
const MAX_KEYFRAME_STEPS: usize = 32;
const MAX_KEYFRAME_DECLARATIONS: usize = 12;
const MAX_ICON_SVG_BYTES: usize = 4096;

fn style_text_ok(value: &str, max: usize) -> bool {
    let lower = value.to_ascii_lowercase();
    !value.trim().is_empty()
        && value.len() <= max
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b" ,.()%#+-/".contains(&byte))
        && !lower.contains("url(")
        && !lower.contains("var(")
        && !lower.contains("expression")
}

fn style_keyword_ok(property: &str, value: &str) -> bool {
    STYLE_KEYWORD_PROPERTIES.contains(&property)
        && style_text_ok(value, 200)
        && (property != "box-shadow" || value == "none")
}

fn easing_ok(function: &str) -> bool {
    matches!(
        function,
        "linear" | "ease" | "ease-in" | "ease-out" | "ease-in-out" | "step-start" | "step-end"
    ) || ((function.starts_with("cubic-bezier(")
        || function.starts_with("steps(")
        || function.starts_with("linear("))
        && function.ends_with(')')
        && style_text_ok(function, MAX_STYLE_TEXT))
}

fn transform_ok(value: &str) -> bool {
    if value == "none" {
        return true;
    }
    let inner = value
        .strip_prefix("matrix(")
        .or_else(|| value.strip_prefix("matrix3d("))
        .and_then(|rest| rest.strip_suffix(')'));
    match inner {
        Some(args) => {
            !args.is_empty()
                && args.len() <= MAX_STYLE_TEXT
                && args
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || b" ,.-e".contains(&byte))
        }
        None => false,
    }
}

fn keyframes_ok(frames: &[KeyframeStep]) -> bool {
    (2..=MAX_KEYFRAME_STEPS).contains(&frames.len())
        && frames.iter().all(|frame| {
            finite_in_range(frame.offset, 0.0, 100.0)
                && !frame.declarations.is_empty()
                && frame.declarations.len() <= MAX_KEYFRAME_DECLARATIONS
                && frame.declarations.iter().all(|(property, value)| {
                    KEYFRAME_PROPERTIES.contains(&property.as_str()) && style_text_ok(value, 200)
                })
        })
}

fn glyph_ok(text: &str) -> bool {
    let count = text.chars().count();
    (1..=4).contains(&count) && !text.chars().any(|c| c.is_control() || "<>&\"'".contains(c))
}

fn has_event_attribute(lower: &str) -> bool {
    lower.match_indices(" on").any(|(index, _)| {
        let rest = &lower[index + 3..];
        let name = rest
            .bytes()
            .take_while(|byte| byte.is_ascii_alphabetic())
            .count();
        name > 0 && rest[name..].trim_start().starts_with('=')
    })
}

fn icon_svg_ok(markup: &str) -> bool {
    let lower = markup.to_ascii_lowercase();
    let trimmed = lower.trim();
    markup.len() <= MAX_ICON_SVG_BYTES
        && trimmed.starts_with("<svg")
        && trimmed.ends_with("</svg>")
        && ![
            "<script",
            "javascript:",
            "url(",
            "href",
            "<foreignobject",
            "<!",
            "<?",
            "<style",
            "<use",
            "<image",
            "<a ",
            "<a>",
        ]
        .iter()
        .any(|bad| lower.contains(bad))
        && !has_event_attribute(&lower)
}

fn iterations_ok(value: &str) -> bool {
    value == "infinite"
        || value
            .parse::<f64>()
            .map(|count| count.is_finite() && count > 0.0 && count <= 1000.0)
            .unwrap_or(false)
}

fn validate_style_tokens(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    let styles = &brand_kit.tokens.styles;
    let is_kind = |name: &str, want: fn(&StyleTokenValue) -> bool| {
        styles
            .get(name)
            .map(|token| want(&token.value.default))
            .unwrap_or(false)
    };
    let is_duration = |value: &StyleTokenValue| matches!(value, StyleTokenValue::Duration { .. });
    let is_easing = |value: &StyleTokenValue| matches!(value, StyleTokenValue::Easing { .. });
    for (path, token) in styles {
        validate_mode_keys(path, &token.value.modes, &brand_kit.modes, diagnostics);
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            let problem: Option<(&str, &str)> = match value {
                StyleTokenValue::Keyword { property, value }
                    if !style_keyword_ok(property, value) =>
                {
                    Some(("LUMB0260", "an invalid keyword"))
                }
                StyleTokenValue::Duration { ms } if !finite_in_range(*ms, 0.0, 60_000.0) => {
                    Some(("LUMB0261", "an invalid duration"))
                }
                StyleTokenValue::Easing { function } if !easing_ok(function) => {
                    Some(("LUMB0262", "an invalid easing"))
                }
                StyleTokenValue::Transform { value } if !transform_ok(value) => {
                    Some(("LUMB0263", "an invalid transform"))
                }
                StyleTokenValue::Keyframes { frames } if !keyframes_ok(frames) => {
                    Some(("LUMB0264", "invalid keyframes"))
                }
                StyleTokenValue::Glyph { text } if !glyph_ok(text) => {
                    Some(("LUMB0265", "an invalid icon glyph"))
                }
                StyleTokenValue::Svg {
                    markup,
                    width,
                    height,
                } if !icon_svg_ok(markup)
                    || !finite_in_range(*width, 1.0, 256.0)
                    || !finite_in_range(*height, 1.0, 256.0) =>
                {
                    Some(("LUMB0265", "an invalid icon svg"))
                }
                StyleTokenValue::Animation {
                    keyframes,
                    duration,
                    easing,
                    delay,
                    iterations,
                    direction,
                    fill_mode,
                } => {
                    let refs = is_kind(keyframes, |v| {
                        matches!(v, StyleTokenValue::Keyframes { .. })
                    }) && is_kind(duration, is_duration)
                        && is_kind(easing, is_easing)
                        && delay
                            .as_deref()
                            .map_or(true, |name| is_kind(name, is_duration));
                    if !refs {
                        Some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                    } else if !iterations_ok(iterations)
                        || !ANIMATION_DIRECTIONS.contains(&direction.as_str())
                        || !ANIMATION_FILL_MODES.contains(&fill_mode.as_str())
                    {
                        Some(("LUMB0264", "an invalid animation"))
                    } else {
                        None
                    }
                }
                StyleTokenValue::Reveal {
                    from_opacity,
                    from_transform,
                    duration,
                    easing,
                } => {
                    let refs = from_opacity
                        .as_deref()
                        .map_or(true, |name| brand_kit.tokens.opacity.contains_key(name))
                        && from_transform.as_deref().map_or(true, |name| {
                            is_kind(name, |v| matches!(v, StyleTokenValue::Transform { .. }))
                        })
                        && is_kind(duration, is_duration)
                        && is_kind(easing, is_easing);
                    (!refs).then_some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                }
                StyleTokenValue::Alias { token } if !styles.contains_key(token) => {
                    Some(("LUMB0266", "a reference to a missing or wrong-kind token"))
                }
                _ => None,
            };
            if let Some((code, what)) = problem {
                diagnostics.push(brand_error(
                    code,
                    format!("style token {} has {}", path, what),
                ));
            }
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct BrandAssets {
    #[serde(default)]
    pub fonts: BTreeMap<String, FontAsset>,
    #[serde(default)]
    pub logos: BTreeMap<String, LogoAsset>,
    #[serde(default)]
    pub images: BTreeMap<String, BrandAsset>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FontAsset {
    pub family: String,
    pub source: AssetSource,
    #[serde(default)]
    pub faces: Vec<FontFace>,
    #[serde(default)]
    pub fallback_stack: Vec<String>,
    #[serde(default)]
    pub scripts: Vec<String>,
    pub license: FontLicense,
    pub provenance: Option<TokenProvenance>,
    /// Measured font metrics extracted at ingestion (units-per-em ratios:
    /// x-height, cap-height, average char width, vertical metrics). Producers
    /// write it, downstream consumers (perceptual size normalization, copy-fit
    /// estimation, evals) read it; the engine itself never interprets it —
    /// the field exists so the block survives the typed validation round trip.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metrics: Option<serde_json::Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FontFace {
    pub weight: u16,
    pub style: FontStyle,
    pub asset_id: Option<AssetId>,
    pub source_url: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FontStyle {
    Normal,
    Italic,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FontLicense {
    pub name: String,
    pub embeddable: bool,
    pub subsettable: bool,
    pub source_url: Option<String>,
    #[serde(default)]
    pub restrictions: Vec<String>,
    /// WHY this font may be embedded, when the answer is not the license `name`
    /// itself (clone-fidelity D-F2). A font ingested from a workspace's own
    /// brand material is embeddable on this platform under the platform's Terms
    /// of Use — `basis: "platform-terms"` — while `name` keeps saying only what
    /// the source declared, which is usually nothing verifiable. The engine
    /// never interprets it: producers write it, the publish gate reads it, and
    /// the field exists so the answer survives the typed round trip instead of
    /// being smuggled through a restrictions line.
    ///
    /// Absent on every kit written before F1.5, and `skip_serializing_if` keeps
    /// those kits' bytes identical.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub basis: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LogoAsset {
    #[serde(default)]
    pub variants: Vec<LogoVariant>,
    pub usage: LogoUsage,
    pub min_size: Option<f64>,
    pub clearspace: Option<f64>,
    #[serde(default)]
    pub allowed_backgrounds: Vec<String>,
    pub license: Option<AssetLicense>,
    pub provenance: Option<TokenProvenance>,
    // Human/AI-authored library metadata (brandkit ingestion v1 slice 3).
    // skip_serializing_if keeps pre-slice-3 kit serializations byte-identical.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Design-usage guidance ("use on dark backgrounds…") — its own field so
    /// downstream caps on `description` can never eat it (imagery slice 1).
    /// Distinct from `usage: LogoUsage`, which is the slot kind.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage_note: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LogoVariant {
    pub name: String,
    pub asset_id: AssetId,
    pub color_mode: LogoColorMode,
    pub width: Option<f64>,
    pub height: Option<f64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LogoColorMode {
    FullColor,
    OneColor,
    Reversed,
    Dark,
    Light,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LogoUsage {
    Primary,
    Secondary,
    Mark,
    Wordmark,
    Partner,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandAsset {
    pub asset_id: AssetId,
    pub role: String,
    pub mime_type: Option<String>,
    pub license: Option<AssetLicense>,
    pub provenance: Option<TokenProvenance>,
    #[serde(default)]
    pub style_tags: Vec<String>,
    #[serde(default)]
    pub allowed_contexts: Vec<String>,
    #[serde(default)]
    pub preferred_color_tokens: Vec<String>,
    pub recolor_allowed: Option<bool>,
    pub crop_allowed: Option<bool>,
    // Human/AI-authored library metadata (brandkit ingestion v1 slice 3).
    // skip_serializing_if keeps pre-slice-3 kit serializations byte-identical.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Design-usage guidance ("use on dark backgrounds…") — its own field so
    /// downstream caps on `description` can never eat it (imagery slice 1).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage_note: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandConstraints {
    pub allow_gradients: bool,
    #[serde(default)]
    pub tone: Vec<String>,
    #[serde(default)]
    pub imagery: Vec<String>,
    #[serde(default)]
    pub iconography: Vec<String>,
    #[serde(default)]
    pub accessibility_notes: Vec<String>,
    #[serde(default)]
    pub print_constraints: Vec<String>,
    #[serde(default)]
    pub contrast_pairs: Vec<ContrastPair>,
}

impl Default for BrandConstraints {
    fn default() -> Self {
        Self {
            allow_gradients: true,
            tone: Vec::new(),
            imagery: Vec::new(),
            iconography: Vec::new(),
            accessibility_notes: Vec::new(),
            print_constraints: Vec::new(),
            contrast_pairs: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ContrastPair {
    pub foreground: String,
    pub background: String,
    pub min_ratio: f64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrandValidationLevel {
    Structural,
    ProductReady,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrandGovernanceStrictness {
    Advisory,
    Strict,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrandCompatibilityStatus {
    Compatible,
    Warning,
    MigrationRequired,
    Incompatible,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TokenChangeKind {
    Added,
    Removed,
    TypeChanged,
    RoleChanged,
    ModeCoverageChanged,
    AssetRemoved,
    FontLicenseChanged,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct TokenChange {
    pub path: String,
    pub kind: TokenChangeKind,
    pub from_kind: Option<String>,
    pub to_kind: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandCompatibilityReport {
    pub from: BrandKitRef,
    pub to: BrandKitRef,
    pub status: BrandCompatibilityStatus,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
    #[serde(default)]
    pub token_changes: Vec<TokenChange>,
    #[serde(default)]
    pub suggested_operations: Vec<Operation>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TokenStrictness {
    None,
    Explicit,
    DesignSystem,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TokenFallbackPolicy {
    DiagnosticsOnly,
    UseFallbacks,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TokenResolutionOptions {
    pub mode: BrandMode,
    pub strictness: TokenStrictness,
    pub fallback: TokenFallbackPolicy,
}

impl Default for TokenResolutionOptions {
    fn default() -> Self {
        Self {
            mode: BrandMode::default(),
            strictness: TokenStrictness::None,
            fallback: TokenFallbackPolicy::DiagnosticsOnly,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TokenResolutionReport {
    pub scene: Scene,
    pub operations: Vec<Operation>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SceneTokenReference {
    pub token: String,
    pub field: String,
    pub subject: DiagnosticSubject,
}

pub fn validate_brand_kit(brand_kit: &BrandKit) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    if brand_kit.version == 0 {
        diagnostics.push(brand_error(
            "LUMB0001",
            format!("brand kit {} must use a positive version", brand_kit.id),
        ));
    }

    if brand_kit.name.trim().is_empty() {
        diagnostics.push(brand_error("LUMB0002", "brand kit name cannot be empty"));
    }

    validate_modes(&brand_kit.modes, &mut diagnostics);
    validate_token_keys(&brand_kit.tokens, &mut diagnostics);
    validate_token_values(brand_kit, &mut diagnostics);
    validate_style_tokens(brand_kit, &mut diagnostics);
    validate_assets(&brand_kit.assets, &mut diagnostics);
    validate_contrast_pairs(brand_kit, &mut diagnostics);

    diagnostics
}

pub fn validate_brand_kit_product_ready(brand_kit: &BrandKit) -> Vec<Diagnostic> {
    let mut diagnostics = validate_brand_kit(brand_kit);
    validate_product_ready_modes(brand_kit, &mut diagnostics);
    validate_required_token_coverage(brand_kit, &mut diagnostics);
    validate_required_mode_coverage(brand_kit, &mut diagnostics);
    validate_product_typography_roles(brand_kit, &mut diagnostics);
    diagnostics
}

const UNBOUND_SPACING_HINT: &str = "Check existing spacing tokens in the active mode before binding: a binding changes resolved geometry, and a padding token sets every edge to one value. Intentional literals may remain under advisory governance. Under strict governance, use an equivalent existing token or review the intended geometry change; do not substitute an unrelated token.";

pub fn validate_scene_brand_governance(
    scene: &Scene,
    brand_kit: &BrandKit,
    strictness: BrandGovernanceStrictness,
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let severity_is_error = strictness == BrandGovernanceStrictness::Strict;
    let print_medium = scene_is_print_medium(scene);

    for page in scene.pages.values() {
        for fill in &page.background {
            if paint_is_bare(&fill.paint) {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0804",
                        format!(
                            "page {} background fill {} uses a raw paint outside the Brand Kit",
                            page.id, fill.id
                        ),
                        Some(DiagnosticSubject::Page(page.id.clone())),
                    )
                    .with_hint(format!(
                        "Use fill(${}) or another Brand Kit surface token.",
                        suggested_token(&brand_kit.tokens.colors, "surface.page", "surface.")
                    )),
                );
            }
        }
    }

    for node in scene.nodes.values() {
        let subject = Some(DiagnosticSubject::Node(node.id.clone()));
        for fill in &node.fills {
            if paint_is_bare(&fill.paint) {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0804",
                        format!(
                            "node {} fill {} uses a raw paint outside the Brand Kit",
                            node.id, fill.id
                        ),
                        subject.clone(),
                    )
                    .with_hint(format!(
                        "Use fill(${}) for visual surfaces or text fills.",
                        suggested_fill_token(brand_kit, node)
                    )),
                );
            }
        }
        // A6b D8: a span's raw (non-token) fill is un-governed exactly like a
        // node fill — same LUMB0804 semantics.
        if let NodeKind::Text(text) = &node.kind {
            for (index, span) in text.spans.iter().enumerate() {
                if let Some(paint) = &span.fill {
                    if paint_is_bare(paint) {
                        diagnostics.push(
                            brand_governance_diag(
                                severity_is_error,
                                "LUMB0804",
                                format!(
                                    "node {} span {} fill uses a raw paint outside the Brand Kit",
                                    node.id, index
                                ),
                                subject.clone(),
                            )
                            .with_hint(format!(
                                "Use span(fill(${})) for the accent color.",
                                suggested_fill_token(brand_kit, node)
                            )),
                        );
                    }
                }
            }
        }
        for stroke in &node.strokes {
            if paint_is_bare(&stroke.paint) || stroke.width_token.is_none() {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0806",
                        format!(
                            "node {} stroke {} is not fully governed by Brand Kit tokens",
                            node.id, stroke.id
                        ),
                        subject.clone(),
                    )
                    .with_hint(format!(
                        "Use stroke(${},{}) with Brand Kit border and stroke-width tokens.",
                        suggested_token(&brand_kit.tokens.colors, "border.default", "border."),
                        suggested_token(
                            &brand_kit.tokens.stroke_widths,
                            "stroke.width.default",
                            "stroke.width.",
                        )
                    )),
                );
            }
        }
        if node.corner.token.is_none()
            && [
                node.corner.top_left,
                node.corner.top_right,
                node.corner.bottom_right,
                node.corner.bottom_left,
            ]
            .iter()
            .any(|value| *value != 0.0)
        {
            diagnostics.push(
                brand_governance_diag(
                    severity_is_error,
                    "LUMB0806",
                    format!(
                        "node {} corner radius uses raw values outside the Brand Kit",
                        node.id
                    ),
                    subject.clone(),
                )
                .with_hint(format!(
                    "Use rd(${}) or another Brand Kit radius token.",
                    suggested_token(&brand_kit.tokens.radii, "radius.card", "radius.")
                )),
            );
        }
        if node.opacity_token.is_none() && node.opacity != 1.0 {
            diagnostics.push(
                brand_governance_diag(
                    severity_is_error,
                    "LUMB0806",
                    format!(
                        "node {} opacity uses a raw value outside the Brand Kit",
                        node.id
                    ),
                    subject.clone(),
                )
                .with_hint(format!(
                    "Use o(${}) or another Brand Kit opacity token.",
                    suggested_token(&brand_kit.tokens.opacity, "opacity.subtle", "opacity.")
                )),
            );
        }
        if print_medium {
            if let Some((source, opacity)) = effective_node_opacity_for_governance(
                brand_kit,
                node,
                subject.clone(),
                &mut diagnostics,
            ) {
                if opacity < 1.0 {
                    diagnostics.push(
                        Diagnostic::error(
                            Phase::Brand,
                            "LUMB0811",
                            format!(
                                "node {} uses transparency {} in print medium",
                                node.id, source
                            ),
                            subject.clone(),
                        )
                        .with_hint(
                            "Use opacity.emphasis or an opaque style for print/direct-mail artifacts.",
                        ),
                    );
                }
            }
        }
        if let Some(layout) = &node.layout {
            if layout.gap_token.is_none() && layout.gap != 0.0 {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0806",
                        format!(
                            "node {} layout gap has no Brand Kit spacing binding",
                            node.id
                        ),
                        subject.clone(),
                    )
                    .with_hint(UNBOUND_SPACING_HINT),
                );
            }
            if layout.padding_token.is_none() && layout.padding.iter().any(|value| *value != 0.0) {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0806",
                        format!(
                            "node {} layout padding has no Brand Kit spacing binding",
                            node.id
                        ),
                        subject.clone(),
                    )
                    .with_hint(UNBOUND_SPACING_HINT),
                );
            }
        }
        if let NodeKind::Text(text) = &node.kind {
            if text.style_token.is_none() {
                diagnostics.push(
                    brand_governance_diag(
                        severity_is_error,
                        "LUMB0805",
                        format!(
                            "node {} text has no Brand Kit typography role binding",
                            node.id
                        ),
                        subject.clone(),
                    )
                    .with_hint(
                        "A missing binding does not establish an invalid visual treatment. Before binding, check that the active-mode role preserves the intended family, weight, size, leading, tracking and color; a size token alone does not make a whole role equivalent. Intentional literals may remain under advisory governance. Under strict governance, use an equivalent existing role or review the intended typography change; do not substitute an unrelated role.",
                    ),
                );
            }
            validate_text_contrast_for_governance(
                scene,
                brand_kit,
                node,
                text,
                severity_is_error,
                subject.clone(),
                &mut diagnostics,
            );
        }
        if let NodeKind::Image(image) = &node.kind {
            if let Some((logo_id, logo)) = logo_for_asset(brand_kit, &image.asset_id) {
                if let Some(min_size) = logo.min_size {
                    if let Some((width, height)) = node_render_size(node) {
                        let shortest_side = width.min(height);
                        if shortest_side < min_size {
                            diagnostics.push(
                                brand_governance_diag(
                                    severity_is_error,
                                    "LUMB0809",
                                    format!(
                                        "node {} renders logo {} at {:.1}px on its shortest side, below the Brand Kit minimum {:.1}px",
                                        node.id, logo_id, shortest_side, min_size
                                    ),
                                    subject.clone(),
                                )
                                .with_hint(format!(
                                    "Increase this logo to at least {:.1}px on its shortest side or choose a smaller approved logo variant.",
                                    min_size
                                )),
                            );
                        }
                    }
                }
                if !logo.allowed_backgrounds.is_empty() {
                    let background = nearest_brand_background_token(scene, &node.id)
                        .unwrap_or_else(|| "surface.page".to_owned());
                    if !logo
                        .allowed_backgrounds
                        .iter()
                        .any(|allowed| allowed == &background)
                    {
                        diagnostics.push(
                            brand_governance_diag(
                                severity_is_error,
                                "LUMB0810",
                                format!(
                                    "node {} places logo {} on disallowed Brand Kit background {}",
                                    node.id, logo_id, background
                                ),
                                subject.clone(),
                            )
                            .with_hint(format!(
                                "Use an allowed background token for this logo: {}.",
                                logo.allowed_backgrounds.join(", ")
                            )),
                        );
                    }
                }
            }
        }
    }

    if brand_kit.approval_status == BrandApprovalStatus::Deprecated {
        diagnostics.push(brand_governance_diag(
            severity_is_error,
            "LUMB0820",
            format!("brand kit {} is deprecated", brand_kit.id),
            None,
        ));
    }

    diagnostics
}

fn node_render_size(node: &Node) -> Option<(f64, f64)> {
    if let Some(computed) = &node.computed {
        let width = computed.render_bounds.width;
        let height = computed.render_bounds.height;
        if width.is_finite() && height.is_finite() && width > 0.0 && height > 0.0 {
            return Some((width, height));
        }
    }

    let width = fixed_dimension_value(&node.size.width);
    let height = fixed_dimension_value(&node.size.height);
    match (width, height) {
        (Some(width), Some(height))
            if width.is_finite() && height.is_finite() && width > 0.0 && height > 0.0 =>
        {
            Some((width, height))
        }
        _ => None,
    }
}

fn fixed_dimension_value(dimension: &Dimension) -> Option<f64> {
    match dimension {
        Dimension::Fixed(value) => Some(*value),
        _ => None,
    }
}

fn suggested_fill_token(brand_kit: &BrandKit, node: &Node) -> String {
    if matches!(node.kind, NodeKind::Text(_)) {
        suggested_token(&brand_kit.tokens.colors, "text.primary", "text.")
    } else {
        suggested_token(&brand_kit.tokens.colors, "surface.card", "surface.")
    }
}

fn suggested_token<T>(tokens: &BTreeMap<String, T>, preferred: &str, prefix: &str) -> String {
    if tokens.contains_key(preferred) {
        return preferred.to_owned();
    }
    tokens
        .keys()
        .find(|token| token.starts_with(prefix))
        .cloned()
        .unwrap_or_else(|| preferred.to_owned())
}

pub fn compare_brand_kit_compatibility(from: &BrandKit, to: &BrandKit) -> BrandCompatibilityReport {
    let mut diagnostics = Vec::new();
    let mut token_changes = Vec::new();

    collect_removed_tokens(
        "color",
        from.tokens.colors.keys(),
        to.tokens.colors.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "typography",
        from.tokens.typography.keys(),
        to.tokens.typography.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "spacing",
        from.tokens.spacing.keys(),
        to.tokens.spacing.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "radius",
        from.tokens.radii.keys(),
        to.tokens.radii.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "stroke width",
        from.tokens.stroke_widths.keys(),
        to.tokens.stroke_widths.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "opacity",
        from.tokens.opacity.keys(),
        to.tokens.opacity.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "asset token",
        from.tokens.assets.keys(),
        to.tokens.assets.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "font asset",
        from.assets.fonts.keys(),
        to.assets.fonts.keys(),
        &mut token_changes,
        &mut diagnostics,
    );
    collect_removed_tokens(
        "logo asset",
        from.assets.logos.keys(),
        to.assets.logos.keys(),
        &mut token_changes,
        &mut diagnostics,
    );

    for (path, from_token) in &from.tokens.typography {
        let Some(to_token) = to.tokens.typography.get(path) else {
            continue;
        };
        if std::mem::discriminant(&from_token.value.default)
            != std::mem::discriminant(&to_token.value.default)
        {
            token_changes.push(TokenChange {
                path: path.clone(),
                kind: TokenChangeKind::TypeChanged,
                from_kind: Some(token_value_kind(&from_token.value.default)),
                to_kind: Some(token_value_kind(&to_token.value.default)),
            });
            diagnostics.push(brand_error(
                "LUMB0815",
                format!("typography token {} changed value type", path),
            ));
        }
    }

    for axis in from.modes.axes.keys() {
        let Some(to_values) = to.modes.axes.get(axis) else {
            diagnostics.push(brand_error(
                "LUMB0813",
                format!("brand kit {} removed mode axis {}", to.id, axis),
            ));
            token_changes.push(TokenChange {
                path: format!("mode.{axis}"),
                kind: TokenChangeKind::ModeCoverageChanged,
                from_kind: Some("mode_axis".to_owned()),
                to_kind: None,
            });
            continue;
        };

        let to_values = to_values
            .iter()
            .cloned()
            .collect::<std::collections::BTreeSet<_>>();
        if let Some(from_values) = from.modes.axes.get(axis) {
            for value in from_values {
                if !to_values.contains(value) {
                    diagnostics.push(brand_error(
                        "LUMB0813",
                        format!("brand kit {} removed mode value {}.{}", to.id, axis, value),
                    ));
                    token_changes.push(TokenChange {
                        path: format!("mode.{axis}.{value}"),
                        kind: TokenChangeKind::ModeCoverageChanged,
                        from_kind: Some("mode_value".to_owned()),
                        to_kind: None,
                    });
                }
            }
        }
    }

    let status = if diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == crate::DiagnosticSeverity::Error)
    {
        BrandCompatibilityStatus::MigrationRequired
    } else if diagnostics.is_empty() && token_changes.is_empty() {
        BrandCompatibilityStatus::Compatible
    } else {
        BrandCompatibilityStatus::Warning
    };

    BrandCompatibilityReport {
        from: from.brand_ref(),
        to: to.brand_ref(),
        status,
        diagnostics,
        token_changes,
        suggested_operations: Vec::new(),
    }
}

pub fn validate_scene_tokens(
    scene: &Scene,
    brand_kit: &BrandKit,
    options: &TokenResolutionOptions,
) -> Vec<Diagnostic> {
    let report = resolve_scene_tokens(scene, brand_kit, options);
    report.diagnostics
}

pub fn scene_has_token_references(scene: &Scene) -> bool {
    !collect_scene_token_references(scene).is_empty()
}

pub fn summarize_brand_kit_for_authoring(brand_kit: &BrandKit) -> BrandKitAuthoringSummary {
    let diagnostics = validate_brand_kit_product_ready(brand_kit);
    let product_ready = !has_error(&diagnostics);

    BrandKitAuthoringSummary {
        id: brand_kit.id.clone(),
        version: brand_kit.version,
        name: brand_kit.name.clone(),
        approval_status: brand_kit.approval_status.clone(),
        default_mode: BrandMode {
            values: brand_kit.modes.defaults.clone(),
        },
        mode_axes: brand_kit.modes.axes.clone(),
        product_ready,
        diagnostics,
        tokens: BrandAuthoringTokenSummary {
            surface_tokens: token_subset(&brand_kit.tokens.colors, |token| {
                token.starts_with("surface.")
            }),
            text_tokens: token_subset(&brand_kit.tokens.colors, |token| token.starts_with("text.")),
            border_tokens: token_subset(&brand_kit.tokens.colors, |token| {
                token.starts_with("border.")
            }),
            focus_tokens: token_subset(&brand_kit.tokens.colors, |token| token.starts_with("focus.")),
            typography_tokens: token_subset(&brand_kit.tokens.typography, |token| {
                token.starts_with("type.")
            }),
            spacing_tokens: token_subset(&brand_kit.tokens.spacing, |token| {
                token.starts_with("space.")
            }),
            radius_tokens: token_subset(&brand_kit.tokens.radii, |token| {
                token.starts_with("radius.")
            }),
            stroke_width_tokens: token_subset(&brand_kit.tokens.stroke_widths, |token| {
                token.starts_with("stroke.width.")
            }),
            opacity_tokens: token_subset(&brand_kit.tokens.opacity, |token| {
                token.starts_with("opacity.")
            }),
            asset_tokens: token_subset(&brand_kit.tokens.assets, |_| true),
        },
        assets: BrandAuthoringAssetSummary {
            font_families: brand_kit
                .assets
                .fonts
                .values()
                .map(|font| font.family.clone())
                .collect(),
            logo_tokens: token_subset(&brand_kit.tokens.assets, |token| {
                token.starts_with("logo.")
            }),
            image_asset_tokens: token_subset(&brand_kit.tokens.assets, |token| {
                token.starts_with("asset.")
            }),
        },
        tone: brand_kit.constraints.tone.clone(),
        imagery: brand_kit.constraints.imagery.clone(),
        iconography: brand_kit.constraints.iconography.clone(),
        authoring_rules: vec![
            "Use semantic tokens instead of raw colors, sizes, spacing, radii, stroke widths, or opacity when the scene is brand-governed.".to_owned(),
            "Use style($type.*) for text roles and keep raw font declarations for explicit overrides only.".to_owned(),
            "Use fill($surface.*), stroke($border.*,$stroke.width.*), g($space.*), pad($space.*), and rd($radius.*).".to_owned(),
            "Use logo.* and asset.* tokens for brand assets when possible; do not invent token names.".to_owned(),
        ],
    }
}

pub fn collect_scene_token_references(scene: &Scene) -> Vec<SceneTokenReference> {
    let mut references = Vec::new();

    for page in scene.pages.values() {
        for fill in &page.background {
            collect_paint_token_references(
                &mut references,
                DiagnosticSubject::Page(page.id.clone()),
                format!("page.background {}", fill.id),
                &fill.paint,
            );
        }
    }

    for node in scene.nodes.values() {
        let subject = DiagnosticSubject::Node(node.id.clone());

        collect_dimension_token_reference(
            &mut references,
            subject.clone(),
            "size.width",
            &node.size.width,
        );
        collect_dimension_token_reference(
            &mut references,
            subject.clone(),
            "size.height",
            &node.size.height,
        );

        for fill in &node.fills {
            collect_paint_token_references(
                &mut references,
                subject.clone(),
                format!("fill {} paint", fill.id),
                &fill.paint,
            );
        }

        for stroke in &node.strokes {
            collect_paint_token_references(
                &mut references,
                subject.clone(),
                format!("stroke {} paint", stroke.id),
                &stroke.paint,
            );
            if let Some(token) = &stroke.width_token {
                push_scene_token_reference(
                    &mut references,
                    subject.clone(),
                    format!("stroke {} width", stroke.id),
                    token,
                );
            }
        }

        if let Some(token) = &node.corner.token {
            push_scene_token_reference(&mut references, subject.clone(), "corner radius", token);
        }
        if let Some(token) = &node.opacity_token {
            push_scene_token_reference(&mut references, subject.clone(), "opacity", token);
        }

        if let Some(layout) = &node.layout {
            if let Some(token) = &layout.gap_token {
                push_scene_token_reference(&mut references, subject.clone(), "layout gap", token);
            }
            if let Some(token) = &layout.padding_token {
                push_scene_token_reference(
                    &mut references,
                    subject.clone(),
                    "layout padding",
                    token,
                );
            }
        }

        if let NodeKind::Text(text) = &node.kind {
            if let Some(token) = &text.style_token {
                push_scene_token_reference(&mut references, subject.clone(), "text style", token);
            }
            if looks_like_token_ref(&text.font_family) {
                push_scene_token_reference(
                    &mut references,
                    subject.clone(),
                    "text font family",
                    &text.font_family,
                );
            }
            // A6b D8: a span's token fill is a scene token reference, exactly
            // like a node fill's.
            for (index, span) in text.spans.iter().enumerate() {
                if let Some(paint) = &span.fill {
                    collect_paint_token_references(
                        &mut references,
                        subject.clone(),
                        format!("span {index} fill paint"),
                        paint,
                    );
                }
            }
        }
    }

    references
}

fn collect_dimension_token_reference(
    references: &mut Vec<SceneTokenReference>,
    subject: DiagnosticSubject,
    field: impl Into<String>,
    dimension: &Dimension,
) {
    if let Dimension::Token { token } = dimension {
        push_scene_token_reference(references, subject, field, token);
    }
}

fn collect_paint_token_references(
    references: &mut Vec<SceneTokenReference>,
    subject: DiagnosticSubject,
    field: impl Into<String>,
    paint: &Paint,
) {
    let field = field.into();
    match paint {
        Paint::Token { token } => {
            push_scene_token_reference(references, subject, field, token);
        }
        Paint::Solid { color } => {
            collect_color_token_reference(references, subject, field, color);
        }
        Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
            for stop in stops {
                collect_color_token_reference(
                    references,
                    subject.clone(),
                    format!("{} stop {}", field, stop.position),
                    &stop.color,
                );
            }
        }
    }
}

fn collect_color_token_reference(
    references: &mut Vec<SceneTokenReference>,
    subject: DiagnosticSubject,
    field: impl Into<String>,
    color: &Color,
) {
    if let Color::Token { token } = color {
        push_scene_token_reference(references, subject, field, token);
    }
}

fn push_scene_token_reference(
    references: &mut Vec<SceneTokenReference>,
    subject: DiagnosticSubject,
    field: impl Into<String>,
    token: impl AsRef<str>,
) {
    let reference = SceneTokenReference {
        token: token.as_ref().to_owned(),
        field: field.into(),
        subject,
    };
    if !references.contains(&reference) {
        references.push(reference);
    }
}

pub fn resolve_scene_tokens(
    scene: &Scene,
    brand_kit: &BrandKit,
    options: &TokenResolutionOptions,
) -> TokenResolutionReport {
    let mut resolver = TokenResolver::new(brand_kit, options.clone());
    resolver.validate_scene_brand_ref(scene);
    resolver.diagnostics.extend(validate_brand_kit(brand_kit));
    if options.strictness != TokenStrictness::None {
        resolver.validate_strict_scene(scene);
    }

    if has_error(&resolver.diagnostics) {
        return TokenResolutionReport {
            scene: scene.clone(),
            operations: Vec::new(),
            diagnostics: resolver.diagnostics,
        };
    }

    let mut resolved = scene.clone();

    for page in resolved.pages.values_mut() {
        for fill in &mut page.background {
            resolver.resolve_fill(fill, Some(DiagnosticSubject::Page(page.id.clone())));
        }
    }

    resolver.node_surface = build_node_surface_map(&resolved);

    for node in resolved.nodes.values_mut() {
        resolver.resolve_node(node);
    }

    let operations = resolution_operations(scene, &resolved);

    TokenResolutionReport {
        scene: resolved,
        operations,
        diagnostics: resolver.diagnostics,
    }
}

/// Resolve only a targeted text's source typography for a checked edit. This
/// reuses the renderer's resolver without baking unrelated scene nodes.
pub(crate) fn resolve_text_for_edit(
    scene: &Scene,
    node_id: &NodeId,
    text: &TextNode,
    brand_kit: &BrandKit,
    options: &TokenResolutionOptions,
) -> Result<TextNode, Vec<Diagnostic>> {
    let options = crate::preflight::token_options_for_scene_medium(scene, options);
    let mut resolver = TokenResolver::new(brand_kit, options);
    if scene.meta.brand_kit.is_some() {
        resolver.validate_scene_brand_ref(scene);
    }
    resolver.diagnostics.extend(validate_brand_kit(brand_kit));
    if has_error(&resolver.diagnostics) {
        return Err(resolver.diagnostics);
    }
    let mut node = Node::new(node_id.clone(), NodeKind::Text(text.clone()));
    resolver.resolve_node(&mut node);
    let NodeKind::Text(resolved) = node.kind else {
        unreachable!()
    };
    if has_error(&resolver.diagnostics)
        || resolved.style_token.is_some()
        || resolved.font_size_token.is_some()
        || resolved.line_height_token.is_some()
        || resolved.letter_spacing_token.is_some()
    {
        return Err(resolver.diagnostics);
    }
    Ok(resolved)
}

pub fn compile_styles_brand_kit(
    source: &str,
    id: BrandKitId,
    version: u32,
    name: impl Into<String>,
) -> Result<BrandKit, Vec<Diagnostic>> {
    let mut kit = BrandKit {
        id,
        version,
        name: name.into(),
        description: Some("Compiled from .styles source".to_owned()),
        sources: vec![BrandSource::Manual {
            label: "Styles/default.styles".to_owned(),
            confidence: 1.0,
        }],
        provenance: None,
        approval_status: BrandApprovalStatus::GeneratedUnreviewed,
        compatibility_policy: BrandCompatibilityPolicy::default(),
        modes: BrandModeSpec::default(),
        tokens: TokenCatalog::default(),
        assets: BrandAssets::default(),
        constraints: BrandConstraints::default(),
    };
    let mut diagnostics = Vec::new();

    for (line_index, raw_line) in source.lines().enumerate() {
        let Some(line) = strip_style_comment(raw_line) else {
            continue;
        };
        if line.is_empty() {
            continue;
        }

        if let Err(message) = compile_style_line(&line, &mut kit) {
            diagnostics.push(brand_error(
                "LUMB0701",
                format!("styles line {}: {}", line_index + 1, message),
            ));
        }
    }

    complete_compiled_styles_brand_kit(&mut kit);
    diagnostics.extend(validate_brand_kit(&kit));
    diagnostics.extend(validate_brand_kit_product_ready(&kit));
    if has_error(&diagnostics) {
        Err(diagnostics)
    } else {
        Ok(kit)
    }
}

fn complete_compiled_styles_brand_kit(brand_kit: &mut BrandKit) {
    brand_kit.compatibility_policy = BrandCompatibilityPolicy {
        allow_critical_mode_fallbacks: false,
        allow_unapproved_asset_placeholders: true,
        require_product_ready_tokens: true,
    };
    ensure_required_mode_axes(&mut brand_kit.modes);
    ensure_platform_color_tokens(brand_kit);
    ensure_platform_number_tokens(brand_kit);
    ensure_platform_typography_tokens(brand_kit);
    ensure_platform_asset_tokens(brand_kit);
}

pub fn generate_brand_kit(seed: &BrandSeed) -> BrandGenerationReport {
    let mut diagnostics = Vec::new();
    let mut missing_inputs = Vec::new();

    if seed.name.trim().is_empty() {
        diagnostics.push(brand_error("LUMB0900", "brand seed name cannot be empty"));
    }
    if seed.version == 0 {
        diagnostics.push(brand_error(
            "LUMB0901",
            format!("brand seed {} must use a positive version", seed.id),
        ));
    }
    if !valid_hex(&seed.primary_color) {
        diagnostics.push(brand_error(
            "LUMB0902",
            format!(
                "brand seed primary color {} must be #RRGGBB or #RRGGBBAA",
                seed.primary_color
            ),
        ));
    }

    if seed.preferred_fonts.is_empty() {
        missing_inputs.push("preferred_fonts".to_owned());
    }
    if seed.logo_refs.is_empty() {
        missing_inputs.push("logo_refs".to_owned());
    }
    if seed.website_url.is_none() && seed.style_guide_asset_ids.is_empty() {
        missing_inputs.push("website_or_style_guide".to_owned());
    }

    if has_error(&diagnostics) {
        return BrandGenerationReport {
            brand_kit: None,
            diagnostics,
            missing_inputs,
            confidence: 0.0,
        };
    }

    let mut modes = BrandModeSpec::default();
    ensure_required_mode_axes(&mut modes);
    for (axis, value) in &seed.default_mode.values {
        if modes
            .axes
            .get(axis)
            .is_some_and(|values| values.iter().any(|candidate| candidate == value))
        {
            modes.defaults.insert(axis.clone(), value.clone());
        } else {
            diagnostics.push(brand_warning(
                "LUMB0903",
                format!(
                    "brand seed requested unknown mode default {}.{}; default ignored",
                    axis, value
                ),
            ));
        }
    }

    let font_family = seed
        .preferred_fonts
        .iter()
        .find(|font| !font.trim().is_empty())
        .map(|font| font.trim().to_owned())
        .unwrap_or_else(|| "Inter".to_owned());

    let mut brand_kit = BrandKit {
        id: seed.id.clone(),
        version: seed.version,
        name: seed.name.trim().to_owned(),
        description: seed
            .description
            .clone()
            .or_else(|| Some("Generated from structured BrandSeed inputs".to_owned())),
        sources: generated_brand_sources(seed),
        provenance: Some(BrandProvenance {
            created_by: "lumen_brand_seed_generator".to_owned(),
            created_at: "generated".to_owned(),
            updated_at: None,
            confidence: 0.78,
            notes: generated_brand_notes(seed),
        }),
        approval_status: BrandApprovalStatus::GeneratedUnreviewed,
        compatibility_policy: BrandCompatibilityPolicy {
            allow_critical_mode_fallbacks: false,
            allow_unapproved_asset_placeholders: true,
            require_product_ready_tokens: true,
        },
        modes,
        tokens: TokenCatalog::default(),
        assets: BrandAssets {
            fonts: generated_font_assets(&font_family),
            logos: generated_logo_assets(seed),
            images: BTreeMap::new(),
        },
        constraints: BrandConstraints {
            allow_gradients: true,
            tone: seed.tone_words.clone(),
            imagery: vec![
                "Prefer brand-approved photography, illustration, or uploaded campaign assets."
                    .to_owned(),
            ],
            iconography: vec![
                "Use simple line or filled icons aligned to brand stroke width.".to_owned(),
            ],
            accessibility_notes: vec![
                "Maintain AA contrast for primary text.".to_owned(),
                "Use high-contrast mode before final export when required.".to_owned(),
            ],
            print_constraints: vec![
                "Use print medium mode for print/PDF exports.".to_owned(),
                "Avoid low-opacity text in print artifacts.".to_owned(),
            ],
            contrast_pairs: vec![
                ContrastPair {
                    foreground: "text.primary".to_owned(),
                    background: "surface.page".to_owned(),
                    min_ratio: 4.5,
                },
                ContrastPair {
                    foreground: "text.inverse".to_owned(),
                    background: "surface.brand".to_owned(),
                    min_ratio: 4.5,
                },
            ],
        },
    };

    if let Err(message) = insert_seed_color_ramp(
        &mut brand_kit,
        "palette.primary",
        &seed.primary_color,
        SeedRampKind::Brand,
    ) {
        diagnostics.push(brand_error("LUMB0904", message));
    }

    let neutral_seed = seed.neutral_color.as_deref().unwrap_or("#0F172A");
    if valid_hex(neutral_seed) {
        if let Err(message) = insert_seed_color_ramp(
            &mut brand_kit,
            "palette.neutral",
            neutral_seed,
            SeedRampKind::Neutral,
        ) {
            diagnostics.push(brand_error("LUMB0905", message));
        }
    } else {
        diagnostics.push(brand_warning(
            "LUMB0905",
            format!(
                "neutral color {} is invalid; using generated neutral fallback",
                neutral_seed
            ),
        ));
        let _ = insert_seed_color_ramp(
            &mut brand_kit,
            "palette.neutral",
            "#0F172A",
            SeedRampKind::Neutral,
        );
    }

    let secondary_seed = seed
        .secondary_color
        .as_deref()
        .filter(|value| valid_hex(value))
        .map(str::to_owned)
        .unwrap_or_else(|| derived_seed_hex(&seed.primary_color, 34.0, 0.54, 0.08));
    let accent_seed = seed
        .accent_color
        .as_deref()
        .filter(|value| valid_hex(value))
        .map(str::to_owned)
        .unwrap_or_else(|| derived_seed_hex(&seed.primary_color, 132.0, 0.68, 0.11));

    let _ = insert_seed_color_ramp(
        &mut brand_kit,
        "palette.secondary",
        &secondary_seed,
        SeedRampKind::Brand,
    );
    let _ = insert_seed_color_ramp(
        &mut brand_kit,
        "palette.accent",
        &accent_seed,
        SeedRampKind::Brand,
    );

    insert_generated_semantic_colors(&mut brand_kit);
    ensure_platform_number_tokens(&mut brand_kit);
    ensure_platform_typography_tokens(&mut brand_kit);
    apply_generated_font_to_typography(&mut brand_kit, &font_family);
    insert_seed_logo_tokens(&mut brand_kit, seed);
    ensure_platform_asset_tokens(&mut brand_kit);

    diagnostics.extend(validate_brand_kit_product_ready(&brand_kit));
    let confidence = generated_brand_confidence(seed, &diagnostics);

    BrandGenerationReport {
        brand_kit: if has_error(&diagnostics) {
            None
        } else {
            Some(brand_kit)
        },
        diagnostics,
        missing_inputs,
        confidence,
    }
}

#[derive(Clone, Copy)]
enum SeedRampKind {
    Brand,
    Neutral,
}

fn generated_brand_sources(seed: &BrandSeed) -> Vec<BrandSource> {
    let mut sources = seed.sources.clone();
    if let Some(url) = &seed.website_url {
        sources.push(BrandSource::Website {
            url: url.clone(),
            captured_at: None,
            confidence: 0.55,
        });
    }
    for asset_id in &seed.style_guide_asset_ids {
        sources.push(BrandSource::UploadedPdf {
            asset_id: asset_id.clone(),
            filename: "style-guide".to_owned(),
            confidence: 0.55,
        });
    }
    for logo_ref in &seed.logo_refs {
        sources.push(BrandSource::LogoFile {
            asset_id: logo_ref.asset_id.clone(),
            filename: logo_ref.logo_id.clone(),
            confidence: 0.7,
        });
    }
    if sources.is_empty() {
        sources.push(BrandSource::DefaultSeed {
            reason: "Generated from seed color and platform defaults".to_owned(),
        });
    }
    sources
}

fn generated_brand_notes(seed: &BrandSeed) -> Vec<String> {
    let mut notes = vec![
        "Generated Brand Kits require human review before approval.".to_owned(),
        "Color ramps are deterministic OKLCH-derived approximations.".to_owned(),
    ];
    if seed.website_url.is_some() {
        notes.push(
            "Website URL was preserved as source context; no crawler ran in lumen-core.".to_owned(),
        );
    }
    if !seed.style_guide_asset_ids.is_empty() {
        notes.push("Style guide asset refs were preserved as source context; parsing belongs to API/agent ingestion.".to_owned());
    }
    notes
}

fn generated_font_assets(font_family: &str) -> BTreeMap<String, FontAsset> {
    BTreeMap::from([(
        "brand".to_owned(),
        FontAsset {
            family: font_family.to_owned(),
            source: AssetSource::System {
                family: font_family.to_owned(),
            },
            faces: vec![
                FontFace {
                    weight: 400,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
                FontFace {
                    weight: 500,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
                FontFace {
                    weight: 700,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
                FontFace {
                    weight: 800,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
            ],
            fallback_stack: vec!["Arial".to_owned(), "sans-serif".to_owned()],
            scripts: vec!["latin".to_owned()],
            license: FontLicense {
                name: "generated_system_font".to_owned(),
                embeddable: true,
                subsettable: true,
                source_url: None,
                restrictions: Vec::new(),
                basis: None,
            },
            provenance: Some(TokenProvenance {
                source: "brand_seed".to_owned(),
                confidence: 0.7,
            }),
            metrics: None,
        },
    )])
}

fn generated_logo_assets(seed: &BrandSeed) -> BTreeMap<String, LogoAsset> {
    let mut logos = BTreeMap::new();
    for logo_ref in &seed.logo_refs {
        logos
            .entry(logo_ref.logo_id.clone())
            .and_modify(|logo: &mut LogoAsset| {
                logo.variants.push(LogoVariant {
                    name: logo_ref
                        .variant
                        .clone()
                        .unwrap_or_else(|| "default".to_owned()),
                    asset_id: logo_ref.asset_id.clone(),
                    color_mode: logo_ref.color_mode.clone(),
                    width: logo_ref.width,
                    height: logo_ref.height,
                });
            })
            .or_insert_with(|| LogoAsset {
                variants: vec![LogoVariant {
                    name: logo_ref
                        .variant
                        .clone()
                        .unwrap_or_else(|| "default".to_owned()),
                    asset_id: logo_ref.asset_id.clone(),
                    color_mode: logo_ref.color_mode.clone(),
                    width: logo_ref.width,
                    height: logo_ref.height,
                }],
                usage: logo_ref.usage.clone(),
                min_size: Some(48.0),
                clearspace: Some(16.0),
                allowed_backgrounds: vec![
                    "surface.page".to_owned(),
                    "surface.card".to_owned(),
                    "surface.brand".to_owned(),
                ],
                license: None,
                provenance: Some(TokenProvenance {
                    source: "brand_seed".to_owned(),
                    confidence: 0.75,
                }),
                title: None,
                description: None,
                usage_note: None,
            });
    }
    logos
}

fn insert_seed_color_ramp(
    brand_kit: &mut BrandKit,
    prefix: &str,
    seed_hex: &str,
    kind: SeedRampKind,
) -> Result<(), String> {
    if !valid_hex(seed_hex) {
        return Err(format!(
            "color seed {seed_hex} must be #RRGGBB or #RRGGBBAA"
        ));
    }
    let Some((_, chroma, hue)) = hex_to_oklch(seed_hex) else {
        return Err(format!("could not convert color seed {seed_hex}"));
    };
    let chroma = match kind {
        SeedRampKind::Brand => chroma.clamp(0.04, 0.14),
        SeedRampKind::Neutral => chroma.min(0.025),
    };
    for (stop, lightness) in COLOR_STOPS {
        brand_kit.tokens.colors.insert(
            format!("{prefix}.{stop}"),
            ColorToken {
                value: ModeValue {
                    default: ColorTokenValue::Oklch {
                        l: lightness,
                        c: chroma,
                        h: hue,
                        alpha: 1.0,
                    },
                    modes: BTreeMap::new(),
                },
                role: Some("palette".to_owned()),
                description: Some(format!("Generated {prefix} color ramp stop {stop}")),
                provenance: Some(TokenProvenance {
                    source: "brand_seed".to_owned(),
                    confidence: 0.78,
                }),
            },
        );
    }
    Ok(())
}

fn derived_seed_hex(primary_hex: &str, hue_delta: f64, lightness: f64, chroma: f64) -> String {
    let (_, _, hue) = hex_to_oklch(primary_hex).unwrap_or((0.54, 0.08, 220.0));
    oklch_to_hex(lightness, chroma, (hue + hue_delta).rem_euclid(360.0), 1.0)
}

fn insert_generated_semantic_colors(brand_kit: &mut BrandKit) {
    insert_color_alias(
        brand_kit,
        "surface.canvas",
        "palette.neutral.50",
        Some("palette.neutral.950"),
        Some("#FFFFFF"),
        "surface",
        "Generated main canvas surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.page",
        "palette.neutral.50",
        Some("palette.neutral.900"),
        Some("#FFFFFF"),
        "surface",
        "Generated artifact page surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.card",
        "palette.neutral.100",
        Some("palette.neutral.800"),
        Some("#FFFFFF"),
        "surface",
        "Generated card surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.elevated",
        "palette.neutral.50",
        Some("palette.neutral.700"),
        Some("#FFFFFF"),
        "surface",
        "Generated elevated surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.brand",
        "palette.primary.800",
        Some("palette.primary.300"),
        Some("#000000"),
        "surface",
        "Generated branded surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.brand.subtle",
        "palette.primary.100",
        Some("palette.primary.900"),
        Some("#FFFFFF"),
        "surface",
        "Generated subtle branded surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.accent",
        "palette.accent.500",
        Some("palette.accent.300"),
        Some("#000000"),
        "surface",
        "Generated accent surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.muted",
        "palette.neutral.200",
        Some("palette.neutral.800"),
        Some("#FFFFFF"),
        "surface",
        "Generated muted surface",
    );
    insert_color_alias(
        brand_kit,
        "surface.inverse",
        "palette.neutral.950",
        Some("palette.neutral.50"),
        Some("#000000"),
        "surface",
        "Generated inverse surface",
    );
    insert_color_alias(
        brand_kit,
        "text.primary",
        "palette.neutral.950",
        Some("palette.neutral.50"),
        Some("#000000"),
        "text",
        "Generated primary text",
    );
    insert_color_alias(
        brand_kit,
        "text.secondary",
        "palette.neutral.700",
        Some("palette.neutral.200"),
        Some("#000000"),
        "text",
        "Generated secondary text",
    );
    insert_color_alias(
        brand_kit,
        "text.muted",
        "palette.neutral.600",
        Some("palette.neutral.300"),
        Some("#000000"),
        "text",
        "Generated muted text",
    );
    insert_color_alias(
        brand_kit,
        "text.inverse",
        "palette.neutral.50",
        Some("palette.neutral.950"),
        Some("#FFFFFF"),
        "text",
        "Generated inverse text",
    );
    insert_color_alias(
        brand_kit,
        "text.brand",
        "palette.primary.800",
        Some("palette.primary.300"),
        Some("#000000"),
        "text",
        "Generated brand text",
    );
    insert_color_alias(
        brand_kit,
        "text.accent",
        "palette.accent.700",
        Some("palette.accent.300"),
        Some("#000000"),
        "text",
        "Generated accent text",
    );
    insert_color_alias(
        brand_kit,
        "border.subtle",
        "palette.neutral.200",
        Some("palette.neutral.800"),
        Some("#000000"),
        "border",
        "Generated subtle border",
    );
    insert_color_alias(
        brand_kit,
        "border.default",
        "palette.neutral.300",
        Some("palette.neutral.600"),
        Some("#000000"),
        "border",
        "Generated default border",
    );
    insert_color_alias(
        brand_kit,
        "border.strong",
        "palette.neutral.600",
        Some("palette.neutral.300"),
        Some("#000000"),
        "border",
        "Generated strong border",
    );
    insert_color_alias(
        brand_kit,
        "border.brand",
        "palette.primary.700",
        Some("palette.primary.300"),
        Some("#000000"),
        "border",
        "Generated brand border",
    );
    insert_color_alias(
        brand_kit,
        "focus.ring",
        "palette.accent.500",
        Some("palette.accent.300"),
        Some("#000000"),
        "focus",
        "Generated focus ring",
    );
}

fn insert_color_alias(
    brand_kit: &mut BrandKit,
    path: &str,
    default: &str,
    dark: Option<&str>,
    high_contrast: Option<&str>,
    role: &str,
    description: &str,
) {
    let mut modes = BTreeMap::new();
    if let Some(dark) = dark {
        modes.insert(
            "theme.dark".to_owned(),
            ColorTokenValue::Alias {
                token: dark.to_owned(),
            },
        );
    }
    if let Some(high_contrast) = high_contrast {
        modes.insert(
            "accessibility.high_contrast".to_owned(),
            if high_contrast.starts_with('#') {
                ColorTokenValue::Hex {
                    value: high_contrast.to_owned(),
                }
            } else {
                ColorTokenValue::Alias {
                    token: high_contrast.to_owned(),
                }
            },
        );
    }
    brand_kit.tokens.colors.insert(
        path.to_owned(),
        ColorToken {
            value: ModeValue {
                default: ColorTokenValue::Alias {
                    token: default.to_owned(),
                },
                modes,
            },
            role: Some(role.to_owned()),
            description: Some(description.to_owned()),
            provenance: Some(TokenProvenance {
                source: "brand_seed".to_owned(),
                confidence: 0.78,
            }),
        },
    );
}

fn apply_generated_font_to_typography(brand_kit: &mut BrandKit, font_family: &str) {
    for token in brand_kit.tokens.typography.values_mut() {
        update_typography_font(&mut token.value.default, font_family);
        for value in token.value.modes.values_mut() {
            update_typography_font(value, font_family);
        }
    }
}

fn update_typography_font(value: &mut TypographyTokenValue, font_family: &str) {
    if let TypographyTokenValue::Style {
        font_family: current_family,
        font_asset,
        ..
    } = value
    {
        *current_family = font_family.to_owned();
        *font_asset = Some("brand".to_owned());
    }
}

fn insert_seed_logo_tokens(brand_kit: &mut BrandKit, seed: &BrandSeed) {
    let primary = seed
        .logo_refs
        .iter()
        .find(|logo| logo.usage == LogoUsage::Primary)
        .or_else(|| seed.logo_refs.first());
    if let Some(primary) = primary {
        let logo_id = primary.logo_id.clone();
        let default_variant = primary
            .variant
            .clone()
            .unwrap_or_else(|| "default".to_owned());
        for (path, variant) in [
            ("logo.primary", default_variant.as_str()),
            ("logo.reversed", "reversed"),
            ("logo.mark", "mark"),
            ("logo.wordmark", "wordmark"),
        ] {
            brand_kit.tokens.assets.insert(
                path.to_owned(),
                AssetToken {
                    value: ModeValue {
                        default: AssetTokenValue::Logo {
                            logo_id: logo_id.clone(),
                            variant: Some(variant.to_owned()),
                        },
                        modes: BTreeMap::new(),
                    },
                    description: Some(format!("Generated {path} logo token")),
                    provenance: Some(TokenProvenance {
                        source: "brand_seed".to_owned(),
                        confidence: 0.74,
                    }),
                },
            );
        }
    }
}

fn generated_brand_confidence(seed: &BrandSeed, diagnostics: &[Diagnostic]) -> f64 {
    let mut confidence: f64 = 0.64;
    if !seed.logo_refs.is_empty() {
        confidence += 0.08;
    }
    if !seed.preferred_fonts.is_empty() {
        confidence += 0.06;
    }
    if seed.website_url.is_some() {
        confidence += 0.04;
    }
    if !seed.style_guide_asset_ids.is_empty() {
        confidence += 0.08;
    }
    if diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == crate::DiagnosticSeverity::Warning)
    {
        confidence -= 0.08;
    }
    if has_error(diagnostics) {
        confidence = 0.0;
    }
    confidence.clamp(0.0, 0.95)
}

#[derive(Clone, Copy)]
enum NumberDomain {
    Dimension,
    LayoutSpacing,
    Radius,
    StrokeWidth,
    Opacity,
    FontSize,
}

struct TokenResolver<'a> {
    brand_kit: &'a BrandKit,
    options: TokenResolutionOptions,
    diagnostics: Vec<Diagnostic>,
    resolving_colors: Vec<String>,
    resolving_numbers: Vec<String>,
    resolving_typography: Vec<String>,
    resolving_assets: Vec<String>,
    // Maps each node to the surface color it sits ON (nearest ancestor's solid
    // fill, else the page background). Used to keep resolved text colors legible
    // against their background — see `contrast_corrected_text_color`.
    node_surface: BTreeMap<NodeId, Color>,
}

impl<'a> TokenResolver<'a> {
    fn new(brand_kit: &'a BrandKit, options: TokenResolutionOptions) -> Self {
        let mut options = options;
        options.mode = effective_mode(brand_kit, options.mode);
        Self {
            brand_kit,
            options,
            diagnostics: Vec::new(),
            resolving_colors: Vec::new(),
            resolving_numbers: Vec::new(),
            resolving_typography: Vec::new(),
            resolving_assets: Vec::new(),
            node_surface: BTreeMap::new(),
        }
    }

    fn validate_scene_brand_ref(&mut self, scene: &Scene) {
        match &scene.meta.brand_kit {
            Some(BrandKitRef { id, version })
                if id == &self.brand_kit.id && *version == self.brand_kit.version => {}
            Some(BrandKitRef { id, version }) => self.diagnostics.push(brand_error(
                "LUMB0101",
                format!(
                    "scene references brand kit {} version {}, but resolver was given {} version {}",
                    id, version, self.brand_kit.id, self.brand_kit.version
                ),
            )),
            None => self.diagnostics.push(brand_error(
                "LUMB0100",
                format!(
                    "scene must reference brand kit {} version {} before token resolution",
                    self.brand_kit.id, self.brand_kit.version
                ),
            )),
        }
    }

    fn validate_strict_scene(&mut self, scene: &Scene) {
        for page in scene.pages.values() {
            for fill in &page.background {
                if paint_is_bare(&fill.paint) {
                    self.diagnostics.push(brand_error(
                        "LUMB0500",
                        format!(
                            "page {} background uses a bare paint in token-strict mode",
                            page.id
                        ),
                    ));
                }
            }
        }

        for node in scene.nodes.values() {
            for fill in &node.fills {
                if paint_is_bare(&fill.paint) {
                    self.diagnostics.push(node_brand_error(
                        "LUMB0500",
                        format!(
                            "node {} fill {} uses a bare paint in token-strict mode",
                            node.id, fill.id
                        ),
                        &node.id,
                    ));
                }
            }

            // A6b D8: a span's bare fill is un-governed in strict mode too.
            if let NodeKind::Text(text) = &node.kind {
                for (index, span) in text.spans.iter().enumerate() {
                    if let Some(paint) = &span.fill {
                        if paint_is_bare(paint) {
                            self.diagnostics.push(node_brand_error(
                                "LUMB0500",
                                format!(
                                    "node {} span {} fill uses a bare paint in token-strict mode",
                                    node.id, index
                                ),
                                &node.id,
                            ));
                        }
                    }
                }
            }

            for stroke in &node.strokes {
                if paint_is_bare(&stroke.paint) || stroke.width_token.is_none() {
                    self.diagnostics.push(node_brand_error(
                        "LUMB0501",
                        format!(
                            "node {} stroke {} is not fully tokenized in token-strict mode",
                            node.id, stroke.id
                        ),
                        &node.id,
                    ));
                }
            }

            if node.corner.token.is_none()
                && (node.corner.top_left != 0.0
                    || node.corner.top_right != 0.0
                    || node.corner.bottom_right != 0.0
                    || node.corner.bottom_left != 0.0)
            {
                self.diagnostics.push(node_brand_error(
                    "LUMB0502",
                    format!(
                        "node {} corner radius uses bare values in token-strict mode",
                        node.id
                    ),
                    &node.id,
                ));
            }

            if node.opacity_token.is_none() && node.opacity != 1.0 {
                self.diagnostics.push(node_brand_error(
                    "LUMB0503",
                    format!(
                        "node {} opacity uses a bare value in token-strict mode",
                        node.id
                    ),
                    &node.id,
                ));
            }

            if matches!(node.kind, NodeKind::Text(_)) {
                let NodeKind::Text(text) = &node.kind else {
                    unreachable!("guarded by matches");
                };
                if text.style_token.is_none() {
                    self.diagnostics.push(node_brand_error(
                        "LUMB0506",
                        format!(
                            "node {} text style uses bare typography in token-strict mode",
                            node.id
                        ),
                        &node.id,
                    ));
                }
            }

            if let Some(layout) = &node.layout {
                if layout.gap_token.is_none() && layout.gap != 0.0 {
                    self.diagnostics.push(node_brand_error(
                        "LUMB0504",
                        format!(
                            "node {} layout gap uses a bare value in token-strict mode",
                            node.id
                        ),
                        &node.id,
                    ));
                }
                if layout.padding_token.is_none()
                    && layout.padding.iter().any(|value| *value != 0.0)
                {
                    self.diagnostics.push(node_brand_error(
                        "LUMB0505",
                        format!(
                            "node {} layout padding uses bare values in token-strict mode",
                            node.id
                        ),
                        &node.id,
                    ));
                }
            }
        }
    }

    /// If a resolved text `color` contrasts poorly with the node's effective
    /// surface, return whichever canonical text color (`text.primary` /
    /// `text.inverse`) contrasts best with that surface; otherwise return `color`
    /// unchanged, so deliberate, readable colors (accents, brand text) are kept.
    fn contrast_corrected_text_color(
        &mut self,
        node_id: &NodeId,
        color: Color,
        subject: Option<DiagnosticSubject>,
    ) -> Color {
        // WCAG AA threshold for large text; below this a text/surface pair reads as
        // unreadable-to-invisible (white-on-white is 1.0).
        const MIN_TEXT_CONTRAST: f64 = 3.0;
        let Some(surface) = self.node_surface.get(node_id).cloned() else {
            return color;
        };
        let Some(surface_rgb) = self.color_to_rgb_resolved(&surface, subject.clone()) else {
            return color;
        };
        let Some(text_rgb) = color_to_rgb(&color) else {
            return color;
        };
        let mut best = color;
        let mut best_contrast = contrast_ratio(text_rgb, surface_rgb);
        if best_contrast >= MIN_TEXT_CONTRAST {
            return best;
        }
        for candidate in ["text.primary", "text.inverse"] {
            if let Some(candidate_color) = self.resolve_color_ref(candidate, subject.clone()) {
                if let Some(candidate_rgb) = color_to_rgb(&candidate_color) {
                    let ratio = contrast_ratio(candidate_rgb, surface_rgb);
                    if ratio > best_contrast {
                        best = candidate_color;
                        best_contrast = ratio;
                    }
                }
            }
        }
        best
    }

    /// Resolve a surface color (literal hex or token) to RGB for contrast math.
    fn color_to_rgb_resolved(
        &mut self,
        color: &Color,
        subject: Option<DiagnosticSubject>,
    ) -> Option<(f64, f64, f64)> {
        match color {
            Color::Token { token } => self
                .resolve_color_ref(token, subject)
                .and_then(|resolved| color_to_rgb(&resolved)),
            other => color_to_rgb(other),
        }
    }

    fn resolve_node(&mut self, node: &mut Node) {
        let subject = Some(DiagnosticSubject::Node(node.id.clone()));

        for fill in &mut node.fills {
            self.resolve_fill(fill, subject.clone());
        }

        for stroke in &mut node.strokes {
            self.resolve_paint(&mut stroke.paint, subject.clone());
            if let Some(token) = stroke.width_token.clone() {
                if let Some(width) =
                    self.resolve_number_ref(&token, NumberDomain::StrokeWidth, subject.clone())
                {
                    stroke.width = width;
                    stroke.width_token = None;
                }
            }
        }

        if let Dimension::Token { token } = &node.size.width {
            if let Some(width) =
                self.resolve_number_ref(token, NumberDomain::Dimension, subject.clone())
            {
                node.size.width = Dimension::Fixed(width);
            }
        }
        if let Dimension::Token { token } = &node.size.height {
            if let Some(height) =
                self.resolve_number_ref(token, NumberDomain::Dimension, subject.clone())
            {
                node.size.height = Dimension::Fixed(height);
            }
        }

        if let Some(token) = node.corner.token.clone() {
            if let Some(radius) =
                self.resolve_number_ref(&token, NumberDomain::Radius, subject.clone())
            {
                node.corner = CornerRadii {
                    top_left: radius,
                    top_right: radius,
                    bottom_right: radius,
                    bottom_left: radius,
                    token: None,
                };
            }
        }

        if let Some(token) = node.opacity_token.clone() {
            if let Some(opacity) =
                self.resolve_number_ref(&token, NumberDomain::Opacity, subject.clone())
            {
                node.opacity = opacity.clamp(0.0, 1.0);
                node.opacity_token = None;
            }
        }

        if let Some(layout) = &mut node.layout {
            self.resolve_layout(layout, subject.clone());
        }

        if let NodeKind::Text(text) = &mut node.kind {
            // A6b D8: span fills resolve like node fills — a $token/solid-token
            // span fill becomes Solid (bindings consumed by design); an
            // unresolved span token keeps the loud sentinel path at raster.
            for span in &mut text.spans {
                if let Some(paint) = &mut span.fill {
                    self.resolve_paint(paint, subject.clone());
                }
            }
            if let Some(token) = text.line_height_token.clone() {
                if let Some(line_height) =
                    self.resolve_number_ref(&token, NumberDomain::Dimension, subject.clone())
                {
                    text.line_height = line_height;
                    text.line_height_token = None;
                }
            }
            if let Some(token) = text.letter_spacing_token.clone() {
                if let Some(letter_spacing) =
                    self.resolve_number_ref(&token, NumberDomain::LayoutSpacing, subject.clone())
                {
                    text.letter_spacing = letter_spacing;
                    text.letter_spacing_token = None;
                }
            }

            if let Some(style) = self.resolve_text_style(text, subject.clone()) {
                text.font_family = style.font_family;
                text.font_size = style.font_size;
                text.font_weight = style.font_weight;
                if let Some(line_height) = style.line_height {
                    text.line_height = line_height;
                    text.line_height_token = None;
                }
                if let Some(letter_spacing) = style.letter_spacing {
                    text.letter_spacing = letter_spacing;
                    text.letter_spacing_token = None;
                }
                text.style_token = None;

                // Fill precedence: a role's baked color is a DEFAULT for text
                // that carries no color of its own. An author who wrote an
                // explicit `fill(...)` on the text node — token or literal —
                // already had it materialized by the node-fill walk at the top
                // of `resolve_node`, and that choice WINS. Before this rule the
                // role clobbered `fills[0]` unconditionally, so authoring
                // `style($type.display) fill($text.inverse)` (white on a brand
                // ground) silently rendered the role's `text.primary` black.
                //
                // The honest signal for "the author wrote this fill" is the
                // fill id: every author fill is named by the DSL compiler
                // (`paint_{node}_fill_{n}`) or by the caller, while the only
                // fill this block ever synthesizes is `{node}_text_fill`. That
                // one stays role-owned, so a re-resolve (a rebound role over an
                // already-resolved scene) still updates its own fill in place
                // instead of freezing the previous role's color.
                let role_owned_fill_id = PaintId::from(format!("{}_text_fill", node.id.as_str()));
                let has_author_fill = node
                    .fills
                    .first()
                    .is_some_and(|fill| fill.id != role_owned_fill_id);

                if let Some(color_token) = style.color.filter(|_| !has_author_fill) {
                    if let Some(color) = self.resolve_color_ref(&color_token, subject.clone()) {
                        // P1.1: keep the resolved text color legible against the
                        // surface it sits on. A type role bakes in one color (e.g.
                        // type.headline -> text.inverse, white), which is invisible on
                        // the opposite surface (a white headline on a light page). If
                        // contrast is poor, flip to the better-contrasting default text
                        // color; otherwise the role's color is preserved.
                        let color =
                            self.contrast_corrected_text_color(&node.id, color, subject.clone());
                        let paint = Paint::Solid { color };
                        if let Some(fill) = node.fills.first_mut() {
                            fill.paint = paint;
                        } else {
                            node.fills.push(Fill {
                                id: role_owned_fill_id,
                                paint,
                            });
                        }
                    }
                }
            }

            // A size-step token (`$type.size.*`) overrides the role's default
            // size. Resolved AFTER the role above so the author's per-surface
            // size choice wins; the role still supplied weight / color /
            // line-height. Resolution is identity (no canvas coupling).
            if let Some(token) = text.font_size_token.clone() {
                if let Some(size) =
                    self.resolve_number_ref(&token, NumberDomain::FontSize, subject.clone())
                {
                    text.font_size = size;
                    text.font_size_token = None;
                }
            }
        }
    }

    fn resolve_layout(&mut self, layout: &mut AutoLayoutProps, subject: Option<DiagnosticSubject>) {
        if let Some(token) = layout.gap_token.clone() {
            if let Some(gap) =
                self.resolve_number_ref(&token, NumberDomain::LayoutSpacing, subject.clone())
            {
                layout.gap = gap;
                layout.gap_token = None;
            }
        }
        if let Some(token) = layout.padding_token.clone() {
            if let Some(padding) =
                self.resolve_number_ref(&token, NumberDomain::LayoutSpacing, subject)
            {
                layout.padding = [padding; 4];
                layout.padding_token = None;
            }
        }
    }

    fn resolve_fill(&mut self, fill: &mut Fill, subject: Option<DiagnosticSubject>) {
        self.resolve_paint(&mut fill.paint, subject);
    }

    fn resolve_paint(&mut self, paint: &mut Paint, subject: Option<DiagnosticSubject>) {
        match paint {
            Paint::Solid { color } => {
                if let Color::Token { token } = color {
                    if let Some(resolved) = self.resolve_color_ref(token, subject) {
                        *color = resolved;
                    }
                }
            }
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
                for stop in stops {
                    if let Color::Token { token } = &stop.color {
                        if let Some(resolved) = self.resolve_color_ref(token, subject.clone()) {
                            stop.color = resolved;
                        }
                    }
                }
            }
            Paint::Token { token } => {
                if let Some(color) = self.resolve_color_ref(token, subject) {
                    *paint = Paint::Solid { color };
                }
            }
        }
    }

    fn resolve_color_ref(
        &mut self,
        token: &str,
        subject: Option<DiagnosticSubject>,
    ) -> Option<Color> {
        let path = match normalize_token_path(token) {
            Ok(path) => path,
            Err(message) => {
                self.diagnostics.push(brand_diag(
                    "LUMB0200",
                    format!("invalid color token reference {token}: {message}"),
                    subject,
                ));
                return None;
            }
        };

        if self.resolving_colors.contains(&path) {
            self.diagnostics.push(brand_diag(
                "LUMB0202",
                format!("color token alias cycle detected at {}", path),
                subject,
            ));
            return None;
        }

        if let Some(alias) = self.brand_kit.tokens.aliases.get(&path) {
            self.resolving_colors.push(path);
            let resolved = self.resolve_color_ref(&alias.token, subject);
            self.resolving_colors.pop();
            return resolved;
        }

        let lookup = token_lookup_candidates(&path, "color");
        let Some((token_path, value)) = lookup.iter().find_map(|candidate| {
            self.brand_kit.tokens.colors.get(candidate).map(|token| {
                (
                    candidate.clone(),
                    token.value.value_for_mode(&self.options.mode),
                )
            })
        }) else {
            self.diagnostics.push(brand_diag(
                "LUMB0201",
                format!(
                    "color token {} is not defined in brand kit {}",
                    path, self.brand_kit.id
                ),
                subject,
            ));
            return None;
        };

        self.resolving_colors.push(token_path);
        let resolved = match value {
            ColorTokenValue::Hex { value } => Some(Color::Hex { value }),
            ColorTokenValue::Oklch { l, c, h, alpha } => Some(Color::Hex {
                value: oklch_to_hex(l, c, h, alpha),
            }),
            ColorTokenValue::Alias { token } => self.resolve_color_ref(&token, subject),
        };
        self.resolving_colors.pop();
        resolved
    }

    fn resolve_number_ref(
        &mut self,
        token: &str,
        domain: NumberDomain,
        subject: Option<DiagnosticSubject>,
    ) -> Option<f64> {
        let path = match normalize_token_path(token) {
            Ok(path) => path,
            Err(message) => {
                self.diagnostics.push(brand_diag(
                    "LUMB0300",
                    format!("invalid number token reference {token}: {message}"),
                    subject,
                ));
                return None;
            }
        };

        if self.resolving_numbers.contains(&path) {
            self.diagnostics.push(brand_diag(
                "LUMB0302",
                format!("number token alias cycle detected at {}", path),
                subject,
            ));
            return None;
        }

        if let Some(alias) = self.brand_kit.tokens.aliases.get(&path) {
            self.resolving_numbers.push(path);
            let resolved = self.resolve_number_ref(&alias.token, domain, subject);
            self.resolving_numbers.pop();
            return resolved;
        }

        let Some((token_path, value)) =
            self.lookup_number_token(&path, domain)
                .map(|(token_path, token)| {
                    (token_path, token.value.value_for_mode(&self.options.mode))
                })
        else {
            self.diagnostics.push(brand_diag(
                "LUMB0301",
                format!("number token {} is not defined for this style field", path),
                subject,
            ));
            return None;
        };

        self.resolving_numbers.push(token_path);
        let resolved = match value {
            NumberTokenValue::Number { value, unit } => {
                self.resolve_number_value(&path, value, unit, domain, subject)
            }
            NumberTokenValue::Alias { token } => self.resolve_number_ref(&token, domain, subject),
        };
        self.resolving_numbers.pop();
        resolved
    }

    fn resolve_number_value(
        &mut self,
        path: &str,
        value: f64,
        unit: NumberUnit,
        domain: NumberDomain,
        subject: Option<DiagnosticSubject>,
    ) -> Option<f64> {
        match domain {
            NumberDomain::Opacity => match unit {
                NumberUnit::Percent => Some(value / 100.0),
                NumberUnit::Ratio | NumberUnit::Unitless => Some(value),
                NumberUnit::Px | NumberUnit::Mm => {
                    self.diagnostics.push(brand_diag(
                        "LUMB0312",
                        format!(
                            "opacity token {} uses unsupported unit {:?}; use ratio, unitless, or percent",
                            path, unit
                        ),
                        subject,
                    ));
                    None
                }
            },
            NumberDomain::Dimension
            | NumberDomain::LayoutSpacing
            | NumberDomain::Radius
            | NumberDomain::StrokeWidth
            | NumberDomain::FontSize => match unit {
                NumberUnit::Unitless | NumberUnit::Px | NumberUnit::Mm => Some(value),
                NumberUnit::Percent | NumberUnit::Ratio => {
                    self.diagnostics.push(brand_diag(
                        "LUMB0313",
                        format!(
                            "number token {} uses relative unit {:?} in an absolute style field",
                            path, unit
                        ),
                        subject,
                    ));
                    None
                }
            },
        }
    }

    fn lookup_number_token(
        &self,
        path: &str,
        domain: NumberDomain,
    ) -> Option<(String, &NumberToken)> {
        let mut candidates = vec![path.to_owned()];
        match domain {
            NumberDomain::Dimension | NumberDomain::LayoutSpacing => {
                candidates.extend(token_lookup_candidates(path, "spacing"));
                candidates.extend(token_lookup_candidates(path, "number"));
                for candidate in candidates {
                    if let Some(token) = self.brand_kit.tokens.spacing.get(&candidate) {
                        return Some((candidate, token));
                    }
                    if let Some(token) = self.brand_kit.tokens.numbers.get(&candidate) {
                        return Some((candidate, token));
                    }
                }
            }
            NumberDomain::Radius => {
                candidates.extend(token_lookup_candidates(path, "radius"));
                candidates.extend(token_lookup_candidates(path, "radii"));
                candidates.extend(token_lookup_candidates(path, "spacing"));
                for candidate in candidates {
                    if let Some(token) = self.brand_kit.tokens.radii.get(&candidate) {
                        return Some((candidate, token));
                    }
                    if let Some(token) = self.brand_kit.tokens.spacing.get(&candidate) {
                        return Some((candidate, token));
                    }
                }
            }
            NumberDomain::StrokeWidth => {
                candidates.extend(token_lookup_candidates(path, "stroke"));
                candidates.extend(token_lookup_candidates(path, "stroke_width"));
                for candidate in candidates {
                    if let Some(token) = self.brand_kit.tokens.stroke_widths.get(&candidate) {
                        return Some((candidate, token));
                    }
                    if let Some(token) = self.brand_kit.tokens.numbers.get(&candidate) {
                        return Some((candidate, token));
                    }
                }
            }
            NumberDomain::Opacity => {
                candidates.extend(token_lookup_candidates(path, "opacity"));
                for candidate in candidates {
                    if let Some(token) = self.brand_kit.tokens.opacity.get(&candidate) {
                        return Some((candidate, token));
                    }
                    if let Some(token) = self.brand_kit.tokens.numbers.get(&candidate) {
                        return Some((candidate, token));
                    }
                }
            }
            NumberDomain::FontSize => {
                candidates.extend(token_lookup_candidates(path, "type"));
                candidates.extend(token_lookup_candidates(path, "font"));
                candidates.extend(token_lookup_candidates(path, "number"));
                for candidate in candidates {
                    if let Some(token) = self.brand_kit.tokens.numbers.get(&candidate) {
                        return Some((candidate, token));
                    }
                }
            }
        }
        None
    }

    fn resolve_text_style(
        &mut self,
        text: &TextNode,
        subject: Option<DiagnosticSubject>,
    ) -> Option<ResolvedTypographyStyle> {
        let token = text
            .style_token
            .as_deref()
            .filter(|value| !value.trim().is_empty())
            .or_else(|| {
                if looks_like_token_ref(&text.font_family) {
                    Some(text.font_family.as_str())
                } else {
                    None
                }
            })?;

        self.resolve_typography_ref(token, subject)
    }

    fn resolve_typography_ref(
        &mut self,
        token: &str,
        subject: Option<DiagnosticSubject>,
    ) -> Option<ResolvedTypographyStyle> {
        let path = match normalize_token_path(token) {
            Ok(path) => path,
            Err(message) => {
                self.diagnostics.push(brand_diag(
                    "LUMB0400",
                    format!("invalid typography token reference {token}: {message}"),
                    subject,
                ));
                return None;
            }
        };

        if self.resolving_typography.contains(&path) {
            self.diagnostics.push(brand_diag(
                "LUMB0402",
                format!("typography token alias cycle detected at {}", path),
                subject,
            ));
            return None;
        }

        if let Some(alias) = self.brand_kit.tokens.aliases.get(&path) {
            self.resolving_typography.push(path);
            let resolved = self.resolve_typography_ref(&alias.token, subject);
            self.resolving_typography.pop();
            return resolved;
        }

        let lookup = token_lookup_candidates(&path, "type");
        let Some((token_path, value)) = lookup.iter().find_map(|candidate| {
            self.brand_kit
                .tokens
                .typography
                .get(candidate)
                .map(|token| {
                    (
                        candidate.clone(),
                        token.value.value_for_mode(&self.options.mode),
                    )
                })
        }) else {
            if let Some(font_family) = self.resolve_font_family_ref(&path, subject.clone()) {
                return Some(ResolvedTypographyStyle {
                    font_family,
                    font_size: 16.0,
                    font_weight: 400,
                    line_height: None,
                    letter_spacing: None,
                    color: None,
                });
            }
            self.diagnostics.push(brand_diag(
                "LUMB0401",
                format!(
                    "typography token {} is not defined in brand kit {}",
                    path, self.brand_kit.id
                ),
                subject,
            ));
            return None;
        };

        self.resolving_typography.push(token_path);
        let resolved = match value {
            TypographyTokenValue::Style {
                font_family,
                font_size,
                font_weight,
                line_height,
                letter_spacing,
                color,
                font_asset,
                ..
            } => {
                let font_family = match font_asset {
                    Some(font_id) => {
                        match self.resolve_font_family_ref(&font_id, subject.clone()) {
                            Some(font_family) => font_family,
                            None => {
                                self.diagnostics.push(brand_diag(
                                    "LUMB0413",
                                    format!(
                                        "typography token references missing font asset {}",
                                        font_id
                                    ),
                                    subject,
                                ));
                                return None;
                            }
                        }
                    }
                    None => font_family,
                };
                Some(ResolvedTypographyStyle {
                    font_family,
                    font_size,
                    font_weight,
                    line_height,
                    letter_spacing,
                    color,
                })
            }
            TypographyTokenValue::Alias { token } => self.resolve_typography_ref(&token, subject),
        };
        self.resolving_typography.pop();
        resolved
    }

    fn resolve_font_family_ref(
        &mut self,
        token: &str,
        subject: Option<DiagnosticSubject>,
    ) -> Option<String> {
        let path = normalize_token_path(token).ok()?;
        if self.resolving_assets.contains(&path) {
            self.diagnostics.push(brand_diag(
                "LUMB0602",
                format!("asset token alias cycle detected at {}", path),
                subject,
            ));
            return None;
        }

        if let Some(font) = self.brand_kit.assets.fonts.get(&path) {
            return Some(font.family.clone());
        }
        let font_path = path.strip_prefix("font.").unwrap_or(&path);
        self.brand_kit
            .assets
            .fonts
            .get(font_path)
            .map(|font| font.family.clone())
    }
}

#[derive(Clone, Debug, PartialEq)]
struct ResolvedTypographyStyle {
    font_family: String,
    font_size: f64,
    font_weight: u16,
    line_height: Option<f64>,
    letter_spacing: Option<f64>,
    color: Option<String>,
}

fn validate_modes(modes: &BrandModeSpec, diagnostics: &mut Vec<Diagnostic>) {
    for (axis, values) in &modes.axes {
        if !valid_token_path(axis) {
            diagnostics.push(brand_error(
                "LUMB0110",
                format!("mode axis {} is not a valid token path segment", axis),
            ));
        }
        if values.is_empty() {
            diagnostics.push(brand_error(
                "LUMB0111",
                format!("mode axis {} must define at least one value", axis),
            ));
        }
        if let Some(default) = modes.defaults.get(axis) {
            if !values.contains(default) {
                diagnostics.push(brand_error(
                    "LUMB0112",
                    format!(
                        "mode axis {} default {} is not listed in axis values",
                        axis, default
                    ),
                ));
            }
        } else {
            diagnostics.push(brand_error(
                "LUMB0113",
                format!("mode axis {} has no default value", axis),
            ));
        }
    }
}

fn validate_token_keys(tokens: &TokenCatalog, diagnostics: &mut Vec<Diagnostic>) {
    validate_map_keys("color", tokens.colors.keys(), diagnostics);
    validate_map_keys("typography", tokens.typography.keys(), diagnostics);
    validate_map_keys("number", tokens.numbers.keys(), diagnostics);
    validate_map_keys("spacing", tokens.spacing.keys(), diagnostics);
    validate_map_keys("radius", tokens.radii.keys(), diagnostics);
    validate_map_keys("stroke width", tokens.stroke_widths.keys(), diagnostics);
    validate_map_keys("opacity", tokens.opacity.keys(), diagnostics);
    validate_map_keys("shadow", tokens.shadows.keys(), diagnostics);
    validate_map_keys("effect", tokens.effects.keys(), diagnostics);
    validate_map_keys("asset", tokens.assets.keys(), diagnostics);
    validate_map_keys("alias", tokens.aliases.keys(), diagnostics);
    validate_map_keys("style", tokens.styles.keys(), diagnostics);
}

fn validate_map_keys<'a>(
    label: &str,
    keys: impl Iterator<Item = &'a String>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for key in keys {
        if !valid_token_path(key) {
            diagnostics.push(brand_error(
                "LUMB0120",
                format!("{} token key {} is not a valid token path", label, key),
            ));
        }
    }
}

fn validate_token_values(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    for (path, token) in &brand_kit.tokens.colors {
        validate_mode_keys(path, &token.value.modes, &brand_kit.modes, diagnostics);
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            match value {
                ColorTokenValue::Hex { value } if !valid_hex(value) => {
                    diagnostics.push(brand_error(
                        "LUMB0210",
                        format!("color token {} has invalid hex value {}", path, value),
                    ))
                }
                ColorTokenValue::Oklch { l, c, h, alpha }
                    if !finite_in_range(*l, 0.0, 1.0)
                        || !finite_in_range(*c, 0.0, 1.0)
                        || !h.is_finite()
                        || !finite_in_range(*alpha, 0.0, 1.0) =>
                {
                    diagnostics.push(brand_error(
                        "LUMB0211",
                        format!("color token {} has invalid OKLCH components", path),
                    ));
                }
                _ => {}
            }
        }
    }

    for (path, token) in number_token_iter(&brand_kit.tokens) {
        validate_mode_keys(&path, &token.value.modes, &brand_kit.modes, diagnostics);
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            if let NumberTokenValue::Number { value, unit } = value {
                if !value.is_finite() {
                    diagnostics.push(brand_error(
                        "LUMB0310",
                        format!("number token {} must be finite", path),
                    ));
                }
                if matches!(unit, NumberUnit::Percent | NumberUnit::Ratio)
                    && !finite_in_range(*value, 0.0, 100.0)
                {
                    diagnostics.push(brand_error(
                        "LUMB0311",
                        format!("number token {} has invalid percent/ratio value", path),
                    ));
                }
            }
        }
    }

    for (path, token) in &brand_kit.tokens.typography {
        validate_mode_keys(path, &token.value.modes, &brand_kit.modes, diagnostics);
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            if let TypographyTokenValue::Style {
                font_family,
                font_size,
                font_weight,
                color,
                font_asset,
                ..
            } = value
            {
                if font_family.trim().is_empty() {
                    diagnostics.push(brand_error(
                        "LUMB0410",
                        format!("typography token {} has an empty font family", path),
                    ));
                }
                if !font_size.is_finite() || *font_size <= 0.0 {
                    diagnostics.push(brand_error(
                        "LUMB0411",
                        format!("typography token {} has invalid font size", path),
                    ));
                }
                if *font_weight == 0 || *font_weight > 1000 {
                    diagnostics.push(brand_error(
                        "LUMB0412",
                        format!("typography token {} has invalid font weight", path),
                    ));
                }
                if let Some(font_id) = font_asset {
                    match normalize_token_path(font_id) {
                        Ok(normalized) if font_asset_exists(brand_kit, &normalized) => {}
                        Ok(_) => diagnostics.push(brand_error(
                            "LUMB0413",
                            format!(
                                "typography token {} references missing font asset {}",
                                path, font_id
                            ),
                        )),
                        Err(message) => diagnostics.push(brand_error(
                            "LUMB0414",
                            format!(
                                "typography token {} has invalid font asset ref {}: {}",
                                path, font_id, message
                            ),
                        )),
                    }
                }
                if let Some(color_token) = color {
                    let mut resolver =
                        TokenResolver::new(brand_kit, TokenResolutionOptions::default());
                    resolver.resolve_color_ref(color_token, None);
                    diagnostics.extend(resolver.diagnostics);
                }
            }
        }
    }

    let mut resolver = TokenResolver::new(brand_kit, TokenResolutionOptions::default());
    for path in brand_kit.tokens.colors.keys() {
        resolver.resolve_color_ref(path, None);
    }
    for path in brand_kit.tokens.typography.keys() {
        resolver.resolve_typography_ref(path, None);
    }
    for path in brand_kit.tokens.spacing.keys() {
        resolver.resolve_number_ref(path, NumberDomain::LayoutSpacing, None);
    }
    for path in brand_kit.tokens.radii.keys() {
        resolver.resolve_number_ref(path, NumberDomain::Radius, None);
    }
    for path in brand_kit.tokens.stroke_widths.keys() {
        resolver.resolve_number_ref(path, NumberDomain::StrokeWidth, None);
    }
    for path in brand_kit.tokens.opacity.keys() {
        resolver.resolve_number_ref(path, NumberDomain::Opacity, None);
    }
    diagnostics.extend(resolver.diagnostics);
}

fn validate_mode_keys<T>(
    token_path: &str,
    modes: &BTreeMap<String, T>,
    spec: &BrandModeSpec,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for mode_key in modes.keys() {
        let Some((axis, value)) = mode_key.split_once('.') else {
            diagnostics.push(brand_error(
                "LUMB0130",
                format!(
                    "token {} uses unqualified mode key {}",
                    token_path, mode_key
                ),
            ));
            continue;
        };
        match spec.axes.get(axis) {
            Some(values) if values.iter().any(|candidate| candidate == value) => {}
            Some(_) => diagnostics.push(brand_error(
                "LUMB0131",
                format!("token {} uses unknown mode value {}", token_path, mode_key),
            )),
            None => diagnostics.push(brand_error(
                "LUMB0132",
                format!("token {} uses unknown mode axis {}", token_path, axis),
            )),
        }
    }
}

fn validate_assets(assets: &BrandAssets, diagnostics: &mut Vec<Diagnostic>) {
    for (id, font) in &assets.fonts {
        if !valid_token_path(id) {
            diagnostics.push(brand_error(
                "LUMB0610",
                format!("font asset id {} is not a valid token path", id),
            ));
        }
        if font.family.trim().is_empty() {
            diagnostics.push(brand_error(
                "LUMB0611",
                format!("font asset {} has empty family", id),
            ));
        }
        if font.fallback_stack.is_empty() {
            diagnostics.push(brand_warning(
                "LUMB0612",
                format!("font asset {} has no fallback stack", id),
            ));
        }
        if !font.license.embeddable {
            diagnostics.push(brand_warning(
                "LUMB0613",
                format!("font asset {} is not marked embeddable for export", id),
            ));
        }
        if !font.license.subsettable {
            diagnostics.push(brand_warning(
                "LUMB0614",
                format!("font asset {} is not marked subsettable for PDF export", id),
            ));
        }
        for face in &font.faces {
            if face.weight == 0 || face.weight > 1000 {
                diagnostics.push(brand_error(
                    "LUMB0615",
                    format!("font asset {} has invalid face weight {}", id, face.weight),
                ));
            }
        }
    }

    for (id, logo) in &assets.logos {
        if !valid_token_path(id) {
            diagnostics.push(brand_error(
                "LUMB0620",
                format!("logo asset id {} is not a valid token path", id),
            ));
        }
        if logo.variants.is_empty() {
            diagnostics.push(brand_warning(
                "LUMB0621",
                format!("logo asset {} has no variants", id),
            ));
        }
        for variant in &logo.variants {
            if variant.name.trim().is_empty() {
                diagnostics.push(brand_error(
                    "LUMB0622",
                    format!("logo asset {} has an empty variant name", id),
                ));
            }
        }
    }

    for (id, asset) in &assets.images {
        if !valid_token_path(id) {
            diagnostics.push(brand_error(
                "LUMB0640",
                format!("brand asset id {} is not a valid token path", id),
            ));
        }
        if asset.role.trim().is_empty() {
            diagnostics.push(brand_error(
                "LUMB0641",
                format!("brand asset {} has an empty role", id),
            ));
        }
        if asset.mime_type.as_deref().is_some_and(str::is_empty) {
            diagnostics.push(brand_warning(
                "LUMB0642",
                format!("brand asset {} has an empty MIME type", id),
            ));
        }
        for token in &asset.preferred_color_tokens {
            if !valid_token_path(token) {
                diagnostics.push(brand_error(
                    "LUMB0643",
                    format!(
                        "brand asset {} uses invalid preferred color token {}",
                        id, token
                    ),
                ));
            }
        }
        if asset
            .license
            .as_ref()
            .is_some_and(|license| !license.allow_export)
        {
            diagnostics.push(brand_warning(
                "LUMB0644",
                format!("brand asset {} is not marked exportable", id),
            ));
        }
    }
}

fn font_asset_exists(brand_kit: &BrandKit, font_id: &str) -> bool {
    if brand_kit.assets.fonts.contains_key(font_id) {
        return true;
    }
    let stripped = font_id.strip_prefix("font.").unwrap_or(font_id);
    brand_kit.assets.fonts.contains_key(stripped)
}

fn validate_contrast_pairs(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    let mut resolver = TokenResolver::new(brand_kit, TokenResolutionOptions::default());
    for pair in &brand_kit.constraints.contrast_pairs {
        if !pair.min_ratio.is_finite() || pair.min_ratio <= 0.0 {
            diagnostics.push(brand_error(
                "LUMB0630",
                format!(
                    "contrast pair {} on {} has invalid minimum ratio",
                    pair.foreground, pair.background
                ),
            ));
            continue;
        }

        let foreground = resolver.resolve_color_ref(&pair.foreground, None);
        let background = resolver.resolve_color_ref(&pair.background, None);
        if let (Some(foreground), Some(background)) = (foreground, background) {
            if let (Some(fg_rgb), Some(bg_rgb)) =
                (color_to_rgb(&foreground), color_to_rgb(&background))
            {
                let ratio = contrast_ratio(fg_rgb, bg_rgb);
                if ratio < pair.min_ratio {
                    diagnostics.push(brand_warning(
                        "LUMB0631",
                        format!(
                            "contrast pair {} on {} has ratio {:.2}, below required {:.2}",
                            pair.foreground, pair.background, ratio, pair.min_ratio
                        ),
                    ));
                }
            }
        }
    }
    diagnostics.extend(resolver.diagnostics);
}

fn validate_product_ready_modes(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    for (axis, required_values) in REQUIRED_MODE_AXES {
        let Some(values) = brand_kit.modes.axes.get(*axis) else {
            diagnostics.push(product_ready_diag(
                brand_kit,
                "LUMB0802",
                format!(
                    "product-ready Brand Kit is missing required mode axis {}",
                    axis
                ),
            ));
            continue;
        };
        for required_value in *required_values {
            if !values.iter().any(|value| value == required_value) {
                diagnostics.push(product_ready_diag(
                    brand_kit,
                    "LUMB0802",
                    format!(
                        "product-ready Brand Kit mode axis {} is missing value {}",
                        axis, required_value
                    ),
                ));
            }
        }
        match brand_kit.modes.defaults.get(*axis) {
            Some(default) if values.contains(default) => {}
            Some(default) => diagnostics.push(product_ready_diag(
                brand_kit,
                "LUMB0802",
                format!(
                    "product-ready Brand Kit mode axis {} has invalid default {}",
                    axis, default
                ),
            )),
            None => diagnostics.push(product_ready_diag(
                brand_kit,
                "LUMB0802",
                format!(
                    "product-ready Brand Kit mode axis {} has no default value",
                    axis
                ),
            )),
        }
    }
}

fn validate_required_token_coverage(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    validate_required_tokens(
        brand_kit,
        "color",
        REQUIRED_PRODUCT_READY_COLOR_TOKENS,
        |kit, token| kit.tokens.colors.contains_key(token),
        "LUMB0800",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "typography",
        REQUIRED_PRODUCT_READY_TYPOGRAPHY_TOKENS,
        |kit, token| kit.tokens.typography.contains_key(token),
        "LUMB0801",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "spacing",
        REQUIRED_PRODUCT_READY_SPACING_TOKENS,
        |kit, token| kit.tokens.spacing.contains_key(token),
        "LUMB0800",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "radius",
        REQUIRED_PRODUCT_READY_RADIUS_TOKENS,
        |kit, token| kit.tokens.radii.contains_key(token),
        "LUMB0800",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "stroke width",
        REQUIRED_PRODUCT_READY_STROKE_WIDTH_TOKENS,
        |kit, token| kit.tokens.stroke_widths.contains_key(token),
        "LUMB0800",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "opacity",
        REQUIRED_PRODUCT_READY_OPACITY_TOKENS,
        |kit, token| kit.tokens.opacity.contains_key(token),
        "LUMB0800",
        diagnostics,
    );
    validate_required_tokens(
        brand_kit,
        "asset",
        REQUIRED_PRODUCT_READY_ASSET_TOKENS,
        |kit, token| kit.tokens.assets.contains_key(token),
        "LUMB0817",
        diagnostics,
    );
}

fn validate_required_tokens(
    brand_kit: &BrandKit,
    label: &str,
    required: &[&str],
    exists: impl Fn(&BrandKit, &str) -> bool,
    code: &str,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for token in required {
        if !exists(brand_kit, token) {
            diagnostics.push(product_ready_diag(
                brand_kit,
                code,
                format!("product-ready Brand Kit is missing required {label} token {token}"),
            ));
        }
    }
}

fn validate_required_mode_coverage(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    for token in CRITICAL_MODE_COLOR_TOKENS {
        let Some(color) = brand_kit.tokens.colors.get(*token) else {
            continue;
        };
        validate_mode_override(
            brand_kit,
            token,
            &color.value.modes,
            "theme.dark",
            diagnostics,
        );
        validate_mode_override(
            brand_kit,
            token,
            &color.value.modes,
            "accessibility.high_contrast",
            diagnostics,
        );
    }

    for token in CRITICAL_MODE_TYPOGRAPHY_TOKENS {
        let Some(style) = brand_kit.tokens.typography.get(*token) else {
            continue;
        };
        validate_mode_override(
            brand_kit,
            token,
            &style.value.modes,
            "accessibility.large_text",
            diagnostics,
        );
    }
}

fn validate_mode_override<T>(
    brand_kit: &BrandKit,
    token: &str,
    modes: &BTreeMap<String, T>,
    required_mode: &str,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if !modes.contains_key(required_mode)
        && !brand_kit.compatibility_policy.allow_critical_mode_fallbacks
    {
        diagnostics.push(product_ready_diag(
            brand_kit,
            "LUMB0803",
            format!(
                "product-ready Brand Kit token {} is missing required mode value {}",
                token, required_mode
            ),
        ));
    }
}

fn logo_for_asset<'a>(
    brand_kit: &'a BrandKit,
    asset_id: &AssetId,
) -> Option<(&'a String, &'a LogoAsset)> {
    brand_kit.assets.logos.iter().find(|(_, logo)| {
        logo.variants
            .iter()
            .any(|variant| &variant.asset_id == asset_id)
    })
}

fn validate_text_contrast_for_governance(
    scene: &Scene,
    brand_kit: &BrandKit,
    node: &Node,
    text: &TextNode,
    severity_is_error: bool,
    subject: Option<DiagnosticSubject>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(background_token) = nearest_brand_background_token(scene, &node.id) else {
        return;
    };

    let mut resolver = TokenResolver::new(brand_kit, token_options_for_governance(scene));
    let foreground = text_foreground_color_for_governance(node, &mut resolver, subject.clone());
    let background = resolver.resolve_color_ref(&background_token, subject.clone());
    diagnostics.extend(resolver.diagnostics);

    let Some((foreground_label, foreground_token, foreground_color)) = foreground else {
        return;
    };
    let Some(background_color) = background else {
        return;
    };
    let (Some(foreground_rgb), Some(background_rgb)) = (
        color_to_rgb(&foreground_color),
        color_to_rgb(&background_color),
    ) else {
        return;
    };

    let ratio = contrast_ratio(foreground_rgb, background_rgb);
    let required_ratio = contrast_ratio_requirement(
        brand_kit,
        foreground_token.as_deref(),
        &background_token,
        text,
    );
    if ratio < required_ratio {
        diagnostics.push(
            brand_governance_diag(
                severity_is_error,
                "LUMB0807",
                format!(
                    "node {} text contrast {} on ${} is {:.2}, below required {:.2}",
                    node.id, foreground_label, background_token, ratio, required_ratio
                ),
                subject,
            )
            .with_hint(format!(
                "Use a Brand Kit text token with sufficient contrast on ${}, such as $text.primary or $text.inverse.",
                background_token
            )),
        );
    }
}

fn token_options_for_governance(scene: &Scene) -> TokenResolutionOptions {
    let mut options = TokenResolutionOptions::default();
    if let Some(medium) = &scene.meta.medium {
        options.mode.values.insert(
            "medium".to_owned(),
            brand_medium_for_scene_medium_for_governance(medium).to_owned(),
        );
    }
    options
}

fn brand_medium_for_scene_medium_for_governance(medium: &crate::scene::Medium) -> &'static str {
    match medium {
        crate::scene::Medium::Print | crate::scene::Medium::DirectMail => "print",
        crate::scene::Medium::Digital
        | crate::scene::Medium::Email
        | crate::scene::Medium::Ad
        | crate::scene::Medium::Web => "digital",
    }
}

fn text_foreground_color_for_governance(
    node: &Node,
    resolver: &mut TokenResolver<'_>,
    subject: Option<DiagnosticSubject>,
) -> Option<(String, Option<String>, Color)> {
    node.fills
        .iter()
        .find_map(|fill| paint_color_for_governance(&fill.paint, resolver, subject.clone()))
}

fn paint_color_for_governance(
    paint: &Paint,
    resolver: &mut TokenResolver<'_>,
    subject: Option<DiagnosticSubject>,
) -> Option<(String, Option<String>, Color)> {
    match paint {
        Paint::Token { token } => {
            let color = resolver.resolve_color_ref(token, subject)?;
            Some((
                format!("${}", token.trim_start_matches('$')),
                Some(token.clone()),
                color,
            ))
        }
        Paint::Solid { color } => color_for_governance(color, resolver, subject),
        Paint::LinearGradient { .. } | Paint::RadialGradient { .. } => None,
    }
}

fn color_for_governance(
    color: &Color,
    resolver: &mut TokenResolver<'_>,
    subject: Option<DiagnosticSubject>,
) -> Option<(String, Option<String>, Color)> {
    match color {
        Color::Token { token } => {
            let color = resolver.resolve_color_ref(token, subject)?;
            Some((
                format!("${}", token.trim_start_matches('$')),
                Some(token.clone()),
                color,
            ))
        }
        Color::Hex { value } => Some((value.clone(), None, color.clone())),
        Color::Oklch { .. } => Some(("oklch(...)".to_owned(), None, color.clone())),
    }
}

fn contrast_ratio_requirement(
    brand_kit: &BrandKit,
    foreground_token: Option<&str>,
    background_token: &str,
    text: &TextNode,
) -> f64 {
    let default_ratio = if text_is_large_scale(text) { 3.0 } else { 4.5 };
    let Some(foreground_token) = foreground_token else {
        return default_ratio;
    };
    let Ok(foreground) = normalize_token_path(foreground_token) else {
        return default_ratio;
    };
    let Ok(background) = normalize_token_path(background_token) else {
        return default_ratio;
    };

    brand_kit
        .constraints
        .contrast_pairs
        .iter()
        .find_map(|pair| {
            let pair_foreground = normalize_token_path(&pair.foreground).ok()?;
            let pair_background = normalize_token_path(&pair.background).ok()?;
            if pair_foreground == foreground && pair_background == background {
                Some(pair.min_ratio)
            } else {
                None
            }
        })
        .filter(|ratio| ratio.is_finite() && *ratio > 0.0)
        .unwrap_or(default_ratio)
}

fn text_is_large_scale(text: &TextNode) -> bool {
    text.font_size >= 24.0 || (text.font_size >= 18.66 && text.font_weight >= 700)
}

fn scene_is_print_medium(scene: &Scene) -> bool {
    matches!(
        scene.meta.medium.as_ref(),
        Some(crate::scene::Medium::Print | crate::scene::Medium::DirectMail)
    )
}

fn effective_node_opacity_for_governance(
    brand_kit: &BrandKit,
    node: &Node,
    subject: Option<DiagnosticSubject>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<(String, f64)> {
    if let Some(token) = &node.opacity_token {
        let mut resolver = TokenResolver::new(
            brand_kit,
            TokenResolutionOptions {
                mode: BrandMode {
                    values: BTreeMap::from([("medium".to_owned(), "print".to_owned())]),
                },
                ..TokenResolutionOptions::default()
            },
        );
        let opacity = resolver.resolve_number_ref(token, NumberDomain::Opacity, subject);
        diagnostics.extend(resolver.diagnostics);
        opacity.map(|opacity| (format!("from token ${token}"), opacity))
    } else {
        Some((format!("value {}", node.opacity), node.opacity))
    }
}

fn nearest_brand_background_token(scene: &Scene, node_id: &NodeId) -> Option<String> {
    let mut parent = scene.parent_of(node_id);
    while let Some(current) = parent {
        match current {
            crate::scene::ParentRef::Page(page_id) => {
                let page = scene.pages.get(&page_id)?;
                return fill_background_token(&page.background)
                    .or_else(|| Some("surface.page".to_owned()));
            }
            crate::scene::ParentRef::Node(parent_id) => {
                let node = scene.nodes.get(&parent_id)?;
                if let Some(token) = fill_background_token(&node.fills) {
                    return Some(token);
                }
                parent = scene.parent_of(&parent_id);
            }
        }
    }
    None
}

fn fill_background_token(fills: &[Fill]) -> Option<String> {
    fills
        .iter()
        .find_map(|fill| paint_background_token(&fill.paint))
}

fn paint_background_token(paint: &Paint) -> Option<String> {
    match paint {
        Paint::Token { token } => Some(token.clone()),
        Paint::Solid {
            color: Color::Token { token },
        } => Some(token.clone()),
        Paint::Solid { .. } | Paint::LinearGradient { .. } | Paint::RadialGradient { .. } => None,
    }
}

fn validate_product_typography_roles(brand_kit: &BrandKit, diagnostics: &mut Vec<Diagnostic>) {
    for token_path in REQUIRED_PRODUCT_READY_TYPOGRAPHY_TOKENS {
        let Some(token) = brand_kit.tokens.typography.get(*token_path) else {
            continue;
        };
        for value in std::iter::once(&token.value.default).chain(token.value.modes.values()) {
            if let TypographyTokenValue::Style {
                font_size,
                line_height,
                ..
            } = value
            {
                if *token_path == "type.body" && *font_size < 14.0 {
                    diagnostics.push(product_ready_diag(
                        brand_kit,
                        "LUMB0818",
                        "type.body font size is below the product readability threshold",
                    ));
                }
                if let Some(line_height) = line_height {
                    if *line_height < 1.0 {
                        diagnostics.push(product_ready_diag(
                            brand_kit,
                            "LUMB0818",
                            format!("typography token {} has line height below 1.0", token_path),
                        ));
                    }
                }
            }
        }
    }
}

fn product_ready_diag(
    brand_kit: &BrandKit,
    code: impl Into<String>,
    message: impl Into<String>,
) -> Diagnostic {
    match brand_kit.approval_status {
        BrandApprovalStatus::Approved => brand_error(code, message),
        BrandApprovalStatus::Draft | BrandApprovalStatus::GeneratedUnreviewed => {
            brand_warning(code, message)
        }
        BrandApprovalStatus::Deprecated => brand_error(code, message),
    }
}

fn collect_removed_tokens<'a>(
    label: &str,
    from_keys: impl Iterator<Item = &'a String>,
    to_keys: impl Iterator<Item = &'a String>,
    token_changes: &mut Vec<TokenChange>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let to_keys = to_keys.cloned().collect::<std::collections::BTreeSet<_>>();
    for key in from_keys {
        if !to_keys.contains(key) {
            token_changes.push(TokenChange {
                path: key.clone(),
                kind: if label.ends_with("asset") {
                    TokenChangeKind::AssetRemoved
                } else {
                    TokenChangeKind::Removed
                },
                from_kind: Some(label.to_owned()),
                to_kind: None,
            });
            diagnostics.push(brand_error(
                "LUMB0814",
                format!(
                    "{} token {} was removed in the target Brand Kit",
                    label, key
                ),
            ));
        }
    }
}

fn token_value_kind(value: &TypographyTokenValue) -> String {
    match value {
        TypographyTokenValue::Style { .. } => "style".to_owned(),
        TypographyTokenValue::Alias { .. } => "alias".to_owned(),
    }
}

fn resolution_operations(original: &Scene, resolved: &Scene) -> Vec<Operation> {
    let mut operations = Vec::new();

    for (page_id, page) in &resolved.pages {
        if let Some(original_page) = original.pages.get(page_id) {
            if original_page.background != page.background {
                operations.push(Operation::UpdatePage {
                    page_id: page_id.clone(),
                    patch: PagePatch {
                        background: FieldPatch::Set(page.background.clone()),
                        ..PagePatch::default()
                    },
                });
            }
        }
    }

    for (node_id, node) in &resolved.nodes {
        let Some(original_node) = original.nodes.get(node_id) else {
            continue;
        };
        let mut patch = NodePatch::default();
        let mut changed = false;

        if original_node.kind != node.kind {
            patch.kind = FieldPatch::Set(node.kind.clone());
            changed = true;
        }
        if original_node.size != node.size {
            patch.size = FieldPatch::Set(node.size.clone());
            changed = true;
        }
        if original_node.fills != node.fills {
            patch.fills = FieldPatch::Set(node.fills.clone());
            changed = true;
        }
        if original_node.strokes != node.strokes {
            patch.strokes = FieldPatch::Set(node.strokes.clone());
            changed = true;
        }
        if original_node.corner != node.corner {
            patch.corner = FieldPatch::Set(node.corner.clone());
            changed = true;
        }
        if original_node.opacity != node.opacity {
            patch.opacity = FieldPatch::Set(node.opacity);
            changed = true;
        }
        if original_node.opacity_token != node.opacity_token {
            patch.opacity_token = match &node.opacity_token {
                Some(token) => OptionalFieldPatch::Set(token.clone()),
                None => OptionalFieldPatch::Clear,
            };
            changed = true;
        }
        if original_node.layout != node.layout {
            patch.layout = match &node.layout {
                Some(layout) => OptionalFieldPatch::Set(layout.clone()),
                None => OptionalFieldPatch::Clear,
            };
            changed = true;
        }

        if changed {
            operations.push(Operation::UpdateNode {
                node_id: node_id.clone(),
                patch,
            });
        }
    }

    operations
}

fn compile_style_line(line: &str, kit: &mut BrandKit) -> Result<(), String> {
    if !line.contains('=') {
        return compile_style_statement(line, kit);
    }

    let (head, value) = line
        .split_once('=')
        .ok_or_else(|| "expected assignment with '='".to_owned())?;
    let head_parts = split_style_words(head);
    let directive = head_parts
        .first()
        .ok_or_else(|| "missing directive".to_owned())?;
    let name = head_parts
        .get(1)
        .ok_or_else(|| "missing token name".to_owned())?;

    if !valid_token_path(name) {
        return Err(format!("invalid token path {}", name));
    }

    let value = value.trim();
    match directive.as_str() {
        "color" => compile_color_directive(name, value, kit),
        "number" | "spacing" => compile_number_directive(
            name,
            value,
            StyleNumberKind::Spacing,
            &mut kit.tokens.spacing,
        ),
        "radius" | "radii" => {
            compile_number_directive(name, value, StyleNumberKind::Radius, &mut kit.tokens.radii)
        }
        "stroke" | "stroke_width" => compile_number_directive(
            name,
            value,
            StyleNumberKind::StrokeWidth,
            &mut kit.tokens.stroke_widths,
        ),
        "opacity" => compile_number_directive(
            name,
            value,
            StyleNumberKind::Opacity,
            &mut kit.tokens.opacity,
        ),
        "alias" => compile_alias_directive(name, value, kit),
        "typography" | "type" => compile_typography_directive(name, value, kit),
        "font" => compile_font_directive(name, value, kit),
        "logo" => compile_logo_directive(name, value, kit),
        "asset" => compile_brand_asset_directive(name, value, StyleBrandAssetKind::Generic, kit),
        "illustration" => {
            compile_brand_asset_directive(name, value, StyleBrandAssetKind::Illustration, kit)
        }
        "icon" => compile_brand_asset_directive(name, value, StyleBrandAssetKind::Icon, kit),
        "texture" => compile_brand_asset_directive(name, value, StyleBrandAssetKind::Texture, kit),
        "pattern" => compile_brand_asset_directive(name, value, StyleBrandAssetKind::Pattern, kit),
        "image" => compile_brand_asset_directive(name, value, StyleBrandAssetKind::Image, kit),
        "constraint" => compile_constraint_directive(name, value, kit),
        _ => Err(format!("unknown directive {}", directive)),
    }
}

fn compile_style_statement(line: &str, kit: &mut BrandKit) -> Result<(), String> {
    let parts = split_style_words(line);
    let directive = parts
        .first()
        .ok_or_else(|| "missing directive".to_owned())?;
    match directive.as_str() {
        "brand" => compile_brand_statement(line, kit),
        "mode" => compile_mode_statement(&parts, kit),
        _ => Err(format!(
            "expected assignment with '=' or supported statement, got {}",
            directive
        )),
    }
}

fn compile_brand_statement(line: &str, kit: &mut BrandKit) -> Result<(), String> {
    let mut remainder = line
        .trim()
        .strip_prefix("brand")
        .ok_or_else(|| "brand statement must start with brand".to_owned())?
        .trim();

    if let Some(after_quote) = remainder.strip_prefix('"') {
        let Some(end_index) = after_quote.find('"') else {
            return Err("brand name is missing a closing quote".to_owned());
        };
        kit.name = after_quote[..end_index].to_owned();
        remainder = after_quote[end_index + 1..].trim();
    } else {
        let words = split_style_words(remainder);
        let name = words
            .first()
            .ok_or_else(|| "brand statement expects a name".to_owned())?;
        kit.name = trim_quotes(name).to_owned();
    }

    for word in split_style_words(remainder) {
        if let Some(id) = call_inner(&word, "id") {
            if !valid_token_path(id) {
                return Err(format!("brand id {} is not a valid token path", id));
            }
            kit.id = BrandKitId::from(id);
        } else if let Some(version) = call_inner(&word, "version") {
            kit.version = version
                .parse::<u32>()
                .map_err(|_| format!("brand version {} is not a positive integer", version))?;
            if kit.version == 0 {
                return Err("brand version must be positive".to_owned());
            }
        }
    }

    Ok(())
}

fn compile_mode_statement(parts: &[String], kit: &mut BrandKit) -> Result<(), String> {
    let axis_call = parts
        .get(1)
        .ok_or_else(|| "mode statement expects axis(values...)".to_owned())?;
    let (axis, values_inner) = parse_style_call(axis_call)
        .ok_or_else(|| "mode statement expects axis(values...)".to_owned())?;
    if !valid_token_path(&axis) {
        return Err(format!("mode axis {} is not a valid token path", axis));
    }
    let values = split_args(&values_inner);
    if values.is_empty() {
        return Err(format!("mode axis {} must define at least one value", axis));
    }
    for value in &values {
        if !valid_token_path(value) {
            return Err(format!("mode value {} is not a valid token segment", value));
        }
    }
    kit.modes.axes.insert(axis.clone(), values.clone());

    let default = parts
        .iter()
        .skip(2)
        .find_map(|part| call_inner(part, "default").map(str::to_owned))
        .unwrap_or_else(|| values[0].clone());
    if !values.iter().any(|value| value == &default) {
        return Err(format!(
            "mode axis {} default {} is not listed in axis values",
            axis, default
        ));
    }
    kit.modes.defaults.insert(axis, default);
    Ok(())
}

fn compile_color_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let seed = call_inner(value, "ramp")
        .or_else(|| call_inner(value, "color"))
        .unwrap_or(value)
        .trim();
    let (_, chroma, hue) = parse_style_color_seed(seed)?;

    let mut prefixes = vec![name.to_owned()];
    if !name.contains('.') {
        prefixes.push(format!("palette.{name}"));
    }
    for prefix in prefixes {
        compile_color_ramp(&prefix, chroma, hue, kit)?;
    }
    Ok(())
}

fn parse_style_color_seed(seed: &str) -> Result<(f64, f64, f64), String> {
    if let Some(inner) = call_inner(seed, "oklch") {
        let args = split_args(inner);
        if args.len() != 3 {
            return Err("oklch color seed expects l,c,h".to_owned());
        }
        let l = parse_finite_f64(&args[0], "oklch lightness")?;
        let c = parse_finite_f64(&args[1], "oklch chroma")?;
        let h = parse_finite_f64(&args[2], "oklch hue")?;
        if !(0.0..=1.0).contains(&l) || !(0.0..=1.0).contains(&c) {
            return Err("oklch lightness/chroma must be between 0 and 1".to_owned());
        }
        return Ok((l, c, h));
    }

    if !valid_hex(seed) {
        return Err(format!(
            "color seed {} must be #RRGGBB, #RRGGBBAA, or oklch(l,c,h)",
            seed
        ));
    }
    hex_to_oklch(seed).ok_or_else(|| format!("could not convert color seed {}", seed))
}

fn compile_color_ramp(
    prefix: &str,
    chroma: f64,
    hue: f64,
    kit: &mut BrandKit,
) -> Result<(), String> {
    let mut generated = BTreeMap::new();
    for (stop, lightness) in COLOR_STOPS {
        generated.insert(
            format!("{prefix}.{stop}"),
            color_token(ColorTokenValue::Oklch {
                l: lightness,
                c: chroma.clamp(0.02, 0.18),
                h: hue,
                alpha: 1.0,
            }),
        );
    }
    for (role, stop) in PRESENCE_STOPS {
        generated.insert(
            format!("{prefix}.{role}"),
            color_token(ColorTokenValue::Alias {
                token: format!("{prefix}.{stop}"),
            }),
        );
    }
    generated.insert(
        prefix.to_owned(),
        color_token(ColorTokenValue::Alias {
            token: format!("{prefix}.mid"),
        }),
    );
    insert_color_tokens_unique(&mut kit.tokens.colors, generated)
}

#[derive(Clone, Copy)]
enum StyleNumberKind {
    Spacing,
    Radius,
    StrokeWidth,
    Opacity,
}

fn compile_number_directive(
    name: &str,
    value: &str,
    kind: StyleNumberKind,
    target: &mut BTreeMap<String, NumberToken>,
) -> Result<(), String> {
    if let Some(inner) = call_inner(value, "named") {
        let mut generated = BTreeMap::new();
        for item in split_args(inner) {
            let (key, raw_value) = item
                .split_once(':')
                .ok_or_else(|| format!("named value {} must use key:value", item))?;
            if !valid_token_path(key) {
                return Err(format!("named token key {} is invalid", key));
            }
            let number = parse_finite_f64(raw_value.trim(), "named number")?;
            generated.insert(
                format!("{name}.{key}"),
                number_token(NumberTokenValue::Number {
                    value: number,
                    unit: number_unit_for_kind(kind),
                }),
            );
        }
        return insert_number_tokens_unique(target, generated);
    }

    let explicit_scale = call_inner(value, "scale");
    let legacy_number = call_inner(value, "number");
    let inner = explicit_scale.or(legacy_number).unwrap_or(value);
    let values = split_args(inner)
        .into_iter()
        .map(|part| {
            parse_finite_f64(
                &part,
                &format!("number generator value {} is not numeric", part),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;

    let mut generated = BTreeMap::new();
    for (index, number) in values.iter().copied().enumerate() {
        let suffix = number_scale_suffix(kind, index, explicit_scale.is_some());
        generated.insert(
            format!("{name}.{suffix}"),
            number_token(NumberTokenValue::Number {
                value: number,
                unit: number_unit_for_kind(kind),
            }),
        );
    }
    insert_number_tokens_unique(target, generated)
}

fn compile_typography_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let inner = value
        .strip_prefix("typography(")
        .and_then(|inner| inner.strip_suffix(')'))
        .unwrap_or(value);
    let args = split_args(inner);
    if args.len() < 3 {
        return Err("typography expects font_family, size, weight".to_owned());
    }
    let (font_family, font_asset) = parse_typography_font_ref(&args[0], kit)?;
    let font_size = parse_finite_f64(&args[1], "typography size")?;
    let font_weight = args[2]
        .parse::<u16>()
        .map_err(|_| "typography weight must be numeric".to_owned())?;
    if font_weight == 0 || font_weight > 1000 {
        return Err("typography weight must be between 1 and 1000".to_owned());
    }

    let mut next_arg = 3;
    let mut line_height = None;
    let mut letter_spacing = None;
    let mut color = None;

    if let Some(arg) = args.get(next_arg) {
        if let Ok(value) = parse_finite_f64(arg, "typography line height") {
            line_height = Some(value);
            next_arg += 1;
        }
    }
    if let Some(arg) = args.get(next_arg) {
        if let Ok(value) = parse_finite_f64(arg, "typography letter spacing") {
            letter_spacing = Some(value);
            next_arg += 1;
        }
    }
    if let Some(arg) = args.get(next_arg) {
        color = Some(normalize_token_path(arg)?);
    }

    let mut paths = vec![name.to_owned()];
    if !name.starts_with("type.") && !name.contains('.') {
        paths.push(format!("type.{name}"));
    }

    let mut generated = BTreeMap::new();
    for path in paths {
        let mut modes = BTreeMap::new();
        modes.insert(
            "accessibility.large_text".to_owned(),
            TypographyTokenValue::Style {
                font_family: font_family.clone(),
                font_size: (font_size * 1.12).ceil(),
                font_weight,
                line_height: line_height.map(|value| (value + 0.04).min(1.8)),
                letter_spacing,
                color: color.clone(),
                font_asset: font_asset.clone(),
            },
        );
        generated.insert(
            path.clone(),
            TypographyToken {
                value: ModeValue {
                    default: TypographyTokenValue::Style {
                        font_family: font_family.clone(),
                        font_size,
                        font_weight,
                        line_height,
                        letter_spacing,
                        color: color.clone(),
                        font_asset: font_asset.clone(),
                    },
                    modes,
                },
                role: Some(path.strip_prefix("type.").unwrap_or(&path).to_owned()),
                description: Some(format!("Compiled .styles typography role {path}")),
                provenance: Some(TokenProvenance {
                    source: "styles_compiler".to_owned(),
                    confidence: 1.0,
                }),
            },
        );
    }
    insert_typography_tokens_unique(&mut kit.tokens.typography, generated)
}

fn compile_font_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let inner = call_inner(value, "font").unwrap_or(value);
    let args = split_args(inner);
    let family = args
        .first()
        .map(|value| trim_quotes(value).to_owned())
        .ok_or_else(|| "font expects a family name".to_owned())?;
    let fallback_stack = args
        .get(1)
        .map(|value| parse_font_fallback_stack(value))
        .unwrap_or_else(|| vec!["Arial".to_owned(), "sans-serif".to_owned()]);

    if kit.assets.fonts.contains_key(name) {
        return Err(format!("duplicate font asset {}", name));
    }
    kit.assets.fonts.insert(
        name.to_owned(),
        FontAsset {
            family: family.clone(),
            source: AssetSource::System { family },
            faces: vec![
                FontFace {
                    weight: 400,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
                FontFace {
                    weight: 700,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
                FontFace {
                    weight: 800,
                    style: FontStyle::Normal,
                    asset_id: None,
                    source_url: None,
                },
            ],
            fallback_stack,
            scripts: vec!["latin".to_owned()],
            license: FontLicense {
                name: "system".to_owned(),
                embeddable: true,
                subsettable: true,
                source_url: None,
                restrictions: Vec::new(),
                basis: None,
            },
            provenance: None,
            metrics: None,
        },
    );
    Ok(())
}

fn compile_logo_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let inner = call_inner(value, "asset").ok_or_else(|| "logo expects asset(...)".to_owned())?;
    let args = split_args(inner);
    let asset_id = args
        .first()
        .ok_or_else(|| "logo asset expects an asset id".to_owned())?;
    let mut usage = LogoUsage::Primary;
    let mut color_mode = LogoColorMode::FullColor;
    let mut min_size = None;
    let mut clearspace = None;
    let mut variant = "full_color".to_owned();

    for arg in args.iter().skip(1) {
        if let Some(inner) = call_inner(arg, "usage") {
            usage = parse_logo_usage(inner)?;
        } else if let Some(inner) = call_inner(arg, "mode") {
            color_mode = parse_logo_color_mode(inner)?;
        } else if let Some(inner) = call_inner(arg, "color_mode") {
            color_mode = parse_logo_color_mode(inner)?;
        } else if let Some(inner) = call_inner(arg, "min_size") {
            min_size = Some(parse_finite_f64(inner, "logo min_size")?);
        } else if let Some(inner) = call_inner(arg, "clearspace") {
            clearspace = Some(parse_finite_f64(inner, "logo clearspace")?);
        } else if let Some(inner) = call_inner(arg, "variant") {
            variant = trim_quotes(inner).to_owned();
        } else {
            return Err(format!("unsupported logo argument {}", arg));
        }
    }

    if kit.assets.logos.contains_key(name) {
        return Err(format!("duplicate logo asset {}", name));
    }
    kit.assets.logos.insert(
        name.to_owned(),
        LogoAsset {
            variants: vec![LogoVariant {
                name: variant.clone(),
                asset_id: AssetId::from(asset_id.as_str()),
                color_mode,
                width: None,
                height: None,
            }],
            usage,
            min_size,
            clearspace,
            allowed_backgrounds: vec!["surface.page".to_owned(), "surface.brand".to_owned()],
            license: None,
            provenance: None,
            title: None,
            description: None,
            usage_note: None,
        },
    );

    insert_asset_token_unique(
        &mut kit.tokens.assets,
        format!("logo.{name}"),
        AssetToken {
            value: ModeValue {
                default: AssetTokenValue::Logo {
                    logo_id: name.to_owned(),
                    variant: Some(variant),
                },
                modes: BTreeMap::new(),
            },
            description: Some(format!("Compiled .styles logo token logo.{name}")),
            provenance: Some(TokenProvenance {
                source: "styles_compiler".to_owned(),
                confidence: 1.0,
            }),
        },
    )
}

#[derive(Clone, Copy)]
enum StyleBrandAssetKind {
    Generic,
    Illustration,
    Icon,
    Texture,
    Pattern,
    Image,
}

impl StyleBrandAssetKind {
    fn registry_prefix(self) -> &'static str {
        match self {
            Self::Generic => "asset",
            Self::Illustration => "illustration",
            Self::Icon => "icon",
            Self::Texture => "texture",
            Self::Pattern => "pattern",
            Self::Image => "image",
        }
    }

    fn token_prefix(self) -> &'static str {
        match self {
            Self::Generic => "asset",
            Self::Illustration => "asset.illustration",
            Self::Icon => "asset.icon",
            Self::Texture => "asset.texture",
            Self::Pattern => "asset.pattern",
            Self::Image => "asset.image",
        }
    }

    fn default_role(self) -> &'static str {
        match self {
            Self::Generic => "brand_asset",
            Self::Illustration => "illustration",
            Self::Icon => "icon",
            Self::Texture => "texture",
            Self::Pattern => "pattern",
            Self::Image => "image",
        }
    }
}

fn compile_brand_asset_directive(
    name: &str,
    value: &str,
    kind: StyleBrandAssetKind,
    kit: &mut BrandKit,
) -> Result<(), String> {
    let inner =
        call_inner(value, "asset").ok_or_else(|| "brand asset expects asset(...)".to_owned())?;
    let args = split_args(inner);
    let asset_id = args
        .first()
        .ok_or_else(|| "brand asset expects an asset id".to_owned())?;

    let mut role = kind.default_role().to_owned();
    let mut mime_type = None;
    let mut style_tags = Vec::new();
    let mut allowed_contexts = Vec::new();
    let mut preferred_color_tokens = Vec::new();
    let mut recolor_allowed = None;
    let mut crop_allowed = None;
    let mut license = None;

    for arg in args.iter().skip(1) {
        if let Some(inner) = call_inner(arg, "role") {
            role = trim_quotes(inner).to_owned();
        } else if let Some(inner) = call_inner(arg, "mime") {
            mime_type = Some(trim_quotes(inner).to_owned());
        } else if let Some(inner) = call_inner(arg, "mime_type") {
            mime_type = Some(trim_quotes(inner).to_owned());
        } else if let Some(inner) = call_inner(arg, "tags") {
            style_tags.extend(parse_style_string_list(inner));
        } else if let Some(inner) = call_inner(arg, "tag") {
            style_tags.push(trim_quotes(inner).to_owned());
        } else if let Some(inner) = call_inner(arg, "context") {
            allowed_contexts.extend(parse_style_string_list(inner));
        } else if let Some(inner) = call_inner(arg, "contexts") {
            allowed_contexts.extend(parse_style_string_list(inner));
        } else if let Some(inner) = call_inner(arg, "color") {
            preferred_color_tokens.push(normalize_token_path(inner)?);
        } else if let Some(inner) = call_inner(arg, "colors") {
            for token in parse_style_string_list(inner) {
                preferred_color_tokens.push(normalize_token_path(&token)?);
            }
        } else if let Some(inner) = call_inner(arg, "recolor") {
            recolor_allowed = Some(parse_style_bool(inner, "asset recolor")?);
        } else if let Some(inner) = call_inner(arg, "crop") {
            crop_allowed = Some(parse_style_bool(inner, "asset crop")?);
        } else if let Some(inner) = call_inner(arg, "license") {
            license = Some(AssetLicense {
                name: trim_quotes(inner).to_owned(),
                allow_export: true,
                allow_modification: false,
                allow_embedding: true,
                allow_subsetting: false,
                source_url: None,
                restrictions: Vec::new(),
            });
        } else {
            return Err(format!("unsupported brand asset argument {}", arg));
        }
    }

    let registry_id = format!("{}.{}", kind.registry_prefix(), name);
    if kit.assets.images.contains_key(&registry_id) {
        return Err(format!("duplicate brand asset {}", registry_id));
    }
    kit.assets.images.insert(
        registry_id.clone(),
        BrandAsset {
            asset_id: AssetId::from(asset_id.as_str()),
            role,
            mime_type,
            license,
            provenance: Some(TokenProvenance {
                source: "styles_compiler".to_owned(),
                confidence: 1.0,
            }),
            style_tags,
            allowed_contexts,
            preferred_color_tokens,
            recolor_allowed,
            crop_allowed,
            title: None,
            description: None,
            usage_note: None,
        },
    );

    let token_path = format!("{}.{}", kind.token_prefix(), name);
    insert_asset_token_unique(
        &mut kit.tokens.assets,
        token_path.clone(),
        AssetToken {
            value: ModeValue {
                default: AssetTokenValue::Asset {
                    asset_id: AssetId::from(asset_id.as_str()),
                },
                modes: BTreeMap::new(),
            },
            description: Some(format!("Compiled .styles brand asset token {token_path}")),
            provenance: Some(TokenProvenance {
                source: "styles_compiler".to_owned(),
                confidence: 1.0,
            }),
        },
    )
}

fn compile_constraint_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    match name {
        "tone" => {
            kit.constraints.tone = trim_quotes(value)
                .split(',')
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_owned)
                .collect();
            Ok(())
        }
        "gradients" => {
            kit.constraints.allow_gradients = match value.trim() {
                "allow" | "true" => true,
                "deny" | "false" => false,
                other => {
                    return Err(format!(
                        "constraint gradients expects allow/deny/true/false, got {}",
                        other
                    ))
                }
            };
            Ok(())
        }
        "imagery" => {
            kit.constraints.imagery.push(trim_quotes(value).to_owned());
            Ok(())
        }
        "iconography" => {
            kit.constraints
                .iconography
                .push(trim_quotes(value).to_owned());
            Ok(())
        }
        _ => Err(format!("unknown constraint {}", name)),
    }
}

fn compile_alias_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let token = normalize_token_path(value)?;
    if kit.tokens.aliases.contains_key(name) {
        return Err(format!("duplicate alias token {}", name));
    }
    kit.tokens.aliases.insert(
        name.to_owned(),
        TokenAlias {
            token: token.clone(),
            description: None,
        },
    );

    if !kit.tokens.colors.contains_key(name) {
        kit.tokens.colors.insert(
            name.to_owned(),
            color_token(ColorTokenValue::Alias { token }),
        );
    }
    Ok(())
}

fn strip_style_comment(raw_line: &str) -> Option<String> {
    let mut in_quote = false;
    let mut quote = '\0';
    let mut end = raw_line.len();
    for (index, ch) in raw_line.char_indices() {
        if in_quote {
            if ch == quote {
                in_quote = false;
            }
            continue;
        }
        if matches!(ch, '"' | '\'') {
            in_quote = true;
            quote = ch;
        } else if ch == '#'
            && raw_line[..index]
                .chars()
                .last()
                .is_none_or(char::is_whitespace)
            && raw_line[index + ch.len_utf8()..]
                .chars()
                .next()
                .is_none_or(char::is_whitespace)
        {
            end = index;
            break;
        }
    }

    let trimmed = raw_line[..end].trim();
    if trimmed.starts_with('#') {
        return None;
    }
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_owned())
    }
}

fn split_args(input: &str) -> Vec<String> {
    split_top_level(input, ',')
}

fn trim_quotes(input: &str) -> &str {
    input.trim().trim_matches('"').trim_matches('\'')
}

fn parse_style_string_list(input: &str) -> Vec<String> {
    split_args(input)
        .into_iter()
        .map(|item| trim_quotes(&item).to_owned())
        .filter(|item| !item.is_empty())
        .collect()
}

fn parse_style_bool(input: &str, label: &str) -> Result<bool, String> {
    match input.trim() {
        "true" => Ok(true),
        "false" => Ok(false),
        other => Err(format!("{} expects true or false, got {}", label, other)),
    }
}

fn token_subset<T>(tokens: &BTreeMap<String, T>, include: impl Fn(&str) -> bool) -> Vec<String> {
    tokens
        .keys()
        .filter(|token| include(token))
        .cloned()
        .collect()
}

fn split_style_words(input: &str) -> Vec<String> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut depth = 0usize;
    let mut in_quote = false;
    let mut quote = '\0';

    for ch in input.chars() {
        if in_quote {
            current.push(ch);
            if ch == quote {
                in_quote = false;
            }
            continue;
        }

        match ch {
            '"' | '\'' => {
                in_quote = true;
                quote = ch;
                current.push(ch);
            }
            '(' => {
                depth += 1;
                current.push(ch);
            }
            ')' => {
                depth = depth.saturating_sub(1);
                current.push(ch);
            }
            ch if ch.is_whitespace() && depth == 0 => {
                if !current.trim().is_empty() {
                    result.push(current.trim().to_owned());
                    current.clear();
                }
            }
            _ => current.push(ch),
        }
    }

    if !current.trim().is_empty() {
        result.push(current.trim().to_owned());
    }
    result
}

fn split_top_level(input: &str, delimiter: char) -> Vec<String> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut depth = 0usize;
    let mut in_quote = false;
    let mut quote = '\0';

    for ch in input.chars() {
        if in_quote {
            current.push(ch);
            if ch == quote {
                in_quote = false;
            }
            continue;
        }

        match ch {
            '"' | '\'' => {
                in_quote = true;
                quote = ch;
                current.push(ch);
            }
            '(' => {
                depth += 1;
                current.push(ch);
            }
            ')' => {
                depth = depth.saturating_sub(1);
                current.push(ch);
            }
            ch if ch == delimiter && depth == 0 => {
                if !current.trim().is_empty() {
                    result.push(current.trim().to_owned());
                }
                current.clear();
            }
            _ => current.push(ch),
        }
    }

    if !current.trim().is_empty() {
        result.push(current.trim().to_owned());
    }
    result
}

fn parse_style_call(input: &str) -> Option<(String, String)> {
    let trimmed = input.trim();
    let open = trimmed.find('(')?;
    if !trimmed.ends_with(')') {
        return None;
    }
    let name = trimmed[..open].trim();
    if name.is_empty() {
        return None;
    }
    Some((
        name.to_owned(),
        trimmed[open + 1..trimmed.len() - 1].to_owned(),
    ))
}

fn call_inner<'a>(input: &'a str, call_name: &str) -> Option<&'a str> {
    let trimmed = input.trim();
    let prefix = format!("{call_name}(");
    trimmed
        .strip_prefix(&prefix)
        .and_then(|inner| inner.strip_suffix(')'))
        .map(str::trim)
}

fn parse_finite_f64(input: &str, label: &str) -> Result<f64, String> {
    let value = input
        .trim()
        .parse::<f64>()
        .map_err(|_| format!("{label} must be numeric"))?;
    if value.is_finite() {
        Ok(value)
    } else {
        Err(format!("{label} must be finite"))
    }
}

fn number_unit_for_kind(kind: StyleNumberKind) -> NumberUnit {
    match kind {
        StyleNumberKind::Opacity => NumberUnit::Ratio,
        _ => NumberUnit::Px,
    }
}

fn number_scale_suffix(kind: StyleNumberKind, index: usize, explicit_scale: bool) -> String {
    let suffix = match kind {
        StyleNumberKind::Spacing if explicit_scale => {
            ["0", "1", "2", "3", "4", "5", "6", "8", "10", "12", "16"]
                .get(index)
                .copied()
        }
        StyleNumberKind::Radius => [
            "none", "xs", "sm", "md", "lg", "xl", "full", "card", "button", "badge",
        ]
        .get(index)
        .copied(),
        StyleNumberKind::StrokeWidth => [
            "hairline", "thin", "default", "firm", "bold", "divider", "card", "focus",
        ]
        .get(index)
        .copied(),
        StyleNumberKind::Opacity => [
            "disabled", "subtle", "muted", "overlay", "scrim", "emphasis",
        ]
        .get(index)
        .copied(),
        _ => TSHIRT_STOPS.get(index).copied(),
    };
    suffix
        .map(str::to_owned)
        .unwrap_or_else(|| format!("{}", index + 1))
}

fn parse_typography_font_ref(
    input: &str,
    kit: &BrandKit,
) -> Result<(String, Option<String>), String> {
    if looks_like_token_ref(input) {
        let token = normalize_token_path(input)?;
        let font_id = token.strip_prefix("font.").unwrap_or(&token).to_owned();
        let family = kit
            .assets
            .fonts
            .get(&font_id)
            .map(|font| font.family.clone())
            .unwrap_or_else(|| font_id.clone());
        Ok((family, Some(font_id)))
    } else {
        Ok((trim_quotes(input).to_owned(), None))
    }
}

fn parse_font_fallback_stack(input: &str) -> Vec<String> {
    let inner = call_inner(input, "fallback").unwrap_or(input);
    let mut values: Vec<String> = split_args(inner)
        .into_iter()
        .flat_map(|value| {
            trim_quotes(&value)
                .split('|')
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .collect();
    if values.is_empty() {
        values = vec!["Arial".to_owned(), "sans-serif".to_owned()];
    }
    values
}

fn parse_logo_usage(input: &str) -> Result<LogoUsage, String> {
    match input.trim() {
        "primary" => Ok(LogoUsage::Primary),
        "secondary" => Ok(LogoUsage::Secondary),
        "mark" => Ok(LogoUsage::Mark),
        "wordmark" => Ok(LogoUsage::Wordmark),
        other => Err(format!("unknown logo usage {}", other)),
    }
}

fn parse_logo_color_mode(input: &str) -> Result<LogoColorMode, String> {
    match input.trim() {
        "full_color" | "full" => Ok(LogoColorMode::FullColor),
        "mono" | "monochrome" | "one_color" => Ok(LogoColorMode::OneColor),
        "reversed" | "reverse" => Ok(LogoColorMode::Reversed),
        other => Err(format!("unknown logo color mode {}", other)),
    }
}

fn insert_color_tokens_unique(
    target: &mut BTreeMap<String, ColorToken>,
    generated: BTreeMap<String, ColorToken>,
) -> Result<(), String> {
    for key in generated.keys() {
        if target.contains_key(key) {
            return Err(format!("duplicate color token {}", key));
        }
    }
    target.extend(generated);
    Ok(())
}

fn insert_number_tokens_unique(
    target: &mut BTreeMap<String, NumberToken>,
    generated: BTreeMap<String, NumberToken>,
) -> Result<(), String> {
    for key in generated.keys() {
        if target.contains_key(key) {
            return Err(format!("duplicate number token {}", key));
        }
    }
    target.extend(generated);
    Ok(())
}

fn insert_typography_tokens_unique(
    target: &mut BTreeMap<String, TypographyToken>,
    generated: BTreeMap<String, TypographyToken>,
) -> Result<(), String> {
    for key in generated.keys() {
        if target.contains_key(key) {
            return Err(format!("duplicate typography token {}", key));
        }
    }
    target.extend(generated);
    Ok(())
}

fn insert_asset_token_unique(
    target: &mut BTreeMap<String, AssetToken>,
    path: String,
    token: AssetToken,
) -> Result<(), String> {
    if target.contains_key(&path) {
        return Err(format!("duplicate asset token {}", path));
    }
    target.insert(path, token);
    Ok(())
}

fn color_token(value: ColorTokenValue) -> ColorToken {
    ColorToken {
        value: ModeValue {
            default: value,
            modes: BTreeMap::new(),
        },
        role: None,
        description: None,
        provenance: None,
    }
}

fn number_token(value: NumberTokenValue) -> NumberToken {
    NumberToken {
        value: ModeValue {
            default: value,
            modes: BTreeMap::new(),
        },
        role: None,
        description: None,
        provenance: None,
    }
}

fn normalize_token_path(input: &str) -> Result<String, String> {
    let trimmed = input.trim();
    let path = if let Some(stripped) = trimmed.strip_prefix('$') {
        stripped
    } else if let Some(inner) = trimmed
        .strip_prefix("token(")
        .and_then(|value| value.strip_suffix(')'))
    {
        inner.trim().strip_prefix('$').unwrap_or(inner.trim())
    } else {
        trimmed
    };

    if valid_token_path(path) {
        Ok(path.to_owned())
    } else {
        Err("expected dot-separated ascii token path".to_owned())
    }
}

fn looks_like_token_ref(input: &str) -> bool {
    let trimmed = input.trim();
    trimmed.starts_with('$') || trimmed.starts_with("token(")
}

fn token_lookup_candidates(path: &str, prefix: &str) -> Vec<String> {
    if let Some(stripped) = path.strip_prefix(&format!("{prefix}.")) {
        vec![path.to_owned(), stripped.to_owned()]
    } else {
        vec![path.to_owned(), format!("{prefix}.{path}")]
    }
}

fn valid_token_path(path: &str) -> bool {
    if path.is_empty() || path.starts_with('.') || path.ends_with('.') || path.contains("..") {
        return false;
    }
    path.bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
}

fn finite_in_range(value: f64, min: f64, max: f64) -> bool {
    value.is_finite() && value >= min && value <= max
}

fn valid_hex(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !matches!(bytes.len(), 7 | 9) || bytes.first() != Some(&b'#') {
        return false;
    }
    bytes[1..].iter().all(|byte| byte.is_ascii_hexdigit())
}

fn paint_is_bare(paint: &Paint) -> bool {
    match paint {
        Paint::Token { .. } => false,
        Paint::Solid { color } => !matches!(color, Color::Token { .. }),
        Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => stops
            .iter()
            .any(|stop| !matches!(stop.color, Color::Token { .. })),
    }
}

fn has_error(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == crate::DiagnosticSeverity::Error)
}

fn brand_error(code: impl Into<String>, message: impl Into<String>) -> Diagnostic {
    Diagnostic::error(Phase::Brand, code, message, None)
}

fn brand_warning(code: impl Into<String>, message: impl Into<String>) -> Diagnostic {
    Diagnostic::warning(Phase::Brand, code, message, None)
}

fn brand_governance_diag(
    severity_is_error: bool,
    code: impl Into<String>,
    message: impl Into<String>,
    subject: Option<DiagnosticSubject>,
) -> Diagnostic {
    if severity_is_error {
        Diagnostic::error(Phase::Brand, code, message, subject)
    } else {
        Diagnostic::warning(Phase::Brand, code, message, subject)
    }
}

fn brand_diag(
    code: impl Into<String>,
    message: impl Into<String>,
    subject: Option<DiagnosticSubject>,
) -> Diagnostic {
    Diagnostic::error(Phase::Brand, code, message, subject)
}

fn node_brand_error(
    code: impl Into<String>,
    message: impl Into<String>,
    node_id: &NodeId,
) -> Diagnostic {
    Diagnostic::error(
        Phase::Brand,
        code,
        message,
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
}

fn number_token_iter(tokens: &TokenCatalog) -> Vec<(String, &NumberToken)> {
    let mut result = Vec::new();
    result.extend(
        tokens
            .numbers
            .iter()
            .map(|(key, token)| (key.clone(), token)),
    );
    result.extend(
        tokens
            .spacing
            .iter()
            .map(|(key, token)| (key.clone(), token)),
    );
    result.extend(tokens.radii.iter().map(|(key, token)| (key.clone(), token)));
    result.extend(
        tokens
            .stroke_widths
            .iter()
            .map(|(key, token)| (key.clone(), token)),
    );
    result.extend(
        tokens
            .opacity
            .iter()
            .map(|(key, token)| (key.clone(), token)),
    );
    result
}

/// Map every node to the surface color it sits ON: the nearest ancestor's solid
/// fill, falling back to the page background. A container's own solid fill becomes
/// the surface for its children (not itself). Surfaces stay as their authored
/// `Color` (token or hex) and are resolved on demand.
fn build_node_surface_map(scene: &Scene) -> BTreeMap<NodeId, Color> {
    let mut map = BTreeMap::new();
    for page in scene.pages.values() {
        let page_surface = page
            .background
            .iter()
            .find_map(|fill| paint_solid_color(&fill.paint));
        for child in &page.children {
            walk_node_surface(scene, child, page_surface.clone(), &mut map);
        }
    }
    map
}

fn walk_node_surface(
    scene: &Scene,
    node_id: &NodeId,
    surface: Option<Color>,
    map: &mut BTreeMap<NodeId, Color>,
) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    if let Some(surface) = surface.clone() {
        map.insert(node_id.clone(), surface);
    }
    let child_surface = node
        .fills
        .iter()
        .find_map(|fill| paint_solid_color(&fill.paint))
        .or(surface);
    for child in &node.children {
        walk_node_surface(scene, child, child_surface.clone(), map);
    }
}

fn paint_solid_color(paint: &Paint) -> Option<Color> {
    match paint {
        Paint::Solid { color } => Some(color.clone()),
        Paint::Token { token } => Some(Color::Token {
            token: token.clone(),
        }),
        _ => None,
    }
}

fn color_to_rgb(color: &Color) -> Option<(f64, f64, f64)> {
    match color {
        Color::Hex { value } => hex_to_rgb(value),
        Color::Oklch { l, c, h, alpha: _ } => {
            let hex = oklch_to_hex(*l, *c, *h, 1.0);
            hex_to_rgb(&hex)
        }
        Color::Token { .. } => None,
    }
}

fn hex_to_rgb(value: &str) -> Option<(f64, f64, f64)> {
    if !valid_hex(value) {
        return None;
    }
    let red = u8::from_str_radix(&value[1..3], 16).ok()? as f64 / 255.0;
    let green = u8::from_str_radix(&value[3..5], 16).ok()? as f64 / 255.0;
    let blue = u8::from_str_radix(&value[5..7], 16).ok()? as f64 / 255.0;
    Some((red, green, blue))
}

fn hex_to_oklch(value: &str) -> Option<(f64, f64, f64)> {
    let (red, green, blue) = hex_to_rgb(value)?;
    let red = srgb_to_linear(red);
    let green = srgb_to_linear(green);
    let blue = srgb_to_linear(blue);

    let l = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue;
    let m = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue;
    let s = 0.0883024619 * red + 0.2817188376 * green + 0.6309787005 * blue;

    let l = l.cbrt();
    let m = m.cbrt();
    let s = s.cbrt();

    let okl = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
    let oka = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
    let okb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
    let chroma = (oka * oka + okb * okb).sqrt();
    let hue = okb.atan2(oka).to_degrees().rem_euclid(360.0);
    Some((okl, chroma, hue))
}

fn oklch_to_hex(l: f64, c: f64, h: f64, alpha: f64) -> String {
    let hue = h.to_radians();
    let a = c * hue.cos();
    let b = c * hue.sin();

    let l1 = l + 0.3963377774 * a + 0.2158037573 * b;
    let m1 = l - 0.1055613458 * a - 0.0638541728 * b;
    let s1 = l - 0.0894841775 * a - 1.2914855480 * b;

    let l2 = l1 * l1 * l1;
    let m2 = m1 * m1 * m1;
    let s2 = s1 * s1 * s1;

    let red = linear_to_srgb(4.0767416621 * l2 - 3.3077115913 * m2 + 0.2309699292 * s2);
    let green = linear_to_srgb(-1.2684380046 * l2 + 2.6097574011 * m2 - 0.3413193965 * s2);
    let blue = linear_to_srgb(-0.0041960863 * l2 - 0.7034186147 * m2 + 1.7076147010 * s2);

    let red = channel_to_u8(red);
    let green = channel_to_u8(green);
    let blue = channel_to_u8(blue);
    let alpha = channel_to_u8(alpha);
    if alpha == 255 {
        format!("#{red:02X}{green:02X}{blue:02X}")
    } else {
        format!("#{red:02X}{green:02X}{blue:02X}{alpha:02X}")
    }
}

fn srgb_to_linear(value: f64) -> f64 {
    if value <= 0.04045 {
        value / 12.92
    } else {
        ((value + 0.055) / 1.055).powf(2.4)
    }
}

fn linear_to_srgb(value: f64) -> f64 {
    if value <= 0.0031308 {
        12.92 * value
    } else {
        1.055 * value.powf(1.0 / 2.4) - 0.055
    }
}

fn channel_to_u8(value: f64) -> u8 {
    (value.clamp(0.0, 1.0) * 255.0).round() as u8
}

fn contrast_ratio(foreground: (f64, f64, f64), background: (f64, f64, f64)) -> f64 {
    let fg = relative_luminance(foreground);
    let bg = relative_luminance(background);
    let light = fg.max(bg);
    let dark = fg.min(bg);
    (light + 0.05) / (dark + 0.05)
}

fn relative_luminance((red, green, blue): (f64, f64, f64)) -> f64 {
    0.2126 * srgb_to_linear(red) + 0.7152 * srgb_to_linear(green) + 0.0722 * srgb_to_linear(blue)
}
