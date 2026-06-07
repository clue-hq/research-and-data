use lumen_core::{NodeId, PageId, Scene, SlotId, SlotKey};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportSidecar {
    pub schema_version: u32,
    pub document_id: String,
    pub profile_name: String,
    pub pages: Vec<PageMapping>,
    pub nodes: Vec<NodeMapping>,
    pub slots: Vec<SlotMapping>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageMapping {
    pub page_id: PageId,
    pub output_id: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NodeMapping {
    pub node_id: NodeId,
    pub page_id: PageId,
    pub output_id: String,
    pub slot_ids: Vec<SlotId>,
    pub slot_keys: Vec<SlotKey>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SlotMapping {
    pub slot_id: SlotId,
    pub slot_key: SlotKey,
    pub bound_nodes: Vec<NodeId>,
}

pub fn build_sidecar(scene: &Scene, page_ids: &[PageId], profile_name: &str) -> ExportSidecar {
    let mut nodes = Vec::new();

    for page_id in page_ids {
        let Some(page) = scene.pages.get(page_id) else {
            continue;
        };
        for child_id in &page.children {
            collect_node_mappings(scene, page_id, child_id, &mut nodes);
        }
    }
    let exported_node_ids = nodes
        .iter()
        .map(|mapping| mapping.node_id.clone())
        .collect::<BTreeSet<_>>();

    let pages = page_ids
        .iter()
        .map(|page_id| PageMapping {
            page_id: page_id.clone(),
            output_id: page_output_id(page_id),
        })
        .collect();

    let slots = scene
        .slots
        .values()
        .filter(|slot| {
            slot.bound_nodes
                .iter()
                .any(|node_id| exported_node_ids.contains(node_id))
        })
        .map(|slot| SlotMapping {
            slot_id: slot.id.clone(),
            slot_key: slot.key.clone(),
            bound_nodes: slot
                .bound_nodes
                .iter()
                .filter(|node_id| exported_node_ids.contains(*node_id))
                .cloned()
                .collect(),
        })
        .collect();

    ExportSidecar {
        schema_version: scene.schema_version,
        document_id: scene.meta.id.to_string(),
        profile_name: profile_name.to_owned(),
        pages,
        nodes,
        slots,
    }
}

pub fn page_output_id(page_id: &PageId) -> String {
    format!("lumen-page-{}", sanitize_id(page_id.as_str()))
}

pub fn node_output_id(node_id: &NodeId) -> String {
    format!("lumen-node-{}", sanitize_id(node_id.as_str()))
}

fn collect_node_mappings(
    scene: &Scene,
    page_id: &PageId,
    node_id: &NodeId,
    nodes: &mut Vec<NodeMapping>,
) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };

    let mut slot_ids = Vec::new();
    let mut slot_keys = Vec::new();
    for slot in scene.slots.values() {
        if slot.bound_nodes.contains(node_id) {
            slot_ids.push(slot.id.clone());
            slot_keys.push(slot.key.clone());
        }
    }

    nodes.push(NodeMapping {
        node_id: node_id.clone(),
        page_id: page_id.clone(),
        output_id: node_output_id(node_id),
        slot_ids,
        slot_keys,
    });

    for child_id in &node.children {
        collect_node_mappings(scene, page_id, child_id, nodes);
    }
}

fn sanitize_id(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}
