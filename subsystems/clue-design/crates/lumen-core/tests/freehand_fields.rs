//! Phase 1a gate — the freehand fields (`position_mode`, `absolute_box`,
//! `base_anchor`, `layout_mode`) must be invisible until used:
//! pre-freehand scene JSON round-trips without gaining keys, old JSON
//! deserializes to the Managed/Stack defaults, and default `NodePatch`
//! serialization stays byte-compatible with pinned operation fixtures.

use lumen_core::{
    AutoLayoutProps, DocumentId, FieldPatch, LayoutMode, Node, NodeId, NodeKind, NodePatch,
    Operation, OptionalFieldPatch, Page, PageId, PageSize, ParentRef, PositionMode, Rect, Scene,
    SizeSpec, TextAlign, TextNode, Unit,
};

fn fixture_value() -> serde_json::Value {
    serde_json::from_str(include_str!("../fixtures/minimal_scene.json")).unwrap()
}

#[test]
fn pre_freehand_scene_json_round_trips_without_gaining_keys() {
    let scene: Scene =
        serde_json::from_str(include_str!("../fixtures/minimal_scene.json")).unwrap();
    let reserialized = serde_json::to_value(&scene).unwrap();
    assert_eq!(
        reserialized,
        fixture_value(),
        "round-trip must not add or drop keys on a pre-freehand scene"
    );

    let text = serde_json::to_string(&scene).unwrap();
    for key in [
        "position_mode",
        "absolute_box",
        "base_anchor",
        "layout_mode",
    ] {
        assert!(
            !text.contains(key),
            "default-valued freehand field `{key}` leaked into serialized scene JSON"
        );
    }
}

#[test]
fn old_json_deserializes_with_managed_and_stack_defaults() {
    let scene: Scene =
        serde_json::from_str(include_str!("../fixtures/minimal_scene.json")).unwrap();
    let node = scene.nodes.values().next().expect("fixture has a node");
    assert_eq!(node.position_mode, PositionMode::Managed);
    assert!(node.absolute_box.is_none());
    assert!(node.base_anchor.is_none());

    // AutoLayoutProps JSON authored before the field exists → Stack.
    let props: AutoLayoutProps =
        serde_json::from_str(r#"{"gap": 8.0, "padding": [0.0, 0.0, 0.0, 0.0], "grow": 0.0}"#)
            .unwrap();
    assert_eq!(props.layout_mode, LayoutMode::Stack);
}

#[test]
fn freehand_fields_round_trip_when_set() {
    let mut node = Node::new(NodeId::from("pinned"), NodeKind::Rect);
    node.position_mode = PositionMode::Absolute;
    node.absolute_box = Some(Rect {
        x: 24.0,
        y: 40.0,
        width: 160.0,
        height: 28.0,
    });
    node.base_anchor = Some(Rect {
        x: 20.0,
        y: 36.0,
        width: 160.0,
        height: 28.0,
    });

    let json = serde_json::to_string(&node).unwrap();
    assert!(json.contains("\"position_mode\":\"absolute\""));
    assert!(json.contains("absolute_box"));
    assert!(json.contains("base_anchor"));
    let decoded: Node = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded, node);

    let props = AutoLayoutProps {
        layout_mode: LayoutMode::Free,
        ..AutoLayoutProps::default()
    };
    let json = serde_json::to_string(&props).unwrap();
    assert!(json.contains("\"layout_mode\":\"free\""));
    let decoded: AutoLayoutProps = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded, props);
}

#[test]
fn default_node_patch_serializes_without_freehand_keys() {
    // Pinned operation fixtures predate freehand; an unchanged patch must not
    // grow keys (mirrors the `effects` guarantee).
    let json = serde_json::to_string(&NodePatch::default()).unwrap();
    for key in ["position_mode", "absolute_box", "base_anchor"] {
        assert!(
            !json.contains(key),
            "unchanged freehand patch field `{key}` leaked into NodePatch JSON"
        );
    }
}

fn scene_with_text_node() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_freehand"), "Freehand");
    scene
        .apply_operation(Operation::AddPage {
            page: Page {
                id: PageId::from("page_a4"),
                name: "A4".to_owned(),
                size: PageSize {
                    width: 210.0,
                    height: 297.0,
                    unit: Unit::Mm,
                    preset: None,
                    orientation: lumen_core::Orientation::Portrait,
                    source: None,
                    output: None,
                },
                children: Vec::new(),
                bleed: None,
                safe_area: None,
                background: Vec::new(),
            },
        })
        .unwrap();
    let mut node = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(TextNode {
            content: "Hello".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec::fixed(160.0, 28.0);
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node,
        })
        .unwrap();
    scene
}

#[test]
fn update_node_applies_and_inverts_freehand_fields() {
    let scene = scene_with_text_node();
    let pin = Rect {
        x: 12.0,
        y: 18.0,
        width: 160.0,
        height: 28.0,
    };
    let operations = vec![Operation::UpdateNode {
        node_id: NodeId::from("headline"),
        patch: NodePatch {
            position_mode: FieldPatch::Set(PositionMode::Absolute),
            absolute_box: OptionalFieldPatch::Set(pin.clone()),
            base_anchor: OptionalFieldPatch::Set(pin.clone()),
            ..NodePatch::default()
        },
    }];

    let inverses = scene
        .invert_operations(&operations)
        .unwrap()
        .expect("freehand patch is invertible");

    let mut working = scene.clone();
    for operation in operations {
        working.apply_operation(operation).unwrap();
    }
    let pinned = &working.nodes[&NodeId::from("headline")];
    assert_eq!(pinned.position_mode, PositionMode::Absolute);
    assert_eq!(pinned.absolute_box, Some(pin.clone()));
    assert_eq!(pinned.base_anchor, Some(pin));

    for operation in inverses {
        working.apply_operation(operation).unwrap();
    }
    assert_eq!(
        serde_json::to_value(&working).unwrap(),
        serde_json::to_value(&scene).unwrap(),
        "inverse must restore the pre-detach scene exactly"
    );
}
