//! Tree → HTML renderer. One code path, two targets.
//!
//! Editor mode adds `data-node-id` on every element (the selection bridge's
//! hit-test hook), the Tailwind v4 browser runtime, and an optional bridge
//! script — served into a sandboxed `srcdoc` iframe. Delivery mode emits
//! clean semantic HTML with zero instrumentation (asserted in tests); the
//! static Tailwind utility compile joins at the export phase. The `data-tv`
//! / `data-btn` attributes appear in both modes: they are the theme base
//! layer's styling hooks, not instrumentation.

use crate::doc::{
    calendly_url_is_valid, fragment_wrapper_class, ButtonAction, ComponentSpec, EmbedProvider,
    MarqueeDirection, WebBackgroundImage, WebDoc, WebNode, WebNodeKind,
};
use crate::runtime::{PLATFORM_CSS, PLATFORM_RUNTIME_JS, TABS_CSS};
use crate::theme::WebTheme;
use crate::util::{escape_attr, escape_text};
use lumen_core::{Diagnostic, DiagnosticSubject, NodeId, PageId, Phase};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RenderMode {
    Editor,
    Delivery,
}

/// One API-resolved, account-scoped runtime frame for a custom-component leaf.
///
/// The canonical document stores only slug, immutable artifact pin, typed
/// props, and host layout classes. Executable bytes are resolved outside the
/// engine and arrive here as an already-contained nested `srcdoc`; the renderer
/// never reads mutable source or manufactures a successful runtime.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CustomComponentRuntimeFrame {
    pub state: String,
    pub artifact_id: String,
    pub name: String,
    #[serde(default)]
    pub srcdoc: Option<String>,
    #[serde(default)]
    pub runtime_nonce: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub error_code: Option<String>,
    #[serde(default)]
    pub intrinsic_height: bool,
    #[serde(default)]
    pub warning_count: usize,
}

/// One API-resolved fragment artifact, keyed in `RenderOptions::fragments` by
/// its `frag_<16 hex>` id (clone-fidelity F1.3).
///
/// The canonical document stores only the id. The artifact — sanitized once at
/// creation and frozen — is resolved outside the engine from the registry and
/// arrives here as markup the renderer emits VERBATIM. The renderer never
/// sanitizes, never rewrites, and never manufactures a fragment it was not
/// handed: a missing entry renders the placeholder, exactly as a missing
/// custom-component pin does.
///
/// Keyed by FRAGMENT id rather than node id (the custom-component frame map's
/// key) because a fragment artifact is content-addressed: two nodes pinning
/// the same section share one artifact, so one entry serves both and the API
/// reads each artifact once. Per-node divergence is the slot layer's, and
/// slots live on the node — F1.4 substitutes them at this arm's call site.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FragmentContent {
    /// The artifact's sanitized HTML. Slot markers are intact; the marker's
    /// own content is the fallback whenever the node binds that key to
    /// nothing, or binds it to something the walk refuses.
    pub html: String,
    /// What each of this artifact's slots MEANS, keyed by slot key — the
    /// artifact's `slot_manifest` kinds, threaded in by the API because the
    /// engine never sees a manifest (F1.4).
    ///
    /// A slot key with no kind here cannot be substituted: the node's value
    /// tag alone cannot distinguish an href from a paragraph (both ride
    /// `Text`), and guessing would let a link target be written into a
    /// heading — or worse, the reverse. Absent ⇒ the artifact's own content,
    /// plus a diagnostic.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub slot_kinds: BTreeMap<String, FragmentSlotKind>,
    /// Artifact-bound platform dependencies, never inferred from captured classes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub native_dependencies: Option<NativeFragmentDependencies>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeFragmentDependencies {
    pub version: u32,
    pub platform_runtime: u32,
    pub tabs: Vec<NativeFragmentTabs>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeFragmentTabs {
    pub root_id: String,
    pub items: Vec<NativeFragmentTabItem>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeFragmentTabItem {
    pub tab_id: String,
    pub panel_id: String,
}

/// What one fragment slot holds, from the artifact's slot manifest. The Python
/// side's `lumen_api.fragments.slots.SLOT_KINDS` is the same four names, and
/// `SLOT_KIND_TO_NODE_TAG` is the mapping this enum enforces against the
/// node's tagged `FragmentSlotValue`:
/// `text`→`{"text":…}`, `image`→`{"asset":…}`, `href`→`{"text":…}`,
/// `visibility`→`{"visible":…}`.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum FragmentSlotKind {
    Text,
    Image,
    Href,
    Visibility,
}

impl FragmentSlotKind {
    pub fn name(self) -> &'static str {
        match self {
            Self::Text => "text",
            Self::Image => "image",
            Self::Href => "href",
            Self::Visibility => "visibility",
        }
    }
}

#[derive(Clone, Debug)]
pub struct RenderOptions {
    pub mode: RenderMode,
    /// Base URL for content-addressed asset bytes (`{base}/{digest}`).
    pub asset_base_url: String,
    /// Editor mode only: the Tailwind v4 browser runtime script src.
    pub tailwind_runtime_src: Option<String>,
    /// Editor mode only: inline bridge script (hover/select/postMessage).
    pub bridge_script: Option<String>,
    /// API-resolved runtime frames keyed by canonical node id. Missing entries
    /// preserve the explicit P6.1 placeholder.
    pub custom_component_runtimes: BTreeMap<String, CustomComponentRuntimeFrame>,
    /// API-resolved fragment artifacts keyed by `frag_<16 hex>` id. Missing
    /// entries render the F1.3 placeholder.
    #[allow(clippy::doc_markdown)]
    pub fragments: BTreeMap<String, FragmentContent>,
}

impl RenderOptions {
    pub fn delivery(asset_base_url: impl Into<String>) -> Self {
        Self {
            mode: RenderMode::Delivery,
            asset_base_url: asset_base_url.into(),
            tailwind_runtime_src: None,
            bridge_script: None,
            custom_component_runtimes: BTreeMap::new(),
            fragments: BTreeMap::new(),
        }
    }

    pub fn editor(asset_base_url: impl Into<String>) -> Self {
        Self {
            mode: RenderMode::Editor,
            asset_base_url: asset_base_url.into(),
            tailwind_runtime_src: None,
            bridge_script: None,
            custom_component_runtimes: BTreeMap::new(),
            fragments: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct RenderOutput {
    pub html: String,
    pub diagnostics: Vec<Diagnostic>,
}

/// Any node reachable from the page root that needs the platform CSS — a
/// Component OR an Embed (`.lumen-embed`, nav/carousel/tab styles all live in
/// PLATFORM_CSS). The public name is kept though the concept is now "uses
/// platform css".
pub fn page_uses_components(doc: &WebDoc, page_id: &PageId) -> bool {
    let Some(page) = doc.page(page_id) else {
        return false;
    };
    page.reachable_ids().iter().any(|id| {
        matches!(
            page.node(id).map(|node| &node.kind),
            Some(
                WebNodeKind::Component { .. }
                    | WebNodeKind::CustomComponent { .. }
                    | WebNodeKind::Embed { .. }
            )
        )
    })
}

/// Every fragment artifact id the page REFERENCES, in reachable order, once
/// each — the engine's own answer to "which artifacts must be resolved before
/// this page can render", and the analog of `page_uses_components` for the
/// F1.3 fragment map + the fragment CSS sheet.
///
/// Reachable-only, because an orphaned node is not on the page: resolving its
/// artifact would splice CSS for a section nobody can see. Deduped, because
/// two nodes pinning the same section share one artifact.
pub fn page_fragment_ids(doc: &WebDoc, page_id: &PageId) -> Vec<String> {
    let Some(page) = doc.page(page_id) else {
        return Vec::new();
    };
    let mut ids: Vec<String> = Vec::new();
    for id in page.reachable_ids() {
        if let Some(WebNodeKind::Fragment { fragment_id, .. }) =
            page.node(&id).map(|node| &node.kind)
        {
            if !ids.iter().any(|seen| seen == fragment_id) {
                ids.push(fragment_id.clone());
            }
        }
    }
    ids
}

/// Reachable features whose behavior needs the platform interaction runtime:
/// a Command-action Button, a Dialog, a Tabs, or a Carousel that actually
/// wires arrows or autoplay. NavMenu is CSS-only.
pub fn page_needs_runtime(doc: &WebDoc, page_id: &PageId) -> bool {
    let Some(page) = doc.page(page_id) else {
        return false;
    };
    page.reachable_ids()
        .iter()
        .any(|id| match page.node(id).map(|node| &node.kind) {
            Some(WebNodeKind::Button {
                action: ButtonAction::Command { .. },
                ..
            }) => true,
            Some(WebNodeKind::Component {
                spec: ComponentSpec::Dialog { .. },
            }) => true,
            Some(WebNodeKind::Component {
                spec: ComponentSpec::Tabs { .. },
            }) => true,
            Some(WebNodeKind::Component {
                spec:
                    ComponentSpec::Carousel {
                        show_arrows,
                        autoplay_s,
                    },
            }) => *show_arrows || autoplay_s.is_some(),
            _ => false,
        })
}

pub fn render_page(
    doc: &WebDoc,
    page_id: &PageId,
    theme: &WebTheme,
    options: &RenderOptions,
) -> Result<RenderOutput, Vec<Diagnostic>> {
    let Some(page) = doc.page(page_id) else {
        return Err(vec![Diagnostic::error(
            Phase::Web,
            "LUMW0400",
            format!("page `{page_id}` does not exist"),
            None,
        )]);
    };
    let Some(root) = page.node(&page.root) else {
        return Err(vec![Diagnostic::error(
            Phase::Web,
            "LUMW0401",
            format!("page `{page_id}` root node `{}` is missing", page.root),
            Some(DiagnosticSubject::Node(page.root.clone())),
        )]);
    };

    let mut diagnostics = Vec::new();
    let mut body = String::new();
    for child in &root.children {
        render_node(
            doc,
            page_id,
            child,
            theme,
            options,
            &mut body,
            &mut diagnostics,
            false,
        );
    }

    let editor = options.mode == RenderMode::Editor;
    let uses_components = page_uses_components(doc, page_id);
    let native_tabs = page_fragment_ids(doc, page_id).iter().any(|id| {
        options
            .fragments
            .get(id)
            .is_some_and(|f| f.native_dependencies.is_some())
    });
    let needs_runtime = page_needs_runtime(doc, page_id) || native_tabs;
    let mut html = String::with_capacity(body.len() + theme.base_css.len() + 2048);
    html.push_str("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n");
    html.push_str("<meta charset=\"utf-8\">\n");
    html.push_str("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n");
    html.push_str(&format!("<title>{}</title>\n", escape_text(&doc.title)));
    // A linked Container must keep the block-level behavior it had as a div.
    // :where() keeps specificity at zero, so authored display utilities
    // (flex/grid/inline-flex) still override this default.
    html.push_str(
        "<style>:where(a[data-lumen-container-link]){display:block;color:inherit;text-decoration:inherit}</style>\n",
    );
    // Plain :root variables in both modes so the base layer's var()
    // references resolve even before (or without) the Tailwind runtime.
    html.push_str("<style>\n:root {\n");
    for (name, value) in &theme.tokens {
        html.push_str(&format!("  --color-{name}: {value};\n"));
    }
    html.push_str("}\n</style>\n");
    if editor {
        html.push_str(&format!(
            "<style type=\"text/tailwindcss\">\n{}\n</style>\n",
            theme.theme_block
        ));
        if let Some(src) = &options.tailwind_runtime_src {
            html.push_str(&format!("<script src=\"{}\"></script>\n", escape_attr(src)));
        }
    }
    if editor {
        // Tailwind v4 emits authored utilities inside cascade layers. Keep
        // semantic theme defaults in the lower-priority base layer so a
        // per-node utility from the human inspector can override them.
        html.push_str(&format!(
            "<style>\n@layer base {{\n{}\n}}\n</style>\n",
            theme.base_css
        ));
    } else {
        html.push_str(&format!("<style>\n{}\n</style>\n", theme.base_css));
    }
    // Platform component/placeholder base styles, versioned with the runtime;
    // emitted in both modes only when the page uses a built-in component,
    // custom-component placeholder, or embed.
    if uses_components {
        html.push_str(&format!("<style>\n{PLATFORM_CSS}\n</style>\n"));
    }
    if uses_components || native_tabs {
        html.push_str(&format!("<style>\n{TABS_CSS}\n</style>\n"));
    }
    // The document's own CSS, AFTER the theme block — which since F1.3 ends with the fragment
    // sheet. So at equal specificity `custom_css` beats a cloned section's rule, and that is the
    // right way round: `custom_css` is a human's deliberate override of this page, while a
    // fragment's CSS came from somebody else's site. (Compiled utilities land after both and win
    // ties over either.) Recorded here because the order is load-bearing and nothing else says so.
    if !doc.custom_css.trim().is_empty() {
        html.push_str(&format!(
            "<style>\n{}\n</style>\n",
            css_style_safe(&doc.custom_css)
        ));
    }
    // The ONE platform interaction runtime — the delivery guarantee's single
    // script exception, inlined in both modes only when a command button or
    // dialog needs it. Never any agent-authored code.
    if needs_runtime {
        html.push_str(&format!(
            "<script>/* lumen-runtime v2 */ {PLATFORM_RUNTIME_JS}</script>\n"
        ));
    }
    // Contract §8 item 2 (founder amendment, 2026-08-18; closes §7 item 7 /
    // contract row 1): the page root renders onto <body> — its classes in
    // BOTH modes (a root `bg-<token>` finally paints, published pages
    // included), its node id under the same editor-only gating as every
    // other node, so a click on empty page background resolves to the root
    // and the inspector's Canvas schema opens (deliberately replacing the
    // old click-clears-selection behavior).
    html.push_str("</head>\n<body");
    if editor {
        html.push_str(&format!(
            " data-node-id=\"{}\"",
            escape_attr(root.id.as_str())
        ));
    }
    if !root.classes.trim().is_empty() {
        html.push_str(&format!(" class=\"{}\"", escape_attr(root.classes.trim())));
    }
    html.push_str(">\n");
    html.push_str(&body);
    if editor {
        if let Some(bridge) = &options.bridge_script {
            html.push_str(&format!("<script>\n{bridge}\n</script>\n"));
        }
    }
    html.push_str("</body>\n</html>\n");

    Ok(RenderOutput { html, diagnostics })
}

#[allow(clippy::too_many_arguments)]
fn render_node(
    doc: &WebDoc,
    page_id: &PageId,
    node_id: &NodeId,
    theme: &WebTheme,
    options: &RenderOptions,
    out: &mut String,
    diagnostics: &mut Vec<Diagnostic>,
    // The marquee's aria-hidden clone renders with node ids suppressed so the
    // bridge's selection hooks are never duplicated in the DOM.
    suppress_node_ids: bool,
) {
    let page = doc.page(page_id).expect("page checked by render_page");
    let Some(node) = page.node(node_id) else {
        diagnostics.push(Diagnostic::warning(
            Phase::Web,
            "LUMW0402",
            format!("child id `{node_id}` has no node; skipped"),
            Some(DiagnosticSubject::Node(node_id.clone())),
        ));
        return;
    };
    let editor = options.mode == RenderMode::Editor;
    let node_attr = |out: &mut String| {
        if editor && !suppress_node_ids {
            out.push_str(&format!(
                " data-node-id=\"{}\"",
                escape_attr(node.id.as_str())
            ));
        }
    };
    let class_attr = |out: &mut String| {
        if !node.classes.trim().is_empty() {
            out.push_str(&format!(" class=\"{}\"", escape_attr(node.classes.trim())));
        }
    };

    match &node.kind {
        WebNodeKind::Section {
            tag,
            anchor_id,
            background,
        } => {
            let tag = tag.as_str();
            out.push('<');
            out.push_str(tag);
            let anchor = anchor_id.as_deref().unwrap_or(node.id.as_str());
            out.push_str(&format!(" id=\"{}\"", escape_attr(anchor)));
            node_attr(out);
            class_attr(out);
            render_background_attr(doc, node, background.as_ref(), options, out, diagnostics);
            out.push('>');
            for child in &node.children {
                render_node(
                    doc,
                    page_id,
                    child,
                    theme,
                    options,
                    out,
                    diagnostics,
                    suppress_node_ids,
                );
            }
            out.push_str(&format!("</{tag}>"));
        }
        WebNodeKind::Container {
            href,
            new_tab,
            background,
        } => {
            let tag = if href.is_some() { "a" } else { "div" };
            out.push('<');
            out.push_str(tag);
            if let Some(href) = href {
                out.push_str(&format!(" href=\"{}\"", escape_attr(href)));
                out.push_str(" data-lumen-container-link");
                if *new_tab {
                    out.push_str(" target=\"_blank\" rel=\"noopener noreferrer\"");
                }
            }
            node_attr(out);
            class_attr(out);
            render_background_attr(doc, node, background.as_ref(), options, out, diagnostics);
            out.push('>');
            for child in &node.children {
                render_node(
                    doc,
                    page_id,
                    child,
                    theme,
                    options,
                    out,
                    diagnostics,
                    suppress_node_ids,
                );
            }
            out.push_str("</");
            out.push_str(tag);
            out.push('>');
        }
        WebNodeKind::Text { variant, content } => {
            let tag = if variant.allows_structured_rich_text() {
                "div"
            } else {
                variant.render_tag()
            };
            out.push('<');
            out.push_str(tag);
            out.push_str(&format!(" data-tv=\"{}\"", variant.as_str()));
            node_attr(out);
            class_attr(out);
            out.push('>');
            if variant.allows_structured_rich_text() {
                out.push_str(&content.to_semantic_html());
            } else {
                out.push_str(&content.to_inline_html());
            }
            out.push_str(&format!("</{tag}>"));
        }
        WebNodeKind::Button {
            label,
            variant,
            action,
        } => match action {
            ButtonAction::Href { href, new_tab } => {
                out.push_str("<a");
                out.push_str(&format!(" data-btn=\"{}\"", variant.as_str()));
                out.push_str(&format!(" href=\"{}\"", escape_attr(href)));
                if *new_tab {
                    out.push_str(" target=\"_blank\" rel=\"noopener noreferrer\"");
                }
                node_attr(out);
                class_attr(out);
                out.push('>');
                out.push_str(label);
                out.push_str("</a>");
            }
            ButtonAction::Command {
                command,
                command_target,
            } => {
                out.push_str("<button type=\"button\"");
                out.push_str(&format!(" data-btn=\"{}\"", variant.as_str()));
                out.push_str(&format!(
                    " commandfor=\"{}\"",
                    escape_attr(command_target.as_str())
                ));
                out.push_str(&format!(" command=\"{}\"", command.as_html_attr()));
                node_attr(out);
                class_attr(out);
                out.push_str(" data-lumen-command=\"true\"");
                out.push('>');
                out.push_str(label);
                out.push_str("</button>");
            }
        },
        WebNodeKind::Component { spec } => match spec {
            ComponentSpec::Dialog { aria_label } => {
                out.push_str(&format!(
                    "<dialog id=\"{}\" data-lumen-dialog=\"true\"",
                    escape_attr(node.id.as_str())
                ));
                if let Some(label) = aria_label {
                    out.push_str(&format!(" aria-label=\"{}\"", escape_attr(label)));
                }
                node_attr(out);
                class_attr(out);
                out.push('>');
                // Platform-owned close control: render-supplied, not a node
                // (so it carries no data-node-id and is never selectable).
                out.push_str(&format!(
                    "<button type=\"button\" data-lumen-command=\"true\" class=\"lumen-dialog-close\" commandfor=\"{}\" command=\"close\" aria-label=\"Close\">&#215;</button>",
                    escape_attr(node.id.as_str())
                ));
                for child in &node.children {
                    render_node(
                        doc,
                        page_id,
                        child,
                        theme,
                        options,
                        out,
                        diagnostics,
                        suppress_node_ids,
                    );
                }
                out.push_str("</dialog>");
            }
            ComponentSpec::Accordion {
                single_open,
                default_open,
            } => {
                out.push_str("<div");
                node_attr(out);
                class_attr(out);
                out.push('>');
                for (index, child_id) in node.children.iter().enumerate() {
                    render_accordion_item(
                        doc,
                        page_id,
                        child_id,
                        theme,
                        options,
                        out,
                        diagnostics,
                        suppress_node_ids,
                        node.id.as_str(),
                        *single_open,
                        *default_open == Some(index as u32),
                    );
                }
                out.push_str("</div>");
            }
            ComponentSpec::Marquee {
                speed_s,
                direction,
                pause_on_hover,
            } => {
                // The element needs BOTH the platform class and node.classes.
                out.push_str("<div class=\"lumen-marquee");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
                out.push_str(&format!(
                    " data-direction=\"{}\"",
                    match direction {
                        MarqueeDirection::Left => "left",
                        MarqueeDirection::Right => "right",
                    }
                ));
                out.push_str(&format!(
                    " data-pause-on-hover=\"{}\"",
                    if *pause_on_hover { "true" } else { "false" }
                ));
                // Platform-generated style from a validated u16 — strictly formatted.
                out.push_str(&format!(" style=\"--lumen-marquee-duration:{speed_s}s\""));
                node_attr(out);
                out.push('>');
                out.push_str("<div class=\"lumen-marquee-track\">");
                for child in &node.children {
                    render_node(
                        doc,
                        page_id,
                        child,
                        theme,
                        options,
                        out,
                        diagnostics,
                        suppress_node_ids,
                    );
                }
                out.push_str("</div>");
                // The aria-hidden clone repeats the content for a seamless loop;
                // its subtree renders with node ids suppressed.
                out.push_str("<div class=\"lumen-marquee-track\" aria-hidden=\"true\">");
                for child in &node.children {
                    render_node(doc, page_id, child, theme, options, out, diagnostics, true);
                }
                out.push_str("</div>");
                out.push_str("</div>");
            }
            ComponentSpec::NavMenu => {
                out.push_str("<div class=\"lumen-nav");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
                node_attr(out);
                out.push('>');
                // Desktop inline row.
                out.push_str("<div class=\"lumen-nav-row\">");
                for child in &node.children {
                    render_node(
                        doc,
                        page_id,
                        child,
                        theme,
                        options,
                        out,
                        diagnostics,
                        suppress_node_ids,
                    );
                }
                out.push_str("</div>");
                // Mobile hamburger dropdown: the same children, node ids
                // suppressed so the bridge never sees the clone (marquee pattern).
                out.push_str(
                    "<details class=\"lumen-nav-menu\"><summary aria-label=\"Open menu\">&#9776;</summary><div class=\"lumen-nav-panel\">",
                );
                for child in &node.children {
                    render_node(doc, page_id, child, theme, options, out, diagnostics, true);
                }
                out.push_str("</div></details>");
                out.push_str("</div>");
            }
            ComponentSpec::Carousel {
                show_arrows,
                autoplay_s,
            } => {
                out.push_str("<div class=\"lumen-carousel");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
                if let Some(seconds) = autoplay_s {
                    out.push_str(&format!(" data-autoplay-s=\"{seconds}\""));
                }
                out.push_str(" data-lumen-carousel=\"true\"");
                node_attr(out);
                out.push('>');
                out.push_str("<div class=\"lumen-carousel-track\">");
                for child in &node.children {
                    render_node(
                        doc,
                        page_id,
                        child,
                        theme,
                        options,
                        out,
                        diagnostics,
                        suppress_node_ids,
                    );
                }
                out.push_str("</div>");
                if *show_arrows {
                    out.push_str(
                        "<button type=\"button\" class=\"lumen-carousel-arrow\" data-dir=\"prev\" aria-label=\"Previous\">&#8249;</button>",
                    );
                    out.push_str(
                        "<button type=\"button\" class=\"lumen-carousel-arrow\" data-dir=\"next\" aria-label=\"Next\">&#8250;</button>",
                    );
                }
                out.push_str("</div>");
            }
            ComponentSpec::Tabs { default_tab } => {
                render_tabs(
                    doc,
                    page_id,
                    node,
                    theme,
                    options,
                    out,
                    diagnostics,
                    suppress_node_ids,
                    *default_tab,
                );
            }
        },
        WebNodeKind::CustomComponent {
            slug, artifact_id, ..
        } => {
            if let Some(runtime) = options
                .custom_component_runtimes
                .get(node.id.as_str())
            {
                out.push_str("<div class=\"lumen-custom-component-runtime");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
                out.push_str(&format!(
                    " role=\"group\" data-custom-component-runtime-state=\"{}\"",
                    escape_attr(&runtime.state)
                ));
                out.push_str(&format!(
                    " data-custom-component-node-id=\"{}\" data-custom-component-slug=\"{}\" data-custom-component-artifact=\"{}\"",
                    escape_attr(node.id.as_str()),
                    escape_attr(slug),
                    escape_attr(artifact_id)
                ));
                out.push_str(&format!(
                    " data-custom-component-intrinsic=\"{}\" data-custom-component-warning-count=\"{}\"",
                    if runtime.intrinsic_height { "true" } else { "false" },
                    runtime.warning_count
                ));
                if editor {
                    out.push_str(" data-custom-component-editor=\"true\"");
                }
                if let Some(error_code) = &runtime.error_code {
                    out.push_str(&format!(
                        " data-custom-component-error-code=\"{}\"",
                        escape_attr(error_code)
                    ));
                }
                if runtime.state != "ready" {
                    out.push_str(" data-custom-component-placeholder=\"true\"");
                }
                node_attr(out);
                out.push_str(&format!(
                    " aria-label=\"Custom component {}\">",
                    escape_attr(&runtime.name)
                ));
                if runtime.state == "ready"
                    && runtime.artifact_id == *artifact_id
                    && runtime.srcdoc.is_some()
                    && runtime.runtime_nonce.is_some()
                {
                    let srcdoc = runtime.srcdoc.as_deref().unwrap_or_default();
                    let runtime_nonce =
                        runtime.runtime_nonce.as_deref().unwrap_or_default();
                    out.push_str(&format!(
                        "<iframe class=\"lumen-custom-component-frame\" title=\"{}\" sandbox=\"allow-scripts\" referrerpolicy=\"no-referrer\" credentialless data-lumen-custom-component-runtime=\"true\" data-runtime-contract-version=\"1\" data-runtime-nonce=\"{}\" data-node-id-ref=\"{}\" data-artifact-id=\"{}\"",
                        escape_attr(&format!("{} component", runtime.name)),
                        escape_attr(runtime_nonce),
                        escape_attr(node.id.as_str()),
                        escape_attr(artifact_id)
                    ));
                    if editor {
                        out.push_str(" tabindex=\"-1\"");
                    }
                    out.push_str(&format!(" srcdoc=\"{}\"></iframe>", escape_attr(srcdoc)));
                    out.push_str(
                        "<span class=\"lumen-custom-component-state\" aria-live=\"polite\"></span>",
                    );
                } else {
                    let message = runtime
                        .message
                        .as_deref()
                        .unwrap_or("The pinned artifact is unavailable.");
                    out.push_str(
                        "<div class=\"lumen-custom-component-unavailable\" role=\"status\">",
                    );
                    out.push_str("<span>Custom component unavailable</span>");
                    out.push_str(&format!("<strong>{}</strong>", escape_text(slug)));
                    out.push_str(&format!("<small>{}</small>", escape_text(message)));
                    out.push_str("</div>");
                    diagnostics.push(Diagnostic::warning(
                        Phase::Web,
                        "LUMW0410",
                        format!(
                            "custom component `{}` artifact `{artifact_id}` is unavailable: {message}",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
                out.push_str("</div>");
                return;
            }
            out.push_str("<div class=\"lumen-custom-component-placeholder");
            if !node.classes.trim().is_empty() {
                out.push(' ');
                out.push_str(&escape_attr(node.classes.trim()));
            }
            out.push('"');
            out.push_str(" role=\"status\" data-custom-component-placeholder=\"true\"");
            out.push_str(&format!(
                " data-custom-component-slug=\"{}\" data-custom-component-artifact=\"{}\"",
                escape_attr(slug),
                escape_attr(artifact_id)
            ));
            node_attr(out);
            out.push_str(&format!(
                " aria-label=\"Custom component {} is unavailable\">",
                escape_attr(slug)
            ));
            out.push_str("<span>Custom component unavailable</span>");
            out.push_str(&format!("<strong>{}</strong>", escape_text(slug)));
            out.push_str("<small>The sandboxed component runtime is not active yet.</small>");
            out.push_str("</div>");
            diagnostics.push(Diagnostic::warning(
                Phase::Web,
                "LUMW0406",
                format!(
                    "custom component `{}` artifact `{artifact_id}` rendered as a safe placeholder",
                    node.id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }
        WebNodeKind::Image {
            asset_id,
            alt,
            href,
            new_tab,
        } => {
            let src = doc
                .assets
                .get(asset_id)
                .and_then(|record| asset_src(record, &options.asset_base_url));
            if src.is_none() {
                diagnostics.push(Diagnostic::warning(
                    Phase::Web,
                    "LUMW0403",
                    format!(
                        "image `{}` asset `{asset_id}` has no resolvable bytes",
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
            if let Some(link) = href {
                out.push_str(&format!("<a href=\"{}\"", escape_attr(link)));
                if *new_tab {
                    out.push_str(" target=\"_blank\" rel=\"noopener noreferrer\"");
                }
                out.push('>');
            }
            out.push_str("<img");
            if let Some(src) = &src {
                out.push_str(&format!(" src=\"{}\"", escape_attr(src)));
            } else {
                out.push_str(" data-missing-asset=\"true\"");
            }
            out.push_str(&format!(" alt=\"{}\"", escape_attr(alt)));
            out.push_str(" loading=\"lazy\"");
            node_attr(out);
            class_attr(out);
            out.push_str(">");
            if href.is_some() {
                out.push_str("</a>");
            }
        }
        WebNodeKind::Icon { icon } => match lumen_core::icons::resolve_icon(icon) {
            Some(def) => {
                out.push_str(&format!(
                    "<svg viewBox=\"0 0 {} {}\" fill=\"currentColor\" aria-hidden=\"true\"",
                    def.view_box[0], def.view_box[1]
                ));
                node_attr(out);
                class_attr(out);
                out.push_str(&format!(
                    "><path d=\"{}\"/></svg>",
                    escape_attr(def.path_data)
                ));
            }
            None => {
                diagnostics.push(Diagnostic::warning(
                    Phase::Web,
                    "LUMW0404",
                    format!("icon `{icon}` on `{}` is unknown; skipped", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
        },
        WebNodeKind::Fragment {
            fragment_id,
            slots,
            text_overrides,
        } => {
            // The wrapper is the ONLY markup this arm authors. Everything
            // inside it is the artifact's own sanitized HTML, emitted
            // verbatim: the fragment was made safe ONCE, at creation, and
            // re-processing it here would make the render path a second
            // sanitizer that could disagree with the first.
            //
            // Two things are interpolated and nothing else: the wrapper class
            // derived from a RE-CHECKED fragment id, and that artifact HTML.
            // The id is re-checked because a document loaded from storage may
            // never have been through `validate_web_doc` — an unchecked id
            // would land in a class attribute in live markup.
            //
            // F1.4 substitutes slot values into `content.html` at this call
            // site; the marker content standing in the artifact today IS the
            // fallback, so the shape does not change when it does.
            let wrapper_class = fragment_wrapper_class(fragment_id);
            let content = wrapper_class
                .as_ref()
                .and_then(|_| options.fragments.get(fragment_id));
            let Some((wrapper_class, content)) = wrapper_class.as_ref().zip(content) else {
                // Placeholder, never a hole and never a hard error: the F1.2
                // reference gate deliberately keeps a document with a dead pin
                // loadable, so the render must degrade the way the
                // custom-component missing-pin path does — visibly, and loud
                // in diagnostics.
                out.push_str("<div class=\"lumen-fragment lumen-fragment-placeholder");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
                out.push_str(" role=\"status\" data-fragment-placeholder=\"true\"");
                if wrapper_class.is_some() {
                    // Safe to name: `frag_` + 16 hex characters, already
                    // re-checked, and the one thing an operator needs to
                    // chase the missing artifact. An INVALID id is never
                    // echoed, not even escaped — the point of the re-check is
                    // that such an id does not travel.
                    out.push_str(&format!(" data-fragment-id=\"{fragment_id}\""));
                }
                node_attr(out);
                out.push_str(" aria-label=\"Cloned section unavailable\">");
                out.push_str("<span>Cloned section unavailable</span>");
                out.push_str("</div>");
                let (code, message) = if wrapper_class.is_none() {
                    (
                        "LUMW0411",
                        format!(
                            "fragment node `{}` carries an id that is not a `frag_<16 hex>` \
                             artifact address; rendered as a safe placeholder",
                            node.id
                        ),
                    )
                } else {
                    (
                        "LUMW0412",
                        format!(
                            "fragment node `{}` pins artifact `{fragment_id}`, which was not \
                             resolved for this render; rendered as a safe placeholder",
                            node.id
                        ),
                    )
                };
                diagnostics.push(Diagnostic::warning(
                    Phase::Web,
                    code,
                    message,
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
                return;
            };
            out.push_str("<div class=\"lumen-fragment ");
            out.push_str(wrapper_class);
            if !node.classes.trim().is_empty() {
                out.push(' ');
                out.push_str(&escape_attr(node.classes.trim()));
            }
            out.push('"');
            // Semantic CSS boundary in both modes, only for resolved artifacts.
            // Unlike an authored class, this cannot accidentally turn a native
            // container or missing-pin placeholder into source-owned markup.
            out.push_str(" data-lumen-fragment=\"true\"");
            node_attr(out);
            // Slice 2 / R-A1: the bridge has to tell a clone ROOT from an ordinary
            // vocabulary node, because everything INSIDE this wrapper is the artifact's
            // own markup and carries no node id — an element in there is addressed by
            // structural path from this wrapper, not by an id of its own. Editor-only,
            // under the same condition `node_attr` emits `data-node-id` under: a
            // delivery snapshot carries no instrumentation at all.
            if editor && !suppress_node_ids {
                out.push_str(" data-fragment-root=\"true\"");
            }
            out.push('>');
            // F1.4: the artifact's markup with this NODE's slot values applied.
            // With nothing bound the walk is the identity function, so an
            // unpersonalized fragment still renders byte-for-byte as stored.
            let substituted = crate::fragment::substitute_fragment_slots(
                &content.html,
                slots,
                &content.slot_kinds,
                doc,
                &options.asset_base_url,
                &node.id,
                diagnostics,
            );
            // R-A6: the marketer's own words, second and last. The slot pass is
            // the agent's personalization; an override is a human overruling it
            // on ONE element, so it runs after — and on that pass's OUTPUT,
            // because the markup the editor measured the path against is the
            // rendered markup, not the stored artifact. Both passes are
            // identity functions when nothing is bound.
            let personalized = crate::fragment::apply_fragment_text_overrides(
                &substituted,
                text_overrides,
                &node.id,
                diagnostics,
            );
            if let Some(dependencies) = &content.native_dependencies {
                let result = if suppress_node_ids {
                    Err("native fragments cannot be duplicated inside a nav or marquee".to_owned())
                } else {
                    crate::fragment::instantiate_native_fragment(
                        &personalized,
                        dependencies,
                        &node.id,
                    )
                };
                match result {
                    Ok(html) => out.push_str(&html),
                    Err(message) => {
                        out.push_str("<span role=\"status\">Native section unavailable</span>");
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0445",
                            message,
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
            } else {
                out.push_str(&personalized);
            }
            out.push_str("</div>");
        }
        WebNodeKind::Embed {
            provider,
            url,
            html,
        } => {
            // Merged class for a live embed iframe: the platform hook first,
            // then the node's own utilities.
            let embed_class = |out: &mut String| {
                out.push_str(" class=\"lumen-embed");
                if !node.classes.trim().is_empty() {
                    out.push(' ');
                    out.push_str(&escape_attr(node.classes.trim()));
                }
                out.push('"');
            };
            let src_iframe = |out: &mut String, url: &str, title: &str| {
                out.push_str(&format!("<iframe src=\"{}\"", escape_attr(url)));
                out.push_str(&format!(" title=\"{title}\""));
                out.push_str(
                    " sandbox=\"allow-scripts allow-same-origin allow-forms allow-popups\"",
                );
                out.push_str(" loading=\"lazy\"");
                node_attr(out);
                embed_class(out);
                out.push_str("></iframe>");
            };
            let missing = |out: &mut String, diagnostics: &mut Vec<Diagnostic>| {
                out.push_str("<div class=\"lumen-embed\" data-missing-embed=\"true\"");
                node_attr(out);
                out.push_str("></div>");
                diagnostics.push(Diagnostic::warning(
                    Phase::Web,
                    "LUMW0405",
                    format!("embed `{}` has no valid url", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            };
            match provider {
                EmbedProvider::Calendly => match url {
                    Some(url) if calendly_url_is_valid(url) => {
                        src_iframe(out, url, "Calendly scheduling");
                    }
                    _ => missing(out, diagnostics),
                },
                EmbedProvider::Custom => {
                    if let Some(url) = url {
                        src_iframe(out, url, "Embedded content");
                    } else if !html.trim().is_empty() {
                        // Pasted widget markup: sandboxed with no same-origin,
                        // so it runs but stays null-origin.
                        out.push_str("<iframe sandbox=\"allow-scripts allow-forms\" srcdoc=\"");
                        out.push_str(&escape_attr(html));
                        out.push_str("\" title=\"Embedded content\" loading=\"lazy\"");
                        embed_class(out);
                        node_attr(out);
                        out.push_str("></iframe>");
                    } else {
                        missing(out, diagnostics);
                    }
                }
            }
        }
    }
}

/// Render one accordion child. A Container with >=2 children becomes a native
/// `<details>` (first child = summary, rest = panel); anything else renders
/// normally (validation warns it will show unfolded).
#[allow(clippy::too_many_arguments)]
fn render_accordion_item(
    doc: &WebDoc,
    page_id: &PageId,
    child_id: &NodeId,
    theme: &WebTheme,
    options: &RenderOptions,
    out: &mut String,
    diagnostics: &mut Vec<Diagnostic>,
    suppress_node_ids: bool,
    accordion_id: &str,
    single_open: bool,
    is_default_open: bool,
) {
    let page = doc.page(page_id).expect("page checked by render_page");
    let item_shape = page
        .node(child_id)
        .map(|child| {
            matches!(child.kind, WebNodeKind::Container { .. }) && child.children.len() >= 2
        })
        .unwrap_or(false);
    if !item_shape {
        render_node(
            doc,
            page_id,
            child_id,
            theme,
            options,
            out,
            diagnostics,
            suppress_node_ids,
        );
        return;
    }
    let child = page.node(child_id).expect("checked present");
    let editor = options.mode == RenderMode::Editor;
    out.push_str("<details data-lumen-acc-item=\"true\"");
    if single_open {
        // Shared name = exclusive open group (native single-open accordion).
        out.push_str(&format!(" name=\"{}\"", escape_attr(accordion_id)));
    }
    if is_default_open {
        out.push_str(" open");
    }
    if editor && !suppress_node_ids {
        out.push_str(&format!(
            " data-node-id=\"{}\"",
            escape_attr(child.id.as_str())
        ));
    }
    if !child.classes.trim().is_empty() {
        out.push_str(&format!(" class=\"{}\"", escape_attr(child.classes.trim())));
    }
    out.push('>');
    out.push_str("<summary>");
    render_node(
        doc,
        page_id,
        &child.children[0],
        theme,
        options,
        out,
        diagnostics,
        suppress_node_ids,
    );
    out.push_str("</summary>");
    for grandchild in &child.children[1..] {
        render_node(
            doc,
            page_id,
            grandchild,
            theme,
            options,
            out,
            diagnostics,
            suppress_node_ids,
        );
    }
    out.push_str("</details>");
}

/// A child fits the tabs item shape when it is a Container with >=2 children
/// whose first child is a Text node (the tab label; the rest is the panel).
fn tabs_item_shape(page: &crate::doc::WebPage, child_id: &NodeId) -> bool {
    page.node(child_id)
        .map(|child| {
            matches!(child.kind, WebNodeKind::Container { .. })
                && child.children.len() >= 2
                && page
                    .node(&child.children[0])
                    .map(|first| matches!(first.kind, WebNodeKind::Text { .. }))
                    .unwrap_or(false)
        })
        .unwrap_or(false)
}

/// Render a Tabs component: a `role="tablist"` of buttons over the item-shaped
/// children (Container, >=2 children, Text-first), one `role="tabpanel"` per
/// item, then any non-fitting children rendered normally (validation warns).
#[allow(clippy::too_many_arguments)]
fn render_tabs(
    doc: &WebDoc,
    page_id: &PageId,
    node: &crate::doc::WebNode,
    theme: &WebTheme,
    options: &RenderOptions,
    out: &mut String,
    diagnostics: &mut Vec<Diagnostic>,
    suppress_node_ids: bool,
    default_tab: u32,
) {
    let page = doc.page(page_id).expect("page checked by render_page");
    let editor = options.mode == RenderMode::Editor;
    let items: Vec<&NodeId> = node
        .children
        .iter()
        .filter(|child_id| tabs_item_shape(page, child_id))
        .collect();
    // default_tab clamps to the last item when out of range.
    let selected = if items.is_empty() {
        0
    } else {
        (default_tab as usize).min(items.len() - 1)
    };

    out.push_str("<div class=\"lumen-tabs");
    if !node.classes.trim().is_empty() {
        out.push(' ');
        out.push_str(&escape_attr(node.classes.trim()));
    }
    out.push('"');
    out.push_str(&format!(
        " id=\"lumen-tabs-{}\" data-lumen-tabs=\"true\"",
        escape_attr(node.id.as_str())
    ));
    if editor && !suppress_node_ids {
        out.push_str(&format!(
            " data-node-id=\"{}\"",
            escape_attr(node.id.as_str())
        ));
    }
    out.push('>');

    out.push_str("<div class=\"lumen-tabs-list\" role=\"tablist\">");
    for (index, item_id) in items.iter().enumerate() {
        let item = page.node(item_id).expect("item present");
        let is_selected = index == selected;
        let label = page
            .node(&item.children[0])
            .and_then(|first| match &first.kind {
                WebNodeKind::Text { content, .. } => Some(content.clone()),
                _ => None,
            })
            .unwrap_or_default();
        out.push_str("<button type=\"button\" role=\"tab\" class=\"lumen-tab\"");
        out.push_str(&format!(" id=\"{}_tab\"", escape_attr(item.id.as_str())));
        out.push_str(&format!(
            " aria-controls=\"{}_panel\"",
            escape_attr(item.id.as_str())
        ));
        out.push_str(&format!(
            " aria-selected=\"{}\"",
            if is_selected { "true" } else { "false" }
        ));
        out.push_str(&format!(
            " tabindex=\"{}\"",
            if is_selected { "0" } else { "-1" }
        ));
        out.push('>');
        // The label is the first Text child's inline content, without its <p>
        // wrapper or data-node-id.
        out.push_str(&label.to_inline_html());
        out.push_str("</button>");
    }
    out.push_str("</div>");

    for (index, item_id) in items.iter().enumerate() {
        let item = page.node(item_id).expect("item present");
        out.push_str(&format!(
            "<div role=\"tabpanel\" id=\"{}_panel\" aria-labelledby=\"{}_tab\"",
            escape_attr(item.id.as_str()),
            escape_attr(item.id.as_str())
        ));
        if !item.classes.trim().is_empty() {
            out.push_str(&format!(" class=\"{}\"", escape_attr(item.classes.trim())));
        }
        if editor && !suppress_node_ids {
            out.push_str(&format!(
                " data-node-id=\"{}\"",
                escape_attr(item.id.as_str())
            ));
        }
        if index != selected {
            out.push_str(" hidden");
        }
        out.push('>');
        for grandchild in &item.children[1..] {
            render_node(
                doc,
                page_id,
                grandchild,
                theme,
                options,
                out,
                diagnostics,
                suppress_node_ids,
            );
        }
        out.push_str("</div>");
    }

    // Children that do not fit the item shape render normally after the tab
    // structure (validation warns about them).
    for child_id in &node.children {
        if !tabs_item_shape(page, child_id) {
            render_node(
                doc,
                page_id,
                child_id,
                theme,
                options,
                out,
                diagnostics,
                suppress_node_ids,
            );
        }
    }

    out.push_str("</div>");
}

/// Defense in depth for the one raw-text slot in the document: validation
/// rejects `</style` in custom_css, but the renderer must be safe even
/// against a payload that bypassed it — `\3c` is the CSS escape for `<`,
/// inert as CSS and unable to terminate the element.
fn css_style_safe(css: &str) -> String {
    let lower = css.to_ascii_lowercase();
    let needle = "</style";
    if !lower.contains(needle) {
        return css.to_owned();
    }
    let mut out = String::with_capacity(css.len() + 16);
    let mut last = 0;
    let mut cursor = 0;
    while let Some(found) = lower[cursor..].find(needle) {
        let at = cursor + found;
        out.push_str(&css[last..at]);
        out.push_str("\\3c /style");
        last = at + needle.len();
        cursor = last;
    }
    out.push_str(&css[last..]);
    out
}

pub(crate) fn asset_src(record: &lumen_core::AssetRecord, asset_base_url: &str) -> Option<String> {
    if let Some(digest) = &record.media.digest {
        let base = asset_base_url.trim_end_matches('/');
        return Some(format!("{base}/{}", digest.value));
    }
    record
        .media
        .location
        .as_ref()
        .and_then(|location| location.url.clone())
}

fn render_background_attr(
    doc: &WebDoc,
    node: &WebNode,
    background: Option<&WebBackgroundImage>,
    options: &RenderOptions,
    out: &mut String,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(background) = background else {
        return;
    };
    let src = doc
        .assets
        .get(&background.asset_id)
        .and_then(|record| asset_src(record, &options.asset_base_url));
    let Some(src) = src else {
        diagnostics.push(Diagnostic::warning(
            Phase::Web,
            "LUMW0404",
            format!(
                "{} `{}` background asset `{}` has no resolvable bytes",
                node.kind.kind_name(),
                node.id,
                background.asset_id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));
        out.push_str(" data-missing-background-asset=\"true\"");
        return;
    };
    let css_src = css_single_quoted_string(&src);
    let image = if let Some(scrim) = &background.scrim {
        let color = scrim.color.as_css_color();
        format!(
            "linear-gradient(color-mix(in srgb,{color} {}%,transparent),color-mix(in srgb,{color} {}%,transparent)),url('{css_src}')",
            scrim.opacity, scrim.opacity
        )
    } else {
        format!("url('{css_src}')")
    };
    let style = format!(
        "background-image:{image};background-size:{};background-position:{};background-repeat:no-repeat",
        background.fit.as_css(),
        background.position.as_css()
    );
    out.push_str(&format!(" style=\"{}\"", escape_attr(&style)));
}

fn css_single_quoted_string(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\n', "\\a ")
        .replace('\r', "\\a ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::WebThemeRef;
    use crate::ingest::ingest_html_into_page;
    use crate::theme::{compile_web_theme, WebThemeOptions};
    use lumen_core::AssetId;

    fn fixture() -> (WebDoc, WebTheme) {
        let (theme, _) =
            compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default());
        let mut doc = WebDoc::new("d1", "Insight Health", None);
        let record: lumen_core::AssetRecord = serde_json::from_value(serde_json::json!({
            "id": "hero_img",
            "label": "Hero",
            "kind": "raster_image",
            "status": "ready",
            "source": {"kind": "generated", "model": "test-model", "request_id": null},
            "media": {
                "mime_type": "image/webp",
                "digest": {"algorithm": "sha256", "value": "abc123"},
                "location": null,
                "filename": null,
                "byte_length": null
            }
        }))
        .expect("asset fixture");
        doc.assets.insert(AssetId::from("hero_img"), record);
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="hero" class="bg-light">
                 <div class="flex flex-col gap-6">
                   <h1 data-variant="display">Hello <strong>world</strong></h1>
                   <a data-button="primary" href="https://x.ai/demo">Go</a>
                   <img data-asset="hero_img" alt="Product UI">
                   <i data-icon="sparkles"></i>
                 </div>
               </section>"#,
            &theme,
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        (doc, theme)
    }

    // Contract §8 item 2 (2026-08-18): the page root renders onto <body>.
    #[test]
    fn page_root_classes_and_editor_id_render_onto_body() {
        let (mut doc, theme) = fixture();
        let page_id = PageId::from("home");
        let root_id = doc.page(&page_id).expect("page").root.clone();
        doc.page_mut(&page_id)
            .expect("page")
            .nodes
            .get_mut(&root_id)
            .expect("root node")
            .classes = "bg-surface-canvas".to_owned();

        let editor = render_page(
            &doc,
            &page_id,
            &theme,
            &RenderOptions::editor("/asset-store"),
        )
        .expect("editor render");
        assert!(editor.html.contains(&format!(
            "<body data-node-id=\"{}\" class=\"bg-surface-canvas\">",
            root_id.as_str()
        )));

        // Delivery keeps the classes (published backgrounds paint) but stays
        // free of editor instrumentation, per the mode's zero-node-id law.
        let delivery = render_page(
            &doc,
            &page_id,
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("delivery render");
        assert!(delivery.html.contains("<body class=\"bg-surface-canvas\">"));
        assert!(!delivery.html.contains("data-node-id"));
    }

    #[test]
    fn classless_root_keeps_a_bare_body_in_delivery() {
        let (doc, theme) = fixture();
        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("delivery render");
        assert!(delivery.html.contains("<body>\n"));
    }

    #[test]
    fn editor_mode_is_instrumented() {
        let (doc, theme) = fixture();
        let mut options = RenderOptions::editor("/asset-store");
        options.tailwind_runtime_src = Some("/vendor/tailwind.js".to_owned());
        options.bridge_script = Some("console.log('bridge')".to_owned());
        let output = render_page(&doc, &PageId::from("home"), &theme, &options).expect("render");
        assert!(output.html.contains("data-node-id=\"hero\""));
        assert!(output.html.contains("text/tailwindcss"));
        assert!(output.html.contains("/vendor/tailwind.js"));
        assert!(output.html.contains("@layer base"));
        assert!(output.html.contains("console.log('bridge')"));
        assert!(output.html.contains("src=\"/asset-store/abc123\""));
    }

    #[test]
    fn custom_component_renders_a_bounded_selectable_placeholder() {
        let (mut doc, theme) = fixture();
        let page = doc.pages.get_mut(0).expect("page");
        let host_id = page
            .nodes
            .get(&NodeId::from("hero"))
            .expect("hero")
            .children[0]
            .clone();
        page.nodes
            .get_mut(&host_id)
            .expect("host")
            .children
            .push(NodeId::from("cc_booking"));
        page.nodes.insert(
            NodeId::from("cc_booking"),
            WebNode {
                id: NodeId::from("cc_booking"),
                kind: WebNodeKind::CustomComponent {
                    slug: "book-a-call".to_owned(),
                    artifact_id: format!("ccart_{}", "c".repeat(64)),
                    props: std::collections::BTreeMap::from([(
                        "headline".to_owned(),
                        crate::doc::CustomComponentValue::String("Talk to us".to_owned()),
                    )]),
                },
                classes: "w-[480px] h-[240px]".to_owned(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );

        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::editor("/asset-store"),
        )
        .expect("editor render");
        assert!(editor
            .html
            .contains("class=\"lumen-custom-component-placeholder w-[480px] h-[240px]\""));
        assert!(editor.html.contains("data-node-id=\"cc_booking\""));
        assert!(editor
            .html
            .contains("data-custom-component-slug=\"book-a-call\""));
        assert!(editor.html.contains("Custom component unavailable"));
        assert!(editor.html.contains(".lumen-custom-component-placeholder"));
        assert!(editor
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0406"));

        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("delivery render");
        assert!(!delivery.html.contains("data-node-id=\"cc_booking\""));
        assert!(delivery
            .html
            .contains("data-custom-component-placeholder=\"true\""));
        assert!(!delivery.html.contains("<script"));
    }

    /// Attach one fragment node carrying `slots` to the fixture page.
    fn fixture_with_fragment_slots(
        fragment_id: &str,
        slots: BTreeMap<String, crate::doc::FragmentSlotValue>,
    ) -> (WebDoc, WebTheme) {
        let (mut doc, theme) = fixture();
        let page = doc.pages.get_mut(0).expect("page");
        let host_id = page
            .nodes
            .get(&NodeId::from("hero"))
            .expect("hero")
            .children[0]
            .clone();
        page.nodes
            .get_mut(&host_id)
            .expect("host")
            .children
            .push(NodeId::from("frg_hero"));
        page.nodes.insert(
            NodeId::from("frg_hero"),
            WebNode {
                id: NodeId::from("frg_hero"),
                kind: WebNodeKind::Fragment {
                    fragment_id: fragment_id.to_owned(),
                    slots,
                    text_overrides: Default::default(),
                },
                classes: "w-full py-12".to_owned(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        (doc, theme)
    }

    /// The same page with a fragment node that binds NOTHING — the shape that
    /// proves the artifact is emitted verbatim when no slot is bound.
    fn fixture_with_fragment(fragment_id: &str) -> (WebDoc, WebTheme) {
        fixture_with_fragment_slots(fragment_id, BTreeMap::new())
    }

    /// The same page whose fragment node carries R-A6 text overrides — the one
    /// interior edit a clone allows.
    fn fixture_with_fragment_overrides(
        fragment_id: &str,
        text_overrides: BTreeMap<String, crate::doc::FragmentTextOverride>,
    ) -> (WebDoc, WebTheme) {
        let (mut doc, theme) = fixture_with_fragment(fragment_id);
        let page = doc.pages.get_mut(0).expect("page");
        let node = page.nodes.get_mut(&NodeId::from("frg_hero")).expect("frg");
        if let WebNodeKind::Fragment { text_overrides: on_node, .. } = &mut node.kind {
            *on_node = text_overrides;
        }
        (doc, theme)
    }

    const FRAGMENT_HTML: &str =
        "<section class=\"hero\"><h1 data-lumen-slot=\"headline\">Care, on your terms</h1></section>";

    fn fragment_options(mode: RenderMode, fragment_id: &str) -> RenderOptions {
        fragment_options_with_kinds(mode, fragment_id, BTreeMap::new())
    }

    fn fragment_options_with_kinds(
        mode: RenderMode,
        fragment_id: &str,
        slot_kinds: BTreeMap<String, FragmentSlotKind>,
    ) -> RenderOptions {
        let mut options = match mode {
            RenderMode::Editor => RenderOptions::editor("/asset-store"),
            RenderMode::Delivery => RenderOptions::delivery("/asset-store"),
        };
        options.fragments.insert(
            fragment_id.to_owned(),
            FragmentContent {
                html: FRAGMENT_HTML.to_owned(),
                slot_kinds,
                native_dependencies: None,
            },
        );
        options
    }

    #[test]
    fn fragment_slot_values_are_substituted_at_render_and_the_document_is_untouched() {
        let fragment_id = "frag_0123456789abcdef";
        let (doc, theme) = fixture_with_fragment_slots(
            fragment_id,
            BTreeMap::from([(
                "headline".to_owned(),
                crate::doc::FragmentSlotValue::Text("Talk to us".to_owned()),
            )]),
        );
        let before = serde_json::to_string(&doc).expect("doc json");
        let options = fragment_options_with_kinds(
            RenderMode::Editor,
            fragment_id,
            BTreeMap::from([("headline".to_owned(), FragmentSlotKind::Text)]),
        );

        let rendered = render_page(&doc, &PageId::from("home"), &theme, &options)
            .expect("editor render");
        assert!(
            rendered
                .html
                .contains("<h1 data-lumen-slot=\"headline\">Talk to us</h1>"),
            "{}",
            rendered.html
        );
        // The artifact's own words are the FALLBACK; a bound slot replaces
        // them, and only in the rendered bytes.
        assert!(!rendered.html.contains("Care, on your terms"));
        assert!(rendered.diagnostics.is_empty(), "{:#?}", rendered.diagnostics);
        assert_eq!(
            serde_json::to_string(&doc).expect("doc json"),
            before,
            "substitution must never touch the stored document"
        );

        // Delivery renders the same substitution (no instrumentation).
        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options_with_kinds(
                RenderMode::Delivery,
                fragment_id,
                BTreeMap::from([("headline".to_owned(), FragmentSlotKind::Text)]),
            ),
        )
        .expect("delivery render");
        assert!(delivery
            .html
            .contains("<h1 data-lumen-slot=\"headline\">Talk to us</h1>"));
    }

    #[test]
    fn fragment_text_overrides_render_after_the_slot_pass_and_the_document_is_untouched() {
        // R-A6: the marketer's own words, applied at render on top of the
        // artifact's frozen markup. The artifact is never rewritten and neither
        // is the stored document — an override exists only in these bytes.
        let fragment_id = "frag_0123456789abcdef";
        let (doc, theme) = fixture_with_fragment_overrides(
            fragment_id,
            BTreeMap::from([(
                ":nth-child(1) > :nth-child(1)".to_owned(),
                crate::doc::FragmentTextOverride {
                    text: "Care, on OUR terms".to_owned(),
                    bold: true,
                    italic: false,
                    underline: false,
                    size: Some(1),
                },
            )]),
        );
        let before = serde_json::to_string(&doc).expect("doc json");

        let rendered = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Editor, fragment_id),
        )
        .expect("editor render");
        assert!(
            rendered.html.contains(
                "<h1 data-lumen-slot=\"headline\" \
                 data-lumen-override=\":nth-child(1) &gt; :nth-child(1)\" \
                 data-lumen-size=\"1\" style=\"font-size:1.125em\">\
                 <strong>Care, on OUR terms</strong></h1>"
            ),
            "{}",
            rendered.html
        );
        // The artifact's own words for THAT element are gone from the render.
        assert!(!rendered.html.contains("Care, on your terms"), "{}", rendered.html);
        // …and the edit lands INSIDE the clone's wrapper, not beside it.
        let wrapper_at = rendered
            .html
            .find("data-fragment-root=\"true\"")
            .expect("wrapper");
        let override_at = rendered
            .html
            .find("data-lumen-override")
            .expect("override");
        assert!(wrapper_at < override_at);
        assert!(rendered.diagnostics.is_empty(), "{:#?}", rendered.diagnostics);
        assert_eq!(
            serde_json::to_string(&doc).expect("doc json"),
            before,
            "an override must never touch the stored document"
        );

        // Delivery renders the same edit (no instrumentation around it).
        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Delivery, fragment_id),
        )
        .expect("delivery render");
        assert!(
            delivery.html.contains("<strong>Care, on OUR terms</strong>"),
            "{}",
            delivery.html
        );
        assert!(!delivery.html.contains("Care, on your terms"));
    }

    #[test]
    fn fragment_renders_its_artifact_html_in_flow_under_the_wrapper_class() {
        let fragment_id = "frag_0123456789abcdef";
        let (doc, theme) = fixture_with_fragment(fragment_id);

        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Editor, fragment_id),
        )
        .expect("editor render");
        // The wrapper carries the platform hook, the SCOPED class the
        // artifact's own CSS is written under, and the node's own utilities.
        assert!(
            editor.html.contains(
                "<div class=\"lumen-fragment lumen-frag-0123456789abcdef w-full py-12\" \
                 data-lumen-fragment=\"true\" data-node-id=\"frg_hero\" data-fragment-root=\"true\">"
            ),
            "{}",
            editor.html
        );
        // The artifact's markup lands VERBATIM, slot markers intact — the
        // marker's own content IS the fallback until F1.4 substitutes.
        assert!(editor.html.contains(FRAGMENT_HTML));
        // In flow: the wrapper is a plain block in the body, not an iframe.
        assert!(!editor.html.contains("lumen-fragment-placeholder"));
        assert!(editor.diagnostics.is_empty(), "{:#?}", editor.diagnostics);

        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Delivery, fragment_id),
        )
        .expect("delivery render");
        assert!(delivery.html.contains(
            "<div class=\"lumen-fragment lumen-frag-0123456789abcdef w-full py-12\" data-lumen-fragment=\"true\">"
        ));
        assert!(delivery.html.contains(FRAGMENT_HTML));
        assert!(!delivery.html.contains("data-node-id"));
    }

    #[test]
    fn a_fragment_wrapper_is_marked_as_a_clone_root_for_the_editor_bridge_only() {
        // Slice 2 / R-A1: everything inside a cloned band is the artifact's own markup
        // and carries no node id, so the bridge addresses an element in there by
        // structural path from the wrapper. It can only know to do that if the wrapper
        // says it is a clone root — and it must say so ONLY where the rest of the
        // editor instrumentation lives, never in a delivered page.
        let fragment_id = "frag_0123456789abcdef";
        let (doc, theme) = fixture_with_fragment(fragment_id);

        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Editor, fragment_id),
        )
        .expect("editor render");
        assert!(
            editor
                .html
                .contains("data-node-id=\"frg_hero\" data-fragment-root=\"true\""),
            "{}",
            editor.html
        );

        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Delivery, fragment_id),
        )
        .expect("delivery render");
        assert!(!delivery.html.contains("data-fragment-root"));
    }

    #[test]
    fn fragment_wrapper_class_is_derived_from_the_id_not_re_spelled() {
        // The Python side mints `lumen-frag-<16 hex>` (fragment_wrapper_class)
        // and scopes the stored CSS under exactly that. A re-spelling here —
        // `lumen-frag-frag_…`, or the whole id — renders the section unstyled.
        assert_eq!(
            fragment_wrapper_class("frag_abcdef0123456789").as_deref(),
            Some("lumen-frag-abcdef0123456789")
        );
        assert_eq!(fragment_wrapper_class("frag_nothex").as_deref(), None);
        assert_eq!(fragment_wrapper_class("ccart_0123456789abcdef"), None);
    }

    #[test]
    fn an_unresolved_fragment_renders_a_placeholder_not_a_hole() {
        // Mirrors the custom-component missing-pin behavior: the F1.2 gate
        // deliberately keeps a document with a dead pin loadable, so render
        // must degrade loudly rather than fail the page.
        let fragment_id = "frag_0123456789abcdef";
        let (doc, theme) = fixture_with_fragment_slots(
            fragment_id,
            BTreeMap::from([(
                "headline".to_owned(),
                crate::doc::FragmentSlotValue::Text("Talk to us".to_owned()),
            )]),
        );
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::editor("/asset-store"),
        )
        .expect("render");
        assert!(
            output
                .html
                .contains("data-fragment-placeholder=\"true\""),
            "{}",
            output.html
        );
        assert!(output.html.contains("data-node-id=\"frg_hero\""));
        // The id is a validated 16-hex address, so naming it is safe and it
        // is the one thing an operator needs to chase the missing artifact.
        assert!(output
            .html
            .contains("data-fragment-id=\"frag_0123456789abcdef\""));
        // No slot value and no invented markup.
        assert!(!output.html.contains("Talk to us"));
        let codes: Vec<&str> = output
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code.as_str())
            .collect();
        assert_eq!(codes, vec!["LUMW0412"]);
    }

    #[test]
    fn an_invalid_fragment_id_is_never_interpolated_into_the_wrapper() {
        // A document loaded from storage may never have been through
        // validate_web_doc, so the arm re-checks the grammar before the id
        // reaches a class attribute.
        let hostile = "frag_\"><style>";
        let (doc, theme) = fixture_with_fragment(hostile);
        let mut options = RenderOptions::editor("/asset-store");
        options.fragments.insert(
            hostile.to_owned(),
            FragmentContent {
                html: FRAGMENT_HTML.to_owned(),
                slot_kinds: BTreeMap::new(),
                native_dependencies: None,
            },
        );
        let output = render_page(&doc, &PageId::from("home"), &theme, &options).expect("render");
        // Not escaped — absent. The id never reaches the body at all.
        let body = output.html.split("<body").nth(1).expect("body");
        assert!(!body.contains("<style"));
        assert!(!output.html.contains("frag_\""));
        assert!(!output.html.contains("frag_&quot;"));
        assert!(!output.html.contains("lumen-frag-"));
        assert!(!output.html.contains(FRAGMENT_HTML));
        assert!(output.html.contains("data-fragment-placeholder=\"true\""));
        let codes: Vec<&str> = output
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code.as_str())
            .collect();
        assert_eq!(codes, vec!["LUMW0411"]);
    }

    #[test]
    fn page_fragment_ids_lists_every_reachable_fragment_once() {
        let fragment_id = "frag_0123456789abcdef";
        let (mut doc, _theme) = fixture_with_fragment(fragment_id);
        assert_eq!(
            page_fragment_ids(&doc, &PageId::from("home")),
            vec![fragment_id.to_owned()]
        );
        // A second node on the SAME artifact resolves once; an unreachable
        // node is not a reference at all.
        let page = doc.pages.get_mut(0).expect("page");
        let host_id = page
            .nodes
            .get(&NodeId::from("hero"))
            .expect("hero")
            .children[0]
            .clone();
        page.nodes
            .get_mut(&host_id)
            .expect("host")
            .children
            .push(NodeId::from("frg_twin"));
        page.nodes.insert(
            NodeId::from("frg_twin"),
            WebNode {
                id: NodeId::from("frg_twin"),
                kind: WebNodeKind::Fragment {
                    fragment_id: fragment_id.to_owned(),
                    slots: Default::default(),
                    text_overrides: Default::default(),
                },
                classes: String::new(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        page.nodes.insert(
            NodeId::from("frg_orphan"),
            WebNode {
                id: NodeId::from("frg_orphan"),
                kind: WebNodeKind::Fragment {
                    fragment_id: "frag_fedcba9876543210".to_owned(),
                    slots: Default::default(),
                    text_overrides: Default::default(),
                },
                classes: String::new(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        assert_eq!(
            page_fragment_ids(&doc, &PageId::from("home")),
            vec![fragment_id.to_owned()]
        );
    }

    #[test]
    fn fragment_css_lands_in_the_head_where_compiled_utilities_outrank_it() {
        // The cascade ruling: fragment CSS is spliced through the theme's base
        // layer, so it sits in the head BEFORE any compiled utility sheet and
        // (in editor mode) inside `@layer base` — a Tailwind utility therefore
        // wins a tie. Fragment selectors are scoped, which is what makes that
        // acceptable; the collision diagnostic at the API layer is the guard.
        let fragment_css = ".lumen-frag-0123456789abcdef .hero { padding: 64px }";
        let (theme, _) = compile_web_theme(
            None,
            &WebThemeRef::default(),
            &WebThemeOptions {
                font_face_css: None,
                fragment_css: Some(fragment_css.to_owned()),
            },
        );
        assert!(theme.base_css.contains(fragment_css));

        let fragment_id = "frag_0123456789abcdef";
        let (doc, _) = fixture_with_fragment(fragment_id);
        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Editor, fragment_id),
        )
        .expect("editor render");
        let css_at = editor.html.find(fragment_css).expect("fragment css in head");
        let head_end = editor.html.find("</head>").expect("head");
        assert!(css_at < head_end, "fragment css must be in the head");
        // Inside the editor's base layer, which the Tailwind runtime's
        // utilities layer outranks.
        let layer_at = editor.html.find("@layer base").expect("base layer");
        assert!(layer_at < css_at);
        // ...and before the custom-css / platform blocks that follow it.
        assert!(css_at < editor.html.find("</body>").expect("body"));

        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &fragment_options(RenderMode::Delivery, fragment_id),
        )
        .expect("delivery render");
        let delivery_css_at = delivery.html.find(fragment_css).expect("fragment css");
        assert!(delivery_css_at < delivery.html.find("</head>").expect("head"));
    }

    #[test]
    fn custom_component_runtime_is_nested_sandboxed_and_editor_selectable() {
        let (mut doc, theme) = fixture();
        let page = doc.pages.get_mut(0).expect("page");
        let host_id = page
            .nodes
            .get(&NodeId::from("hero"))
            .expect("hero")
            .children[0]
            .clone();
        page.nodes
            .get_mut(&host_id)
            .expect("host")
            .children
            .push(NodeId::from("cc_runtime"));
        let artifact_id = format!("ccart_{}", "d".repeat(64));
        page.nodes.insert(
            NodeId::from("cc_runtime"),
            WebNode {
                id: NodeId::from("cc_runtime"),
                kind: WebNodeKind::CustomComponent {
                    slug: "runtime-card".to_owned(),
                    artifact_id: artifact_id.clone(),
                    props: std::collections::BTreeMap::new(),
                },
                classes: "w-full min-h-[160px]".to_owned(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        let runtime = CustomComponentRuntimeFrame {
            state: "ready".to_owned(),
            artifact_id: artifact_id.clone(),
            name: "Runtime Card".to_owned(),
            srcdoc: Some("<!doctype html><h2>First & ready</h2>".to_owned()),
            runtime_nonce: Some("runtime-nonce-123".to_owned()),
            message: None,
            error_code: None,
            intrinsic_height: true,
            warning_count: 2,
        };

        let mut editor_options = RenderOptions::editor("/asset-store");
        editor_options
            .custom_component_runtimes
            .insert("cc_runtime".to_owned(), runtime.clone());
        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &editor_options,
        )
        .expect("editor runtime");
        assert!(editor.html.contains(
            "class=\"lumen-custom-component-runtime w-full min-h-[160px]\""
        ));
        assert_eq!(
            editor
                .html
                .matches("data-custom-component-editor=\"true\"")
                .count(),
            2
        );
        assert!(editor.html.contains("sandbox=\"allow-scripts\""));
        assert!(!editor.html.contains("allow-same-origin"));
        assert!(editor.html.contains("credentialless"));
        assert!(editor.html.contains("tabindex=\"-1\""));
        assert!(!editor
            .html
            .contains("tabindex=\"-1\" aria-hidden=\"true\""));
        assert!(editor
            .html
            .contains("srcdoc=\"&lt;!doctype html&gt;&lt;h2&gt;First &amp; ready&lt;/h2&gt;\""));
        assert!(editor
            .html
            .contains("data-custom-component-warning-count=\"2\""));
        assert!(editor.html.contains("pointer-events: none"));

        let mut delivery_options = RenderOptions::delivery("/asset-store");
        delivery_options
            .custom_component_runtimes
            .insert("cc_runtime".to_owned(), runtime);
        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &delivery_options,
        )
        .expect("delivery runtime");
        assert_eq!(
            delivery
                .html
                .matches("data-custom-component-editor=\"true\"")
                .count(),
            1
        );
        assert!(!delivery.html.contains("tabindex=\"-1\""));
        assert!(delivery.html.contains("title=\"Runtime Card component\""));
        assert!(!delivery.html.contains("data-node-id=\"cc_runtime\""));
    }

    #[test]
    fn delivery_mode_has_zero_instrumentation() {
        let (doc, theme) = fixture();
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        assert!(!output.html.contains("data-node-id"));
        assert!(!output.html.contains("<script"));
        assert!(!output.html.contains("text/tailwindcss"));
        assert!(!output.html.contains("@layer base"));
        // A component-free page pulls in neither the platform CSS nor runtime.
        assert!(!output.html.contains("lumen-platform"));
        // Semantic styling hooks stay.
        assert!(output.html.contains("data-tv=\"display\""));
        assert!(output.html.contains("data-btn=\"primary\""));
        assert!(output.html.contains("<section id=\"hero\""));
        assert!(output.html.contains(":root"));
        assert!(output.html.contains("--color-primary:"));
    }

    #[test]
    fn clickable_container_and_scrimmed_background_render_in_editor_and_delivery() {
        let (mut doc, theme) = fixture();
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="hero" data-background-asset="hero_img" data-background-position="top" data-scrim-color="dark" data-scrim-opacity="60">
                 <div id="story" class="p-6" data-href="/story" data-new-tab="true">
                   <p>Read the story</p>
                 </div>
               </section>"#,
            &theme,
        );
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);

        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("delivery");
        assert!(delivery
            .html
            .contains("<a href=\"/story\" data-lumen-container-link target=\"_blank\" rel=\"noopener noreferrer\" class=\"p-6\">"));
        assert!(delivery.html.contains("background-size:cover"));
        assert!(delivery.html.contains("background-position:top"));
        assert!(delivery.html.contains("var(--color-dark) 60%"));
        assert!(delivery.html.contains("url('/asset-store/abc123')"));
        assert!(!delivery.html.contains("data-node-id=\"story\""));

        let editor = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::editor("/asset-store"),
        )
        .expect("editor");
        assert!(editor.html.contains("data-node-id=\"story\""));
        assert!(editor.html.contains("href=\"/story\""));
    }

    #[test]
    fn inline_markup_renders_verbatim_and_escaped_title() {
        let (mut doc, theme) = fixture();
        doc.title = "A <B> & C".to_owned();
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        assert!(output.html.contains("<title>A &lt;B&gt; &amp; C</title>"));
        assert!(output.html.contains("Hello <strong>world</strong>"));
    }

    #[test]
    fn structured_body_delivery_is_semantic_and_editor_independent() {
        let (doc, theme) = component_fixture(
            r#"<section id="story">
                 <div id="story_copy" data-text="rich" data-variant="body">
                   <p>Intro <strong>copy</strong></p>
                   <ol><li>First</li><li>Second<ul><li>Nested</li></ul></li></ol>
                 </div>
               </section>"#,
        );
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("delivery");
        assert!(output.html.contains(
            "<div data-tv=\"body\"><p>Intro <strong>copy</strong></p>\
             <ol><li>First</li><li>Second<ul><li>Nested</li></ul></li></ol></div>"
        ));
        assert!(!output.html.contains("data-lexical"));
        assert!(!output.html.contains("contenteditable"));
        assert!(!output.html.contains("data-node-id=\"story_copy\""));
    }

    #[test]
    fn custom_css_cannot_terminate_its_style_element() {
        let (mut doc, theme) = fixture();
        doc.custom_css = ".x{color:red}</StYle><script>alert(1)</script>".to_owned();
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        assert!(!output.html.to_ascii_lowercase().contains("</style><script"));
        assert!(output.html.contains("\\3c /style"));
        // The payload stays inert raw text INSIDE the style element: the
        // number of real </style> closers must equal the number of <style>
        // openers (the injection added no element boundary).
        let lower = output.html.to_ascii_lowercase();
        assert_eq!(
            lower.matches("<style").count(),
            lower.matches("</style").count(),
        );
    }

    fn component_fixture(html: &str) -> (WebDoc, WebTheme) {
        let (theme, _) =
            compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default());
        let mut doc = WebDoc::new("d1", "Components", None);
        let outcome = ingest_html_into_page(&mut doc, &PageId::from("home"), html, &theme);
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        (doc, theme)
    }

    #[test]
    fn dialog_and_command_button_markup_and_runtime() {
        let (doc, theme) = component_fixture(
            r#"<section id="s">
                 <a data-button="primary" data-command="show-modal" data-target="dlg_book">Book</a>
                 <div data-component="dialog" id="dlg_book" data-aria-label="Booking">
                   <p>Pick a time.</p>
                 </div>
               </section>"#,
        );
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        // Dialog markup.
        assert!(output
            .html
            .contains("<dialog id=\"dlg_book\" data-lumen-dialog=\"true\""));
        assert!(output.html.contains("aria-label=\"Booking\""));
        assert!(output
            .html
            .contains("class=\"lumen-dialog-close\" commandfor=\"dlg_book\" command=\"close\""));
        // Command button markup.
        assert!(output.html.contains("<button type=\"button\""));
        assert!(output.html.contains("commandfor=\"dlg_book\""));
        assert!(output.html.contains("command=\"show-modal\""));
        // Exactly one script (the runtime) even in delivery, and the CSS.
        assert_eq!(output.html.matches("<script").count(), 1);
        assert!(output.html.contains("__lumenRuntimeV2"));
        assert!(output.html.contains("lumen-platform v2"));
    }

    #[test]
    fn accordion_details_structure() {
        let (doc, theme) = component_fixture(
            r#"<section id="s">
                 <div data-component="accordion" id="faq" data-single-open="true" data-default-open="1">
                   <div><h3>Q1</h3><p>A1</p></div>
                   <div><h3>Q2</h3><p>A2</p></div>
                 </div>
               </section>"#,
        );
        let output = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        assert_eq!(
            output
                .html
                .matches("<details data-lumen-acc-item=\"true\"")
                .count(),
            2
        );
        assert!(output.html.contains("<summary>"));
        // single_open ⇒ shared name; default_open=1 ⇒ the second item is open.
        assert_eq!(output.html.matches("name=\"faq\"").count(), 2);
        assert_eq!(output.html.matches(" open>").count(), 1);
        // Accordion alone needs the CSS but no runtime script.
        assert!(output.html.contains("lumen-platform v2"));
        assert!(!output.html.contains("<script"));
    }

    #[test]
    fn marquee_two_tracks_and_suppressed_clone() {
        let (doc, theme) = component_fixture(
            r#"<section id="s">
                 <div data-component="marquee" id="strip" data-speed="20" data-direction="right" class="py-4">
                   <p id="logo_txt">logo</p>
                 </div>
               </section>"#,
        );
        // Delivery: two tracks, aria-hidden clone, duration var, merged class.
        let delivery = render_page(
            &doc,
            &PageId::from("home"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .expect("render");
        assert_eq!(
            delivery.html.matches("class=\"lumen-marquee-track").count(),
            2
        );
        assert!(delivery
            .html
            .contains("class=\"lumen-marquee-track\" aria-hidden=\"true\""));
        assert!(delivery.html.contains("--lumen-marquee-duration:20s"));
        assert!(delivery.html.contains("class=\"lumen-marquee py-4\""));
        assert!(delivery.html.contains("data-direction=\"right\""));
        // Marquee alone: CSS but no runtime.
        assert!(delivery.html.contains("lumen-platform v2"));
        assert!(!delivery.html.contains("<script"));

        // Editor: the aria-hidden clone must not repeat the bridge hook.
        let mut editor_options = RenderOptions::editor("/asset-store");
        editor_options.tailwind_runtime_src = Some("/tw.js".to_owned());
        let editor = render_page(&doc, &PageId::from("home"), &theme, &editor_options)
            .expect("render editor");
        assert_eq!(editor.html.matches("data-node-id=\"logo_txt\"").count(), 1);
    }

    #[test]
    fn missing_page_is_fatal() {
        let (doc, theme) = fixture();
        let err = render_page(
            &doc,
            &PageId::from("nope"),
            &theme,
            &RenderOptions::delivery("/asset-store"),
        )
        .unwrap_err();
        assert_eq!(err[0].code, "LUMW0400");
    }
}
