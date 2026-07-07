"""K4: deterministic brand-fidelity scoring — the scene-vs-kit contract."""

from evaluation.brand_fidelity import score_brand_fidelity


def _kit() -> dict:
    return {
        "id": "brand_kit_any",
        "version": 1,
        "tokens": {
            "colors": {
                "surface.brand": {
                    "value": {"default": {"kind": "hex", "value": "#00525C"}}
                },
                "palette.accent.500": {
                    "value": {"default": {"kind": "oklch", "l": 0.72, "c": 0.17, "h": 160.0}}
                },
            },
            "typography": {
                "type.headline": {
                    "value": {
                        "default": {
                            "kind": "style",
                            "font_family": "Aeonik",
                            "font_size": 32.0,
                            "font_weight": 700,
                        }
                    }
                }
            },
        },
        "assets": {
            "fonts": {"brand": {"family": "Aeonik", "faces": []}},
            "logos": {
                "primary": {
                    "variants": [{"asset_id": "asset_lockup", "name": "full_color"}]
                }
            },
        },
    }


def _scene(*, bound: bool, family: str = "Aeonik", place_logo: bool = True,
           fill: str = "#00525C") -> dict:
    nodes = {
        "headline": {
            "kind": {
                "kind": "text",
                "content": "Hello",
                "font_family": family,
                **({"style_token": "type.headline"} if bound else {}),
            },
            "fills": [],
        },
        "card": {
            "kind": {"kind": "frame"},
            "fills": [{"id": "p1", "paint": {"kind": "solid", "color": {"kind": "hex", "value": fill}}}],
        },
    }
    if place_logo:
        nodes["logo"] = {"kind": {"kind": "image", "asset_id": "asset_lockup"}, "fills": []}
    return {"meta": {}, "pages": {"p": {"background": []}}, "nodes": nodes}


def test_fully_brand_true_scene_ships() -> None:
    report = score_brand_fidelity(_scene(bound=True), _kit())
    assert report["verdict"] == "ship"
    assert report["scores"]["typography_binding"] == 1.0
    assert report["scores"]["logo_adoption"] is True


def test_unbound_text_is_a_redo_even_with_matching_family() -> None:
    """The round-2 live shape: family literal matches the kit but nothing is
    bound — the design detaches from the kit on any token change."""
    report = score_brand_fidelity(_scene(bound=False), _kit())
    assert report["verdict"] == "redo"
    assert report["scores"]["typography_binding"] == 0.0
    # family axis still credits the matching literal
    assert report["scores"]["typography_family"] == 1.0


def test_off_kit_family_literal_is_named() -> None:
    report = score_brand_fidelity(_scene(bound=False, family="Inter"), _kit())
    assert "Inter" in report["detail"]["off_family_literals"]
    assert report["scores"]["typography_family"] == 0.0


def test_missing_logo_is_a_redo_when_kit_provides_one() -> None:
    report = score_brand_fidelity(_scene(bound=True, place_logo=False), _kit())
    assert report["verdict"] == "redo"
    assert report["scores"]["logo_adoption"] is False


def test_rogue_paint_value_downgrades_to_tweak() -> None:
    report = score_brand_fidelity(_scene(bound=True, fill="#ff00aa"), _kit())
    assert report["verdict"] == "tweak"
    assert "#ff00aa" in report["detail"]["rogue_paint_values"]


def test_kit_without_logos_scores_logo_axis_not_applicable() -> None:
    kit = _kit()
    kit["assets"]["logos"] = {}
    report = score_brand_fidelity(_scene(bound=True, place_logo=False), kit)
    assert report["scores"]["logo_adoption"] is None
    assert report["verdict"] == "ship"
