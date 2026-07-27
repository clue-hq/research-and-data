//! Constrained-HTML ingestion: the agent's wire format → the node tree.
//!
//! The parser IS the vocabulary validator. The agent authors a closed
//! element set (`section/header/footer`, `div`, `h1-h4/p/span`,
//! `a[data-button]`, `img[data-asset]`, `i[data-icon]`) with theme-token
//! classes; anything outside the contract becomes a structured `LUMW01xx`
//! diagnostic for the author-retry loop, never a silent drop. Any Error
//! diagnostic blocks the whole ingest — the document is only ever mutated by
//! markup that parsed clean.

use crate::classes::{lint_classes, ClassLintContext};
use crate::doc::{
    ButtonVariant, SectionTag, TextVariant, WebDoc, WebNode, WebNodeKind, MAX_TREE_DEPTH,
};
use crate::inline::sanitize_inline;
use crate::theme::WebTheme;
use crate::util::{href_is_allowed, line_col, normalize_entities, self_close_voids};
use lumen_core::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, NodeId, PageId, Phase};
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use std::collections::BTreeSet;

const ROOT_WRAPPER: &str = "lumen-root";

#[derive(Clone, Debug, Default)]
pub struct IngestOutcome {
    /// Completed nodes (children listed before their parents).
    pub nodes: Vec<WebNode>,
    /// Top-level node ids in document order; each must be a Section.
    pub roots: Vec<NodeId>,
    pub diagnostics: Vec<Diagnostic>,
}

impl IngestOutcome {
    pub fn has_errors(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    }
}

/// A branch (Section/Container) currently open on the parse stack.
struct BranchFrame {
    node: WebNode,
    tag_name: String,
}

/// Inline capture for Text/Button: raw inner markup is sliced by byte offset
/// once the matching end tag arrives, then sanitized.
struct CaptureFrame {
    tag_name: String,
    start_offset: usize,
    nested_depth: usize,
    pending: PendingLeaf,
}

enum PendingLeaf {
    Text {
        id: NodeId,
        variant: TextVariant,
        classes: String,
        name: Option<String>,
    },
    Button {
        id: NodeId,
        href: String,
        variant: ButtonVariant,
        new_tab: bool,
        classes: String,
        name: Option<String>,
    },
    /// Swallow inner content without producing a node (script bodies,
    /// stray labels inside icon elements).
    Discard { warn_if_content: bool },
}

struct IngestState<'a> {
    theme: &'a WebTheme,
    source: &'a str,
    nodes: Vec<WebNode>,
    roots: Vec<NodeId>,
    diagnostics: Vec<Diagnostic>,
    branch_stack: Vec<BranchFrame>,
    capture: Option<CaptureFrame>,
    used_ids: BTreeSet<String>,
    auto_counter: usize,
}

pub fn ingest_html(html: &str, theme: &WebTheme) -> IngestOutcome {
    let normalized = self_close_voids(&normalize_entities(html));
    let wrapped = format!("<{ROOT_WRAPPER}>{normalized}</{ROOT_WRAPPER}>");

    let mut reader = Reader::from_str(&wrapped);
    reader.config_mut().trim_text(false);

    let mut state = IngestState {
        theme,
        source: &wrapped,
        nodes: Vec::new(),
        roots: Vec::new(),
        diagnostics: Vec::new(),
        branch_stack: Vec::new(),
        capture: None,
        used_ids: BTreeSet::new(),
        auto_counter: 0,
    };

    loop {
        let pos_before = reader.buffer_position() as usize;
        match reader.read_event() {
            Ok(Event::Start(start)) => state.on_start(&start, false, &reader),
            Ok(Event::Empty(start)) => state.on_start(&start, true, &reader),
            Ok(Event::End(end)) => {
                let name = String::from_utf8_lossy(end.name().as_ref()).to_lowercase();
                state.on_end(&name, pos_before);
            }
            Ok(Event::Text(text)) => {
                if state.capture.is_none() {
                    let content = text.unescape().map(|value| value.into_owned()).unwrap_or_default();
                    if !content.trim().is_empty() {
                        let (line, _) = line_col(state.source, pos_before);
                        state.diagnostics.push(
                            Diagnostic::error(
                                Phase::Web,
                                "LUMW0117",
                                format!(
                                    "loose text outside a text element near line {line}: {:?}",
                                    content.trim().chars().take(40).collect::<String>()
                                ),
                                None,
                            )
                            .with_hint("Wrap copy in <p>, <h1>-<h4>, or <span data-variant=…>."),
                        );
                    }
                }
            }
            Ok(Event::CData(_)) | Ok(Event::Comment(_)) | Ok(Event::Decl(_)) | Ok(Event::PI(_))
            | Ok(Event::DocType(_)) => {}
            Ok(Event::Eof) => break,
            Err(err) => {
                let error_pos = reader.buffer_position() as usize;
                let (line, col) = line_col(&wrapped, error_pos.min(wrapped.len()));
                state.diagnostics.push(
                    Diagnostic::error(
                        Phase::Web,
                        "LUMW0100",
                        format!("markup does not parse near line {line}, column {col}: {err}"),
                        None,
                    )
                    .with_hint(
                        "Author well-formed markup: close every tag, quote every attribute. \
                         Void elements (<img>, <br>) may stay unclosed.",
                    ),
                );
                return IngestOutcome {
                    nodes: Vec::new(),
                    roots: Vec::new(),
                    diagnostics: state.diagnostics,
                };
            }
        }
    }

    if state.has_error() {
        // Errors invalidate the whole batch: the tree is only built from
        // clean markup, so a retry never merges with half-ingested output.
        return IngestOutcome {
            nodes: Vec::new(),
            roots: Vec::new(),
            diagnostics: state.diagnostics,
        };
    }

    IngestOutcome {
        nodes: state.nodes,
        roots: state.roots,
        diagnostics: state.diagnostics,
    }
}

/// Ingest authored HTML and replace `page_id`'s content with the result.
/// On any Error diagnostic (including unresolved `data-asset` references)
/// the document is left untouched.
pub fn ingest_html_into_page(
    doc: &mut WebDoc,
    page_id: &PageId,
    html: &str,
    theme: &WebTheme,
) -> IngestOutcome {
    let mut outcome = ingest_html(html, theme);
    for node in &outcome.nodes {
        if let WebNodeKind::Image { asset_id, .. } = &node.kind {
            if !doc.assets.contains_key(asset_id) {
                outcome.diagnostics.push(
                    Diagnostic::error(
                        Phase::Web,
                        "LUMW0120",
                        format!(
                            "image node `{}` references unknown asset `{}`",
                            node.id, asset_id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Generate or import the asset first (asset tool / import_external_image), \
                         then reference its id via data-asset.",
                    ),
                );
            }
        }
    }
    if outcome.has_errors() {
        return outcome;
    }
    let Some(page) = doc.page_mut(page_id) else {
        outcome.diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0121",
            format!("page `{page_id}` does not exist"),
            None,
        ));
        return outcome;
    };
    let root_id = page.root.clone();
    let Some(mut root) = page.nodes.get(&root_id).cloned() else {
        outcome.diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0122",
            format!("page `{page_id}` root node `{root_id}` is missing"),
            Some(DiagnosticSubject::Node(root_id.clone())),
        ));
        return outcome;
    };
    page.nodes.clear();
    root.children = outcome.roots.clone();
    page.nodes.insert(root_id, root);
    for node in &outcome.nodes {
        page.nodes.insert(node.id.clone(), node.clone());
    }
    outcome
}

impl<'a> IngestState<'a> {
    fn has_error(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    }

    fn error(&mut self, code: &str, message: String, hint: &str, node: Option<&NodeId>) {
        let mut diagnostic = Diagnostic::error(
            Phase::Web,
            code,
            message,
            node.map(|id| DiagnosticSubject::Node(id.clone())),
        );
        if !hint.is_empty() {
            diagnostic = diagnostic.with_hint(hint);
        }
        self.diagnostics.push(diagnostic);
    }

    fn warning(&mut self, code: &str, message: String, hint: &str, node: Option<&NodeId>) {
        let mut diagnostic = Diagnostic::warning(
            Phase::Web,
            code,
            message,
            node.map(|id| DiagnosticSubject::Node(id.clone())),
        );
        if !hint.is_empty() {
            diagnostic = diagnostic.with_hint(hint);
        }
        self.diagnostics.push(diagnostic);
    }

    fn on_start(&mut self, start: &BytesStart<'_>, is_empty: bool, reader: &Reader<&[u8]>) {
        let name = String::from_utf8_lossy(start.name().as_ref()).to_lowercase();
        if name == ROOT_WRAPPER {
            return;
        }
        if let Some(capture) = &mut self.capture {
            // Inside a text/button: content is captured verbatim and later
            // sanitized; only track nesting so we find the real end tag.
            if !is_empty {
                capture.nested_depth += 1;
            }
            return;
        }

        let attrs = read_attrs(start);
        for (key, _) in &attrs {
            if key.starts_with("on") {
                self.error(
                    "LUMW0103",
                    format!("<{name}> carries event handler attribute `{key}`"),
                    "Event handlers are not part of the vocabulary; interactivity comes from the platform.",
                    None,
                );
                continue;
            }
            // Nothing outside the vocabulary is ever dropped silently: an
            // ignored attribute (style= especially) would otherwise change
            // the page invisibly and starve the author-retry loop of signal.
            let known = matches!(
                key.as_str(),
                "id" | "class"
                    | "href"
                    | "target"
                    | "alt"
                    | "src"
                    | "data-name"
                    | "data-variant"
                    | "data-button"
                    | "data-icon"
                    | "data-asset"
                    | "data-href"
                    | "data-new-tab"
            );
            if !known {
                let hint = if key == "style" {
                    "Inline style attributes are not supported; express styling as utility \
                     classes (page-level effects belong in custom_css)."
                } else {
                    "Recognized attributes: id class href target alt data-variant data-button \
                     data-icon data-asset data-href data-new-tab data-name."
                };
                self.warning(
                    "LUMW0132",
                    format!("attribute `{key}` on <{name}> is not in the vocabulary; ignored"),
                    hint,
                    None,
                );
            }
        }
        if name == "script" || name == "style" {
            self.error(
                "LUMW0101",
                format!("<{name}> is not allowed in authored markup"),
                "Page-level CSS belongs in custom_css; scripts are never authored.",
                None,
            );
            if !is_empty {
                // Consume the body so its text isn't also reported as loose.
                self.capture = Some(CaptureFrame {
                    tag_name: name,
                    start_offset: reader.buffer_position() as usize,
                    nested_depth: 0,
                    pending: PendingLeaf::Discard {
                        warn_if_content: false,
                    },
                });
            }
            return;
        }

        let depth = self.branch_stack.len();
        if depth >= MAX_TREE_DEPTH {
            self.error(
                "LUMW0116",
                format!("<{name}> exceeds the maximum tree depth of {MAX_TREE_DEPTH}"),
                "Flatten the structure; deep nesting is almost always accidental.",
                None,
            );
            return;
        }

        match name.as_str() {
            "section" | "header" | "footer" => {
                if depth > 0 {
                    self.error(
                        "LUMW0102",
                        format!("<{name}> must be a top-level element"),
                        "Sections are the page's top-level bands; use <div> containers inside them.",
                        None,
                    );
                }
                let tag = match name.as_str() {
                    "header" => SectionTag::Header,
                    "footer" => SectionTag::Footer,
                    _ => SectionTag::Section,
                };
                let explicit_id = attrs_get(&attrs, "id");
                let id = self.mint_id("sec", explicit_id.as_deref());
                let anchor_id = explicit_id;
                let node = WebNode {
                    id: id.clone(),
                    kind: WebNodeKind::Section { tag, anchor_id },
                    classes: self.take_classes(&attrs, &id),
                    children: Vec::new(),
                    name: attrs_get(&attrs, "data-name"),
                    slot_key: None,
                };
                if is_empty {
                    self.finish_node(node);
                } else {
                    self.branch_stack.push(BranchFrame { node, tag_name: name });
                }
            }
            "div" => {
                let id = self.mint_id("box", attrs_get(&attrs, "id").as_deref());
                let node = WebNode {
                    id: id.clone(),
                    kind: WebNodeKind::Container,
                    classes: self.take_classes(&attrs, &id),
                    children: Vec::new(),
                    name: attrs_get(&attrs, "data-name"),
                    slot_key: None,
                };
                if is_empty {
                    self.finish_node(node);
                } else {
                    self.branch_stack.push(BranchFrame { node, tag_name: name });
                }
            }
            "h1" | "h2" | "h3" | "h4" | "p" | "span" | "i" => {
                if attrs_get(&attrs, "data-icon").is_some() || name == "i" {
                    self.start_icon(&name, &attrs);
                    if !is_empty {
                        // Icon elements should be empty; swallow any label.
                        self.capture = Some(CaptureFrame {
                            tag_name: name,
                            start_offset: reader.buffer_position() as usize,
                            nested_depth: 0,
                            pending: PendingLeaf::Discard {
                                warn_if_content: true,
                            },
                        });
                    }
                    return;
                }
                let default_variant = match name.as_str() {
                    "h1" => TextVariant::H1,
                    "h2" => TextVariant::H2,
                    "h3" => TextVariant::H3,
                    "h4" => TextVariant::H4,
                    _ => TextVariant::Body,
                };
                let variant = match attrs_get(&attrs, "data-variant") {
                    Some(value) => match TextVariant::parse(&value) {
                        Some(parsed) => parsed,
                        None => {
                            self.warning(
                                "LUMW0119",
                                format!("unknown data-variant `{value}` on <{name}>"),
                                "Valid: display h1 h2 h3 h4 body small overline.",
                                None,
                            );
                            default_variant
                        }
                    },
                    None => default_variant,
                };
                let id = self.mint_id("txt", attrs_get(&attrs, "id").as_deref());
                let classes = self.take_classes(&attrs, &id);
                let node_name = attrs_get(&attrs, "data-name");
                if is_empty {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Text {
                            variant,
                            content: String::new(),
                        },
                        classes,
                        children: Vec::new(),
                        name: node_name,
                        slot_key: None,
                    });
                } else {
                    self.capture = Some(CaptureFrame {
                        tag_name: name,
                        start_offset: reader.buffer_position() as usize,
                        nested_depth: 0,
                        pending: PendingLeaf::Text {
                            id,
                            variant,
                            classes,
                            name: node_name,
                        },
                    });
                }
            }
            "a" => {
                let Some(button_value) = attrs_get(&attrs, "data-button") else {
                    self.error(
                        "LUMW0109",
                        "bare <a> at block level".to_owned(),
                        "CTAs are <a data-button=\"primary|secondary|…\">; inline links live inside text content.",
                        None,
                    );
                    return;
                };
                let variant = match ButtonVariant::parse(&button_value) {
                    Some(parsed) => parsed,
                    None => {
                        self.warning(
                            "LUMW0106",
                            format!("unknown data-button variant `{button_value}`; using primary"),
                            "Valid: primary secondary outline ghost link.",
                            None,
                        );
                        ButtonVariant::Primary
                    }
                };
                let id = self.mint_id("btn", attrs_get(&attrs, "id").as_deref());
                let href = attrs_get(&attrs, "href").unwrap_or_default();
                if href.trim().is_empty() {
                    self.error(
                        "LUMW0107",
                        format!("button `{id}` has no href"),
                        "Every CTA needs a real target; fetch the site rather than guessing paths.",
                        Some(&id),
                    );
                } else if !href_is_allowed(&href) {
                    self.error(
                        "LUMW0108",
                        format!("button `{id}` href has a disallowed scheme: {href}"),
                        "Allowed: https:// http:// mailto: tel: #anchor /path.",
                        Some(&id),
                    );
                }
                let new_tab = attrs_get(&attrs, "target").as_deref() == Some("_blank");
                let classes = self.take_classes(&attrs, &id);
                let node_name = attrs_get(&attrs, "data-name");
                if is_empty {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Button {
                            label: String::new(),
                            href,
                            variant,
                            new_tab,
                        },
                        classes,
                        children: Vec::new(),
                        name: node_name,
                        slot_key: None,
                    });
                } else {
                    self.capture = Some(CaptureFrame {
                        tag_name: name,
                        start_offset: reader.buffer_position() as usize,
                        nested_depth: 0,
                        pending: PendingLeaf::Button {
                            id,
                            href,
                            variant,
                            new_tab,
                            classes,
                            name: node_name,
                        },
                    });
                }
            }
            "img" => {
                let id = self.mint_id("img", attrs_get(&attrs, "id").as_deref());
                let asset_attr = attrs_get(&attrs, "data-asset");
                let src = attrs_get(&attrs, "src");
                let asset_id = match asset_attr {
                    Some(value) => match lumen_core::AssetId::new(value.clone()) {
                        Ok(asset_id) => Some(asset_id),
                        Err(_) => {
                            self.error(
                                "LUMW0112",
                                format!("invalid data-asset id `{value}` on image `{id}`"),
                                "Asset ids are alphanumeric with _ or -.",
                                Some(&id),
                            );
                            None
                        }
                    },
                    None => {
                        if let Some(src_value) = &src {
                            if src_value.starts_with("http://") || src_value.starts_with("https://")
                            {
                                self.error(
                                    "LUMW0110",
                                    format!("image `{id}` uses an external src: {src_value}"),
                                    "External images must be rehosted: import_external_image(url) → data-asset.",
                                    Some(&id),
                                );
                            } else {
                                self.error(
                                    "LUMW0111",
                                    format!("image `{id}` has no data-asset reference"),
                                    "Reference an ingested asset: <img data-asset=\"asset_id\" alt=\"…\">.",
                                    Some(&id),
                                );
                            }
                        } else {
                            self.error(
                                "LUMW0111",
                                format!("image `{id}` has no data-asset reference"),
                                "Reference an ingested asset: <img data-asset=\"asset_id\" alt=\"…\">.",
                                Some(&id),
                            );
                        }
                        None
                    }
                };
                let alt = match attrs_get(&attrs, "alt") {
                    Some(alt) if !alt.trim().is_empty() => alt,
                    _ => {
                        self.warning(
                            "LUMW0113",
                            format!("image `{id}` has no alt text"),
                            "Describe the image for screen readers; decorative images may use alt=\"\".",
                            Some(&id),
                        );
                        String::new()
                    }
                };
                let href = match attrs_get(&attrs, "data-href") {
                    Some(value) if href_is_allowed(&value) => Some(value),
                    Some(value) => {
                        self.warning(
                            "LUMW0108",
                            format!("image `{id}` data-href has a disallowed scheme; dropped: {value}"),
                            "Allowed: https:// http:// mailto: tel: #anchor /path.",
                            Some(&id),
                        );
                        None
                    }
                    None => None,
                };
                let new_tab = attrs_get(&attrs, "data-new-tab").as_deref() == Some("true");
                let classes = self.take_classes(&attrs, &id);
                if let Some(asset_id) = asset_id {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Image {
                            asset_id,
                            alt,
                            href,
                            new_tab,
                        },
                        classes,
                        children: Vec::new(),
                        name: attrs_get(&attrs, "data-name"),
                        slot_key: None,
                    });
                }
            }
            other => {
                let hint = match other {
                    "nav" => "Use a <header> section with <div> containers and text links inside text nodes.",
                    "ul" | "ol" | "li" => "Lists are built from <div> containers with text nodes.",
                    "button" => "Use <a data-button=\"primary\" href=\"…\">.",
                    "main" | "body" | "html" => "Author sections at the top level; the page shell is rendered for you.",
                    _ => "Vocabulary: section header footer div h1-h4 p span a[data-button] img[data-asset] i[data-icon].",
                };
                self.error(
                    "LUMW0105",
                    format!("<{other}> is not in the web vocabulary"),
                    hint,
                    None,
                );
            }
        }
    }

    fn start_icon(&mut self, element: &str, attrs: &[(String, String)]) {
        let Some(icon_name) = attrs_get(attrs, "data-icon") else {
            self.error(
                "LUMW0105",
                format!("<{element}> without data-icon is not in the web vocabulary"),
                "Icons are <i data-icon=\"name\"></i>; italics inside text use <em>.",
                None,
            );
            return;
        };
        let id = self.mint_id("ico", attrs_get(attrs, "id").as_deref());
        if lumen_core::icons::resolve_icon(&icon_name).is_none() {
            let known = lumen_core::icons::icon_names().join(", ");
            self.error(
                "LUMW0114",
                format!("unknown icon `{icon_name}` on `{id}`"),
                &format!("Known icons: {known}."),
                Some(&id),
            );
            return;
        }
        let classes = self.take_classes(attrs, &id);
        self.finish_node(WebNode {
            id: id.clone(),
            kind: WebNodeKind::Icon { icon: icon_name },
            classes,
            children: Vec::new(),
            name: attrs_get(attrs, "data-name"),
            slot_key: None,
        });
    }

    fn on_end(&mut self, name: &str, pos_before: usize) {
        if name == ROOT_WRAPPER {
            return;
        }
        if let Some(capture) = &mut self.capture {
            if capture.nested_depth > 0 {
                // This end tag closes an element nested inside the capture.
                capture.nested_depth -= 1;
                return;
            }
            if capture.tag_name != name {
                // Unreachable with check_end_names on; ignore defensively.
                return;
            }
            let capture = self.capture.take().expect("capture present");
            let inner = &self.source[capture.start_offset..pos_before.min(self.source.len())];
            if let PendingLeaf::Discard { warn_if_content } = &capture.pending {
                if *warn_if_content && !inner.trim().is_empty() {
                    self.warning(
                        "LUMW0131",
                        format!("content inside an icon element is ignored: {:?}", inner.trim()),
                        "Icon elements must be empty: <i data-icon=\"name\"></i>.",
                        None,
                    );
                }
                return;
            }
            let sanitized = sanitize_inline(inner);
            for note in &sanitized.removed {
                let subject = match &capture.pending {
                    PendingLeaf::Text { id, .. } | PendingLeaf::Button { id, .. } => id.clone(),
                    PendingLeaf::Discard { .. } => unreachable!("discard handled above"),
                };
                self.warning(
                    "LUMW0130",
                    format!("inline content adjusted in `{subject}`: {note}"),
                    "Allowed inline markup: strong em u s a br span[class].",
                    Some(&subject),
                );
            }
            match capture.pending {
                PendingLeaf::Text { id, variant, classes, name } => {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Text {
                            variant,
                            content: sanitized.html,
                        },
                        classes,
                        children: Vec::new(),
                        name,
                        slot_key: None,
                    });
                }
                PendingLeaf::Button { id, href, variant, new_tab, classes, name } => {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Button {
                            label: sanitized.html,
                            href,
                            variant,
                            new_tab,
                        },
                        classes,
                        children: Vec::new(),
                        name,
                        slot_key: None,
                    });
                }
                PendingLeaf::Discard { .. } => unreachable!("discard handled above"),
            }
            return;
        }
        // End tags of rejected (never-opened) elements have no frame; only
        // pop when the names line up. Their error already voided the batch.
        let matches_top = self
            .branch_stack
            .last()
            .map(|frame| frame.tag_name == name)
            .unwrap_or(false);
        if matches_top {
            let frame = self.branch_stack.pop().expect("checked above");
            self.finish_node(frame.node);
        }
    }

    /// Attach a completed node to the open branch (or the page top level).
    fn finish_node(&mut self, node: WebNode) {
        let id = node.id.clone();
        let is_section = matches!(node.kind, WebNodeKind::Section { .. });
        if let Some(parent) = self.branch_stack.last_mut() {
            parent.node.children.push(id);
            self.nodes.push(node);
            return;
        }
        if !is_section {
            self.error(
                "LUMW0102",
                format!(
                    "top-level <{}> is not a section",
                    node.kind.kind_name()
                ),
                "Every top-level element must be <section>, <header>, or <footer>.",
                Some(&id),
            );
        }
        self.roots.push(id);
        self.nodes.push(node);
    }

    fn take_classes(&mut self, attrs: &[(String, String)], node_id: &NodeId) -> String {
        let classes = attrs_get(attrs, "class").unwrap_or_default();
        if !classes.is_empty() {
            let lint = lint_classes(
                &classes,
                Some(node_id),
                &ClassLintContext {
                    color_tokens: &self.theme.tokens,
                },
            );
            self.diagnostics.extend(lint);
        }
        classes
    }

    fn mint_id(&mut self, prefix: &str, explicit: Option<&str>) -> NodeId {
        if let Some(value) = explicit {
            match NodeId::new(value) {
                Ok(id) => {
                    if self.used_ids.insert(value.to_owned()) {
                        return id;
                    }
                    self.error(
                        "LUMW0115",
                        format!("duplicate id `{value}`"),
                        "Element ids must be unique across the page.",
                        Some(&id),
                    );
                    // Fall through to an auto id so parsing can continue.
                }
                Err(_) => {
                    self.error(
                        "LUMW0104",
                        format!("invalid id `{value}`"),
                        "Ids are alphanumeric with _ or - (e.g. id=\"sec_hero\").",
                        None,
                    );
                }
            }
        }
        loop {
            self.auto_counter += 1;
            let candidate = format!("{prefix}_{}", self.auto_counter);
            if self.used_ids.insert(candidate.clone()) {
                return NodeId::from(candidate);
            }
        }
    }
}

fn read_attrs(start: &BytesStart<'_>) -> Vec<(String, String)> {
    start
        .attributes()
        .with_checks(false)
        .flatten()
        .map(|attr| {
            let key = String::from_utf8_lossy(attr.key.as_ref()).to_lowercase();
            let value = attr
                .unescape_value()
                .map(|value| value.into_owned())
                .unwrap_or_else(|_| String::from_utf8_lossy(&attr.value).into_owned());
            (key, value)
        })
        .collect()
}

fn attrs_get(attrs: &[(String, String)], key: &str) -> Option<String> {
    attrs
        .iter()
        .find(|(candidate, _)| candidate == key)
        .map(|(_, value)| value.clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::WebThemeRef;
    use crate::theme::{compile_web_theme, WebThemeOptions};

    fn theme() -> WebTheme {
        compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default()).0
    }

    const GOOD_PAGE: &str = r##"
<header id="site_header" class="bg-light border-b border-border">
  <div class="flex items-center justify-between px-6 py-4 max-w-[1200px] mx-auto">
    <p data-variant="overline" class="text-primary">Insight Health</p>
    <a data-button="primary" href="https://insighthealth.ai/demo">Book a demo</a>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="max-w-[1200px] mx-auto px-6 py-24 flex flex-col gap-6">
    <h1 data-variant="display">AI scribing that <span class="text-primary">clinicians trust</span></h1>
    <p class="text-muted max-w-[640px]">Documentation that writes itself.</p>
    <div class="flex gap-4">
      <a data-button="primary" href="https://insighthealth.ai/demo">Book a demo</a>
      <a data-button="ghost" href="#how-it-works">See how it works</a>
    </div>
    <i data-icon="sparkles" class="text-primary"></i>
  </div>
</section>
"##;

    #[test]
    fn clean_page_ingests_without_errors() {
        let outcome = ingest_html(GOOD_PAGE, &theme());
        assert!(!outcome.has_errors(), "diagnostics: {:#?}", outcome.diagnostics);
        assert_eq!(outcome.roots.len(), 2);
        let header = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "site_header")
            .unwrap();
        assert!(matches!(
            header.kind,
            WebNodeKind::Section { tag: SectionTag::Header, .. }
        ));
        let hero_heading = outcome
            .nodes
            .iter()
            .find(|node| matches!(&node.kind, WebNodeKind::Text { variant: TextVariant::Display, .. }))
            .unwrap();
        if let WebNodeKind::Text { content, .. } = &hero_heading.kind {
            assert!(content.contains("<span class=\"text-primary\">clinicians trust</span>"));
        }
        assert!(outcome
            .nodes
            .iter()
            .any(|node| matches!(&node.kind, WebNodeKind::Icon { icon } if icon == "sparkles")));
    }

    #[test]
    fn raw_hex_class_blocks_the_batch() {
        let html = r#"<section id="s1"><div class="bg-[#ff0000]"><p>x</p></div></section>"#;
        let outcome = ingest_html(html, &theme());
        assert!(outcome.has_errors());
        assert!(outcome.nodes.is_empty());
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0210"));
    }

    #[test]
    fn script_and_external_img_are_rejected() {
        let html = r#"<section id="s1"><script>alert(1)</script><img src="https://x.com/a.png" alt="a"></section>"#;
        let outcome = ingest_html(html, &theme());
        let codes: Vec<&str> = outcome
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code.as_str())
            .collect();
        assert!(codes.contains(&"LUMW0101"), "codes: {codes:?}");
        assert!(codes.contains(&"LUMW0110"), "codes: {codes:?}");
    }

    #[test]
    fn top_level_div_is_rejected() {
        let outcome = ingest_html(r#"<div class="flex"><p>x</p></div>"#, &theme());
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0102"));
    }

    #[test]
    fn unknown_element_gets_vocabulary_hint() {
        let outcome = ingest_html(r#"<section id="s"><ul><li>x</li></ul></section>"#, &theme());
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0105"));
    }

    #[test]
    fn malformed_markup_reports_parse_error() {
        let outcome = ingest_html("<section id=\"s\"><div><p>x</div></section>", &theme());
        assert!(outcome.has_errors());
        assert_eq!(outcome.diagnostics[0].code, "LUMW0100");
    }

    #[test]
    fn button_requires_real_href() {
        let outcome = ingest_html(
            r#"<section id="s"><a data-button="primary">No link</a></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0107"));
    }

    #[test]
    fn unknown_attributes_warn_instead_of_vanishing() {
        let outcome = ingest_html(
            r#"<section id="s"><p style="color:red" data-mystery="1">x</p></section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors());
        let warnings: Vec<&str> = outcome
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "LUMW0132")
            .map(|diagnostic| diagnostic.message.as_str())
            .collect();
        assert_eq!(warnings.len(), 2, "{:#?}", outcome.diagnostics);
        assert!(warnings.iter().any(|message| message.contains("`style`")));
    }

    #[test]
    fn duplicate_ids_are_rejected() {
        let outcome = ingest_html(
            r#"<section id="a"><p id="x">1</p><p id="x">2</p></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0115"));
    }

    #[test]
    fn ingest_into_page_replaces_content_only_when_clean() {
        let mut doc = WebDoc::new("d1", "Site", None);
        let theme = theme();
        let outcome = ingest_html_into_page(&mut doc, &PageId::from("home"), GOOD_PAGE, &theme);
        assert!(!outcome.has_errors());
        let page = doc.page(&PageId::from("home")).unwrap();
        let root = page.node(&page.root).unwrap();
        assert_eq!(root.children.len(), 2);
        assert!(page.nodes.len() > 5);

        // A failing ingest must leave the document untouched.
        let before = doc.clone();
        let bad = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="s"><img data-asset="missing_asset" alt="x"></section>"#,
            &theme,
        );
        assert!(bad.has_errors());
        assert!(bad
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0120"));
        assert_eq!(doc, before);
    }

    #[test]
    fn unclosed_void_and_entities_are_tolerated() {
        let mut doc = WebDoc::new("d1", "Site", None);
        // Seed an asset so the reference resolves.
        let record: lumen_core::AssetRecord = serde_json::from_value(serde_json::json!({
            "id": "logo_1",
            "label": "Logo",
            "kind": "logo",
            "status": "ready",
            "source": {"kind": "generated", "model": "test-model", "request_id": null},
        }))
        .unwrap_or_else(|_| panic!("asset record fixture"));
        doc.assets.insert(lumen_core::AssetId::from("logo_1"), record);
        let theme = theme();
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="s"><p>Fast&nbsp;&amp; safe&mdash;always</p><img data-asset="logo_1" alt="logo"></section>"#,
            &theme,
        );
        assert!(!outcome.has_errors(), "diagnostics: {:#?}", outcome.diagnostics);
    }
}
