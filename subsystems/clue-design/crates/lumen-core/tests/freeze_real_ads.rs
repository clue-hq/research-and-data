//! The test that would have caught 2026-09-20: freeze each real ad and assert
//! NOTHING moves.
//!
//! The three fixtures under `fixtures/scenes/freeze/` are the LinkedIn ads the
//! human froze on the live walk, recovered pre-freeze (no `computed` blocks, no
//! `layout_mode` keys — they are the scenes as the agent authored them). Each
//! test solves the ad, freezes it, re-solves, and demands the two solves agree
//! box for box; then it applies the batch's inverses and demands the scene come
//! back byte-identically; then it checks the post-freeze node invariants (every
//! unlocked auto-layout container is `Free`; no dimension is still `fill`, and
//! only a TEXT node may still be `hug`, on its height axis alone).
//!
//! The defect this pins: `build_freeze_layout` used to exempt a container's own
//! `Fill` from the bake, and the two layout modes disagree about what `Fill`
//! means — the Stack solve treats a nested cross-axis `Fill` as hug, Free mode
//! resolves it against the parent's OUTER box. Every container in these three
//! ads is `fill`-width, so the old engine snapped hugged rows to the artboard
//! edge the moment the document was frozen.

use lumen_core::{
    build_freeze_layout, layout_operations, layout_scene, DiagnosticSeverity, Dimension,
    LayoutMode, LayoutOptions, NodeId, NodeKind, PositionMode, Scene,
};

fn load(name: &str) -> Scene {
    let path = format!(
        "{}/fixtures/scenes/freeze/{name}.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let raw = std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {path}: {err}"));
    serde_json::from_str(&raw).unwrap_or_else(|err| panic!("parse {path}: {err}"))
}

/// One solve: every layout box keyed and sorted by node id, plus the ERROR-
/// severity diagnostics it raised (code + subject, sorted).
///
/// Two deliberate choices about diagnostics. (1) Nothing here asserts on a
/// diagnostic COUNT: these scenes are measured by the heuristic fallback
/// measurer, which emits font-shaping WARNINGS (LUMS0100/LUMS0102) whose number
/// depends on the fonts installed on the machine running the test. (2) Nothing
/// asserts errors are ABSENT either — all three real ads legitimately raise
/// overflow errors (LUMV0801 out-of-parent-bounds, LUMV0903 text exceeds
/// available height) under that approximate measurer BEFORE the freeze, and
/// hiding that would mean asserting against a scrubbed fixture instead of the
/// real ad. What must hold is one-way: the freeze may not INTRODUCE an error the
/// pre-freeze solve did not already have.
fn solved(scene: &Scene) -> (Vec<(String, (f64, f64, f64, f64))>, Vec<String>) {
    let result = layout_scene(scene, LayoutOptions::default());
    let mut errors: Vec<String> = result
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        .map(|diagnostic| format!("{} {:?}", diagnostic.code, diagnostic.subject))
        .collect();
    errors.sort();
    let mut boxes: Vec<_> = result
        .geometry
        .iter()
        .map(|(id, geometry)| {
            (
                id.to_string(),
                (
                    geometry.layout_bounds.x,
                    geometry.layout_bounds.y,
                    geometry.layout_bounds.width,
                    geometry.layout_bounds.height,
                ),
            )
        })
        .collect();
    boxes.sort_by(|left, right| left.0.cmp(&right.0));
    (boxes, errors)
}

/// Known, deferred engine residual (recorded by Task 1, not fixed here): the
/// Stack solve reports taffy's whole-pixel-ROUNDED geometry while the Free path
/// natural-sizes unrounded, so a TEXT node that keeps its `hug` HEIGHT through
/// the freeze (the K1 rider — the one dimension deliberately left un-baked) can
/// re-measure a sub-pixel different height on the second solve. Every other
/// number, on every other node, must match to 1e-6: those are baked `Fixed`
/// extents and a baked transform, and any drift there is a real regression.
///
/// `allow_text_height_slack` names exactly the nodes granted the 1.0px height
/// tolerance, so the grant can never silently widen to a node that did not need
/// it.
fn assert_boxes_match(
    name: &str,
    before: &[(String, (f64, f64, f64, f64))],
    after: &[(String, (f64, f64, f64, f64))],
    allow_text_height_slack: &[&str],
) {
    assert_eq!(
        before.iter().map(|entry| &entry.0).collect::<Vec<_>>(),
        after.iter().map(|entry| &entry.0).collect::<Vec<_>>(),
        "{name}: the freeze changed which nodes the solve places"
    );
    // Collected, never short-circuited: one failure must name EVERY node that
    // moved, not just the first in id order.
    let mut violations: Vec<String> = Vec::new();
    for ((id, before_box), (_, after_box)) in before.iter().zip(after.iter()) {
        let height_tolerance = if allow_text_height_slack.contains(&id.as_str()) {
            1.0
        } else {
            1e-6
        };
        let axes = [
            ("x", before_box.0, after_box.0, 1e-6),
            ("y", before_box.1, after_box.1, 1e-6),
            ("width", before_box.2, after_box.2, 1e-6),
            ("height", before_box.3, after_box.3, height_tolerance),
        ];
        for (axis, was, now, tolerance) in axes {
            let delta = (now - was).abs();
            if delta > tolerance {
                violations.push(format!(
                    "{id}.{axis}: {was} -> {now} (delta {delta}, tolerance {tolerance})"
                ));
            }
        }
    }
    assert!(
        violations.is_empty(),
        "{name}: {} node dimension(s) moved or resized during freeze:\n  {}",
        violations.len(),
        violations.join("\n  ")
    );
}

/// The Task 1 post-freeze table, node by node.
fn assert_frozen_node_invariants(name: &str, source: &Scene, frozen: &Scene) {
    assert_eq!(
        source.nodes.len(),
        frozen.nodes.len(),
        "{name}: the freeze added or dropped nodes"
    );
    for (id, node) in &frozen.nodes {
        let original = source
            .nodes
            .get(id)
            .unwrap_or_else(|| panic!("{name}: the freeze invented node {id}"));

        // Absolute children never enter the bake — their page-space box wins in
        // both modes. (None of these three ads pins a child Absolute today, so
        // this branch is currently vacuous over the fixtures; it is here so the
        // rule is enforced the day one of them does.)
        if original.position_mode == PositionMode::Absolute {
            assert_eq!(
                node.size, original.size,
                "{name}: absolute node {id} was resized by the freeze"
            );
            assert_eq!(
                node.transform, original.transform,
                "{name}: absolute node {id} was moved by the freeze"
            );
            continue;
        }

        if matches!(node.kind, NodeKind::AutoLayout(_)) && !node.locked {
            let mode = node.layout.clone().unwrap_or_default().layout_mode;
            assert_eq!(
                mode,
                LayoutMode::Free,
                "{name}: container {id} is still {mode:?} after the freeze"
            );
        }

        let is_text = matches!(node.kind, NodeKind::Text(_));
        assert!(
            matches!(
                node.size.width,
                Dimension::Fixed(_) | Dimension::Token { .. }
            ),
            "{name}: node {id} kept a non-baked width {:?} through the freeze",
            node.size.width
        );
        match &node.size.height {
            Dimension::Fixed(_) | Dimension::Token { .. } => {}
            // The one deliberate survivor: a text node's hug HEIGHT re-measures
            // vertically and must not be frozen to a pre-token-resolution box.
            Dimension::Hug if is_text => {}
            other => {
                panic!("{name}: node {id} kept a non-baked height {other:?} through the freeze")
            }
        }
    }
}

fn freeze_is_zero_motion(name: &str, allow_text_height_slack: &[&str]) {
    let mut scene = load(name);
    // The builders refuse a scene with no solved geometry ("run layout before
    // freeing"), so stamp `computed` the way the editor does.
    scene
        .apply_operations(layout_operations(&scene, LayoutOptions::default()))
        .unwrap();
    let (before, errors_before) = solved(&scene);

    let batch = build_freeze_layout(&scene).unwrap();
    assert!(
        !batch.operations.is_empty(),
        "{name}: nothing froze — the fixture has no Stack container left to bake"
    );

    let mut frozen = scene.clone();
    frozen.apply_operations(batch.operations.clone()).unwrap();
    let (after, errors_after) = solved(&frozen);
    assert_boxes_match(name, &before, &after, allow_text_height_slack);
    // The freeze may not INTRODUCE an error. It is allowed to drop one, and on
    // these ads it drops a few: a hug-height text node whose Stack height taffy
    // rounded DOWN (`sep`, `pair_x`, `prod_dac` — the 0.71px cases) overflowed
    // its own rounded box with LUMV0903, and re-measuring unrounded in Free mode
    // makes the copy fit. Same rounding residual as the height tolerance above,
    // in the safe direction.
    let introduced: Vec<&String> = errors_after
        .iter()
        .filter(|error| !errors_before.contains(error))
        .collect();
    assert!(
        introduced.is_empty(),
        "{name}: the freeze introduced error diagnostics {introduced:?} \
         (before: {errors_before:?}, after: {errors_after:?})"
    );

    assert_frozen_node_invariants(name, &scene, &frozen);
    // The slack below is granted ONLY to a text node that actually kept its hug
    // height — it can never quietly cover a baked Fixed extent that drifted.
    for id in allow_text_height_slack {
        let node = frozen
            .nodes
            .get(&NodeId::from(*id))
            .unwrap_or_else(|| panic!("{name}: no node {id} to grant height slack to"));
        assert!(
            matches!(node.kind, NodeKind::Text(_)) && matches!(node.size.height, Dimension::Hug),
            "{name}: node {id} was granted text-height slack but is not a hug-height text node"
        );
    }

    let mut restored = frozen.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        serde_json::to_value(&restored).unwrap(),
        serde_json::to_value(&scene).unwrap(),
        "{name}: inverse must restore the scene byte-identically"
    );
}

/// The hug-height text nodes of each ad. Every one of them re-measures within
/// 0.71px of its Stack height on the Free re-solve (largest observed delta:
/// `sep`/`pair_x`/`logo_sep`/`prod_dac`, 0.71px) — the whole-pixel rounding
/// residual documented on `assert_boxes_match`. Nothing else in any of the three
/// ads needs a tolerance at all: every other box matches to 1e-6.
#[test]
fn capital_digestive_care_ad_freezes_zero_motion() {
    freeze_is_zero_motion(
        "capital_digestive_care_ad",
        &[
            "eyebrow",
            "headline",
            "kicker",
            "pair_x",
            "prod_dac",
            "prod_intake",
            "prod_magicdocs",
            "support",
        ],
    );
}

#[test]
fn austin_gastroenterology_ad_freezes_zero_motion() {
    freeze_is_zero_motion(
        "austin_gastroenterology_ad",
        &["cta", "headline", "sep", "support"],
    );
}

#[test]
fn mngi_digestive_health_ad_freezes_zero_motion() {
    freeze_is_zero_motion(
        "mngi_digestive_health_ad",
        &["cta", "headline", "logo_sep", "p1", "p2", "p3", "support"],
    );
}
