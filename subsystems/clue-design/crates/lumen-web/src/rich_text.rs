//! Canonical, editor-library-independent rich-text document.
//!
//! Lexical is an interaction implementation detail in the website editor. The
//! persisted document uses this small semantic model so API validation,
//! personalization, rendering, history, and delivery do not depend on
//! Lexical's private JSON format.

use crate::derive::personalization_key_is_valid;
use crate::inline::sanitize_inline;
use crate::util::{escape_attr, escape_text, href_is_allowed};
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

        let mut inline_count = 0usize;
        let mut char_count = 0usize;
        for block in &self.blocks {
            validate_block(block, 0, &mut inline_count, &mut char_count, &mut issues);
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
            out.push_str(" target=\"_blank\"");
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

fn validate_block(
    block: &RichTextBlock,
    list_depth: usize,
    inline_count: &mut usize,
    char_count: &mut usize,
    issues: &mut Vec<String>,
) {
    match block {
        RichTextBlock::Paragraph { children, .. } => {
            validate_inlines(children, inline_count, char_count, issues);
        }
        RichTextBlock::List { items, .. } => {
            if list_depth >= MAX_LIST_DEPTH {
                issues.push(format!(
                    "rich-text list nesting exceeds {MAX_LIST_DEPTH} levels"
                ));
            }
            for item in items {
                validate_inlines(&item.children, inline_count, char_count, issues);
                for nested in &item.nested {
                    validate_block(nested, list_depth + 1, inline_count, char_count, issues);
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
            "Hello <a href=\"/x\"><strong>bold</strong></a> <span data-var=\"account.name\" class=\"text-primary\">Acme</span><br>now",
        );

        assert_eq!(doc.plain_text(), "Hello bold Acme\nnow");
        assert!(doc.contains_link());
        assert!(doc.contains_variable());
        assert_eq!(
            doc.to_inline_html(),
            "Hello <a href=\"/x\"><strong>bold</strong></a> <span data-var=\"account.name\" class=\"text-primary\">Acme</span><br />now"
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
}
