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


# --- Imagery slice 1: informational imagery_adoption axis --------------------


def _kit_with_images() -> dict:
    kit = _kit()
    kit["assets"]["images"] = {
        "img.1": {"asset_id": "asset_hero_photo", "role": "photo"},
        # An image entry that aliases the LOGO asset must not count as imagery.
        "img.2": {"asset_id": "asset_lockup", "role": "og_image"},
    }
    return kit


def test_imagery_adoption_true_when_kit_image_placed() -> None:
    scene = _scene(bound=True)
    scene["nodes"]["hero"] = {
        "kind": {"kind": "image", "asset_id": "asset_hero_photo"},
        "fills": [],
    }
    report = score_brand_fidelity(scene, _kit_with_images())
    assert report["scores"]["imagery_adoption"] is True
    assert report["detail"]["kit_imagery_asset_ids"] == ["asset_hero_photo"]


def test_imagery_adoption_false_is_informational_never_gating() -> None:
    # The K4 lesson applied to itself: measure before gating. A brand-true
    # scene with no kit imagery still SHIPS; the miss is a note, not a demerit.
    report = score_brand_fidelity(_scene(bound=True), _kit_with_images())
    assert report["scores"]["imagery_adoption"] is False
    assert report["verdict"] == "ship"
    assert any("brand images" in reason for reason in report["reasons"])


def test_imagery_axis_not_applicable_without_kit_images() -> None:
    report = score_brand_fidelity(_scene(bound=True), _kit())
    assert report["scores"]["imagery_adoption"] is None


def test_logo_assets_never_double_count_as_imagery() -> None:
    # img.2 points at the lockup; with the hero photo removed, the only image
    # entry left aliases a logo — the imagery axis must be n/a, not False.
    kit = _kit_with_images()
    del kit["assets"]["images"]["img.1"]
    report = score_brand_fidelity(_scene(bound=True), kit)
    assert report["scores"]["imagery_adoption"] is None
