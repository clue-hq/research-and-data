use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{AssetId, BrandKitId, NodeId, PaintId};
use crate::operations::{FieldPatch, NodePatch, Operation, OptionalFieldPatch, PagePatch};
use crate::scene::{
    AutoLayoutProps, BrandKitRef, Color, CornerRadii, Dimension, Fill, Node, NodeKind, Paint,
    Scene, TextNode,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

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
            "theme".to_owned(),
            vec!["light".to_owned(), "dark".to_owned()],
        ),
    ])
}

fn default_mode_values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("accessibility".to_owned(), "standard".to_owned()),
        ("density".to_owned(), "comfortable".to_owned()),
        ("theme".to_owned(), "light".to_owned()),
    ])
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
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AssetSource {
    Uploaded { asset_id: AssetId },
    Url { url: String },
    System { family: String },
    Generated { model: String },
    Unknown,
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
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetLicense {
    pub name: String,
    pub allow_export: bool,
    pub allow_modification: bool,
    #[serde(default)]
    pub restrictions: Vec<String>,
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
    validate_assets(&brand_kit.assets, &mut diagnostics);
    validate_contrast_pairs(brand_kit, &mut diagnostics);

    diagnostics
}

pub fn validate_scene_tokens(
    scene: &Scene,
    brand_kit: &BrandKit,
    options: &TokenResolutionOptions,
) -> Vec<Diagnostic> {
    let report = resolve_scene_tokens(scene, brand_kit, options);
    report.diagnostics
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

    diagnostics.extend(validate_brand_kit(&kit));
    if has_error(&diagnostics) {
        Err(diagnostics)
    } else {
        Ok(kit)
    }
}

#[derive(Clone, Copy)]
enum NumberDomain {
    Dimension,
    LayoutSpacing,
    Radius,
    StrokeWidth,
    Opacity,
}

struct TokenResolver<'a> {
    brand_kit: &'a BrandKit,
    options: TokenResolutionOptions,
    diagnostics: Vec<Diagnostic>,
    resolving_colors: Vec<String>,
    resolving_numbers: Vec<String>,
    resolving_typography: Vec<String>,
    resolving_assets: Vec<String>,
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
            if let Some(style) = self.resolve_text_style(text, subject.clone()) {
                text.font_family = style.font_family;
                text.font_size = style.font_size;
                text.font_weight = style.font_weight;
                text.style_token = None;

                if let Some(color_token) = style.color {
                    if let Some(color) = self.resolve_color_ref(&color_token, subject) {
                        let paint = Paint::Solid { color };
                        if let Some(fill) = node.fills.first_mut() {
                            fill.paint = paint;
                        } else {
                            node.fills.push(Fill {
                                id: PaintId::from(format!("{}_text_fill", node.id.as_str())),
                                paint,
                            });
                        }
                    }
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
            | NumberDomain::StrokeWidth => match unit {
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
    let (head, value) = line
        .split_once('=')
        .ok_or_else(|| "expected assignment with '='".to_owned())?;
    let mut head_parts = head.split_whitespace();
    let directive = head_parts
        .next()
        .ok_or_else(|| "missing directive".to_owned())?;
    let name = head_parts
        .next()
        .ok_or_else(|| "missing token name".to_owned())?;

    if !valid_token_path(name) {
        return Err(format!("invalid token path {}", name));
    }

    let value = value.trim();
    match directive {
        "color" => compile_color_directive(name, value, kit),
        "number" | "spacing" => compile_number_directive(name, value, &mut kit.tokens.spacing),
        "radius" | "radii" => compile_number_directive(name, value, &mut kit.tokens.radii),
        "stroke" | "stroke_width" => {
            compile_number_directive(name, value, &mut kit.tokens.stroke_widths)
        }
        "opacity" => compile_number_directive(name, value, &mut kit.tokens.opacity),
        "alias" => {
            kit.tokens.aliases.insert(
                name.to_owned(),
                TokenAlias {
                    token: value.to_owned(),
                    description: None,
                },
            );
            Ok(())
        }
        "typography" | "type" => compile_typography_directive(name, value, kit),
        "font" => compile_font_directive(name, value, kit),
        _ => Err(format!("unknown directive {}", directive)),
    }
}

fn compile_color_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let seed = value
        .strip_prefix("color(")
        .and_then(|inner| inner.strip_suffix(')'))
        .unwrap_or(value)
        .trim();
    if !valid_hex(seed) {
        return Err(format!("color seed {} must be #RRGGBB or #RRGGBBAA", seed));
    }
    let Some((_, _, hue)) = hex_to_oklch(seed) else {
        return Err(format!("could not convert color seed {}", seed));
    };

    for (stop, lightness) in COLOR_STOPS {
        kit.tokens.colors.insert(
            format!("{name}.{stop}"),
            color_token(ColorTokenValue::Oklch {
                l: lightness,
                c: 0.09,
                h: hue,
                alpha: 1.0,
            }),
        );
    }
    for (role, stop) in PRESENCE_STOPS {
        kit.tokens.colors.insert(
            format!("{name}.{role}"),
            color_token(ColorTokenValue::Alias {
                token: format!("{name}.{stop}"),
            }),
        );
    }
    kit.tokens.colors.insert(
        name.to_owned(),
        color_token(ColorTokenValue::Alias {
            token: format!("{name}.mid"),
        }),
    );
    Ok(())
}

fn compile_number_directive(
    name: &str,
    value: &str,
    target: &mut BTreeMap<String, NumberToken>,
) -> Result<(), String> {
    let inner = value
        .strip_prefix("number(")
        .and_then(|inner| inner.strip_suffix(')'))
        .unwrap_or(value);
    let values = split_args(inner)
        .into_iter()
        .map(|part| {
            part.parse::<f64>()
                .map_err(|_| format!("number generator value {} is not numeric", part))
        })
        .collect::<Result<Vec<_>, _>>()?;

    for (index, number) in values.into_iter().enumerate() {
        let key = TSHIRT_STOPS.get(index).copied().unwrap_or("custom");
        let key = if key == "custom" {
            format!("{name}.{}", index + 1)
        } else {
            format!("{name}.{key}")
        };
        target.insert(
            key,
            number_token(NumberTokenValue::Number {
                value: number,
                unit: NumberUnit::Px,
            }),
        );
    }
    Ok(())
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
    let font_family = trim_quotes(&args[0]).to_owned();
    let font_size = args[1]
        .parse::<f64>()
        .map_err(|_| "typography size must be numeric".to_owned())?;
    let font_weight = args[2]
        .parse::<u16>()
        .map_err(|_| "typography weight must be numeric".to_owned())?;
    let color = args.get(3).map(|value| value.to_string());

    kit.tokens.typography.insert(
        name.to_owned(),
        typography_token(TypographyTokenValue::Style {
            font_family,
            font_size,
            font_weight,
            line_height: None,
            letter_spacing: None,
            color,
            font_asset: None,
        }),
    );
    Ok(())
}

fn compile_font_directive(name: &str, value: &str, kit: &mut BrandKit) -> Result<(), String> {
    let inner = value
        .strip_prefix("font(")
        .and_then(|inner| inner.strip_suffix(')'))
        .unwrap_or(value);
    let args = split_args(inner);
    let family = args
        .first()
        .map(|value| trim_quotes(value).to_owned())
        .ok_or_else(|| "font expects a family name".to_owned())?;
    let fallback_stack = args
        .get(1)
        .map(|value| trim_quotes(value).split('|').map(str::to_owned).collect())
        .unwrap_or_else(|| vec!["Arial".to_owned(), "sans-serif".to_owned()]);

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
            ],
            fallback_stack,
            scripts: vec!["latin".to_owned()],
            license: FontLicense {
                name: "system".to_owned(),
                embeddable: true,
                subsettable: true,
                source_url: None,
                restrictions: Vec::new(),
            },
            provenance: None,
        },
    );
    Ok(())
}

fn strip_style_comment(raw_line: &str) -> Option<String> {
    let trimmed = raw_line.trim();
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
    input
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .collect()
}

fn trim_quotes(input: &str) -> &str {
    input.trim().trim_matches('"').trim_matches('\'')
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

fn typography_token(value: TypographyTokenValue) -> TypographyToken {
    TypographyToken {
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
