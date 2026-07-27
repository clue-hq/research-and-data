//! Tree → HTML renderer. One code path, two targets.
//!
//! Editor mode adds `data-node-id` on every element (the selection bridge's
//! hit-test hook), the Tailwind v4 browser runtime, and an optional bridge
//! script — served into a sandboxed `srcdoc` iframe. Delivery mode emits
//! clean semantic HTML with zero instrumentation (asserted in tests); the
//! static Tailwind utility compile joins at the export phase. The `data-tv`
//! / `data-btn` attributes appear in both modes: they are the theme base
//! layer's styling hooks, not instrumentation.

use crate::doc::{WebDoc, WebNodeKind};
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
        render_node(doc, page_id, child, theme, options, &mut body, &mut diagnostics);
    }

    let editor = options.mode == RenderMode::Editor;
    let mut html = String::with_capacity(body.len() + theme.base_css.len() + 2048);
    html.push_str("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n");
    html.push_str("<meta charset=\"utf-8\">\n");
    html.push_str("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n");
    html.push_str(&format!("<title>{}</title>\n", escape_text(&doc.title)));
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
    html.push_str(&format!("<style>\n{}\n</style>\n", theme.base_css));
    if !doc.custom_css.trim().is_empty() {
        html.push_str(&format!(
            "<style>\n{}\n</style>\n",
            css_style_safe(&doc.custom_css)
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

fn render_node(
    doc: &WebDoc,
    page_id: &PageId,
    node_id: &NodeId,
    theme: &WebTheme,
    options: &RenderOptions,
    out: &mut String,
    diagnostics: &mut Vec<Diagnostic>,
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
        if editor {
            out.push_str(&format!(" data-node-id=\"{}\"", escape_attr(node.id.as_str())));
        }
    };
    let class_attr = |out: &mut String| {
        if !node.classes.trim().is_empty() {
            out.push_str(&format!(" class=\"{}\"", escape_attr(node.classes.trim())));
        }
    };

    match &node.kind {
        WebNodeKind::Section { tag, anchor_id } => {
            let tag = tag.as_str();
            out.push('<');
            out.push_str(tag);
            let anchor = anchor_id.as_deref().unwrap_or(node.id.as_str());
            out.push_str(&format!(" id=\"{}\"", escape_attr(anchor)));
            node_attr(out);
            class_attr(out);
            out.push('>');
            for child in &node.children {
                render_node(doc, page_id, child, theme, options, out, diagnostics);
            }
            out.push_str(&format!("</{tag}>"));
        }
        WebNodeKind::Container => {
            out.push_str("<div");
            node_attr(out);
            class_attr(out);
            out.push('>');
            for child in &node.children {
                render_node(doc, page_id, child, theme, options, out, diagnostics);
            }
            out.push_str("</div>");
        }
        WebNodeKind::Text { variant, content } => {
            let tag = variant.render_tag();
            out.push('<');
            out.push_str(tag);
            out.push_str(&format!(" data-tv=\"{}\"", variant.as_str()));
            node_attr(out);
            class_attr(out);
            out.push('>');
            // Content is sanitized restricted inline markup, stored canonical.
            out.push_str(content);
            out.push_str(&format!("</{tag}>"));
        }
        WebNodeKind::Button {
            label,
            href,
            variant,
            new_tab,
        } => {
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
                    format!("image `{}` asset `{asset_id}` has no resolvable bytes", node.id),
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
                out.push_str(&format!("><path d=\"{}\"/></svg>", escape_attr(def.path_data)));
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
        WebNodeKind::Embed { html } => {
            out.push_str("<iframe sandbox=\"\" srcdoc=\"");
            out.push_str(&escape_attr(html));
            out.push('"');
            node_attr(out);
            class_attr(out);
            out.push_str("></iframe>");
        }
    }
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
        // Semantic styling hooks stay.
        assert!(output.html.contains("data-tv=\"display\""));
        assert!(output.html.contains("data-btn=\"primary\""));
        assert!(output.html.contains("<section id=\"hero\""));
        assert!(output.html.contains(":root"));
        assert!(output.html.contains("--color-primary:"));
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
