//! Template derivation: one web document → one account-personalized copy.
//!
//! This mirrors the scene-side `derive_instance` stack (BindingSet + slot
//! substitution), simplified for the web medium: no finalize-revision
//! immutability and no required-slot hard gates — provenance is carried by the
//! surviving markers and a coverage report, and unbound keys fall back to the
//! template's own content. The function is pure (doc → doc, no I/O) and
//! deterministic: identical inputs serialize byte-for-byte.
//!
//! Two marker families drive substitution, both authored on the ingestion
//! seam (`ingest`) and preserved through derivation so a derived doc can itself
//! be re-derived:
//! - inline `<span data-var="key">fallback</span>` inside Text/Button content;
//! - node `slot_key` (from `data-slot`) plus the `when:`-prefixed presence gate
//!   (from `data-slot-when`).
//!
//! Diagnostics namespace: `LUMW06xx`.

use crate::doc::{WebDoc, WebNode, WebNodeKind, WebPage};
use crate::inline::sanitize_inline;
use crate::util::escape_text;
use crate::validate::validate_web_doc;
use lumen_core::{
    AssetId, AssetRecord, Diagnostic, DiagnosticSeverity, DiagnosticSubject, NodeId, Phase, SlotKey,
};
use quick_xml::events::Event;
use quick_xml::Reader;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// Slot-key prefix marking a presence gate (from `data-slot-when`): the node
/// (and its subtree) survives derivation only when the referenced value is
/// present. The colon is intentionally outside the `SlotKey` charset, so a
/// prefixed key can only ever be minted internally (never charset-validated
/// as-is).
pub const WHEN_PREFIX: &str = "when:";

/// Repeater expansion cap; excess list items are dropped with a warning
/// (LUMW0604), mirroring the scene runtime's bounded reflow.
pub const MAX_REPEATER_ITEMS: usize = 12;

/// Maximum personalization key length (data-var, data-slot, data-slot-when).
pub const MAX_KEY_LEN: usize = 64;

/// The ONE key grammar for every personalization marker: `[a-z0-9_.-]+`,
/// ≤64 chars. Deliberately stricter than `lumen_core::SlotKey` (lowercase
/// only): the skills and the editor's client-side validation teach exactly
/// this charset, so no write path may mint a key the inspector refuses.
pub fn personalization_key_is_valid(key: &str) -> bool {
    !key.is_empty()
        && key.len() <= MAX_KEY_LEN
        && key
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'_' | b'-' | b'.'))
}

/// One bound value for a web derivation. Mirrors
/// `lumen_core::binding::BoundValue`, kind-tagged snake_case.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum WebBoundValue {
    Text {
        value: String,
    },
    Asset {
        asset_id: AssetId,
        /// Replacement alt text for the bound image. Alt is CONTENT: without
        /// this, a derived page keeps the template's alt (e.g. the seed
        /// account's name) — an a11y/social leak the e2e caught live.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alt: Option<String>,
    },
    List {
        items: Vec<WebBoundValue>,
    },
}

impl WebBoundValue {
    pub fn kind_name(&self) -> &'static str {
        match self {
            Self::Text { .. } => "text",
            Self::Asset { .. } => "asset",
            Self::List { .. } => "list",
        }
    }

    /// Presence semantics for `when:` gates: text must be non-blank, lists
    /// non-empty; assets are present by construction.
    pub fn is_present(&self) -> bool {
        match self {
            Self::Text { value } => !value.trim().is_empty(),
            Self::Asset { .. } => true,
            Self::List { items } => !items.is_empty(),
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct DeriveWebOptions {
    pub new_doc_id: String,
    pub new_title: Option<String>,
}

/// One key that was referenced by a marker but left to its fallback, plus the
/// nodes that carried it.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct UnboundEntry {
    pub key: String,
    pub node_ids: Vec<String>,
}

/// What the derivation touched, for the batch manifest and honesty checks.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct WebDeriveCoverage {
    /// Keys applied to at least one carrier (or that kept a `when:` node).
    pub bound: Vec<String>,
    /// Unbound `data-slot` carriers, grouped by key.
    pub unbound_slots: Vec<UnboundEntry>,
    /// Unbound `data-var` spans, grouped by key.
    pub unbound_vars: Vec<UnboundEntry>,
    /// Provided values referenced by no marker anywhere.
    pub unused_values: Vec<String>,
    /// Carriers dropped by an absent `when:` gate.
    pub removed_node_ids: Vec<String>,
}

pub struct DerivedWebDoc {
    pub doc: WebDoc,
    pub diagnostics: Vec<Diagnostic>,
    pub coverage: WebDeriveCoverage,
}

impl DerivedWebDoc {
    /// True when derivation (or the final validation) produced an error-level
    /// diagnostic; the caller must reject the result (the template is a `&`
    /// ref and is never mutated, so rejection is inherently atomic).
    pub fn has_errors(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    }
}

/// True when `sk` is a legal web slot key: the strict personalization key
/// grammar, tolerating a single leading `when:` presence-gate prefix.
pub fn web_slot_key_is_valid(sk: &SlotKey) -> bool {
    let raw = sk.as_str();
    let key = raw.strip_prefix(WHEN_PREFIX).unwrap_or(raw);
    personalization_key_is_valid(key)
}

/// The unprefixed key of a `when:`-gated slot key, or `None` for plain keys.
pub fn when_gate_key(sk: &SlotKey) -> Option<&str> {
    sk.as_str().strip_prefix(WHEN_PREFIX)
}

/// Derive one personalized copy of `template` from `values`. See module docs
/// for the substitution contract.
pub fn derive_web_doc(
    template: &WebDoc,
    values: &BTreeMap<String, WebBoundValue>,
    assets: &[AssetRecord],
    opts: &DeriveWebOptions,
) -> DerivedWebDoc {
    let mut doc = template.clone();
    doc.id = opts.new_doc_id.clone();
    if let Some(title) = &opts.new_title {
        doc.title = title.clone();
    }

    let provided: BTreeMap<&AssetId, &AssetRecord> =
        assets.iter().map(|record| (&record.id, record)).collect();
    let existing_asset_ids: BTreeSet<AssetId> = doc.assets.keys().cloned().collect();

    let mut ctx = Ctx::default();
    let mut diagnostics = Vec::new();
    let mut upserts: BTreeMap<AssetId, AssetRecord> = BTreeMap::new();

    // A values key that no marker could ever reference (bad charset) is called
    // out once so its later appearance in `unused_values` has a reason.
    for key in values.keys() {
        if !personalization_key_is_valid(key) {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Web,
                    "LUMW0601",
                    format!("value key `{key}` is not a valid slot key and can bind nothing"),
                    None,
                )
                .with_hint("Keys are lowercase [a-z0-9_.-], max 64 chars (e.g. account.name)."),
            );
        }
    }

    for page in doc.pages.iter_mut() {
        apply_when_gates(page, values, &mut ctx);
        apply_slots(
            page,
            values,
            &provided,
            &existing_asset_ids,
            &mut upserts,
            &mut ctx,
            &mut diagnostics,
        );
        apply_data_vars(page, values, &mut ctx, &mut diagnostics);
    }

    for (id, record) in upserts {
        doc.assets.insert(id, record);
    }

    let coverage = ctx.into_coverage(values);
    // Atomic gate: derivation runs the full structural validation and any
    // error-level result rejects the derive (mirrors the checked apply). The
    // template is a `&` ref, so it is untouched regardless.
    diagnostics.extend(validate_web_doc(&doc));

    DerivedWebDoc {
        doc,
        diagnostics,
        coverage,
    }
}

/// Coverage accumulator; every collection is ordered so the report — and thus
/// the whole derived doc — is deterministic.
#[derive(Default)]
struct Ctx {
    bound: BTreeSet<String>,
    referenced: BTreeSet<String>,
    unbound_slots: BTreeMap<String, BTreeSet<String>>,
    unbound_vars: BTreeMap<String, BTreeSet<String>>,
    removed: BTreeSet<String>,
}

impl Ctx {
    fn reference(&mut self, key: &str) {
        self.referenced.insert(key.to_owned());
    }

    fn bind(&mut self, key: &str) {
        self.referenced.insert(key.to_owned());
        self.bound.insert(key.to_owned());
    }

    fn unbound_slot(&mut self, key: &str, node: &NodeId) {
        self.referenced.insert(key.to_owned());
        self.unbound_slots
            .entry(key.to_owned())
            .or_default()
            .insert(node.as_str().to_owned());
    }

    fn unbound_var(&mut self, key: &str, node: &NodeId) {
        self.referenced.insert(key.to_owned());
        self.unbound_vars
            .entry(key.to_owned())
            .or_default()
            .insert(node.as_str().to_owned());
    }

    fn removed(&mut self, node: &NodeId) {
        self.removed.insert(node.as_str().to_owned());
    }

    fn into_coverage(self, values: &BTreeMap<String, WebBoundValue>) -> WebDeriveCoverage {
        let unused_values = values
            .keys()
            .filter(|key| !self.referenced.contains(*key))
            .cloned()
            .collect();
        let entries = |map: BTreeMap<String, BTreeSet<String>>| {
            map.into_iter()
                .map(|(key, node_ids)| UnboundEntry {
                    key,
                    node_ids: node_ids.into_iter().collect(),
                })
                .collect()
        };
        WebDeriveCoverage {
            bound: self.bound.into_iter().collect(),
            unbound_slots: entries(self.unbound_slots),
            unbound_vars: entries(self.unbound_vars),
            unused_values,
            removed_node_ids: self.removed.into_iter().collect(),
        }
    }
}

/// Pass 1: drop every `when:`-gated carrier (with its subtree) whose gate value
/// is absent. Gates inside an already-dropped subtree are not re-evaluated.
fn apply_when_gates(page: &mut WebPage, values: &BTreeMap<String, WebBoundValue>, ctx: &mut Ctx) {
    let mut to_remove: BTreeSet<NodeId> = BTreeSet::new();
    let mut stack = vec![page.root.clone()];
    while let Some(id) = stack.pop() {
        let Some(node) = page.nodes.get(&id) else {
            continue;
        };
        if let Some(key) = node.slot_key.as_ref().and_then(when_gate_key) {
            ctx.reference(key);
            let present = values.get(key).is_some_and(WebBoundValue::is_present);
            if !present {
                collect_subtree(page, &id, &mut to_remove);
                ctx.removed(&id);
                continue; // subtree goes with it; do not descend
            }
            ctx.bind(key);
        }
        if let Some(node) = page.nodes.get(&id) {
            for child in node.children.iter().rev() {
                stack.push(child.clone());
            }
        }
    }
    if to_remove.is_empty() {
        return;
    }
    for id in &to_remove {
        page.nodes.remove(id);
    }
    for node in page.nodes.values_mut() {
        node.children.retain(|child| !to_remove.contains(child));
    }
}

/// Pass 2: apply unprefixed `data-slot` carriers per node kind.
#[allow(clippy::too_many_arguments)]
fn apply_slots(
    page: &mut WebPage,
    values: &BTreeMap<String, WebBoundValue>,
    provided: &BTreeMap<&AssetId, &AssetRecord>,
    existing_asset_ids: &BTreeSet<AssetId>,
    upserts: &mut BTreeMap<AssetId, AssetRecord>,
    ctx: &mut Ctx,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let targets: Vec<(NodeId, String)> = page
        .nodes
        .iter()
        .filter_map(|(id, node)| {
            node.slot_key.as_ref().and_then(|sk| {
                if sk.as_str().starts_with(WHEN_PREFIX) {
                    None
                } else {
                    Some((id.clone(), sk.as_str().to_owned()))
                }
            })
        })
        .collect();

    for (id, key) in targets {
        if !page.nodes.contains_key(&id) {
            continue; // consumed by a repeater expansion above
        }
        ctx.reference(&key);
        let Some(value) = values.get(&key) else {
            ctx.unbound_slot(&key, &id);
            continue;
        };
        let kind_name = page.nodes.get(&id).map(|node| node.kind.kind_name());
        match (kind_name, value) {
            (Some("text"), WebBoundValue::Text { value }) => {
                if let Some(WebNodeKind::Text { content, .. }) =
                    page.nodes.get_mut(&id).map(|node| &mut node.kind)
                {
                    *content = sanitize_inline(&escape_text(value)).html.into();
                }
                ctx.bind(&key);
            }
            (Some("image"), WebBoundValue::Asset { asset_id, alt }) => {
                ensure_asset(
                    asset_id,
                    provided,
                    existing_asset_ids,
                    upserts,
                    &id,
                    diagnostics,
                );
                if let Some(WebNodeKind::Image {
                    asset_id: existing,
                    alt: existing_alt,
                    ..
                }) = page.nodes.get_mut(&id).map(|node| &mut node.kind)
                {
                    *existing = asset_id.clone();
                    if let Some(alt) = alt {
                        *existing_alt = alt.clone();
                    }
                }
                ctx.bind(&key);
            }
            (Some("container"), WebBoundValue::List { items }) => {
                expand_repeater(
                    page,
                    &id,
                    &key,
                    items,
                    provided,
                    existing_asset_ids,
                    upserts,
                    ctx,
                    diagnostics,
                );
            }
            (Some(actual), _) => {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Web,
                        "LUMW0602",
                        format!(
                            "slot `{key}` on {actual} node `{id}` expects a matching value; \
                             binding provides a {} value (node left as authored)",
                            value.kind_name()
                        ),
                        Some(DiagnosticSubject::Node(id.clone())),
                    )
                    .with_hint(
                        "Text carriers take text, images take assets, containers take lists.",
                    ),
                );
            }
            (None, _) => {}
        }
    }
}

/// Container repeater: clone the container's first child once per list item.
#[allow(clippy::too_many_arguments)]
fn expand_repeater(
    page: &mut WebPage,
    container_id: &NodeId,
    key: &str,
    items: &[WebBoundValue],
    provided: &BTreeMap<&AssetId, &AssetRecord>,
    existing_asset_ids: &BTreeSet<AssetId>,
    upserts: &mut BTreeMap<AssetId, AssetRecord>,
    ctx: &mut Ctx,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let original_children = page
        .nodes
        .get(container_id)
        .map(|node| node.children.clone())
        .unwrap_or_default();
    let Some(proto_id) = original_children.first().cloned() else {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Web,
                "LUMW0603",
                format!("repeater `{container_id}` has no prototype child to clone"),
                Some(DiagnosticSubject::Node(container_id.clone())),
            )
            .with_hint("A list container needs one child to serve as the repeated item template."),
        );
        return;
    };

    let proto_subtree = subtree_preorder(page, &proto_id);
    let first_text = proto_subtree
        .iter()
        .find(|id| matches!(page.nodes.get(*id).map(|n| &n.kind), Some(WebNodeKind::Text { .. })))
        .cloned();
    let first_image = proto_subtree
        .iter()
        .find(|id| matches!(page.nodes.get(*id).map(|n| &n.kind), Some(WebNodeKind::Image { .. })))
        .cloned();

    let effective = if items.len() > MAX_REPEATER_ITEMS {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Web,
                "LUMW0604",
                format!(
                    "repeater `{container_id}` received {} items; only the first {MAX_REPEATER_ITEMS} are rendered",
                    items.len()
                ),
                Some(DiagnosticSubject::Node(container_id.clone())),
            )
            .with_hint("Trim the list or split it across sections."),
        );
        &items[..MAX_REPEATER_ITEMS]
    } else {
        items
    };

    let mut new_children = Vec::with_capacity(effective.len());
    let mut new_nodes: Vec<WebNode> = Vec::new();
    for (index, item) in effective.iter().enumerate() {
        for orig_id in &proto_subtree {
            let mut cloned = page.nodes.get(orig_id).expect("proto node").clone();
            cloned.id = suffix_id(orig_id, index);
            cloned.children = cloned
                .children
                .iter()
                .map(|child| suffix_id(child, index))
                .collect();
            new_nodes.push(cloned);
        }
        match item {
            WebBoundValue::Text { value } => match &first_text {
                Some(target) => {
                    let cloned_id = suffix_id(target, index);
                    if let Some(WebNodeKind::Text { content, .. }) = new_nodes
                        .iter_mut()
                        .find(|node| node.id == cloned_id)
                        .map(|node| &mut node.kind)
                    {
                        *content = sanitize_inline(&escape_text(value)).html.into();
                    }
                }
                None => diagnostics.push(unusable_prototype(
                    container_id,
                    "text items but the prototype has no text node",
                )),
            },
            WebBoundValue::Asset { asset_id, alt } => match &first_image {
                Some(target) => {
                    ensure_asset(
                        asset_id,
                        provided,
                        existing_asset_ids,
                        upserts,
                        container_id,
                        diagnostics,
                    );
                    let cloned_id = suffix_id(target, index);
                    if let Some(WebNodeKind::Image {
                        asset_id: existing,
                        alt: existing_alt,
                        ..
                    }) = new_nodes
                        .iter_mut()
                        .find(|node| node.id == cloned_id)
                        .map(|node| &mut node.kind)
                    {
                        *existing = asset_id.clone();
                        if let Some(alt) = alt {
                            *existing_alt = alt.clone();
                        }
                    }
                }
                None => diagnostics.push(unusable_prototype(
                    container_id,
                    "asset items but the prototype has no image node",
                )),
            },
            WebBoundValue::List { .. } => diagnostics.push(
                Diagnostic::warning(
                    Phase::Web,
                    "LUMW0602",
                    format!("repeater `{container_id}` list item is itself a list; nested repeaters are not supported"),
                    Some(DiagnosticSubject::Node(container_id.clone())),
                )
                .with_hint("Repeater items are text or asset values."),
            ),
        }
        new_children.push(suffix_id(&proto_id, index));
    }

    // Replace the container's whole child set with the clones; the originals
    // (prototype included) leave the arena.
    let mut removed: BTreeSet<NodeId> = BTreeSet::new();
    for child in &original_children {
        collect_subtree(page, child, &mut removed);
    }
    for id in removed {
        page.nodes.remove(&id);
    }
    for node in new_nodes {
        page.nodes.insert(node.id.clone(), node);
    }
    if let Some(container) = page.nodes.get_mut(container_id) {
        container.children = new_children;
    }
    ctx.bind(key);
}

fn unusable_prototype(container_id: &NodeId, detail: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Web,
        "LUMW0603",
        format!("repeater `{container_id}` has {detail}"),
        Some(DiagnosticSubject::Node(container_id.clone())),
    )
    .with_hint("The prototype must contain the node kind each item sets (a text or image node).")
}

/// Ensure the asset backing an Asset value is available in the derived doc,
/// upserting the provided record when needed. Missing → LUMW0605 (error).
fn ensure_asset(
    asset_id: &AssetId,
    provided: &BTreeMap<&AssetId, &AssetRecord>,
    existing_asset_ids: &BTreeSet<AssetId>,
    upserts: &mut BTreeMap<AssetId, AssetRecord>,
    subject: &NodeId,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if existing_asset_ids.contains(asset_id) || upserts.contains_key(asset_id) {
        return;
    }
    if let Some(record) = provided.get(asset_id) {
        upserts.insert(asset_id.clone(), (*record).clone());
        return;
    }
    diagnostics.push(
        Diagnostic::error(
            Phase::Web,
            "LUMW0605",
            format!("asset `{asset_id}` bound to `{subject}` has no record in the derive input"),
            Some(DiagnosticSubject::Node(subject.clone())),
        )
        .with_hint("Pass the asset's record alongside the value (the account's logo projection)."),
    );
}

/// Pass 3: substitute `data-var` spans in every Text/Button field.
fn apply_data_vars(
    page: &mut WebPage,
    values: &BTreeMap<String, WebBoundValue>,
    ctx: &mut Ctx,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let ids: Vec<NodeId> = page.nodes.keys().cloned().collect();
    for id in ids {
        let Some(node) = page.nodes.get_mut(&id) else {
            continue;
        };
        match &mut node.kind {
            WebNodeKind::Text { content, .. } if content.contains_variable() => {
                content.for_each_variable_mut(|key, fallback| {
                    if let VarAction::Substitute(value) =
                        classify_var(key, values, &id, ctx, diagnostics)
                    {
                        *fallback = value;
                    }
                });
            }
            WebNodeKind::Button { label, .. } if label.contains("data-var") => {
                *label = substitute_vars(label, values, &id, ctx, diagnostics);
            }
            _ => {}
        }
    }
}

/// Replace the inner text of each `<span data-var="key">` with the bound Text
/// value (escaped), preserving the span and its `data-var` marker so the doc
/// is re-derivable. Everything else is copied through verbatim.
fn substitute_vars(
    source: &str,
    values: &BTreeMap<String, WebBoundValue>,
    node_id: &NodeId,
    ctx: &mut Ctx,
    diagnostics: &mut Vec<Diagnostic>,
) -> String {
    let wrapped = format!("<lumen-var>{source}</lumen-var>");
    let mut reader = Reader::from_str(&wrapped);
    reader.config_mut().trim_text(false);
    let mut out = String::with_capacity(source.len());
    // >0 while inside a data-var span whose body we are dropping.
    let mut skip_depth = 0usize;
    loop {
        let pos_before = reader.buffer_position() as usize;
        let event = reader.read_event();
        let pos_after = reader.buffer_position() as usize;
        match event {
            Ok(Event::Start(start)) => {
                let name = String::from_utf8_lossy(start.name().as_ref()).to_ascii_lowercase();
                if name == "lumen-var" {
                    continue;
                }
                if skip_depth > 0 {
                    skip_depth += 1;
                    continue;
                }
                let tag_src = &wrapped[pos_before..pos_after];
                if name == "span" {
                    if let Some(key) = attr_value(&start, b"data-var") {
                        match classify_var(&key, values, node_id, ctx, diagnostics) {
                            VarAction::Substitute(value) => {
                                out.push_str(tag_src);
                                out.push_str(&escape_text(&value));
                                skip_depth = 1;
                                continue;
                            }
                            VarAction::Keep => {
                                out.push_str(tag_src);
                                continue;
                            }
                        }
                    }
                }
                out.push_str(tag_src);
            }
            Ok(Event::Empty(start)) => {
                if skip_depth > 0 {
                    continue;
                }
                let name = String::from_utf8_lossy(start.name().as_ref()).to_ascii_lowercase();
                let tag_src = &wrapped[pos_before..pos_after];
                if name == "span" {
                    if let Some(key) = attr_value(&start, b"data-var") {
                        match classify_var(&key, values, node_id, ctx, diagnostics) {
                            VarAction::Substitute(value) => {
                                out.push_str(&open_from_empty(tag_src));
                                out.push_str(&escape_text(&value));
                                out.push_str("</span>");
                                continue;
                            }
                            VarAction::Keep => {
                                out.push_str(tag_src);
                                continue;
                            }
                        }
                    }
                }
                out.push_str(tag_src);
            }
            Ok(Event::End(end)) => {
                let name = String::from_utf8_lossy(end.name().as_ref()).to_ascii_lowercase();
                if name == "lumen-var" {
                    continue;
                }
                if skip_depth > 0 {
                    skip_depth -= 1;
                    if skip_depth == 0 {
                        out.push_str("</span>");
                    }
                    continue;
                }
                out.push_str("</");
                out.push_str(&name);
                out.push('>');
            }
            Ok(Event::Text(_)) | Ok(Event::CData(_)) => {
                if skip_depth > 0 {
                    continue;
                }
                out.push_str(&wrapped[pos_before..pos_after]);
            }
            Ok(Event::Eof) => break,
            // Canonical inline content carries no comments/PIs; ignore any.
            Ok(_) => {}
            // Content is already canonical sanitized markup, so a parse error
            // is not expected; fall back to the unmodified source.
            Err(_) => return source.to_owned(),
        }
    }
    out
}

enum VarAction {
    Substitute(String),
    Keep,
}

/// Decide what a `data-var` span does for `key`, recording coverage.
fn classify_var(
    key: &str,
    values: &BTreeMap<String, WebBoundValue>,
    node_id: &NodeId,
    ctx: &mut Ctx,
    diagnostics: &mut Vec<Diagnostic>,
) -> VarAction {
    ctx.reference(key);
    match values.get(key) {
        Some(WebBoundValue::Text { value }) => {
            ctx.bind(key);
            VarAction::Substitute(value.clone())
        }
        Some(other) => {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Web,
                    "LUMW0602",
                    format!(
                        "inline var `{key}` on `{node_id}` expects a text value; \
                         binding provides a {} value (span left as authored)",
                        other.kind_name()
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint("data-var spans substitute text only."),
            );
            VarAction::Keep
        }
        None => {
            ctx.unbound_var(key, node_id);
            VarAction::Keep
        }
    }
}

fn attr_value(start: &quick_xml::events::BytesStart<'_>, key: &[u8]) -> Option<String> {
    for attr in start.attributes().with_checks(false).flatten() {
        if attr.key.as_ref().eq_ignore_ascii_case(key) {
            return Some(
                attr.unescape_value()
                    .map(|value| value.into_owned())
                    .unwrap_or_else(|_| String::from_utf8_lossy(&attr.value).into_owned()),
            );
        }
    }
    None
}

/// Convert a self-closed span tag (`<span … />`) to an opening tag so a value
/// can be nested inside it.
fn open_from_empty(tag_src: &str) -> String {
    let without_gt = tag_src.trim_end().strip_suffix('>').unwrap_or(tag_src);
    let without_slash = without_gt
        .trim_end()
        .strip_suffix('/')
        .unwrap_or(without_gt);
    format!("{}>", without_slash.trim_end())
}

fn suffix_id(id: &NodeId, index: usize) -> NodeId {
    NodeId::from(format!("{}_r{index}", id.as_str()))
}

/// Subtree ids (preorder) rooted at `id`, cycle-safe.
fn subtree_preorder(page: &WebPage, id: &NodeId) -> Vec<NodeId> {
    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    let mut stack = vec![id.clone()];
    while let Some(current) = stack.pop() {
        if !seen.insert(current.clone()) {
            continue;
        }
        if let Some(node) = page.nodes.get(&current) {
            out.push(current.clone());
            for child in node.children.iter().rev() {
                stack.push(child.clone());
            }
        }
    }
    out
}

fn collect_subtree(page: &WebPage, id: &NodeId, out: &mut BTreeSet<NodeId>) {
    for node_id in subtree_preorder(page, id) {
        out.insert(node_id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::WebThemeRef;
    use crate::ingest::ingest_html_into_page;
    use crate::theme::{compile_web_theme, WebTheme, WebThemeOptions};
    use lumen_core::PageId;

    fn theme() -> WebTheme {
        compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default()).0
    }

    fn logo_record(id: &str) -> AssetRecord {
        serde_json::from_value(serde_json::json!({
            "id": id,
            "label": "Logo",
            "kind": "logo",
            "status": "ready",
            "source": {"kind": "generated", "model": "test-model", "request_id": null},
        }))
        .expect("asset record fixture")
    }

    fn template(html: &str) -> WebDoc {
        let mut doc = WebDoc::new("tmpl", "Template", None);
        // Seed both possible logo assets so image markers resolve.
        doc.assets
            .insert(AssetId::from("tmpl_logo"), logo_record("tmpl_logo"));
        let outcome = ingest_html_into_page(&mut doc, &PageId::from("home"), html, &theme());
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        doc
    }

    fn opts() -> DeriveWebOptions {
        DeriveWebOptions {
            new_doc_id: "derived_1".to_owned(),
            new_title: Some("Derived".to_owned()),
        }
    }

    fn text_value(v: &str) -> WebBoundValue {
        WebBoundValue::Text {
            value: v.to_owned(),
        }
    }

    #[test]
    fn markers_survive_and_repeat_across_derivations() {
        let tmpl = template(
            r#"<section id="hero">
                 <h1 id="head">Grow your <span data-var="account.name">Acme</span> practice</h1>
               </section>"#,
        );
        let mut values = BTreeMap::new();
        values.insert("account.name".to_owned(), text_value("Privia Health"));

        let first = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(!first.has_errors(), "{:#?}", first.diagnostics);
        let content = text_content(&first.doc, "head");
        assert!(content.contains("Privia Health"), "{content}");
        // The span + marker survive so the doc can be re-derived.
        assert!(content.contains("data-var=\"account.name\""), "{content}");
        assert!(!content.contains("Acme"), "fallback should be gone: {content}");

        // Re-derive the DERIVED doc for a different account.
        let mut values2 = BTreeMap::new();
        values2.insert("account.name".to_owned(), text_value("Sutter"));
        let second = derive_web_doc(&first.doc, &values2, &[], &opts());
        let content2 = text_content(&second.doc, "head");
        assert!(content2.contains("Sutter"), "{content2}");
        assert!(!content2.contains("Privia"), "{content2}");
    }

    #[test]
    fn personalization_preserves_structured_blocks_and_lists() {
        let tmpl = template(
            r#"<section id="story">
                 <div id="copy" data-text="rich" data-variant="body">
                   <p>Meet <span data-var="account.name"><strong>Acme</strong></span></p>
                   <ul><li>Keep this item</li><li>For <span data-var="account.name">Acme</span></li></ul>
                 </div>
               </section>"#,
        );
        let mut values = BTreeMap::new();
        values.insert("account.name".to_owned(), text_value("Privia"));
        let derived = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);
        let page = derived.doc.page(&PageId::from("home")).unwrap();
        let WebNodeKind::Text { content, .. } =
            &page.node(&NodeId::from("copy")).unwrap().kind
        else {
            panic!("structured text");
        };
        assert_eq!(content.blocks.len(), 2);
        assert_eq!(
            content.to_semantic_html(),
            "<p>Meet <span data-var=\"account.name\"><strong>Privia</strong></span></p>\
             <ul><li>Keep this item</li><li>For <span data-var=\"account.name\">Privia</span></li></ul>"
        );
    }

    #[test]
    fn derivation_is_byte_identical_for_identical_inputs() {
        let tmpl = template(
            r#"<section id="hero">
                 <h1 id="head" data-slot="account.headline">Fallback headline</h1>
                 <p id="sub">Meet <span data-var="account.name">Acme</span></p>
                 <img id="logo" data-slot="account.logo" data-asset="tmpl_logo" alt="logo">
                 <div id="peers" data-slot="account.peers"><p id="peer">peer</p></div>
               </section>"#,
        );
        let mut values = BTreeMap::new();
        values.insert("account.name".to_owned(), text_value("Privia"));
        values.insert("account.headline".to_owned(), text_value("Trusted by clinicians"));
        values.insert(
            "account.logo".to_owned(),
            WebBoundValue::Asset {
                asset_id: AssetId::from("acct_logo"),
                alt: None,
            },
        );
        values.insert(
            "account.peers".to_owned(),
            WebBoundValue::List {
                items: vec![text_value("A"), text_value("B"), text_value("C")],
            },
        );
        let assets = [logo_record("acct_logo")];

        let a = derive_web_doc(&tmpl, &values, &assets, &opts());
        let b = derive_web_doc(&tmpl, &values, &assets, &opts());
        assert!(!a.has_errors(), "{:#?}", a.diagnostics);
        let ja = serde_json::to_string(&a.doc).unwrap();
        let jb = serde_json::to_string(&b.doc).unwrap();
        assert_eq!(ja, jb, "same inputs must serialize byte-identically");
    }

    #[test]
    fn asset_slot_substitutes_alt_when_bound() {
        let tmpl = template(
            r#"<section id="s">
                 <img id="logo" data-slot="account.logo" data-asset="tmpl_logo" alt="Privia Health">
               </section>"#,
        );
        let mut values = BTreeMap::new();
        values.insert(
            "account.logo".to_owned(),
            WebBoundValue::Asset {
                asset_id: AssetId::from("acct_logo"),
                alt: Some("Oak Street Health logo".to_owned()),
            },
        );
        let derived = derive_web_doc(&tmpl, &values, &[logo_record("acct_logo")], &opts());
        assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);
        let page = derived.doc.page(&PageId::from("home")).unwrap();
        let WebNodeKind::Image { asset_id, alt, .. } = &page.node(&NodeId::from("logo")).unwrap().kind
        else {
            panic!("logo is an image");
        };
        assert_eq!(asset_id.as_str(), "acct_logo");
        // Alt is content: the template's seed-account alt must not leak.
        assert_eq!(alt, "Oak Street Health logo");

        // Without an alt in the binding, the template's alt is the fallback.
        let mut bare = BTreeMap::new();
        bare.insert(
            "account.logo".to_owned(),
            WebBoundValue::Asset {
                asset_id: AssetId::from("acct_logo"),
                alt: None,
            },
        );
        let kept = derive_web_doc(&tmpl, &bare, &[logo_record("acct_logo")], &opts());
        let page = kept.doc.page(&PageId::from("home")).unwrap();
        let WebNodeKind::Image { alt, .. } = &page.node(&NodeId::from("logo")).unwrap().kind else {
            panic!("logo is an image");
        };
        assert_eq!(alt, "Privia Health");
    }

    #[test]
    fn repeater_clones_prototype_and_truncates() {
        let tmpl = template(
            r#"<section id="s">
                 <div id="grid" data-slot="account.logos">
                   <div id="cell"><img id="ci" data-asset="tmpl_logo" alt="peer"></div>
                 </div>
               </section>"#,
        );
        let mut items = Vec::new();
        let mut assets = Vec::new();
        for n in 0..15 {
            let id = format!("peer_{n}");
            items.push(WebBoundValue::Asset {
                asset_id: AssetId::from(id.clone()),
                alt: None,
            });
            assets.push(logo_record(&id));
        }
        let mut values = BTreeMap::new();
        values.insert("account.logos".to_owned(), WebBoundValue::List { items });

        let derived = derive_web_doc(&tmpl, &values, &assets, &opts());
        assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);
        let page = derived.doc.page(&PageId::from("home")).unwrap();
        let grid = page.node(&NodeId::from("grid")).unwrap();
        assert_eq!(grid.children.len(), MAX_REPEATER_ITEMS, "truncated to cap");
        assert_eq!(grid.children[0].as_str(), "cell_r0");
        assert!(page.node(&NodeId::from("cell_r0")).is_some());
        assert!(page.node(&NodeId::from("cell")).is_none(), "prototype removed");
        // First clone's image points at the first item's asset.
        let WebNodeKind::Image { asset_id, .. } = &page.node(&NodeId::from("ci_r0")).unwrap().kind
        else {
            panic!("image clone");
        };
        assert_eq!(asset_id.as_str(), "peer_0");
        assert!(derived
            .diagnostics
            .iter()
            .any(|d| d.code == "LUMW0604"), "truncation warning");
    }

    #[test]
    fn when_gate_removes_absent_subtree() {
        let tmpl = template(
            r#"<section id="proof" data-slot-when="account.testimonial">
                 <p id="quote"><span data-var="account.testimonial">quote</span></p>
               </section>
               <section id="always"><p id="k">Keep me</p></section>"#,
        );
        // No testimonial value → the gated section and its subtree vanish.
        let values = BTreeMap::new();
        let derived = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);
        let page = derived.doc.page(&PageId::from("home")).unwrap();
        assert!(page.node(&NodeId::from("proof")).is_none());
        assert!(page.node(&NodeId::from("quote")).is_none(), "subtree gone");
        assert!(page.node(&NodeId::from("always")).is_some());
        let root = page.node(&page.root).unwrap();
        assert!(!root.children.contains(&NodeId::from("proof")));
        assert!(derived
            .coverage
            .removed_node_ids
            .contains(&"proof".to_owned()));

        // With a value present, the section stays.
        let mut values = BTreeMap::new();
        values.insert("account.testimonial".to_owned(), text_value("Great!"));
        let kept = derive_web_doc(&tmpl, &values, &[], &opts());
        let page = kept.doc.page(&PageId::from("home")).unwrap();
        assert!(page.node(&NodeId::from("proof")).is_some());
        assert!(kept.coverage.removed_node_ids.is_empty());
    }

    #[test]
    fn kind_mismatch_leaves_node_and_reports() {
        let tmpl = template(
            r#"<section id="s"><h1 id="head" data-slot="account.name">Fallback</h1></section>"#,
        );
        let mut values = BTreeMap::new();
        // Text carrier bound to a List value → mismatch.
        values.insert(
            "account.name".to_owned(),
            WebBoundValue::List {
                items: vec![text_value("x")],
            },
        );
        let derived = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(!derived.has_errors(), "mismatch is a warning: {:#?}", derived.diagnostics);
        assert_eq!(text_content(&derived.doc, "head"), "Fallback");
        assert!(derived.diagnostics.iter().any(|d| d.code == "LUMW0602"));
        assert!(!derived.coverage.bound.contains(&"account.name".to_owned()));
    }

    #[test]
    fn unbound_key_falls_back_and_is_reported() {
        let tmpl = template(
            r#"<section id="s">
                 <h1 id="head" data-slot="account.headline">Default headline</h1>
                 <p id="sub">Hi <span data-var="account.name">there</span></p>
               </section>"#,
        );
        // Provide nothing; provide one unused value.
        let mut values = BTreeMap::new();
        values.insert("account.unused".to_owned(), text_value("nope"));
        let derived = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(!derived.has_errors());
        assert_eq!(text_content(&derived.doc, "head"), "Default headline");
        assert!(text_content(&derived.doc, "sub").contains("there"), "fallback kept");
        assert!(derived
            .coverage
            .unbound_slots
            .iter()
            .any(|e| e.key == "account.headline" && e.node_ids.contains(&"head".to_owned())));
        assert!(derived
            .coverage
            .unbound_vars
            .iter()
            .any(|e| e.key == "account.name"));
        assert!(derived
            .coverage
            .unused_values
            .contains(&"account.unused".to_owned()));
    }

    #[test]
    fn missing_asset_record_rejects_derive() {
        let tmpl = template(
            r#"<section id="s"><img id="logo" data-slot="account.logo" data-asset="tmpl_logo" alt="l"></section>"#,
        );
        let mut values = BTreeMap::new();
        values.insert(
            "account.logo".to_owned(),
            WebBoundValue::Asset {
                asset_id: AssetId::from("ghost_asset"),
                alt: None,
            },
        );
        // No asset records passed → LUMW0605 error → rejection.
        let derived = derive_web_doc(&tmpl, &values, &[], &opts());
        assert!(derived.has_errors());
        assert!(derived.diagnostics.iter().any(|d| d.code == "LUMW0605"));
    }

    fn text_content(doc: &WebDoc, id: &str) -> String {
        let page = doc.page(&PageId::from("home")).unwrap();
        let WebNodeKind::Text { content, .. } = &page.node(&NodeId::from(id)).unwrap().kind else {
            panic!("text node `{id}`");
        };
        content.to_inline_html()
    }

    #[test]
    fn bound_value_round_trips_through_json() {
        for value in [
            text_value("hi"),
            WebBoundValue::Asset {
                asset_id: AssetId::from("a1"),
                alt: None,
            },
            WebBoundValue::List {
                items: vec![text_value("x")],
            },
        ] {
            let json = serde_json::to_value(&value).unwrap();
            let back: WebBoundValue = serde_json::from_value(json).unwrap();
            assert_eq!(back, value);
        }
    }
}
