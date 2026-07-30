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

pub const WEB_SCHEMA_VERSION: u32 = 1;

/// Maximum tree depth (root exclusive) accepted by validation and ingestion.
pub const MAX_TREE_DEPTH: usize = 12;

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
        /// Sanitized restricted inline markup (see `inline`): only
        /// `strong em u s a br span[class]` survive ingestion.
        content: String,
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
            WebNodeKind::Image { .. } => "image",
            WebNodeKind::Icon { .. } => "icon",
            WebNodeKind::Embed { .. } => "embed",
        }
    }

    /// Section, Container, and Component may hold children (a Component's
    /// children are ordinary nodes; its behavior is the platform runtime's).
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
                content: "Hello".to_owned(),
            },
            classes: "text-dark".to_owned(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let value = serde_json::to_value(&node).expect("serialize");
        assert_eq!(value["kind"], "text");
        assert_eq!(value["variant"], "h2");
        assert_eq!(value["content"], "Hello");
        assert_eq!(value["classes"], "text-dark");
        let back: WebNode = serde_json::from_value(value).expect("deserialize");
        assert_eq!(back, node);
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
                content: "hi".to_owned(),
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
