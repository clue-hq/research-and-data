"""The web lane's hands on cloned sections (clone-fidelity F2.3).

Ingestion clones a walked site's sections and a human releases them by approving the brand kit.
Everything after that is this file: the author can FIND those sections, LOOK at them, and PIN one
into the page it is building — and a section a human has not released refuses in words the model
can act on, rather than blowing up at commit time.

The durable half (approved-only listing, the gate's own refusal codes, workspace scoping) is
pinned DB-backed in ``apps/api/tests/test_agent_cloned_sections.py``. Here the registry is a fake
that answers exactly what the real capability answers, and the ENGINE is real: every insert goes
through ``web_apply_ops``, so the wrapped-in-a-section shape and the slot grammar are judged by
the thing that will judge them in production.
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A real 1x1 PNG. The view path attaches images through PIL, so a byte string that merely LOOKS
#: like a PNG fails at decode rather than proving anything about the tool.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

HERO_ID = "frag_0123456789abcdef"
NAV_ID = "frag_fedcba9876543210"
PROOF_ID = "frag_abcdef0123456789"
HERO_WRAPPER = "lumen-frag-0123456789abcdef"

HERO_HTML = (
    '<section class="clone-hero">'
    '<h1 data-lumen-slot="headline">Care, on your terms</h1>'
    '<a data-lumen-slot="cta_href" href="https://insight.example/demo">Book a demo</a>'
    "</section>"
)
HERO_CSS = f".{HERO_WRAPPER} .clone-hero {{ padding: 64px }}"
NAV_HTML = '<nav class="clone-nav"><a href="/">Insight</a></nav>'
PROOF_HTML = (
    '<section class="clone-proof">'
    '<p data-lumen-slot="body">Trusted by 400 clinics</p>'
    '<img data-lumen-slot="image_1" src="/asset-store/' + "a" * 64 + '" alt="">'
    '<div data-lumen-slot="visible">badge</div>'
    "</section>"
)


class FakeRegistry:
    """What the real ``DurableAgentClonedSectionRegistry`` answers, without a database.

    ``draft`` rows are held here NOT to be listed — they exist so a test can ask for one and get
    the gate's refusal, which is the whole point of the insert path.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.sections: dict[str, dict] = {}
        self.describe_calls: list[list[str]] = []
        self.list_calls: list[str | None] = []

    def add(
        self,
        fragment_id: str,
        *,
        role: str,
        label: str,
        html: str,
        css: str = "",
        slots: list[dict] | None = None,
        status: str = "approved",
        preview: bytes | None = PNG_1PX,
        source_url: str = "https://insight.example/",
        kit: tuple[str, int] | None = ("brand_kit_1", 3),
    ) -> None:
        preview_path = None
        if preview is not None:
            path = self.tmp_path / f"{fragment_id}.png"
            path.write_bytes(preview)
            preview_path = str(path)
        self.sections[fragment_id] = {
            "fragment_id": fragment_id,
            "section_role": role,
            "label": label,
            "status": status,
            "source_url": source_url,
            "source_kit_id": None if kit is None else kit[0],
            "source_kit_version": None if kit is None else kit[1],
            "preview_digest": None if preview is None else "d" * 64,
            "preview_path": preview_path,
            "slot_keys": [slot["key"] for slot in (slots or [])],
            "slots": list(slots or []),
            "page_url": source_url,
            "created_at": "2026-08-27T00:00:00Z",
            "html": html,
            "css": css,
        }

    # --- the capability's three methods ---------------------------------------------------

    def list_sections(self, section_role=None):
        self.list_calls.append(section_role)
        return {
            "schema_version": 1,
            "workspace_id": "ws_test",
            "total": sum(
                section["status"] == "approved"
                and (section_role is None or section["section_role"] == section_role)
                for section in self.sections.values()
            ),
            "sections": [
                {
                    key: value
                    for key, value in section.items()
                    if key not in {"html", "css", "slots", "preview_path"}
                }
                for section in self.sections.values()
                if section["status"] == "approved"
                and (section_role is None or section["section_role"] == section_role)
            ],
        }

    def describe(self, fragment_ids):
        ids = list(fragment_ids)
        self.describe_calls.append(ids)
        return {
            fragment_id: {
                "slots": list(self.sections[fragment_id]["slots"]),
                "preview_path": self.sections[fragment_id]["preview_path"],
            }
            for fragment_id in ids
            if fragment_id in self.sections
        }

    def mint_repair(self, *, replaces, html, css, rung, note, release=False):
        """The raw lane's mint: a released row derived from `replaces`, resolvable at once."""
        new_id = f"frag_{len(self.sections):016x}"
        original = self.sections[replaces]
        self.add(
            new_id,
            role=original["section_role"],
            label=f"repair of {original['label']}",
            html=html,
            css=css,
            slots=[],
            status="approved" if release else "draft",
        )
        return {
            "fragment_id": new_id,
            "status": self.sections[new_id]["status"],
            "insertable": release,
            "derived_from": replaces,
            "derived_reason": f"repair rung {rung}: {note}",
        }

    def read_source(self, fragment_id):
        section = self.sections.get(fragment_id)
        if section is None:
            raise KeyError(f"fragment {fragment_id!r} was not found in this workspace")
        return {
            "fragment_id": fragment_id,
            "section_role": section.get("section_role") or section.get("role"),
            "label": section.get("label"),
            "source_url": section.get("source_url"),
            "status": section.get("status"),
            "derived_from": section.get("derived_from"),
            "slots": section.get("slots") or [],
            "html": section.get("html") or "",
            "css": section.get("css") or "",
        }

    def resolve_insertable(self, fragment_id):
        section = self.sections.get(fragment_id)
        if section is None:
            raise _FakeGateRefusal(
                "fragment.unresolved",
                f"fragment {fragment_id!r} was not found in this workspace",
                fragment_id,
            )
        if section["status"] != "approved":
            raise _FakeGateRefusal(
                "fragment.not_approved",
                f"fragment {fragment_id!r} is {section['status']}; a document may only pin an "
                "approved fragment (approve the brand kit it was cloned from)",
                fragment_id,
            )
        return {
            "fragment_id": fragment_id,
            "section_role": section["section_role"],
            "label": section["label"],
            "source_url": section["source_url"],
            "slots": list(section["slots"]),
            "preview_path": section["preview_path"],
            "render": {
                "html": section["html"],
                "css": section["css"],
                "slot_kinds": {
                    slot["key"]: slot["kind"] for slot in section["slots"]
                },
                "asset_digests": [],
            },
        }


def _FakeGateRefusal(code: str, message: str, fragment_id: str):
    """The REAL gate exception, built by hand.

    Not a look-alike: the substrate tells a permission refusal from a database outage by TYPE, so
    a fake that merely quacked like `FragmentReferenceError` would prove the wrong thing — it
    would pass whether or not the narrow catch existed.
    """
    from lumen_api.database import FragmentReferenceError

    return FragmentReferenceError(
        code, message, node_id="probe_cloned_section", fragment_id=fragment_id
    )


def _seed_doc() -> dict:
    return {
        "schema_version": 1,
        "id": "doc_cloned_sections",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "classes": "",
                        "new_tab": False,
                        "children": ["sec_existing"],
                    },
                    "sec_existing": {
                        "id": "sec_existing",
                        "kind": "section",
                        "tag": "section",
                        "classes": "py-16",
                        "children": [],
                    },
                },
            }
        ],
        # One registered asset, so an image slot has something real to bind to: the engine
        # refuses a slot pointing at an asset the document does not carry (LUMW0035).
        "assets": {
            "asset_logo_1": {
                "id": "asset_logo_1",
                "label": "Logo",
                "kind": "logo",
                "status": "ready",
                "source": {"kind": "generated", "model": "test-model", "request_id": None},
            }
        },
    }


@pytest.fixture()
def registry(tmp_path: Path) -> FakeRegistry:
    fake = FakeRegistry(tmp_path)
    fake.add(
        HERO_ID,
        role="hero",
        label="Hero — Care, on your terms",
        html=HERO_HTML,
        css=HERO_CSS,
        slots=[
            {"key": "cta_href", "kind": "href"},
            {"key": "headline", "kind": "text"},
        ],
    )
    fake.add(
        NAV_ID,
        role="nav",
        label="Nav",
        html=NAV_HTML,
        slots=[],
        preview=None,
    )
    fake.add(
        PROOF_ID,
        role="proof",
        label="Proof — Trusted by 400 clinics",
        html=PROOF_HTML,
        slots=[
            {"key": "body", "kind": "text"},
            {"key": "image_1", "kind": "image"},
            {"key": "visible", "kind": "visibility"},
        ],
        status="draft",
    )
    return fake


def _tools(tmp_path: Path, registry: FakeRegistry | None) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
    )
    return LumenWebTools(config, "Build a page", initial_web_doc=_seed_doc())


def _page(tools: LumenWebTools) -> dict:
    return tools.web_doc["pages"][0]


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def test_discovery_lists_the_approved_sections_with_what_a_choice_needs(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())

    assert result["status"] == "ok"
    ids = [row["fragment_id"] for row in result["results"]]
    assert HERO_ID in ids and NAV_ID in ids
    hero = next(row for row in result["results"] if row["fragment_id"] == HERO_ID)
    assert hero["section_role"] == "hero"
    assert hero["label"] == "Hero — Care, on your terms"
    assert hero["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]
    assert hero["source_url"] == "https://insight.example/"
    assert hero["brand_kit"] == {"id": "brand_kit_1", "version": 3}
    # The literal target that shows this section's real pixels — the `search_assets` convention.
    assert hero["view"] == f"cloned_section:{HERO_ID}"


def test_a_draft_section_is_not_offered(tmp_path: Path, registry: FakeRegistry) -> None:
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())

    assert PROOF_ID not in [row["fragment_id"] for row in result["results"]]


def test_a_query_narrows_to_the_matching_sections(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections("nav"))

    assert [row["fragment_id"] for row in result["results"]] == [NAV_ID]


def test_a_role_filter_asks_the_registry_for_that_role(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections(role="nav"))

    assert registry.list_calls[-1] == "nav"
    assert [row["fragment_id"] for row in result["results"]] == [NAV_ID]


def test_naming_a_fragment_id_returns_that_section(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(
        _tools(tmp_path, registry).search_cloned_sections(f"put the {HERO_ID} at the top")
    )

    assert result["results"][0]["fragment_id"] == HERO_ID
    assert result["results"][0]["id_match"] is True


def test_zero_matches_names_the_inventory_it_searched(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(
        _tools(tmp_path, registry).search_cloned_sections("submarine")
    )

    assert result["results"] == []
    assert "2" in result["note"]
    assert "cloned section" in result["note"]


def test_an_empty_library_says_so_rather_than_looking_like_a_bad_query(
    tmp_path: Path,
) -> None:
    result = json.loads(_tools(tmp_path, FakeRegistry(tmp_path)).search_cloned_sections())

    assert result["results"] == []
    assert "no cloned sections" in result["note"]


def test_discovery_only_describes_the_rows_it_will_return(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    _tools(tmp_path, registry).search_cloned_sections("nav")

    assert registry.describe_calls == [[NAV_ID]]


def test_without_a_registry_discovery_refuses_instead_of_pretending(
    tmp_path: Path,
) -> None:
    result = json.loads(_tools(tmp_path, None).search_cloned_sections())

    assert result["error_code"] == "cloned_section.registry_unavailable"


def test_a_bad_limit_is_refused(tmp_path: Path, registry: FakeRegistry) -> None:
    assert (
        json.loads(_tools(tmp_path, registry).search_cloned_sections(limit=0))["error_code"]
        == "cloned_section.bad_limit"
    )


def test_search_can_reach_every_match_without_redescribing_earlier_pages(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    expected = []
    for index in range(44):
        fragment_id = f"frag_{index:016x}"
        expected.append(fragment_id)
        registry.add(fragment_id, role="features", label="Product", html="<section/>")
    tools = _tools(tmp_path, registry)
    pages = []
    offset = 0
    while offset is not None:
        page = json.loads(tools.search_cloned_sections(q="product", limit=20, offset=offset))
        assert page["offset"] == offset
        assert page["total"] == 44
        assert page["inventory_truncated"] is False
        pages.append([row["fragment_id"] for row in page["results"]])
        offset = page["next_offset"]
    assert [len(page) for page in pages] == [20, 20, 4]
    assert [fragment_id for page in pages for fragment_id in page] == expected
    assert registry.describe_calls == pages


def test_page_filter_precedes_pagination_and_preserves_source_lineage(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    urls = ["https://insight.example/", "https://insight.example/product?tab=care"]
    for index in range(6):
        registry.add(
            f"frag_{index:016x}", role="features", label="Product", html="<section/>",
            source_url=urls[index % 2],
        )
    derived = registry.sections["frag_0000000000000003"]
    derived.update(composed="agent", derived_from="frag_0000000000000001")
    tools = _tools(tmp_path, registry)
    result = json.loads(tools.search_cloned_sections(page_url=urls[1], limit=1, offset=1))
    assert result["total"] == 3
    assert result["page_url"] == urls[1]
    assert result["next_offset"] == 2
    row = result["results"][0]
    assert row["fragment_id"] == derived["fragment_id"]
    assert row["composed"] == "agent"
    assert row["derived_from"] == "frag_0000000000000001"
    assert registry.describe_calls == [[derived["fragment_id"]]]
    # Exact URL filtering does not silently drop query parameters or override the filter
    # for a named ID. The URL identifies a recorded page, not captured-code authenticity.
    missing = json.loads(tools.search_cloned_sections(
        q="frag_0000000000000000", page_url=urls[1],
    ))
    assert missing["results"] == []
    assert "no cloned sections released" not in missing["note"]


def test_an_exhausted_search_page_is_not_reported_as_an_empty_library(
    tmp_path: Path, registry: FakeRegistry,
) -> None:
    tools = _tools(tmp_path, registry)
    result = json.loads(tools.search_cloned_sections(offset=2))
    assert result["results"] == []
    assert result["total"] == 2
    assert result["next_offset"] is None
    assert "offset" in result["note"]
    assert "no cloned sections released" not in result["note"]
    assert registry.describe_calls == []


def test_search_exposes_a_registry_cap_instead_of_claiming_complete_coverage(
    tmp_path: Path, registry: FakeRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = registry.list_sections()
    listing["total"] = 203  # Registry can expose only a bounded inventory.
    monkeypatch.setattr(registry, "list_sections", lambda role: listing)
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())
    assert result["total"] == 2
    assert result["inventory_scanned"] == 2
    assert result["inventory_total"] == 203
    assert result["inventory_truncated"] is True
    assert result["next_offset"] is None
    assert "203" in result["inventory_note"]
    assert "complete" in result["inventory_note"]


@pytest.mark.parametrize("offset", [-1, True, 1.5, "20"])
def test_bad_search_offsets_refuse_before_reading_the_registry(
    tmp_path: Path, registry: FakeRegistry, offset,
) -> None:
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections(offset=offset))
    assert result["error_code"] == "cloned_section.bad_offset"
    assert registry.list_calls == []


def test_native_search_tool_accepts_page_arguments_and_keeps_the_document_unchanged(
    tmp_path: Path, registry: FakeRegistry,
) -> None:
    from langchain_core.tools import StructuredTool

    tools = _tools(tmp_path, registry)
    before = json.dumps(tools.web_doc, sort_keys=True)
    result = json.loads(StructuredTool.from_function(tools.search_cloned_sections).invoke({
        "page_url": "https://insight.example/", "limit": 1, "offset": 1,
    }))
    assert [row["fragment_id"] for row in result["results"]] == [NAV_ID]
    assert result["offset"] == 1 and result["next_offset"] is None
    assert registry.describe_calls == [[NAV_ID]]
    assert json.dumps(tools.web_doc, sort_keys=True) == before


def test_search_does_not_invent_an_inventory_total_from_missing_metadata(
    tmp_path: Path, registry: FakeRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = registry.list_sections()
    listing.pop("total")
    monkeypatch.setattr(registry, "list_sections", lambda role: listing)
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())
    assert result["total"] == 2
    assert result["inventory_total"] is None
    assert result["inventory_truncated"] is None
    assert "unknown" in result["inventory_note"]


# --------------------------------------------------------------------------- #
# Looking at one
# --------------------------------------------------------------------------- #


def test_view_shows_a_cloned_sections_real_pixels(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    tools.search_cloned_sections()

    blocks = tools._view_content(f"cloned_section:{HERO_ID}")

    assert blocks[0]["type"] == "text"
    assert "Hero — Care, on your terms" in blocks[0]["text"]
    assert blocks[1]["type"] == "image"


def test_view_says_honestly_when_a_section_has_no_preview(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    tools.search_cloned_sections()

    blocks = tools._view_content(f"cloned_section:{NAV_ID}")

    assert len(blocks) == 1
    assert "no preview" in blocks[0]["text"]


def test_view_of_an_unknown_cloned_section_offers_the_ones_it_has_resolved(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    tools.search_cloned_sections()

    blocks = tools._view_content("cloned_section:frag_ffffffffffffffff")

    assert HERO_ID in blocks[0]["text"]


def test_view_before_any_search_says_to_search_first(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    blocks = _tools(tmp_path, registry)._view_content(f"cloned_section:{HERO_ID}")

    assert "search_cloned_sections" in blocks[0]["text"]


def test_the_unknown_target_menu_names_cloned_sections(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    blocks = _tools(tmp_path, registry)._view_content("nonsense")

    assert "cloned_section:" in blocks[0]["text"]


# --------------------------------------------------------------------------- #
# Inserting one
# --------------------------------------------------------------------------- #


def test_inserting_wraps_the_cloned_section_in_a_section_container(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(HERO_ID))

    assert result["status"] == "ok"
    page = _page(tools)
    section_id = result["section_node_id"]
    node_id = result["node_id"]
    # LUMW0011: the page root holds only sections, so the fragment can never be its direct child.
    assert page["nodes"][section_id]["kind"] == "section"
    assert page["nodes"][section_id]["children"] == [node_id]
    assert page["nodes"][node_id]["kind"] == "fragment"
    assert page["nodes"][node_id]["fragment_id"] == HERO_ID
    assert section_id in page["nodes"]["root"]["children"]


def test_an_insert_appends_at_the_end_of_the_page_by_default(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(HERO_ID))

    assert _page(tools)["nodes"]["root"]["children"] == [
        "sec_existing",
        result["section_node_id"],
    ]


def test_an_explicit_index_places_the_section_there(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(NAV_ID, index=0))

    assert _page(tools)["nodes"]["root"]["children"] == [
        result["section_node_id"],
        "sec_existing",
    ]


def test_the_insert_is_one_replayable_operation(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(HERO_ID))

    assert [op["kind"] for op in tools.operations_ledger] == ["insert_node"]
    operation = tools.operations_ledger[0]
    assert operation["root"] == result["section_node_id"]
    assert {node["id"] for node in operation["nodes"]} == {
        result["section_node_id"],
        result["node_id"],
    }


def test_slot_values_are_tagged_by_the_artifacts_own_slot_kinds(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.insert_cloned_section(
            HERO_ID,
            slot_values_json=json.dumps(
                {
                    "headline": "Care, on Privia's terms",
                    "cta_href": "https://privia.example/demo",
                }
            ),
        )
    )

    slots = _page(tools)["nodes"][result["node_id"]]["slots"]
    # An href IS a string to the node, so only the manifest kind knows it is a link target —
    # tagging by kind is what stops a URL being written into a heading.
    assert slots == {
        "cta_href": {"text": "https://privia.example/demo"},
        "headline": {"text": "Care, on Privia's terms"},
    }
    assert result["slots_bound"] == ["cta_href", "headline"]


def test_an_image_slot_takes_an_asset_id_and_a_visibility_slot_a_boolean(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    registry.sections[PROOF_ID]["status"] = "approved"
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.insert_cloned_section(
            PROOF_ID,
            slot_values_json=json.dumps(
                {"image_1": "asset_logo_1", "visible": False, "body": "Trusted here"}
            ),
        )
    )

    assert _page(tools)["nodes"][result["node_id"]]["slots"] == {
        "body": {"text": "Trusted here"},
        "image_1": {"asset": "asset_logo_1"},
        "visible": {"visible": False},
    }


def test_a_slot_the_section_does_not_have_is_refused_with_the_ones_it_does(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.insert_cloned_section(
            HERO_ID, slot_values_json=json.dumps({"subhead": "nope"})
        )
    )

    assert result["error_code"] == "cloned_section.unknown_slot"
    assert "headline" in result["message"]
    assert _page(tools)["nodes"]["root"]["children"] == ["sec_existing"]


def test_a_visibility_slot_refuses_a_non_boolean(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    registry.sections[PROOF_ID]["status"] = "approved"
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.insert_cloned_section(
            PROOF_ID, slot_values_json=json.dumps({"visible": "yes"})
        )
    )

    assert result["error_code"] == "cloned_section.bad_slot_value"


def test_the_engine_refuses_an_image_slot_pointing_at_an_unregistered_asset(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Bounds belong to the engine, not to a second copy of its rules in this tool."""
    registry.sections[PROOF_ID]["status"] = "approved"
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.insert_cloned_section(
            PROOF_ID, slot_values_json=json.dumps({"image_1": "asset_never_registered"})
        )
    )

    assert result["status"] == "rejected"
    assert any(
        diagnostic.get("code") == "LUMW0035"
        for diagnostic in result.get("diagnostics") or []
    )
    assert _page(tools)["nodes"]["root"]["children"] == ["sec_existing"]


def test_malformed_slot_json_is_refused(tmp_path: Path, registry: FakeRegistry) -> None:
    result = json.loads(
        _tools(tmp_path, registry).insert_cloned_section(HERO_ID, slot_values_json="[]")
    )

    assert result["error_code"] == "cloned_section.bad_slot_values"


# --------------------------------------------------------------------------- #
# The refusal the agent must be able to read
# --------------------------------------------------------------------------- #


def test_inserting_a_draft_section_surfaces_the_gates_own_refusal(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(PROOF_ID))

    assert result["status"] == "error"
    assert result["error_code"] == "fragment.not_approved"
    assert "approve the brand kit" in result["message"]
    assert result["fragment_id"] == PROOF_ID
    # Nothing was pinned: a refused insert leaves the page exactly as it was.
    assert _page(tools)["nodes"]["root"]["children"] == ["sec_existing"]


def test_inserting_an_unknown_section_surfaces_the_gates_unresolved_code(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(
        _tools(tmp_path, registry).insert_cloned_section("frag_ffffffffffffffff")
    )

    assert result["error_code"] == "fragment.unresolved"


def test_without_a_registry_the_insert_refuses(tmp_path: Path) -> None:
    result = json.loads(_tools(tmp_path, None).insert_cloned_section(HERO_ID))

    assert result["error_code"] == "cloned_section.registry_unavailable"


# --------------------------------------------------------------------------- #
# The inserted section actually renders
# --------------------------------------------------------------------------- #


def test_an_inserted_section_reaches_the_render_map_this_turn(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    tools.insert_cloned_section(HERO_ID)

    rendered = tools._fragment_render_map()
    assert HERO_ID in rendered
    assert "Care, on your terms" in rendered[HERO_ID]["html"]
    assert HERO_WRAPPER in (tools._fragment_css() or "")


def test_the_engine_renders_the_inserted_section_into_the_page(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HERO_ID)

    rendered = tools.core.web_render(
        tools.web_doc,
        tools.page_id,
        fragments=tools._fragment_render_map(),
        fragment_css=tools._fragment_css(),
    )

    html = rendered.get("html") or ""
    assert "Care, on your terms" in html
    assert HERO_WRAPPER in html


def test_the_preview_render_threads_the_inserted_section(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    from lumen_api.core import CoreError

    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HERO_ID)

    captured: dict = {}
    real_core = tools.core

    class _RecordingCore:
        def __getattr__(self, name):
            return getattr(real_core, name)

        def web_render(self, *args, **kwargs):
            captured.update(kwargs)
            raise CoreError("test.stop", "the kwargs are what this test judges")

    tools.core = _RecordingCore()
    tools.render_web_preview()

    assert HERO_ID in (captured.get("fragments") or {})
    assert HERO_WRAPPER in (captured.get("fragment_css") or "")


# --------------------------------------------------------------------------- #
# The reuse ladder: the law that makes reuse the default
# --------------------------------------------------------------------------- #


def _director_prompt() -> str:
    from lumen_agent.prompts_web import build_web_orchestrator_prompt

    return build_web_orchestrator_prompt(
        doc_title="Acme",
        has_existing_content=False,
        brand_card="{}",
        review_cap=2,
        author_cap=2,
    )


def _author_prompt() -> str:
    from lumen_agent.prompts_web import build_web_author_prompt

    return build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")


def test_the_director_must_walk_the_reuse_ladder() -> None:
    """The three rungs, in order, and the "look before you decide" rule beside them.

    The third rung's wording is F3.1's, not F2's (ruling D-F6): the absolutist "never edit a
    cloned section's internals" protected brokenness, so it is replaced by "never CASUALLY
    rewrite a WORKING one" plus a route for a broken one. The order is what is guarded.
    """
    prompt = _director_prompt()

    assert "REUSE LADDER" in prompt
    assert "search_cloned_sections" in prompt
    ladder = prompt.split("REUSE LADDER", 1)[1]
    reuse = ladder.index("REUSE a cloned section")
    compose = ladder.index("COMPOSE A NEW SECTION")
    never = ladder.index("NEVER CASUALLY REWRITE A WORKING CLONED SECTION")
    assert reuse < compose < never
    lowered = ladder.lower()
    assert "chrome" in lowered and "proof" in lowered


def test_the_reuse_decision_reaches_the_author_brief() -> None:
    """Same guarantee the imagery decision has: the choice is briefed, not kept in a head."""
    ladder = _director_prompt().split("REUSE LADDER", 1)[1]

    assert "author's brief" in ladder


def test_the_author_is_told_to_reuse_before_composing_and_never_to_rewrite() -> None:
    """The DISCIPLINE, not the prose. A founder rewrite that keeps these four rules stays green;
    one that drops a rule goes red, which is the only thing worth guarding."""
    prompt = _author_prompt()
    rule = prompt.split("REUSE BEFORE YOU COMPOSE", 1)[1].split("\n- ", 1)[0]

    # 1. It knows both tools.
    assert "search_cloned_sections" in rule and "insert_cloned_section" in rule
    # 2. Slots are the boundary — a clone's internals are not the author's to rewrite.
    lowered = rule.lower()
    assert "slot" in lowered
    # 3. The whole-page trap: a rewrite loses pinned clones, and the result names them.
    assert "author_web_page" in rule
    assert "dropped_cloned_sections" in rule
    # 4. A refusal is an answer, not a thing to retry.
    assert "fragment.not_approved" in rule


def test_the_author_holds_both_halves_of_the_ladder_and_the_director_only_discovery(
    tmp_path: Path, monkeypatch
) -> None:
    """The director decides and briefs; the AUTHOR is the only role that writes to the page."""
    import deepagents

    import lumen_agent.llm as llm
    from lumen_agent import harness_web

    capture: dict = {}
    marker = object()

    # Patch the real module's attribute rather than replacing `sys.modules["deepagents"]`: the
    # stub-the-module route poisons `lumen_agent.fs_backend`, whose backend class is built from
    # whatever `FilesystemBackend` was bound at first import, for every later test in the run.
    monkeypatch.setattr(
        deepagents, "create_deep_agent", lambda **kwargs: capture.update(kwargs) or marker
    )
    monkeypatch.setattr(
        harness_web, "materialize_agent_workspace", lambda _config: None
    )
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(
        llm, "assert_all_role_models_support_image_input", lambda _config: None
    )

    harness_web.create_web_deepagent(
        "Build a page",
        replace(
            AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
        ),
        _seed_doc(),
    )

    def names(entries):
        return {
            getattr(entry, "name", None) or getattr(entry, "__name__", "")
            for entry in entries
        }

    author = next(
        sub for sub in capture["subagents"] if sub["name"] == "lumen-web-author"
    )
    assert {"search_cloned_sections", "insert_cloned_section"} <= names(author["tools"])
    orchestrator = names(capture["tools"])
    assert "search_cloned_sections" in orchestrator
    assert "insert_cloned_section" not in orchestrator


def test_the_view_tool_advertises_the_cloned_section_target(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A target nothing names is a target nobody uses — the `asset:` precedent."""
    from lumen_agent.tools.web_substrate import make_web_view_tool

    view = make_web_view_tool(_tools(tmp_path, registry), can_render=False)

    assert "cloned_section:" in (view.description or "")


# --------------------------------------------------------------------------- #
# A whole-page rewrite drops every pinned clone — LOUDLY
# --------------------------------------------------------------------------- #

TWO_SECTIONS = """
<section id="alpha" class="bg-light"><h2 id="alpha_title">Alpha</h2></section>
<section id="beta" class="bg-card"><h2 id="beta_title">Beta</h2></section>
"""


def _seed_doc_with_pin(fragment_id: str = HERO_ID) -> dict:
    """A page that already carries a cloned section, as a stored document would."""
    doc = _seed_doc()
    page = doc["pages"][0]
    page["nodes"]["root"]["children"] = ["sec_pinned"]
    page["nodes"]["sec_pinned"] = {
        "id": "sec_pinned",
        "kind": "section",
        "tag": "section",
        "classes": "w-full",
        "children": ["frg_pinned"],
    }
    page["nodes"]["frg_pinned"] = {
        "id": "frg_pinned",
        "kind": "fragment",
        "classes": "",
        "fragment_id": fragment_id,
        "slots": {},
    }
    del page["nodes"]["sec_existing"]
    return doc


def _tools_with(tmp_path: Path, registry: FakeRegistry | None, doc: dict) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
    )
    return LumenWebTools(config, "Build a page", initial_web_doc=doc)


def test_a_whole_page_rewrite_names_every_cloned_section_it_dropped(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    pinned = json.loads(tools.insert_cloned_section(HERO_ID))

    result = json.loads(tools.author_web_page(TWO_SECTIONS))

    assert result["status"] == "ok"
    dropped = result["dropped_cloned_sections"]
    assert [entry["fragment_id"] for entry in dropped] == [HERO_ID]
    assert dropped[0]["node_id"] == pinned["node_id"]
    assert dropped[0]["label"] == "Hero — Care, on your terms"
    assert dropped[0]["section_role"] == "hero"


def test_the_drop_rides_the_warnings_bucket_the_author_must_answer_for(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """`warnings` is the lane's "this is work" bucket; `advice` is the "judge it" one."""
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HERO_ID)

    result = json.loads(tools.author_web_page(TWO_SECTIONS))

    warning = next(
        entry
        for entry in result["warnings"]
        if entry.get("code") == "LUMA0810"
    )
    assert HERO_ID in warning["message"]
    assert "insert_cloned_section" in warning["hint"]
    assert not [
        entry for entry in result["advice"] if entry.get("code") == "LUMA0810"
    ]


def test_a_pin_this_turn_never_looked_up_is_still_named(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A clone pinned by an EARLIER turn has no label in this turn's memory. Name it anyway."""
    tools = _tools_with(tmp_path, registry, _seed_doc_with_pin())

    result = json.loads(tools.author_web_page(TWO_SECTIONS))

    dropped = result["dropped_cloned_sections"]
    assert [entry["fragment_id"] for entry in dropped] == [HERO_ID]
    assert dropped[0]["node_id"] == "frg_pinned"
    # Honest about what it does not know, rather than inventing a label.
    assert dropped[0]["label"] is None
    assert dropped[0]["section_role"] is None


def test_a_page_with_no_clones_gains_no_drop_report(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    result = json.loads(_tools(tmp_path, registry).author_web_page(TWO_SECTIONS))

    assert result["status"] == "ok"
    assert "dropped_cloned_sections" not in result
    assert not [
        entry for entry in result["warnings"] if entry.get("code") == "LUMA0810"
    ]


def test_replacing_a_clones_own_section_names_the_drop_too(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The same wipe arrives through the scoped path when the target section holds a clone."""
    tools = _tools_with(tmp_path, registry, _seed_doc_with_pin())

    result = json.loads(
        tools.author_web_subtree(
            "sec_pinned", '<section id="sec_pinned"><h2 id="t">Replaced</h2></section>'
        )
    )

    assert result["status"] == "ok"
    assert [entry["fragment_id"] for entry in result["dropped_cloned_sections"]] == [
        HERO_ID
    ]


def test_a_scoped_edit_that_keeps_the_clone_reports_no_drop(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Discrimination guard: only a pin that actually LEFT the page is reported."""
    doc = _seed_doc_with_pin()
    page = doc["pages"][0]
    page["nodes"]["root"]["children"] = ["sec_pinned", "sec_other"]
    page["nodes"]["sec_other"] = {
        "id": "sec_other",
        "kind": "section",
        "tag": "section",
        "classes": "",
        "children": [],
    }
    tools = _tools_with(tmp_path, registry, doc)

    result = json.loads(
        tools.author_web_subtree(
            "sec_other", '<section id="sec_other"><h2 id="t">Other</h2></section>'
        )
    )

    assert result["status"] == "ok"
    assert "dropped_cloned_sections" not in result


def test_a_rejected_rewrite_reports_no_drop_because_nothing_was_replaced(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools_with(tmp_path, registry, _seed_doc_with_pin())

    result = json.loads(tools.author_web_page('<section id="a"><i data-icon="globe"></i></section>'))

    assert result["status"] == "rejected"
    assert "dropped_cloned_sections" not in result
    # The page is untouched, so the clone is still there.
    assert "frg_pinned" in tools.web_doc["pages"][0]["nodes"]


def test_a_registry_outage_reads_as_an_outage_not_as_a_permission_refusal(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A blip must not arrive wearing "nobody released this, compose instead" clothes.

    The permission envelope tells the agent to stop asking and compose the band. A database
    that was briefly unreachable is the opposite instruction, and a turn that took the first
    answer for the second would abandon the client's real chrome over a timeout.
    """

    def _boom(_fragment_id):
        raise TimeoutError("connection to the design database timed out")

    registry.resolve_insertable = _boom  # type: ignore[assignment]
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(HERO_ID))

    assert result["error_code"] == "cloned_section.registry_failed"
    assert "TimeoutError" in result["message"]
    assert _page(tools)["nodes"]["root"]["children"] == ["sec_existing"]


def test_a_gate_refusal_carrying_no_code_still_reads_as_a_permission_answer(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The narrow catch is on the TYPE, so a gate error is never mistaken for an outage."""
    from lumen_api.database import FragmentReferenceError

    def _refuse(_fragment_id):
        error = FragmentReferenceError(
            "", "nope", node_id="n", fragment_id=HERO_ID
        )
        raise error

    registry.resolve_insertable = _refuse  # type: ignore[assignment]

    result = json.loads(_tools(tmp_path, registry).insert_cloned_section(HERO_ID))

    assert result["error_code"] == "cloned_section.not_insertable"


def test_search_says_how_many_matched_not_only_how_many_it_showed(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """W5. `count` alone cannot tell a complete answer from a truncated one, and the default
    limit is 8 — so on the F2 acceptance walk's own site an unqualified call showed 8 of 13
    approved sections with nothing saying the other five existed."""
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())
    assert result["total"] >= result["count"]
    assert "total" in result

    narrowed = json.loads(_tools(tmp_path, registry).search_cloned_sections(limit=1))
    assert narrowed["count"] == 1
    assert narrowed["total"] > 1
    assert narrowed["next_offset"] == 1
    remainder = json.loads(_tools(tmp_path, registry).search_cloned_sections(
        offset=narrowed["next_offset"],
    ))
    assert remainder["count"] + narrowed["count"] == narrowed["total"]


def _seed_doc_with_two_pins_of_one_band(fragment_id: str = HERO_ID) -> dict:
    """One band pinned TWICE — the same CTA above and below a long section is an ordinary page."""
    doc = _seed_doc_with_pin(fragment_id)
    page = doc["pages"][0]
    page["nodes"]["root"]["children"] = ["sec_pinned", "sec_second"]
    page["nodes"]["sec_second"] = {
        "id": "sec_second",
        "kind": "section",
        "tag": "section",
        "classes": "w-full",
        "children": ["frg_second"],
    }
    page["nodes"]["frg_second"] = {
        "id": "frg_second",
        "kind": "fragment",
        "classes": "",
        "fragment_id": fragment_id,
        "slots": {},
    }
    return doc


def test_losing_one_of_two_pins_of_the_same_band_is_reported(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """F3.4, the structural fix the F1 wave carried. The drop report was keyed by fragment id, so
    a rewrite that removed ONE of two instances left the id present on both sides and said
    nothing at all: the band-level truth held, and the page had silently lost half of it."""
    tools = _tools_with(tmp_path, registry, _seed_doc_with_two_pins_of_one_band())

    result = json.loads(
        tools.author_web_subtree(
            "sec_pinned", '<section id="sec_pinned"><h2 id="t">Replaced</h2></section>'
        )
    )

    assert result["status"] == "ok"
    (dropped,) = result["dropped_cloned_sections"]
    assert dropped["fragment_id"] == HERO_ID
    assert dropped["node_ids"] == ["frg_pinned"]
    assert dropped["surviving_pins"] == 1
    warning = next(
        entry for entry in result["warnings"] if entry.get("code") == "LUMA0810"
    )
    # The sentence says which happened: "no longer on the page" would be false here.
    assert "1 of its pins, 1 still on the page" in warning["message"]
    assert "0 of them are no longer on the page at all" in warning["message"]


def test_losing_both_pins_of_one_band_still_reads_as_a_whole_drop(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools_with(tmp_path, registry, _seed_doc_with_two_pins_of_one_band())

    result = json.loads(tools.author_web_page(TWO_SECTIONS))

    (dropped,) = result["dropped_cloned_sections"]
    assert sorted(dropped["node_ids"]) == ["frg_pinned", "frg_second"]
    assert dropped["surviving_pins"] == 0
    warning = next(
        entry for entry in result["warnings"] if entry.get("code") == "LUMA0810"
    )
    assert "1 of them are no longer on the page at all" in warning["message"]
    assert "still on the page" not in warning["message"]


def test_the_picker_flags_a_kept_despite_broken_family_repair(tmp_path) -> None:
    """T27 review I-2: the R-X4 flag (`lineage_degraded_fallback`) existed on the projection
    and the picker's whitelist dropped it — no production reader. An author browsing the
    library must see that a seated repair's whole family is broken, not only at the pin."""
    registry = FakeRegistry(tmp_path)
    registry.add(HERO_ID, role="hero", label="Hero — kept per policy", html="<section/>")
    registry.sections[HERO_ID]["degraded"] = True
    registry.sections[HERO_ID]["degraded_reason"] = "dead_height"
    registry.sections[HERO_ID]["lineage_degraded_fallback"] = True

    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())

    row = next(r for r in result["results"] if r["fragment_id"] == HERO_ID)
    assert row["lineage_degraded_fallback"] is True
    assert "keep_flagged" in row["lineage_degraded_note"]
    assert "needs review" in row["lineage_degraded_note"]


# --------------------------------------------------------------------------- #
# The raw repair lane, walked through the TOOL (the path dry run 2 crashed on)
# --------------------------------------------------------------------------- #


def test_a_raw_repair_swaps_the_pinned_band_in_place(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Red under fe466fe29: the raw branch read `instances[0]` before assignment
    (UnboundLocalError killed a live turn, dry run 2, 2026-08-31). The registry-level
    tests minted directly and never walked the tool, so nothing caught it."""
    tools = _tools(tmp_path, registry)
    pinned = json.loads(tools.insert_cloned_section(HERO_ID))
    assert pinned["status"] == "ok"
    old_section = pinned["section_node_id"]

    result = json.loads(
        tools.repair_cloned_section(
            HERO_ID,
            '<section id="sec_fix"><h2>Same story, working band</h2></section>',
            rung=2,
            note="campaign variant: one CTA, carousel dropped",
            css=".sec_fix { padding: 96px 0 }",
        )
    )

    assert result["status"] == "ok"
    assert result.get("raw") is True
    page = _page(tools)
    # The broken band came off the page and the released repair sits in its place.
    assert old_section not in page["nodes"]["root"]["children"]
    new_fragment_id = result["repair_fragment_id"]
    pins = [
        node["fragment_id"]
        for node in page["nodes"].values()
        if node.get("kind") == "fragment"
    ]
    assert new_fragment_id in pins
    assert HERO_ID not in pins


# --- inspect_cloned_section: the raw lane's missing read (third solo Ramp run, 2026-09-04) ---


def test_inspect_cloned_section_shows_the_real_html_and_css(tmp_path: Path) -> None:
    """Every raw-lane instruction says "remix the original's actual CSS", and until this tool
    existed nothing showed the agent those bytes — search lists slots, view shows a picture —
    so the third solo run grepped the filesystem for clone markup and then composed from
    memory. The read returns the captured html + scoped css + slots, truncating honestly."""
    registry = FakeRegistry(tmp_path)
    registry.add(
        fragment_id="frag_inspect_me",
        role="hero",
        label="Homepage hero",
        html='<section class="hp-hero"><h1 data-slot="headline">Real</h1></section>',
        css=".hp-hero { padding: 96px 0; background: linear-gradient(#a960ee, #ffcb57); }",
        slots=[{"key": "headline", "kind": "text"}],
    )
    tools = _tools(tmp_path, registry)
    result = json.loads(tools.inspect_cloned_section("frag_inspect_me"))
    assert result["status"] == "ok"
    assert result["label"] == "Homepage hero"
    assert 'class="hp-hero"' in result["html"]
    assert "linear-gradient(#a960ee, #ffcb57)" in result["css"]
    assert result["html_truncated"] is False and result["css_truncated"] is False
    assert result["slots"] == [{"key": "headline", "kind": "text"}]
    missing = json.loads(tools.inspect_cloned_section("frag_nope"))
    assert missing["status"] == "error" and missing["error_code"] == "cloned_section.not_found"


def test_inspect_cloned_section_default_still_returns_bounded_source_prefixes(
    tmp_path: Path,
) -> None:
    registry = FakeRegistry(tmp_path)
    html = "<section>" + "é🧭" * 10_000 + "</section>"
    css = ".card{color:red}" * 2_000
    registry.add("frag_long", role="feature", label="Long source", html=html, css=css)

    result = json.loads(_tools(tmp_path, registry).inspect_cloned_section("frag_long"))

    for kind, source in (("html", html), ("css", css)):
        assert result[kind] == source[:12_000]
        assert result[f"{kind}_chars"] == len(source)
        assert result[f"{kind}_truncated"] is True
        assert result[f"{kind}_offset"] == 0
        assert result[f"{kind}_end_offset"] == 12_000
        assert result[f"{kind}_slice_chars"] == 12_000
        assert result[f"{kind}_next_offset"] == 12_000


def test_inspect_cloned_section_pages_reassemble_exact_source_without_mutation(
    tmp_path: Path,
) -> None:
    registry = FakeRegistry(tmp_path)
    sources = {
        "html": ("é🧭<a href='/demo'>Read</a>" * 2_000)[:42_268],
        "css": (".café{color:red} /* 🧭 */\n" * 10_000)[:195_384],
    }
    registry.add("frag_long", role="feature", label="Long source", **sources)
    tools = _tools(tmp_path, registry)
    original_doc = json.dumps(tools.web_doc, sort_keys=True)
    original_registry = json.dumps(registry.sections, sort_keys=True)
    offsets = {"html": 0, "css": 0}
    chunks = {"html": [], "css": []}

    for _ in range(20):
        result = json.loads(tools.inspect_cloned_section(
            "frag_long", html_offset=offsets["html"], css_offset=offsets["css"],
        ))
        assert result["status"] == "ok"
        assert result["fragment_id"] == "frag_long"
        for kind, source in sources.items():
            chunk = result[kind]
            end = offsets[kind] + len(chunk)
            assert len(chunk) <= 12_000
            assert chunk == source[offsets[kind]:end]
            assert result[f"{kind}_offset"] == offsets[kind]
            assert result[f"{kind}_end_offset"] == end
            assert result[f"{kind}_chars"] == len(source)
            assert result[f"{kind}_slice_chars"] == len(chunk)
            assert result[f"{kind}_next_offset"] == (end if end < len(source) else None)
            assert result[f"{kind}_truncated"] is (end < len(source))
            chunks[kind].append(chunk)
            offsets[kind] = end
        if all(result[f"{kind}_next_offset"] is None for kind in sources):
            break
    else:
        pytest.fail("bounded inspection did not reach the end of both source streams")

    assert {kind: "".join(parts) for kind, parts in chunks.items()} == sources
    assert json.dumps(tools.web_doc, sort_keys=True) == original_doc
    assert json.dumps(registry.sections, sort_keys=True) == original_registry
    assert tools.operations_ledger == []


@pytest.mark.parametrize("field", ["html_offset", "css_offset"])
@pytest.mark.parametrize("offset", [-1, True, 1.5, "1", None, 10**30])
def test_inspect_cloned_section_refuses_invalid_offsets(tmp_path: Path, field, offset) -> None:
    registry = FakeRegistry(tmp_path)
    registry.add("frag_small", role="feature", label="Small", html="html", css="css")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.inspect_cloned_section("frag_small", **{field: offset}))

    assert result["status"] == "error"
    assert result["error_code"] == "cloned_section.bad_offset"
    assert "html" not in result and "css" not in result
    assert tools.operations_ledger == []


def test_inspect_cloned_section_empty_source_and_end_offsets_are_terminal(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    registry.add("frag_small", role="feature", label="Small", html="html", css="")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.inspect_cloned_section("frag_small", html_offset=4))

    assert result["status"] == "ok"
    for kind in ("html", "css"):
        assert result[kind] == ""
        assert result[f"{kind}_slice_chars"] == 0
        assert result[f"{kind}_next_offset"] is None
        assert result[f"{kind}_truncated"] is False


def test_inspect_cloned_section_continuation_still_uses_workspace_registry(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    registry.add("frag_here", role="feature", label="Local", html="local")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.inspect_cloned_section("frag_other_workspace", html_offset=12_000))

    assert result["status"] == "error"
    assert result["error_code"] == "cloned_section.not_found"
    assert "html" not in result and "css" not in result


# --------------------------------------------------------------------------- #
# A pin is born with a human name (R-A5)
# --------------------------------------------------------------------------- #


def test_a_pin_stamps_a_human_name_on_both_nodes(tmp_path: Path) -> None:
    """A page the agent pinned and the same page opened by a human must agree on what each
    band is called. The editor derives `"{Role} — {label}"` for an unnamed clone; the pin
    stamps exactly those words, so the layers panel reads the same either way — and the name
    rides INSIDE the `insert_node` payload, so the commit gate's replay reproduces it."""
    named_hero_id = "frag_00000000000000aa"
    registry = FakeRegistry(tmp_path)
    registry.add(
        fragment_id=named_hero_id,
        role="hero",
        label="Stripe homepage hero",
        html='<section class="sh-hero"><h1>Real</h1></section>',
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(named_hero_id, slot_values_json="{}"))

    assert result["status"] == "ok"
    page = _page(tools)
    section = page["nodes"][result["section_node_id"]]
    fragment = page["nodes"][result["node_id"]]
    assert section["kind"] == "section" and fragment["kind"] == "fragment"
    assert section["name"] == "Hero — Stripe homepage hero"
    assert fragment["name"] == "Hero — Stripe homepage hero"
    # No second operation to keep in step: the name is part of the one insert that replays.
    assert [op["kind"] for op in tools.operations_ledger] == ["insert_node"]
    assert {node["name"] for node in tools.operations_ledger[0]["nodes"]} == {
        "Hero — Stripe homepage hero"
    }


def test_pin_display_name_degrades_honestly() -> None:
    from lumen_agent.tools.web_substrate import pin_display_name

    assert (
        pin_display_name({"section_role": "footer", "label": "Stripe footer"})
        == "Footer — Stripe footer"
    )
    assert pin_display_name({"section_role": "cta", "label": ""}) == "Cta"
    assert pin_display_name({"label": "Only a label"}) == "Only a label"
    assert pin_display_name({}) == "Cloned section"


# --------------------------------------------------------------------------- #
# A human's interior text edits are visible to the agent (R-A6, slice 3)
# --------------------------------------------------------------------------- #


def test_inspect_lists_the_human_text_overrides_on_every_pin_of_that_clone(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """An override is the ONE interior edit a human may make to a clone, and the agent has to
    be able to see it — otherwise the next turn rewrites the band and silently argues with the
    marketer about their own headline. `inspect_cloned_section` reads them off the DOCUMENT
    (the artifact is immutable; an override is per-instance), so the list is per pinned node."""
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(HERO_ID))
    node_id = pin["node_id"]

    applied = json.loads(
        tools.web_ops(
            json.dumps(
                [
                    {
                        "kind": "set_fragment_text_override",
                        "page_id": "home",
                        "id": node_id,
                        "path": ":nth-child(1)",
                        "override": {
                            "text": "Care, your way",
                            "bold": True,
                            "italic": False,
                            "underline": False,
                            "size": 1,
                        },
                    }
                ]
            )
        )
    )
    assert applied["status"] == "ok", applied

    result = json.loads(tools.inspect_cloned_section(HERO_ID))
    assert result["status"] == "ok"
    assert result["text_overrides"] == [
        {
            "page_id": "home",
            "node_id": node_id,
            "path": ":nth-child(1)",
            "text": "Care, your way",
            "bold": True,
            "italic": False,
            "underline": False,
            "size": 1,
        }
    ]
    terminal = json.loads(tools.inspect_cloned_section(
        HERO_ID, html_offset=result["html_chars"], css_offset=result["css_chars"],
    ))
    assert terminal["text_overrides"] == result["text_overrides"]


def test_a_clone_nobody_has_edited_lists_no_overrides(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HERO_ID)
    assert json.loads(tools.inspect_cloned_section(HERO_ID))["text_overrides"] == []


def test_source_version_evidence_survives_search_and_inspection(tmp_path: Path) -> None:
    class SourceRegistry(FakeRegistry):
        def read_source(self, fragment_id):
            return {**super().read_source(fragment_id), **metadata}

    metadata = {
        "source_kit_id": "kit_original", "source_kit_version": 1,
        "source_kit_bindings": [{"brand_kit_id": "kit_current", "version": 2}],
        "page_url": "https://insight.example/product", "section_index": 3,
        "created_at": "2026-09-19T00:00:00Z", "payload_digest": "a" * 64,
        "capture_evidence": {"snapshot_id": "snap_old", "dead_height_check": {
            "assessed": False, "because": "no_preview"}},
        "behavior_evidence": {"basis": "sanitized_html_snapshot",
                              "controller_status": "controller_not_retained",
                              "behavior_test": "not_performed"},
    }
    registry = SourceRegistry(tmp_path)
    registry.add("frag_evidence", role="hero", label="Product hero", html=HERO_HTML)
    registry.sections["frag_evidence"].update(metadata)
    tools = _tools(tmp_path, registry)
    found = json.loads(tools.search_cloned_sections())["results"][0]
    assert found["brand_kit"] == {"id": "kit_original", "version": 1}
    assert found["source_kit_bindings"] == metadata["source_kit_bindings"]
    assert found["page_url"] == metadata["page_url"]
    inspected = json.loads(tools.inspect_cloned_section("frag_evidence"))
    for key, value in metadata.items():
        assert inspected[key] == value
    # Association is not freshness or visual acceptance.
    assert "fidelity_verified" not in inspected
    assert "captured_at" not in inspected


def test_authored_product_band_is_not_mislabeled_as_campaign_chrome(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    registry.add("frag_product", role="feature", label="Product", html=HERO_HTML)
    registry.sections["frag_product"]["composed"] = "agent"
    result = json.loads(_tools(tmp_path, registry).search_cloned_sections())["results"][0]
    assert result["composed"] == "agent"
    assert "authored" in result["composed_note"]
    assert "shell" not in result["composed_note"]


class HrefRegistry(FakeRegistry):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        from lumen_api.fragments.artifact import build_fragment_artifact
        from lumen_api.fragments.slots import SlotSpec

        source = build_fragment_artifact(
            html=HERO_HTML.replace(
                "</section>", '<a href="/demo">Lower one</a><a href="/demo">Lower two</a></section>'
            ),
            css=".clone-hero{padding:64px}@media(max-width:600px){.clone-hero{padding:16px}}",
            rehosted={}, slots=[SlotSpec(key="headline", kind="text", selector="h1"),
                                SlotSpec(key="cta_href", kind="href", selector="a")],
        )
        self.original = source.fragment_id
        self.payloads = {}
        self.mint_calls = []
        self.install(source)

    def install(self, artifact):
        payload = artifact.payload
        self.payloads[artifact.fragment_id] = payload
        self.add(artifact.fragment_id, role="hero", label="Captured hero", html=payload["html"],
                 css=payload["css"], slots=[{"key": key, "kind": spec["kind"]}
                                          for key, spec in payload["slot_manifest"].items()])

    def mint_href_repair(self, *, replaces, replacements=None, label_replacements=None, rung, note):
        from lumen_api.fragments.href_repair import build_href_repair

        self.mint_calls.append(replacements)
        repair = build_href_repair(self.payloads[replaces], replacements, label_replacements=label_replacements)
        self.install(repair.artifact)
        return {"fragment_id": repair.artifact.fragment_id, "status": "approved",
                "match_counts": repair.match_counts, "label_match_counts": repair.label_match_counts,
                "lineage_kept": True, "converged": False}


class RawRepairRegistry(HrefRegistry):
    """Real sanitize/slot/scoping primitives; only artifact custody is in memory."""

    def __init__(self, tmp_path):
        FakeRegistry.__init__(self, tmp_path)
        from lumen_api.fragments import build_fragment_artifact
        from lumen_ingestion.sections.slotdetect import detect_slots

        html = (
            '<section class="clone-hero"><h1>Original headline</h1>'
            '<p>Original body</p><img src="/asset-store/' + 'a' * 64 + '" alt="Brand">'
            '<a href="https://seller.example/demo">Book a demo</a></section>'
        )
        source = build_fragment_artifact(
            html=html, css='.clone-hero { padding: 160px }',
            rehosted={}, slots=detect_slots(html).specs,
        )
        self.original = source.fragment_id
        self.payloads = {}
        self.install(source)

    def mint_repair(self, *, replaces, html, css, rung, note, release=False):
        from lumen_api.fragments import build_fragment_artifact, sanitize_fragment_html
        from lumen_ingestion.sections.slotdetect import detect_slots

        sanitized = sanitize_fragment_html(html, rehosted={})
        artifact = build_fragment_artifact(
            html=sanitized.html, css=css, rehosted={},
            slots=detect_slots(sanitized.html).specs, source_fragment_id=replaces,
        )
        self.install(artifact)
        source = self.payloads[replaces]
        return {
            'fragment_id': artifact.fragment_id, 'status': 'approved', 'derived_from': replaces,
            'preserves_pin_content': source['html'] == artifact.payload['html']
            and source['slot_manifest'] == artifact.payload['slot_manifest'],
        }


def test_css_only_raw_repair_preserves_live_copy_logo_and_human_edit_in_place(tmp_path):
    registry = RawRepairRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(
        registry.original,
        slot_values_json=json.dumps({'body': 'Account-specific body', 'image': 'asset_logo_1'}),
    ))
    assert pin['status'] == 'ok', pin
    assert json.loads(tools.web_ops(json.dumps([{
        'kind': 'set_node_props', 'page_id': 'home', 'id': pin['section_node_id'],
        'props': {'kind': 'section', 'tag': 'section', 'anchor_id': 'account-insights'},
    }, {
        'kind': 'set_fragment_text_override', 'page_id': 'home', 'id': pin['node_id'],
        'path': ':nth-child(1) > :nth-child(1)',
        'override': {'text': 'Human account headline', 'bold': True},
    }])))['status'] == 'ok'
    before = json.loads(json.dumps(tools.web_doc))
    source = registry.payloads[registry.original]
    result = json.loads(tools.repair_cloned_section(
        registry.original, html=source['html'], css=source['css'].replace('160px', '32px'),
        note='Reduce spacing only; keep current copy and logo',
    ))
    assert result['status'] == 'ok', result
    expected = before
    expected['pages'][0]['nodes'][pin['node_id']]['fragment_id'] = result['repair_fragment_id']
    assert tools.web_doc == expected
    assert result['section_node_id'] == pin['section_node_id']
    assert tools.operations_ledger[-1]['kind'] == 'set_node_props'
    for mode in ('editor', 'delivery'):
        rendered = tools.core.web_render(
            tools.web_doc, 'home', mode=mode,
            fragments=tools._fragment_render_map(), fragment_css=tools._fragment_css(),
        )['html']
        assert 'Human account headline' in rendered
        assert 'Account-specific body' in rendered
        assert 'id="account-insights"' in rendered


def test_raw_copy_change_is_not_masked_by_old_copy_overrides(tmp_path):
    registry = RawRepairRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(
        registry.original, slot_values_json=json.dumps({'headline': 'Old bound headline'}),
    ))
    source = registry.payloads[registry.original]
    result = json.loads(tools.repair_cloned_section(
        registry.original, html=source['html'].replace('Original headline', 'Revised campaign'),
        css=source['css'], note='Change campaign headline',
    ))
    assert result['status'] == 'ok', result
    assert result['section_node_id'] != pin['section_node_id']
    rendered = tools.core.web_render(
        tools.web_doc, 'home', fragments=tools._fragment_render_map(),
        fragment_css=tools._fragment_css(),
    )['html']
    assert 'Revised campaign' in rendered
    assert 'Old bound headline' not in rendered


def test_exact_href_tool_schema_and_real_render_preserve_pin_human_edits_and_binding(tmp_path):
    from langchain_core.tools import StructuredTool
    from selectolax.lexbor import LexborHTMLParser

    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(
        registry.original, slot_values_json=json.dumps({"cta_href": "https://client.example/bound"})
    ))
    tools.web_ops(json.dumps([{
        "kind": "set_fragment_text_override", "page_id": "home", "id": pin["node_id"],
        "path": ":nth-child(1) > :nth-child(1)",
        "override": {"text": "Human headline", "bold": True},
    }]))
    before = json.loads(json.dumps(tools.web_doc))
    original_source = json.loads(json.dumps(registry.payloads[registry.original]))
    exposed = StructuredTool.from_function(tools.repair_cloned_section)
    schema = exposed.args_schema.model_json_schema()
    assert schema["required"] == ["fragment_id"]
    result = json.loads(exposed.invoke({
        "fragment_id": registry.original, "note": "Restore the two inherited navigation targets",
        "href_replacements_json": json.dumps({"/demo": "https://client.example/demo"}),
    }))
    assert result["status"] == "ok", result
    assert result["match_counts"] == {"/demo": 2}
    expected = before
    expected["pages"][0]["nodes"][pin["node_id"]]["fragment_id"] = result["repair_fragment_id"]
    assert tools.web_doc == expected
    assert registry.payloads[registry.original] == original_source
    assert tools.operations_ledger[-1]["kind"] == "set_node_props"
    for mode in ("editor", "delivery"):
        rendered = tools.core.web_render(
            tools.web_doc, "home", mode=mode,
            fragments=tools._fragment_render_map(), fragment_css=tools._fragment_css(),
        )
        tree = LexborHTMLParser(rendered["html"])
        assert [a.attributes["href"] for a in tree.css(".clone-hero a")] == [
            "https://client.example/bound", "https://client.example/demo", "https://client.example/demo",
        ]
        assert tree.css_first(".clone-hero h1").text() == "Human headline"


@pytest.mark.parametrize("mapping", ["{}", "[]", "not json", '{"/demo":"javascript:x"}',
                                    '{"/demo":"/a","/demo":"/b"}', "x" * 40_001],
                         ids=["empty", "array", "malformed", "unsafe", "duplicate", "oversized"])
def test_exact_href_tool_rejects_bad_input_before_registry_mint(tmp_path, mapping):
    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(registry.original)
    before = json.dumps(tools.web_doc, sort_keys=True)
    result = json.loads(tools.repair_cloned_section(
        registry.original, note="Fix links", href_replacements_json=mapping,
    ))
    assert result["error_code"] == "repair.bad_href_map"
    assert not registry.mint_calls
    assert json.dumps(tools.web_doc, sort_keys=True) == before


def test_exact_href_tool_refuses_multiple_pins_and_mixed_source_inputs(tmp_path):
    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(registry.original)
    result = json.loads(tools.repair_cloned_section(
        registry.original, html="replacement", note="Fix links",
        href_replacements_json='{"/demo":"/x"}',
    ))
    assert result["error_code"] == "repair.bad_href_map"
    tools.insert_cloned_section(registry.original)
    result = json.loads(tools.repair_cloned_section(
        registry.original, note="Fix links", href_replacements_json='{"/demo":"/x"}',
    ))
    assert result["error_code"] == "repair.ambiguous_pin"
    assert not registry.mint_calls


def test_exact_href_tool_reports_released_artifact_when_swap_fails(tmp_path, monkeypatch):
    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(registry.original)
    before = json.dumps(tools.web_doc, sort_keys=True)
    monkeypatch.setattr(
        tools.core, "web_apply_ops", lambda *_: {"ok": False, "diagnostics": ["refused"]},
    )
    result = json.loads(tools.repair_cloned_section(
        registry.original, note="Fix links", href_replacements_json='{"/demo":"/x"}',
    ))
    assert result["error_code"] == "repair.swap_rejected"
    assert result["released"] is True and result["pinned"] is False
    assert result["fragment_id"] in registry.payloads
    assert json.dumps(tools.web_doc, sort_keys=True) == before


def test_exact_label_tool_changes_rendered_cta_without_losing_personalized_copy(tmp_path):
    from langchain_core.tools import StructuredTool
    from selectolax.lexbor import LexborHTMLParser

    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(
        registry.original, slot_values_json=json.dumps({"headline": "A relevant account argument"})
    ))
    before = json.loads(json.dumps(tools.web_doc))
    exposed = StructuredTool.from_function(tools.repair_cloned_section)
    assert "cta_label_replacements_json" in exposed.args_schema.model_json_schema()["properties"]
    result = json.loads(exposed.invoke({
        "fragment_id": registry.original, "note": "Match the page's primary action",
        "cta_label_replacements_json": '{"Book a demo":"Explore the workflow"}',
    }))
    assert result["status"] == "ok", result
    assert result["label_match_counts"] == {"Book a demo": 1}
    expected = before
    expected["pages"][0]["nodes"][pin["node_id"]]["fragment_id"] = result["repair_fragment_id"]
    assert tools.web_doc == expected
    for mode in ("editor", "delivery"):
        html = tools.core.web_render(
            tools.web_doc, "home", mode=mode,
            fragments=tools._fragment_render_map(), fragment_css=tools._fragment_css(),
        )["html"]
        tree = LexborHTMLParser(html)
        assert tree.css_first(".clone-hero h1").text() == "A relevant account argument"
        assert tree.css_first(".clone-hero a").text() == "Explore the workflow"
        assert tree.css_first(".clone-hero a").attributes["href"] == "https://insight.example/demo"


def test_label_tool_cannot_silently_mask_existing_human_text_overrides(tmp_path):
    registry = HrefRegistry(tmp_path)
    tools = _tools(tmp_path, registry)
    pin = json.loads(tools.insert_cloned_section(registry.original))
    tools.web_ops(json.dumps([{
        "kind": "set_fragment_text_override", "page_id": "home", "id": pin["node_id"],
        "path": ":nth-child(1) > :nth-child(2)", "override": {"text": "Human CTA"},
    }]))
    before = json.dumps(tools.web_doc, sort_keys=True)
    result = json.loads(tools.repair_cloned_section(
        registry.original, note="Match action",
        cta_label_replacements_json='{"Book a demo":"Explore"}',
    ))
    assert result["error_code"] == "repair.label_override_conflict"
    assert not registry.mint_calls
    assert json.dumps(tools.web_doc, sort_keys=True) == before
