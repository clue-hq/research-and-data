"""K4 retokenization: deterministic literal→token binding on agent drafts."""

from lumen_deepagent.retokenize import build_retokenize_operations


def _kit() -> dict:
    return {
        "tokens": {
            "colors": {
                "surface.brand": {"value": {"default": {"kind": "hex", "value": "#00525C"}}},
                "palette.teal.700": {"value": {"default": {"kind": "hex", "value": "#00525C"}}},
                "surface.accent": {"value": {"default": {"kind": "hex", "value": "#3D8D5C"}}},
            },
            "spacing": {
                "space.md": {"value": {"default": {"kind": "number", "unit": "px", "value": 12.0}}},
                "space.3": {"value": {"default": {"kind": "number", "unit": "px", "value": 12.0}}},
                "space.6": {"value": {"default": {"kind": "number", "unit": "px", "value": 24.0}}},
            },
            "stroke_widths": {
                "stroke.width.default": {"value": {"default": {"kind": "number", "unit": "px", "value": 1.0}}},
            },
            "opacity": {
                "opacity.muted": {"value": {"default": {"kind": "number", "unit": "px", "value": 0.56}}},
            },
            "numbers": {
                "type.size.md": {"value": {"default": {"kind": "number", "unit": "px", "value": 17.0}}},
                "type.size.7xl": {"value": {"default": {"kind": "number", "unit": "px", "value": 85.5}}},
            },
            "typography": {
                "type.headline": {
                    "value": {"default": {"kind": "style", "font_family": "Aeonik", "font_size": 32.0, "font_weight": 700}}
                },
            },
        },
        "assets": {"fonts": {"brand": {"family": "Aeonik", "faces": []}}},
    }


def _ops_by_node(scene: dict) -> dict:
    return {op["node_id"]: op for op in build_retokenize_operations(scene, _kit())}


def test_solid_fill_matching_kit_color_binds_semantic_token_over_palette() -> None:
    scene = {
        "nodes": {
            "hero": {
                "kind": {"kind": "frame"},
                "fills": [{"id": "p1", "paint": {"kind": "solid", "color": {"kind": "hex", "value": "#00525c"}}}],
            }
        }
    }
    ops = _ops_by_node(scene)
    fills = ops["hero"]["patch"]["fills"]
    assert fills["kind"] == "set"
    assert fills["value"][0]["paint"] == {"kind": "token", "token": "surface.brand"}


def test_gap_and_uniform_padding_bind_semantic_spacing() -> None:
    scene = {
        "nodes": {
            "stack": {
                "kind": {"kind": "frame"},
                "layout": {
                    "gap": 12.0,
                    "padding": {"top": 24.0, "right": 24.0, "bottom": 24.0, "left": 24.0},
                },
            }
        }
    }
    layout = _ops_by_node(scene)["stack"]["patch"]["layout"]["value"]
    assert layout["gap_token"] == "space.md"  # semantic beats space.3
    assert layout["padding_token"] == "space.6"


def test_text_exact_role_match_binds_style_token() -> None:
    scene = {
        "nodes": {
            "h": {
                "kind": {
                    "kind": "text", "content": "x", "font_family": "Aeonik",
                    "font_size": 32.0, "font_weight": 700,
                }
            }
        }
    }
    kind = _ops_by_node(scene)["h"]["patch"]["kind"]["value"]
    assert kind["style_token"] == "type.headline"
    assert "font_size_token" not in kind


def test_text_role_plus_ramp_override_binds_both_tokens() -> None:
    scene = {
        "nodes": {
            "big": {
                "kind": {
                    "kind": "text", "content": "x", "font_family": "Aeonik",
                    "font_size": 85.5, "font_weight": 700,
                }
            }
        }
    }
    kind = _ops_by_node(scene)["big"]["patch"]["kind"]["value"]
    assert kind["style_token"] == "type.headline"
    assert kind["font_size_token"] == "type.size.7xl"
    assert kind["font_size"] == 85.5  # exact: literal untouched


def test_near_ramp_size_snaps_within_tolerance() -> None:
    scene = {
        "nodes": {
            "near": {
                "kind": {
                    "kind": "text", "content": "x", "font_family": "Aeonik",
                    "font_size": 82.0, "font_weight": 700,  # 4.3% from 85.5
                }
            }
        }
    }
    kind = _ops_by_node(scene)["near"]["patch"]["kind"]["value"]
    assert kind["font_size_token"] == "type.size.7xl"
    assert kind["font_size"] == 85.5  # snapped


def test_non_kit_family_and_non_matching_values_produce_no_ops() -> None:
    scene = {
        "nodes": {
            "alien": {
                "kind": {
                    "kind": "text", "content": "x", "font_family": "Comic Sans",
                    "font_size": 33.0, "font_weight": 400,
                },
                "fills": [{"id": "p", "paint": {"kind": "solid", "color": {"kind": "hex", "value": "#ff00aa"}}}],
            }
        }
    }
    assert build_retokenize_operations(scene, _kit()) == []


def test_already_bound_nodes_are_left_alone() -> None:
    scene = {
        "nodes": {
            "bound": {
                "kind": {
                    "kind": "text", "content": "x", "font_family": "Aeonik",
                    "font_size": 32.0, "font_weight": 700, "style_token": "type.headline",
                },
                "fills": [{"id": "p", "paint": {"kind": "token", "token": "surface.brand"}}],
            }
        }
    }
    assert build_retokenize_operations(scene, _kit()) == []
