//! Structural validation for web documents (`LUMW00xx`).
//!
//! Invariants: exactly-one-parent arena, root children are Sections only,
//! only branches hold children, bounded depth, resolvable asset/icon
//! references, allowed hrefs, canonical inline content, and a custom_css
//! escape hatch that cannot smuggle imports or script schemes.

use crate::doc::{ButtonAction, ComponentSpec, WebDoc, WebNodeKind, MAX_TREE_DEPTH, WEB_SCHEMA_VERSION};
use crate::inline::sanitize_inline;
use crate::util::href_is_allowed;
use lumen_core::{Diagnostic, DiagnosticSubject, NodeId, Phase};
use std::collections::{BTreeMap, BTreeSet};

pub fn validate_web_doc(doc: &WebDoc) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    if doc.schema_version != WEB_SCHEMA_VERSION {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0001",
            format!(
                "unsupported schema_version {} (expected {WEB_SCHEMA_VERSION})",
                doc.schema_version
            ),
            None,
        ));
    }
    if doc.pages.is_empty() {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0002",
            "document has no pages",
            None,
        ));
    }
    let mut seen_routes = BTreeSet::new();
    let mut seen_pages = BTreeSet::new();
    for page in &doc.pages {
        if !seen_pages.insert(page.id.clone()) {
            diagnostics.push(Diagnostic::error(
                Phase::Web,
                "LUMW0003",
                format!("duplicate page id `{}`", page.id),
                Some(DiagnosticSubject::Page(page.id.clone())),
            ));
        }
        if !seen_routes.insert(page.route.clone()) {
            diagnostics.push(Diagnostic::error(
                Phase::Web,
                "LUMW0004",
                format!("duplicate route `{}`", page.route),
                Some(DiagnosticSubject::Page(page.id.clone())),
            ));
        }
        validate_page(doc, page, &mut diagnostics);
    }

    let css = doc.custom_css.to_ascii_lowercase();
    if css.contains("@import") || css.contains("javascript:") || css.contains("</style") {
        diagnostics.push(
            Diagnostic::error(
                Phase::Web,
                "LUMW0013",
                "custom_css may not contain @import, javascript: URLs, or a </style sequence",
                None,
            )
            .with_hint("Inline plain CSS only; the renderer additionally escapes </style as defense in depth."),
        );
    }

    diagnostics
}

fn validate_page(doc: &WebDoc, page: &crate::doc::WebPage, diagnostics: &mut Vec<Diagnostic>) {
    let subject_page = || Some(DiagnosticSubject::Page(page.id.clone()));
    let Some(root) = page.nodes.get(&page.root) else {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0005",
            format!("page `{}` root `{}` is missing", page.id, page.root),
            subject_page(),
        ));
        return;
    };
    if !matches!(root.kind, WebNodeKind::Container) {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0006",
            format!("page `{}` root must be a container", page.id),
            Some(DiagnosticSubject::Node(root.id.clone())),
        ));
    }

    // Parent multiplicity + child resolution.
    let mut parent_count: BTreeMap<&NodeId, usize> = BTreeMap::new();
    for node in page.nodes.values() {
        if !node.kind.is_branch() && !node.children.is_empty() {
            diagnostics.push(Diagnostic::error(
                Phase::Web,
                "LUMW0007",
                format!(
                    "{} node `{}` cannot have children",
                    node.kind.kind_name(),
                    node.id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }
        for child in &node.children {
            if !page.nodes.contains_key(child) {
                diagnostics.push(Diagnostic::error(
                    Phase::Web,
                    "LUMW0008",
                    format!("node `{}` lists missing child `{child}`", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
            *parent_count.entry(child).or_default() += 1;
        }
    }
    for (child, count) in &parent_count {
        if *count > 1 {
            diagnostics.push(Diagnostic::error(
                Phase::Web,
                "LUMW0009",
                format!("node `{child}` has {count} parents"),
                Some(DiagnosticSubject::Node((*child).clone())),
            ));
        }
    }
    if parent_count.contains_key(&page.root) {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0009",
            format!("page root `{}` may not appear as a child", page.root),
            Some(DiagnosticSubject::Node(page.root.clone())),
        ));
    }

    // Depth + reachability walk (cycle-safe via visited set).
    let mut visited: BTreeSet<NodeId> = BTreeSet::new();
    let mut stack: Vec<(NodeId, usize)> = vec![(page.root.clone(), 0)];
    while let Some((id, depth)) = stack.pop() {
        if !visited.insert(id.clone()) {
            continue;
        }
        if depth > MAX_TREE_DEPTH {
            diagnostics.push(Diagnostic::error(
                Phase::Web,
                "LUMW0010",
                format!("node `{id}` exceeds maximum depth {MAX_TREE_DEPTH}"),
                Some(DiagnosticSubject::Node(id.clone())),
            ));
            continue;
        }
        if let Some(node) = page.nodes.get(&id) {
            if depth == 1 && !matches!(node.kind, WebNodeKind::Section { .. }) {
                diagnostics.push(Diagnostic::error(
                    Phase::Web,
                    "LUMW0011",
                    format!(
                        "top-level node `{id}` is {}; the page root may only hold sections",
                        node.kind.kind_name()
                    ),
                    Some(DiagnosticSubject::Node(id.clone())),
                ));
            }
            for child in node.children.iter().rev() {
                stack.push((child.clone(), depth + 1));
            }
        }
    }
    for node in page.nodes.values() {
        if !visited.contains(&node.id) {
            diagnostics.push(Diagnostic::warning(
                Phase::Web,
                "LUMW0012",
                format!("node `{}` is unreachable from the page root", node.id),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }
    }

    // Reference + content checks.
    for node in page.nodes.values() {
        match &node.kind {
            WebNodeKind::Image { asset_id, href, .. } => {
                if !doc.assets.contains_key(asset_id) {
                    diagnostics.push(Diagnostic::error(
                        Phase::Web,
                        "LUMW0014",
                        format!("image `{}` references unknown asset `{asset_id}`", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
                if let Some(href) = href {
                    if !href_is_allowed(href) {
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0016",
                            format!("image `{}` href is not allowed: {href}", node.id),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
            }
            WebNodeKind::Icon { icon } => {
                if lumen_core::icons::resolve_icon(icon).is_none() {
                    diagnostics.push(Diagnostic::error(
                        Phase::Web,
                        "LUMW0015",
                        format!("icon `{}` on `{}` is unknown", icon, node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            WebNodeKind::Button { action, .. } => match action {
                ButtonAction::Href { href, .. } => {
                    if !href_is_allowed(href) {
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0016",
                            format!("button `{}` href is not allowed: {href}", node.id),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
                ButtonAction::Command { command_target, .. } => {
                    let targets_dialog = page.nodes.get(command_target).is_some_and(|target| {
                        matches!(
                            &target.kind,
                            WebNodeKind::Component {
                                spec: ComponentSpec::Dialog { .. }
                            }
                        )
                    });
                    if !targets_dialog {
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0018",
                            format!(
                                "button `{}` command targets `{command_target}` which is missing/not a dialog",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
            },
            WebNodeKind::Component {
                spec: ComponentSpec::Accordion { .. },
            } => {
                for child_id in &node.children {
                    let is_item = page.nodes.get(child_id).is_some_and(|child| {
                        matches!(child.kind, WebNodeKind::Container) && child.children.len() >= 2
                    });
                    if !is_item {
                        diagnostics.push(Diagnostic::warning(
                            Phase::Web,
                            "LUMW0019",
                            format!(
                                "accordion `{}` item `{child_id}` is not a container with a summary and content; it renders unfolded",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(child_id.clone())),
                        ));
                    }
                }
            }
            WebNodeKind::Component {
                spec: ComponentSpec::Dialog { .. },
            } => {
                // Warn on a dialog reachable inside another dialog: nesting the
                // top layer is rarely intended.
                let mut stack: Vec<NodeId> = node.children.clone();
                let mut seen: BTreeSet<NodeId> = BTreeSet::new();
                while let Some(current) = stack.pop() {
                    if !seen.insert(current.clone()) {
                        continue;
                    }
                    if let Some(descendant) = page.nodes.get(&current) {
                        if matches!(
                            &descendant.kind,
                            WebNodeKind::Component {
                                spec: ComponentSpec::Dialog { .. }
                            }
                        ) {
                            diagnostics.push(Diagnostic::warning(
                                Phase::Web,
                                "LUMW0020",
                                format!(
                                    "dialog `{}` nests dialog `{current}`; top-layer stacking is rarely intended",
                                    node.id
                                ),
                                Some(DiagnosticSubject::Node(current.clone())),
                            ));
                        }
                        for child in &descendant.children {
                            stack.push(child.clone());
                        }
                    }
                }
            }
            WebNodeKind::Text { content, .. } => {
                let canonical = sanitize_inline(content);
                if canonical.html != *content {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Web,
                        "LUMW0017",
                        format!("text `{}` content is not canonical inline markup", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::{TextVariant, WebDoc, WebNode, WebThemeRef};
    use crate::ingest::ingest_html_into_page;
    use crate::theme::{compile_web_theme, WebThemeOptions};
    use lumen_core::{DiagnosticSeverity, PageId};

    fn clean_doc() -> WebDoc {
        let (theme, _) =
            compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default());
        let mut doc = WebDoc::new("d1", "Site", None);
        let outcome = ingest_html_into_page(
            &mut doc,
            &PageId::from("home"),
            r#"<section id="hero"><div><h1>Hi</h1></div></section>"#,
            &theme,
        );
        assert!(!outcome.has_errors());
        doc
    }

    #[test]
    fn clean_document_validates() {
        let diagnostics = validate_web_doc(&clean_doc());
        assert!(
            diagnostics
                .iter()
                .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
            "{diagnostics:#?}"
        );
    }

    #[test]
    fn empty_new_doc_validates() {
        let diagnostics = validate_web_doc(&WebDoc::new("d1", "Empty", None));
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
    }

    #[test]
    fn detects_orphans_missing_children_and_bad_refs() {
        let mut doc = clean_doc();
        let page = doc.pages.get_mut(0).unwrap();
        // Orphan node.
        page.nodes.insert(
            lumen_core::NodeId::from("orphan"),
            WebNode {
                id: lumen_core::NodeId::from("orphan"),
                kind: WebNodeKind::Text {
                    variant: TextVariant::Body,
                    content: "x".to_owned(),
                },
                classes: String::new(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        // Missing child reference.
        page.nodes
            .get_mut(&lumen_core::NodeId::from("hero"))
            .unwrap()
            .children
            .push(lumen_core::NodeId::from("ghost"));
        let codes: Vec<String> = validate_web_doc(&doc)
            .iter()
            .map(|diagnostic| diagnostic.code.clone())
            .collect();
        assert!(codes.contains(&"LUMW0012".to_owned()), "{codes:?}");
        assert!(codes.contains(&"LUMW0008".to_owned()), "{codes:?}");
    }

    #[test]
    fn custom_css_import_is_rejected() {
        let mut doc = clean_doc();
        doc.custom_css = "@import url('https://evil.example/x.css');".to_owned();
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0013"));
    }

    #[test]
    fn custom_css_style_escape_is_rejected() {
        let mut doc = clean_doc();
        doc.custom_css = "x{}</StYle><script>alert(1)</script>".to_owned();
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0013"));
    }

    fn ingest_doc(html: &str) -> WebDoc {
        let (theme, _) =
            compile_web_theme(None, &WebThemeRef::default(), &WebThemeOptions::default());
        let mut doc = WebDoc::new("d1", "Site", None);
        let outcome = ingest_html_into_page(&mut doc, &PageId::from("home"), html, &theme);
        assert!(!outcome.has_errors(), "{:#?}", outcome.diagnostics);
        doc
    }

    #[test]
    fn command_button_target_must_be_a_dialog() {
        let doc = ingest_doc(
            r#"<section id="s"><a data-button="primary" data-command="show-modal" data-target="ghost">Open</a></section>"#,
        );
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0018"));
    }

    #[test]
    fn accordion_item_shape_warns() {
        let doc = ingest_doc(
            r#"<section id="s"><div data-component="accordion" id="faq"><p>lonely</p></div></section>"#,
        );
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0019"));
    }

    #[test]
    fn nested_dialog_warns() {
        let doc = ingest_doc(
            r#"<section id="s"><div data-component="dialog" id="d1"><div data-component="dialog" id="d2"><p>x</p></div></div></section>"#,
        );
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0020"));
    }

    #[test]
    fn all_three_components_validate_clean() {
        let doc = ingest_doc(
            r#"<section id="s">
                 <a data-button="primary" data-command="show-modal" data-target="dlg_1">Open</a>
                 <div data-component="dialog" id="dlg_1"><p>hi</p></div>
                 <div data-component="accordion" id="faq" data-single-open="true" data-default-open="0">
                   <div><h3>Q1</h3><p>A1</p></div>
                   <div><h3>Q2</h3><p>A2</p></div>
                 </div>
                 <div data-component="marquee" id="strip"><p>logo</p></div>
               </section>"#,
        );
        assert!(validate_web_doc(&doc)
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
    }

    #[test]
    fn image_script_scheme_href_is_rejected() {
        let mut doc = clean_doc();
        let page = doc.pages.get_mut(0).unwrap();
        let hero = lumen_core::NodeId::from("hero");
        page.nodes.get_mut(&hero).unwrap().children.push(lumen_core::NodeId::from("img_x"));
        page.nodes.insert(
            lumen_core::NodeId::from("img_x"),
            WebNode {
                id: lumen_core::NodeId::from("img_x"),
                kind: WebNodeKind::Image {
                    asset_id: lumen_core::AssetId::from("missing"),
                    alt: String::new(),
                    href: Some("javascript:alert(1)".to_owned()),
                    new_tab: false,
                },
                classes: String::new(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
        let codes: Vec<String> = validate_web_doc(&doc)
            .iter()
            .map(|diagnostic| diagnostic.code.clone())
            .collect();
        assert!(codes.contains(&"LUMW0016".to_owned()), "{codes:?}");
    }
}
