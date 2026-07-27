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
    },
    Container,
    Text {
        #[serde(default)]
        variant: TextVariant,
        /// Sanitized restricted inline markup (see `inline`): only
        /// `strong em u s a br span[class]` survive ingestion.
        content: String,
    },
    Button {
        label: String,
        href: String,
        #[serde(default)]
        variant: ButtonVariant,
        #[serde(default)]
        new_tab: bool,
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
        /// Rendered inside a sandboxed iframe in both modes.
        html: String,
    },
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SectionTag {
    #[default]
    Section,
    Header,
    Footer,
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

impl WebNodeKind {
    pub fn kind_name(&self) -> &'static str {
        match self {
            WebNodeKind::Section { .. } => "section",
            WebNodeKind::Container => "container",
            WebNodeKind::Text { .. } => "text",
            WebNodeKind::Button { .. } => "button",
            WebNodeKind::Image { .. } => "image",
            WebNodeKind::Icon { .. } => "icon",
            WebNodeKind::Embed { .. } => "embed",
        }
    }

    /// Only Section and Container may hold children.
    pub fn is_branch(&self) -> bool {
        matches!(self, WebNodeKind::Section { .. } | WebNodeKind::Container)
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
    pub fn new(id: impl Into<String>, title: impl Into<String>, brand_kit: Option<BrandKitRef>) -> Self {
        let root_id = NodeId::from("root");
        let root = WebNode::branch(root_id.clone(), WebNodeKind::Container, "");
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
    fn text_variant_render_tags() {
        assert_eq!(TextVariant::Display.render_tag(), "h1");
        assert_eq!(TextVariant::H3.render_tag(), "h3");
        assert_eq!(TextVariant::Overline.render_tag(), "p");
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
