//! Structural validation for web documents (`LUMW00xx`).
//!
//! Invariants: exactly-one-parent arena, root children are Sections only,
//! only branches hold children, bounded depth, resolvable asset/icon
//! references, allowed hrefs, canonical inline content, and a custom_css
//! escape hatch that cannot smuggle imports or script schemes.

use crate::derive::{web_slot_key_is_valid, when_gate_key};
use crate::doc::{
    calendly_url_is_valid, custom_component_artifact_id_is_valid, custom_component_props_issue,
    custom_component_slug_is_valid, ButtonAction, ComponentSpec, EmbedProvider, WebDoc,
    WebNodeKind, MAX_TREE_DEPTH, WEB_SCHEMA_VERSION,
};
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
    if !matches!(root.kind, WebNodeKind::Container { .. }) {
        diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0006",
            format!("page `{}` root must be a container", page.id),
            Some(DiagnosticSubject::Node(root.id.clone())),
        ));
    }
    if let WebNodeKind::Container {
        href, background, ..
    } = &root.kind
    {
        if href.is_some() || background.is_some() {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0029",
                    format!("page `{}` root cannot be clickable or carry a background", page.id),
                    Some(DiagnosticSubject::Node(root.id.clone())),
                )
                .with_hint("Put the link or background on a visible section/container below the page root."),
            );
        }
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
            WebNodeKind::Section { background, .. } => {
                validate_background(doc, node, background.as_ref(), diagnostics);
            }
            WebNodeKind::Container {
                href, background, ..
            } => {
                validate_background(doc, node, background.as_ref(), diagnostics);
                if let Some(href) = href {
                    if !href_is_allowed(href) {
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0016",
                            format!("container `{}` href is not allowed: {href}", node.id),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                    if let Some(descendant) = first_interactive_descendant(page, node) {
                        diagnostics.push(
                            Diagnostic::error(
                                Phase::Web,
                                "LUMW0028",
                                format!(
                                    "clickable container `{}` contains interactive descendant `{descendant}`",
                                    node.id
                                ),
                                Some(DiagnosticSubject::Node(descendant)),
                            )
                            .with_hint(
                                "A clickable container may contain text, images, and layout nodes, but not nested links, buttons, components, or embeds.",
                            ),
                        );
                    }
                }
            }
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
                        matches!(child.kind, WebNodeKind::Container { .. })
                            && child.children.len() >= 2
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
            WebNodeKind::Component {
                spec: ComponentSpec::NavMenu,
            } => {
                for child_id in &node.children {
                    let is_link_or_label = page.nodes.get(child_id).is_some_and(|child| {
                        matches!(
                            child.kind,
                            WebNodeKind::Button { .. } | WebNodeKind::Text { .. }
                        )
                    });
                    if !is_link_or_label {
                        diagnostics.push(Diagnostic::warning(
                            Phase::Web,
                            "LUMW0023",
                            format!(
                                "nav menu `{}` item `{child_id}` is not a link or label; nav menu items are links and labels",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(child_id.clone())),
                        ));
                    }
                }
            }
            WebNodeKind::Component {
                spec: ComponentSpec::Carousel { .. },
            } => {
                if node.children.len() < 2 {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Web,
                        "LUMW0023",
                        format!(
                            "carousel `{}` has fewer than 2 children; a carousel needs slides to page through",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            WebNodeKind::Component {
                spec: ComponentSpec::Tabs { .. },
            } => {
                for child_id in &node.children {
                    let is_item = page.nodes.get(child_id).is_some_and(|child| {
                        matches!(child.kind, WebNodeKind::Container { .. })
                            && child.children.len() >= 2
                            && page
                                .nodes
                                .get(&child.children[0])
                                .is_some_and(|first| matches!(first.kind, WebNodeKind::Text { .. }))
                    });
                    if !is_item {
                        diagnostics.push(Diagnostic::warning(
                            Phase::Web,
                            "LUMW0023",
                            format!(
                                "tabs `{}` item `{child_id}` is not a container with a text label and panel content; it renders after the tabs",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(child_id.clone())),
                        ));
                    }
                }
            }
            WebNodeKind::Embed {
                provider,
                url,
                html,
            } => match provider {
                EmbedProvider::Calendly => {
                    let valid = url.as_deref().is_some_and(calendly_url_is_valid);
                    if !valid {
                        diagnostics.push(Diagnostic::error(
                            Phase::Web,
                            "LUMW0021",
                            format!("calendly embed `{}` has a missing or invalid url", node.id),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
                EmbedProvider::Custom => {
                    if url.is_none() && html.trim().is_empty() {
                        diagnostics.push(Diagnostic::warning(
                            Phase::Web,
                            "LUMW0022",
                            format!("embed `{}` has no content", node.id),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        ));
                    }
                }
            },
            WebNodeKind::CustomComponent {
                slug,
                artifact_id,
                props,
            } => {
                if !custom_component_slug_is_valid(slug) {
                    diagnostics.push(
                        Diagnostic::error(
                            Phase::Web,
                            "LUMW0030",
                            format!(
                                "custom component `{}` has invalid slug `{slug}`",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint(
                            "Use a 1–64 character lowercase kebab-case slug without repeated hyphens.",
                        ),
                    );
                }
                if !custom_component_artifact_id_is_valid(artifact_id) {
                    diagnostics.push(
                        Diagnostic::error(
                            Phase::Web,
                            "LUMW0031",
                            format!(
                                "custom component `{}` has invalid artifact id `{artifact_id}`",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint(
                            "Artifact ids are immutable registry ids in the form ccart_<sha256>.",
                        ),
                    );
                }
                if let Some(issue) = custom_component_props_issue(props) {
                    diagnostics.push(Diagnostic::error(
                        Phase::Web,
                        "LUMW0032",
                        format!("custom component `{}` {issue}", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            WebNodeKind::Text { variant, content } => {
                for issue in content.validate() {
                    diagnostics.push(Diagnostic::error(
                        Phase::Web,
                        "LUMW0017",
                        format!("text `{}` has invalid rich-text content: {issue}", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
                if !variant.allows_structured_rich_text() && !content.is_single_paragraph() {
                    diagnostics.push(Diagnostic::error(
                        Phase::Web,
                        "LUMW0025",
                        format!(
                            "text `{}` uses variant `{}` with multiple paragraphs or lists",
                            node.id,
                            variant.as_str()
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ).with_hint(
                        "Display, heading, and overline text must be one paragraph; use body or small for structured content.",
                    ));
                }
            }
            _ => {}
        }
    }

    // Personalization slot keys (Phase 5): charset + `when:` placement, so a
    // doc mutated via SetSlotKey obeys the same rules ingestion enforces.
    for node in page.nodes.values() {
        let Some(slot_key) = &node.slot_key else {
            continue;
        };
        if !web_slot_key_is_valid(slot_key) {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0024",
                    format!("node `{}` has an invalid slot key `{slot_key}`", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint(
                    "Keys are lowercase [a-z0-9_.-], max 64 chars (with an optional when: gate prefix).",
                ),
            );
        }
        if when_gate_key(slot_key).is_some()
            && !matches!(
                node.kind,
                WebNodeKind::Section { .. } | WebNodeKind::Container { .. }
            )
        {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0025",
                    format!(
                        "{} node `{}` carries a when: presence gate; only sections and containers may",
                        node.kind.kind_name(),
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Move the presence gate to the enclosing section or container."),
            );
        }
    }
}

fn validate_background(
    doc: &WebDoc,
    node: &crate::doc::WebNode,
    background: Option<&crate::doc::WebBackgroundImage>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(background) = background else {
        return;
    };
    match doc.assets.get(&background.asset_id) {
        None => diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0026",
            format!(
                "{} `{}` background references unknown asset `{}`",
                node.kind.kind_name(),
                node.id,
                background.asset_id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        )),
        Some(record) if !record.is_image_compatible() => diagnostics.push(Diagnostic::error(
            Phase::Web,
            "LUMW0026",
            format!(
                "{} `{}` background asset `{}` is not image-compatible",
                node.kind.kind_name(),
                node.id,
                background.asset_id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        )),
        Some(_) => {}
    }
    if let Some(scrim) = &background.scrim {
        if scrim.opacity > 100 {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0027",
                    format!(
                        "{} `{}` scrim opacity {} is outside 0..=100",
                        node.kind.kind_name(),
                        node.id,
                        scrim.opacity
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Use an integer scrim opacity from 0 through 100."),
            );
        }
    }
}

fn first_interactive_descendant(
    page: &crate::doc::WebPage,
    node: &crate::doc::WebNode,
) -> Option<NodeId> {
    let mut stack = node.children.clone();
    let mut seen = BTreeSet::new();
    while let Some(id) = stack.pop() {
        if !seen.insert(id.clone()) {
            continue;
        }
        let Some(descendant) = page.nodes.get(&id) else {
            continue;
        };
        let interactive = match &descendant.kind {
            WebNodeKind::Button { .. }
            | WebNodeKind::Component { .. }
            | WebNodeKind::CustomComponent { .. }
            | WebNodeKind::Embed { .. } => true,
            WebNodeKind::Image { href, .. } => href.is_some(),
            WebNodeKind::Container { href, .. } => href.is_some(),
            WebNodeKind::Text { content, .. } => content.contains_link(),
            _ => false,
        };
        if interactive {
            return Some(id);
        }
        stack.extend(descendant.children.iter().cloned());
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doc::{
        TextVariant, WebBackgroundFit, WebBackgroundImage, WebBackgroundPosition,
        WebBackgroundScrim, WebDoc, WebNode, WebScrimColor, WebThemeRef,
    };
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

    fn add_custom_component(doc: &mut WebDoc) {
        let page = doc.pages.get_mut(0).expect("page");
        let container_id = page
            .nodes
            .get(&lumen_core::NodeId::from("hero"))
            .expect("hero")
            .children[0]
            .clone();
        page.nodes
            .get_mut(&container_id)
            .expect("hero container")
            .children
            .push(lumen_core::NodeId::from("cc_form"));
        page.nodes.insert(
            lumen_core::NodeId::from("cc_form"),
            WebNode {
                id: lumen_core::NodeId::from("cc_form"),
                kind: WebNodeKind::CustomComponent {
                    slug: "book-a-call".to_owned(),
                    artifact_id: format!("ccart_{}", "a".repeat(64)),
                    props: BTreeMap::from([(
                        "headline".to_owned(),
                        crate::doc::CustomComponentValue::String("Book a call".to_owned()),
                    )]),
                },
                classes: "w-full".to_owned(),
                children: Vec::new(),
                name: None,
                slot_key: None,
            },
        );
    }

    #[test]
    fn valid_custom_component_leaf_validates() {
        let mut doc = clean_doc();
        add_custom_component(&mut doc);
        let diagnostics = validate_web_doc(&doc);
        assert!(
            diagnostics
                .iter()
                .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
            "{diagnostics:#?}"
        );
    }

    #[test]
    fn custom_component_identity_props_and_leaf_shape_are_validated() {
        let mut doc = clean_doc();
        add_custom_component(&mut doc);
        let node = doc.pages[0]
            .nodes
            .get_mut(&lumen_core::NodeId::from("cc_form"))
            .expect("custom component");
        let WebNodeKind::CustomComponent {
            slug,
            artifact_id,
            props,
        } = &mut node.kind
        else {
            panic!("custom component");
        };
        *slug = "Bad--Slug".to_owned();
        *artifact_id = "latest".to_owned();
        props.insert(
            "bad-key".to_owned(),
            crate::doc::CustomComponentValue::Boolean(true),
        );
        node.children.push(lumen_core::NodeId::from("impossible"));

        let codes: Vec<String> = validate_web_doc(&doc)
            .iter()
            .map(|diagnostic| diagnostic.code.clone())
            .collect();
        assert!(codes.contains(&"LUMW0007".to_owned()), "{codes:?}");
        assert!(codes.contains(&"LUMW0030".to_owned()), "{codes:?}");
        assert!(codes.contains(&"LUMW0031".to_owned()), "{codes:?}");
        assert!(codes.contains(&"LUMW0032".to_owned()), "{codes:?}");
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
                    content: "x".to_owned().into(),
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
    fn clickable_container_accepts_plain_content_and_rejects_nested_interaction() {
        let plain = ingest_doc(
            r#"<section id="s"><div id="card" data-href="/story"><p>Read it</p></div></section>"#,
        );
        assert!(validate_web_doc(&plain)
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));

        let nested = ingest_doc(
            r#"<section id="s"><div id="card" data-href="/story"><a data-button="primary" href="/buy">Buy</a></div></section>"#,
        );
        assert!(validate_web_doc(&nested)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0028"));
    }

    #[test]
    fn background_asset_and_scrim_opacity_are_validated() {
        let mut doc = clean_doc();
        let page = doc.pages.get_mut(0).unwrap();
        let hero = page
            .nodes
            .get_mut(&lumen_core::NodeId::from("hero"))
            .unwrap();
        let WebNodeKind::Section { background, .. } = &mut hero.kind else {
            panic!("section");
        };
        *background = Some(WebBackgroundImage {
            asset_id: lumen_core::AssetId::from("missing_photo"),
            fit: WebBackgroundFit::Cover,
            position: WebBackgroundPosition::Center,
            scrim: Some(WebBackgroundScrim {
                color: WebScrimColor::Dark,
                opacity: 101,
            }),
        });
        let diagnostics = validate_web_doc(&doc);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0026"));
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0027"));
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
    fn slot_key_charset_and_when_placement_are_validated() {
        // A valid data-slot on a text node validates clean.
        let doc =
            ingest_doc(r#"<section id="s"><p id="p" data-slot="account.name">x</p></section>"#);
        assert!(validate_web_doc(&doc)
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));

        // A when: gate on a text node (only reachable by hand-mutating the doc,
        // since ingest rejects it) is caught by validation: LUMW0025.
        let mut doc = doc;
        let page = doc.pages.get_mut(0).unwrap();
        page.nodes
            .get_mut(&lumen_core::NodeId::from("p"))
            .unwrap()
            .slot_key = Some(lumen_core::SlotKey::from("when:account.name"));
        assert!(validate_web_doc(&doc)
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMW0025"));

        // Off-charset AND uppercase keys are LUMW0024 (keys are strictly
        // lowercase [a-z0-9_.-], stricter than lumen_core::SlotKey).
        for bad in ["bad key!", "Account.Name"] {
            let page = doc.pages.get_mut(0).unwrap();
            page.nodes
                .get_mut(&lumen_core::NodeId::from("p"))
                .unwrap()
                .slot_key = Some(lumen_core::SlotKey::from(bad));
            assert!(
                validate_web_doc(&doc)
                    .iter()
                    .any(|diagnostic| diagnostic.code == "LUMW0024"),
                "{bad}"
            );
        }
    }

    #[test]
    fn image_script_scheme_href_is_rejected() {
        let mut doc = clean_doc();
        let page = doc.pages.get_mut(0).unwrap();
        let hero = lumen_core::NodeId::from("hero");
        page.nodes
            .get_mut(&hero)
            .unwrap()
            .children
            .push(lumen_core::NodeId::from("img_x"));
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
