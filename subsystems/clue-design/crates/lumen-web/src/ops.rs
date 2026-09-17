//! Web document operations — invertible, envelope-ready.
//!
//! Same contract as the scene ledger: every applied operation returns its
//! inverse computed against the exact pre-application state, so the API's
//! `edit_envelopes` flow gives undo/redo/checkpoints without new machinery.
//! Batches apply against a draft and commit atomically: a failing op leaves
//! the document untouched.

use crate::derive::web_slot_key_is_valid;
use crate::doc::{
    calendly_url_is_valid, custom_component_artifact_id_is_valid, custom_component_props_issue,
    custom_component_slug_is_valid, fragment_id_is_valid, fragment_override_path_is_valid,
    fragment_slots_issue, ButtonAction, EmbedProvider, FragmentTextOverride, TextVariant, WebDoc,
    WebNode, WebNodeKind, WebThemeRef,
};
use crate::inline::sanitize_inline;
use crate::rich_text::RichTextDocument;
use crate::util::href_is_allowed;
use crate::validate::{route_is_valid, validate_web_doc};
use lumen_core::{AssetId, AssetRecord, Diagnostic, DiagnosticSeverity, NodeId, PageId, SlotKey};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug)]
pub struct WebOpError {
    pub code: &'static str,
    pub message: String,
    /// Populated by the checked apply when validation rejects the batch.
    pub diagnostics: Vec<Diagnostic>,
}

impl WebOpError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            diagnostics: Vec::new(),
        }
    }
}

impl fmt::Display for WebOpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for WebOpError {}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum WebOperation {
    InsertNode {
        page_id: PageId,
        parent: NodeId,
        index: usize,
        /// The full subtree, children before parents or any order; `root`
        /// must be present in `nodes`.
        nodes: Vec<WebNode>,
        root: NodeId,
    },
    RemoveNode {
        page_id: PageId,
        id: NodeId,
    },
    MoveNode {
        page_id: PageId,
        id: NodeId,
        new_parent: NodeId,
        index: usize,
    },
    SetNodeClasses {
        page_id: PageId,
        id: NodeId,
        classes: String,
    },
    /// Whole-props replacement; the node kind may not change.
    SetNodeProps {
        page_id: PageId,
        id: NodeId,
        props: WebNodeKind,
    },
    /// Set (or clear) a node's personalization slot key. The first op writing
    /// a `WebNode` field outside `kind`/`classes`; canonicalization validates
    /// the key charset (the `when:` presence-gate prefix is tolerated).
    SetSlotKey {
        page_id: PageId,
        id: NodeId,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        slot_key: Option<SlotKey>,
    },
    /// Set (or clear, with a `None` override) the text a human substituted for
    /// one element inside a cloned section. Ruling R-A6: the ONE interior edit
    /// a clone allows. Clearing is `None`, which is also the inverse of a first
    /// write, so undo restores the artifact's own text by removing the entry
    /// rather than by writing the old string back.
    SetFragmentTextOverride {
        page_id: PageId,
        id: NodeId,
        path: String,
        #[serde(rename = "override", default, skip_serializing_if = "Option::is_none")]
        r#override: Option<FragmentTextOverride>,
    },
    SetText {
        page_id: PageId,
        id: NodeId,
        content: String,
    },
    /// Replace a text node's canonical semantic rich-text document. Human
    /// range edits use this operation; `SetText` remains an HTML-import
    /// adapter for existing agent/tool callers.
    SetRichText {
        page_id: PageId,
        id: NodeId,
        content: RichTextDocument,
    },
    ReplaceAsset {
        page_id: PageId,
        id: NodeId,
        asset_id: AssetId,
    },
    UpsertAsset {
        record: AssetRecord,
    },
    RemoveAsset {
        asset_id: AssetId,
    },
    SetTheme {
        theme: WebThemeRef,
    },
    SetPageMeta {
        page_id: PageId,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        name: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        route: Option<String>,
    },
    SetCustomCss {
        css: String,
    },
    /// Insert a whole page (F5). An empty page is its root Container alone. Refused when the
    /// id or route already exists, the route fails the grammar, or `root` is not in `nodes`.
    AddPage {
        page: crate::doc::WebPage,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        index: Option<usize>,
    },
    /// Remove a page; the inverse re-inserts it verbatim at its former index. The last page
    /// is refused by name (validation would refuse it too, as LUMW0002).
    RemovePage {
        page_id: PageId,
    },
}

/// Apply a batch atomically. Returns the inverse batch (in inverse order:
/// applying it verbatim restores the pre-batch document).
pub fn apply_operations(
    doc: &mut WebDoc,
    operations: &[WebOperation],
) -> Result<Vec<WebOperation>, WebOpError> {
    let mut draft = doc.clone();
    let mut inverses = Vec::with_capacity(operations.len());
    for operation in operations {
        inverses.push(apply_operation_in_place(&mut draft, operation)?);
    }
    inverses.reverse();
    *doc = draft;
    Ok(inverses)
}

/// Apply a batch atomically AND require the resulting document to validate:
/// any Error diagnostic rejects the whole batch (the scene engine's checked
/// apply, mirrored). Returns the inverse batch plus surviving non-error
/// diagnostics.
pub fn apply_operations_checked(
    doc: &mut WebDoc,
    operations: &[WebOperation],
) -> Result<(Vec<WebOperation>, Vec<Diagnostic>), WebOpError> {
    let mut draft = doc.clone();
    let mut inverses = Vec::with_capacity(operations.len());
    for operation in operations {
        inverses.push(apply_operation_in_place(&mut draft, operation)?);
    }
    let diagnostics = validate_web_doc(&draft);
    if diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    {
        let summary = diagnostics
            .iter()
            .find(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
            .map(|diagnostic| format!("{}: {}", diagnostic.code, diagnostic.message))
            .unwrap_or_default();
        let mut error = WebOpError::new(
            "op.validation_failed",
            format!("batch would leave the document invalid ({summary})"),
        );
        error.diagnostics = diagnostics;
        return Err(error);
    }
    inverses.reverse();
    *doc = draft;
    Ok((inverses, diagnostics))
}

/// Ops are a write path exactly like ingestion: content-bearing props are
/// canonicalized on the way in, so stored inline markup is always sanitized
/// and hrefs always scheme-checked — no matter which surface authored the op.
fn canonicalize_incoming_kind(kind: &mut WebNodeKind) -> Result<(), WebOpError> {
    match kind {
        WebNodeKind::Text { variant, content } => {
            validate_rich_text(content)?;
            validate_rich_text_variant(*variant, content)?;
        }
        WebNodeKind::Button { label, action, .. } => {
            *label = sanitize_inline(label).html;
            // Command buttons carry no href; only the Href action is scheme-checked.
            if let ButtonAction::Href { href, .. } = action {
                if !href_is_allowed(href) {
                    return Err(WebOpError::new(
                        "op.href_invalid",
                        format!("button href is not allowed: {href}"),
                    ));
                }
            }
        }
        WebNodeKind::Image {
            href: Some(href), ..
        } => {
            if !href_is_allowed(href) {
                return Err(WebOpError::new(
                    "op.href_invalid",
                    format!("image href is not allowed: {href}"),
                ));
            }
        }
        WebNodeKind::Container { href, new_tab, .. } => {
            if let Some(value) = href {
                let trimmed = value.trim();
                if trimmed.is_empty() {
                    *href = None;
                    *new_tab = false;
                } else if !href_is_allowed(trimmed) {
                    return Err(WebOpError::new(
                        "op.href_invalid",
                        format!("container href is not allowed: {value}"),
                    ));
                } else if trimmed != value {
                    *value = trimmed.to_owned();
                }
            } else {
                *new_tab = false;
            }
        }
        WebNodeKind::Embed { provider, url, .. } => {
            // html is NOT sanitized: embeds are sandboxed by design.
            match provider {
                EmbedProvider::Calendly => {
                    if !url.as_deref().is_some_and(calendly_url_is_valid) {
                        return Err(WebOpError::new(
                            "op.embed_url_invalid",
                            format!("calendly embed url is not a valid calendly link: {url:?}"),
                        ));
                    }
                }
                EmbedProvider::Custom => {
                    // Permissive human path: any https URL is accepted. A
                    // calendly.com URL is PROMOTED to the Calendly provider so
                    // the allowlist semantics (editor badge, provider-aware
                    // rendering) hold no matter which write path authored it —
                    // ops payloads routinely omit `provider` and default here.
                    if let Some(url_value) = url {
                        if calendly_url_is_valid(url_value) {
                            *provider = EmbedProvider::Calendly;
                        } else if !url_value
                            .trim()
                            .to_ascii_lowercase()
                            .starts_with("https://")
                        {
                            return Err(WebOpError::new(
                                "op.embed_url_invalid",
                                format!("custom embed url must be https: {url_value}"),
                            ));
                        }
                    }
                }
            }
        }
        WebNodeKind::CustomComponent {
            slug,
            artifact_id,
            props,
        } => {
            if !custom_component_slug_is_valid(slug) {
                return Err(WebOpError::new(
                    "op.custom_component_slug_invalid",
                    format!("custom component slug is invalid: {slug}"),
                ));
            }
            if !custom_component_artifact_id_is_valid(artifact_id) {
                return Err(WebOpError::new(
                    "op.custom_component_artifact_invalid",
                    format!("custom component artifact id is invalid: {artifact_id}"),
                ));
            }
            if let Some(issue) = custom_component_props_issue(props) {
                return Err(WebOpError::new(
                    "op.custom_component_props_invalid",
                    format!("custom component {issue}"),
                ));
            }
        }
        WebNodeKind::Fragment {
            fragment_id, slots, ..
        } => {
            // Both the artifact pin and the slot values are checked here, so
            // InsertNode and SetNodeProps (which routes props through this
            // function) enforce the same bounds: props arriving via an op are
            // exactly as untrusted as a node arriving via one.
            if !fragment_id_is_valid(fragment_id) {
                return Err(WebOpError::new(
                    "op.fragment_id_invalid",
                    format!("fragment id is invalid: {fragment_id}"),
                ));
            }
            if let Some(issue) = fragment_slots_issue(slots) {
                return Err(WebOpError::new(
                    "op.fragment_slots_invalid",
                    format!("fragment {issue}"),
                ));
            }
        }
        _ => {}
    }
    Ok(())
}

fn validate_rich_text(content: &RichTextDocument) -> Result<(), WebOpError> {
    if let Some(issue) = content.validate().first() {
        return Err(WebOpError::new(
            "op.rich_text_invalid",
            format!("rich-text content is invalid: {issue}"),
        ));
    }
    Ok(())
}

fn validate_rich_text_variant(
    variant: TextVariant,
    content: &RichTextDocument,
) -> Result<(), WebOpError> {
    if !variant.allows_structured_rich_text() && !content.is_single_paragraph() {
        return Err(WebOpError::new(
            "op.rich_text_variant_invalid",
            format!(
                "{} text must contain exactly one paragraph; switch the node to body or small before adding paragraphs or lists",
                variant.as_str()
            ),
        ));
    }
    Ok(())
}

fn apply_operation_in_place(
    doc: &mut WebDoc,
    operation: &WebOperation,
) -> Result<WebOperation, WebOpError> {
    match operation {
        WebOperation::InsertNode {
            page_id,
            parent,
            index,
            nodes,
            root,
        } => {
            let page = require_page_mut(doc, page_id)?;
            let parent_node = page.nodes.get(parent).ok_or_else(|| {
                WebOpError::new("op.parent_missing", format!("parent `{parent}` not found"))
            })?;
            if !parent_node.kind.is_branch() {
                return Err(WebOpError::new(
                    "op.parent_not_branch",
                    format!("parent `{parent}` cannot hold children"),
                ));
            }
            if *index > parent_node.children.len() {
                return Err(WebOpError::new(
                    "op.index_out_of_bounds",
                    format!(
                        "index {index} exceeds child count {}",
                        parent_node.children.len()
                    ),
                ));
            }
            let mut incoming = BTreeSet::new();
            for node in nodes {
                if !incoming.insert(node.id.clone()) {
                    return Err(WebOpError::new(
                        "op.duplicate_node",
                        format!("subtree repeats id `{}`", node.id),
                    ));
                }
                if page.nodes.contains_key(&node.id) {
                    return Err(WebOpError::new(
                        "op.id_taken",
                        format!("node id `{}` already exists", node.id),
                    ));
                }
            }
            if !incoming.contains(root) {
                return Err(WebOpError::new(
                    "op.root_not_in_subtree",
                    format!("root `{root}` is not among the inserted nodes"),
                ));
            }
            // Subtree integrity: children must resolve inside the subtree
            // itself (pointing at existing page nodes would give them two
            // parents), and every non-root inserted node needs exactly one.
            let mut child_counts: BTreeMap<NodeId, usize> = BTreeMap::new();
            for node in nodes {
                for child in &node.children {
                    if !incoming.contains(child) {
                        return Err(WebOpError::new(
                            "op.subtree_invalid",
                            format!(
                                "inserted node `{}` lists child `{child}` outside the subtree",
                                node.id
                            ),
                        ));
                    }
                    *child_counts.entry(child.clone()).or_default() += 1;
                }
            }
            for node in nodes {
                let count = child_counts.get(&node.id).copied().unwrap_or(0);
                if node.id == *root {
                    if count != 0 {
                        return Err(WebOpError::new(
                            "op.subtree_invalid",
                            format!("subtree root `{root}` may not also appear as a child"),
                        ));
                    }
                } else if count != 1 {
                    return Err(WebOpError::new(
                        "op.subtree_invalid",
                        format!(
                            "inserted node `{}` has {count} parents (expected exactly 1)",
                            node.id
                        ),
                    ));
                }
            }
            for node in nodes {
                let mut node = node.clone();
                canonicalize_incoming_kind(&mut node.kind)?;
                page.nodes.insert(node.id.clone(), node);
            }
            let parent_node = page.nodes.get_mut(parent).expect("parent checked");
            parent_node.children.insert(*index, root.clone());
            Ok(WebOperation::RemoveNode {
                page_id: page_id.clone(),
                id: root.clone(),
            })
        }
        WebOperation::RemoveNode { page_id, id } => {
            let page = require_page_mut(doc, page_id)?;
            if *id == page.root {
                return Err(WebOpError::new(
                    "op.cannot_remove_root",
                    "the page root is fixed",
                ));
            }
            if !page.nodes.contains_key(id) {
                return Err(WebOpError::new(
                    "op.node_missing",
                    format!("node `{id}` not found"),
                ));
            }
            let parent_id = page.parent_of(id).cloned().ok_or_else(|| {
                WebOpError::new("op.node_detached", format!("node `{id}` has no parent"))
            })?;
            // Collect the subtree (preorder) before removal for the inverse.
            let mut subtree = Vec::new();
            let mut stack = vec![id.clone()];
            while let Some(current) = stack.pop() {
                if let Some(node) = page.nodes.get(&current) {
                    subtree.push(node.clone());
                    for child in node.children.iter().rev() {
                        stack.push(child.clone());
                    }
                }
            }
            for node in &subtree {
                page.nodes.remove(&node.id);
            }
            let parent = page.nodes.get_mut(&parent_id).expect("parent exists");
            let index = parent
                .children
                .iter()
                .position(|child| child == id)
                .expect("child listed in parent");
            parent.children.remove(index);
            Ok(WebOperation::InsertNode {
                page_id: page_id.clone(),
                parent: parent_id,
                index,
                nodes: subtree,
                root: id.clone(),
            })
        }
        WebOperation::MoveNode {
            page_id,
            id,
            new_parent,
            index,
        } => {
            let page = require_page_mut(doc, page_id)?;
            if *id == page.root {
                return Err(WebOpError::new(
                    "op.cannot_move_root",
                    "the page root is fixed",
                ));
            }
            if !page.nodes.contains_key(id) {
                return Err(WebOpError::new(
                    "op.node_missing",
                    format!("node `{id}` not found"),
                ));
            }
            let target = page.nodes.get(new_parent).ok_or_else(|| {
                WebOpError::new(
                    "op.parent_missing",
                    format!("new parent `{new_parent}` not found"),
                )
            })?;
            if !target.kind.is_branch() {
                return Err(WebOpError::new(
                    "op.parent_not_branch",
                    format!("new parent `{new_parent}` cannot hold children"),
                ));
            }
            // Reparenting under one's own subtree would orphan the branch.
            let mut cursor = Some(new_parent.clone());
            while let Some(current) = cursor {
                if current == *id {
                    return Err(WebOpError::new(
                        "op.cycle",
                        format!("cannot move `{id}` into its own subtree"),
                    ));
                }
                cursor = page.parent_of(&current).cloned();
            }
            let old_parent_id = page.parent_of(id).cloned().ok_or_else(|| {
                WebOpError::new("op.node_detached", format!("node `{id}` has no parent"))
            })?;
            let old_parent = page.nodes.get_mut(&old_parent_id).expect("parent exists");
            let old_index = old_parent
                .children
                .iter()
                .position(|child| child == id)
                .expect("child listed in parent");
            old_parent.children.remove(old_index);
            let target = page.nodes.get_mut(new_parent).expect("target checked");
            if *index > target.children.len() {
                // Restore before failing so the draft stays coherent even
                // though the caller discards it.
                let old_parent = page.nodes.get_mut(&old_parent_id).expect("parent exists");
                old_parent.children.insert(old_index, id.clone());
                return Err(WebOpError::new(
                    "op.index_out_of_bounds",
                    format!("index {index} exceeds target child count"),
                ));
            }
            target.children.insert(*index, id.clone());
            Ok(WebOperation::MoveNode {
                page_id: page_id.clone(),
                id: id.clone(),
                new_parent: old_parent_id,
                index: old_index,
            })
        }
        WebOperation::SetNodeClasses {
            page_id,
            id,
            classes,
        } => {
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let previous = std::mem::replace(&mut node.classes, classes.clone());
            Ok(WebOperation::SetNodeClasses {
                page_id: page_id.clone(),
                id: id.clone(),
                classes: previous,
            })
        }
        WebOperation::SetNodeProps { page_id, id, props } => {
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            if node.kind.kind_name() != props.kind_name() {
                return Err(WebOpError::new(
                    "op.kind_mismatch",
                    format!(
                        "node `{id}` is {}, props are {}",
                        node.kind.kind_name(),
                        props.kind_name()
                    ),
                ));
            }
            let mut incoming = props.clone();
            canonicalize_incoming_kind(&mut incoming)?;
            // Text overrides are owned by SetFragmentTextOverride alone — a
            // props write never touches them. This arm replaces `kind` whole
            // and an incoming Fragment deserializes its override map to empty
            // by `#[serde(default)]`, so without this carry every slot-value
            // write (the agent's bind/rebind, a future inspector) would
            // silently wipe a human's edits. The incoming map is ignored.
            if let (
                WebNodeKind::Fragment {
                    text_overrides: existing,
                    ..
                },
                WebNodeKind::Fragment {
                    text_overrides: incoming_overrides,
                    ..
                },
            ) = (&node.kind, &mut incoming)
            {
                *incoming_overrides = existing.clone();
            }
            let previous = std::mem::replace(&mut node.kind, incoming);
            Ok(WebOperation::SetNodeProps {
                page_id: page_id.clone(),
                id: id.clone(),
                props: previous,
            })
        }
        WebOperation::SetSlotKey {
            page_id,
            id,
            slot_key,
        } => {
            // Canonicalization: a provided key must be charset-valid before it
            // reaches the arena (the `when:` prefix is checked structurally by
            // validate_web_doc, which the checked apply runs).
            if let Some(key) = slot_key {
                if !web_slot_key_is_valid(key) {
                    return Err(WebOpError::new(
                        "op.slot_key_invalid",
                        format!("slot key `{key}` is not valid"),
                    ));
                }
            }
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let previous = std::mem::replace(&mut node.slot_key, slot_key.clone());
            Ok(WebOperation::SetSlotKey {
                page_id: page_id.clone(),
                id: id.clone(),
                slot_key: previous,
            })
        }
        WebOperation::SetFragmentTextOverride {
            page_id,
            id,
            path,
            r#override,
        } => {
            // The path is checked before anything is looked up: a key that is
            // not structural must never reach the arena, whether or not the
            // page and node it names exist.
            if !fragment_override_path_is_valid(path) {
                return Err(WebOpError::new(
                    "op.override_path_invalid",
                    format!("override path `{path}` is not a structural path"),
                ));
            }
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let WebNodeKind::Fragment { text_overrides, .. } = &mut node.kind else {
                return Err(WebOpError::new(
                    "op.node_kind_mismatch",
                    format!("node `{id}` is not a cloned section"),
                ));
            };
            let previous = match r#override {
                Some(value) => text_overrides.insert(path.clone(), value.clone()),
                None => text_overrides.remove(path),
            };
            Ok(WebOperation::SetFragmentTextOverride {
                page_id: page_id.clone(),
                id: id.clone(),
                path: path.clone(),
                r#override: previous,
            })
        }
        WebOperation::SetText {
            page_id,
            id,
            content,
        } => {
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let WebNodeKind::Text {
                variant,
                content: existing,
            } = &mut node.kind
            else {
                return Err(WebOpError::new(
                    "op.not_text",
                    format!("node `{id}` is {}, not text", node.kind.kind_name()),
                ));
            };
            // SetText is the HTML import adapter. Body/Small may carry semantic
            // paragraph/list markup; heading-like variants stay inline-only.
            let imported = if variant.allows_structured_rich_text() {
                RichTextDocument::from_html(content)
            } else {
                RichTextDocument::from_inline_html(content)
            };
            validate_rich_text_variant(*variant, &imported)?;
            let previous = std::mem::replace(existing, imported);
            Ok(WebOperation::SetRichText {
                page_id: page_id.clone(),
                id: id.clone(),
                content: previous,
            })
        }
        WebOperation::SetRichText {
            page_id,
            id,
            content,
        } => {
            validate_rich_text(content)?;
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let WebNodeKind::Text {
                variant,
                content: existing,
            } = &mut node.kind
            else {
                return Err(WebOpError::new(
                    "op.not_text",
                    format!("node `{id}` is {}, not text", node.kind.kind_name()),
                ));
            };
            validate_rich_text_variant(*variant, content)?;
            let previous = std::mem::replace(existing, content.clone());
            Ok(WebOperation::SetRichText {
                page_id: page_id.clone(),
                id: id.clone(),
                content: previous,
            })
        }
        WebOperation::ReplaceAsset {
            page_id,
            id,
            asset_id,
        } => {
            if !doc.assets.contains_key(asset_id) {
                return Err(WebOpError::new(
                    "op.asset_missing",
                    format!("asset `{asset_id}` is not in the document"),
                ));
            }
            let page = require_page_mut(doc, page_id)?;
            let node = page.nodes.get_mut(id).ok_or_else(|| {
                WebOpError::new("op.node_missing", format!("node `{id}` not found"))
            })?;
            let WebNodeKind::Image {
                asset_id: existing, ..
            } = &mut node.kind
            else {
                return Err(WebOpError::new(
                    "op.not_image",
                    format!("node `{id}` is {}, not image", node.kind.kind_name()),
                ));
            };
            let previous = std::mem::replace(existing, asset_id.clone());
            Ok(WebOperation::ReplaceAsset {
                page_id: page_id.clone(),
                id: id.clone(),
                asset_id: previous,
            })
        }
        WebOperation::UpsertAsset { record } => {
            let previous = doc.assets.insert(record.id.clone(), record.clone());
            Ok(match previous {
                Some(previous) => WebOperation::UpsertAsset { record: previous },
                None => WebOperation::RemoveAsset {
                    asset_id: record.id.clone(),
                },
            })
        }
        WebOperation::RemoveAsset { asset_id } => {
            let referencing = doc.pages.iter().find_map(|page| {
                page.nodes.values().find_map(|node| match &node.kind {
                    WebNodeKind::Image { asset_id: used, .. } if used == asset_id => {
                        Some(node.id.clone())
                    }
                    WebNodeKind::Section {
                        background: Some(background),
                        ..
                    }
                    | WebNodeKind::Container {
                        background: Some(background),
                        ..
                    } if &background.asset_id == asset_id => Some(node.id.clone()),
                    _ => None,
                })
            });
            if let Some(node_id) = referencing {
                return Err(WebOpError::new(
                    "op.asset_in_use",
                    format!("asset `{asset_id}` is used by node `{node_id}`"),
                ));
            }
            let previous = doc.assets.remove(asset_id).ok_or_else(|| {
                WebOpError::new(
                    "op.asset_missing",
                    format!("asset `{asset_id}` is not in the document"),
                )
            })?;
            Ok(WebOperation::UpsertAsset { record: previous })
        }
        WebOperation::SetTheme { theme } => {
            let previous = std::mem::replace(&mut doc.theme, theme.clone());
            Ok(WebOperation::SetTheme { theme: previous })
        }
        WebOperation::SetPageMeta {
            page_id,
            name,
            route,
        } => {
            if let Some(candidate) = route {
                if !route_is_valid(candidate) {
                    return Err(WebOpError::new(
                        "op.route_invalid",
                        format!("route `{candidate}` is not a valid site route"),
                    ));
                }
                if doc
                    .pages
                    .iter()
                    .any(|other| &other.id != page_id && &other.route == candidate)
                {
                    return Err(WebOpError::new(
                        "op.route_exists",
                        format!("route `{candidate}` is already taken"),
                    ));
                }
            }
            let page = require_page_mut(doc, page_id)?;
            let mut previous_name = None;
            let mut previous_route = None;
            if let Some(name) = name {
                previous_name = Some(std::mem::replace(&mut page.name, name.clone()));
            }
            if let Some(route) = route {
                previous_route = Some(std::mem::replace(&mut page.route, route.clone()));
            }
            Ok(WebOperation::SetPageMeta {
                page_id: page_id.clone(),
                name: previous_name,
                route: previous_route,
            })
        }
        WebOperation::SetCustomCss { css } => {
            let previous = std::mem::replace(&mut doc.custom_css, css.clone());
            Ok(WebOperation::SetCustomCss { css: previous })
        }
        WebOperation::AddPage { page, index } => {
            if doc.page(&page.id).is_some() {
                return Err(WebOpError::new(
                    "op.page_exists",
                    format!("page `{}` already exists", page.id),
                ));
            }
            if doc.pages.iter().any(|existing| existing.route == page.route) {
                return Err(WebOpError::new(
                    "op.route_exists",
                    format!("route `{}` is already taken", page.route),
                ));
            }
            if !route_is_valid(&page.route) {
                return Err(WebOpError::new(
                    "op.route_invalid",
                    format!("route `{}` is not a valid site route", page.route),
                ));
            }
            if !page.nodes.contains_key(&page.root) {
                return Err(WebOpError::new(
                    "op.page_root_missing",
                    format!("page `{}` root `{}` is not in its nodes", page.id, page.root),
                ));
            }
            let at = index.unwrap_or(doc.pages.len());
            if at > doc.pages.len() {
                return Err(WebOpError::new(
                    "op.index_out_of_range",
                    format!("page index {at} is past the end ({})", doc.pages.len()),
                ));
            }
            doc.pages.insert(at, page.clone());
            Ok(WebOperation::RemovePage {
                page_id: page.id.clone(),
            })
        }
        WebOperation::RemovePage { page_id } => {
            if doc.pages.len() <= 1 {
                return Err(WebOpError::new(
                    "op.cannot_remove_last_page",
                    "a document keeps at least one page",
                ));
            }
            let Some(at) = doc.pages.iter().position(|page| &page.id == page_id) else {
                return Err(WebOpError::new(
                    "op.page_missing",
                    format!("page `{page_id}` not found"),
                ));
            };
            let page = doc.pages.remove(at);
            Ok(WebOperation::AddPage {
                page,
                index: Some(at),
            })
        }
    }
}

fn require_page_mut<'doc>(
    doc: &'doc mut WebDoc,
    page_id: &PageId,
) -> Result<&'doc mut crate::doc::WebPage, WebOpError> {
    doc.page_mut(page_id)
        .ok_or_else(|| WebOpError::new("op.page_missing", format!("page `{page_id}` not found")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::{
        SectionTag, TextVariant, WebBackgroundFit, WebBackgroundImage, WebBackgroundPosition,
        WebBackgroundScrim, WebScrimColor, WebThemeRef,
    };
    use crate::ingest::ingest_html_into_page;
    use crate::rich_text::{
        RichTextBlock, RichTextInline, RichTextLink, RichTextListItem, RichTextListType,
        RichTextMarks, RICH_TEXT_SCHEMA_VERSION,
    };
    use crate::theme::{compile_web_theme, WebThemeOptions};

    fn fixture() -> WebDoc {
        let (theme, _) =
            compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default());
        let mut doc = WebDoc::new("d1", "Site", None);
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="hero">
                 <div id="stack" class="flex flex-col gap-4">
                   <h1 id="headline">Hello</h1>
                   <p id="sub">World</p>
                 </div>
               </section>
               <section id="features">
                 <div id="grid" class="grid grid-cols-3"><p id="f1">One</p></div>
               </section>"#,
            &theme,
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        doc
    }

    fn page_id() -> PageId {
        PageId::from("home")
    }

    #[test]
    fn every_op_inverse_restores_the_document() {
        let base = fixture();
        let text_node = WebNode {
            id: NodeId::from("new_txt"),
            kind: WebNodeKind::Text {
                variant: TextVariant::Body,
                content: "inserted".to_owned().into(),
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let section = WebNode::branch(
            NodeId::from("new_sec"),
            WebNodeKind::Section {
                tag: SectionTag::Section,
                anchor_id: None,
                background: None,
            },
            "",
        );
        let cases: Vec<WebOperation> = vec![
            WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 1,
                nodes: vec![text_node],
                root: NodeId::from("new_txt"),
            },
            WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("root"),
                index: 2,
                nodes: vec![section],
                root: NodeId::from("new_sec"),
            },
            WebOperation::RemoveNode {
                page_id: page_id(),
                id: NodeId::from("stack"),
            },
            WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("sub"),
                new_parent: NodeId::from("grid"),
                index: 0,
            },
            WebOperation::SetNodeClasses {
                page_id: page_id(),
                id: NodeId::from("stack"),
                classes: "flex gap-8".to_owned(),
            },
            WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("headline"),
                props: WebNodeKind::Text {
                    variant: TextVariant::Display,
                    content: "Bigger".to_owned().into(),
                },
            },
            WebOperation::SetText {
                page_id: page_id(),
                id: NodeId::from("sub"),
                content: "Updated <strong>copy</strong>".to_owned(),
            },
            WebOperation::SetSlotKey {
                page_id: page_id(),
                id: NodeId::from("headline"),
                slot_key: Some(SlotKey::from("account.headline")),
            },
            WebOperation::SetTheme {
                theme: WebThemeRef {
                    brand_kit: None,
                    overrides: [("primary".to_owned(), "#123456".to_owned())].into(),
                },
            },
            WebOperation::SetPageMeta {
                page_id: page_id(),
                name: Some("Landing".to_owned()),
                route: None,
            },
            WebOperation::SetCustomCss {
                css: "@keyframes x { from { opacity: 0 } }".to_owned(),
            },
        ];
        for operation in cases {
            let mut doc = base.clone();
            let inverses =
                apply_operations(&mut doc, std::slice::from_ref(&operation)).expect("apply");
            assert_ne!(doc, base, "operation must change the doc: {operation:?}");
            apply_operations(&mut doc, &inverses).expect("apply inverse");
            assert_eq!(doc, base, "inverse must restore: {operation:?}");
        }
    }

    fn custom_component_node(id: &str, digest_char: char) -> WebNode {
        WebNode {
            id: NodeId::from(id),
            kind: WebNodeKind::CustomComponent {
                slug: "book-a-call".to_owned(),
                artifact_id: format!("ccart_{}", digest_char.to_string().repeat(64)),
                props: BTreeMap::from([
                    (
                        "headline".to_owned(),
                        crate::doc::CustomComponentValue::String("Book a call".to_owned()),
                    ),
                    (
                        "showLogo".to_owned(),
                        crate::doc::CustomComponentValue::Boolean(true),
                    ),
                ]),
            },
            classes: "w-[480px] h-[240px]".to_owned(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        }
    }

    #[test]
    fn custom_component_insert_edit_move_duplicate_delete_and_inverses_are_total() {
        let base = fixture();
        let mut doc = base.clone();

        let insert = WebOperation::InsertNode {
            page_id: page_id(),
            parent: NodeId::from("stack"),
            index: 2,
            nodes: vec![custom_component_node("cc_form", 'a')],
            root: NodeId::from("cc_form"),
        };
        let (insert_inverse, _) =
            apply_operations_checked(&mut doc, std::slice::from_ref(&insert)).expect("insert");

        let edit_batch = vec![
            WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("cc_form"),
                props: WebNodeKind::CustomComponent {
                    slug: "book-a-call".to_owned(),
                    artifact_id: format!("ccart_{}", "b".repeat(64)),
                    props: BTreeMap::from([(
                        "headline".to_owned(),
                        crate::doc::CustomComponentValue::String("Choose a time".to_owned()),
                    )]),
                },
            },
            WebOperation::SetNodeClasses {
                page_id: page_id(),
                id: NodeId::from("cc_form"),
                classes: "w-[560px] h-[300px]".to_owned(),
            },
            WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("cc_form"),
                new_parent: NodeId::from("grid"),
                index: 1,
            },
            WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("grid"),
                index: 2,
                nodes: vec![custom_component_node("cc_copy", 'b')],
                root: NodeId::from("cc_copy"),
            },
            WebOperation::RemoveNode {
                page_id: page_id(),
                id: NodeId::from("cc_copy"),
            },
        ];
        let (edit_inverse, diagnostics) =
            apply_operations_checked(&mut doc, &edit_batch).expect("edit batch");
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));

        let node = doc.pages[0]
            .node(&NodeId::from("cc_form"))
            .expect("custom component");
        assert_eq!(node.classes, "w-[560px] h-[300px]");
        let WebNodeKind::CustomComponent {
            artifact_id, props, ..
        } = &node.kind
        else {
            panic!("custom component");
        };
        assert_eq!(artifact_id, &format!("ccart_{}", "b".repeat(64)));
        assert_eq!(
            props.get("headline"),
            Some(&crate::doc::CustomComponentValue::String(
                "Choose a time".to_owned()
            ))
        );
        assert_eq!(
            doc.pages[0].parent_of(&NodeId::from("cc_form")),
            Some(&NodeId::from("grid"))
        );
        assert!(doc.pages[0].node(&NodeId::from("cc_copy")).is_none());

        apply_operations_checked(&mut doc, &edit_inverse).expect("undo edit batch");
        apply_operations_checked(&mut doc, &insert_inverse).expect("undo insert");
        assert_eq!(doc, base);
    }

    #[test]
    fn custom_component_is_never_a_move_parent() {
        let mut doc = fixture();
        apply_operations_checked(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 2,
                nodes: vec![custom_component_node("cc_form", 'a')],
                root: NodeId::from("cc_form"),
            }],
        )
        .expect("insert");
        let error = apply_operations_checked(
            &mut doc,
            &[WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("sub"),
                new_parent: NodeId::from("cc_form"),
                index: 0,
            }],
        )
        .expect_err("leaf rejects children");
        assert_eq!(error.code, "op.parent_not_branch");
    }

    /// A document whose asset registry holds the logo a fragment slot binds.
    /// An asset slot resolves through `doc.assets` at render (LUMW0035, the
    /// F1.4 ruling), exactly as an Image node's `asset_id` does, so the
    /// document has to hold the record before a write path may name it.
    fn fixture_with_logo() -> WebDoc {
        let mut doc = fixture();
        doc.assets.insert(
            lumen_core::AssetId::from("asset_logo_1"),
            serde_json::from_value(serde_json::json!({
                "id": "asset_logo_1",
                "label": "Logo",
                "kind": "logo",
                "status": "ready",
                "source": {"kind": "generated", "model": "m", "request_id": null},
            }))
            .expect("asset record"),
        );
        doc
    }

    fn fragment_node(id: &str, digest_char: char) -> WebNode {
        WebNode {
            id: NodeId::from(id),
            kind: WebNodeKind::Fragment {
                fragment_id: format!("frag_{}", digest_char.to_string().repeat(16)),
                slots: BTreeMap::from([
                    (
                        "headline".to_owned(),
                        crate::doc::FragmentSlotValue::Text("Book a call".to_owned()),
                    ),
                    (
                        "logo".to_owned(),
                        crate::doc::FragmentSlotValue::Asset("asset_logo_1".to_owned()),
                    ),
                    (
                        "badge".to_owned(),
                        crate::doc::FragmentSlotValue::Visible(true),
                    ),
                ]),
                text_overrides: BTreeMap::new(),
            },
            classes: "w-full".to_owned(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        }
    }

    #[test]
    fn fragment_insert_edit_move_duplicate_delete_and_inverses_are_total() {
        let base = fixture_with_logo();
        let mut doc = base.clone();

        let insert = WebOperation::InsertNode {
            page_id: page_id(),
            parent: NodeId::from("stack"),
            index: 2,
            nodes: vec![fragment_node("frg_hero", 'a')],
            root: NodeId::from("frg_hero"),
        };
        let (insert_inverse, _) =
            apply_operations_checked(&mut doc, std::slice::from_ref(&insert)).expect("insert");

        let edit_batch = vec![
            // SetNodeProps is the slot-value write path.
            WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                props: WebNodeKind::Fragment {
                    fragment_id: format!("frag_{}", "a".repeat(16)),
                    slots: BTreeMap::from([
                        (
                            "headline".to_owned(),
                            crate::doc::FragmentSlotValue::Text("Choose a time".to_owned()),
                        ),
                        (
                            "badge".to_owned(),
                            crate::doc::FragmentSlotValue::Visible(false),
                        ),
                    ]),
                    text_overrides: BTreeMap::new(),
                },
            },
            WebOperation::SetNodeClasses {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                classes: "w-full py-12".to_owned(),
            },
            WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                new_parent: NodeId::from("grid"),
                index: 1,
            },
            WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("grid"),
                index: 2,
                nodes: vec![fragment_node("frg_copy", 'b')],
                root: NodeId::from("frg_copy"),
            },
            WebOperation::RemoveNode {
                page_id: page_id(),
                id: NodeId::from("frg_copy"),
            },
        ];
        let (edit_inverse, diagnostics) =
            apply_operations_checked(&mut doc, &edit_batch).expect("edit batch");
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));

        let node = doc.pages[0]
            .node(&NodeId::from("frg_hero"))
            .expect("fragment");
        assert_eq!(node.classes, "w-full py-12");
        let WebNodeKind::Fragment { slots, .. } = &node.kind else {
            panic!("fragment");
        };
        assert_eq!(
            slots.get("headline"),
            Some(&crate::doc::FragmentSlotValue::Text(
                "Choose a time".to_owned()
            ))
        );
        assert_eq!(
            slots.get("badge"),
            Some(&crate::doc::FragmentSlotValue::Visible(false))
        );
        assert_eq!(slots.get("logo"), None, "props replacement is whole-map");
        assert_eq!(
            doc.pages[0].parent_of(&NodeId::from("frg_hero")),
            Some(&NodeId::from("grid"))
        );
        assert!(doc.pages[0].node(&NodeId::from("frg_copy")).is_none());

        apply_operations_checked(&mut doc, &edit_inverse).expect("undo edit batch");
        apply_operations_checked(&mut doc, &insert_inverse).expect("undo insert");
        assert_eq!(doc, base);
    }

    /// A document with one inserted fragment under `stack`, built from the
    /// same helpers the other fragment tests use so the node ids and the slot
    /// shape are the real ones.
    fn doc_with_pinned_fragment() -> WebDoc {
        let mut doc = fixture_with_logo();
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 2,
                nodes: vec![fragment_node("frg_hero", 'a')],
                root: NodeId::from("frg_hero"),
            }],
        )
        .expect("insert fragment");
        doc
    }

    fn text_overrides_of(doc: &WebDoc, id: &str) -> BTreeMap<String, FragmentTextOverride> {
        let node = doc.pages[0].node(&NodeId::from(id)).expect("node");
        let WebNodeKind::Fragment { text_overrides, .. } = &node.kind else {
            panic!("fragment");
        };
        text_overrides.clone()
    }

    #[test]
    fn set_fragment_text_override_applies_and_inverts() {
        let base = doc_with_pinned_fragment();
        let mut doc = base.clone();
        let set = WebOperation::SetFragmentTextOverride {
            page_id: page_id(),
            id: NodeId::from("frg_hero"),
            path: ":nth-child(1)".to_owned(),
            r#override: Some(FragmentTextOverride {
                text: "Shorter".to_owned(),
                bold: true,
                italic: false,
                underline: false,
                size: Some(1),
            }),
        };
        let inverse = apply_operations(&mut doc, std::slice::from_ref(&set)).expect("applies");
        let overrides = text_overrides_of(&doc, "frg_hero");
        assert_eq!(overrides[":nth-child(1)"].text, "Shorter");
        assert!(overrides[":nth-child(1)"].bold);
        assert_eq!(overrides[":nth-child(1)"].size, Some(1));

        // The inverse of a FIRST write is a clear, not the old string: before
        // the edit the artifact's own text was what rendered, and nothing in
        // the document held it.
        assert_eq!(
            inverse,
            vec![WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                path: ":nth-child(1)".to_owned(),
                r#override: None,
            }]
        );
        apply_operations(&mut doc, &inverse).expect("inverse applies");
        assert!(text_overrides_of(&doc, "frg_hero").is_empty());
        assert_eq!(doc, base);

        // A SECOND write returns the displaced override, so undo restores the
        // human's previous edit rather than the artifact's text.
        let mut doc = base.clone();
        apply_operations(&mut doc, std::slice::from_ref(&set)).expect("first write");
        let second = WebOperation::SetFragmentTextOverride {
            page_id: page_id(),
            id: NodeId::from("frg_hero"),
            path: ":nth-child(1)".to_owned(),
            r#override: Some(FragmentTextOverride {
                text: "Shorter still".to_owned(),
                bold: false,
                italic: true,
                underline: false,
                size: None,
            }),
        };
        let inverse = apply_operations(&mut doc, &[second]).expect("second write");
        assert_eq!(
            text_overrides_of(&doc, "frg_hero")[":nth-child(1)"].text,
            "Shorter still"
        );
        apply_operations(&mut doc, &inverse).expect("undo second write");
        let restored = text_overrides_of(&doc, "frg_hero");
        assert_eq!(restored[":nth-child(1)"].text, "Shorter");
        assert!(restored[":nth-child(1)"].bold);

        // A clear on a path carrying nothing is a no-op whose inverse is also
        // a clear — the op is total, not conditional on prior state.
        let mut doc = base.clone();
        let inverse = apply_operations(
            &mut doc,
            &[WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                path: ":nth-child(7)".to_owned(),
                r#override: None,
            }],
        )
        .expect("clear of nothing");
        assert_eq!(doc, base);
        assert_eq!(
            inverse,
            vec![WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                path: ":nth-child(7)".to_owned(),
                r#override: None,
            }]
        );
    }

    #[test]
    fn set_fragment_text_override_refuses_non_fragments_and_bad_paths() {
        let base = doc_with_pinned_fragment();

        // The path grammar is checked BEFORE the page and node are looked up,
        // so a bad path is refused even when it names something real.
        for bad_path in [
            "div > h2",
            ":nth-child(0)",
            ":nth-child(1) > ",
            "",
            ".headline",
        ] {
            let mut doc = base.clone();
            let error = apply_operations(
                &mut doc,
                &[WebOperation::SetFragmentTextOverride {
                    page_id: page_id(),
                    id: NodeId::from("frg_hero"),
                    path: bad_path.to_owned(),
                    r#override: Some(FragmentTextOverride {
                        text: "x".to_owned(),
                        bold: false,
                        italic: false,
                        underline: false,
                        size: None,
                    }),
                }],
            )
            .expect_err("bad override path");
            assert_eq!(error.code, "op.override_path_invalid", "{bad_path:?}");
            assert_eq!(doc, base, "rejected op must not mutate");
        }

        // Only a clone carries overrides. `stack` is a plain container.
        let mut doc = base.clone();
        let error = apply_operations(
            &mut doc,
            &[WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("stack"),
                path: ":nth-child(1)".to_owned(),
                r#override: None,
            }],
        )
        .expect_err("not a fragment");
        assert_eq!(error.code, "op.node_kind_mismatch");
        assert_eq!(doc, base, "rejected op must not mutate");

        // A missing node and a missing page are refused by name too.
        let mut doc = base.clone();
        let error = apply_operations(
            &mut doc,
            &[WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("frg_ghost"),
                path: ":nth-child(1)".to_owned(),
                r#override: None,
            }],
        )
        .expect_err("missing node");
        assert_eq!(error.code, "op.node_missing");
        let error = apply_operations(
            &mut doc,
            &[WebOperation::SetFragmentTextOverride {
                page_id: PageId::from("ghost"),
                id: NodeId::from("frg_hero"),
                path: ":nth-child(1)".to_owned(),
                r#override: None,
            }],
        )
        .expect_err("missing page");
        assert_eq!(error.code, "op.page_missing");
        assert_eq!(doc, base, "rejected op must not mutate");
    }

    #[test]
    fn set_node_props_preserves_a_humans_text_overrides() {
        // Text overrides are owned by SetFragmentTextOverride alone. Every
        // slot-value writer goes through SetNodeProps, which replaces `kind`
        // whole; without the carry, the agent rebinding a slot would silently
        // wipe the human's edit.
        let mut doc = doc_with_pinned_fragment();
        apply_operations(
            &mut doc,
            &[WebOperation::SetFragmentTextOverride {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                path: ":nth-child(1)".to_owned(),
                r#override: Some(FragmentTextOverride {
                    text: "Human copy".to_owned(),
                    bold: true,
                    italic: false,
                    underline: false,
                    size: Some(-1),
                }),
            }],
        )
        .expect("override");
        let before = doc.clone();

        let props = WebNodeKind::Fragment {
            fragment_id: format!("frag_{}", "a".repeat(16)),
            slots: BTreeMap::from([(
                "headline".to_owned(),
                crate::doc::FragmentSlotValue::Text("Agent copy".to_owned()),
            )]),
            // The incoming map is empty — as it always is off the wire, where
            // `text_overrides` is `#[serde(default)]`.
            text_overrides: BTreeMap::new(),
        };
        let inverse = apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                props,
            }],
        )
        .expect("props write");

        let node = doc.pages[0]
            .node(&NodeId::from("frg_hero"))
            .expect("fragment");
        let WebNodeKind::Fragment {
            slots,
            text_overrides,
            ..
        } = &node.kind
        else {
            panic!("fragment");
        };
        assert_eq!(
            slots.get("headline"),
            Some(&crate::doc::FragmentSlotValue::Text(
                "Agent copy".to_owned()
            )),
            "the slot write still lands"
        );
        assert_eq!(slots.get("logo"), None, "props replacement is whole-map");
        assert_eq!(
            text_overrides[":nth-child(1)"].text, "Human copy",
            "a props write never touches text overrides"
        );

        // An incoming map that DOES carry overrides is ignored, not merged.
        let mut carrying = doc.clone();
        apply_operations(
            &mut carrying,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("frg_hero"),
                props: WebNodeKind::Fragment {
                    fragment_id: format!("frag_{}", "a".repeat(16)),
                    slots: BTreeMap::new(),
                    text_overrides: BTreeMap::from([(
                        ":nth-child(9)".to_owned(),
                        FragmentTextOverride {
                            text: "Smuggled".to_owned(),
                            bold: false,
                            italic: false,
                            underline: false,
                            size: None,
                        },
                    )]),
                },
            }],
        )
        .expect("props write");
        assert_eq!(
            text_overrides_of(&carrying, "frg_hero"),
            text_overrides_of(&doc, "frg_hero")
        );

        // The inverse is the previous kind, so undo restores both.
        apply_operations(&mut doc, &inverse).expect("undo props write");
        assert_eq!(doc, before);
    }

    #[test]
    fn set_fragment_text_override_round_trips_on_the_wire() {
        let op = WebOperation::SetFragmentTextOverride {
            page_id: page_id(),
            id: NodeId::from("frg_hero"),
            path: ":nth-child(1)".to_owned(),
            r#override: Some(FragmentTextOverride {
                text: "Shorter".to_owned(),
                bold: true,
                italic: false,
                underline: false,
                size: Some(1),
            }),
        };
        let value = serde_json::to_value(&op).expect("serialize");
        assert_eq!(
            value,
            serde_json::json!({
                "kind": "set_fragment_text_override",
                "page_id": "home",
                "id": "frg_hero",
                "path": ":nth-child(1)",
                "override": {
                    "text": "Shorter",
                    "bold": true,
                    "italic": false,
                    "underline": false,
                    "size": 1,
                },
            })
        );
        assert_eq!(
            serde_json::from_value::<WebOperation>(value).expect("deserialize"),
            op
        );

        // A clear: `null` and an absent key both mean None, and None is
        // written back out without the key at all.
        let clear = WebOperation::SetFragmentTextOverride {
            page_id: page_id(),
            id: NodeId::from("frg_hero"),
            path: ":nth-child(1)".to_owned(),
            r#override: None,
        };
        let json = serde_json::to_string(&clear).expect("serialize");
        // The KEY, not the substring: `"override"` also occurs inside the
        // kind name `set_fragment_text_override`.
        assert!(!json.contains(r#""override":"#), "{json}");
        for wire in [
            r#"{"kind":"set_fragment_text_override","page_id":"home","id":"frg_hero","path":":nth-child(1)"}"#,
            r#"{"kind":"set_fragment_text_override","page_id":"home","id":"frg_hero","path":":nth-child(1)","override":null}"#,
        ] {
            assert_eq!(
                serde_json::from_str::<WebOperation>(wire).expect("deserialize"),
                clear,
                "{wire}"
            );
        }
    }

    #[test]
    fn fragment_is_never_a_move_parent() {
        let mut doc = fixture_with_logo();
        apply_operations_checked(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 2,
                nodes: vec![fragment_node("frg_hero", 'a')],
                root: NodeId::from("frg_hero"),
            }],
        )
        .expect("insert");
        let error = apply_operations_checked(
            &mut doc,
            &[WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("sub"),
                new_parent: NodeId::from("frg_hero"),
                index: 0,
            }],
        )
        .expect_err("leaf rejects children");
        assert_eq!(error.code, "op.parent_not_branch");
    }

    #[test]
    fn fragment_ops_refuse_bad_ids_and_out_of_bounds_slots() {
        let base = fixture();

        // Insert path: the id shape is enforced before the node lands.
        for bad_id in [
            "latest",
            "frag_0123456789ABCDEF",
            "frag_\"><style>x",
            "frag_short",
        ] {
            let mut doc = base.clone();
            let mut node = fragment_node("frg_hero", 'a');
            let WebNodeKind::Fragment { fragment_id, .. } = &mut node.kind else {
                panic!("fragment");
            };
            *fragment_id = bad_id.to_owned();
            let error = apply_operations(
                &mut doc,
                &[WebOperation::InsertNode {
                    page_id: page_id(),
                    parent: NodeId::from("stack"),
                    index: 2,
                    nodes: vec![node],
                    root: NodeId::from("frg_hero"),
                }],
            )
            .expect_err("bad fragment id");
            assert_eq!(error.code, "op.fragment_id_invalid", "{bad_id}");
            assert_eq!(doc, base, "rejected op must not mutate");
        }

        // Insert path: slot bounds.
        let mut doc = base.clone();
        let mut node = fragment_node("frg_hero", 'a');
        let WebNodeKind::Fragment { slots, .. } = &mut node.kind else {
            panic!("fragment");
        };
        slots.insert(
            "headline".to_owned(),
            crate::doc::FragmentSlotValue::Text(
                "x".repeat(crate::doc::MAX_FRAGMENT_SLOT_VALUE_BYTES + 1),
            ),
        );
        let error = apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 2,
                nodes: vec![node],
                root: NodeId::from("frg_hero"),
            }],
        )
        .expect_err("oversized slot value");
        assert_eq!(error.code, "op.fragment_slots_invalid");
        assert_eq!(doc, base, "rejected op must not mutate");

        // Props path: props arriving via ops are as untrusted as nodes are.
        let mut doc = base.clone();
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 2,
                nodes: vec![fragment_node("frg_hero", 'a')],
                root: NodeId::from("frg_hero"),
            }],
        )
        .expect("insert");
        let inserted = doc.clone();
        for (props, expected) in [
            (
                WebNodeKind::Fragment {
                    fragment_id: "frag_not_hex_at_all".to_owned(),
                    slots: BTreeMap::new(),
                    text_overrides: BTreeMap::new(),
                },
                "op.fragment_id_invalid",
            ),
            (
                WebNodeKind::Fragment {
                    fragment_id: format!("frag_{}", "a".repeat(16)),
                    slots: BTreeMap::from([(
                        "logo".to_owned(),
                        crate::doc::FragmentSlotValue::Asset("not an asset id".to_owned()),
                    )]),
                    text_overrides: BTreeMap::new(),
                },
                "op.fragment_slots_invalid",
            ),
            (
                WebNodeKind::Fragment {
                    fragment_id: format!("frag_{}", "a".repeat(16)),
                    slots: BTreeMap::from([(
                        "k".repeat(crate::doc::MAX_FRAGMENT_SLOT_KEY_CHARS + 1),
                        crate::doc::FragmentSlotValue::Visible(true),
                    )]),
                    text_overrides: BTreeMap::new(),
                },
                "op.fragment_slots_invalid",
            ),
            (
                WebNodeKind::Fragment {
                    fragment_id: format!("frag_{}", "a".repeat(16)),
                    slots: (0..=crate::doc::MAX_FRAGMENT_SLOTS)
                        .map(|index| {
                            (
                                format!("slot_{index}"),
                                crate::doc::FragmentSlotValue::Visible(true),
                            )
                        })
                        .collect(),
                    text_overrides: BTreeMap::new(),
                },
                "op.fragment_slots_invalid",
            ),
        ] {
            let mut doc = inserted.clone();
            let error = apply_operations(
                &mut doc,
                &[WebOperation::SetNodeProps {
                    page_id: page_id(),
                    id: NodeId::from("frg_hero"),
                    props,
                }],
            )
            .expect_err("invalid fragment props");
            assert_eq!(error.code, expected);
            assert_eq!(doc, inserted, "rejected op must not mutate");
        }
    }

    #[test]
    fn batch_is_atomic_on_failure() {
        let base = fixture();
        let mut doc = base.clone();
        let result = apply_operations(
            &mut doc,
            &[
                WebOperation::SetNodeClasses {
                    page_id: page_id(),
                    id: NodeId::from("stack"),
                    classes: "flex".to_owned(),
                },
                WebOperation::RemoveNode {
                    page_id: page_id(),
                    id: NodeId::from("missing"),
                },
            ],
        );
        assert!(result.is_err());
        assert_eq!(doc, base, "failed batch must not mutate");
    }

    #[test]
    fn move_into_own_subtree_is_rejected() {
        let mut doc = fixture();
        let result = apply_operations(
            &mut doc,
            &[WebOperation::MoveNode {
                page_id: page_id(),
                id: NodeId::from("stack"),
                new_parent: NodeId::from("stack"),
                index: 0,
            }],
        );
        assert_eq!(result.unwrap_err().code, "op.cycle");
    }

    #[test]
    fn set_text_sanitizes() {
        let mut doc = fixture();
        apply_operations(
            &mut doc,
            &[WebOperation::SetText {
                page_id: page_id(),
                id: NodeId::from("sub"),
                content: "<script>alert(1)</script>Safe".to_owned(),
            }],
        )
        .expect("apply");
        let page = doc.page(&page_id()).unwrap();
        let WebNodeKind::Text { content, .. } = &page.node(&NodeId::from("sub")).unwrap().kind
        else {
            panic!("text node");
        };
        assert_eq!(content, "Safe");
    }

    #[test]
    fn set_rich_text_is_typed_validated_and_invertible() {
        let base = fixture();
        let content = RichTextDocument {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children: vec![
                    RichTextInline::Text {
                        text: "Hello ".to_owned(),
                        marks: RichTextMarks::default(),
                        classes: None,
                        link: None,
                    },
                    RichTextInline::Text {
                        text: "range".to_owned(),
                        marks: RichTextMarks {
                            bold: true,
                            ..RichTextMarks::default()
                        },
                        classes: None,
                        link: None,
                    },
                ],
            }],
        };
        let mut doc = base.clone();
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::SetRichText {
                page_id: page_id(),
                id: NodeId::from("headline"),
                content,
            }],
        )
        .expect("typed rich-text apply");
        let WebNodeKind::Text { content, .. } = &doc
            .page(&page_id())
            .unwrap()
            .node(&NodeId::from("headline"))
            .unwrap()
            .kind
        else {
            panic!("text node");
        };
        assert_eq!(content.to_inline_html(), "Hello <strong>range</strong>");

        apply_operations(&mut doc, &inverses).expect("rich-text inverse");
        assert_eq!(doc, base);

        let unsafe_content = RichTextDocument {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![RichTextBlock::Paragraph {
                alignment: None,
                children: vec![RichTextInline::Text {
                    text: "unsafe".to_owned(),
                    marks: RichTextMarks::default(),
                    classes: None,
                    link: Some(RichTextLink {
                        href: "javascript:alert(1)".to_owned(),
                        new_tab: false,
                    }),
                }],
            }],
        };
        let error = apply_operations(
            &mut doc,
            &[WebOperation::SetRichText {
                page_id: page_id(),
                id: NodeId::from("headline"),
                content: unsafe_content,
            }],
        )
        .unwrap_err();
        assert_eq!(error.code, "op.rich_text_invalid");
        assert_eq!(doc, base, "rejected rich-text op must not mutate");
    }

    #[test]
    fn structured_rich_text_is_allowed_for_body_and_rejected_for_headings() {
        let structured = RichTextDocument {
            schema_version: RICH_TEXT_SCHEMA_VERSION,
            blocks: vec![
                RichTextBlock::Paragraph {
                    alignment: None,
                    children: vec![RichTextInline::Text {
                        text: "Intro".to_owned(),
                        marks: RichTextMarks::default(),
                        classes: None,
                        link: None,
                    }],
                },
                RichTextBlock::List {
                    list_type: RichTextListType::Ordered,
                    items: vec![RichTextListItem {
                        children: vec![RichTextInline::Text {
                            text: "First".to_owned(),
                            marks: RichTextMarks {
                                bold: true,
                                ..RichTextMarks::default()
                            },
                            classes: None,
                            link: None,
                        }],
                        nested: Vec::new(),
                    }],
                },
            ],
        };
        let mut doc = fixture();
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::SetRichText {
                page_id: page_id(),
                id: NodeId::from("sub"),
                content: structured.clone(),
            }],
        )
        .expect("body accepts structured content");
        let WebNodeKind::Text { content, .. } =
            &doc.page(&page_id()).unwrap().node(&NodeId::from("sub")).unwrap().kind
        else {
            panic!("text node");
        };
        assert_eq!(content, &structured);
        apply_operations(&mut doc, &inverses).expect("undo structured edit");
        assert_eq!(doc, fixture());

        let before = doc.clone();
        let error = apply_operations(
            &mut doc,
            &[WebOperation::SetRichText {
                page_id: page_id(),
                id: NodeId::from("headline"),
                content: structured,
            }],
        )
        .unwrap_err();
        assert_eq!(error.code, "op.rich_text_variant_invalid");
        assert_eq!(doc, before);
    }

    #[test]
    fn set_slot_key_round_trips_and_validates() {
        let base = fixture();

        // Set then clear; each direction's inverse restores exactly.
        let mut doc = base.clone();
        let set = WebOperation::SetSlotKey {
            page_id: page_id(),
            id: NodeId::from("headline"),
            slot_key: Some(SlotKey::from("account.name")),
        };
        let inverses = apply_operations(&mut doc, std::slice::from_ref(&set)).expect("set");
        let node = doc
            .page(&page_id())
            .unwrap()
            .node(&NodeId::from("headline"))
            .unwrap();
        assert_eq!(
            node.slot_key.as_ref().map(|k| k.as_str()),
            Some("account.name")
        );
        apply_operations(&mut doc, &inverses).expect("inverse");
        assert_eq!(doc, base, "inverse clears the slot key");

        // A when:-prefixed key is accepted by canonicalization.
        let mut doc = base.clone();
        apply_operations(
            &mut doc,
            &[WebOperation::SetSlotKey {
                page_id: page_id(),
                id: NodeId::from("stack"),
                slot_key: Some(SlotKey::from("when:account.testimonial")),
            }],
        )
        .expect("when-prefixed key accepted");

        // Off-charset and uppercase keys are rejected on the write path
        // (one strict grammar: [a-z0-9_.-], lowercase only).
        for bad in ["bad key!", "Account.Name"] {
            let mut doc = base.clone();
            let result = apply_operations(
                &mut doc,
                &[WebOperation::SetSlotKey {
                    page_id: page_id(),
                    id: NodeId::from("headline"),
                    slot_key: Some(SlotKey::from(bad)),
                }],
            );
            assert_eq!(result.unwrap_err().code, "op.slot_key_invalid", "{bad}");
            assert_eq!(doc, base, "rejected op must not mutate");
        }
    }

    #[test]
    fn kind_change_via_props_is_rejected() {
        let mut doc = fixture();
        let result = apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("headline"),
                props: WebNodeKind::Container {
                    href: None,
                    new_tab: false,
                    background: None,
                },
            }],
        );
        assert_eq!(result.unwrap_err().code, "op.kind_mismatch");
    }

    #[test]
    fn insert_node_sanitizes_content_and_checks_subtree() {
        let mut doc = fixture();
        // Unsanitized content is canonicalized on the way in.
        let dirty = WebNode {
            id: NodeId::from("dirty"),
            kind: WebNodeKind::Text {
                variant: TextVariant::Body,
                content: "<script>alert(1)</script>Safe <strong>copy</strong>"
                    .to_owned()
                    .into(),
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![dirty],
                root: NodeId::from("dirty"),
            }],
        )
        .expect("apply");
        let page = doc.page(&page_id()).unwrap();
        let WebNodeKind::Text { content, .. } = &page.node(&NodeId::from("dirty")).unwrap().kind
        else {
            panic!("text node");
        };
        assert_eq!(content, "Safe <strong>copy</strong>");

        // A child reference outside the subtree is rejected.
        let mut orphaning = WebNode::branch(
            NodeId::from("bad_box"),
            WebNodeKind::Container {
                href: None,
                new_tab: false,
                background: None,
            },
            "",
        );
        orphaning.children = vec![NodeId::from("headline")];
        let result = apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![orphaning],
                root: NodeId::from("bad_box"),
            }],
        );
        assert_eq!(result.unwrap_err().code, "op.subtree_invalid");
    }

    #[test]
    fn set_node_props_sanitizes_and_rejects_bad_href() {
        let mut doc = fixture();
        apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("headline"),
                props: WebNodeKind::Text {
                    variant: TextVariant::H1,
                    content: "Hi <div onclick=\"x()\">there</div>".to_owned().into(),
                },
            }],
        )
        .expect("apply");
        let page = doc.page(&page_id()).unwrap();
        let WebNodeKind::Text { content, .. } = &page.node(&NodeId::from("headline")).unwrap().kind
        else {
            panic!("text node");
        };
        assert_eq!(content, "Hi there");

        let button = WebNode {
            id: NodeId::from("cta"),
            kind: WebNodeKind::Button {
                label: "Go".to_owned(),
                variant: crate::doc::ButtonVariant::Primary,
                action: ButtonAction::Href {
                    href: "https://example.com".to_owned(),
                    new_tab: false,
                },
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![button],
                root: NodeId::from("cta"),
            }],
        )
        .expect("insert button");
        let result = apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("cta"),
                props: WebNodeKind::Button {
                    label: "Go".to_owned(),
                    variant: crate::doc::ButtonVariant::Primary,
                    action: ButtonAction::Href {
                        href: "javascript:alert(1)".to_owned(),
                        new_tab: false,
                    },
                },
            }],
        );
        assert_eq!(result.unwrap_err().code, "op.href_invalid");
    }

    #[test]
    fn clickable_container_and_background_props_are_checked_and_invertible() {
        let base = fixture();
        let mut doc = base.clone();
        let (link_inverse, _) = apply_operations_checked(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("stack"),
                props: WebNodeKind::Container {
                    href: Some("  /story  ".to_owned()),
                    new_tab: true,
                    background: None,
                },
            }],
        )
        .expect("set clickable container");
        let WebNodeKind::Container { href, new_tab, .. } = &doc
            .page(&page_id())
            .unwrap()
            .node(&NodeId::from("stack"))
            .unwrap()
            .kind
        else {
            panic!("container");
        };
        assert_eq!(href.as_deref(), Some("/story"));
        assert!(*new_tab);
        apply_operations_checked(&mut doc, &link_inverse).expect("undo link");
        assert_eq!(doc, base);

        let record: AssetRecord = serde_json::from_value(serde_json::json!({
            "id": "hero_photo",
            "label": "Hero photo",
            "kind": "raster_image",
            "status": "ready",
            "source": {"kind": "generated", "model": "test", "request_id": null},
            "media": {
                "mime_type": "image/webp",
                "digest": {"algorithm": "sha256", "value": "abc123"},
                "location": null,
                "filename": null,
                "byte_length": null
            }
        }))
        .expect("asset");
        apply_operations_checked(
            &mut doc,
            &[
                WebOperation::UpsertAsset {
                    record: record.clone(),
                },
                WebOperation::SetNodeProps {
                    page_id: page_id(),
                    id: NodeId::from("hero"),
                    props: WebNodeKind::Section {
                        tag: SectionTag::Section,
                        anchor_id: Some("hero".to_owned()),
                        background: Some(WebBackgroundImage {
                            asset_id: record.id.clone(),
                            fit: WebBackgroundFit::Cover,
                            position: WebBackgroundPosition::Center,
                            scrim: Some(WebBackgroundScrim {
                                color: WebScrimColor::Dark,
                                opacity: 55,
                            }),
                        }),
                    },
                },
            ],
        )
        .expect("set background");
        let error = apply_operations(
            &mut doc,
            &[WebOperation::RemoveAsset {
                asset_id: record.id,
            }],
        )
        .unwrap_err();
        assert_eq!(error.code, "op.asset_in_use");
    }

    #[test]
    fn href_to_command_rewire_and_inverse_restores() {
        // A Href→Command rewire (and back) is legal: SetNodeProps checks
        // kind_name only, and both actions live on the same Button kind.
        let mut doc = fixture();
        let cta = WebNode {
            id: NodeId::from("cta"),
            kind: WebNodeKind::Button {
                label: "Book".to_owned(),
                variant: crate::doc::ButtonVariant::Primary,
                action: ButtonAction::Href {
                    href: "https://example.com".to_owned(),
                    new_tab: false,
                },
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![cta],
                root: NodeId::from("cta"),
            }],
        )
        .expect("insert button");
        let before = doc.clone();
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("cta"),
                props: WebNodeKind::Button {
                    label: "Book".to_owned(),
                    variant: crate::doc::ButtonVariant::Primary,
                    action: ButtonAction::Command {
                        command: crate::doc::ButtonCommand::ShowModal,
                        command_target: NodeId::from("dlg_1"),
                    },
                },
            }],
        )
        .expect("rewire to command");
        let WebNodeKind::Button { action, .. } = &doc
            .page(&page_id())
            .unwrap()
            .node(&NodeId::from("cta"))
            .unwrap()
            .kind
        else {
            panic!("button node");
        };
        assert!(matches!(action, ButtonAction::Command { .. }));
        apply_operations(&mut doc, &inverses).expect("inverse");
        assert_eq!(doc, before, "inverse restores the Href action exactly");
    }

    #[test]
    fn command_button_inserts_cleanly() {
        let mut doc = fixture();
        let cta = WebNode {
            id: NodeId::from("trigger"),
            kind: WebNodeKind::Button {
                label: "Open".to_owned(),
                variant: crate::doc::ButtonVariant::Primary,
                action: ButtonAction::Command {
                    command: crate::doc::ButtonCommand::ShowModal,
                    command_target: NodeId::from("dlg_1"),
                },
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        apply_operations(
            &mut doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![cta],
                root: NodeId::from("trigger"),
            }],
        )
        .expect("insert command button");
        assert!(doc
            .page(&page_id())
            .unwrap()
            .node(&NodeId::from("trigger"))
            .is_some());
    }

    #[test]
    fn checked_apply_rejects_structurally_invalid_result() {
        let base = fixture();
        // A Text node directly under the page root violates the
        // sections-only invariant (LUMW0011): plain apply allows it,
        // checked apply must reject and leave the doc untouched.
        let stray = WebNode {
            id: NodeId::from("stray"),
            kind: WebNodeKind::Text {
                variant: TextVariant::Body,
                content: "x".to_owned().into(),
            },
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        };
        let batch = [WebOperation::InsertNode {
            page_id: page_id(),
            parent: NodeId::from("root"),
            index: 0,
            nodes: vec![stray],
            root: NodeId::from("stray"),
        }];
        let mut doc = base.clone();
        assert!(apply_operations(&mut doc, &batch).is_ok());

        let mut doc = base.clone();
        let error = apply_operations_checked(&mut doc, &batch).unwrap_err();
        assert_eq!(error.code, "op.validation_failed");
        assert!(error
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0011"));
        assert_eq!(doc, base, "rejected batch must not mutate");
    }

    fn embed_node(id: &str, kind: WebNodeKind) -> WebNode {
        WebNode {
            id: NodeId::from(id),
            kind,
            classes: String::new(),
            children: Vec::new(),
            name: None,
            slot_key: None,
        }
    }

    fn insert_embed(doc: &mut WebDoc, node: WebNode) -> Result<Vec<WebOperation>, WebOpError> {
        let id = node.id.clone();
        apply_operations(
            doc,
            &[WebOperation::InsertNode {
                page_id: page_id(),
                parent: NodeId::from("stack"),
                index: 0,
                nodes: vec![node],
                root: id,
            }],
        )
    }

    #[test]
    fn embed_op_canonicalization() {
        use crate::doc::EmbedProvider;

        // Calendly with a bad url is rejected.
        let mut doc = fixture();
        let result = insert_embed(
            &mut doc,
            embed_node(
                "emb_bad",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Calendly,
                    url: Some("https://evil.com/x".to_owned()),
                    html: String::new(),
                },
            ),
        );
        assert_eq!(result.unwrap_err().code, "op.embed_url_invalid");

        // Custom with any https url is accepted (permissive human path).
        let mut doc = fixture();
        insert_embed(
            &mut doc,
            embed_node(
                "emb_url",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Custom,
                    url: Some("https://widget.example/embed".to_owned()),
                    html: String::new(),
                },
            ),
        )
        .expect("custom https url accepted");

        // Custom with a calendly.com url is PROMOTED to the Calendly provider
        // (ops payloads routinely omit `provider`; the allowlist semantics
        // must hold on every write path — proven by a live agent turn that
        // stored a calendly link as custom).
        let mut doc = fixture();
        insert_embed(
            &mut doc,
            embed_node(
                "emb_promoted",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Custom,
                    url: Some("https://calendly.com/acme/demo".to_owned()),
                    html: String::new(),
                },
            ),
        )
        .expect("calendly url accepted");
        let page = doc.page(&page_id()).unwrap();
        let WebNodeKind::Embed { provider, .. } =
            &page.node(&NodeId::from("emb_promoted")).unwrap().kind
        else {
            panic!("embed node");
        };
        assert_eq!(*provider, EmbedProvider::Calendly);

        // Custom non-https url is rejected.
        let mut doc = fixture();
        let result = insert_embed(
            &mut doc,
            embed_node(
                "emb_http",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Custom,
                    url: Some("http://widget.example/embed".to_owned()),
                    html: String::new(),
                },
            ),
        );
        assert_eq!(result.unwrap_err().code, "op.embed_url_invalid");

        // Custom snippet (html, no url) is accepted and NOT sanitized.
        let mut doc = fixture();
        insert_embed(
            &mut doc,
            embed_node(
                "emb_snip",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Custom,
                    url: None,
                    html: "<script>widget()</script>".to_owned(),
                },
            ),
        )
        .expect("custom snippet accepted");
        let page = doc.page(&page_id()).unwrap();
        let WebNodeKind::Embed { html, .. } = &page.node(&NodeId::from("emb_snip")).unwrap().kind
        else {
            panic!("embed");
        };
        assert_eq!(html, "<script>widget()</script>", "html is not sanitized");
    }

    #[test]
    fn legacy_embed_props_round_trip_through_ops() {
        use crate::doc::EmbedProvider;
        let mut doc = fixture();
        insert_embed(
            &mut doc,
            embed_node(
                "emb_1",
                WebNodeKind::Embed {
                    provider: EmbedProvider::Calendly,
                    url: Some("https://calendly.com/team".to_owned()),
                    html: String::new(),
                },
            ),
        )
        .expect("insert");
        let before = doc.clone();
        // SetNodeProps to a new valid calendly url, then invert.
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::SetNodeProps {
                page_id: page_id(),
                id: NodeId::from("emb_1"),
                props: WebNodeKind::Embed {
                    provider: EmbedProvider::Calendly,
                    url: Some("https://acme.calendly.com/demo".to_owned()),
                    html: String::new(),
                },
            }],
        )
        .expect("set props");
        apply_operations(&mut doc, &inverses).expect("undo");
        assert_eq!(doc, before, "inverse restores the embed props exactly");
    }

    #[test]
    fn ops_round_trip_through_json() {
        let operation = WebOperation::MoveNode {
            page_id: page_id(),
            id: NodeId::from("a"),
            new_parent: NodeId::from("b"),
            index: 3,
        };
        let json = serde_json::to_value(&operation).expect("serialize");
        assert_eq!(json["kind"], "move_node");
        let back: WebOperation = serde_json::from_value(json).expect("deserialize");
        assert_eq!(back, operation);
    }

    fn empty_page(id: &str, route: &str) -> crate::doc::WebPage {
        let root_id = NodeId::from(format!("root_{id}"));
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
        crate::doc::WebPage {
            id: PageId::from(id),
            name: id.to_owned(),
            route: route.to_owned(),
            root: root_id,
            nodes,
        }
    }

    #[test]
    fn add_page_then_inverse_restores_the_document() {
        let mut doc = fixture();
        let before = doc.clone();
        let inverses = apply_operations_checked(
            &mut doc,
            &[WebOperation::AddPage {
                page: empty_page("pricing", "/pricing"),
                index: None,
            }],
        )
        .expect("add page")
        .0;
        assert_eq!(doc.pages.len(), 2);
        assert_eq!(doc.pages[1].route, "/pricing");
        assert!(matches!(inverses[0], WebOperation::RemovePage { .. }));
        apply_operations(&mut doc, &inverses).expect("inverse applies");
        assert_eq!(doc, before);
    }

    #[test]
    fn remove_page_inverse_reinserts_at_the_same_index() {
        let mut doc = fixture();
        apply_operations(
            &mut doc,
            &[WebOperation::AddPage {
                page: empty_page("a", "/a"),
                index: Some(0),
            }],
        )
        .unwrap();
        let before = doc.clone();
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::RemovePage {
                page_id: PageId::from("a"),
            }],
        )
        .unwrap();
        assert_eq!(doc.pages.len(), 1);
        apply_operations(&mut doc, &inverses).unwrap();
        assert_eq!(doc, before);
        assert_eq!(doc.pages[0].id, PageId::from("a"));
    }

    #[test]
    fn add_page_refuses_duplicates_and_bad_routes() {
        let mut doc = fixture();
        let dup_id = apply_operations(
            &mut doc,
            &[WebOperation::AddPage {
                page: empty_page("home", "/x"),
                index: None,
            }],
        );
        assert_eq!(dup_id.unwrap_err().code, "op.page_exists");
        let dup_route = apply_operations(
            &mut doc,
            &[WebOperation::AddPage {
                page: empty_page("x", "/"),
                index: None,
            }],
        );
        assert_eq!(dup_route.unwrap_err().code, "op.route_exists");
        let bad_route = apply_operations(
            &mut doc,
            &[WebOperation::AddPage {
                page: empty_page("x", "/Bad"),
                index: None,
            }],
        );
        assert_eq!(bad_route.unwrap_err().code, "op.route_invalid");
        assert_eq!(
            doc.pages.len(),
            1,
            "a refused batch leaves the document untouched"
        );
    }

    #[test]
    fn the_last_page_cannot_be_removed() {
        let mut doc = fixture();
        let err = apply_operations(
            &mut doc,
            &[WebOperation::RemovePage {
                page_id: page_id(),
            }],
        )
        .unwrap_err();
        assert_eq!(err.code, "op.cannot_remove_last_page");
    }

    #[test]
    fn set_page_meta_refuses_an_invalid_route() {
        let mut doc = fixture();
        let err = apply_operations(
            &mut doc,
            &[WebOperation::SetPageMeta {
                page_id: page_id(),
                name: None,
                route: Some("/Bad Route".into()),
            }],
        )
        .unwrap_err();
        assert_eq!(err.code, "op.route_invalid");
    }
}
