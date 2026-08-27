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


class _FakeGateRefusal(RuntimeError):
    """The shape ``FragmentReferenceError`` presents: a code, a message, and the id."""

    def __init__(self, code: str, message: str, fragment_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_id = "probe_cloned_section"
        self.fragment_id = fragment_id


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
    """The three rungs, in order, and the "look before you decide" rule beside them."""
    prompt = _director_prompt()

    assert "REUSE LADDER" in prompt
    assert "search_cloned_sections" in prompt
    ladder = prompt.split("REUSE LADDER", 1)[1]
    reuse = ladder.index("REUSE a cloned section")
    compose = ladder.index("COMPOSE A NEW SECTION")
    never = ladder.index("NEVER EDIT A CLONED SECTION")
    assert reuse < compose < never
    lowered = ladder.lower()
    assert "chrome" in lowered and "proof" in lowered


def test_the_reuse_decision_reaches_the_author_brief() -> None:
    """Same guarantee the imagery decision has: the choice is briefed, not kept in a head."""
    ladder = _director_prompt().split("REUSE LADDER", 1)[1]

    assert "author's brief" in ladder


def test_the_author_is_told_to_reuse_before_composing_and_never_to_rewrite() -> None:
    prompt = _author_prompt()

    assert "insert_cloned_section" in prompt
    assert "search_cloned_sections" in prompt
    assert "SLOTS are the only thing you may change" in prompt
    # The specific trap: a whole-page author call wipes an already-pinned clone.
    assert "replaces the whole page, cloned sections included" in prompt
    # And the refusal is an answer, not a thing to retry.
    assert "fragment.not_approved" in prompt


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
