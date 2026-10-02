//! Wave 3 C3a: point→node hit-testing over rendered geometry.

use lumen_core::{
    hit_stack, hit_test, ComputedGeometry, DocumentId, LineNode, Node, NodeId, NodeKind,
    Orientation, Page, PageId, PagePreset, PageSize, Rect, Scene, SizeSpec, TextAlign, TextNode,
    Transform, Unit,
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

// ── Editor Quality Plan 4, item F: text hits by its painted lines ───────────

fn text_node_with_lines(
    id: &str,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    lines: &[(f64, f64, f64, f64)],
) -> Node {
    let mut n = node(
        id,
        NodeKind::Text(TextNode {
            content: "x".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 96.0,
            font_weight: 700,
            align: TextAlign::Left,
            ..TextNode::default()
        }),
        x,
        y,
        w,
        h,
    );
    let computed = n.computed.as_mut().expect("node() sets computed");
    computed.text_lines = lines
        .iter()
        .map(|&(x, y, width, height)| Rect {
            x,
            y,
            width,
            height,
        })
        .collect();
    n
}

#[test]
fn text_hits_its_painted_lines_not_its_layout_box() {
    // The Apollo "x": a 326×71 fixed box holding one 96pt glyph whose line box
    // (52 wide, 115 tall) runs past the box bottom. A wash sits behind it.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let glyph = text_node_with_lines(
        "x",
        100.0,
        100.0,
        326.0,
        71.0,
        &[(100.0, 100.0, 52.0, 115.0)],
    );
    let scene = scene_with(vec![wash, glyph], vec!["wash", "x"]);

    // Inside the layout box, right of the glyph: the wash, not the text.
    assert_eq!(
        hit_test(&scene, &page_id(), 300.0, 130.0).unwrap().as_str(),
        "wash"
    );
    assert_eq!(
        hit_stack(&scene, &page_id(), 300.0, 130.0)
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>(),
        vec!["wash".to_string()]
    );
    // Below the layout box's bottom (171) but on the painted glyph: the text.
    assert_eq!(
        hit_test(&scene, &page_id(), 120.0, 200.0).unwrap().as_str(),
        "x"
    );
    // Pick slop: 1.5 past the line's right edge (152) still hits; 4 past does not.
    assert_eq!(
        hit_test(&scene, &page_id(), 153.5, 130.0).unwrap().as_str(),
        "x"
    );
    assert_eq!(
        hit_test(&scene, &page_id(), 156.0, 130.0).unwrap().as_str(),
        "wash"
    );
}

#[test]
fn text_without_painted_lines_keeps_the_box_test() {
    // An engine that has not placed lines (pre-Plan-4 `computed`, an empty
    // string, a collapsed box) hit-tests the layout box exactly as before.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let legacy = text_node_with_lines("legacy", 100.0, 100.0, 326.0, 71.0, &[]);
    let zero = text_node_with_lines(
        "zero",
        500.0,
        100.0,
        200.0,
        40.0,
        &[(500.0, 100.0, 0.0, 20.0)],
    );
    let scene = scene_with(vec![wash, legacy, zero], vec!["wash", "legacy", "zero"]);
    assert_eq!(
        hit_test(&scene, &page_id(), 300.0, 130.0).unwrap().as_str(),
        "legacy"
    );
    assert_eq!(
        hit_test(&scene, &page_id(), 600.0, 120.0).unwrap().as_str(),
        "zero"
    );
}

#[test]
fn text_lines_follow_the_node_rotation() {
    // A 200×50 box at (100,100) rotated 90° about its origin, with one 80×20
    // line at the box's top-left. Page point (90, 140) maps into the local
    // frame as (40, 10) — inside the line — while (90, 190) maps to (90, 10),
    // past the line's 80 width but still inside the rotated box.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let mut turned = text_node_with_lines(
        "turned",
        100.0,
        100.0,
        200.0,
        50.0,
        &[(100.0, 100.0, 80.0, 20.0)],
    );
    turned.transform.rotation = 90.0;
    let scene = scene_with(vec![wash, turned], vec!["wash", "turned"]);
    assert_eq!(
        hit_test(&scene, &page_id(), 90.0, 140.0).unwrap().as_str(),
        "turned"
    );
    assert_eq!(
        hit_test(&scene, &page_id(), 90.0, 190.0).unwrap().as_str(),
        "wash"
    );
}
