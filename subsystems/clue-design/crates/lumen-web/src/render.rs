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
    calendly_url_is_valid, ButtonAction, ComponentSpec, EmbedProvider, MarqueeDirection,
    WebBackgroundImage, WebDoc, WebNode, WebNodeKind,
};
use crate::runtime::{PLATFORM_CSS, PLATFORM_RUNTIME_JS};
use crate::theme::WebTheme;
use crate::util::{escape_attr, escape_text};
use lumen_core::{Diagnostic, DiagnosticSubject, NodeId, PageId, Phase};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RenderMode {
    Editor,
    Delivery,
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
}

impl RenderOptions {
    pub fn delivery(asset_base_url: impl Into<String>) -> Self {
        Self {
            mode: RenderMode::Delivery,
            asset_base_url: asset_base_url.into(),
            tailwind_runtime_src: None,
            bridge_script: None,
        }
    }

    pub fn editor(asset_base_url: impl Into<String>) -> Self {
        Self {
            mode: RenderMode::Editor,
            asset_base_url: asset_base_url.into(),
            tailwind_runtime_src: None,
            bridge_script: None,
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
            Some(WebNodeKind::Component { .. } | WebNodeKind::Embed { .. })
        )
    })
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
    let needs_runtime = page_needs_runtime(doc, page_id);
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
    // Platform component base styles, versioned with the runtime; emitted in
    // both modes only when the page actually uses a Component node.
    if uses_components {
        html.push_str(&format!("<style>\n{PLATFORM_CSS}\n</style>\n"));
    }
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
    html.push_str("</head>\n<body>\n");
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
            let tag = variant.render_tag();
            out.push('<');
            out.push_str(tag);
            out.push_str(&format!(" data-tv=\"{}\"", variant.as_str()));
            node_attr(out);
            class_attr(out);
            out.push('>');
            out.push_str(&content.to_inline_html());
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
                    "<button type=\"button\" class=\"lumen-dialog-close\" commandfor=\"{}\" command=\"close\" aria-label=\"Close\">&#215;</button>",
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

fn asset_src(record: &lumen_core::AssetRecord, asset_base_url: &str) -> Option<String> {
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
