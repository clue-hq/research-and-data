//! Canonical, editor-library-independent rich-text document.
//!
//! Lexical is an interaction implementation detail in the website editor. The
//! persisted document uses this small semantic model so API validation,
//! personalization, rendering, history, and delivery do not depend on
//! Lexical's private JSON format.

use crate::derive::personalization_key_is_valid;
use crate::inline::sanitize_inline;
use crate::util::{
    escape_attr, escape_stray_lt, escape_text, href_is_allowed, normalize_entities,
    self_close_voids,
};
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use serde::{Deserialize, Deserializer, Serialize};
use std::fmt;

pub const RICH_TEXT_SCHEMA_VERSION: u32 = 1;
const MAX_BLOCKS: usize = 128;
const MAX_INLINES: usize = 4_096;
const MAX_TEXT_CHARS: usize = 100_000;
const MAX_LIST_DEPTH: usize = 6;

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct RichTextDocument {
    pub schema_version: u32,
    pub blocks: Vec<RichTextBlock>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum RichTextDocumentInput {
    LegacyInlineHtml(String),
    Structured(RichTextDocumentRepr),
}

#[derive(Deserialize)]
struct RichTextDocumentRepr {
    schema_version: u32,
    blocks: Vec<RichTextBlock>,
}

impl<'de> Deserialize<'de> for RichTextDocument {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        match RichTextDocumentInput::deserialize(deserializer)? {
            RichTextDocumentInput::LegacyInlineHtml(html) => Ok(Self::from_inline_html(&html)),
            RichTextDocumentInput::Structured(value) => Ok(Self {
                schema_version: value.schema_version,
                blocks: value.blocks,
            }),
        }
    }
}

impl Default for RichTextDocument {
    fn default() -> Self {
        Self::empty()
    }
}

impl From<String> for RichTextDocument {
    fn from(value: String) -> Self {
        Self::from_inline_html(&value)
    }
}

impl From<&str> for RichTextDocument {
    fn from(value: &str) -> Self {
        Self::from_inline_html(value)
    }
}

impl fmt::Display for RichTextDocument {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.to_inline_html())
    }
}

impl PartialEq<str> for RichTextDocument {
    fn eq(&self, other: &str) -> bool {
        self.to_inline_html() == other
    }
}

impl PartialEq<&str> for RichTextDocument {
    fn eq(&self, other: &&str) -> bool {
        self.to_inline_html() == *other
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RichTextBlock {
    Paragraph {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alignment: Option<RichTextAlignment>,
        #[serde(default)]
        children: Vec<RichTextInline>,
    },
    List {
        #[serde(default)]
        list_type: RichTextListType,
        #[serde(default)]
        items: Vec<RichTextListItem>,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RichTextListItem {
    #[serde(default)]
    pub children: Vec<RichTextInline>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub nested: Vec<RichTextBlock>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RichTextAlignment {
    #[default]
    Start,
    Center,
    End,
    Justify,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RichTextListType {
    #[default]
    Unordered,
    Ordered,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RichTextInline {
    Text {
        text: String,
        #[serde(default, skip_serializing_if = "RichTextMarks::is_empty")]
        marks: RichTextMarks,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        classes: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        link: Option<RichTextLink>,
    },
    Variable {
        key: String,
        #[serde(default)]
        fallback: String,
        #[serde(default, skip_serializing_if = "RichTextMarks::is_empty")]
        marks: RichTextMarks,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        classes: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        link: Option<RichTextLink>,
    },
    LineBreak {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        link: Option<RichTextLink>,
    },
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct RichTextMarks {
    #[serde(default, skip_serializing_if = "is_false")]
    pub bold: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub italic: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub underline: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub strikethrough: bool,
}

impl RichTextMarks {
    pub fn is_empty(&self) -> bool {
        !self.bold && !self.italic && !self.underline && !self.strikethrough
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RichTextLink {
    pub href: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub new_tab: bool,
}

#[derive(Clone, Debug, Default)]
struct InlineContext {
    marks: RichTextMarks,
    classes: Vec<String>,
    link: Option<RichTextLink>,
    variable: Option<String>,
}

#[derive(Clone, Debug)]
enum ParsedHtmlNode {
    Text(String),
    Element(ParsedHtmlElement),
}

#[derive(Clone, Debug)]
struct ParsedHtmlElement {
    tag: String,
    attrs: Vec<(String, String)>,
    children: Vec<ParsedHtmlNode>,
}

impl RichTextDocument {
    pub fn empty() -> Self {
        Self {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children: Vec::new(),
            }],
        }
    }

    pub fn from_plain_text(text: impl Into<String>) -> Self {
        let text = text.into();
        let children = if text.is_empty() {
            Vec::new()
        } else {
            vec![RichTextInline::Text {
                text,
                marks: RichTextMarks::default(),
                classes: None,
                link: None,
            }]
        };
        Self {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children,
            }],
        }
    }

    /// Import the previous restricted-inline-HTML representation. Sanitization
    /// happens before parsing, making this an explicit compatibility/import
    /// boundary rather than a second storage format.
    pub fn from_inline_html(input: &str) -> Self {
        let canonical = sanitize_inline(input).html;
        if canonical.is_empty() {
            return Self::empty();
        }

        let wrapped = format!("<lumen-rich>{canonical}</lumen-rich>");
        let mut reader = Reader::from_str(&wrapped);
        reader.config_mut().trim_text(false);
        let mut contexts = vec![InlineContext::default()];
        let mut children = Vec::new();

        loop {
            match reader.read_event() {
                Ok(Event::Start(start)) => {
                    let name = String::from_utf8_lossy(start.name().as_ref()).to_lowercase();
                    if name != "lumen-rich" {
                        let next = context_for_start(
                            contexts.last().cloned().unwrap_or_default(),
                            &name,
                            &start,
                        );
                        contexts.push(next);
                    }
                }
                Ok(Event::Empty(start)) => {
                    let name = String::from_utf8_lossy(start.name().as_ref()).to_lowercase();
                    if name == "br" {
                        children.push(RichTextInline::LineBreak {
                            link: contexts.last().and_then(|value| value.link.clone()),
                        });
                    }
                }
                Ok(Event::End(end)) => {
                    let name = String::from_utf8_lossy(end.name().as_ref()).to_lowercase();
                    if name != "lumen-rich" && contexts.len() > 1 {
                        contexts.pop();
                    }
                }
                Ok(Event::Text(text)) => {
                    let value = text
                        .unescape()
                        .map(|value| value.into_owned())
                        .unwrap_or_else(|_| String::from_utf8_lossy(text.as_ref()).into_owned());
                    if !value.is_empty() {
                        push_text(
                            &mut children,
                            &value,
                            contexts.last().cloned().unwrap_or_default(),
                        );
                    }
                }
                Ok(Event::CData(data)) => {
                    let value = String::from_utf8_lossy(data.as_ref());
                    if !value.is_empty() {
                        push_text(
                            &mut children,
                            &value,
                            contexts.last().cloned().unwrap_or_default(),
                        );
                    }
                }
                Ok(Event::Eof) => break,
                Ok(_) => {}
                Err(_) => return Self::from_plain_text(input),
            }
        }

        Self {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children,
            }],
        }
    }

    /// Import semantic rich HTML (`p`, `ol`, `ul`, `li` plus the restricted
    /// inline vocabulary) into the canonical document. Unsupported elements are
    /// unwrapped, executable/style subtrees are dropped, attributes are
    /// allowlisted, and list nesting is bounded before persistence.
    pub fn from_html(input: &str) -> Self {
        let Some(nodes) = parse_html_fragment(input) else {
            return Self::from_inline_html(input);
        };
        if !contains_structural_html(&nodes) {
            return Self::from_inline_html(input);
        }
        let blocks = parsed_nodes_to_blocks(&nodes);
        Self {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: if blocks.is_empty() {
                Self::empty().blocks
            } else {
                blocks
            },
        }
    }

    /// Delivery/editor render projection. The model, not Lexical, owns this
    /// HTML so both render targets remain byte-for-byte semantic peers.
    pub fn to_inline_html(&self) -> String {
        let mut out = String::new();
        for (index, block) in self.blocks.iter().enumerate() {
            if index > 0 {
                out.push_str("<br />");
            }
            render_block(block, &mut out);
        }
        out
    }

    /// Semantic block projection for Body/Small text nodes. The containing web
    /// node owns styling and identity; this projection owns only meaningful
    /// paragraph/list structure and never emits editor-library attributes.
    pub fn to_semantic_html(&self) -> String {
        let mut out = String::new();
        for block in &self.blocks {
            render_semantic_block(block, &mut out);
        }
        out
    }

    pub fn is_single_paragraph(&self) -> bool {
        matches!(self.blocks.as_slice(), [RichTextBlock::Paragraph { .. }])
    }

    pub fn plain_text(&self) -> String {
        let mut out = String::new();
        for (block_index, block) in self.blocks.iter().enumerate() {
            if block_index > 0 {
                out.push('\n');
            }
            append_block_plain_text(block, &mut out);
        }
        out
    }

    pub fn contains_link(&self) -> bool {
        self.visit_inlines().any(|inline| match inline {
            RichTextInline::Text { link, .. }
            | RichTextInline::Variable { link, .. }
            | RichTextInline::LineBreak { link } => link.is_some(),
        })
    }

    pub fn contains_variable(&self) -> bool {
        self.visit_inlines()
            .any(|inline| matches!(inline, RichTextInline::Variable { .. }))
    }

    pub(crate) fn for_each_variable_mut(&mut self, mut visit: impl FnMut(&str, &mut String)) {
        for block in &mut self.blocks {
            visit_block_variables_mut(block, &mut visit);
        }
    }

    /// Convenience for call sites that previously inspected the canonical
    /// inline-HTML string. New semantic checks should prefer `contains_link`
    /// and `contains_variable`.
    pub fn contains(&self, needle: &str) -> bool {
        self.to_inline_html().contains(needle)
    }

    pub fn validate(&self) -> Vec<String> {
        let mut issues = Vec::new();
        if self.schema_version != RICH_TEXT_SCHEMA_VERSION {
            issues.push(format!(
                "unsupported rich-text schema version {}",
                self.schema_version
            ));
        }
        if self.blocks.is_empty() {
            issues.push("rich-text document must contain at least one block".to_owned());
        }
        if self.blocks.len() > MAX_BLOCKS {
            issues.push(format!("rich-text document exceeds {MAX_BLOCKS} blocks"));
        }

        let mut block_count = 0usize;
        let mut inline_count = 0usize;
        let mut char_count = 0usize;
        for block in &self.blocks {
            validate_block(
                block,
                0,
                &mut block_count,
                &mut inline_count,
                &mut char_count,
                &mut issues,
            );
        }
        if block_count > MAX_BLOCKS {
            issues.push(format!("rich-text document exceeds {MAX_BLOCKS} blocks"));
        }
        if inline_count > MAX_INLINES {
            issues.push(format!(
                "rich-text document exceeds {MAX_INLINES} inline nodes"
            ));
        }
        if char_count > MAX_TEXT_CHARS {
            issues.push(format!(
                "rich-text document exceeds {MAX_TEXT_CHARS} characters"
            ));
        }
        issues
    }

    fn visit_inlines(&self) -> impl Iterator<Item = &RichTextInline> {
        self.blocks.iter().flat_map(block_inlines)
    }
}

fn parse_html_fragment(input: &str) -> Option<Vec<ParsedHtmlNode>> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Some(Vec::new());
    }
    let normalized = self_close_voids(&escape_stray_lt(&normalize_entities(trimmed)));
    let wrapped = format!("<lumen-rich>{normalized}</lumen-rich>");
    let mut reader = Reader::from_str(&wrapped);
    reader.config_mut().trim_text(false);
    let mut stack: Vec<ParsedHtmlElement> = Vec::new();
    let mut root: Option<ParsedHtmlElement> = None;

    loop {
        match reader.read_event() {
            Ok(Event::Start(start)) => {
                stack.push(ParsedHtmlElement {
                    tag: String::from_utf8_lossy(start.name().as_ref()).to_ascii_lowercase(),
                    attrs: parsed_attrs(&start),
                    children: Vec::new(),
                });
            }
            Ok(Event::Empty(start)) => {
                let element = ParsedHtmlElement {
                    tag: String::from_utf8_lossy(start.name().as_ref()).to_ascii_lowercase(),
                    attrs: parsed_attrs(&start),
                    children: Vec::new(),
                };
                stack
                    .last_mut()
                    .map(|parent| parent.children.push(ParsedHtmlNode::Element(element)))?;
            }
            Ok(Event::End(end)) => {
                let tag = String::from_utf8_lossy(end.name().as_ref()).to_ascii_lowercase();
                let element = stack.pop()?;
                if element.tag != tag {
                    return None;
                }
                if let Some(parent) = stack.last_mut() {
                    parent.children.push(ParsedHtmlNode::Element(element));
                } else {
                    root = Some(element);
                }
            }
            Ok(Event::Text(text)) => {
                let value = text
                    .unescape()
                    .map(|value| value.into_owned())
                    .unwrap_or_else(|_| String::from_utf8_lossy(text.as_ref()).into_owned());
                stack
                    .last_mut()
                    .map(|parent| parent.children.push(ParsedHtmlNode::Text(value)))?;
            }
            Ok(Event::CData(data)) => {
                stack.last_mut().map(|parent| {
                    parent.children.push(ParsedHtmlNode::Text(
                        String::from_utf8_lossy(data.as_ref()).into_owned(),
                    ))
                })?;
            }
            Ok(Event::Eof) => break,
            Ok(_) => {}
            Err(_) => return None,
        }
    }
    let root = root?;
    (root.tag == "lumen-rich").then_some(root.children)
}

fn parsed_attrs(start: &BytesStart<'_>) -> Vec<(String, String)> {
    start
        .attributes()
        .with_checks(false)
        .flatten()
        .map(|attr| {
            let name = String::from_utf8_lossy(attr.key.as_ref()).to_ascii_lowercase();
            let value = attr
                .unescape_value()
                .map(|value| value.into_owned())
                .unwrap_or_else(|_| String::from_utf8_lossy(&attr.value).into_owned());
            (name, value)
        })
        .collect()
}

fn contains_structural_html(nodes: &[ParsedHtmlNode]) -> bool {
    nodes.iter().any(|node| match node {
        ParsedHtmlNode::Text(_) => false,
        ParsedHtmlNode::Element(element) => {
            matches!(
                element.tag.as_str(),
                "p" | "div" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "ul" | "ol" | "li"
            ) || contains_structural_html(&element.children)
        }
    })
}

fn parsed_nodes_to_blocks(nodes: &[ParsedHtmlNode]) -> Vec<RichTextBlock> {
    let mut blocks = Vec::new();
    let mut pending_inline = Vec::new();
    for node in nodes {
        match node {
            ParsedHtmlNode::Element(element) if matches!(element.tag.as_str(), "ul" | "ol") => {
                flush_inline_block(&mut pending_inline, &mut blocks);
                blocks.push(parsed_list(element, 1));
            }
            ParsedHtmlNode::Element(element)
                if matches!(
                    element.tag.as_str(),
                    "p" | "div" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6"
                ) =>
            {
                flush_inline_block(&mut pending_inline, &mut blocks);
                let mut children = Vec::new();
                collect_parsed_inlines(&element.children, InlineContext::default(), &mut children);
                blocks.push(RichTextBlock::Paragraph {
                    alignment: None,
                    children,
                });
            }
            ParsedHtmlNode::Element(element)
                if matches!(element.tag.as_str(), "script" | "style") => {}
            _ => pending_inline.push(node.clone()),
        }
    }
    flush_inline_block(&mut pending_inline, &mut blocks);
    blocks
}

fn flush_inline_block(pending: &mut Vec<ParsedHtmlNode>, blocks: &mut Vec<RichTextBlock>) {
    if pending.is_empty()
        || pending
            .iter()
            .all(|node| matches!(node, ParsedHtmlNode::Text(value) if value.trim().is_empty()))
    {
        pending.clear();
        return;
    }
    let mut children = Vec::new();
    collect_parsed_inlines(pending, InlineContext::default(), &mut children);
    blocks.push(RichTextBlock::Paragraph {
        alignment: None,
        children,
    });
    pending.clear();
}

fn parsed_list(element: &ParsedHtmlElement, depth: usize) -> RichTextBlock {
    let list_type = if element.tag == "ol" {
        RichTextListType::Ordered
    } else {
        RichTextListType::Unordered
    };
    let mut items = Vec::new();
    for child in &element.children {
        let ParsedHtmlNode::Element(item) = child else {
            continue;
        };
        if item.tag != "li" {
            continue;
        }
        let mut children = Vec::new();
        let mut nested = Vec::new();
        for item_child in &item.children {
            match item_child {
                ParsedHtmlNode::Element(nested_list)
                    if matches!(nested_list.tag.as_str(), "ul" | "ol") =>
                {
                    if depth < MAX_LIST_DEPTH {
                        nested.push(parsed_list(nested_list, depth + 1));
                    } else {
                        flatten_parsed_list(nested_list, &mut children);
                    }
                }
                ParsedHtmlNode::Element(block) if matches!(block.tag.as_str(), "p" | "div") => {
                    if !children.is_empty() {
                        children.push(RichTextInline::LineBreak { link: None });
                    }
                    collect_parsed_inlines(
                        &block.children,
                        InlineContext::default(),
                        &mut children,
                    );
                }
                other => collect_parsed_inlines(
                    std::slice::from_ref(other),
                    InlineContext::default(),
                    &mut children,
                ),
            }
        }
        items.push(RichTextListItem { children, nested });
    }
    RichTextBlock::List { list_type, items }
}

fn flatten_parsed_list(element: &ParsedHtmlElement, out: &mut Vec<RichTextInline>) {
    for child in &element.children {
        let ParsedHtmlNode::Element(item) = child else {
            continue;
        };
        if item.tag != "li" {
            continue;
        }
        if !out.is_empty() {
            out.push(RichTextInline::LineBreak { link: None });
        }
        for item_child in &item.children {
            match item_child {
                ParsedHtmlNode::Element(nested) if matches!(nested.tag.as_str(), "ul" | "ol") => {
                    flatten_parsed_list(nested, out);
                }
                other => collect_parsed_inlines(
                    std::slice::from_ref(other),
                    InlineContext::default(),
                    out,
                ),
            }
        }
    }
}

fn collect_parsed_inlines(
    nodes: &[ParsedHtmlNode],
    context: InlineContext,
    out: &mut Vec<RichTextInline>,
) {
    for node in nodes {
        match node {
            ParsedHtmlNode::Text(value) => {
                if !value.is_empty() {
                    push_text(out, value, context.clone());
                }
            }
            ParsedHtmlNode::Element(element) => {
                let tag = element.tag.as_str();
                if matches!(tag, "script" | "style" | "iframe" | "object" | "embed") {
                    continue;
                }
                if tag == "br" {
                    out.push(RichTextInline::LineBreak {
                        link: context.link.clone(),
                    });
                    continue;
                }
                let mut next = context.clone();
                match tag {
                    "strong" | "b" => next.marks.bold = true,
                    "em" | "i" => next.marks.italic = true,
                    "u" => next.marks.underline = true,
                    "s" | "strike" => next.marks.strikethrough = true,
                    "a" => {
                        if let Some(href) =
                            parsed_attr(element, "href").filter(|href| href_is_allowed(href))
                        {
                            next.link = Some(RichTextLink {
                                href: href.to_owned(),
                                new_tab: parsed_attr(element, "target") == Some("_blank"),
                            });
                        }
                    }
                    "span" => {
                        if let Some(classes) = parsed_attr(element, "class") {
                            next.classes.push(classes.to_owned());
                        }
                        if let Some(key) = parsed_attr(element, "data-var")
                            .filter(|key| personalization_key_is_valid(key))
                        {
                            next.variable = Some(key.to_owned());
                        }
                    }
                    _ => {}
                }
                collect_parsed_inlines(&element.children, next, out);
            }
        }
    }
}

fn parsed_attr<'a>(element: &'a ParsedHtmlElement, name: &str) -> Option<&'a str> {
    element
        .attrs
        .iter()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.as_str())
}

fn context_for_start(
    mut context: InlineContext,
    name: &str,
    start: &BytesStart<'_>,
) -> InlineContext {
    match name {
        "strong" => context.marks.bold = true,
        "em" => context.marks.italic = true,
        "u" => context.marks.underline = true,
        "s" => context.marks.strikethrough = true,
        "a" => {
            if let Some(href) = attr(start, "href") {
                context.link = Some(RichTextLink {
                    href,
                    new_tab: attr(start, "target").as_deref() == Some("_blank"),
                });
            }
        }
        "span" => {
            if let Some(classes) = attr(start, "class") {
                context.classes.push(classes);
            }
            if let Some(key) = attr(start, "data-var") {
                context.variable = Some(key);
            }
        }
        _ => {}
    }
    context
}

fn attr(start: &BytesStart<'_>, name: &str) -> Option<String> {
    start
        .attributes()
        .with_checks(false)
        .flatten()
        .find(|attr| attr.key.as_ref() == name.as_bytes())
        .map(|attr| {
            attr.unescape_value()
                .map(|value| value.into_owned())
                .unwrap_or_else(|_| String::from_utf8_lossy(&attr.value).into_owned())
        })
}

fn push_text(children: &mut Vec<RichTextInline>, text: &str, context: InlineContext) {
    let classes = normalized_classes(&context.classes);
    let next = if let Some(key) = context.variable {
        RichTextInline::Variable {
            key,
            fallback: text.to_owned(),
            marks: context.marks,
            classes,
            link: context.link,
        }
    } else {
        RichTextInline::Text {
            text: text.to_owned(),
            marks: context.marks,
            classes,
            link: context.link,
        }
    };

    if !merge_inline(children.last_mut(), &next) {
        children.push(next);
    }
}

fn merge_inline(existing: Option<&mut RichTextInline>, next: &RichTextInline) -> bool {
    match (existing, next) {
        (
            Some(RichTextInline::Text {
                text,
                marks,
                classes,
                link,
            }),
            RichTextInline::Text {
                text: next_text,
                marks: next_marks,
                classes: next_classes,
                link: next_link,
            },
        ) if marks == next_marks && classes == next_classes && link == next_link => {
            text.push_str(next_text);
            true
        }
        (
            Some(RichTextInline::Variable {
                key,
                fallback,
                marks,
                classes,
                link,
            }),
            RichTextInline::Variable {
                key: next_key,
                fallback: next_fallback,
                marks: next_marks,
                classes: next_classes,
                link: next_link,
            },
        ) if key == next_key
            && marks == next_marks
            && classes == next_classes
            && link == next_link =>
        {
            fallback.push_str(next_fallback);
            true
        }
        _ => false,
    }
}

fn normalized_classes(values: &[String]) -> Option<String> {
    let joined = values
        .iter()
        .flat_map(|value| value.split_ascii_whitespace())
        .collect::<Vec<_>>()
        .join(" ");
    (!joined.is_empty()).then_some(joined)
}

fn render_block(block: &RichTextBlock, out: &mut String) {
    match block {
        RichTextBlock::Paragraph { children, .. } => render_inlines(children, out),
        RichTextBlock::List { list_type, items } => {
            let tag = match list_type {
                RichTextListType::Unordered => "ul",
                RichTextListType::Ordered => "ol",
            };
            out.push('<');
            out.push_str(tag);
            out.push('>');
            for item in items {
                out.push_str("<li>");
                render_inlines(&item.children, out);
                for nested in &item.nested {
                    render_block(nested, out);
                }
                out.push_str("</li>");
            }
            out.push_str("</");
            out.push_str(tag);
            out.push('>');
        }
    }
}

fn render_semantic_block(block: &RichTextBlock, out: &mut String) {
    match block {
        RichTextBlock::Paragraph { children, .. } => {
            out.push_str("<p>");
            render_inlines(children, out);
            out.push_str("</p>");
        }
        RichTextBlock::List { list_type, items } => {
            let tag = match list_type {
                RichTextListType::Unordered => "ul",
                RichTextListType::Ordered => "ol",
            };
            out.push('<');
            out.push_str(tag);
            out.push('>');
            for item in items {
                out.push_str("<li>");
                render_inlines(&item.children, out);
                for nested in &item.nested {
                    render_semantic_block(nested, out);
                }
                out.push_str("</li>");
            }
            out.push_str("</");
            out.push_str(tag);
            out.push('>');
        }
    }
}

fn render_inlines(inlines: &[RichTextInline], out: &mut String) {
    for inline in inlines {
        match inline {
            RichTextInline::LineBreak { .. } => out.push_str("<br />"),
            RichTextInline::Text {
                text,
                marks,
                classes,
                link,
            } => render_leaf(text, None, *marks, classes.as_deref(), link.as_ref(), out),
            RichTextInline::Variable {
                key,
                fallback,
                marks,
                classes,
                link,
            } => render_leaf(
                fallback,
                Some(key),
                *marks,
                classes.as_deref(),
                link.as_ref(),
                out,
            ),
        }
    }
}

fn render_leaf(
    text: &str,
    variable: Option<&str>,
    marks: RichTextMarks,
    classes: Option<&str>,
    link: Option<&RichTextLink>,
    out: &mut String,
) {
    if let Some(link) = link {
        out.push_str("<a href=\"");
        out.push_str(&escape_attr(&link.href));
        out.push('"');
        if link.new_tab {
            out.push_str(" target=\"_blank\" rel=\"noopener noreferrer\"");
        }
        out.push('>');
    }
    if variable.is_some() || classes.is_some() {
        out.push_str("<span");
        if let Some(key) = variable {
            out.push_str(" data-var=\"");
            out.push_str(&escape_attr(key));
            out.push('"');
        }
        if let Some(classes) = classes {
            out.push_str(" class=\"");
            out.push_str(&escape_attr(classes));
            out.push('"');
        }
        out.push('>');
    }
    if marks.bold {
        out.push_str("<strong>");
    }
    if marks.italic {
        out.push_str("<em>");
    }
    if marks.underline {
        out.push_str("<u>");
    }
    if marks.strikethrough {
        out.push_str("<s>");
    }
    out.push_str(&escape_text(text));
    if marks.strikethrough {
        out.push_str("</s>");
    }
    if marks.underline {
        out.push_str("</u>");
    }
    if marks.italic {
        out.push_str("</em>");
    }
    if marks.bold {
        out.push_str("</strong>");
    }
    if variable.is_some() || classes.is_some() {
        out.push_str("</span>");
    }
    if link.is_some() {
        out.push_str("</a>");
    }
}

fn append_block_plain_text(block: &RichTextBlock, out: &mut String) {
    match block {
        RichTextBlock::Paragraph { children, .. } => append_inline_plain_text(children, out),
        RichTextBlock::List { items, .. } => {
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push('\n');
                }
                append_inline_plain_text(&item.children, out);
                for nested in &item.nested {
                    out.push('\n');
                    append_block_plain_text(nested, out);
                }
            }
        }
    }
}

fn append_inline_plain_text(inlines: &[RichTextInline], out: &mut String) {
    for inline in inlines {
        match inline {
            RichTextInline::Text { text, .. } => out.push_str(text),
            RichTextInline::Variable { fallback, .. } => out.push_str(fallback),
            RichTextInline::LineBreak { .. } => out.push('\n'),
        }
    }
}

fn block_inlines(block: &RichTextBlock) -> Box<dyn Iterator<Item = &RichTextInline> + '_> {
    match block {
        RichTextBlock::Paragraph { children, .. } => Box::new(children.iter()),
        RichTextBlock::List { items, .. } => Box::new(items.iter().flat_map(|item| {
            item.children
                .iter()
                .chain(item.nested.iter().flat_map(|nested| block_inlines(nested)))
        })),
    }
}

fn visit_block_variables_mut(block: &mut RichTextBlock, visit: &mut impl FnMut(&str, &mut String)) {
    match block {
        RichTextBlock::Paragraph { children, .. } => {
            visit_inline_variables_mut(children, visit);
        }
        RichTextBlock::List { items, .. } => {
            for item in items {
                visit_inline_variables_mut(&mut item.children, visit);
                for nested in &mut item.nested {
                    visit_block_variables_mut(nested, visit);
                }
            }
        }
    }
}

fn visit_inline_variables_mut(
    inlines: &mut [RichTextInline],
    visit: &mut impl FnMut(&str, &mut String),
) {
    for inline in inlines {
        if let RichTextInline::Variable { key, fallback, .. } = inline {
            visit(key, fallback);
        }
    }
}

fn validate_block(
    block: &RichTextBlock,
    list_depth: usize,
    block_count: &mut usize,
    inline_count: &mut usize,
    char_count: &mut usize,
    issues: &mut Vec<String>,
) {
    *block_count += 1;
    match block {
        RichTextBlock::Paragraph { children, .. } => {
            validate_inlines(children, inline_count, char_count, issues);
        }
        RichTextBlock::List { items, .. } => {
            if items.is_empty() {
                issues.push("rich-text list must contain at least one item".to_owned());
            }
            if list_depth >= MAX_LIST_DEPTH {
                issues.push(format!(
                    "rich-text list nesting exceeds {MAX_LIST_DEPTH} levels"
                ));
            }
            for item in items {
                if item.children.is_empty() && item.nested.is_empty() {
                    issues.push("rich-text list item must contain content".to_owned());
                }
                validate_inlines(&item.children, inline_count, char_count, issues);
                for nested in &item.nested {
                    validate_block(
                        nested,
                        list_depth + 1,
                        block_count,
                        inline_count,
                        char_count,
                        issues,
                    );
                }
            }
        }
    }
}

fn validate_inlines(
    inlines: &[RichTextInline],
    inline_count: &mut usize,
    char_count: &mut usize,
    issues: &mut Vec<String>,
) {
    *inline_count += inlines.len();
    for inline in inlines {
        match inline {
            RichTextInline::Text {
                text,
                classes,
                link,
                ..
            } => {
                *char_count += text.chars().count();
                validate_leaf(classes, link, issues);
            }
            RichTextInline::Variable {
                key,
                fallback,
                classes,
                link,
                ..
            } => {
                *char_count += fallback.chars().count();
                if !personalization_key_is_valid(key) {
                    issues.push(format!("invalid personalization variable key `{key}`"));
                }
                if fallback.trim().is_empty() {
                    issues.push(format!(
                        "personalization variable `{key}` requires visible fallback text"
                    ));
                }
                validate_leaf(classes, link, issues);
            }
            RichTextInline::LineBreak { link } => validate_link(link, issues),
        }
    }
}

fn validate_leaf(classes: &Option<String>, link: &Option<RichTextLink>, issues: &mut Vec<String>) {
    if classes.as_ref().is_some_and(|value| {
        value.is_empty()
            || value
                .chars()
                .any(|ch| ch.is_control() || matches!(ch, '<' | '>'))
    }) {
        issues.push("rich-text inline classes are not canonical".to_owned());
    }
    validate_link(link, issues);
}

fn validate_link(link: &Option<RichTextLink>, issues: &mut Vec<String>) {
    if let Some(link) = link {
        if !href_is_allowed(&link.href) {
            issues.push(format!("rich-text link href is not allowed: {}", link.href));
        }
    }
}

fn is_false(value: &bool) -> bool {
    !*value
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn imports_marks_links_classes_variables_and_breaks() {
        let doc = RichTextDocument::from_inline_html(
            "Hello <a href=\"/x\" target=\"_blank\"><strong>bold</strong></a> <span data-var=\"account.name\" class=\"text-primary\">Acme</span><br>now",
        );

        assert_eq!(doc.plain_text(), "Hello bold Acme\nnow");
        assert!(doc.contains_link());
        assert!(doc.contains_variable());
        assert_eq!(
            doc.to_inline_html(),
            "Hello <a href=\"/x\" target=\"_blank\" rel=\"noopener noreferrer\"><strong>bold</strong></a> <span data-var=\"account.name\" class=\"text-primary\">Acme</span><br />now"
        );
        assert!(doc.validate().is_empty());
    }

    #[test]
    fn structured_json_round_trips_without_lexical_state() {
        let doc = RichTextDocument::from_inline_html("one <strong>two</strong>");
        let encoded = serde_json::to_string(&doc).unwrap();
        assert!(encoded.contains("\"schema_version\":1"));
        assert!(!encoded.contains("lexical"));
        assert_eq!(
            serde_json::from_str::<RichTextDocument>(&encoded).unwrap(),
            doc
        );
    }

    #[test]
    fn legacy_string_json_is_an_import_adapter() {
        let doc: RichTextDocument = serde_json::from_str("\"safe <strong>text</strong>\"").unwrap();
        assert_eq!(doc.to_inline_html(), "safe <strong>text</strong>");
    }

    #[test]
    fn rejects_untrusted_structured_links_and_variables() {
        let mut doc = RichTextDocument::from_plain_text("unsafe");
        let RichTextBlock::Paragraph { children, .. } = &mut doc.blocks[0] else {
            unreachable!()
        };
        children.push(RichTextInline::Variable {
            key: "Account.Name".to_owned(),
            fallback: "x".to_owned(),
            marks: RichTextMarks::default(),
            classes: None,
            link: Some(RichTextLink {
                href: "javascript:alert(1)".to_owned(),
                new_tab: false,
            }),
        });
        let issues = doc.validate();
        assert!(issues.iter().any(|issue| issue.contains("variable key")));
        assert!(issues.iter().any(|issue| issue.contains("href")));
    }

    #[test]
    fn rejects_variables_without_visible_fallback_text() {
        let doc = RichTextDocument {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children: vec![RichTextInline::Variable {
                    key: "account.name".to_owned(),
                    fallback: "   ".to_owned(),
                    marks: RichTextMarks::default(),
                    classes: None,
                    link: None,
                }],
            }],
        };
        assert!(doc
            .validate()
            .iter()
            .any(|issue| issue.contains("visible fallback text")));
    }

    #[test]
    fn imports_and_renders_safe_semantic_paragraphs_and_nested_lists() {
        let doc = RichTextDocument::from_html(
            r#"<p style="color:red" onclick="bad()">Intro <strong>copy</strong><script>bad()</script></p>
               <ul><li>First<ul><li><em>Nested</em></li></ul></li>
               <li><a href="javascript:alert(1)">safe text</a></li></ul>
               <p>Outro<br>line</p>"#,
        );

        assert_eq!(
            doc.to_semantic_html(),
            "<p>Intro <strong>copy</strong></p>\
             <ul><li>First<ul><li><em>Nested</em></li></ul></li>\
             <li>safe text</li></ul><p>Outro<br />line</p>"
        );
        assert_eq!(doc.blocks.len(), 3);
        assert!(doc.validate().is_empty());
        assert!(!doc.to_semantic_html().contains("style="));
        assert!(!doc.to_semantic_html().contains("onclick="));
        assert!(!doc.to_semantic_html().contains("javascript:"));
        assert!(!doc.to_semantic_html().contains("script"));
    }

    #[test]
    fn structural_import_bounds_excessive_list_nesting() {
        let mut html = String::new();
        for depth in 0..8 {
            html.push_str(if depth % 2 == 0 {
                "<ul><li>item"
            } else {
                "<ol><li>item"
            });
        }
        for depth in (0..8).rev() {
            html.push_str(if depth % 2 == 0 {
                "</li></ul>"
            } else {
                "</li></ol>"
            });
        }

        let doc = RichTextDocument::from_html(&html);
        assert!(doc.validate().is_empty(), "{:?}", doc.validate());
        assert_eq!(doc.to_semantic_html().matches("<ul>").count(), 3);
        assert_eq!(doc.to_semantic_html().matches("<ol>").count(), 3);
        assert!(doc.plain_text().contains("item"));
    }

    #[test]
    fn rejects_empty_typed_list_items() {
        let doc = RichTextDocument {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::List {
                list_type: RichTextListType::Unordered,
                items: vec![RichTextListItem {
                    children: Vec::new(),
                    nested: Vec::new(),
                }],
            }],
        };
        assert!(doc
            .validate()
            .iter()
            .any(|issue| issue.contains("list item must contain content")));
    }
}
