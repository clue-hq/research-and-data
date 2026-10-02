//! Web document schema (v1).
//!
//! A `WebDoc` is a flat node arena per page. Styling is carried exclusively
//! by each node's Tailwind utility `classes` string plus the compiled brand
//! theme; there is no per-node style struct and no fixed page geometry.
//! Row/Column are editor insert-presets (Containers with preset classes),
//! not node kinds.

use lumen_core::{AssetId, AssetRecord, BrandKitRef, NodeId, PageId, SlotKey};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use crate::rich_text::RichTextDocument;

pub const WEB_SCHEMA_VERSION: u32 = 1;

/// Maximum tree depth (root exclusive) accepted by validation and ingestion.
pub const MAX_TREE_DEPTH: usize = 12;

/// Custom-component props are intentionally a small JSON scalar vocabulary.
/// P6.2 derives this map from the component's TypeScript `Props` type; keeping
/// it typed here prevents arbitrary JSON trees from becoming a second document
/// model inside a leaf.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum CustomComponentValue {
    String(String),
    Number(serde_json::Number),
    Boolean(bool),
}

pub const MAX_CUSTOM_COMPONENT_PROPS: usize = 128;
pub const MAX_CUSTOM_COMPONENT_PROP_STRING_BYTES: usize = 65_536;

/// Per-instance values for a cloned fragment's slots. Flat scalars only: the
/// artifact's slot manifest declares what a slot *means* (an `href` slot rides
/// `Text`), and the document stores nothing but the scalar — never markup.
///
/// Unlike `CustomComponentValue` this enum is serde-TAGGED rather than
/// untagged, because `Text` and `Asset` are both JSON strings: an untagged
/// shape cannot tell them apart, so every asset slot would silently come back
/// as text and the round trip would not be value-preserving. The tag is the
/// discriminator, not extra structure — `{"text": "Book a call"}`,
/// `{"asset": "asset_logo_1"}`, `{"visible": false}`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FragmentSlotValue {
    Text(String),
    Asset(String),
    Visible(bool),
}

pub const MAX_FRAGMENT_SLOTS: usize = 64;
pub const MAX_FRAGMENT_SLOT_KEY_CHARS: usize = 64;
pub const MAX_FRAGMENT_SLOT_VALUE_BYTES: usize = 8_192;

/// One human text edit inside a cloned section, keyed by the structural path
/// of the element it replaces.
///
/// `text` is PLAIN text — never markup. The three marks and the relative size
/// step are the whole vocabulary: a clone's typography belongs to the artifact,
/// so this offers a nudge (`size` is a step, not a value) rather than a second
/// styling system that could disagree with the pinned CSS.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FragmentTextOverride {
    pub text: String,
    #[serde(default)]
    pub bold: bool,
    #[serde(default)]
    pub italic: bool,
    #[serde(default)]
    pub underline: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<i8>,
}

pub const MAX_FRAGMENT_TEXT_OVERRIDES: usize = 64;
pub const MAX_FRAGMENT_OVERRIDE_PATH_CHARS: usize = 256;
/// Inclusive relative size steps. A step, not a font size: the artifact owns
/// the scale and this only walks it.
pub const MIN_FRAGMENT_OVERRIDE_SIZE: i8 = -3;
pub const MAX_FRAGMENT_OVERRIDE_SIZE: i8 = 3;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WebDoc {
    pub schema_version: u32,
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub theme: WebThemeRef,
    pub pages: Vec<WebPage>,
    #[serde(default)]
    pub assets: BTreeMap<AssetId, AssetRecord>,
    #[serde(default)]
    pub custom_css: String,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct WebThemeRef {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub brand_kit: Option<BrandKitRef>,
    /// Per-document token value overrides (token name -> CSS color), applied
    /// on top of the kit-compiled theme.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub overrides: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WebPage {
    pub id: PageId,
    pub name: String,
    pub route: String,
    pub root: NodeId,
    pub nodes: BTreeMap<NodeId, WebNode>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WebNode {
    pub id: NodeId,
    #[serde(flatten)]
    pub kind: WebNodeKind,
    #[serde(default)]
    pub classes: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub children: Vec<NodeId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Phase-5 personalization hedge: carried by the schema from day 0,
    /// ignored by every v0 code path.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_key: Option<SlotKey>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum WebNodeKind {
    Section {
        #[serde(default)]
        tag: SectionTag,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        anchor_id: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        background: Option<WebBackgroundImage>,
    },
    Container {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        href: Option<String>,
        #[serde(default)]
        new_tab: bool,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        background: Option<WebBackgroundImage>,
    },
    Text {
        #[serde(default)]
        variant: TextVariant,
        /// Canonical semantic rich text. Lexical is only an editor adapter;
        /// this library-independent document is the persisted source of truth.
        content: RichTextDocument,
    },
    Button {
        label: String,
        #[serde(default)]
        variant: ButtonVariant,
        #[serde(flatten)]
        action: ButtonAction,
    },
    Component {
        #[serde(flatten)]
        spec: ComponentSpec,
    },
    /// Tier-3 custom program output. This node is always a leaf: the document
    /// owns host layout/classes while `artifact_id` pins one immutable compile.
    /// Source and bundle bytes live in the durable account-scoped registry,
    /// never in this document payload.
    CustomComponent {
        slug: String,
        artifact_id: String,
        #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
        props: BTreeMap<String, CustomComponentValue>,
    },
    /// A verbatim cloned section, pinned to one immutable fragment artifact.
    /// Always a leaf, exactly like `CustomComponent`: the sanitized markup and
    /// the scoped CSS live in the durable registry keyed by `fragment_id`, and
    /// the node carries only that id plus flat scalar slot values. No raw HTML
    /// ever enters the document, so no write path can smuggle markup into the
    /// arena — sanitization happens once, at artifact creation.
    Fragment {
        fragment_id: String,
        #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
        slots: BTreeMap<String, FragmentSlotValue>,
        /// Ruling R-A6 (founder, 2026-09-04): the ONE interior edit a human
        /// may make to a clone. D-F3 said a fragment is opaque below its
        /// root; this amends it by exactly one axis — the TEXT of one
        /// element, addressed by structural path — and nothing else. The
        /// artifact stays immutable: an override is a per-instance
        /// substitution applied at render, never a rewrite of the clone.
        #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
        text_overrides: BTreeMap<String, FragmentTextOverride>,
    },
    Image {
        asset_id: AssetId,
        #[serde(default)]
        alt: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        href: Option<String>,
        #[serde(default)]
        new_tab: bool,
    },
    Icon {
        /// Name from the curated `lumen_core::icons` set.
        icon: String,
    },
    Embed {
        #[serde(default)]
        provider: EmbedProvider,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        url: Option<String>,
        /// Rendered inside a sandboxed iframe in both modes.
        #[serde(default)]
        html: String,
    },
}

/// Two trust levels, one sandbox: `Calendly` is the AGENT-authorable
/// allowlisted provider (validated calendly.com URL); `Custom` is the
/// human paste path (any https URL, or a raw snippet) written through the
/// inspector. The iframe sandbox applies to both — the allowlist gates the
/// writer, not the safety.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbedProvider {
    Calendly,
    #[default]
    Custom,
}

/// True when `url` is an `https://` link whose host is exactly `calendly.com`
/// or a `*.calendly.com` subdomain. Parsed by hand (no url crate): scheme
/// must be `https://`, the host runs to the first `/`, `?`, or `#`, and it may
/// carry neither userinfo (`@`) nor a port (`:`).
pub fn calendly_url_is_valid(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://") else {
        return false;
    };
    let host_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let host = rest[..host_end].to_ascii_lowercase();
    if host.is_empty() || host.contains('@') || host.contains(':') {
        return false;
    }
    host == "calendly.com" || host.ends_with(".calendly.com")
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SectionTag {
    #[default]
    Section,
    Header,
    Footer,
}

/// A registered document asset painted behind a Section or Container. These
/// fields are deliberately typed instead of accepting raw style strings: all
/// writers (AI ingest, operations, and the human inspector) therefore produce
/// the same safe rendering and export semantics.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WebBackgroundImage {
    pub asset_id: AssetId,
    #[serde(default)]
    pub fit: WebBackgroundFit,
    #[serde(default)]
    pub position: WebBackgroundPosition,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scrim: Option<WebBackgroundScrim>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WebBackgroundFit {
    #[default]
    Cover,
    Contain,
}

impl WebBackgroundFit {
    pub fn as_css(&self) -> &'static str {
        match self {
            WebBackgroundFit::Cover => "cover",
            WebBackgroundFit::Contain => "contain",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WebBackgroundPosition {
    #[default]
    Center,
    Top,
    Right,
    Bottom,
    Left,
}

impl WebBackgroundPosition {
    pub fn as_css(&self) -> &'static str {
        match self {
            WebBackgroundPosition::Center => "center",
            WebBackgroundPosition::Top => "top",
            WebBackgroundPosition::Right => "right",
            WebBackgroundPosition::Bottom => "bottom",
            WebBackgroundPosition::Left => "left",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WebBackgroundScrim {
    #[serde(default)]
    pub color: WebScrimColor,
    #[serde(default = "default_scrim_opacity")]
    pub opacity: u8,
}

fn default_scrim_opacity() -> u8 {
    50
}

/// Scrims use the document's semantic theme variables. Keeping this list
/// finite guarantees that renderer-generated inline style cannot be used as a
/// CSS injection path while still covering light/dark and brand treatments.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WebScrimColor {
    #[default]
    Dark,
    Light,
    Primary,
    Accent,
    Black,
    White,
}

impl WebScrimColor {
    pub fn as_css_color(&self) -> &'static str {
        match self {
            WebScrimColor::Dark => "var(--color-dark)",
            WebScrimColor::Light => "var(--color-light)",
            WebScrimColor::Primary => "var(--color-primary)",
            WebScrimColor::Accent => "var(--color-accent)",
            WebScrimColor::Black => "#000000",
            WebScrimColor::White => "#ffffff",
        }
    }
}

impl SectionTag {
    pub fn as_str(&self) -> &'static str {
        match self {
            SectionTag::Section => "section",
            SectionTag::Header => "header",
            SectionTag::Footer => "footer",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextVariant {
    Display,
    H1,
    H2,
    H3,
    H4,
    #[default]
    Body,
    Small,
    Overline,
}

impl TextVariant {
    pub fn as_str(&self) -> &'static str {
        match self {
            TextVariant::Display => "display",
            TextVariant::H1 => "h1",
            TextVariant::H2 => "h2",
            TextVariant::H3 => "h3",
            TextVariant::H4 => "h4",
            TextVariant::Body => "body",
            TextVariant::Small => "small",
            TextVariant::Overline => "overline",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "display" => Some(TextVariant::Display),
            "h1" => Some(TextVariant::H1),
            "h2" => Some(TextVariant::H2),
            "h3" => Some(TextVariant::H3),
            "h4" => Some(TextVariant::H4),
            "body" => Some(TextVariant::Body),
            "small" => Some(TextVariant::Small),
            "overline" => Some(TextVariant::Overline),
            _ => None,
        }
    }

    /// The HTML tag the variant renders as.
    pub fn render_tag(&self) -> &'static str {
        match self {
            TextVariant::Display | TextVariant::H1 => "h1",
            TextVariant::H2 => "h2",
            TextVariant::H3 => "h3",
            TextVariant::H4 => "h4",
            TextVariant::Body | TextVariant::Small | TextVariant::Overline => "p",
        }
    }

    /// Body copy can own semantic paragraph/list blocks. Display, headings,
    /// and overlines remain one block so changing a text variant can never
    /// produce invalid heading/list HTML.
    pub fn allows_structured_rich_text(&self) -> bool {
        matches!(self, TextVariant::Body | TextVariant::Small)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ButtonVariant {
    #[default]
    Primary,
    Secondary,
    Outline,
    Ghost,
    Link,
}

impl ButtonVariant {
    pub fn as_str(&self) -> &'static str {
        match self {
            ButtonVariant::Primary => "primary",
            ButtonVariant::Secondary => "secondary",
            ButtonVariant::Outline => "outline",
            ButtonVariant::Ghost => "ghost",
            ButtonVariant::Link => "link",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "" | "primary" => Some(ButtonVariant::Primary),
            "secondary" => Some(ButtonVariant::Secondary),
            "outline" => Some(ButtonVariant::Outline),
            "ghost" => Some(ButtonVariant::Ghost),
            "link" => Some(ButtonVariant::Link),
            _ => None,
        }
    }
}

/// Untagged + flattened: legacy button JSON ({href, new_tab}) deserializes
/// as Href with zero migration; Command carries the invoker wiring
/// ({command, command_target}).
///
/// Deserialize is hand-written instead of `#[serde(untagged)]`: the derive's
/// "data did not match any variant" error names neither the accepted shapes
/// nor the actual mistake, which live-cost an agent turn several rejected
/// batches (kebab "show-modal" where JSON wants "show_modal"). Every failure
/// path here says exactly what a button action may be.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum ButtonAction {
    Command {
        command: ButtonCommand,
        command_target: NodeId,
    },
    Href {
        href: String,
        #[serde(default)]
        new_tab: bool,
    },
}

impl<'de> Deserialize<'de> for ButtonAction {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        use serde::de::Error;

        // Raw tolerates unknown keys: under #[serde(flatten)] this map holds
        // whatever the outer Button struct did not consume.
        #[derive(Deserialize)]
        struct Raw {
            command: Option<String>,
            command_target: Option<NodeId>,
            href: Option<String>,
            #[serde(default)]
            new_tab: bool,
        }

        const SHAPES: &str = "a button action is either a link {href, new_tab?} \
                              or a trigger {command: \"show_modal\"|\"close\", command_target: \"<dialog node id>\"}";

        let raw = Raw::deserialize(deserializer)?;
        match (raw.command, raw.href) {
            (Some(command), None) => {
                let command = match command.as_str() {
                    "show_modal" => ButtonCommand::ShowModal,
                    "close" => ButtonCommand::Close,
                    other => {
                        let hint = if ButtonCommand::parse_html_attr(other).is_some() {
                            " (JSON uses the snake_case form, not the HTML kebab attribute)"
                        } else {
                            ""
                        };
                        return Err(D::Error::custom(format!(
                            "unknown button command `{other}`{hint}; valid: \"show_modal\", \"close\""
                        )));
                    }
                };
                let command_target = raw.command_target.ok_or_else(|| {
                    D::Error::custom(
                        "command button is missing `command_target` (the dialog's node id)",
                    )
                })?;
                Ok(ButtonAction::Command {
                    command,
                    command_target,
                })
            }
            (None, Some(href)) => Ok(ButtonAction::Href {
                href,
                new_tab: raw.new_tab,
            }),
            (Some(_), Some(_)) => Err(D::Error::custom(format!(
                "button carries both `href` and `command`; {SHAPES}"
            ))),
            (None, None) => Err(D::Error::custom(format!(
                "button action fields missing; {SHAPES}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ButtonCommand {
    ShowModal,
    Close,
}

impl ButtonCommand {
    /// The HTML invoker `command` attribute value (kebab, not the JSON form).
    pub fn as_html_attr(&self) -> &'static str {
        match self {
            ButtonCommand::ShowModal => "show-modal",
            ButtonCommand::Close => "close",
        }
    }

    pub fn parse_html_attr(value: &str) -> Option<Self> {
        match value {
            "show-modal" => Some(ButtonCommand::ShowModal),
            "close" => Some(ButtonCommand::Close),
            _ => None,
        }
    }
}

/// Tier-2 platform components. Children are ordinary nodes; behavior comes
/// from native HTML + the ONE versioned platform runtime, never authored JS.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "component", rename_all = "snake_case")]
pub enum ComponentSpec {
    Dialog {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        aria_label: Option<String>,
    },
    Accordion {
        #[serde(default)]
        single_open: bool,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        default_open: Option<u32>,
    },
    Marquee {
        #[serde(default = "default_marquee_speed")]
        speed_s: u16,
        #[serde(default)]
        direction: MarqueeDirection,
        #[serde(default = "default_true")]
        pause_on_hover: bool,
    },
    NavMenu,
    Carousel {
        #[serde(default = "default_true")]
        show_arrows: bool,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        autoplay_s: Option<u16>,
    },
    Tabs {
        #[serde(default)]
        default_tab: u32,
    },
}

fn default_marquee_speed() -> u16 {
    30
}

fn default_true() -> bool {
    true
}

impl ComponentSpec {
    pub fn component_name(&self) -> &'static str {
        match self {
            ComponentSpec::Dialog { .. } => "dialog",
            ComponentSpec::Accordion { .. } => "accordion",
            ComponentSpec::Marquee { .. } => "marquee",
            ComponentSpec::NavMenu => "nav_menu",
            ComponentSpec::Carousel { .. } => "carousel",
            ComponentSpec::Tabs { .. } => "tabs",
        }
    }
}

/// Registry slugs double as the stable source-directory id. They use the
/// Mutiny-compatible kebab grammar, bounded so paths and inspector labels stay
/// manageable. Consecutive/trailing hyphens are rejected.
pub fn custom_component_slug_is_valid(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.is_empty() || bytes.len() > 64 {
        return false;
    }
    if !bytes[0].is_ascii_lowercase() && !bytes[0].is_ascii_digit() {
        return false;
    }
    if !bytes[bytes.len() - 1].is_ascii_lowercase()
        && !bytes[bytes.len() - 1].is_ascii_digit()
    {
        return false;
    }
    let mut previous_hyphen = false;
    for byte in bytes {
        let hyphen = *byte == b'-';
        if !byte.is_ascii_lowercase() && !byte.is_ascii_digit() && !hyphen {
            return false;
        }
        if hyphen && previous_hyphen {
            return false;
        }
        previous_hyphen = hyphen;
    }
    true
}

/// Artifact ids are content identities minted by the registry:
/// `ccart_` + one lowercase SHA-256 digest.
pub fn custom_component_artifact_id_is_valid(value: &str) -> bool {
    value.strip_prefix("ccart_").is_some_and(|digest| {
        digest.len() == 64
            && digest
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    })
}

/// Props originate from TypeScript object fields, so use the JavaScript
/// identifier grammar supported by the P6 compiler rather than accepting
/// arbitrary attacker-controlled keys.
pub fn custom_component_prop_name_is_valid(value: &str) -> bool {
    let mut chars = value.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if value.len() > 64 || !(first.is_ascii_alphabetic() || first == '_' || first == '$') {
        return false;
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '$')
}

pub fn custom_component_props_issue(
    props: &BTreeMap<String, CustomComponentValue>,
) -> Option<String> {
    if props.len() > MAX_CUSTOM_COMPONENT_PROPS {
        return Some(format!(
            "has {} props; maximum is {MAX_CUSTOM_COMPONENT_PROPS}",
            props.len()
        ));
    }
    for (name, value) in props {
        if !custom_component_prop_name_is_valid(name) {
            return Some(format!("prop name `{name}` is not a supported identifier"));
        }
        if let CustomComponentValue::String(text) = value {
            if text.len() > MAX_CUSTOM_COMPONENT_PROP_STRING_BYTES {
                return Some(format!(
                    "string prop `{name}` exceeds {MAX_CUSTOM_COMPONENT_PROP_STRING_BYTES} bytes"
                ));
            }
        }
    }
    None
}

/// Fragment artifact ids are content identities minted by the registry:
/// `frag_` + exactly 16 lowercase hex characters (a truncated SHA-256).
///
/// The shape check is load-bearing beyond identity: the id is interpolated
/// into a CSS class (`lumen-frag-<id>`) and an HTML wrapper class downstream,
/// so an id carrying `<`, whitespace, or a quote is refused here rather than
/// escaped there.
pub fn fragment_id_is_valid(value: &str) -> bool {
    value.strip_prefix("frag_").is_some_and(|digest| {
        digest.len() == 16
            && digest
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    })
}

/// The ONE class a fragment's wrapper and its stored CSS agree on:
/// `lumen-frag-<16 hex>` — the `frag_` prefix stripped, because
/// `.lumen-frag-frag_…` says "frag" twice and the prefix carries no
/// information a class name needs.
///
/// `None` for any id that is not a valid fragment id, which is what makes the
/// re-check structural rather than a habit: a document loaded straight from
/// storage may never have been through `validate_web_doc`, and this class is
/// interpolated into live markup. The Python side's
/// `lumen_api.fragments.fragment_wrapper_class` is the same spelling on the
/// other side of the seam — the artifact's CSS is scoped under whatever IT
/// returns, so a divergence here renders the section unstyled.
pub fn fragment_wrapper_class(fragment_id: &str) -> Option<String> {
    fragment_id_is_valid(fragment_id)
        .then(|| format!("lumen-frag-{}", &fragment_id["frag_".len()..]))
}

/// Slot keys come from the artifact's slot manifest, which is machine-minted
/// from the cloned markup, so the grammar can be narrow: 1–64 characters of
/// `[a-z0-9_-]` and nothing else.
///
/// Narrow on purpose. A key is later interpolated into markup and selectors,
/// and the only way to be sure that is safe on every downstream path is to
/// refuse anything needing escaping at the door — no uppercase, no dots or
/// slashes, no whitespace, no quotes or angle brackets. This was tightened
/// from "printable ASCII" before any stored document carried a fragment key;
/// tightening later would have been a breaking validation change.
pub fn fragment_slot_key_is_valid(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_FRAGMENT_SLOT_KEY_CHARS
        && value
            .bytes()
            .all(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9' | b'_' | b'-'))
}

/// Bounds for one node's slot map. Every breach is refused (the caller turns
/// this into a typed error or an Error diagnostic); nothing is truncated.
pub fn fragment_slots_issue(slots: &BTreeMap<String, FragmentSlotValue>) -> Option<String> {
    if slots.len() > MAX_FRAGMENT_SLOTS {
        return Some(format!(
            "has {} slots; maximum is {MAX_FRAGMENT_SLOTS}",
            slots.len()
        ));
    }
    for (key, value) in slots {
        if !fragment_slot_key_is_valid(key) {
            return Some(format!(
                "slot key {key:?} is not a supported key; keys are 1–{MAX_FRAGMENT_SLOT_KEY_CHARS} characters of [a-z0-9_-]"
            ));
        }
        match value {
            FragmentSlotValue::Text(text) => {
                if text.len() > MAX_FRAGMENT_SLOT_VALUE_BYTES {
                    return Some(format!(
                        "text slot `{key}` exceeds {MAX_FRAGMENT_SLOT_VALUE_BYTES} bytes"
                    ));
                }
            }
            FragmentSlotValue::Asset(asset_id) => {
                if asset_id.len() > MAX_FRAGMENT_SLOT_VALUE_BYTES {
                    return Some(format!(
                        "asset slot `{key}` exceeds {MAX_FRAGMENT_SLOT_VALUE_BYTES} bytes"
                    ));
                }
                // One asset-id grammar for the whole engine: the stable-id
                // constructor every other asset reference is built from.
                if AssetId::new(asset_id.clone()).is_err() {
                    return Some(format!("asset slot `{key}` is not an asset id"));
                }
            }
            FragmentSlotValue::Visible(_) => {}
        }
    }
    None
}

/// The grammar of a text-override key: `^(:nth-child\(\d+\)( > )?)+$`, with
/// every index ≥ 1.
///
/// STRUCTURAL only — positions, never names. A path may say "the second child
/// of the first child", and it may not say `div`, `.headline`, or `#hero`.
/// That is the whole point: a name-bearing selector would let a write path
/// address the clone by its markup and, downstream, be interpolated into a
/// selector or a query. Positions carry no characters that need escaping, so
/// what the editor can address is bounded at the door rather than sanitized
/// wherever it lands.
///
/// Written by hand — this crate has no regex dependency and the grammar is
/// small enough that adding one would cost more than it saves.
pub fn fragment_override_path_is_valid(path: &str) -> bool {
    if path.is_empty() || path.len() > MAX_FRAGMENT_OVERRIDE_PATH_CHARS {
        return false;
    }
    let mut rest = path;
    loop {
        let Some(after_open) = rest.strip_prefix(":nth-child(") else {
            return false;
        };
        let Some(close) = after_open.find(')') else {
            return false;
        };
        let digits = &after_open[..close];
        // `:nth-child` is 1-based, so index 0 addresses nothing; a leading
        // zero is refused with it, keeping one spelling per position.
        if digits.is_empty()
            || digits.starts_with('0')
            || !digits.bytes().all(|byte| byte.is_ascii_digit())
        {
            return false;
        }
        rest = &after_open[close + 1..];
        if rest.is_empty() {
            return true;
        }
        // A separator must be followed by another step: a trailing ` > `
        // addresses nothing.
        let Some(after_separator) = rest.strip_prefix(" > ") else {
            return false;
        };
        if after_separator.is_empty() {
            return false;
        }
        rest = after_separator;
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MarqueeDirection {
    #[default]
    Left,
    Right,
}

impl WebNodeKind {
    pub fn kind_name(&self) -> &'static str {
        match self {
            WebNodeKind::Section { .. } => "section",
            WebNodeKind::Container { .. } => "container",
            WebNodeKind::Text { .. } => "text",
            WebNodeKind::Button { .. } => "button",
            WebNodeKind::Component { .. } => "component",
            WebNodeKind::CustomComponent { .. } => "custom_component",
            WebNodeKind::Fragment { .. } => "fragment",
            WebNodeKind::Image { .. } => "image",
            WebNodeKind::Icon { .. } => "icon",
            WebNodeKind::Embed { .. } => "embed",
        }
    }

    /// Section, Container, and built-in Component may hold children. Custom
    /// components and fragments are deliberately absent: both are always
    /// leaves, and this list is the single place leaf-ness is decided (ops
    /// insert/move and validation's LUMW0007 both read it).
    pub fn is_branch(&self) -> bool {
        matches!(
            self,
            WebNodeKind::Section { .. }
                | WebNodeKind::Container { .. }
                | WebNodeKind::Component { .. }
        )
    }
}

impl WebNode {
    pub fn branch(id: NodeId, kind: WebNodeKind, classes: impl Into<String>) -> Self {
        Self {
            id,
            kind,
            classes: classes.into(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        }
    }
}

impl WebDoc {
    /// An empty web document: one page ("Home", route `/`) whose root is an
    /// empty Container. The root node itself is not a Section; validation
    /// requires every root child to be one.
    pub fn new(
        id: impl Into<String>,
        title: impl Into<String>,
        brand_kit: Option<BrandKitRef>,
    ) -> Self {
        let root_id = NodeId::from("root");
        let root = WebNode::branch(
            root_id.clone(),
            WebNodeKind::Container {
                href: None,
                new_tab: false,
                background: None,
            },
            "",
        );
        let mut nodes = BTreeMap::new();
        nodes.insert(root_id.clone(), root);
        Self {
            schema_version: WEB_SCHEMA_VERSION,
            id: id.into(),
            title: title.into(),
            theme: WebThemeRef {
                brand_kit,
                overrides: BTreeMap::new(),
            },
            pages: vec![WebPage {
                id: PageId::from("home"),
                name: "Home".to_owned(),
                route: "/".to_owned(),
                root: root_id,
                nodes,
            }],
            assets: BTreeMap::new(),
            custom_css: String::new(),
        }
    }

    pub fn page(&self, page_id: &PageId) -> Option<&WebPage> {
        self.pages.iter().find(|page| &page.id == page_id)
    }

    pub fn page_mut(&mut self, page_id: &PageId) -> Option<&mut WebPage> {
        self.pages.iter_mut().find(|page| &page.id == page_id)
    }
}

impl WebPage {
    pub fn node(&self, id: &NodeId) -> Option<&WebNode> {
        self.nodes.get(id)
    }

    /// Parent lookup by child-list scan; the arena stores no parent pointers.
    pub fn parent_of(&self, id: &NodeId) -> Option<&NodeId> {
        self.nodes
            .values()
            .find(|node| node.children.contains(id))
            .map(|node| &node.id)
    }

    /// Ids reachable from the root, in document (pre-)order.
    pub fn reachable_ids(&self) -> Vec<NodeId> {
        let mut out = Vec::new();
        let mut stack = vec![self.root.clone()];
        while let Some(id) = stack.pop() {
            if let Some(node) = self.nodes.get(&id) {
                out.push(id);
                for child in node.children.iter().rev() {
                    stack.push(child.clone());
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_doc_round_trips_through_json() {
        let doc = WebDoc::new("doc_1", "Test site", None);
        let json = serde_json::to_string(&doc).expect("serialize");
        let back: WebDoc = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(doc, back);
        assert_eq!(back.schema_version, WEB_SCHEMA_VERSION);
        assert_eq!(back.pages.len(), 1);
        assert_eq!(back.pages[0].route, "/");
    }

    #[test]
    fn node_kind_serializes_with_flattened_tag() {
        let node = WebNode {
            id: NodeId::from("t1"),
            kind: WebNodeKind::Text {
                variant: TextVariant::H2,
                content: "Hello".to_owned().into(),
            },
            classes: "text-dark".to_owned(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "text");
        assert_eq!(value["variant"], "h2");
        assert_eq!(value["content"]["schema_version"], 1);
        assert_eq!(value["content"]["blocks"][0]["type"], "paragraph");
        assert_eq!(value["content"]["blocks"][0]["children"][0]["text"], "Hello");
        assert_eq!(value["classes"], "text-dark");
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, node);
    }

    #[test]
    fn custom_component_leaf_round_trips_typed_props_and_pin() {
        let artifact_id = format!("ccart_{}", "a".repeat(64));
        let node = WebNode {
            id: NodeId::from("cc_form"),
            kind: WebNodeKind::CustomComponent {
                slug: "book-a-call".to_owned(),
                artifact_id: artifact_id.clone(),
                props: BTreeMap::from([
                    (
                        "headline".to_owned(),
                        CustomComponentValue::String("Book a call".to_owned()),
                    ),
                    (
                        "seats".to_owned(),
                        CustomComponentValue::Number(serde_json::Number::from(12)),
                    ),
                    (
                        "showLogo".to_owned(),
                        CustomComponentValue::Boolean(true),
                    ),
                ]),
            },
            classes: "w-[480px] h-[320px]".to_owned(),
            children: Vec::new(),
            name: Some("Booking form".to_owned()),
            slot_key: None,
        };

        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "custom_component");
        assert_eq!(value["slug"], "book-a-call");
        assert_eq!(value["artifact_id"], artifact_id);
        assert_eq!(value["props"]["headline"], "Book a call");
        assert_eq!(value["props"]["seats"], 12);
        assert_eq!(value["props"]["showLogo"], true);
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, node);
        assert!(!back.kind.is_branch());
        assert_eq!(back.kind.kind_name(), "custom_component");
    }

    #[test]
    fn custom_component_rejects_nested_prop_values_during_deserialization() {
        let artifact_id = format!("ccart_{}", "b".repeat(64));
        for props in [
            serde_json::json!({"nested": {"unsafe": true}}),
            serde_json::json!({"items": ["one", "two"]}),
            serde_json::json!({"empty": null}),
        ] {
            let value = serde_json::json!({
                "id": "cc_bad",
                "kind": "custom_component",
                "slug": "safe-slug",
                "artifact_id": artifact_id,
                "props": props,
                "classes": ""
            });
            assert!(
                serde_json::from_value::<WebNode>(value).is_err(),
                "nested/null JSON must not enter the typed props map"
            );
        }
    }

    #[test]
    fn custom_component_identity_grammars_are_bounded() {
        assert!(custom_component_slug_is_valid("book-a-call"));
        assert!(custom_component_slug_is_valid("chart2"));
        for bad in [
            "",
            "Book-a-call",
            "-book",
            "book-",
            "book--call",
            "book_call",
        ] {
            assert!(!custom_component_slug_is_valid(bad), "{bad}");
        }
        assert!(custom_component_artifact_id_is_valid(&format!(
            "ccart_{}",
            "0".repeat(64)
        )));
        assert!(!custom_component_artifact_id_is_valid("ccart_abc"));
        assert!(!custom_component_artifact_id_is_valid(&format!(
            "ccart_{}",
            "A".repeat(64)
        )));
        assert!(custom_component_prop_name_is_valid("showLogo"));
        assert!(custom_component_prop_name_is_valid("_private"));
        assert!(!custom_component_prop_name_is_valid(""));
        assert!(!custom_component_prop_name_is_valid("bad-key"));
        assert!(!custom_component_prop_name_is_valid("2bad"));
    }

    fn fragment_kind(fragment_id: &str, slots: BTreeMap<String, FragmentSlotValue>) -> WebNodeKind {
        WebNodeKind::Fragment {
            fragment_id: fragment_id.to_owned(),
            slots,
            text_overrides: BTreeMap::new(),
        }
    }

    #[test]
    fn fragment_override_paths_are_structural_only() {
        for good in [
            ":nth-child(1)",
            ":nth-child(12)",
            ":nth-child(1) > :nth-child(2)",
            ":nth-child(3) > :nth-child(1) > :nth-child(9)",
        ] {
            assert!(fragment_override_path_is_valid(good), "{good:?}");
        }
        for bad in [
            // `:nth-child` is 1-based; 0 addresses nothing.
            ":nth-child(0)",
            ":nth-child(01)",
            // Name-bearing selectors are the whole reason for the grammar.
            "div > h2",
            ".headline",
            "#hero",
            ":nth-child(1) > h2",
            // Separator shapes.
            ":nth-child(1) > ",
            ":nth-child(1)>:nth-child(2)",
            ":nth-child(1) >> :nth-child(2)",
            ":nth-child(1):nth-child(2)",
            "",
            // Malformed steps.
            ":nth-child(",
            ":nth-child()",
            ":nth-child(a)",
            ":nth-child(1",
            ":nth-child(1))",
        ] {
            assert!(!fragment_override_path_is_valid(bad), "{bad:?}");
        }

        // Bounded length: 256 characters is the ceiling, 257 is refused.
        let step = ":nth-child(1)";
        let separator = " > ";
        let mut path = step.to_owned();
        while path.len() + separator.len() + step.len() <= MAX_FRAGMENT_OVERRIDE_PATH_CHARS {
            path.push_str(separator);
            path.push_str(step);
        }
        assert!(path.len() <= MAX_FRAGMENT_OVERRIDE_PATH_CHARS);
        assert!(fragment_override_path_is_valid(&path), "{path:?}");
        let long = format!(":nth-child({})", "1".repeat(257 - ":nth-child()".len()));
        assert_eq!(long.len(), 257);
        assert!(!fragment_override_path_is_valid(&long), "{long:?}");
    }

    #[test]
    fn fragment_text_overrides_round_trip_and_omit_the_empty_map() {
        // The empty map is skipped on the way out, so a fragment that carries
        // no human edit serializes exactly as it did before R-A6.
        let bare = WebNode {
            id: NodeId::from("frg_hero"),
            kind: fragment_kind("frag_0123456789abcdef", BTreeMap::new()),
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let json = serde_json::to_string(&bare).expect("serialize");
        assert!(!json.contains("text_overrides"), "{json}");

        let mut edited = bare.clone();
        let WebNodeKind::Fragment { text_overrides, .. } = &mut edited.kind else {
            panic!("fragment");
        };
        text_overrides.insert(
            ":nth-child(1)".to_owned(),
            FragmentTextOverride {
                text: "Shorter".to_owned(),
                bold: true,
                italic: false,
                underline: false,
                size: Some(1),
            },
        );
        let value = serde_json::to_value(&edited).expect("serialize");
        assert_eq!(
            value["text_overrides"][":nth-child(1)"],
            serde_json::json!({"text": "Shorter", "bold": true, "italic": false, "underline": false, "size": 1})
        );
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, edited);

        // A missing `size` is None and is not written back out.
        let plain = FragmentTextOverride {
            text: "Plain".to_owned(),
            bold: false,
            italic: false,
            underline: false,
            size: None,
        };
        let plain_json = serde_json::to_string(&plain).expect("serialize");
        assert!(!plain_json.contains("size"), "{plain_json}");
        assert_eq!(
            serde_json::from_str::<FragmentTextOverride>(r#"{"text":"Plain"}"#)
                .expect("deserialize"),
            plain
        );
    }

    #[test]
    fn fragment_leaf_round_trips_all_three_slot_value_kinds() {
        let node = WebNode {
            id: NodeId::from("frg_hero"),
            kind: fragment_kind(
                "frag_0123456789abcdef",
                BTreeMap::from([
                    (
                        "headline".to_owned(),
                        FragmentSlotValue::Text("Book a call".to_owned()),
                    ),
                    (
                        "logo".to_owned(),
                        FragmentSlotValue::Asset("asset_logo_1".to_owned()),
                    ),
                    ("badge".to_owned(), FragmentSlotValue::Visible(false)),
                ]),
            ),
            classes: "w-full".to_owned(),
            children: Vec::new(),
            name: Some("Cloned hero".to_owned()),
            slot_key: None,
        };

        let json = serde_json::to_string(&node).expect("serialize");
        let back: WebNode = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(back, node, "every slot value kind survives the round trip");
        assert_eq!(
            serde_json::to_string(&back).expect("re-serialize"),
            json,
            "re-serialization is byte-identical"
        );

        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "fragment");
        assert_eq!(value["fragment_id"], "frag_0123456789abcdef");
        assert_eq!(value["slots"]["headline"]["text"], "Book a call");
        assert_eq!(value["slots"]["logo"]["asset"], "asset_logo_1");
        assert_eq!(value["slots"]["badge"]["visible"], false);
        assert!(!back.kind.is_branch(), "a fragment is always a leaf");
        assert_eq!(back.kind.kind_name(), "fragment");
    }

    #[test]
    fn fragment_asset_slot_never_decays_into_a_text_slot() {
        // The one shape hazard of this vocabulary: Text and Asset are both JSON
        // strings, so a tag-less encoding would silently reclassify every asset
        // slot as text on the way back in.
        let kind = fragment_kind(
            &format!("frag_{}", "a".repeat(16)),
            BTreeMap::from([(
                "logo".to_owned(),
                FragmentSlotValue::Asset("asset_logo_1".to_owned()),
            )]),
        );
        let back: WebNodeKind =
            serde_json::from_value(serde_json::to_value(&kind).expect("serialize"))
                .expect("deserialize");
        assert_eq!(back, kind);
    }

    #[test]
    fn fragment_with_no_slots_round_trips_and_omits_the_empty_map() {
        // The shape the registry mints most often: a cloned section with
        // nothing parameterized yet. `slots` is skipped on the way out and
        // defaults on the way back in, so the absent map is not a special case.
        let node = WebNode {
            id: NodeId::from("frg_plain"),
            kind: fragment_kind("frag_00112233445566ff", BTreeMap::new()),
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let json = serde_json::to_string(&node).expect("serialize");
        assert!(!json.contains("slots"), "{json}");
        let back: WebNode = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(back, node);
        assert_eq!(
            serde_json::to_string(&back).expect("re-serialize"),
            json,
            "re-serialization is byte-identical"
        );
        let WebNodeKind::Fragment { slots, .. } = &back.kind else {
            panic!("fragment");
        };
        assert!(slots.is_empty());
        assert_eq!(fragment_slots_issue(slots), None);
    }

    #[test]
    fn fragment_slots_reject_nested_json_during_deserialization() {
        for slots in [
            serde_json::json!({"headline": {"text": {"nested": true}}}),
            serde_json::json!({"headline": "bare string"}),
            serde_json::json!({"headline": {"html": "<script>alert(1)</script>"}}),
            serde_json::json!({"headline": null}),
        ] {
            let value = serde_json::json!({
                "id": "frg_bad",
                "kind": "fragment",
                "fragment_id": "frag_0123456789abcdef",
                "slots": slots,
                "classes": ""
            });
            assert!(
                serde_json::from_value::<WebNode>(value).is_err(),
                "only the typed scalar slot vocabulary may enter the document"
            );
        }
    }

    #[test]
    fn fragment_id_grammar_is_bounded() {
        assert!(fragment_id_is_valid("frag_0123456789abcdef"));
        assert!(fragment_id_is_valid(&format!("frag_{}", "f".repeat(16))));
        for bad in [
            "",
            "frag_",
            "frag",
            "ccart_0123456789abcdef",
            "frag_0123456789abcde",   // 15 hex chars
            "frag_0123456789abcdef0", // 17 hex chars
            "frag_0123456789ABCDEF",  // uppercase hex
            "frag_0123456789abcdeg",  // non-hex char
            "frag_<script>abcdef",
            "frag_0123456789abcd ef",
            "frag_\"0123456789abcd",
            " frag_0123456789abcdef",
            "frag_0123456789abcdef ",
        ] {
            assert!(!fragment_id_is_valid(bad), "{bad:?}");
        }
    }

    #[test]
    fn fragment_slot_bounds_refuse_rather_than_truncate() {
        let ok = BTreeMap::from([(
            "headline".to_owned(),
            FragmentSlotValue::Text("hi".to_owned()),
        )]);
        assert_eq!(fragment_slots_issue(&ok), None);

        // Keys: non-empty, at most 64 chars, and strictly [a-z0-9_-]. The
        // grammar is narrow because keys are machine-minted by the artifact
        // annotator and then interpolated into markup and selectors — nothing
        // that needs escaping downstream may enter the document at all.
        for bad_key in [
            String::new(),
            "k".repeat(MAX_FRAGMENT_SLOT_KEY_CHARS + 1),
            "héadline".to_owned(),
            "head\nline".to_owned(),
            "head\u{0}line".to_owned(),
            "head line".to_owned(),
            "head<line".to_owned(),
            "head\"line".to_owned(),
            "head'line".to_owned(),
            "Headline".to_owned(),
            "head.line".to_owned(),
            "head/line".to_owned(),
            "head:line".to_owned(),
            "{headline}".to_owned(),
        ] {
            let slots =
                BTreeMap::from([(bad_key.clone(), FragmentSlotValue::Text("hi".to_owned()))]);
            assert!(fragment_slots_issue(&slots).is_some(), "{bad_key:?}");
        }
        for good_key in ["headline", "cta-primary", "logo_2", "s", "0"] {
            let slots = BTreeMap::from([(
                good_key.to_owned(),
                FragmentSlotValue::Text("hi".to_owned()),
            )]);
            assert_eq!(fragment_slots_issue(&slots), None, "{good_key}");
        }
        assert_eq!(
            fragment_slots_issue(&BTreeMap::from([(
                "k".repeat(MAX_FRAGMENT_SLOT_KEY_CHARS),
                FragmentSlotValue::Text("hi".to_owned())
            )])),
            None,
            "exactly at the key bound is accepted"
        );

        // Values: text and asset scalars are bounded at 8 KB.
        assert!(fragment_slots_issue(&BTreeMap::from([(
            "headline".to_owned(),
            FragmentSlotValue::Text("x".repeat(MAX_FRAGMENT_SLOT_VALUE_BYTES + 1))
        )]))
        .is_some());
        assert_eq!(
            fragment_slots_issue(&BTreeMap::from([(
                "headline".to_owned(),
                FragmentSlotValue::Text("x".repeat(MAX_FRAGMENT_SLOT_VALUE_BYTES))
            )])),
            None,
            "exactly at the value bound is accepted"
        );

        // Asset slots carry asset ids, not free text.
        for bad_asset in ["", "asset logo", "asset/logo", "<script>", "asset\"1"] {
            assert!(
                fragment_slots_issue(&BTreeMap::from([(
                    "logo".to_owned(),
                    FragmentSlotValue::Asset(bad_asset.to_owned())
                )]))
                .is_some(),
                "{bad_asset:?}"
            );
        }
        assert_eq!(
            fragment_slots_issue(&BTreeMap::from([(
                "logo".to_owned(),
                FragmentSlotValue::Asset("asset_logo-1".to_owned())
            )])),
            None
        );

        // At most 64 slots per node.
        let many: BTreeMap<String, FragmentSlotValue> = (0..=MAX_FRAGMENT_SLOTS)
            .map(|index| (format!("slot_{index}"), FragmentSlotValue::Visible(true)))
            .collect();
        assert_eq!(many.len(), MAX_FRAGMENT_SLOTS + 1);
        assert!(fragment_slots_issue(&many).is_some());
        let at_bound: BTreeMap<String, FragmentSlotValue> = (0..MAX_FRAGMENT_SLOTS)
            .map(|index| (format!("slot_{index}"), FragmentSlotValue::Visible(true)))
            .collect();
        assert_eq!(fragment_slots_issue(&at_bound), None);
    }

    #[test]
    fn legacy_button_json_deserializes_as_href() {
        let json = r#"{"kind":"button","label":"Go","href":"https://x.com","variant":"primary","new_tab":false}"#;
        let kind: WebNodeKind = serde_json::from_str(json).expect("deserialize");
        let WebNodeKind::Button { action, .. } = &kind else {
            panic!("button node");
        };
        assert!(matches!(action, ButtonAction::Href { href, .. } if href == "https://x.com"));
        let back = serde_json::to_string(&kind).expect("serialize");
        assert!(back.contains("\"href\""), "{back}");
    }

    #[test]
    fn command_button_round_trips() {
        let json = r#"{"kind":"button","label":"Go","variant":"primary","command":"show_modal","command_target":"dlg_1"}"#;
        let kind: WebNodeKind = serde_json::from_str(json).expect("deserialize");
        let WebNodeKind::Button { action, .. } = &kind else {
            panic!("button node");
        };
        assert!(matches!(
            action,
            ButtonAction::Command { command: ButtonCommand::ShowModal, command_target }
                if command_target.as_str() == "dlg_1"
        ));
        let value = serde_json::to_value(&kind).expect("serialize");
        assert_eq!(value["command"], "show_modal");
        assert_eq!(value["command_target"], "dlg_1");
        let back: WebNodeKind = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, kind);
    }

    #[test]
    fn button_action_errors_name_the_accepted_shapes() {
        // Kebab HTML form in JSON: the error must teach the snake_case form.
        let err = serde_json::from_str::<WebNodeKind>(
            r#"{"kind":"button","label":"Go","command":"show-modal","command_target":"dlg_1"}"#,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("show_modal"), "{err}");
        assert!(err.contains("snake_case"), "{err}");

        // Command without a target.
        let err = serde_json::from_str::<WebNodeKind>(
            r#"{"kind":"button","label":"Go","command":"close"}"#,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("command_target"), "{err}");

        // Both shapes at once.
        let err = serde_json::from_str::<WebNodeKind>(
            r#"{"kind":"button","label":"Go","href":"https://x.com","command":"close","command_target":"dlg_1"}"#,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("both"), "{err}");

        // Neither shape.
        let err = serde_json::from_str::<WebNodeKind>(r#"{"kind":"button","label":"Go"}"#)
            .unwrap_err()
            .to_string();
        assert!(err.contains("link {href"), "{err}");
    }

    #[test]
    fn button_command_html_attrs() {
        assert_eq!(ButtonCommand::ShowModal.as_html_attr(), "show-modal");
        assert_eq!(ButtonCommand::Close.as_html_attr(), "close");
        assert_eq!(
            ButtonCommand::parse_html_attr("show-modal"),
            Some(ButtonCommand::ShowModal)
        );
        assert_eq!(
            ButtonCommand::parse_html_attr("close"),
            Some(ButtonCommand::Close)
        );
        assert_eq!(ButtonCommand::parse_html_attr("show_modal"), None);
    }

    #[test]
    fn component_node_round_trips() {
        let node = WebNode {
            id: NodeId::from("dlg_book"),
            kind: WebNodeKind::Component {
                spec: ComponentSpec::Dialog {
                    aria_label: Some("Book a call".to_owned()),
                },
            },
            classes: "max-w-[480px]".to_owned(),
            children: vec![NodeId::from("txt_1")],
            name: None,
            slot_key: None,
        };
        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "component");
        assert_eq!(value["component"], "dialog");
        assert_eq!(value["aria_label"], "Book a call");
        assert_eq!(value["classes"], "max-w-[480px]");
        assert_eq!(value["children"][0], "txt_1");
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, node);
        assert!(node.kind.is_branch());
        assert_eq!(node.kind.kind_name(), "component");
    }

    #[test]
    fn marquee_defaults_fill_in() {
        let json = r#"{"kind":"component","component":"marquee"}"#;
        let kind: WebNodeKind = serde_json::from_str(json).expect("deserialize");
        let WebNodeKind::Component {
            spec:
                ComponentSpec::Marquee {
                    speed_s,
                    direction,
                    pause_on_hover,
                },
        } = kind
        else {
            panic!("marquee component");
        };
        assert_eq!(speed_s, 30);
        assert_eq!(direction, MarqueeDirection::Left);
        assert!(pause_on_hover);
    }

    #[test]
    fn legacy_embed_deserializes_as_custom() {
        let json = r#"{"kind":"embed","html":"<iframe src=\"x\"></iframe>"}"#;
        let kind: WebNodeKind = serde_json::from_str(json).expect("deserialize");
        let WebNodeKind::Embed {
            provider,
            url,
            html,
        } = &kind
        else {
            panic!("embed node");
        };
        assert_eq!(*provider, EmbedProvider::Custom);
        assert_eq!(*url, None);
        assert_eq!(html, "<iframe src=\"x\"></iframe>");
    }

    #[test]
    fn calendly_embed_round_trips() {
        let node = WebNode {
            id: NodeId::from("emb_1"),
            kind: WebNodeKind::Embed {
                provider: EmbedProvider::Calendly,
                url: Some("https://calendly.com/team/intro".to_owned()),
                html: String::new(),
            },
            classes: "w-full".to_owned(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "embed");
        assert_eq!(value["provider"], "calendly");
        assert_eq!(value["url"], "https://calendly.com/team/intro");
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, node);
    }

    #[test]
    fn calendly_url_validation() {
        assert!(calendly_url_is_valid("https://calendly.com/team/intro"));
        assert!(calendly_url_is_valid("https://acme.calendly.com/demo"));
        assert!(calendly_url_is_valid("https://CALENDLY.com/x"));
        assert!(calendly_url_is_valid("https://calendly.com"));
        // wrong scheme
        assert!(!calendly_url_is_valid("http://calendly.com/x"));
        // not calendly
        assert!(!calendly_url_is_valid("https://evil.com/calendly.com"));
        assert!(!calendly_url_is_valid("https://notcalendly.com/x"));
        // userinfo / port rejected
        assert!(!calendly_url_is_valid("https://calendly.com@evil.com/x"));
        assert!(!calendly_url_is_valid("https://calendly.com:8080/x"));
    }

    #[test]
    fn wave2_components_round_trip() {
        for (json, name) in [
            (r#"{"kind":"component","component":"nav_menu"}"#, "nav_menu"),
            (r#"{"kind":"component","component":"carousel"}"#, "carousel"),
            (r#"{"kind":"component","component":"tabs"}"#, "tabs"),
        ] {
            let kind: WebNodeKind = serde_json::from_str(json).expect("deserialize");
            let WebNodeKind::Component { spec } = &kind else {
                panic!("component node");
            };
            assert_eq!(spec.component_name(), name);
            let value = serde_json::to_value(&kind).expect("serialize");
            assert_eq!(value["component"], name);
            let back: WebNodeKind = serde_json::from_value(value).expect("deserialize");
            assert_eq!(back, kind);
        }
    }

    #[test]
    fn carousel_and_tabs_defaults_fill_in() {
        let carousel: WebNodeKind =
            serde_json::from_str(r#"{"kind":"component","component":"carousel"}"#).expect("de");
        let WebNodeKind::Component {
            spec:
                ComponentSpec::Carousel {
                    show_arrows,
                    autoplay_s,
                },
        } = carousel
        else {
            panic!("carousel");
        };
        assert!(show_arrows);
        assert_eq!(autoplay_s, None);

        let tabs: WebNodeKind =
            serde_json::from_str(r#"{"kind":"component","component":"tabs"}"#).expect("de");
        let WebNodeKind::Component {
            spec: ComponentSpec::Tabs { default_tab },
        } = tabs
        else {
            panic!("tabs");
        };
        assert_eq!(default_tab, 0);
    }

    #[test]
    fn text_variant_render_tags() {
        assert_eq!(TextVariant::Display.render_tag(), "h1");
        assert_eq!(TextVariant::H3.render_tag(), "h3");
        assert_eq!(TextVariant::Overline.render_tag(), "p");
    }

    #[test]
    fn container_and_section_background_props_round_trip_with_legacy_defaults() {
        let legacy: WebNodeKind =
            serde_json::from_str(r#"{"kind":"container"}"#).expect("legacy container");
        assert_eq!(
            legacy,
            WebNodeKind::Container {
                href: None,
                new_tab: false,
                background: None,
            }
        );

        let kind = WebNodeKind::Section {
            tag: SectionTag::Section,
            anchor_id: Some("hero".to_owned()),
            background: Some(WebBackgroundImage {
                asset_id: AssetId::from("hero_photo"),
                fit: WebBackgroundFit::Contain,
                position: WebBackgroundPosition::Top,
                scrim: Some(WebBackgroundScrim {
                    color: WebScrimColor::Primary,
                    opacity: 65,
                }),
            }),
        };
        let value = serde_json::to_value(&kind).expect("serialize");
        assert_eq!(value["background"]["asset_id"], "hero_photo");
        assert_eq!(value["background"]["fit"], "contain");
        assert_eq!(value["background"]["scrim"]["opacity"], 65);
        assert_eq!(
            serde_json::from_value::<WebNodeKind>(value).expect("deserialize"),
            kind
        );
    }

    #[test]
    fn reachable_ids_walks_preorder() {
        let mut doc = WebDoc::new("doc_1", "Test", None);
        let page = &mut doc.pages[0];
        let sec = WebNode::branch(
            NodeId::from("sec_hero"),
            WebNodeKind::Section {
                tag: SectionTag::Section,
                anchor_id: None,
                background: None,
            },
            "",
        );
        let text = WebNode {
            id: NodeId::from("txt_1"),
            kind: WebNodeKind::Text {
                variant: TextVariant::Body,
                content: "hi".to_owned().into(),
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        page.nodes.get_mut(&NodeId::from("root")).unwrap().children =
            vec![NodeId::from("sec_hero")];
        let mut sec = sec;
        sec.children = vec![NodeId::from("txt_1")];
        page.nodes.insert(NodeId::from("sec_hero"), sec);
        page.nodes.insert(NodeId::from("txt_1"), text);
        let ids: Vec<String> = page
            .reachable_ids()
            .iter()
            .map(|id| id.as_str().to_owned())
            .collect();
        assert_eq!(ids, vec!["root", "sec_hero", "txt_1"]);
        assert_eq!(
            page.parent_of(&NodeId::from("txt_1")).unwrap().as_str(),
            "sec_hero"
        );
    }
}
