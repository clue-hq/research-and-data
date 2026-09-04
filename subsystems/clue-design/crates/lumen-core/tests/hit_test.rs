//! Wave 3 C3a: point→node hit-testing over rendered geometry.

use lumen_core::{
    hit_stack, hit_test, ComputedGeometry, DocumentId, LineNode, Node, NodeId, NodeKind,
    Orientation, Page, PageId, PagePreset, PageSize, Rect, Scene, SizeSpec, Transform, Unit,
};

fn bounds(x: f64, y: f64, w: f64, h: f64) -> Option<ComputedGeometry> {
    let r = Rect {
        x,
        y,
        width: w,
        height: h,
    };
    Some(ComputedGeometry {
        layout_bounds: r.clone(),
        render_bounds: r,
        text_lines: Vec::new(),
    })
}

fn node(id: &str, kind: NodeKind, x: f64, y: f64, w: f64, h: f64) -> Node {
    let mut n = Node::new(NodeId::from(id), kind);
    n.size = SizeSpec::fixed(w, h);
    n.transform = Transform {
        x,
        y,
        ..Transform::default()
    };
    n.computed = bounds(x, y, w, h);
    n
}

/// Build a scene from `(node, children)` pairs; the page children are the ids
/// passed in `page_children`.
fn scene_with(nodes: Vec<Node>, page_children: Vec<&str>) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc"), "Hit Test");
    let page = Page {
        id: PageId::from("page"),
        name: "Page".to_owned(),
        size: PageSize {
            width: 800.0,
            height: 600.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
            source: None,
            output: None,
        },
        children: page_children.iter().map(|id| NodeId::from(*id)).collect(),
        bleed: None,
        safe_area: None,
        background: Vec::new(),
    };
    scene.pages.insert(page.id.clone(), page);
    for n in nodes {
        scene.nodes.insert(n.id.clone(), n);
    }
    scene
}

fn page_id() -> PageId {
    PageId::from("page")
}

#[test]
fn hits_topmost_of_overlapping_siblings() {
    // `b` is painted after `a` (later in page children) so it is on top.
    let a = node("a", NodeKind::Rect, 0.0, 0.0, 100.0, 100.0);
    let b = node("b", NodeKind::Rect, 50.0, 50.0, 100.0, 100.0);
    let scene = scene_with(vec![a, b], vec!["a", "b"]);

    // Overlap region: topmost is `b`; the full stack is bottom-to-top.
    assert_eq!(
        hit_test(&scene, &page_id(), 60.0, 60.0).unwrap().as_str(),
        "b"
    );
    assert_eq!(
        hit_stack(&scene, &page_id(), 60.0, 60.0)
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>(),
        vec!["a".to_string(), "b".to_string()]
    );
    // Only `a` here.
    assert_eq!(
        hit_test(&scene, &page_id(), 10.0, 10.0).unwrap().as_str(),
        "a"
    );
    // Only `b` here.
    assert_eq!(
        hit_test(&scene, &page_id(), 140.0, 140.0).unwrap().as_str(),
        "b"
    );
}

#[test]
fn misses_when_outside_every_node() {
    let a = node("a", NodeKind::Rect, 0.0, 0.0, 100.0, 100.0);
    let scene = scene_with(vec![a], vec!["a"]);
    assert!(hit_test(&scene, &page_id(), 500.0, 500.0).is_none());
    assert!(hit_stack(&scene, &page_id(), 500.0, 500.0).is_empty());
}

#[test]
fn hits_nested_child_over_its_parent() {
    let mut frame = node("frame", NodeKind::Frame, 40.0, 40.0, 400.0, 300.0);
    frame.children = vec![NodeId::from("child")];
    let child = node("child", NodeKind::Rect, 60.0, 60.0, 100.0, 100.0);
    let scene = scene_with(vec![frame, child], vec!["frame"]);

    // Inside the child (which lies within the frame): topmost is the child.
    assert_eq!(
        hit_test(&scene, &page_id(), 100.0, 100.0).unwrap().as_str(),
        "child"
    );
    // Inside the frame but outside the child: the frame.
    assert_eq!(
        hit_test(&scene, &page_id(), 300.0, 280.0).unwrap().as_str(),
        "frame"
    );
}

#[test]
fn clip_hides_children_outside_the_container() {
    // The child sits OUTSIDE the frame's box.
    let mut frame = node("frame", NodeKind::Frame, 0.0, 0.0, 100.0, 100.0);
    frame.children = vec![NodeId::from("child")];
    let child = node("child", NodeKind::Rect, 200.0, 200.0, 80.0, 80.0);

    // Without clip: the child is hittable where it is drawn.
    let open = scene_with(vec![frame.clone(), child.clone()], vec!["frame"]);
    assert_eq!(
        hit_test(&open, &page_id(), 220.0, 220.0).unwrap().as_str(),
        "child"
    );

    // With clip: the point is outside the frame, so the clipped child is hidden.
    frame.clip = true;
    let clipped = scene_with(vec![frame, child], vec!["frame"]);
    assert!(hit_test(&clipped, &page_id(), 220.0, 220.0).is_none());
}

#[test]
fn honors_rotation_about_the_node_origin() {
    // 100x100 rect at (100,100) rotated 45° about its top-left origin.
    let mut rotated = node("r", NodeKind::Rect, 100.0, 100.0, 100.0, 100.0);
    rotated.transform.rotation = 45.0;
    let scene = scene_with(vec![rotated], vec!["r"]);

    // Down the local diagonal → inside the rotated quad.
    assert!(hit_test(&scene, &page_id(), 100.0, 170.0).is_some());
    // Straight right of the origin → outside the rotated quad (local y < 0).
    assert!(hit_test(&scene, &page_id(), 170.0, 100.0).is_none());

    // The same point WOULD hit an unrotated rect — proving rotation matters.
    let upright = node("u", NodeKind::Rect, 100.0, 100.0, 100.0, 100.0);
    let upright_scene = scene_with(vec![upright], vec!["u"]);
    assert!(hit_test(&upright_scene, &page_id(), 170.0, 100.0).is_some());
}

#[test]
fn ellipse_excludes_its_bounding_corners() {
    let ellipse = node("e", NodeKind::Ellipse, 0.0, 0.0, 100.0, 60.0);
    let scene = scene_with(vec![ellipse], vec!["e"]);
    // Center is inside.
    assert!(hit_test(&scene, &page_id(), 50.0, 30.0).is_some());
    // The bbox corner is outside the ellipse.
    assert!(hit_test(&scene, &page_id(), 1.0, 1.0).is_none());
}

#[test]
fn line_hits_near_its_segment_only() {
    // Horizontal line from (10,10) of length 80. No stroke → default
    // tolerance (0.5 + 2.0 slop = 2.5 scene units).
    let line = node(
        "l",
        NodeKind::Line(LineNode { x2: 80.0, y2: 0.0 }),
        10.0,
        10.0,
        80.0,
        1.0,
    );
    let scene = scene_with(vec![line], vec!["l"]);
    // On the segment.
    assert!(hit_test(&scene, &page_id(), 50.0, 10.0).is_some());
    // Well off the segment.
    assert!(hit_test(&scene, &page_id(), 50.0, 30.0).is_none());
}
