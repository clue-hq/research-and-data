use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{SlotId, SlotKey};
use crate::scene::{NodeKind, Scene};
use crate::slots::{ContentType, EmptyBehavior, SlotScope};
use crate::SCHEMA_VERSION;
use std::collections::{BTreeMap, BTreeSet};

pub fn validate_scene(scene: &Scene) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    if scene.schema_version != SCHEMA_VERSION {
        diagnostics.push(
            Diagnostic::error(
                Phase::Validation,
                "LUMV0001",
                format!(
                    "scene schema version {} does not match engine schema {}",
                    scene.schema_version, SCHEMA_VERSION
                ),
                Some(DiagnosticSubject::Document),
            )
            .with_hint("Run a scene migration before applying operations or exporting."),
        );
    }

    if scene.pages.is_empty() {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMV0100",
            "document must contain at least one page/artboard",
            Some(DiagnosticSubject::Document),
        ));
    }

    validate_map_identity(scene, &mut diagnostics);
    validate_page_children(scene, &mut diagnostics);
    validate_node_children(scene, &mut diagnostics);
    validate_tree_parentage(scene, &mut diagnostics);
    validate_cycles(scene, &mut diagnostics);
    validate_orphans(scene, &mut diagnostics);
    validate_slots(scene, &mut diagnostics);
    validate_export_profiles(scene, &mut diagnostics);

    diagnostics
}

fn validate_map_identity(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    for (page_id, page) in &scene.pages {
        if page_id != &page.id {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0110",
                format!(
                    "page map key {} does not match embedded page id {}",
                    page_id, page.id
                ),
                Some(DiagnosticSubject::Page(page_id.clone())),
            ));
        }
    }

    for (node_id, node) in &scene.nodes {
        if node_id != &node.id {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0111",
                format!(
                    "node map key {} does not match embedded node id {}",
                    node_id, node.id
                ),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
        }
    }

    for (slot_id, slot) in &scene.slots {
        if slot_id != &slot.id {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0112",
                format!(
                    "slot map key {} does not match embedded slot id {}",
                    slot_id, slot.id
                ),
                Some(DiagnosticSubject::Slot(slot_id.clone())),
            ));
        }
    }
}

fn validate_page_children(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    for page in scene.pages.values() {
        let mut seen = BTreeSet::new();
        for node_id in &page.children {
            if !scene.nodes.contains_key(node_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0200",
                    format!("page {} references missing child node {}", page.id, node_id),
                    Some(DiagnosticSubject::Page(page.id.clone())),
                ));
            }
            if !seen.insert(node_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0201",
                    format!("page {} contains duplicate child node {}", page.id, node_id),
                    Some(DiagnosticSubject::Page(page.id.clone())),
                ));
            }
        }
    }
}

fn validate_node_children(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    for node in scene.nodes.values() {
        if !node.children.is_empty() && !node.kind.can_have_children() {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0300",
                format!("node {} is a leaf and cannot have children", node.id),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }

        let mut seen = BTreeSet::new();
        for child_id in &node.children {
            if !scene.nodes.contains_key(child_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0301",
                    format!(
                        "node {} references missing child node {}",
                        node.id, child_id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
            if !seen.insert(child_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0302",
                    format!("node {} contains duplicate child {}", node.id, child_id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }
        }
    }
}

fn validate_orphans(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    let mut referenced = BTreeSet::new();
    for page in scene.pages.values() {
        referenced.extend(page.children.iter().cloned());
    }
    for node in scene.nodes.values() {
        referenced.extend(node.children.iter().cloned());
    }

    for node_id in scene.nodes.keys() {
        if !referenced.contains(node_id) {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMV0400",
                format!("node {} is not reachable from any page", node_id),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
        }
    }
}

fn validate_tree_parentage(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    let mut parent_by_node: BTreeMap<_, String> = BTreeMap::new();

    for page in scene.pages.values() {
        for child_id in &page.children {
            if scene.nodes.contains_key(child_id) {
                let parent = format!("page {}", page.id);
                if let Some(existing_parent) =
                    parent_by_node.insert(child_id.clone(), parent.clone())
                {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMV0401",
                        format!(
                            "node {} has multiple parents: {} and {}",
                            child_id, existing_parent, parent
                        ),
                        Some(DiagnosticSubject::Node(child_id.clone())),
                    ));
                }
            }
        }
    }

    for node in scene.nodes.values() {
        for child_id in &node.children {
            if child_id == &node.id {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0402",
                    format!("node {} cannot be its own child", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
            }

            if scene.nodes.contains_key(child_id) {
                let parent = format!("node {}", node.id);
                if let Some(existing_parent) =
                    parent_by_node.insert(child_id.clone(), parent.clone())
                {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMV0401",
                        format!(
                            "node {} has multiple parents: {} and {}",
                            child_id, existing_parent, parent
                        ),
                        Some(DiagnosticSubject::Node(child_id.clone())),
                    ));
                }
            }
        }
    }
}

fn validate_cycles(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    let mut state = BTreeMap::new();
    let mut stack = Vec::new();

    for node_id in scene.nodes.keys() {
        visit_for_cycles(scene, node_id, &mut state, &mut stack, diagnostics);
    }
}

fn visit_for_cycles(
    scene: &Scene,
    node_id: &crate::ids::NodeId,
    state: &mut BTreeMap<crate::ids::NodeId, VisitState>,
    stack: &mut Vec<crate::ids::NodeId>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match state.get(node_id) {
        Some(VisitState::Done) => return,
        Some(VisitState::Visiting) => {
            let cycle_start = stack
                .iter()
                .position(|id| id == node_id)
                .unwrap_or_default();
            let cycle = stack[cycle_start..]
                .iter()
                .map(ToString::to_string)
                .chain(std::iter::once(node_id.to_string()))
                .collect::<Vec<_>>()
                .join(" -> ");
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0403",
                format!("node tree contains a cycle: {}", cycle),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
            return;
        }
        None => {}
    }

    state.insert(node_id.clone(), VisitState::Visiting);
    stack.push(node_id.clone());

    if let Some(node) = scene.nodes.get(node_id) {
        for child_id in &node.children {
            if scene.nodes.contains_key(child_id) {
                visit_for_cycles(scene, child_id, state, stack, diagnostics);
            }
        }
    }

    stack.pop();
    state.insert(node_id.clone(), VisitState::Done);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum VisitState {
    Visiting,
    Done,
}

fn validate_slots(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    let mut slot_keys: BTreeMap<SlotKey, SlotId> = BTreeMap::new();

    for slot in scene.slots.values() {
        if let Some(existing_id) = slot_keys.insert(slot.key.clone(), slot.id.clone()) {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0500",
                format!(
                    "slot key {} is used by both {} and {}",
                    slot.key, existing_id, slot.id
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }

        if slot.required && slot.placeholder.as_deref().unwrap_or("").is_empty() {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMV0501",
                format!("required slot {} has no placeholder", slot.key),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }

        for node_id in &slot.bound_nodes {
            if !scene.nodes.contains_key(node_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0502",
                    format!("slot {} binds missing node {}", slot.key, node_id),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        match &slot.scope {
            SlotScope::Document => {}
            SlotScope::Page(page_id) => {
                if !scene.pages.contains_key(page_id) {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMV0510",
                        format!("slot {} is scoped to missing page {}", slot.key, page_id),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
            }
            SlotScope::Node(node_id) => {
                if !scene.nodes.contains_key(node_id) {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMV0511",
                        format!("slot {} is scoped to missing node {}", slot.key, node_id),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
            }
            SlotScope::Group(node_id) => match scene.nodes.get(node_id) {
                Some(node) if group_scope_can_target(&node.kind) => {}
                Some(_) => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0512",
                    format!(
                        "slot {} group scope targets non-container node {}",
                        slot.key, node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                )),
                None => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0511",
                    format!(
                        "slot {} is scoped to missing group node {}",
                        slot.key, node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                )),
            },
        }

        if matches!(slot.content_type, ContentType::Image | ContentType::Logo)
            && slot.image_policy.is_none()
        {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMV0503",
                format!("image-like slot {} has no image policy", slot.key),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }

        if slot.conditional.is_some()
            && slot
                .conditional
                .as_ref()
                .is_some_and(|rule| matches!(rule.when_false, EmptyBehavior::UseFallback))
            && slot.placeholder.as_deref().unwrap_or("").is_empty()
        {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMV0504",
                format!(
                    "conditional slot {} uses fallback without placeholder",
                    slot.key
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }

        if let Some(repeater) = &slot.repeater {
            if !matches!(slot.content_type, ContentType::RepeaterGroup) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0505",
                    format!(
                        "slot {} defines repeater behavior but is not a repeater_group",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }

            if !scene.nodes.contains_key(&repeater.template_node_id) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0506",
                    format!(
                        "repeater slot {} references missing template node {}",
                        slot.key, repeater.template_node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }

            if repeater
                .max_items
                .is_some_and(|max_items| max_items < repeater.min_items)
            {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0507",
                    format!("repeater slot {} has max_items below min_items", slot.key),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        if let Some(max_items) = slot.cardinality.max_items {
            if max_items < slot.cardinality.min_items {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0508",
                    format!(
                        "slot {} has max cardinality below min cardinality",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        if matches!(
            slot.content_type,
            ContentType::TextShort | ContentType::TextLong
        ) && slot.validation.samples.is_empty()
            && slot.validation.worst_case.is_none()
            && slot.validation.max_length.is_none()
        {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMV0509",
                format!("text slot {} has no fit-validation fixtures", slot.key),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }
    }
}

fn group_scope_can_target(kind: &NodeKind) -> bool {
    matches!(
        kind,
        NodeKind::Frame | NodeKind::Group | NodeKind::AutoLayout(_)
    )
}

fn validate_export_profiles(scene: &Scene, diagnostics: &mut Vec<Diagnostic>) {
    let mut seen = BTreeSet::new();

    for profile in &scene.export_profiles {
        if profile.name.trim().is_empty() {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0600",
                "export profile name cannot be empty",
                Some(DiagnosticSubject::Document),
            ));
        }

        if !seen.insert(profile.name.as_str()) {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMV0601",
                format!("duplicate export profile name {}", profile.name),
                Some(DiagnosticSubject::Document),
            ));
        }

        if let Some(raster) = &profile.raster {
            if raster.scale <= 0.0 {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMV0602",
                    format!(
                        "export profile {} has non-positive raster scale",
                        profile.name
                    ),
                    Some(DiagnosticSubject::Document),
                ));
            }
        }
    }
}
