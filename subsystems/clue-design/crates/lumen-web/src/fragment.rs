//! Slot substitution inside a rendered fragment (clone-fidelity F1.4), and the
//! text-override pass that runs after it (R-A6).
//!
//! A fragment artifact is sanitized ONCE, at creation, and frozen. This walk
//! is what makes the frozen thing personalizable: it copies the artifact's
//! HTML through verbatim and touches only the elements the artifact itself
//! marked with `data-lumen-slot`, applying the values the DOCUMENT node
//! carries for those keys.
//!
//! Modeled on `derive::substitute_vars` — same quick_xml shape, same rule that
//! anything the walk does not understand is copied byte-for-byte. The artifact
//! is sanitizer-trusted (F1.2), so re-escaping, reordering or normalizing it
//! would be this render path second-guessing a decision already made once.
//!
//! Three things make this walk security-relevant, and all three are handled
//! here rather than upstream, because a slot VALUE never passes the sanitizer:
//! it is written by ops or by a derive, straight onto the document node.
//! 1. Bound text is HTML-escaped before it becomes element content.
//! 2. A bound href is scheme-checked (`util::href_is_allowed`) and refused
//!    into the artifact's own fallback when it is not a link we serve.
//! 3. A bound image resolves through `doc.assets` — the same resolution the
//!    Image node arm performs — so only a digest-derived URL ever reaches
//!    `src`; no free text from a slot value can.
//!
//! `apply_fragment_text_overrides` is the SECOND walk, over the first one's
//! output: the one interior edit a human may make to a clone (R-A6), addressed
//! by structural path rather than by a marker the artifact planted. Its own
//! doc comment carries the rules; the same escape-it-here reasoning applies,
//! because an override's text is typed into the inspector and never meets the
//! sanitizer either.
//!
//! Nothing here mutates the stored document or the stored artifact. The output
//! exists only in the rendered HTML, and every marker survives it, so a
//! rendered fragment can be rendered again from the same two inputs.

use crate::doc::{FragmentSlotValue, FragmentTextOverride, WebDoc};
use crate::render::{asset_src, FragmentSlotKind};
use crate::util::{escape_attr, escape_text, href_is_allowed};
use lumen_core::{AssetId, Diagnostic, DiagnosticSubject, NodeId, Phase};
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use std::collections::{BTreeMap, BTreeSet};

/// The artifact's own marker attribute (minted by the F1.2 annotator; any
/// source-planted `data-lumen-*` is stripped there, so a marker seen here is
/// always ours).
const SLOT_ATTR: &[u8] = b"data-lumen-slot";

/// Restore only declared platform tab roots and scope their owned references
/// to this pin. Run after slots/overrides; never change stored artifact bytes.
/// Legacy captures do not enter this pass. The API validates DOM ownership at
/// mint/read; this walk additionally refuses lost/duplicated targets at render.
pub fn instantiate_native_fragment(
    html: &str,
    dependencies: &crate::render::NativeFragmentDependencies,
    node_id: &NodeId,
) -> Result<String, String> {
    if dependencies.version != 1
        || dependencies.platform_runtime != 2
        || dependencies.tabs.is_empty()
        || dependencies.tabs.len() > 32
    {
        return Err("unsupported native fragment dependency version/shape".to_owned());
    }
    let mut ids = BTreeMap::new();
    let mut roots = BTreeSet::new();
    let mut controls = BTreeMap::new();
    let hex = |text: &str| text.bytes().map(|b| format!("{b:02x}")).collect::<String>();
    let prefix = format!("lumen-pin-{}-", hex(node_id.as_str()));
    for group in &dependencies.tabs {
        if group.items.is_empty() || group.items.len() > 64 {
            return Err("unsupported native tab item count".to_owned());
        }
        roots.insert(group.root_id.clone());
        let mut group_ids = vec![&group.root_id];
        for item in &group.items {
            group_ids.extend([&item.tab_id, &item.panel_id]);
            controls.insert(
                item.tab_id.clone(),
                ("tab", "aria-controls", item.panel_id.clone()),
            );
            controls.insert(
                item.panel_id.clone(),
                ("tabpanel", "aria-labelledby", item.tab_id.clone()),
            );
        }
        for id in group_ids {
            if id.is_empty()
                || id.len() > 256
                || !id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
                || ids
                    .insert(id.clone(), format!("{prefix}{}", hex(id)))
                    .is_some()
            {
                return Err("native fragment target IDs must be safe and unique".to_owned());
            }
        }
    }
    let mut reader = Reader::from_str(html);
    reader.config_mut().check_end_names = false; // sanitized HTML contains void elements
    let mut out = String::with_capacity(html.len());
    let mut seen = BTreeSet::new();
    loop {
        let before = reader.buffer_position() as usize;
        let event = reader
            .read_event()
            .map_err(|_| "native fragment markup is unreadable")?;
        let after = reader.buffer_position() as usize;
        match event {
            Event::Start(ref start) | Event::Empty(ref start) => {
                let mut replacements: Vec<(String, String)> = Vec::new();
                if let Some(id) = attr_value(start, b"id") {
                    if let Some(scoped) = ids.get(&id) {
                        if !seen.insert(id.clone()) {
                            return Err(format!("native fragment target `{id}` is duplicated"));
                        }
                        if let Some((role, reference, target)) = controls.get(&id) {
                            if attr_value(start, b"role").as_deref() != Some(role)
                                || attr_value(start, reference.as_bytes()).as_deref()
                                    != Some(target)
                            {
                                return Err(format!(
                                    "native fragment target `{id}` lost its relationship"
                                ));
                            }
                        }
                        replacements.push(("id".into(), scoped.clone()));
                        if roots.contains(&id) {
                            replacements.push(("data-lumen-tabs".into(), "true".into()));
                        }
                    }
                }
                // Exact token references only: never rewrite text, asset URLs or CSS.
                for attr in [
                    "aria-controls",
                    "aria-labelledby",
                    "aria-describedby",
                    "for",
                ] {
                    if let Some(value) = attr_value(start, attr.as_bytes()) {
                        if value.split_whitespace().any(|v| ids.contains_key(v)) {
                            let rewritten = value
                                .split_whitespace()
                                .map(|v| ids.get(v).map_or(v, String::as_str))
                                .collect::<Vec<_>>()
                                .join(" ");
                            replacements.push((attr.into(), rewritten));
                        }
                    }
                }
                if let Some(value) = attr_value(start, b"href") {
                    if let Some(scoped) = value.strip_prefix('#').and_then(|id| ids.get(id)) {
                        replacements.push(("href".into(), format!("#{scoped}")));
                    }
                }
                if replacements.is_empty() {
                    out.push_str(&html[before..after]);
                } else {
                    let refs = replacements
                        .iter()
                        .map(|(k, v)| (k.as_str(), v.as_str()))
                        .collect::<Vec<_>>();
                    out.push_str(&rewrite_tag(
                        start,
                        &tag_name(start),
                        matches!(event, Event::Empty(_)),
                        &refs,
                        &[],
                        &[],
                    ));
                }
            }
            Event::Eof => break,
            _ => out.push_str(&html[before..after]),
        }
    }
    if seen.len() != ids.len() {
        return Err("native fragment lost one or more declared targets after edits".to_owned());
    }
    Ok(out)
}

/// Wrapper element name, so the walk sees one well-formed root. Chosen to be a
/// name no real markup carries.
const WALK_ROOT: &str = "lumen-fragment-walk";

/// HTML elements that carry no end tag. A depth counter that counted them
/// would never come back down, and every sibling after a replaced `<h1>a<br>b`
/// would silently vanish from the page.
const VOID_ELEMENTS: &[&str] = &[
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
    "track", "wbr",
];

/// Attributes that load image bytes alongside `src`. When a slot swaps the
/// image, these are DROPPED rather than kept: a `srcset` left pointing at the
/// cloned site's rungs is what a retina visitor actually loads, so keeping it
/// would show the old logo to exactly the people with the better screens.
const STALE_IMAGE_ATTRS: &[&str] = &["srcset", "imagesrcset", "sizes"];

/// Apply `slots` to the artifact's `html`, returning the HTML to render.
///
/// Never mutates anything. With no bound slot the return value is the input,
/// byte for byte.
pub(crate) fn substitute_fragment_slots(
    html: &str,
    slots: &BTreeMap<String, FragmentSlotValue>,
    kinds: &BTreeMap<String, FragmentSlotKind>,
    doc: &WebDoc,
    asset_base_url: &str,
    node_id: &NodeId,
    diagnostics: &mut Vec<Diagnostic>,
) -> String {
    if slots.is_empty() {
        return html.to_owned();
    }

    let wrapped = format!("<{WALK_ROOT}>{html}</{WALK_ROOT}>");
    let mut reader = Reader::from_str(&wrapped);
    let config = reader.config_mut();
    config.trim_text(false);
    // The artifact is HTML, not XML: void elements have no end tag and the
    // sanitizer preserves the author's structure as-is. Name checking would
    // turn ordinary markup into a parse error, and a parse error abandons the
    // whole substitution.
    config.check_end_names = false;
    config.allow_unmatched_ends = true;

    let mut out = String::with_capacity(html.len() + 256);
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut skip: Option<Skip> = None;

    loop {
        let pos_before = reader.buffer_position() as usize;
        let event = reader.read_event();
        let pos_after = reader.buffer_position() as usize;
        let source = &wrapped[pos_before..pos_after];
        match event {
            Ok(event @ (Event::Start(_) | Event::Empty(_))) => {
                let empty = matches!(event, Event::Empty(_));
                let start = match &event {
                    Event::Start(start) | Event::Empty(start) => start,
                    _ => unreachable!("matched above"),
                };
                let name = tag_name(start);
                if name == WALK_ROOT {
                    continue;
                }
                if let Some(state) = skip.as_mut() {
                    // Still record the marker: a bound key inside a consumed
                    // subtree IS present in the artifact, and reporting it as
                    // absent (LUMW0416) would send an operator chasing a
                    // phantom. But a BOUND one has just lost its value — the
                    // element it would have been applied to is not in the
                    // output — so the loss is named rather than swallowed.
                    if let Some(key) = attr_value(start, SLOT_ATTR) {
                        if slots.contains_key(&key) {
                            diagnostics.push(nested_marker_consumed(
                                node_id,
                                &key,
                                &state.owner,
                                state.close.is_none(),
                            ));
                        }
                        seen.insert(key);
                    }
                    if !empty && !is_void(&name) {
                        state.depth.push(name);
                    }
                    continue;
                }
                let Some(key) = attr_value(start, SLOT_ATTR) else {
                    out.push_str(source);
                    continue;
                };
                seen.insert(key.clone());
                let Some(value) = slots.get(&key) else {
                    // Unbound: the marker's stored content IS the fallback.
                    out.push_str(source);
                    continue;
                };
                let Some(kind) = kinds.get(&key).copied() else {
                    diagnostics.push(kind_unknown(node_id, &key));
                    out.push_str(source);
                    continue;
                };
                apply_marker(
                    Marker {
                        start,
                        name: &name,
                        source,
                        empty,
                        key: &key,
                        kind,
                        value,
                    },
                    doc,
                    asset_base_url,
                    node_id,
                    &mut out,
                    &mut skip,
                    diagnostics,
                );
            }
            Ok(Event::End(end)) => {
                let name = String::from_utf8_lossy(end.name().as_ref()).into_owned();
                if name == WALK_ROOT {
                    continue;
                }
                if let Some(state) = skip.as_mut() {
                    if is_void(&name) {
                        continue;
                    }
                    if state.depth.pop().is_some() {
                        continue;
                    }
                    // This closes the marked element itself.
                    if let Some(close) = state.close.take() {
                        out.push_str(&close);
                    }
                    skip = None;
                    continue;
                }
                out.push_str(source);
            }
            Ok(Event::Eof) => break,
            // Text, CDATA, comments, PIs, doctypes — copied through exactly as
            // the sanitizer left them. The walk understands markers; anything
            // else is somebody else's decision, already made.
            Ok(_) => {
                if skip.is_none() {
                    out.push_str(source);
                }
            }
            // The artifact is stored markup, so a parse error is not expected.
            // If one happens, emit the artifact unchanged rather than a
            // half-substituted document.
            Err(_) => return html.to_owned(),
        }
    }

    for key in slots.keys() {
        if !seen.contains(key) {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Web,
                    "LUMW0416",
                    format!(
                        "fragment node `{node_id}` binds slot `{key}`, which this artifact does \
                         not declare; the value was ignored"
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint("Slot keys come from the artifact's slot manifest."),
            );
        }
    }

    out
}

/// What the walk is currently swallowing, and what (if anything) it owes the
/// output when the marked element closes.
struct Skip {
    /// Names of the not-yet-closed elements INSIDE the marked one, so an
    /// unbalanced artifact cannot desynchronize the walk.
    ///
    /// A NAME stack rather than a counter, and it is only ever right because
    /// the artifact was re-serialized by lexbor at sanitization: the sanitizer
    /// parses the harvested markup into a tree and writes that tree back, so
    /// what reaches this walk is balanced by construction. Hand-written markup
    /// with a stray `</div>` would not be, and this stack is what keeps that
    /// from swallowing the rest of the page rather than an assumption that it
    /// cannot happen.
    depth: Vec<String>,
    /// The end tag to emit when the marked element closes (text substitution),
    /// or `None` when the element is being dropped entirely (visibility).
    close: Option<String>,
    /// The slot key whose value consumed this subtree, so a bound marker found
    /// inside it can say what swallowed it.
    owner: String,
}

struct Marker<'a> {
    start: &'a BytesStart<'a>,
    name: &'a str,
    source: &'a str,
    empty: bool,
    key: &'a str,
    kind: FragmentSlotKind,
    value: &'a FragmentSlotValue,
}

fn apply_marker(
    marker: Marker<'_>,
    doc: &WebDoc,
    asset_base_url: &str,
    node_id: &NodeId,
    out: &mut String,
    skip: &mut Option<Skip>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Marker {
        start,
        name,
        source,
        empty,
        key,
        kind,
        value,
    } = marker;
    match (kind, value) {
        (FragmentSlotKind::Text, FragmentSlotValue::Text(text)) => {
            if is_void(name) {
                // A void element has no content to replace; substituting would
                // mean inventing a container the artifact never had.
                diagnostics.push(kind_mismatch(node_id, key, kind, value));
                out.push_str(source);
                return;
            }
            // The value never met the sanitizer — it is ops- or derive-authored
            // and lands straight on the node — so it is escaped HERE, into text
            // context, before it becomes element content.
            if empty {
                out.push_str(&open_from_empty(source));
                out.push_str(&escape_text(text));
                out.push_str(&format!("</{name}>"));
                return;
            }
            out.push_str(source);
            out.push_str(&escape_text(text));
            *skip = Some(Skip {
                depth: Vec::new(),
                close: Some(format!("</{name}>")),
                owner: key.to_owned(),
            });
        }
        (FragmentSlotKind::Href, FragmentSlotValue::Text(target)) => {
            if !href_is_allowed(target) {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Web,
                        "LUMW0414",
                        format!(
                            "fragment node `{node_id}` binds href slot `{key}` to a target that \
                             is not an allowed link; the artifact's own href was kept"
                        ),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    )
                    .with_hint("Links are http(s)://, mailto:, tel:, `#fragment` or `/path`."),
                );
                out.push_str(source);
                return;
            }
            out.push_str(&rewrite_tag(
                start,
                name,
                empty,
                &[("href", target)],
                &[],
                &[],
            ));
        }
        (FragmentSlotKind::Image, FragmentSlotValue::Asset(asset_id)) => {
            // Only a digest-derived URL ever reaches `src`: the slot value
            // names an ASSET, and the document's own asset record is what
            // turns that name into bytes — exactly as the Image node arm does.
            let resolved = doc
                .assets
                .get(&AssetId::from(asset_id.as_str()))
                .and_then(|record| asset_src(record, asset_base_url));
            let Some(src) = resolved else {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Web,
                        "LUMW0415",
                        format!(
                            "fragment node `{node_id}` binds image slot `{key}` to asset \
                             `{asset_id}`, which has no resolvable bytes in this document; the \
                             artifact's own image was kept"
                        ),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    )
                    .with_hint("Bind an asset the document holds (derive upserts the record)."),
                );
                out.push_str(source);
                return;
            };
            out.push_str(&rewrite_tag(
                start,
                name,
                empty,
                &[("src", &src)],
                &[],
                STALE_IMAGE_ATTRS,
            ));
        }
        (FragmentSlotKind::Visibility, FragmentSlotValue::Visible(visible)) => {
            if *visible {
                out.push_str(source);
                return;
            }
            if empty || is_void(name) {
                return; // nothing follows it to swallow
            }
            *skip = Some(Skip {
                depth: Vec::new(),
                close: None,
                owner: key.to_owned(),
            });
        }
        _ => {
            diagnostics.push(kind_mismatch(node_id, key, kind, value));
            out.push_str(source);
        }
    }
}

fn kind_mismatch(
    node_id: &NodeId,
    key: &str,
    kind: FragmentSlotKind,
    value: &FragmentSlotValue,
) -> Diagnostic {
    Diagnostic::warning(
        Phase::Web,
        "LUMW0413",
        format!(
            "fragment node `{node_id}` binds slot `{key}` (a {} slot) to a {} value; the \
             artifact's own content was kept",
            kind.name(),
            value_tag(value)
        ),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint("text/href slots take {\"text\": …}, image slots {\"asset\": …}, visibility slots {\"visible\": …}.")
}

/// A bound marker whose element sits inside another slot's consumed subtree.
///
/// The artifact declares both slots, and both are legal to declare — `slots.py`
/// refuses two slots on one ELEMENT, not a slot inside another slot's element —
/// so this is a real authoring shape, and one F2's automatic selector detection
/// will produce. The inner value simply cannot be applied: the element it names
/// is not in the output. Naming both keys is the difference between "that
/// binding does nothing" being discoverable and being a mystery.
fn nested_marker_consumed(
    node_id: &NodeId,
    key: &str,
    owner: &str,
    hidden: bool,
) -> Diagnostic {
    let fate = if hidden {
        format!("inside slot `{owner}`, which this node hides")
    } else {
        format!("inside slot `{owner}`, whose bound value replaced it")
    };
    Diagnostic::warning(
        Phase::Web,
        "LUMW0417",
        format!(
            "fragment node `{node_id}` binds slot `{key}`, whose marker sits {fate}; \
             that value was not applied"
        ),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint(
        "A slot inside another slot's element cannot be bound at the same time; bind the outer \
         slot or the inner one.",
    )
}

fn kind_unknown(node_id: &NodeId, key: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Web,
        "LUMW0413",
        format!(
            "fragment node `{node_id}` binds slot `{key}`, whose kind this artifact does not \
             declare; the artifact's own content was kept"
        ),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint("The slot manifest declares each slot's kind; a value cannot be applied without it.")
}

fn value_tag(value: &FragmentSlotValue) -> &'static str {
    match value {
        FragmentSlotValue::Text(_) => "text",
        FragmentSlotValue::Asset(_) => "asset",
        FragmentSlotValue::Visible(_) => "visible",
    }
}

// --- text overrides (R-A6) --------------------------------------------------

/// Apply this node's `text_overrides` to already-slot-substituted `html`.
///
/// The second and last walk of a fragment render. Ruling R-A6 (founder,
/// 2026-09-04) amends D-F3 — a fragment is opaque below its root — by exactly
/// one axis: the TEXT of one element, addressed by structural path. Everything
/// else about the clone is still untouchable here, and the artifact itself is
/// never rewritten: an override is a per-instance substitution that exists only
/// in the rendered bytes, so clearing it restores the clone exactly.
///
/// It runs AFTER the slot pass, on the slot pass's output, for two reasons: the
/// marketer's own words outrank the agent's personalization on the one element
/// they edited, and the markup the editor measured the path against is the
/// rendered markup — the slot pass's output — not the stored artifact.
///
/// **The path's origin is the clone WRAPPER.** `render.rs` emits the artifact
/// inside `<div class="lumen-fragment …" data-fragment-root>`, so that
/// wrapper's element children are the stored HTML's top-level elements. The
/// walk wraps the same HTML in `<lumen-fragment-walk>`, which puts the origin
/// in exactly the same place: a first `:nth-child(n)` step names the n-th
/// TOP-LEVEL element of the artifact. Two other implementations count from that
/// same origin and must agree with this one step for step — the editor bridge
/// (`web_bridge.py`'s `elementPath`, counting `firstElementChild` /
/// `nextElementSibling` from `data-fragment-root`) and the server-side resolver
/// (`apps/api/lumen_api/fragments/paths.py`, walking from `body`).
///
/// Never mutates anything. With no override the return value is the input, byte
/// for byte, without even parsing it.
pub(crate) fn apply_fragment_text_overrides(
    html: &str,
    overrides: &BTreeMap<String, FragmentTextOverride>,
    node_id: &NodeId,
    diagnostics: &mut Vec<Diagnostic>,
) -> String {
    if overrides.is_empty() {
        return html.to_owned();
    }

    let wrapped = format!("<{WALK_ROOT}>{html}</{WALK_ROOT}>");
    let mut reader = Reader::from_str(&wrapped);
    let config = reader.config_mut();
    config.trim_text(false);
    // Same reasons as the slot walk: this is HTML, not XML, and a parse error
    // would abandon the whole pass.
    config.check_end_names = false;
    config.allow_unmatched_ends = true;

    let mut out = String::with_capacity(html.len() + 256);
    let mut applied: BTreeSet<String> = BTreeSet::new();
    // One counter per OPEN depth, counting ELEMENT children only. The last
    // entry is the index of the element being read and every entry before it is
    // an ancestor's, frozen at its own index for as long as it stays open — so
    // the stack IS the path, and no separate bookkeeping can drift from it.
    let mut counters: Vec<usize> = vec![0];
    let mut skip: Option<Skip> = None;

    loop {
        let pos_before = reader.buffer_position() as usize;
        let event = reader.read_event();
        let pos_after = reader.buffer_position() as usize;
        let source = &wrapped[pos_before..pos_after];
        match event {
            Ok(event @ (Event::Start(_) | Event::Empty(_))) => {
                let empty = matches!(event, Event::Empty(_));
                let start = match &event {
                    Event::Start(start) | Event::Empty(start) => start,
                    _ => unreachable!("matched above"),
                };
                let name = tag_name(start);
                if name == WALK_ROOT {
                    continue;
                }
                if let Some(state) = skip.as_mut() {
                    // Inside a replaced subtree nothing is counted and nothing
                    // is emitted; the name stack only has to know which `End`
                    // closes the overridden element.
                    if !empty && !is_void(&name) {
                        state.depth.push(name);
                    }
                    continue;
                }
                if let Some(index) = counters.last_mut() {
                    *index += 1;
                }
                let path = current_path(&counters);
                match overrides.get(&path) {
                    // A void or self-closing element has no content to replace,
                    // and inventing a container the artifact never had is not
                    // the answer — an `<img>` has no text.
                    Some(_) if empty || is_void(&name) => {
                        applied.insert(path.clone());
                        diagnostics.push(override_on_void(node_id, &path, &name));
                        out.push_str(source);
                    }
                    Some(over) => {
                        applied.insert(path.clone());
                        out.push_str(&override_tag(start, &name, &path, over));
                        out.push_str(&override_content(over));
                        // The original subtree is consumed exactly as a text
                        // slot's is. Deliberately no `counters.push`: the walk
                        // does not descend, and the `End` that closes this
                        // element is taken by the skip branch without a pop, so
                        // this element's own counter survives for its siblings.
                        skip = Some(Skip {
                            depth: Vec::new(),
                            close: Some(format!("</{name}>")),
                            owner: path,
                        });
                    }
                    None => {
                        out.push_str(source);
                        if !empty && !is_void(&name) {
                            counters.push(0);
                        }
                    }
                }
            }
            Ok(Event::End(end)) => {
                let name = String::from_utf8_lossy(end.name().as_ref()).into_owned();
                if name == WALK_ROOT {
                    continue;
                }
                if let Some(state) = skip.as_mut() {
                    if is_void(&name) {
                        continue;
                    }
                    if state.depth.pop().is_some() {
                        continue;
                    }
                    // This closes the overridden element itself.
                    if let Some(close) = state.close.take() {
                        out.push_str(&close);
                    }
                    skip = None;
                    continue;
                }
                // A void element never opened a depth, and an unmatched `</div>`
                // (the reader is told to allow them) must not pop past the root.
                if !is_void(&name) && counters.len() > 1 {
                    counters.pop();
                }
                out.push_str(source);
            }
            Ok(Event::Eof) => break,
            // Text, comments, CDATA, PIs: copied through, and never counted —
            // the bridge counts elements, so counting these would address a
            // different element than the one the marketer clicked.
            Ok(_) => {
                if skip.is_none() {
                    out.push_str(source);
                }
            }
            // Same answer as the slot walk: emit the input unchanged rather
            // than a half-edited page.
            Err(_) => return html.to_owned(),
        }
    }

    for path in overrides.keys() {
        if !applied.contains(path) {
            diagnostics.push(override_path_unresolved(node_id, path));
        }
    }

    out
}

/// The stack of element-child indices as the `:nth-child(n) > …` address it is.
fn current_path(counters: &[usize]) -> String {
    counters
        .iter()
        .map(|index| format!(":nth-child({index})"))
        .collect::<Vec<_>>()
        .join(" > ")
}

/// Relative size steps → an `em` multiplier on the artifact's own scale.
///
/// A step, not a font size: the clone owns its type scale and this only walks
/// it, so `em` — relative to what the element already inherits — is the only
/// unit that cannot fight the artifact's own CSS. The multipliers are literal
/// strings rather than formatted floats because `0.8125` through a float
/// formatter is exactly the kind of trailing-digit noise that shows up in a
/// diff of rendered HTML and in nothing else.
fn size_em(step: i8) -> Option<&'static str> {
    Some(match step {
        -3 => "0.75",
        -2 => "0.8125",
        -1 => "0.875",
        0 => "1",
        1 => "1.125",
        2 => "1.25",
        3 => "1.5",
        // Validation refuses a step outside the ramp at the door (LUMW0443), so
        // this is only reachable on a document that never passed it. The
        // artifact's own size is the honest answer; a panic is not.
        _ => return None,
    })
}

/// The overridden element's start tag: its own attributes, then ours.
///
/// `data-lumen-override` always (it is how the editor finds an edited element
/// again in a fresh render), `data-lumen-size` only when the override carries a
/// step, and the size itself as an inline `font-size` appended to whatever
/// `style` the clone already had.
fn override_tag(
    start: &BytesStart<'_>,
    name: &str,
    path: &str,
    over: &FragmentTextOverride,
) -> String {
    let step = over.size.map(|step| step.to_string());
    let font_size = over
        .size
        .and_then(size_em)
        .map(|em| format!("font-size:{em}em"));
    let mut replacements: Vec<(&str, &str)> = vec![("data-lumen-override", path)];
    if let Some(step) = step.as_deref() {
        replacements.push(("data-lumen-size", step));
    }
    let appends: Vec<(&str, &str)> = match font_size.as_deref() {
        Some(font_size) => vec![("style", font_size)],
        None => Vec::new(),
    };
    rewrite_tag(start, name, false, &replacements, &appends, &[])
}

/// The override's text as element content: escaped, then wrapped in the marks
/// it carries, `strong > em > u` outermost-first.
///
/// The text never met the sanitizer — it is typed by a human into the inspector
/// and lands straight on the document node — so it is escaped HERE, into text
/// context, or not at all. The three marks are the whole vocabulary: an
/// override is a nudge, not a second rich-text document.
fn override_content(over: &FragmentTextOverride) -> String {
    let mut open = String::new();
    let mut close = String::new();
    for (present, tag) in [
        (over.bold, "strong"),
        (over.italic, "em"),
        (over.underline, "u"),
    ] {
        if present {
            open.push_str(&format!("<{tag}>"));
            close.insert_str(0, &format!("</{tag}>"));
        }
    }
    format!("{open}{}{close}", escape_text(&over.text))
}

/// The markup an edit was made against can legitimately have moved on — a later
/// turn regenerated the band — and the honest answer is to say the address is
/// dead and leave the clone's own words standing, never to guess at the nearest
/// heading and put words in the marketer's mouth.
fn override_path_unresolved(node_id: &NodeId, path: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Web,
        "LUMW0444",
        format!(
            "fragment node `{node_id}` carries a text override at `{path}`, which does not \
             resolve to an element in this artifact; the clone's own text was kept"
        ),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint(
        "The band was probably regenerated after the edit was made; clear the override and make \
         it again against the markup that is there now.",
    )
}

fn override_on_void(node_id: &NodeId, path: &str, name: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Web,
        "LUMW0444",
        format!(
            "fragment node `{node_id}` carries a text override at `{path}`, which lands on \
             `{name}` — an element that holds no text; the override was not applied"
        ),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint("A text override addresses an element that holds words, not an image or a break.")
}

/// Re-emit one start tag with `replacements` applied, `appends` merged onto the
/// artifact's own value, and `drops` removed.
///
/// Only ever called on an element the artifact itself marked, or one a text
/// override addresses, so the normalization this performs (attribute values
/// re-escaped into canonical double-quoted form) is confined to those —
/// everything else in the artifact is copied through as source bytes.
///
/// An attribute the element already carries keeps its SOURCE position whether
/// it is replaced or appended to; a new one is written after every original, in
/// the order given (replacements first, then appends).
fn rewrite_tag(
    start: &BytesStart<'_>,
    name: &str,
    empty: bool,
    replacements: &[(&str, &str)],
    appends: &[(&str, &str)],
    drops: &[&str],
) -> String {
    let mut out = format!("<{name}");
    let mut written: BTreeSet<String> = BTreeSet::new();
    for attr in start.attributes().with_checks(false).flatten() {
        let key = String::from_utf8_lossy(attr.key.as_ref()).into_owned();
        let lower = key.to_ascii_lowercase();
        if drops.iter().any(|drop| *drop == lower) {
            continue;
        }
        written.insert(lower.clone());
        // The injected value is the untrusted half: it is escaped.
        if let Some((_, replacement)) = replacements
            .iter()
            .find(|(replaced, _)| *replaced == lower)
        {
            out.push_str(&format!(" {key}=\"{}\"", escape_attr(replacement)));
            continue;
        }
        // Every OTHER attribute is carried over as the sanitizer wrote it,
        // without an unescape/re-escape round trip. Round-tripping would
        // turn `alt="A &nbsp; B"` into a literal `&amp;nbsp;` (quick_xml
        // resolves only the five XML entities), which is this walk
        // normalizing markup it was told not to touch. The artifact is
        // serialized with double quotes and `"` escaped, so a raw value
        // cannot close the attribute — and if one ever did, it is escaped
        // instead of emitted.
        // A bare boolean attribute (`disabled`, `hidden`) re-emits as
        // `disabled=""`, which is the same HTML. Safe here for the same
        // upstream reason: lexbor re-serialized this markup at
        // sanitization, so every attribute already arrives quoted and
        // normalized, and quick_xml hands back an empty value rather than
        // the ragged shapes raw harvested HTML can carry.
        let raw = String::from_utf8_lossy(attr.value.as_ref()).into_owned();
        let carried = if raw.contains('"') {
            escape_attr(&raw)
        } else {
            raw
        };
        match appends.iter().find(|(appended, _)| *appended == lower) {
            // An APPEND keeps the artifact's own value and adds to it, because
            // the clone's own `style="color:red"` is part of what makes it look
            // like the clone; replacing it would strip the declaration a
            // relative size step was meant to sit on top of.
            Some((_, addition)) => {
                let separator = if carried.is_empty() || carried.trim_end().ends_with(';') {
                    ""
                } else {
                    ";"
                };
                out.push_str(&format!(
                    " {key}=\"{carried}{separator}{}\"",
                    escape_attr(addition)
                ));
            }
            None => out.push_str(&format!(" {key}=\"{carried}\"")),
        }
    }
    // An element the manifest calls an href/image slot normally has the
    // attribute already (the annotator refuses one that does not), but a
    // hand-built artifact might not — append rather than silently no-op. An
    // override's own `data-lumen-*` attributes are new by construction and
    // land here too.
    for (key, value) in replacements.iter().chain(appends.iter()) {
        if !written.contains(*key) {
            out.push_str(&format!(" {key}=\"{}\"", escape_attr(value)));
        }
    }
    out.push_str(if empty { "/>" } else { ">" });
    out
}

/// `<x a="1"/>` → `<x a="1">`, so text can be written inside it.
fn open_from_empty(source: &str) -> String {
    let trimmed = source.trim_end();
    match trimmed.strip_suffix("/>") {
        Some(head) => format!("{}>", head.trim_end()),
        None => trimmed.to_owned(),
    }
}

fn tag_name(start: &BytesStart<'_>) -> String {
    String::from_utf8_lossy(start.name().as_ref()).into_owned()
}

fn is_void(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    VOID_ELEMENTS.contains(&lower.as_str())
}

fn attr_value(start: &BytesStart<'_>, key: &[u8]) -> Option<String> {
    for attr in start.attributes().with_checks(false).flatten() {
        if attr.key.as_ref().eq_ignore_ascii_case(key) {
            return Some(
                attr.unescape_value()
                    .map(|value| value.into_owned())
                    .unwrap_or_else(|_| String::from_utf8_lossy(attr.value.as_ref()).into_owned()),
            );
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::{FragmentSlotValue, WebDoc};
    use crate::render::FragmentSlotKind;
    use lumen_core::{AssetId, AssetRecord, NodeId};
    use std::collections::BTreeMap;

    const DIGEST: &str = "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999";

    fn logo_record(id: &str, digest: &str) -> AssetRecord {
        serde_json::from_value(serde_json::json!({
            "id": id,
            "label": "Logo",
            "kind": "logo",
            "status": "ready",
            "source": {"kind": "generated", "model": "test-model", "request_id": null},
            "media": {
                "mime_type": "image/png",
                "filename": "logo.png",
                "byte_length": 12,
                "digest": {"algorithm": "sha256", "value": digest},
                "location": null,
            },
        }))
        .expect("asset record fixture")
    }

    fn doc_with(assets: &[(&str, &str)]) -> WebDoc {
        let mut doc = WebDoc::new("doc_1", "Doc", None);
        for (id, digest) in assets {
            doc.assets
                .insert(AssetId::from(*id), logo_record(id, digest));
        }
        doc
    }

    fn kinds(entries: &[(&str, FragmentSlotKind)]) -> BTreeMap<String, FragmentSlotKind> {
        entries
            .iter()
            .map(|(key, kind)| ((*key).to_owned(), *kind))
            .collect()
    }

    fn slots(entries: Vec<(&str, FragmentSlotValue)>) -> BTreeMap<String, FragmentSlotValue> {
        entries
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value))
            .collect()
    }

    fn run(
        html: &str,
        slots: &BTreeMap<String, FragmentSlotValue>,
        kinds: &BTreeMap<String, FragmentSlotKind>,
        doc: &WebDoc,
    ) -> (String, Vec<String>) {
        let mut diagnostics = Vec::new();
        let out = substitute_fragment_slots(
            html,
            slots,
            kinds,
            doc,
            "/asset-store",
            &NodeId::from("frg_hero"),
            &mut diagnostics,
        );
        let codes = diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code.clone())
            .collect();
        (out, codes)
    }

    // --- the copy-through guarantee ---------------------------------------

    #[test]
    fn an_artifact_with_nothing_bound_is_emitted_byte_for_byte() {
        // Deliberately full of things a careless walk would "fix": a comment,
        // an unclosed void element, a single-quoted attribute, an entity, an
        // uppercase tag, and a marker whose key nothing binds.
        let html = "<!-- hero --><SECTION class='hero' data-x=\"a&amp;b\">\
                    <h1 data-lumen-slot=\"headline\">Care &amp; comfort</h1><br>\
                    <img src=\"/asset-store/abc\" srcset=\"/asset-store/abc 2x\"></SECTION>";
        let doc = doc_with(&[]);

        let (empty_bound, codes) = run(html, &slots(vec![]), &kinds(&[]), &doc);
        assert_eq!(empty_bound, html);
        assert!(codes.is_empty(), "{codes:?}");

        // An UNBOUND marker is the same story: the marker's stored content IS
        // the fallback, so the artifact is emitted exactly as stored.
        let (unbound, codes) = run(
            html,
            &slots(vec![("other", FragmentSlotValue::Text("x".to_owned()))]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        assert!(unbound.contains("Care &amp; comfort"), "{unbound}");
        // A bound key the artifact never marked is loud, not silent.
        assert_eq!(codes, vec!["LUMW0416"]);
    }

    // --- text ---------------------------------------------------------------

    #[test]
    fn a_bound_text_slot_replaces_the_content_and_keeps_the_marker() {
        let html = "<section><h1 class=\"t\" data-lumen-slot=\"headline\">\
                    Care, <em>on your terms</em></h1></section>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Text("Privia Health".to_owned()),
            )]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        assert_eq!(
            out,
            "<section><h1 class=\"t\" data-lumen-slot=\"headline\">Privia Health</h1></section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    /// SECURITY RED CASE 1 (brief obligation 1). A slot value never meets the
    /// sanitizer: it is ops- or agent-authored and lands straight on the node.
    #[test]
    fn text_bound_to_markup_renders_inert() {
        let html = "<h1 data-lumen-slot=\"headline\">Care</h1>";
        let doc = doc_with(&[]);
        let (out, _) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Text(
                    "<script>alert(1)</script><img src=x onerror=alert(2)>".to_owned(),
                ),
            )]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        // No tag survives: the hostile value is text, and only text.
        assert!(!out.contains("<script"), "{out}");
        assert!(!out.contains("<img"), "{out}");
        assert_eq!(
            out,
            "<h1 data-lumen-slot=\"headline\">&lt;script&gt;alert(1)&lt;/script&gt;\
             &lt;img src=x onerror=alert(2)&gt;</h1>"
        );
        // The marker survives so the slot can be re-bound later.
        assert!(out.contains("data-lumen-slot=\"headline\""), "{out}");
    }

    #[test]
    fn a_wrong_kind_value_falls_back_instead_of_substituting() {
        let html = "<h1 data-lumen-slot=\"headline\">Care</h1>";
        let doc = doc_with(&[("asset_logo", DIGEST)]);
        // An asset value on a TEXT slot.
        let (out, codes) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Asset("asset_logo".to_owned()),
            )]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        assert_eq!(out, html);
        assert_eq!(codes, vec!["LUMW0413"]);

        // A slot the artifact marked but whose kind the render map never
        // declared is the same fail-closed answer: fallback, loudly.
        let (out, codes) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Text("Privia".to_owned()),
            )]),
            &kinds(&[]),
            &doc,
        );
        assert_eq!(out, html);
        assert_eq!(codes, vec!["LUMW0413"]);
    }

    // --- href ---------------------------------------------------------------

    #[test]
    fn a_bound_href_slot_swaps_the_target_and_keeps_the_label() {
        let html = "<a class=\"btn\" href=\"/demo\" data-lumen-slot=\"cta\">Book a demo</a>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "cta",
                FragmentSlotValue::Text("https://priviahealth.com/demo".to_owned()),
            )]),
            &kinds(&[("cta", FragmentSlotKind::Href)]),
            &doc,
        );
        assert!(out.contains("href=\"https://priviahealth.com/demo\""), "{out}");
        // The artifact's own target is gone, not duplicated.
        assert!(!out.contains("href=\"/demo\""), "{out}");
        assert!(out.contains(">Book a demo</a>"), "{out}");
        assert!(out.contains("data-lumen-slot=\"cta\""), "{out}");
        assert!(out.contains("class=\"btn\""), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    /// SECURITY RED CASE 2 (brief obligation 2).
    #[test]
    fn an_href_slot_refuses_every_dangerous_scheme() {
        let html = "<a href=\"/demo\" data-lumen-slot=\"cta\">Book</a>";
        let doc = doc_with(&[]);
        for hostile in [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "java\tscript:alert(1)",
            "  javascript:alert(1)",
            "java\nscript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ] {
            let (out, codes) = run(
                html,
                &slots(vec![("cta", FragmentSlotValue::Text(hostile.to_owned()))]),
                &kinds(&[("cta", FragmentSlotKind::Href)]),
                &doc,
            );
            assert!(!out.to_ascii_lowercase().contains("javascript"), "{out}");
            assert!(!out.to_ascii_lowercase().contains("vbscript"), "{out}");
            assert!(!out.contains("data:text/html"), "{out}");
            assert!(!out.contains("file://"), "{out}");
            // The artifact's own href is the fallback — never a hole, never
            // the hostile value.
            assert!(out.contains("href=\"/demo\""), "{out}");
            assert_eq!(codes, vec!["LUMW0414"], "{hostile}");
        }
    }

    #[test]
    fn an_href_value_is_attribute_escaped() {
        let html = "<a href=\"/demo\" data-lumen-slot=\"cta\">Book</a>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "cta",
                FragmentSlotValue::Text("https://x.test/?a=1&b=2\" onmouseover=\"alert(1)".to_owned()),
            )]),
            &kinds(&[("cta", FragmentSlotKind::Href)]),
            &doc,
        );
        assert!(!out.contains("onmouseover=\"alert"), "{out}");
        assert!(out.contains("&quot;"), "{out}");
        assert!(out.contains("&amp;b=2"), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    // --- image --------------------------------------------------------------

    #[test]
    fn a_bound_image_slot_swaps_the_src_and_drops_the_stale_srcset() {
        let html = "<img data-lumen-slot=\"logo\" src=\"/asset-store/old\" \
                    srcset=\"/asset-store/old 1x, /asset-store/old2 2x\" alt=\"Clone Co\">";
        let doc = doc_with(&[("asset_logo", DIGEST)]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "logo",
                FragmentSlotValue::Asset("asset_logo".to_owned()),
            )]),
            &kinds(&[("logo", FragmentSlotKind::Image)]),
            &doc,
        );
        assert!(out.contains(&format!("src=\"/asset-store/{DIGEST}\"")), "{out}");
        assert!(!out.contains("/asset-store/old"), "{out}");
        assert!(!out.contains("srcset"), "{out}");
        assert!(out.contains("data-lumen-slot=\"logo\""), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn the_other_attributes_of_a_rewritten_tag_survive_as_the_sanitizer_wrote_them() {
        // Rewriting `src` must not quietly re-encode the neighbours. An
        // unescape/re-escape round trip would turn `&nbsp;` into a literal
        // `&amp;nbsp;`, because only the five XML entities survive one.
        let html = "<img data-lumen-slot=\"logo\" src=\"/asset-store/old\" \
                    alt=\"Clone&nbsp;Co &amp; sons &quot;quoted&quot;\" width=\"120\">";
        let doc = doc_with(&[("asset_logo", DIGEST)]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "logo",
                FragmentSlotValue::Asset("asset_logo".to_owned()),
            )]),
            &kinds(&[("logo", FragmentSlotKind::Image)]),
            &doc,
        );
        assert!(codes.is_empty(), "{codes:?}");
        assert!(
            out.contains("alt=\"Clone&nbsp;Co &amp; sons &quot;quoted&quot;\""),
            "{out}"
        );
        assert!(out.contains("width=\"120\""), "{out}");
        assert!(!out.contains("&amp;nbsp;"), "{out}");
    }

    #[test]
    fn an_image_slot_naming_an_asset_the_document_does_not_hold_falls_back() {
        let html = "<img data-lumen-slot=\"logo\" src=\"/asset-store/old\" alt=\"Clone Co\">";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![(
                "logo",
                FragmentSlotValue::Asset("asset_ghost".to_owned()),
            )]),
            &kinds(&[("logo", FragmentSlotKind::Image)]),
            &doc,
        );
        assert_eq!(out, html);
        assert_eq!(codes, vec!["LUMW0415"]);
    }

    // --- visibility ---------------------------------------------------------

    #[test]
    fn a_hidden_slot_takes_its_whole_subtree_with_it() {
        let html = "<section><div data-lumen-slot=\"badge\" class=\"b\">\
                    <span>New</span><img src=\"/asset-store/a\"></div><p>Keep me</p></section>";
        let doc = doc_with(&[]);
        let (hidden, codes) = run(
            html,
            &slots(vec![("badge", FragmentSlotValue::Visible(false))]),
            &kinds(&[("badge", FragmentSlotKind::Visibility)]),
            &doc,
        );
        assert_eq!(hidden, "<section><p>Keep me</p></section>");
        assert!(codes.is_empty(), "{codes:?}");

        // `true` renders exactly as stored — marker included.
        let (shown, codes) = run(
            html,
            &slots(vec![("badge", FragmentSlotValue::Visible(true))]),
            &kinds(&[("badge", FragmentSlotKind::Visibility)]),
            &doc,
        );
        assert_eq!(shown, html);
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_marker_consumed_by_another_slot_is_reported_not_silently_lost() {
        // The reviewer's probe. `slots.py` refuses two slots on ONE element,
        // but a text slot on `h1` and an href slot on `h1 a` is an accepted
        // spec pair — and F2's automatic selector detection is exactly where
        // that shape appears. The inner value cannot be applied (its element
        // is gone with the outer substitution), so the loss is named.
        let html = "<div data-lumen-slot=\"a\">x<span data-lumen-slot=\"b\">y</span></div>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![
                ("a", FragmentSlotValue::Text("A".to_owned())),
                ("b", FragmentSlotValue::Text("B".to_owned())),
            ]),
            &kinds(&[("a", FragmentSlotKind::Text), ("b", FragmentSlotKind::Text)]),
            &doc,
        );
        assert_eq!(out, "<div data-lumen-slot=\"a\">A</div>");
        assert_eq!(codes, vec!["LUMW0417"]);

        let mut diagnostics = Vec::new();
        substitute_fragment_slots(
            html,
            &slots(vec![
                ("a", FragmentSlotValue::Text("A".to_owned())),
                ("b", FragmentSlotValue::Text("B".to_owned())),
            ]),
            &kinds(&[("a", FragmentSlotKind::Text), ("b", FragmentSlotKind::Text)]),
            &doc,
            "/asset-store",
            &NodeId::from("frg_hero"),
            &mut diagnostics,
        );
        // Both keys named: which value was lost, and what consumed it.
        let message = &diagnostics[0].message;
        assert!(message.contains('`') && message.contains("`b`"), "{message}");
        assert!(message.contains("`a`"), "{message}");
        // …and it reads as a sentence. A rejoined line wrap had left a run of
        // literal spaces mid-message in both this string and its hint, which
        // an operator sees verbatim. Cheap to pin, invisible otherwise.
        assert!(!message.contains("  "), "{message}");
        let hint = diagnostics[0].hint.as_deref().unwrap_or_default();
        assert!(!hint.contains("  "), "{hint}");
        assert!(hint.contains("bind the outer slot or the inner one"), "{hint}");
    }

    #[test]
    fn a_marker_inside_a_hidden_subtree_is_reported_the_same_way() {
        let html = "<div data-lumen-slot=\"badge\"><a href=\"/x\" data-lumen-slot=\"cta\">Go</a></div>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![
                ("badge", FragmentSlotValue::Visible(false)),
                ("cta", FragmentSlotValue::Text("https://x.test".to_owned())),
            ]),
            &kinds(&[
                ("badge", FragmentSlotKind::Visibility),
                ("cta", FragmentSlotKind::Href),
            ]),
            &doc,
        );
        assert_eq!(out, "");
        assert_eq!(codes, vec!["LUMW0417"]);
    }

    #[test]
    fn an_unbound_marker_inside_a_consumed_subtree_says_nothing() {
        // Nothing was lost: the inner marker had no value to apply, and it is
        // still present in the artifact, so LUMW0416 must not fire either.
        let html = "<div data-lumen-slot=\"a\">x<span data-lumen-slot=\"b\">y</span></div>";
        let doc = doc_with(&[]);
        let (out, codes) = run(
            html,
            &slots(vec![("a", FragmentSlotValue::Text("A".to_owned()))]),
            &kinds(&[("a", FragmentSlotKind::Text), ("b", FragmentSlotKind::Text)]),
            &doc,
        );
        assert_eq!(out, "<div data-lumen-slot=\"a\">A</div>");
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_void_element_inside_a_replaced_subtree_does_not_swallow_the_page() {
        // `<br>` has no end tag. A depth counter that counts it would never
        // come back, and everything after the marker would vanish.
        let html = "<section><h1 data-lumen-slot=\"headline\">a<br>b</h1><p>after</p></section>";
        let doc = doc_with(&[]);
        let (out, _) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Text("New".to_owned()),
            )]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        assert_eq!(
            out,
            "<section><h1 data-lumen-slot=\"headline\">New</h1><p>after</p></section>"
        );
    }

    #[test]
    fn several_slots_of_different_kinds_apply_in_one_pass() {
        let html = "<section><h1 data-lumen-slot=\"headline\">Care</h1>\
                    <img data-lumen-slot=\"logo\" src=\"/asset-store/old\" alt=\"Clone\">\
                    <a href=\"/x\" data-lumen-slot=\"cta\">Go</a>\
                    <aside data-lumen-slot=\"badge\">Award</aside></section>";
        let doc = doc_with(&[("asset_logo", DIGEST)]);
        let (out, codes) = run(
            html,
            &slots(vec![
                ("headline", FragmentSlotValue::Text("Privia".to_owned())),
                ("logo", FragmentSlotValue::Asset("asset_logo".to_owned())),
                (
                    "cta",
                    FragmentSlotValue::Text("https://privia.test".to_owned()),
                ),
                ("badge", FragmentSlotValue::Visible(false)),
            ]),
            &kinds(&[
                ("headline", FragmentSlotKind::Text),
                ("logo", FragmentSlotKind::Image),
                ("cta", FragmentSlotKind::Href),
                ("badge", FragmentSlotKind::Visibility),
            ]),
            &doc,
        );
        assert!(codes.is_empty(), "{codes:?}");
        assert!(out.contains(">Privia</h1>"), "{out}");
        assert!(out.contains(&format!("src=\"/asset-store/{DIGEST}\"")), "{out}");
        assert!(out.contains("href=\"https://privia.test\""), "{out}");
        assert!(!out.contains("Award"), "{out}");
        assert!(!out.contains("<aside"), "{out}");
        // Every surviving marker is still there: this output is re-derivable.
        for key in ["headline", "logo", "cta"] {
            assert!(out.contains(&format!("data-lumen-slot=\"{key}\"")), "{out}");
        }
    }

    // --- text overrides (R-A6) ----------------------------------------------

    fn over(
        text: &str,
        bold: bool,
        italic: bool,
        underline: bool,
        size: Option<i8>,
    ) -> FragmentTextOverride {
        FragmentTextOverride {
            text: text.to_owned(),
            bold,
            italic,
            underline,
            size,
        }
    }

    fn overrides(
        entries: Vec<(&str, FragmentTextOverride)>,
    ) -> BTreeMap<String, FragmentTextOverride> {
        entries
            .into_iter()
            .map(|(path, value)| (path.to_owned(), value))
            .collect()
    }

    fn run_overrides(
        html: &str,
        overrides: &BTreeMap<String, FragmentTextOverride>,
    ) -> (String, Vec<String>) {
        let mut diagnostics = Vec::new();
        let out = apply_fragment_text_overrides(
            html,
            overrides,
            &NodeId::from("frg_hero"),
            &mut diagnostics,
        );
        let codes = diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code.clone())
            .collect();
        (out, codes)
    }

    #[test]
    fn an_override_replaces_text_and_wraps_marks_and_size() {
        let html = "<section><div><h2 data-lumen-slot=\"headline\">Old <em>words</em></h2>\
                    <p>Body</p></div></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1) > :nth-child(1)",
                over("New & better", true, false, true, Some(1)),
            )]),
        );
        // The element's own attributes first, in source order, then ours; the
        // text is escaped and wrapped outermost-first (`strong > em > u`), and
        // the whole original subtree — the `<em>words</em>` included — is gone.
        assert_eq!(
            out,
            "<section><div><h2 data-lumen-slot=\"headline\" \
             data-lumen-override=\":nth-child(1) &gt; :nth-child(1) &gt; :nth-child(1)\" \
             data-lumen-size=\"1\" style=\"font-size:1.125em\">\
             <strong><u>New &amp; better</u></strong></h2><p>Body</p></div></section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn the_path_origin_is_the_clone_wrapper_not_the_artifact_root() {
        // `render.rs` emits the artifact INSIDE its `data-fragment-root` wrapper,
        // so the wrapper's element children are the stored HTML's top-level
        // elements and a first step names one of those. One step SHORTER than
        // the headline's path therefore names the headline's parent `<div>`, and
        // the override replaces that whole block. This is the same origin the
        // editor bridge counts from and the same one the server-side mirror
        // (`apps/api/lumen_api/fragments/paths.py`) walks — pinned here as a
        // test rather than trusted as a comment.
        let html = "<section><div><h2 data-lumen-slot=\"headline\">Old <em>words</em></h2>\
                    <p>Body</p></div></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("Whole block", false, false, false, None),
            )]),
        );
        assert_eq!(
            out,
            "<section><div data-lumen-override=\":nth-child(1) &gt; :nth-child(1)\">\
             Whole block</div></section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn only_element_children_count_toward_a_path() {
        // Text runs, comments and PIs are not children — the bridge counts
        // `firstElementChild`/`nextElementSibling` and `paths.py` filters the
        // same set. A walk that counted them would address a different element
        // than the one the marketer clicked.
        let html = "<section>lead <!-- note --><h2>First</h2> tail <h3>Second</h3></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(2)",
                over("Second, edited", false, false, false, None),
            )]),
        );
        assert_eq!(
            out,
            "<section>lead <!-- note --><h2>First</h2> tail \
             <h3 data-lumen-override=\":nth-child(1) &gt; :nth-child(2)\">Second, edited</h3>\
             </section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_dead_override_path_leaves_the_element_and_says_so() {
        let html = "<section><p>Body</p></section>";
        let overrides = overrides(vec![(
            ":nth-child(4)",
            over("x", false, false, false, None),
        )]);
        let (out, codes) = run_overrides(html, &overrides);
        assert_eq!(out, html);
        assert_eq!(codes, vec!["LUMW0444"]);

        // The path is named, so an operator can see WHICH edit stopped
        // applying, and the sentence reads as one.
        let mut diagnostics = Vec::new();
        apply_fragment_text_overrides(
            html,
            &overrides,
            &NodeId::from("frg_hero"),
            &mut diagnostics,
        );
        let message = &diagnostics[0].message;
        assert!(message.contains(":nth-child(4)"), "{message}");
        assert!(message.contains("frg_hero"), "{message}");
        assert!(!message.contains("  "), "{message}");
        let hint = diagnostics[0].hint.as_deref().unwrap_or_default();
        assert!(!hint.contains("  "), "{hint}");
    }

    #[test]
    fn an_override_on_a_void_element_is_refused_not_applied() {
        // An `<img>` has no text content, so there is nothing to replace and
        // inventing a container the artifact never had is not the answer.
        for html in [
            "<section><img src=\"/asset-store/a\"><p>Body</p></section>",
            "<section><img src=\"/asset-store/a\"/><p>Body</p></section>",
        ] {
            let (out, codes) = run_overrides(
                html,
                &overrides(vec![(
                    ":nth-child(1) > :nth-child(1)",
                    over("Words", false, false, false, None),
                )]),
            );
            assert_eq!(out, html);
            assert_eq!(codes, vec!["LUMW0444"], "{html}");
        }
    }

    #[test]
    fn an_artifact_with_no_override_is_emitted_byte_for_byte() {
        // The same shape the slot walk is pinned on: a comment, an unclosed
        // void element, a single-quoted attribute, an entity, an uppercase tag.
        let html = "<!-- hero --><SECTION class='hero' data-x=\"a&amp;b\">\
                    <h1 data-lumen-slot=\"headline\">Care &amp; comfort</h1><br>\
                    <img src=\"/asset-store/abc\"></SECTION>";
        let (out, codes) = run_overrides(html, &overrides(vec![]));
        assert_eq!(out, html);
        assert!(codes.is_empty(), "{codes:?}");

        // …and with an override bound elsewhere, everything the walk does not
        // own still copies through unchanged.
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("New", false, false, false, None),
            )]),
        );
        assert!(out.contains("<!-- hero -->"), "{out}");
        assert!(out.contains("data-x=\"a&amp;b\""), "{out}");
        assert!(out.contains("class='hero'"), "{out}");
        assert!(out.contains("<img src=\"/asset-store/abc\">"), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    /// SECURITY RED CASE. An override is written by a human through the
    /// inspector and lands straight on the node: it never meets the sanitizer,
    /// so it is escaped HERE or not at all.
    #[test]
    fn override_text_bound_to_markup_renders_inert() {
        let html = "<section><h2>Care</h2></section>";
        let (out, _) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over(
                    "<script>alert(1)</script><img src=x onerror=alert(2)>",
                    true,
                    false,
                    false,
                    None,
                ),
            )]),
        );
        assert!(!out.contains("<script"), "{out}");
        assert!(!out.contains("<img"), "{out}");
        assert!(
            out.contains(
                "<strong>&lt;script&gt;alert(1)&lt;/script&gt;\
                 &lt;img src=x onerror=alert(2)&gt;</strong>"
            ),
            "{out}"
        );
    }

    #[test]
    fn every_size_step_walks_the_em_ramp() {
        let html = "<section><h2>Old</h2></section>";
        for (step, em) in [
            (-3i8, "0.75"),
            (-2, "0.8125"),
            (-1, "0.875"),
            (0, "1"),
            (1, "1.125"),
            (2, "1.25"),
            (3, "1.5"),
        ] {
            let (out, codes) = run_overrides(
                html,
                &overrides(vec![(
                    ":nth-child(1) > :nth-child(1)",
                    over("New", false, false, false, Some(step)),
                )]),
            );
            assert!(
                out.contains(&format!(
                    "data-lumen-size=\"{step}\" style=\"font-size:{em}em\""
                )),
                "{out}"
            );
            assert!(codes.is_empty(), "{codes:?}");
        }

        // No step at all is no size attribute and no inline style: the
        // artifact's own scale, untouched.
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("New", false, false, false, None),
            )]),
        );
        assert!(!out.contains("data-lumen-size"), "{out}");
        assert!(!out.contains("style="), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_step_outside_the_ramp_renders_without_a_font_size_rather_than_panicking() {
        // Validation refuses -3..=3 at the door (LUMW0443), so this cannot come
        // from a checked write — but a document loaded from storage may never
        // have been validated, and the honest answer is the artifact's own size.
        let html = "<section><h2>Old</h2></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("New", false, false, false, Some(99)),
            )]),
        );
        assert!(!out.contains("font-size"), "{out}");
        assert!(out.contains(">New</h2>"), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn an_existing_style_is_kept_and_the_size_appended_to_it() {
        // The clone's own declaration is what makes it look like the clone. It
        // keeps its source position too, so only the size is new.
        let html = "<section><h2 style=\"color:red\">A</h2><h3 style=\"color:red;\">B</h3>\
                    </section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![
                (
                    ":nth-child(1) > :nth-child(1)",
                    over("A2", false, false, false, Some(1)),
                ),
                (
                    ":nth-child(1) > :nth-child(2)",
                    over("B2", false, false, false, Some(-1)),
                ),
            ]),
        );
        assert!(
            out.contains(
                "<h2 style=\"color:red;font-size:1.125em\" \
                 data-lumen-override=\":nth-child(1) &gt; :nth-child(1)\" \
                 data-lumen-size=\"1\">A2</h2>"
            ),
            "{out}"
        );
        // Already terminated: no second semicolon.
        assert!(
            out.contains(
                "<h3 style=\"color:red;font-size:0.875em\" \
                 data-lumen-override=\":nth-child(1) &gt; :nth-child(2)\" \
                 data-lumen-size=\"-1\">B2</h3>"
            ),
            "{out}"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_void_element_inside_an_overridden_subtree_does_not_swallow_the_page() {
        // `<br>` has no end tag. A depth counter that counted it would never
        // come back down and everything after the edit would vanish.
        let html = "<section><h1>a<br>b</h1><p>after</p></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("New", false, false, false, None),
            )]),
        );
        assert_eq!(
            out,
            "<section><h1 data-lumen-override=\":nth-child(1) &gt; :nth-child(1)\">New</h1>\
             <p>after</p></section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn a_sibling_after_an_overridden_element_still_counts_from_the_right_place() {
        // The walk does not descend into a replaced subtree, so the counter at
        // the element's own depth has to survive the skip intact.
        let html = "<section><h1>a<span>x</span></h1><h2>b</h2><h3>c</h3></section>";
        let (out, codes) = run_overrides(
            html,
            &overrides(vec![
                (
                    ":nth-child(1) > :nth-child(1)",
                    over("A", false, false, false, None),
                ),
                (
                    ":nth-child(1) > :nth-child(3)",
                    over("C", false, false, false, None),
                ),
            ]),
        );
        assert_eq!(
            out,
            "<section><h1 data-lumen-override=\":nth-child(1) &gt; :nth-child(1)\">A</h1>\
             <h2>b</h2>\
             <h3 data-lumen-override=\":nth-child(1) &gt; :nth-child(3)\">C</h3></section>"
        );
        assert!(codes.is_empty(), "{codes:?}");
    }

    #[test]
    fn an_override_wins_over_a_slot_value_on_the_same_element() {
        // Two writers, one element: the agent binds the slot, the marketer
        // overrules it by hand. The override runs on the slot pass's OUTPUT —
        // which is the markup the editor addressed the path against — so the
        // human's words are what remain, and the marker survives so the slot
        // can still be re-bound later.
        let html = "<section><h2 data-lumen-slot=\"headline\">Old</h2></section>";
        let doc = doc_with(&[]);
        let (substituted, codes) = run(
            html,
            &slots(vec![(
                "headline",
                FragmentSlotValue::Text("Slot copy".to_owned()),
            )]),
            &kinds(&[("headline", FragmentSlotKind::Text)]),
            &doc,
        );
        assert!(codes.is_empty(), "{codes:?}");
        assert!(substituted.contains("Slot copy"), "{substituted}");

        let (out, codes) = run_overrides(
            &substituted,
            &overrides(vec![(
                ":nth-child(1) > :nth-child(1)",
                over("Human copy", false, false, false, None),
            )]),
        );
        assert!(out.contains(">Human copy</h2>"), "{out}");
        assert!(!out.contains("Slot copy"), "{out}");
        assert!(out.contains("data-lumen-slot=\"headline\""), "{out}");
        assert!(codes.is_empty(), "{codes:?}");
    }
}
