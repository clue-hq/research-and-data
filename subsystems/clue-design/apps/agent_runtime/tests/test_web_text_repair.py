"""Native tools edit held component copy without reconstructing captured CSS."""

import copy
import json

import pytest
from langchain_core.tools import StructuredTool

from lumen_api.fragments.artifact import build_fragment_artifact
from lumen_api.fragments.href_repair import build_href_repair
from lumen_api.fragments.slots import SlotSpec
from test_web_cloned_sections import HrefRegistry, _tools


class TextRegistry(HrefRegistry):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        artifact = build_fragment_artifact(
            html='<section class="features"><h2>Bound headline</h2><p>Generic account story</p>'
            "<details><summary>What happens next?</summary><p>Original answer</p></details></section>",
            css=".features{font-family:serif;padding:48px;border-radius:12px}"
            ".features p{font-size:24px;font-weight:400}"
            "@media(max-width:600px){.features{padding:16px}.features p{font-size:18px}}",
            rehosted={},
            slots=[SlotSpec(key="headline", kind="text", selector="h2")],
        )
        self.install(artifact)
        self.original = artifact.fragment_id

    def mint_href_repair(self, *, replaces, text_edits=None, rung, note, **kwargs):
        self.mint_calls.append(text_edits)
        repair = build_href_repair(
            self.payloads[replaces],
            text_edits=text_edits,
            text_edit_scope="campaign_variant"
            if "campaign variant" in note
            else "canonical_repair",
            **kwargs,
        )
        self.install(repair.artifact)
        return {
            "fragment_id": repair.artifact.fragment_id,
            "status": "approved",
            "text_match_paths": repair.text_match_paths,
            "lineage_kept": True,
        }


def prepare(tmp_path):
    registry = TextRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(
        tools.insert_cloned_section(
            registry.original,
            slot_values_json=json.dumps({"headline": "Approved account headline"}),
        )
    )
    assert pin["status"] == "ok", pin
    edits = [
        {
            "path": ":nth-child(1) > :nth-child(2)",
            "expected": "Generic account story",
            "replacement": "A coordinated request handoff across the portfolio",
        }
    ]
    return registry, tools, pin, edits


def test_native_schema_copy_derivative_preserves_pin_bindings_and_engine_render(tmp_path):
    registry, tools, pin, edits = prepare(tmp_path)
    before = copy.deepcopy(tools.web_doc)
    source = copy.deepcopy(registry.payloads[registry.original])
    exposed = StructuredTool.from_function(tools.repair_cloned_section)
    result = json.loads(
        exposed.invoke(
            {
                "fragment_id": registry.original,
                "text_edits_json": json.dumps(edits),
                "note": "campaign variant: explain the account request handoff",
            }
        )
    )
    assert result["status"] == "ok", result
    before["pages"][0]["nodes"][pin["node_id"]]["fragment_id"] = result["repair_fragment_id"]
    assert tools.web_doc == before
    assert registry.payloads[registry.original] == source
    assert result["text_match_paths"] == [edits[0]["path"]]
    assert result["href_only"] is False
    for mode in ("editor", "delivery"):
        rendered = tools.core.web_render(
            tools.web_doc,
            "home",
            mode=mode,
            fragments=tools._fragment_render_map(),
            fragment_css=tools._fragment_css(),
        )["html"]
        assert "Approved account headline" in rendered
        assert edits[0]["replacement"] in rendered
        assert "Generic account story" not in rendered
        assert "<details" in rendered and "<summary" in rendered


def test_text_only_inspection_omits_large_styles_and_reports_stored_coordinates(tmp_path):
    registry, tools, _, _ = prepare(tmp_path)
    registry.sections[registry.original]["css"] += "/* held source */" * 15000
    exposed = StructuredTool.from_function(tools.inspect_cloned_section)
    result = json.loads(exposed.invoke({"fragment_id": registry.original, "text_only": True}))
    assert result["status"] == "ok", result
    assert result["css_chars"] > 200000
    assert "html" not in result and "css" not in result
    assert "css_next_offset" not in result and "page_char_limit" not in result
    inventory = result["text_inventory"]
    assert inventory["coordinate_space"] == "stored_fragment_html"
    assert inventory["rendered_visibility"] == "unverified"
    assert any(row["text"] == "Original answer" and row["editable"] for row in inventory["targets"])
    assert inventory["targets"][0]["reason"] == "existing_text_slot"


@pytest.mark.parametrize(
    "args",
    [
        {"text_only": True, "html_offset": 1},
        {"text_only": True, "css_offset": 1},
        {"text_only": False, "text_offset": 1},
        {"text_only": True, "text_offset": -1},
        {"text_only": True, "text_offset": True},
        {"text_only": True, "text_offset": 500},
    ],
)
def test_text_inspection_refuses_ambiguous_or_invalid_offsets(tmp_path, args):
    registry, tools, _, _ = prepare(tmp_path)
    result = json.loads(tools.inspect_cloned_section(registry.original, **args))
    assert result["status"] == "error", result


def test_human_override_refuses_before_mint_or_page_change(tmp_path):
    registry, tools, pin, edits = prepare(tmp_path)
    assert (
        json.loads(
            tools.web_ops(
                json.dumps(
                    [
                        {
                            "kind": "set_fragment_text_override",
                            "page_id": "home",
                            "id": pin["node_id"],
                            "path": ":nth-child(1) > :nth-child(2)",
                            "override": {"text": "Human account story"},
                        }
                    ]
                )
            )
        )["status"]
        == "ok"
    )
    before = copy.deepcopy(tools.web_doc)
    result = json.loads(
        tools.repair_cloned_section(
            registry.original,
            text_edits_json=json.dumps(edits),
            note="campaign variant: new story",
        )
    )
    assert result["status"] == "error" and result["error_code"] == "repair.text_override_conflict"
    assert registry.mint_calls == [] and tools.web_doc == before


@pytest.mark.parametrize("extra", [{"html": "<section>Wrong</section>"}, {"css": ".wrong{}"}])
def test_text_edits_cannot_be_mixed_with_raw_reconstruction(tmp_path, extra):
    registry, tools, _, edits = prepare(tmp_path)
    before = copy.deepcopy(tools.web_doc)
    result = json.loads(
        tools.repair_cloned_section(
            registry.original,
            text_edits_json=json.dumps(edits),
            note="campaign variant: story",
            **extra,
        )
    )
    assert result["status"] == "error", result
    assert registry.mint_calls == [] and tools.web_doc == before
