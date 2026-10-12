//! The kit's `styles` token group (Wave 2 A9): measured values the typed groups cannot hold.
use lumen_core::{validate_brand_kit, BrandKit, DiagnosticSeverity, StyleTokenValue};
use serde_json::{json, Value};

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");

fn token(value: Value) -> Value {
    json!({
        "value": {"default": value, "modes": {}},
        "description": null,
        "provenance": {"source": "website:https://example.test/ :: button solid.047464 rest", "confidence": 0.8}
    })
}

fn kit_with(styles: Value) -> BrandKit {
    let mut kit: Value = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    kit["tokens"]["styles"] = styles;
    serde_json::from_value(kit).unwrap()
}

fn errors(kit: &BrandKit) -> Vec<String> {
    validate_brand_kit(kit)
        .into_iter()
        .filter(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        .map(|diagnostic| diagnostic.code)
        .collect()
}

const ICON: &str = "<svg viewBox=\"0 0 12 12\" fill=\"none\"><path d=\"M1 6h9M7 2l4 4-4 4\" stroke=\"currentColor\" stroke-width=\"1.5\"></path></svg>";

fn valid_styles() -> Value {
    json!({
        "button.solid-047464.case": token(json!({"kind": "keyword", "property": "text-transform", "value": "uppercase"})),
        "button.solid-047464.hover.shadow": token(json!({"kind": "keyword", "property": "box-shadow", "value": "none"})),
        "motion.button.solid-047464.duration-1": token(json!({"kind": "duration", "ms": 200.0})),
        "motion.button.solid-047464.easing-1": token(json!({"kind": "easing", "function": "cubic-bezier(0.2, 0.8, 0.2, 1)"})),
        "button.solid-047464.hover.transform": token(json!({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, -2)"})),
        "button.solid-047464.icon": token(json!({"kind": "glyph", "text": "→"})),
        "button.outline-0d2b25.icon": token(json!({"kind": "svg", "markup": ICON, "width": 12.0, "height": 12.0})),
        "motion.keyframes.pulse": token(json!({"kind": "keyframes", "frames": [
            {"offset": 0.0, "declarations": {"opacity": "1", "transform": "scale(1)"}},
            {"offset": 100.0, "declarations": {"opacity": "0.4", "transform": "scale(1.2)"}}
        ]})),
        "motion.animation.pulse.duration": token(json!({"kind": "duration", "ms": 1600.0})),
        "motion.animation.pulse.easing": token(json!({"kind": "easing", "function": "ease-in-out"})),
        "motion.animation.pulse": token(json!({"kind": "animation", "keyframes": "motion.keyframes.pulse",
            "duration": "motion.animation.pulse.duration", "easing": "motion.animation.pulse.easing",
            "delay": null, "iterations": "infinite", "direction": "alternate", "fill_mode": "none"})),
        "motion.reveal.3f2a91c0.from-transform": token(json!({"kind": "transform", "value": "matrix(1, 0, 0, 1, 0, 24)"})),
        "motion.reveal.3f2a91c0": token(json!({"kind": "reveal", "from_opacity": null,
            "from_transform": "motion.reveal.3f2a91c0.from-transform",
            "duration": "motion.animation.pulse.duration", "easing": "motion.animation.pulse.easing"})),
    })
}

#[test]
fn a_kit_with_measured_style_tokens_validates_and_round_trips() {
    let kit = kit_with(valid_styles());
    assert_eq!(errors(&kit), Vec::<String>::new());
    assert!(matches!(
        kit.tokens.styles["button.solid-047464.case"].value.default,
        StyleTokenValue::Keyword { .. }
    ));
    let json = serde_json::to_value(&kit).unwrap();
    assert_eq!(
        json["tokens"]["styles"]["motion.animation.pulse"]["value"]["default"]["iterations"],
        "infinite"
    );
    let back: BrandKit = serde_json::from_value(json).unwrap();
    assert_eq!(back, kit);
}

#[test]
fn a_kit_without_style_tokens_serializes_exactly_as_before() {
    let original: Value = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let kit: BrandKit = serde_json::from_value(original).unwrap();
    let json = serde_json::to_value(&kit).unwrap();
    assert!(
        json["tokens"].get("styles").is_none(),
        "an empty styles group is omitted"
    );
}

#[test]
fn each_unsafe_or_dangling_style_token_is_refused_by_its_code() {
    let cases = [
        (
            "LUMB0260",
            json!({"kind": "keyword", "property": "background-image", "value": "none"}),
        ),
        (
            "LUMB0260",
            json!({"kind": "keyword", "property": "cursor", "value": "url(x.cur), auto"}),
        ),
        (
            "LUMB0260",
            json!({"kind": "keyword", "property": "box-shadow", "value": "0 0 2px red"}),
        ),
        ("LUMB0261", json!({"kind": "duration", "ms": -1.0})),
        ("LUMB0262", json!({"kind": "easing", "function": "bounce"})),
        (
            "LUMB0263",
            json!({"kind": "transform", "value": "translateX(4px)"}),
        ),
        (
            "LUMB0264",
            json!({"kind": "keyframes", "frames": [
                {"offset": 0.0, "declarations": {"background-image": "url(x)"}},
                {"offset": 100.0, "declarations": {"opacity": "1"}}
            ]}),
        ),
        ("LUMB0265", json!({"kind": "glyph", "text": "<b>"})),
        (
            "LUMB0265",
            json!({"kind": "svg", "markup": "<svg onload=\"x()\"></svg>", "width": 12.0, "height": 12.0}),
        ),
        (
            "LUMB0265",
            json!({"kind": "svg", "markup": "<svg><use href=\"#a\"></use></svg>", "width": 12.0, "height": 12.0}),
        ),
        (
            "LUMB0266",
            json!({"kind": "animation", "keyframes": "motion.keyframes.missing", "duration": "x",
            "easing": "y", "delay": null, "iterations": "1", "direction": "normal", "fill_mode": "none"}),
        ),
    ];
    for (code, value) in cases {
        let kit = kit_with(json!({"button.solid-047464.case": token(value.clone())}));
        assert!(
            errors(&kit).contains(&code.to_owned()),
            "{code} for {value}"
        );
    }
    let bad_key = kit_with(json!({"button solid": token(json!({"kind": "duration", "ms": 1.0}))}));
    assert!(errors(&bad_key).contains(&"LUMB0120".to_owned()));
}
