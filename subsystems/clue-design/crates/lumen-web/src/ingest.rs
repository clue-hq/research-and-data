//! Constrained-HTML ingestion: the agent's wire format → the node tree.
//!
//! The parser IS the vocabulary validator. The agent authors a closed
//! element set (`section/header/footer`, `div`, `h1-h4/p/span`,
//! `a[data-button]`, `img[data-asset]`, `i[data-icon]`) with theme-token
//! classes; anything outside the contract becomes a structured `LUMW01xx`
//! diagnostic for the author-retry loop, never a silent drop. Any Error
//! diagnostic blocks the whole ingest — the document is only ever mutated by
//! markup that parsed clean.

use crate::classes::{extend_deduping_advice, lint_classes, ClassLintContext};
use crate::derive::{personalization_key_is_valid, WHEN_PREFIX};
use crate::doc::{
    calendly_url_is_valid, ButtonAction, ButtonCommand, ButtonVariant, ComponentSpec,
    EmbedProvider, MarqueeDirection, SectionTag, TextVariant, WebBackgroundFit, WebBackgroundImage,
    WebBackgroundPosition, WebBackgroundScrim, WebDoc, WebNode, WebNodeKind, WebScrimColor,
    MAX_TREE_DEPTH,
};
use crate::inline::sanitize_inline;
use crate::rich_text::RichTextDocument;
use crate::theme::WebTheme;
use crate::util::{href_is_allowed, line_col, normalize_entities, self_close_voids};
use lumen_core::{
    Diagnostic, DiagnosticSeverity, DiagnosticSubject, NodeId, PageId, Phase, SlotKey,
};
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
        slot_key: Option<SlotKey>,
        structured: bool,
    },
    Button {
        id: NodeId,
        action: ButtonAction,
        variant: ButtonVariant,
        classes: String,
        name: Option<String>,
        slot_key: Option<SlotKey>,
    },
    /// Swallow inner content without producing a node (script bodies,
    /// stray labels inside icon/embed elements).
    Discard {
        warn_if_content: bool,
        /// Which element the swallowed content sat inside — selects the
        /// warning's wording (icon vs embed). Unused when `warn_if_content`
        /// is false (script/style bodies).
        context: DiscardContext,
    },
}

/// The element a `Discard` frame is swallowing content from; picks the
/// LUMW0131 warning wording.
#[derive(Clone, Copy)]
enum DiscardContext {
    Icon,
    Embed,
}

impl DiscardContext {
    fn message(self, inner: &str) -> String {
        match self {
            DiscardContext::Icon => {
                format!("content inside an icon element is ignored: {inner:?}")
            }
            DiscardContext::Embed => {
                format!("content inside an embed element is ignored: {inner:?}")
            }
        }
    }

    fn hint(self) -> &'static str {
        match self {
            DiscardContext::Icon => "Icon elements must be empty: <i data-icon=\"name\"></i>.",
            DiscardContext::Embed => {
                "Embed elements are empty: <div data-embed=\"calendly\" data-url=\"https://calendly.com/…\"></div>."
            }
        }
    }
}

/// Ingest knobs the caller knows and the parser does not.
///
/// Kept as a struct (rather than more parameters) so the pre-existing
/// `ingest_html` / `ingest_html_into_page` signatures stay exactly as they
/// were: everything that does not know about briefs keeps calling them.
#[derive(Clone, Copy, Debug, Default)]
pub struct IngestOptions {
    /// The pinned brand kit carries a Creative Brief. See
    /// `ClassLintContext::briefed` — the only thing this changes is whether the
    /// class lint may emit LUMW0306 advice.
    pub briefed: bool,
}

struct IngestState<'a> {
    theme: &'a WebTheme,
    options: IngestOptions,
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
    ingest_html_with(html, theme, IngestOptions::default())
}

pub fn ingest_html_with(
    html: &str,
    theme: &WebTheme,
    options: IngestOptions,
) -> IngestOutcome {
    let normalized = self_close_voids(&normalize_entities(html));
    let wrapped = format!("<{ROOT_WRAPPER}>{normalized}</{ROOT_WRAPPER}>");

    let mut reader = Reader::from_str(&wrapped);
    reader.config_mut().trim_text(false);

    let mut state = IngestState {
        theme,
        options,
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
                    let content = text
                        .unescape()
                        .map(|value| value.into_owned())
                        .unwrap_or_default();
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
            Ok(Event::CData(_))
            | Ok(Event::Comment(_))
            | Ok(Event::Decl(_))
            | Ok(Event::PI(_))
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
    ingest_html_into_page_with(doc, page_id, html, theme, IngestOptions::default())
}

pub fn ingest_html_into_page_with(
    doc: &mut WebDoc,
    page_id: &PageId,
    html: &str,
    theme: &WebTheme,
    options: IngestOptions,
) -> IngestOutcome {
    let mut outcome = ingest_html_with(html, theme, options);
    for node in &outcome.nodes {
        let asset_reference = match &node.kind {
            WebNodeKind::Image { asset_id, .. } => Some(("image", asset_id)),
            WebNodeKind::Section {
                background: Some(background),
                ..
            }
            | WebNodeKind::Container {
                background: Some(background),
                ..
            } => Some(("background", &background.asset_id)),
            _ => None,
        };
        if let Some((usage, asset_id)) = asset_reference {
            if !doc.assets.contains_key(asset_id) {
                outcome.diagnostics.push(
                    Diagnostic::error(
                        Phase::Web,
                        "LUMW0120",
                        format!(
                            "{usage} on node `{}` references unknown asset `{}`",
                            node.id, asset_id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Generate or import the asset first (asset tool / import_external_image), \
                         then reference its id via data-asset or data-background-asset.",
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
                    | "data-text"
                    | "data-variant"
                    | "data-button"
                    | "data-icon"
                    | "data-asset"
                    | "data-href"
                    | "data-new-tab"
                    | "data-background-asset"
                    | "data-background-fit"
                    | "data-background-position"
                    | "data-scrim-color"
                    | "data-scrim-opacity"
                    | "data-component"
                    | "data-command"
                    | "data-target"
                    | "data-aria-label"
                    | "data-single-open"
                    | "data-default-open"
                    | "data-speed"
                    | "data-direction"
                    | "data-pause-on-hover"
                    | "data-embed"
                    | "data-url"
                    | "data-show-arrows"
                    | "data-autoplay"
                    | "data-default-tab"
                    | "data-slot"
                    | "data-slot-when"
            );
            if !known {
                let hint = if key == "style" {
                    "Inline style attributes are not supported; express styling as utility \
                     classes (page-level effects belong in custom_css)."
                } else {
                    "Recognized attributes: id class href target alt data-variant data-button \
                     data-icon data-asset data-text data-href data-new-tab data-background-asset \
                     data-background-fit data-background-position data-scrim-color \
                     data-scrim-opacity data-name data-slot \
                     data-slot-when, plus the Tier-2 component/command/embed data-* attributes \
                     (data-component data-command data-target data-aria-label data-single-open \
                     data-default-open data-speed data-direction data-pause-on-hover data-embed \
                     data-url data-show-arrows data-autoplay data-default-tab)."
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
                        context: DiscardContext::Icon,
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
                let slot_key = self.take_slot_key(&attrs, &id, true);
                let background = self.parse_background(&attrs, &id);
                let node = WebNode {
                    id: id.clone(),
                    kind: WebNodeKind::Section {
                        tag,
                        anchor_id,
                        background,
                    },
                    classes: self.take_classes(&attrs, &id),
                    children: Vec::new(),
                    name: attrs_get(&attrs, "data-name"),
                    slot_key,
                };
                if is_empty {
                    self.finish_node(node);
                } else {
                    self.branch_stack.push(BranchFrame {
                        node,
                        tag_name: name,
                    });
                }
            }
            "div" => {
                // A data-text div is the structured Body/Small wire format:
                // one canonical text node whose inner semantic p/ol/ul/li
                // blocks survive AI subtree edits without becoming sibling
                // WebNodes.
                if attrs_get(&attrs, "data-text").is_some() {
                    let variant = match attrs_get(&attrs, "data-variant").as_deref() {
                        None | Some("") | Some("body") => TextVariant::Body,
                        Some("small") => TextVariant::Small,
                        Some(value) => {
                            self.error(
                                "LUMW0137",
                                format!("structured text cannot use variant `{value}`"),
                                "Structured text supports data-variant=\"body\" or \"small\" only.",
                                None,
                            );
                            return;
                        }
                    };
                    let id = self.mint_id("txt", attrs_get(&attrs, "id").as_deref());
                    let classes = self.take_classes(&attrs, &id);
                    let node_name = attrs_get(&attrs, "data-name");
                    let slot_key = self.take_slot_key(&attrs, &id, false);
                    if is_empty {
                        self.finish_node(WebNode {
                            id,
                            kind: WebNodeKind::Text {
                                variant,
                                content: RichTextDocument::empty(),
                            },
                            classes,
                            children: Vec::new(),
                            name: node_name,
                            slot_key,
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
                                slot_key,
                                structured: true,
                            },
                        });
                    }
                    return;
                }
                // A div carrying data-embed is a sandboxed embed leaf. Checked
                // before data-component: the only agent-authorable provider is
                // calendly (custom URL/snippet embeds are a human editor path).
                if let Some(embed_value) = attrs_get(&attrs, "data-embed") {
                    let id = self.mint_id("emb", attrs_get(&attrs, "id").as_deref());
                    if embed_value.trim() != "calendly" {
                        self.error(
                            "LUMW0128",
                            format!("unknown embed provider `{embed_value}`"),
                            "Agent-authorable embeds: calendly. Custom URL/snippet embeds are added by humans in the editor.",
                            Some(&id),
                        );
                        return;
                    }
                    let url = attrs_get(&attrs, "data-url").unwrap_or_default();
                    if !calendly_url_is_valid(url.trim()) {
                        self.error(
                            "LUMW0129",
                            format!("calendly embed `{id}` missing/invalid data-url"),
                            "A real https://calendly.com/… link — real endpoints only; use an obvious placeholder and flag it if none was provided.",
                            Some(&id),
                        );
                        return;
                    }
                    let classes = self.take_classes(&attrs, &id);
                    let slot_key = self.take_slot_key(&attrs, &id, false);
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Embed {
                            provider: EmbedProvider::Calendly,
                            url: Some(url.trim().to_owned()),
                            html: String::new(),
                        },
                        classes,
                        children: Vec::new(),
                        name: attrs_get(&attrs, "data-name"),
                        slot_key,
                    });
                    if !is_empty {
                        // Embed elements are empty; swallow any inner content.
                        self.capture = Some(CaptureFrame {
                            tag_name: name,
                            start_offset: reader.buffer_position() as usize,
                            nested_depth: 0,
                            pending: PendingLeaf::Discard {
                                warn_if_content: true,
                                context: DiscardContext::Embed,
                            },
                        });
                    }
                    return;
                }
                // A div carrying data-component is a Tier-2 platform component
                // branch; its children parse as ordinary nodes inside it.
                if let Some(component_value) = attrs_get(&attrs, "data-component") {
                    let id = self.mint_id("cmp", attrs_get(&attrs, "id").as_deref());
                    let Some(spec) = self.parse_component(&component_value, &attrs, &id) else {
                        return;
                    };
                    let slot_key = self.take_slot_key(&attrs, &id, false);
                    let node = WebNode {
                        id: id.clone(),
                        kind: WebNodeKind::Component { spec },
                        classes: self.take_classes(&attrs, &id),
                        children: Vec::new(),
                        name: attrs_get(&attrs, "data-name"),
                        slot_key,
                    };
                    if is_empty {
                        self.finish_node(node);
                    } else {
                        self.branch_stack.push(BranchFrame {
                            node,
                            tag_name: name,
                        });
                    }
                    return;
                }
                let id = self.mint_id("box", attrs_get(&attrs, "id").as_deref());
                let slot_key = self.take_slot_key(&attrs, &id, true);
                let href = match attrs_get(&attrs, "data-href") {
                    Some(value) if value.trim().is_empty() => None,
                    Some(value) if href_is_allowed(value.trim()) => Some(value.trim().to_owned()),
                    Some(value) => {
                        self.error(
                            "LUMW0108",
                            format!("container `{id}` data-href has a disallowed scheme: {value}"),
                            "Allowed: https:// http:// mailto: tel: #anchor /path.",
                            Some(&id),
                        );
                        None
                    }
                    None => None,
                };
                let new_tab =
                    href.is_some() && attrs_get(&attrs, "data-new-tab").as_deref() == Some("true");
                let background = self.parse_background(&attrs, &id);
                let node = WebNode {
                    id: id.clone(),
                    kind: WebNodeKind::Container {
                        href,
                        new_tab,
                        background,
                    },
                    classes: self.take_classes(&attrs, &id),
                    children: Vec::new(),
                    name: attrs_get(&attrs, "data-name"),
                    slot_key,
                };
                if is_empty {
                    self.finish_node(node);
                } else {
                    self.branch_stack.push(BranchFrame {
                        node,
                        tag_name: name,
                    });
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
                                context: DiscardContext::Icon,
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
                let slot_key = self.take_slot_key(&attrs, &id, false);
                if is_empty {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Text {
                            variant,
                            content: String::new().into(),
                        },
                        classes,
                        children: Vec::new(),
                        name: node_name,
                        slot_key,
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
                            slot_key,
                            structured: false,
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
                let href_raw = attrs_get(&attrs, "href");
                // A button is a link (href) OR a command trigger, never both.
                let action = if let Some(command_value) = attrs_get(&attrs, "data-command") {
                    let has_href = href_raw
                        .as_ref()
                        .map(|href| !href.trim().is_empty())
                        .unwrap_or(false);
                    if has_href {
                        self.error(
                            "LUMW0127",
                            format!("button `{id}` has both href and data-command"),
                            "A button is a link (href) or a trigger (data-command + data-target), never both.",
                            Some(&id),
                        );
                        return;
                    }
                    let Some(command) = ButtonCommand::parse_html_attr(command_value.trim()) else {
                        self.error(
                            "LUMW0125",
                            format!("unknown command `{command_value}`"),
                            "Valid commands: show-modal close.",
                            Some(&id),
                        );
                        return;
                    };
                    let target = attrs_get(&attrs, "data-target").unwrap_or_default();
                    if target.trim().is_empty() {
                        self.error(
                            "LUMW0126",
                            format!("command button `{id}` has no data-target"),
                            "Point data-target at the id of a dialog component.",
                            Some(&id),
                        );
                        return;
                    }
                    ButtonAction::Command {
                        command,
                        command_target: NodeId::from(target.trim()),
                    }
                } else {
                    let href = href_raw.unwrap_or_default();
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
                    ButtonAction::Href { href, new_tab }
                };
                let classes = self.take_classes(&attrs, &id);
                let node_name = attrs_get(&attrs, "data-name");
                let slot_key = self.take_slot_key(&attrs, &id, false);
                if is_empty {
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Button {
                            label: String::new(),
                            variant,
                            action,
                        },
                        classes,
                        children: Vec::new(),
                        name: node_name,
                        slot_key,
                    });
                } else {
                    self.capture = Some(CaptureFrame {
                        tag_name: name,
                        start_offset: reader.buffer_position() as usize,
                        nested_depth: 0,
                        pending: PendingLeaf::Button {
                            id,
                            action,
                            variant,
                            classes,
                            name: node_name,
                            slot_key,
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
                            format!(
                                "image `{id}` data-href has a disallowed scheme; dropped: {value}"
                            ),
                            "Allowed: https:// http:// mailto: tel: #anchor /path.",
                            Some(&id),
                        );
                        None
                    }
                    None => None,
                };
                let new_tab = attrs_get(&attrs, "data-new-tab").as_deref() == Some("true");
                let classes = self.take_classes(&attrs, &id);
                let slot_key = self.take_slot_key(&attrs, &id, false);
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
                        slot_key,
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
        let slot_key = self.take_slot_key(attrs, &id, false);
        self.finish_node(WebNode {
            id: id.clone(),
            kind: WebNodeKind::Icon { icon: icon_name },
            classes,
            children: Vec::new(),
            name: attrs_get(attrs, "data-name"),
            slot_key,
        });
    }

    /// Parse a `data-component` value into a typed spec, warning-and-defaulting
    /// on bad prop values (LUMW0124) and erroring on an unknown component name
    /// (LUMW0123 → None, which aborts this element).
    fn parse_component(
        &mut self,
        value: &str,
        attrs: &[(String, String)],
        id: &NodeId,
    ) -> Option<ComponentSpec> {
        match value.trim() {
            "dialog" => Some(ComponentSpec::Dialog {
                aria_label: attrs_get(attrs, "data-aria-label"),
            }),
            "accordion" => {
                let single_open = self.component_bool(attrs, "data-single-open", false, id);
                let default_open = match attrs_get(attrs, "data-default-open") {
                    Some(raw) => match raw.trim().parse::<u32>() {
                        Ok(index) => Some(index),
                        Err(_) => {
                            self.warning(
                                "LUMW0124",
                                format!("invalid value for `data-default-open` on component `{id}`: {raw}"),
                                "data-default-open is a 0-based item index (a non-negative integer).",
                                Some(id),
                            );
                            None
                        }
                    },
                    None => None,
                };
                Some(ComponentSpec::Accordion {
                    single_open,
                    default_open,
                })
            }
            "marquee" => {
                let speed_s = match attrs_get(attrs, "data-speed") {
                    Some(raw) => match raw.trim().parse::<u16>() {
                        Ok(seconds) if (5..=120).contains(&seconds) => seconds,
                        _ => {
                            self.warning(
                                "LUMW0124",
                                format!(
                                    "invalid value for `data-speed` on component `{id}`: {raw}"
                                ),
                                "data-speed is seconds in 5..=120; using the default 30.",
                                Some(id),
                            );
                            30
                        }
                    },
                    None => 30,
                };
                let direction = match attrs_get(attrs, "data-direction") {
                    Some(raw) => {
                        match raw.trim() {
                            "left" => MarqueeDirection::Left,
                            "right" => MarqueeDirection::Right,
                            _ => {
                                self.warning(
                                "LUMW0124",
                                format!("invalid value for `data-direction` on component `{id}`: {raw}"),
                                "data-direction is left or right; using left.",
                                Some(id),
                            );
                                MarqueeDirection::Left
                            }
                        }
                    }
                    None => MarqueeDirection::Left,
                };
                let pause_on_hover = self.component_bool(attrs, "data-pause-on-hover", true, id);
                Some(ComponentSpec::Marquee {
                    speed_s,
                    direction,
                    pause_on_hover,
                })
            }
            "nav_menu" => Some(ComponentSpec::NavMenu),
            "carousel" => {
                let show_arrows = self.component_bool(attrs, "data-show-arrows", true, id);
                let autoplay_s = match attrs_get(attrs, "data-autoplay") {
                    Some(raw) => {
                        match raw.trim().parse::<u16>() {
                            Ok(seconds) if (2..=60).contains(&seconds) => Some(seconds),
                            _ => {
                                self.warning(
                                "LUMW0124",
                                format!("invalid value for `data-autoplay` on component `{id}`: {raw}"),
                                "data-autoplay is seconds in 2..=60; omitting autoplay.",
                                Some(id),
                            );
                                None
                            }
                        }
                    }
                    None => None,
                };
                Some(ComponentSpec::Carousel {
                    show_arrows,
                    autoplay_s,
                })
            }
            "tabs" => {
                let default_tab = match attrs_get(attrs, "data-default-tab") {
                    Some(raw) => match raw.trim().parse::<u32>() {
                        Ok(index) => index,
                        Err(_) => {
                            self.warning(
                                "LUMW0124",
                                format!("invalid value for `data-default-tab` on component `{id}`: {raw}"),
                                "data-default-tab is a 0-based tab index (a non-negative integer); using 0.",
                                Some(id),
                            );
                            0
                        }
                    },
                    None => 0,
                };
                Some(ComponentSpec::Tabs { default_tab })
            }
            other => {
                self.error(
                    "LUMW0123",
                    format!("unknown component `{other}`"),
                    "Valid components: dialog accordion marquee nav_menu carousel tabs.",
                    Some(id),
                );
                None
            }
        }
    }

    /// A `"true"`/`"false"` component data-attr, warn-and-default on anything else.
    fn component_bool(
        &mut self,
        attrs: &[(String, String)],
        key: &str,
        default: bool,
        id: &NodeId,
    ) -> bool {
        match attrs_get(attrs, key) {
            Some(raw) => match raw.trim() {
                "true" => true,
                "false" => false,
                _ => {
                    self.warning(
                        "LUMW0124",
                        format!("invalid value for `{key}` on component `{id}`: {raw}"),
                        "Expected \"true\" or \"false\".",
                        Some(id),
                    );
                    default
                }
            },
            None => default,
        }
    }

    fn parse_background(
        &mut self,
        attrs: &[(String, String)],
        id: &NodeId,
    ) -> Option<WebBackgroundImage> {
        let asset_raw = attrs_get(attrs, "data-background-asset");
        let has_scrim = attrs_get(attrs, "data-scrim-color").is_some()
            || attrs_get(attrs, "data-scrim-opacity").is_some();
        let Some(asset_raw) = asset_raw else {
            if has_scrim
                || attrs_get(attrs, "data-background-fit").is_some()
                || attrs_get(attrs, "data-background-position").is_some()
            {
                self.error(
                    "LUMW0135",
                    format!("background controls on `{id}` have no data-background-asset"),
                    "Set data-background-asset to a registered image asset id, or remove the background controls.",
                    Some(id),
                );
            }
            return None;
        };
        let asset_id = match lumen_core::AssetId::new(asset_raw.trim()) {
            Ok(asset_id) => asset_id,
            Err(_) => {
                self.error(
                    "LUMW0135",
                    format!("invalid background asset id `{asset_raw}` on `{id}`"),
                    "Asset ids are alphanumeric with _ or -.",
                    Some(id),
                );
                return None;
            }
        };
        let fit = match attrs_get(attrs, "data-background-fit").as_deref() {
            None | Some("") | Some("cover") => WebBackgroundFit::Cover,
            Some("contain") => WebBackgroundFit::Contain,
            Some(value) => {
                self.error(
                    "LUMW0136",
                    format!("invalid background fit `{value}` on `{id}`"),
                    "Valid background fits: cover contain.",
                    Some(id),
                );
                WebBackgroundFit::Cover
            }
        };
        let position = match attrs_get(attrs, "data-background-position").as_deref() {
            None | Some("") | Some("center") => WebBackgroundPosition::Center,
            Some("top") => WebBackgroundPosition::Top,
            Some("right") => WebBackgroundPosition::Right,
            Some("bottom") => WebBackgroundPosition::Bottom,
            Some("left") => WebBackgroundPosition::Left,
            Some(value) => {
                self.error(
                    "LUMW0136",
                    format!("invalid background position `{value}` on `{id}`"),
                    "Valid positions: center top right bottom left.",
                    Some(id),
                );
                WebBackgroundPosition::Center
            }
        };
        let scrim = if has_scrim {
            let color = match attrs_get(attrs, "data-scrim-color").as_deref() {
                None | Some("") | Some("dark") => WebScrimColor::Dark,
                Some("light") => WebScrimColor::Light,
                Some("primary") => WebScrimColor::Primary,
                Some("accent") => WebScrimColor::Accent,
                Some("black") => WebScrimColor::Black,
                Some("white") => WebScrimColor::White,
                Some(value) => {
                    self.error(
                        "LUMW0136",
                        format!("invalid scrim color `{value}` on `{id}`"),
                        "Valid scrim colors: dark light primary accent black white.",
                        Some(id),
                    );
                    WebScrimColor::Dark
                }
            };
            let opacity = match attrs_get(attrs, "data-scrim-opacity").as_deref() {
                None | Some("") => 50,
                Some(value) => match value.parse::<u8>() {
                    Ok(parsed) if parsed <= 100 => parsed,
                    _ => {
                        self.error(
                            "LUMW0136",
                            format!("invalid scrim opacity `{value}` on `{id}`"),
                            "Scrim opacity is an integer from 0 through 100.",
                            Some(id),
                        );
                        50
                    }
                },
            };
            Some(WebBackgroundScrim { color, opacity })
        } else {
            None
        };
        Some(WebBackgroundImage {
            asset_id,
            fit,
            position,
            scrim,
        })
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
            if let PendingLeaf::Discard {
                warn_if_content,
                context,
            } = &capture.pending
            {
                if *warn_if_content && !inner.trim().is_empty() {
                    self.warning(
                        "LUMW0131",
                        context.message(inner.trim()),
                        context.hint(),
                        None,
                    );
                }
                return;
            }
            match capture.pending {
                PendingLeaf::Text {
                    id,
                    variant,
                    classes,
                    name,
                    slot_key,
                    structured,
                } => {
                    let content = if structured {
                        RichTextDocument::from_html(inner)
                    } else {
                        let sanitized = sanitize_inline(inner);
                        self.warn_inline_adjustments(&id, &sanitized.removed);
                        sanitized.html.into()
                    };
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Text { variant, content },
                        classes,
                        children: Vec::new(),
                        name,
                        slot_key,
                    });
                }
                PendingLeaf::Button {
                    id,
                    action,
                    variant,
                    classes,
                    name,
                    slot_key,
                } => {
                    let sanitized = sanitize_inline(inner);
                    self.warn_inline_adjustments(&id, &sanitized.removed);
                    self.finish_node(WebNode {
                        id,
                        kind: WebNodeKind::Button {
                            label: sanitized.html,
                            variant,
                            action,
                        },
                        classes,
                        children: Vec::new(),
                        name,
                        slot_key,
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

    fn warn_inline_adjustments(&mut self, subject: &NodeId, removed: &[String]) {
        for note in removed {
            self.warning(
                "LUMW0130",
                format!("inline content adjusted in `{subject}`: {note}"),
                "Allowed inline markup: strong em u s a br span[class].",
                Some(subject),
            );
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
                format!("top-level <{}> is not a section", node.kind.kind_name()),
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
                    briefed: self.options.briefed,
                },
            );
            // Advice is deduped across the whole ingest: one line per raw
            // class, not one per node that carries it.
            extend_deduping_advice(&mut self.diagnostics, lint);
        }
        classes
    }

    /// Resolve a node's personalization slot key from `data-slot` /
    /// `data-slot-when`. `data-slot` is legal on any element; `data-slot-when`
    /// (stored as `when:{key}`, a presence gate) is legal only where
    /// `allow_when` holds (sections and containers). Keys obey the ONE strict
    /// personalization grammar (`[a-z0-9_.-]+`, ≤64 — same as `data-var`); bad
    /// key → LUMW0133; misplaced `data-slot-when` → LUMW0134. When both are
    /// present the gate wins (gating subsumes substitution).
    fn take_slot_key(
        &mut self,
        attrs: &[(String, String)],
        id: &NodeId,
        allow_when: bool,
    ) -> Option<SlotKey> {
        if let Some(raw) = attrs_get(attrs, "data-slot-when") {
            let key = raw.trim();
            if !allow_when {
                self.error(
                    "LUMW0134",
                    format!("data-slot-when on `{id}` is only valid on sections and containers"),
                    "Presence gating wraps a section or a <div> container; move the marker to the enclosing band.",
                    Some(id),
                );
                return None;
            }
            if !personalization_key_is_valid(key) {
                self.error(
                    "LUMW0133",
                    format!("invalid data-slot-when key `{key}` on `{id}`"),
                    "Keys are lowercase [a-z0-9_.-], max 64 chars (e.g. account.testimonial).",
                    Some(id),
                );
                return None;
            }
            return Some(SlotKey::from(format!("{WHEN_PREFIX}{key}")));
        }
        if let Some(raw) = attrs_get(attrs, "data-slot") {
            let key = raw.trim();
            if !personalization_key_is_valid(key) {
                self.error(
                    "LUMW0133",
                    format!("invalid data-slot key `{key}` on `{id}`"),
                    "Keys are lowercase [a-z0-9_.-], max 64 chars (e.g. account.name).",
                    Some(id),
                );
                return None;
            }
            return Some(SlotKey::from(key));
        }
        None
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
        assert!(
            !outcome.has_errors(),
            "diagnostics: {:#?}",
            outcome.diagnostics
        );
        assert_eq!(outcome.roots.len(), 2);
        let header = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "site_header")
            .unwrap();
        assert!(matches!(
            header.kind,
            WebNodeKind::Section {
                tag: SectionTag::Header,
                ..
            }
        ));
        let hero_heading = outcome
            .nodes
            .iter()
            .find(|node| {
                matches!(
                    &node.kind,
                    WebNodeKind::Text {
                        variant: TextVariant::Display,
                        ..
                    }
                )
            })
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
    fn structured_text_wrapper_ingests_as_one_semantic_body_node() {
        let outcome = ingest_html(
            r#"<section id="content">
                 <div id="story" data-text="rich" data-variant="body" class="max-w-prose">
                   <p>Intro <strong>copy</strong></p>
                   <ul><li>First<ul><li>Nested</li></ul></li><li>Second</li></ul>
                   <p>Outro<br>line</p>
                 </div>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let node = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "story")
            .expect("structured text node");
        let WebNodeKind::Text { variant, content } = &node.kind else {
            panic!("story should be one text node");
        };
        assert_eq!(*variant, TextVariant::Body);
        assert_eq!(node.classes, "max-w-prose");
        assert_eq!(content.blocks.len(), 3);
        assert_eq!(
            content.to_semantic_html(),
            "<p>Intro <strong>copy</strong></p>\
             <ul><li>First<ul><li>Nested</li></ul></li><li>Second</li></ul>\
             <p>Outro<br />line</p>"
        );
        assert_eq!(
            outcome
                .nodes
                .iter()
                .filter(|candidate| matches!(candidate.kind, WebNodeKind::Text { .. }))
                .count(),
            1,
            "inner blocks must not become sibling WebNodes"
        );
    }

    #[test]
    fn structured_text_wrapper_rejects_heading_variants() {
        let outcome = ingest_html(
            r#"<section id="content">
                 <div data-text="rich" data-variant="h2"><p>One</p><p>Two</p></div>
               </section>"#,
            &theme(),
        );
        assert!(outcome.has_errors());
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0137"));
    }

    #[test]
    fn clickable_container_and_background_attributes_ingest_as_typed_semantics() {
        let outcome = ingest_html(
            r#"<section id="hero" data-background-asset="hero_photo" data-background-position="top" data-scrim-color="dark" data-scrim-opacity="60">
                 <div id="card" data-href="/case-study" data-new-tab="true" data-background-asset="card_photo" data-background-fit="contain">
                   <p>Read the story</p>
                 </div>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let hero = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "hero")
            .unwrap();
        let WebNodeKind::Section {
            background: Some(background),
            ..
        } = &hero.kind
        else {
            panic!("section background");
        };
        assert_eq!(background.position, WebBackgroundPosition::Top);
        assert_eq!(background.scrim.as_ref().unwrap().opacity, 60);

        let card = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "card")
            .unwrap();
        let WebNodeKind::Container {
            href,
            new_tab,
            background: Some(background),
        } = &card.kind
        else {
            panic!("clickable background container");
        };
        assert_eq!(href.as_deref(), Some("/case-study"));
        assert!(*new_tab);
        assert_eq!(background.fit, WebBackgroundFit::Contain);
    }

    #[test]
    fn malformed_background_attributes_are_rejected() {
        let outcome = ingest_html(
            r#"<section id="hero" data-background-asset="photo" data-background-fit="stretch" data-scrim-opacity="101"><p>Hi</p></section>"#,
            &theme(),
        );
        assert!(outcome.has_errors());
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0136"));
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
    fn dialog_component_with_props_and_children_parses() {
        let outcome = ingest_html(
            r#"<section id="s">
                 <div data-component="dialog" id="dlg_book" data-aria-label="Book a call" class="max-w-[480px]">
                   <p>Pick a time.</p>
                 </div>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let dialog = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "dlg_book")
            .expect("dialog node");
        let WebNodeKind::Component {
            spec: ComponentSpec::Dialog { aria_label },
        } = &dialog.kind
        else {
            panic!("dialog component");
        };
        assert_eq!(aria_label.as_deref(), Some("Book a call"));
        assert_eq!(dialog.children.len(), 1);
    }

    #[test]
    fn unknown_component_errors() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-component="lightbox"></div></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0123"));
    }

    #[test]
    fn command_button_parses_to_command_action() {
        let outcome = ingest_html(
            r#"<section id="s">
                 <a data-button="primary" data-command="show-modal" data-target="dlg_book">Book a call</a>
                 <div data-component="dialog" id="dlg_book"></div>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let button = outcome
            .nodes
            .iter()
            .find(|node| matches!(&node.kind, WebNodeKind::Button { .. }))
            .expect("button");
        let WebNodeKind::Button { action, .. } = &button.kind else {
            panic!("button");
        };
        assert!(matches!(
            action,
            ButtonAction::Command { command: ButtonCommand::ShowModal, command_target }
                if command_target.as_str() == "dlg_book"
        ));
    }

    #[test]
    fn command_button_missing_target_errors() {
        let outcome = ingest_html(
            r#"<section id="s"><a data-button="primary" data-command="show-modal">Open</a></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0126"));
    }

    #[test]
    fn button_with_href_and_command_conflicts() {
        let outcome = ingest_html(
            r#"<section id="s"><a data-button="primary" href="https://x.com" data-command="show-modal" data-target="dlg">Open</a></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0127"));
    }

    #[test]
    fn command_button_unknown_command_errors() {
        let outcome = ingest_html(
            r#"<section id="s"><a data-button="primary" data-command="explode" data-target="dlg">Open</a></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0125"));
        // The link-path "no href" error must not fire for command buttons.
        assert!(!outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0107"));
    }

    #[test]
    fn marquee_speed_out_of_range_warns_and_defaults() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-component="marquee" data-speed="999"><p>logo</p></div></section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0124"));
        let marquee = outcome
            .nodes
            .iter()
            .find(|node| matches!(&node.kind, WebNodeKind::Component { .. }))
            .expect("marquee");
        let WebNodeKind::Component {
            spec: ComponentSpec::Marquee { speed_s, .. },
        } = &marquee.kind
        else {
            panic!("marquee");
        };
        assert_eq!(*speed_s, 30);
    }

    #[test]
    fn calendly_embed_parses() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-embed="calendly" data-url="https://calendly.com/team/intro" class="w-full"></div></section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let embed = outcome
            .nodes
            .iter()
            .find(|node| matches!(&node.kind, WebNodeKind::Embed { .. }))
            .expect("embed node");
        assert!(embed.id.as_str().starts_with("emb"));
        let WebNodeKind::Embed {
            provider,
            url,
            html,
        } = &embed.kind
        else {
            panic!("embed");
        };
        assert_eq!(*provider, EmbedProvider::Calendly);
        assert_eq!(url.as_deref(), Some("https://calendly.com/team/intro"));
        assert!(html.is_empty());
    }

    #[test]
    fn embed_unknown_provider_errors() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-embed="typeform" data-url="https://typeform.com/x"></div></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0128"));
    }

    #[test]
    fn embed_invalid_url_errors() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-embed="calendly" data-url="https://evil.com/x"></div></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0129"));
    }

    #[test]
    fn embed_with_content_warns_and_swallows() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-embed="calendly" data-url="https://calendly.com/x">stray</div></section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let warn = outcome
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code == "LUMW0131")
            .expect("discard warning");
        assert!(warn.message.contains("embed"), "{}", warn.message);
    }

    #[test]
    fn nav_menu_carousel_tabs_parse_with_props() {
        let outcome = ingest_html(
            r#"<section id="s">
                 <div data-component="nav_menu" id="nav"><p>Home</p></div>
                 <div data-component="carousel" id="car" data-show-arrows="false" data-autoplay="5">
                   <div><p>a</p></div>
                   <div><p>b</p></div>
                 </div>
                 <div data-component="tabs" id="tabs" data-default-tab="1">
                   <div><p>Tab 1</p><p>Body 1</p></div>
                   <div><p>Tab 2</p><p>Body 2</p></div>
                 </div>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let carousel = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "car")
            .expect("carousel");
        let WebNodeKind::Component {
            spec:
                ComponentSpec::Carousel {
                    show_arrows,
                    autoplay_s,
                },
        } = &carousel.kind
        else {
            panic!("carousel");
        };
        assert!(!show_arrows);
        assert_eq!(*autoplay_s, Some(5));
        let tabs = outcome
            .nodes
            .iter()
            .find(|node| node.id.as_str() == "tabs")
            .expect("tabs");
        let WebNodeKind::Component {
            spec: ComponentSpec::Tabs { default_tab },
        } = &tabs.kind
        else {
            panic!("tabs");
        };
        assert_eq!(*default_tab, 1);
    }

    #[test]
    fn carousel_autoplay_out_of_range_warns() {
        let outcome = ingest_html(
            r#"<section id="s"><div data-component="carousel" data-autoplay="600"><div><p>a</p></div><div><p>b</p></div></div></section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0124"));
        let carousel = outcome
            .nodes
            .iter()
            .find(|node| {
                matches!(
                    &node.kind,
                    WebNodeKind::Component {
                        spec: ComponentSpec::Carousel { .. }
                    }
                )
            })
            .expect("carousel");
        let WebNodeKind::Component {
            spec: ComponentSpec::Carousel { autoplay_s, .. },
        } = &carousel.kind
        else {
            panic!("carousel");
        };
        assert_eq!(*autoplay_s, None);
    }

    #[test]
    fn personalization_markers_round_trip_through_ingest() {
        let outcome = ingest_html(
            r#"<section id="proof" data-slot-when="account.testimonial">
                 <div id="grid" data-slot="account.peers">
                   <p id="peer" data-slot="account.peer_name">Peer</p>
                 </div>
                 <h1 id="head">Meet <span data-var="account.name">Acme</span></h1>
                 <a id="cta" data-button="primary" href="/x" data-slot="account.cta">Go</a>
               </section>"#,
            &theme(),
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        let by_id = |id: &str| {
            outcome
                .nodes
                .iter()
                .find(|node| node.id.as_str() == id)
                .unwrap_or_else(|| panic!("node `{id}`"))
        };
        // data-slot-when becomes a when:-prefixed slot key on the section.
        assert_eq!(
            by_id("proof").slot_key.as_ref().map(|k| k.as_str()),
            Some("when:account.testimonial")
        );
        // data-slot maps straight to slot_key on container, text, and button.
        assert_eq!(
            by_id("grid").slot_key.as_ref().map(|k| k.as_str()),
            Some("account.peers")
        );
        assert_eq!(
            by_id("peer").slot_key.as_ref().map(|k| k.as_str()),
            Some("account.peer_name")
        );
        assert_eq!(
            by_id("cta").slot_key.as_ref().map(|k| k.as_str()),
            Some("account.cta")
        );
        // data-var survives inside the sanitized text content.
        let WebNodeKind::Text { content, .. } = &by_id("head").kind else {
            panic!("text node");
        };
        assert!(content.contains("data-var=\"account.name\""), "{content}");
    }

    #[test]
    fn invalid_slot_key_errors() {
        // Off-charset (space), uppercase data-slot, and uppercase
        // data-slot-when all reject: keys are strictly [a-z0-9_.-].
        for html in [
            r#"<section id="s"><p id="p" data-slot="Account Name">x</p></section>"#,
            r#"<section id="s"><p id="p" data-slot="Account.Name">x</p></section>"#,
            r#"<section id="s" data-slot-when="Account.Testimonial"><p id="p">x</p></section>"#,
        ] {
            let outcome = ingest_html(html, &theme());
            assert!(
                outcome
                    .diagnostics
                    .iter()
                    .any(|diagnostic| diagnostic.code == "LUMW0133"),
                "{html}: {:#?}",
                outcome.diagnostics
            );
        }
    }

    #[test]
    fn data_slot_when_on_non_container_errors() {
        // A text node cannot carry a presence gate.
        let outcome = ingest_html(
            r#"<section id="s"><p id="p" data-slot-when="account.x">x</p></section>"#,
            &theme(),
        );
        assert!(outcome
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0134"));
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
        doc.assets
            .insert(lumen_core::AssetId::from("logo_1"), record);
        let theme = theme();
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="s"><p>Fast&nbsp;&amp; safe&mdash;always</p><img data-asset="logo_1" alt="logo"></section>"#,
            &theme,
        );
        assert!(
            !outcome.has_errors(),
            "diagnostics: {:#?}",
            outcome.diagnostics
        );
    }

    // --- brand-geometry advice on a briefed kit (LUMW0306) ------------------
    //
    // A kit that carries a Creative Brief has MEASURED shape, so raw radius and
    // elevation steps are drift the author can see. The finding is Advice: it
    // reaches the agent and nothing else, and can never reject a page.

    const RAW_GEOMETRY_PAGE: &str = r##"
<section id="cards" class="bg-light">
  <div class="flex flex-col gap-6 px-6 py-20">
    <div class="rounded-2xl shadow-lg p-6 bg-card">
      <p class="text-muted">First card.</p>
    </div>
    <div class="rounded-2xl shadow-lg p-6 bg-card">
      <p class="text-muted">Second card.</p>
    </div>
  </div>
</section>
"##;

    fn advice_codes(outcome: &IngestOutcome, code: &str) -> Vec<String> {
        outcome
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == code)
            .map(|diagnostic| diagnostic.message.clone())
            .collect()
    }

    #[test]
    fn briefed_kit_advises_on_raw_geometry() {
        let outcome = ingest_html_with(
            RAW_GEOMETRY_PAGE,
            &theme(),
            IngestOptions { briefed: true },
        );
        assert!(
            !outcome.has_errors(),
            "advice must never reject: {:#?}",
            outcome.diagnostics
        );
        let advice: Vec<&Diagnostic> = outcome
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "LUMW0306")
            .collect();
        assert!(
            advice
                .iter()
                .all(|diagnostic| diagnostic.severity == DiagnosticSeverity::Advice),
            "LUMW0306 must be advice: {advice:#?}"
        );
        let messages: Vec<&str> = advice
            .iter()
            .map(|diagnostic| diagnostic.message.as_str())
            .collect();
        assert!(
            messages.iter().any(|message| message.contains("`rounded-2xl`")),
            "expected radius advice, got {messages:?}"
        );
        assert!(
            messages.iter().any(|message| message.contains("`shadow-lg`")),
            "expected shadow advice, got {messages:?}"
        );
    }

    #[test]
    fn unbriefed_kit_is_byte_identical_to_today() {
        let plain = ingest_html(RAW_GEOMETRY_PAGE, &theme());
        let explicit = ingest_html_with(
            RAW_GEOMETRY_PAGE,
            &theme(),
            IngestOptions { briefed: false },
        );
        assert_eq!(plain.diagnostics, explicit.diagnostics);
        assert!(
            advice_codes(&plain, "LUMW0306").is_empty(),
            "an unbriefed kit gets no geometry advice: {:#?}",
            plain.diagnostics
        );
        // The representative clean page is untouched too.
        assert_eq!(
            ingest_html(GOOD_PAGE, &theme()).diagnostics,
            ingest_html_with(GOOD_PAGE, &theme(), IngestOptions { briefed: false }).diagnostics
        );
    }

    #[test]
    fn geometry_advice_is_deduped_across_nodes() {
        let outcome = ingest_html_with(
            RAW_GEOMETRY_PAGE,
            &theme(),
            IngestOptions { briefed: true },
        );
        // Two cards, identical classes → one line per raw class, not per node.
        let radius: Vec<String> = advice_codes(&outcome, "LUMW0306")
            .into_iter()
            .filter(|message| message.contains("`rounded-2xl`"))
            .collect();
        assert_eq!(radius.len(), 1, "expected one deduped line: {radius:?}");
    }

    #[test]
    fn a_page_saturated_with_raw_geometry_still_stores() {
        let mut doc = WebDoc::new("d1", "Site", None);
        let theme = theme();
        let outcome = ingest_html_into_page_with(
            &mut doc,
            &PageId::from("home"),
            RAW_GEOMETRY_PAGE,
            &theme,
            IngestOptions { briefed: true },
        );
        assert!(
            !outcome.has_errors(),
            "geometry advice may never reject: {:#?}",
            outcome.diagnostics
        );
        assert!(!outcome.nodes.is_empty());
        let page = doc.page_mut(&PageId::from("home")).expect("home page");
        assert!(page.nodes.contains_key(&NodeId::from("cards")));
    }
}
