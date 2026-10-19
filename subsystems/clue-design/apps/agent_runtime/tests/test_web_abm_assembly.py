"""The ABM assembly walk (clone-fidelity F4.2, rulings R24-1…R24-7).

F4.1 minted the shells; nothing yet told an ABM page to wear them. ``assemble_abm_page`` is that
step: it pins the released campaign header FIRST, the released campaign footer LAST, and a
personalized hero clone between them — bound to the account TEMPLATE MARKERS the F1.4 derive
substitutes, so one document serves every account.

What this file guards, seam by seam:

* **The cloned nav is usually not the answer** (ruling R24-1, DEMOTED TO ADVICE by founder
  ruling R-F5-8). A workspace with no released shells is still refused by name and told to mint
  them — that is a missing input, not a taste. But a caller who names a ``nav``- or
  ``footer``-role clone now gets it PINNED with a note in ``advice``, and a page that already
  carries one is assembled around it and told. Links are structurally free; the agent is only
  told what the practice is.
* **Newest released shell per role, deterministically, and SAID** (the I6 interim law). Shells
  carry no supersession, so a kit change leaves two approved headers; the walk picks one the
  same way every time and names the sibling it stepped over.
* **The page is a TEMPLATE.** The slot values the walk writes are markers, not values, so an
  author can look at one document and Task 25 can derive it per account.
* **New sections are named ``abm_``** (ruling R24-3). The walk does not compose them — the
  ordinary authoring vocabulary does — but it reports the convention and names any top-level
  section that broke it, so the review can tell a new ABM band from cloned chrome mechanically.
* **R24-7's carry-in:** a shell VIEWED AFTER BEING PINNED must not claim a browser measured it.

The registry is a fake that answers what the real capability answers; the ENGINE is real. The
durable half — the contract module, the derive over the assembled shape — is
``apps/api/tests/test_abm_assembly.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import (
    _ABM_SECTION_NAMING_CODE,
    LumenWebTools,
)
from lumen_api.fragments.abm_page import (
    ABM_SECTION_ID_PREFIX,
    ACCOUNT_LOGO_MARKER,
    ACCOUNT_NAME_MARKER,
)
from lumen_api.fragments.campaign_shell import (
    CAMPAIGN_SHELL_FOOTER,
    CAMPAIGN_SHELL_HEADER,
    COMPOSED_CAMPAIGN_SHELL,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PAGE = "https://insight.example/"
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)

HEADER_ID = "frag_00000000000000a1"
FOOTER_ID = "frag_00000000000000b1"
HERO_ID = "frag_00000000000000c1"
NAV_ID = "frag_00000000000000d1"
SITE_FOOTER_ID = "frag_00000000000000e1"


class FakeRegistry:
    """What the real cloned-section capability answers, without a database."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.rows: dict[str, dict] = {}

    def add(
        self,
        fragment_id: str,
        *,
        role: str,
        label: str,
        index: int | None = None,
        composed: str | None = None,
        created_at: str = "2026-08-20T00:00:00Z",
        slots: dict | None = None,
        html: str | None = None,
    ) -> None:
        path = self.tmp_path / f"{fragment_id}.png"
        path.write_bytes(PNG_1PX)
        self.rows[fragment_id] = {
            "fragment_id": fragment_id,
            "section_role": role,
            "label": label,
            "status": "approved",
            "source_url": "composed:campaign-shell" if composed else PAGE,
            "source_kit_id": "brand_kit_1",
            "source_kit_version": 3,
            "preview_digest": "d" * 64,
            "preview_path": str(path),
            "slot_keys": sorted(slots or {}),
            "page_url": None if composed else PAGE,
            "section_index": index,
            "created_at": created_at,
            "degraded": False,
            "degraded_reason": None,
            "degraded_note": None,
            "derived_from": None,
            "derived_reason": None,
            "composed": composed,
            "lineage_root": fragment_id,
            "superseded_by": None,
            "lineage_ambiguous": [],
            "lineage_ranked_over": [],
            "repairs": [],
            "slot_kinds": dict(slots or {}),
            "html": html
            or f'<section class="clone-{role}"><p>{label}</p></section>',
            "css": "",
        }

    # --- what the walk reads ------------------------------------------------------------------

    def list_sections(self, section_role=None):
        sections = [
            {
                key: value
                for key, value in row.items()
                if key not in ("html", "css", "preview_path", "slot_kinds")
            }
            for row in self.rows.values()
            if section_role is None or row["section_role"] == section_role
        ]
        return {
            "schema_version": 1,
            "workspace_id": "ws_test",
            "sections": sections,
            "total": len(sections),
        }

    def describe(self, fragment_ids):
        return {
            fragment_id: {
                "slots": [
                    {"key": key, "kind": kind}
                    for key, kind in sorted(self.rows[fragment_id]["slot_kinds"].items())
                ],
                "preview_path": self.rows[fragment_id]["preview_path"],
            }
            for fragment_id in fragment_ids
            if fragment_id in self.rows
        }

    def resolve_insertable(self, fragment_id):
        row = self.rows[fragment_id]
        return {
            "fragment_id": fragment_id,
            "section_role": row["section_role"],
            "label": row["label"],
            "source_url": row["source_url"],
            "slots": [],
            "preview_path": row["preview_path"],
            "degraded": False,
            "degraded_reason": None,
            "degraded_note": None,
            "derived_from": None,
            "superseded_by": None,
            "lineage_ambiguous": [],
            # R24-7: the provenance is read here anyway, so the pin doors can stop erasing it.
            "composed": row["composed"],
            "render": {
                "html": row["html"],
                "css": row["css"],
                "slot_kinds": dict(row["slot_kinds"]),
                "asset_digests": [],
                "derived": False,
            },
        }


HERO_HTML = (
    '<section class="clone-hero">'
    '<h1 data-lumen-slot="headline">Clinical notes, written for you</h1>'
    '<p data-lumen-slot="subhead">One record, every clinician.</p>'
    '<img data-lumen-slot="badge" src="/asset-store/'
    + "b" * 64
    + '" alt="">'
    "</section>"
)


def _seeded(tmp_path: Path, **which) -> FakeRegistry:
    """A workspace with released shells, a hero, and the client's real nav and footer."""
    registry = FakeRegistry(tmp_path)
    if which.get("shells", True):
        registry.add(
            HEADER_ID,
            role=CAMPAIGN_SHELL_HEADER,
            label="Campaign header — Insight Health",
            composed=COMPOSED_CAMPAIGN_SHELL,
            slots={
                "prepared_for": "text",
                "target_logo": "image",
                "cta_href": "href",
                "cta_label": "text",
            },
        )
        registry.add(
            FOOTER_ID,
            role=CAMPAIGN_SHELL_FOOTER,
            label="Campaign footer — Insight Health",
            composed=COMPOSED_CAMPAIGN_SHELL,
        )
    if which.get("hero", True):
        registry.add(
            HERO_ID,
            role="hero",
            label="Hero — clinical notes",
            index=1,
            slots={"headline": "text", "subhead": "text", "badge": "image"},
            html=HERO_HTML,
        )
    if which.get("chrome_clones", True):
        registry.add(NAV_ID, role="nav", label="Global navigation", index=0)
        registry.add(SITE_FOOTER_ID, role="footer", label="Site footer", index=9)
    return registry


def _empty_doc() -> dict:
    return {
        "schema_version": 1,
        "id": "doc_abm",
        "title": "Insight Health",
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
                        "children": [],
                    }
                },
            }
        ],
        "assets": {},
    }


#: The turn's seller. The seeded shells are minted against it, so the walk's brand scoping picks
#: them; a test that wants the multi-brand case moves one side or the other.
BRAND_KIT = {"id": "brand_kit_1", "version": 3, "name": "Insight Health"}


def _tools(tmp_path: Path, registry, *, brand_kit=None) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
        brand_kit=dict(BRAND_KIT) if brand_kit is None else brand_kit,
    )
    return LumenWebTools(config, "Build the ABM page", initial_web_doc=_empty_doc())


def _children(tools: LumenWebTools) -> list[str]:
    page = tools._home_page()
    return list(page["nodes"][page["root"]]["children"])


def _fragment_nodes(tools: LumenWebTools) -> dict[str, dict]:
    """``{fragment_id: node}`` for every fragment pinned on the page."""
    nodes = tools._home_page()["nodes"]
    return {
        node["fragment_id"]: node
        for node in nodes.values()
        if node.get("kind") == "fragment"
    }


def _hero_slots(**overrides) -> str:
    slots = {
        "headline": f"Clinical notes, written for {ACCOUNT_NAME_MARKER}",
        "badge": ACCOUNT_LOGO_MARKER,
    }
    slots.update(overrides)
    return json.dumps(slots)


# =============================================================================================
# Red case 1 — the assembly: header first, footer last, hero slot-bound with account markers
# =============================================================================================


def test_the_walk_assembles_chrome_around_a_marker_bound_hero(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )

    assert result["status"] == "ok", result
    pinned = [entry["fragment_id"] for entry in result["pinned"]]
    assert pinned == [HEADER_ID, HERO_ID, FOOTER_ID]

    # ...and on the PAGE, in that order, header first and footer last.
    nodes = tools._home_page()["nodes"]
    order = [
        nodes[nodes[section_id]["children"][0]]["fragment_id"] for section_id in _children(tools)
    ]
    assert order == [HEADER_ID, HERO_ID, FOOTER_ID]

    # The shell's ruled per-account slots carry MARKERS, not values (R24-2).
    frags = _fragment_nodes(tools)
    assert frags[HEADER_ID]["slots"]["prepared_for"] == {"text": ACCOUNT_NAME_MARKER}
    assert frags[HEADER_ID]["slots"]["target_logo"] == {"text": ACCOUNT_LOGO_MARKER}
    # The hero's, as the author asked for them — and the IMAGE slot's marker rides as text so
    # the derive can resolve it into an asset.
    assert frags[HERO_ID]["slots"]["headline"] == {
        "text": f"Clinical notes, written for {ACCOUNT_NAME_MARKER}"
    }
    assert frags[HERO_ID]["slots"]["badge"] == {"text": ACCOUNT_LOGO_MARKER}
    # The footer has nothing per-account, and binds nothing. (The engine omits an empty slot map
    # from the node it serializes, so an absent key and an empty one are the same answer.)
    assert frags[FOOTER_ID].get("slots") in ({}, None)


def test_the_assembled_page_still_renders_and_keeps_its_markers(tmp_path: Path) -> None:
    """Re-derivable, not baked: the engine renders the template, the slot markers are still in
    the document, and the artifact's own `data-lumen-slot` attributes survive into the html."""
    tools = _tools(tmp_path, _seeded(tmp_path))
    tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())

    rendered = tools.core.web_render(
        tools.web_doc,
        tools.page_id,
        fragments=tools._fragment_render_map(),
        fragment_css=tools._fragment_css(),
    )
    html = rendered.get("html") or ""

    for key in ("headline", "subhead", "badge"):
        assert f'data-lumen-slot="{key}"' in html
    # The markers themselves are on the DOCUMENT (they are slot values, not markup), so a
    # second derive against a different account is still possible.
    document = json.dumps(tools.web_doc)
    assert ACCOUNT_NAME_MARKER in document
    assert ACCOUNT_LOGO_MARKER in document


def test_the_walk_reports_where_the_target_logo_comes_from_and_that_empty_is_correct(
    tmp_path: Path,
) -> None:
    result = json.loads(
        _tools(tmp_path, _seeded(tmp_path)).assemble_abm_page(hero_fragment_id=HERO_ID)
    )

    note = result["target_logo"]
    assert "fetch_logo" in note
    assert ACCOUNT_LOGO_MARKER in note
    lowered = note.lower()
    assert "empty" in lowered and "correct" in lowered


# =============================================================================================
# Red cases 2 & 4 — no shells means a refusal, never the cloned nav
# =============================================================================================


def test_a_workspace_whose_only_chrome_is_the_cloned_nav_is_refused_not_served(
    tmp_path: Path,
) -> None:
    """The assembly-side escape-route red case. The nav is RIGHT THERE and released, and the
    walk still refuses rather than pinning it — there is no fallback to build."""
    tools = _tools(tmp_path, _seeded(tmp_path, shells=False))

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["status"] == "error"
    assert result["error_code"] == "abm.no_campaign_shells"
    # Nothing was pinned — not the nav, not the hero, nothing.
    assert _children(tools) == []
    assert NAV_ID not in result["message"]


def test_no_released_shells_names_the_remedy_rather_than_improvising(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path, shells=False, chrome_clones=False))

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["error_code"] == "abm.no_campaign_shells"
    message = result["message"]
    assert "mint_campaign_shells" in message
    # The other half of the remedy: minted shells are born draft and a human releases them.
    assert "approv" in message.lower()
    assert _children(tools) == []


def test_a_workspace_with_only_one_of_the_two_shells_is_refused_and_says_which(
    tmp_path: Path,
) -> None:
    registry = _seeded(tmp_path)
    del registry.rows[FOOTER_ID]
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["error_code"] == "abm.no_campaign_shells"
    assert CAMPAIGN_SHELL_FOOTER in result["message"]
    assert _children(tools) == []


# =============================================================================================
# Red case 3 — a nav or site footer on an ABM page is ADVISED AGAINST, never refused (R-F5-8)
# =============================================================================================


@pytest.mark.parametrize("fragment_id", [NAV_ID, SITE_FOOTER_ID])
def test_naming_a_nav_or_site_footer_as_the_hero_pins_it_and_advises(
    tmp_path: Path, fragment_id: str
) -> None:
    """R-F5-8: allowed, not recommended. The walk does what it was asked, and says what it
    thinks of it."""
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=fragment_id))

    assert result["status"] == "ok"
    assert fragment_id in [entry["fragment_id"] for entry in result["pinned"]]
    notes = [item for item in result["advice"] if isinstance(item, str) and fragment_id in item]
    assert notes, result["advice"]
    assert "poor practice" in notes[0]
    assert "R-F5-8" in notes[0]
    # The header and the footer shells still went on, and the hero really is on the page.
    assert len(_children(tools)) == 3


def test_a_nav_already_pinned_on_the_page_is_assembled_around_and_noted(
    tmp_path: Path,
) -> None:
    """The DETECTION is about the PAGE, not only about this call's arguments — a nav pinned by an
    earlier `insert_cloned_section` is spotted the same way. Under R-F5-8 the walk builds the
    chrome around it and hands the author the note instead of refusing."""
    registry = _seeded(tmp_path)
    tools = _tools(tmp_path, registry)
    assert json.loads(tools.insert_cloned_section(NAV_ID))["status"] == "ok"
    before = _children(tools)

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["status"] == "ok"
    notes = [item for item in result["advice"] if isinstance(item, str) and NAV_ID in item]
    assert notes, result["advice"]
    assert "cloned nav" in notes[0]
    assert "poor practice" in notes[0]
    # Nothing removed: the walk does not silently unpin somebody's section — it adds around it.
    assert set(before).issubset(set(_children(tools)))


# =============================================================================================
# Red case 5 — the abm_ convention for NEW sections
# =============================================================================================


def test_the_walk_names_the_new_section_convention_and_the_sections_that_broke_it(
    tmp_path: Path,
) -> None:
    """The walk composes no new section — the ordinary authoring vocabulary does. What it owes
    is the mechanical read: which top-level sections are cloned pins, which are new, and which
    new ones are not named so a reviewer can tell them apart."""
    tools = _tools(tmp_path, _seeded(tmp_path))
    authored = tools.author_web_page(
        '<section id="abm_peer_proof"><p>Peers you would recognize.</p></section>'
        '<section id="how_we_would_work"><p>Three steps.</p></section>'
    )
    assert json.loads(authored)["status"] == "ok", authored

    result = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )

    assert result["status"] == "ok", result
    assert result["new_section_convention"]["prefix"] == ABM_SECTION_ID_PREFIX
    assert result["new_sections"] == ["abm_peer_proof", "how_we_would_work"]
    assert result["off_convention"] == ["how_we_would_work"]
    # It is WORK, in the bucket the prompt calls mandatory — not a note nobody reads.
    codes = [warning.get("code") for warning in result["warnings"]]
    assert _ABM_SECTION_NAMING_CODE in codes

    # And the cloned pins keep their own ids: nothing renamed the chrome.
    nodes = tools._home_page()["nodes"]
    pinned_wrappers = [
        section_id
        for section_id in _children(tools)
        if nodes[nodes[section_id]["children"][0]].get("kind") == "fragment"
    ]
    assert all(re.fullmatch(r"sec_[0-9a-f]{8}", section_id) for section_id in pinned_wrappers)
    assert not any(section_id.startswith(ABM_SECTION_ID_PREFIX) for section_id in pinned_wrappers)


def test_a_page_of_correctly_named_sections_draws_no_warning(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))
    tools.author_web_page('<section id="abm_peer_proof"><p>Peers.</p></section>')

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["off_convention"] == []
    assert _ABM_SECTION_NAMING_CODE not in [w.get("code") for w in result["warnings"]]


# =============================================================================================
# The shell picker — newest released per role, deterministically, and SAID (I6 interim law)
# =============================================================================================


def test_the_walk_wears_this_brands_chrome_and_never_another_brands(tmp_path: Path) -> None:
    """A multi-brand workspace holds more than one seller's shells. The turn's kit decides —
    the same scoping T23's fix round gave the legal-link evidence read."""
    registry = _seeded(tmp_path)
    for row in registry.rows.values():
        row["source_kit_id"] = "brand_kit_other"
    tools = _tools(tmp_path, registry, brand_kit={"id": "brand_kit_1", "name": "Insight"})

    result = json.loads(tools.assemble_abm_page())

    assert result["error_code"] == "abm.no_campaign_shells"
    assert "brand_kit_1" in result["message"]
    assert _children(tools) == []


def test_a_turn_with_no_brand_kit_picks_workspace_wide_and_says_so(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path), brand_kit={})

    result = json.loads(tools.assemble_abm_page())

    assert result["status"] == "ok", result
    assert [entry["fragment_id"] for entry in result["pinned"]] == [HEADER_ID, FOOTER_ID]
    assert "multi-brand" in result["chrome_scope_note"]


def test_a_turn_with_a_brand_kit_does_not_carry_the_scope_note(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(tools.assemble_abm_page())

    assert "chrome_scope_note" not in result


def test_a_second_released_header_picks_the_newest_and_names_the_sibling(
    tmp_path: Path,
) -> None:
    registry = _seeded(tmp_path)
    registry.rows[HEADER_ID]["created_at"] = "2026-08-01T00:00:00Z"
    registry.add(
        "frag_00000000000000a2",
        role=CAMPAIGN_SHELL_HEADER,
        label="Campaign header — Insight Health",
        composed=COMPOSED_CAMPAIGN_SHELL,
        created_at="2026-08-25T00:00:00Z",
        slots={"prepared_for": "text", "target_logo": "image"},
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["pinned"][0]["fragment_id"] == "frag_00000000000000a2"
    assert result["chrome_siblings"][CAMPAIGN_SHELL_HEADER] == [HEADER_ID]
    note = result["chrome_siblings_note"]
    assert HEADER_ID in note
    # The honest half: we do not KNOW the old one is superseded, and the note says so.
    assert "newest" in note.lower()


# =============================================================================================
# Red case 9 — re-running the walk converges rather than duplicating the chrome
# =============================================================================================


def test_running_the_walk_twice_does_not_duplicate_the_chrome(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))
    first = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )
    after_first = _children(tools)

    second = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )

    assert second["status"] == "ok", second
    assert _children(tools) == after_first
    assert [entry["fragment_id"] for entry in second["pinned"]] == []
    assert sorted(entry["fragment_id"] for entry in second["converged"]) == sorted(
        entry["fragment_id"] for entry in first["pinned"]
    )
    # One document write for the first walk, none for the second.
    assert second["converged_note"]


def test_a_second_walk_still_pins_the_half_the_first_one_did_not_have(
    tmp_path: Path,
) -> None:
    """Convergence is per band, not all-or-nothing: an author who assembled chrome and then
    chose a hero gets the hero pinned without a second header."""
    tools = _tools(tmp_path, _seeded(tmp_path))
    tools.assemble_abm_page()

    result = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )

    assert [entry["fragment_id"] for entry in result["pinned"]] == [HERO_ID]
    assert sorted(entry["fragment_id"] for entry in result["converged"]) == sorted(
        [HEADER_ID, FOOTER_ID]
    )
    nodes = tools._home_page()["nodes"]
    order = [
        nodes[nodes[section_id]["children"][0]]["fragment_id"] for section_id in _children(tools)
    ]
    assert order == [HEADER_ID, HERO_ID, FOOTER_ID]


def test_a_walk_with_no_hero_says_so_rather_than_choosing_one(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(tools.assemble_abm_page())

    assert result["status"] == "ok"
    assert result["hero"] is None
    assert HERO_ID in result["hero_candidates"]
    assert "hero" in result["hero_note"].lower()


# =============================================================================================
# Slot refusals reach the agent by name
# =============================================================================================


def test_an_unknown_hero_slot_is_refused_with_the_slots_that_do_exist(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(
        tools.assemble_abm_page(
            hero_fragment_id=HERO_ID, hero_slots_json=json.dumps({"tagline": "x"})
        )
    )

    assert result["error_code"] == "cloned_section.unknown_slot"
    assert "headline" in result["message"]
    assert _children(tools) == []


def test_a_marker_the_derive_cannot_substitute_is_refused_before_anything_is_pinned(
    tmp_path: Path,
) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(
        tools.assemble_abm_page(
            hero_fragment_id=HERO_ID,
            hero_slots_json=json.dumps({"headline": "Welcome, {{brand.name}}"}),
        )
    )

    assert result["error_code"] == "abm.unknown_marker"
    assert _children(tools) == []


def test_an_unreadable_hero_is_a_retryable_failure_not_a_slots_none_lie(
    tmp_path: Path,
) -> None:
    """An empty kinds map would refuse every named slot with "its slots are: none" — a confident
    lie about a hero that has four, and one that sends the agent off to compose a band it has."""
    registry = _seeded(tmp_path)

    def boom(_ids):
        raise RuntimeError("connection reset")

    registry.describe = boom
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json=_hero_slots())
    )

    assert result["error_code"] == "cloned_section.registry_failed"
    assert "not a refusal" in result["message"]
    assert _children(tools) == []


def test_a_bad_slot_payload_is_refused_by_name(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(
        tools.assemble_abm_page(hero_fragment_id=HERO_ID, hero_slots_json="[1, 2]")
    )

    assert result["error_code"] == "cloned_section.bad_slot_values"


def test_a_hero_id_this_workspace_does_not_hold_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    result = json.loads(tools.assemble_abm_page(hero_fragment_id="frag_nope"))

    assert result["error_code"] == "abm.hero_unknown"
    assert _children(tools) == []


def test_the_campaign_cta_binds_on_the_header_when_the_caller_names_it(
    tmp_path: Path,
) -> None:
    tools = _tools(tmp_path, _seeded(tmp_path))

    tools.assemble_abm_page(
        cta_href="https://insight.example/book", cta_label="Book a walkthrough"
    )

    header = _fragment_nodes(tools)[HEADER_ID]["slots"]
    assert header["cta_href"] == {"text": "https://insight.example/book"}
    assert header["cta_label"] == {"text": "Book a walkthrough"}


def test_the_walk_refuses_when_the_turn_carries_no_cloned_section_library(
    tmp_path: Path,
) -> None:
    tools = _tools(tmp_path, None)

    result = json.loads(tools.assemble_abm_page())

    assert result["error_code"] == "cloned_section.registry_unavailable"


# =============================================================================================
# R24-7 — the composed marker survives the pin, so the view sentence stays true
# =============================================================================================


def test_viewing_a_shell_after_pinning_it_does_not_claim_a_browser_measured_it(
    tmp_path: Path,
) -> None:
    """T23 re-review finding N6, live-reproduced there. The three pin doors rebuilt the seen-row
    from `resolve_insertable`, which did not carry `composed`, so a shell VIEWED AFTER PINNING
    answered the harvested-clone sentence. It is the moment an author is most likely to look."""
    registry = _seeded(tmp_path)
    # A shell with no preview is the shape the sentence is about.
    registry.rows[HEADER_ID]["preview_path"] = str(tmp_path / "absent.png")
    tools = _tools(tmp_path, registry)
    tools.assemble_abm_page()

    blocks = tools._view_cloned_section(f"cloned_section:{HEADER_ID}")
    text = " ".join(block.get("text", "") for block in blocks)

    assert "composed from the brand kit" in text
    assert "what the browser measured" not in text


def test_the_same_is_true_after_a_plain_insert(tmp_path: Path) -> None:
    registry = _seeded(tmp_path)
    registry.rows[HEADER_ID]["preview_path"] = str(tmp_path / "absent.png")
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HEADER_ID)

    text = " ".join(
        block.get("text", "")
        for block in tools._view_cloned_section(f"cloned_section:{HEADER_ID}")
    )

    assert "composed from the brand kit" in text
    assert "what the browser measured" not in text


def test_a_harvested_clone_still_gets_the_harvested_sentence(tmp_path: Path) -> None:
    """The other half of the discrimination: the fix must not make every band read as composed."""
    registry = _seeded(tmp_path)
    registry.rows[HERO_ID]["preview_path"] = str(tmp_path / "absent.png")
    tools = _tools(tmp_path, registry)
    tools.insert_cloned_section(HERO_ID)

    text = " ".join(
        block.get("text", "")
        for block in tools._view_cloned_section(f"cloned_section:{HERO_ID}")
    )

    assert "what the browser measured" in text
    assert "composed from the brand kit" not in text


# =============================================================================================
# Red case 8 — the prompt law (R24-5 / R24-6), and D-F6's wording untouched
# =============================================================================================


def _director_prompt() -> str:
    from lumen_agent.prompts_web import build_web_orchestrator_prompt

    return build_web_orchestrator_prompt(
        doc_title="Insight Health",
        has_existing_content=False,
        brand_card="{}",
        review_cap=2,
        author_cap=2,
    )


def _author_prompt() -> str:
    from lumen_agent.prompts_web import build_web_author_prompt

    return build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")


def _squashed(text: str) -> str:
    """Whitespace-robust reading: the prompts are wrapped prose, so a rule must be asserted on
    its words rather than on the column a founder's editor happened to wrap it at (T17 lesson)."""
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_the_reuse_ladder_carries_the_abm_rung(prompt_of) -> None:
    """The focused template path uses shells, without making all account pages identical."""
    prompt = _squashed(prompt_of())

    assert "assemble_abm_page" in prompt
    assert "mint_campaign_shells" in prompt
    assert "existing navigation" in prompt.lower() or "existing pinned navigation" in prompt.lower()
    assert "advice" in prompt.lower()
    # The rung ORDER survives: shells for chrome, clones for proof, new sections last.
    lowered = prompt.lower()
    shells = lowered.index("campaign shell")
    proof = lowered.index("proof", shells)
    assert shells < proof


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_the_relationship_language_guardrail_is_prompt_law(prompt_of) -> None:
    """R24-5: prepared-for framing only; no claim of a relationship that does not exist."""
    prompt = _squashed(prompt_of())
    lowered = prompt.lower()

    assert "prepared for" in lowered
    for forbidden in ("partner", "customer", "trusted by"):
        assert forbidden in lowered, forbidden
    assert "logo wall" in lowered or "testimonial" in lowered


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_the_new_section_convention_is_prompt_law_too(prompt_of) -> None:
    prompt = _squashed(prompt_of())

    assert ABM_SECTION_ID_PREFIX in prompt


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_the_clone_repair_ladder_wording_is_untouched(prompt_of) -> None:
    """D-F6's own words, which this task amends around and never through."""
    prompt = _squashed(prompt_of())

    assert "A CLONE IS THE STARTING REFERENCE, NOT AN UNTOUCHABLE ARTIFACT" in prompt
    assert "Never preserve a broken result merely because it came from the original site" in prompt
    assert "reproduce the original experience with supported primitives" in prompt
    assert "an equivalent interaction serving the same storytelling purpose" in prompt
    assert "deliberate, compact static fallback" in prompt
    assert "NEVER CASUALLY REWRITE A WORKING CLONED SECTION" in prompt


# =============================================================================================
# Red case 7 — the rubric's ABM clause, one artifact, both readers, both flag states
# =============================================================================================


def _rubric_readers() -> tuple[str, str, str]:
    from lumen_agent.prompts_web import (
        build_web_orchestrator_prompt,
        build_web_reviewer_prompt,
    )
    from lumen_agent.rubrics import load_clone_review_rubric

    self_review = build_web_orchestrator_prompt(
        doc_title="Insight Health",
        has_existing_content=False,
        brand_card="{}",
        review_cap=2,
        author_cap=2,
        web_reviewer=False,
    )
    return load_clone_review_rubric(), build_web_reviewer_prompt(), self_review


def test_the_rubric_carries_the_seller_dominance_clause_and_bumped_its_version() -> None:
    from lumen_agent.rubrics import clone_review_rubric_version

    rubric, _reviewer, _self_review = _rubric_readers()

    assert clone_review_rubric_version() >= 2
    squashed = _squashed(rubric)
    # The acceptance question, VERBATIM (ruling R24-4).
    assert (
        "would it still look like the seller's site without the target logo?" in squashed.lower()
    )
    lowered = squashed.lower()
    assert "seller" in lowered and "dominate" in lowered
    assert "one restrained accent" in lowered
    assert "exact target logo" in lowered
    # And the never-synthesize half: an empty logo slot is not a defect.
    assert "empty" in lowered


def test_both_readers_and_both_flag_states_get_the_amended_bytes(tmp_path, monkeypatch) -> None:
    rubric, reviewer_prompt, self_review_prompt = _rubric_readers()

    assert rubric in reviewer_prompt
    assert rubric in self_review_prompt
    assert reviewer_prompt.count(rubric) == 1
    assert self_review_prompt.count(rubric) == 1
    # Still ONE artifact: editing the file moves both, so neither holds a private copy of the
    # ABM clause either.
    edited = tmp_path / "rubric.md"
    edited.write_text(
        "<!--\nversion: 99\n-->\n--- rubric ---\nSTRICT: a clause nobody has seen.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("lumen_agent.rubrics.CLONE_REVIEW_RUBRIC_PATH", edited, raising=True)
    _again, reviewer_after, self_review_after = _rubric_readers()
    assert "a clause nobody has seen" in reviewer_after
    assert "a clause nobody has seen" in self_review_after
    for after in (reviewer_after, self_review_after):
        # Rubric-only phrases, one from v1 and one from the ABM clause. Deliberately NOT the
        # acceptance question: that sentence is ALSO prompt law (director step 1f), so its
        # presence would prove nothing about which artifact the reader received.
        assert "animation timing" not in after
        assert "NO ESCAPE ROUTES" not in after


def test_the_walk_is_registered_on_the_author_role(tmp_path: Path, monkeypatch) -> None:
    """The author is the only role that writes to the page (the F2.3/F3.1 rule), and this walk
    writes. The director decides and briefs; it does not pin."""
    import deepagents

    import lumen_agent.llm as llm
    from lumen_agent import harness_web

    capture: dict = {}
    monkeypatch.setattr(
        deepagents, "create_deep_agent", lambda **kwargs: capture.update(kwargs) or object()
    )
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(
        llm, "assert_all_role_models_support_image_input", lambda _config: None
    )

    harness_web.create_web_deepagent(
        "Build the ABM page",
        replace(
            AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
        ),
        _empty_doc(),
    )

    def names(entries):
        return {
            getattr(entry, "name", None) or getattr(entry, "__name__", "")
            for entry in entries
        }

    author = next(
        sub for sub in capture["subagents"] if sub["name"] == "lumen-web-author"
    )
    assert {"assemble_abm_page", "mint_campaign_shells"} <= names(author["tools"])
    assert "assemble_abm_page" not in names(capture["tools"])


# =============================================================================================
# Fix round (T24 review I1 / M1 / M4) — the hero door's holes, and the scan's honesty
# =============================================================================================


def test_naming_a_campaign_shell_as_the_hero_is_refused_not_double_pinned(
    tmp_path: Path,
) -> None:
    """T24 review I1, live-reproduced there: the header shell named as hero pinned TWO campaign
    headers ([header, header, footer]); the footer shell gave [footer, header, footer]. A shell
    is this walk's CHROME — naming one as the hero refuses typed, and the page is untouched."""
    registry = _seeded(tmp_path)
    tools = _tools(tmp_path, registry)
    before = _children(tools)

    for shell_id in (HEADER_ID, FOOTER_ID):
        result = json.loads(tools.assemble_abm_page(hero_fragment_id=shell_id))
        assert result["error_code"] == "abm.shell_is_chrome", shell_id
        assert shell_id in result["message"]
        assert _children(tools) == before


def test_another_brands_shell_cannot_ride_in_as_the_hero(tmp_path: Path) -> None:
    """The brand scoping the chrome pick applies was absent on the hero door (I1's third
    repro): a foreign-kit shell named explicitly as hero pinned another brand's chrome."""
    registry = _seeded(tmp_path)
    foreign = "frag_00000000000000f9"
    registry.add(
        foreign,
        role=CAMPAIGN_SHELL_HEADER,
        label="Campaign header — Other Brand",
        composed=COMPOSED_CAMPAIGN_SHELL,
    )
    registry.rows[foreign]["source_kit_id"] = "brand_kit_other"
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=foreign))

    assert result["error_code"] == "abm.shell_is_chrome"


def test_a_pinned_fragment_the_listing_cannot_resolve_assembles_and_advises(
    tmp_path: Path,
) -> None:
    """T24 review M1 found the detection: a pinned nav whose row is absent from the bounded
    approved listing (retired later, or beyond the listing cap) sailed past the escape-route
    scan. Under R-F5-8 the CONSEQUENCE is advice, not a refusal — the walk assembles the page
    and says plainly that it could not check what this fragment links to."""
    registry = _seeded(tmp_path)
    tools = _tools(tmp_path, registry)
    assert json.loads(tools.insert_cloned_section(NAV_ID))["status"] == "ok"
    del registry.rows[NAV_ID]
    before = _children(tools)

    result = json.loads(tools.assemble_abm_page(hero_fragment_id=HERO_ID))

    assert result["status"] == "ok"
    notes = [item for item in result["advice"] if isinstance(item, str) and NAV_ID in item]
    assert notes, result["advice"]
    assert "could not check what it links to" in notes[0]
    assert "R-F5-8" in notes[0]
    # The chrome still went on, and nothing the author had pinned was removed.
    assert set(before).issubset(set(_children(tools)))


def test_degraded_and_superseded_heroes_are_not_offered_silently(tmp_path: Path) -> None:
    """T24 review M4: everywhere else in this family a degraded band is announced loudly;
    the hero candidates offered one silently, and a superseded one whose repair is the real
    candidate was listed beside its repair."""
    registry = _seeded(tmp_path)
    broken = "frag_00000000000000c8"
    superseded = "frag_00000000000000c9"
    registry.add(broken, role="hero", label="Hero — broken carousel")
    registry.rows[broken]["degraded"] = True
    registry.add(superseded, role="hero", label="Hero — old")
    registry.rows[superseded]["superseded_by"] = HERO_ID
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.assemble_abm_page())

    assert superseded not in result["hero_candidates"]
    assert broken in result["hero_candidates"]
    assert "degraded" in result["hero_note"]
    assert broken in result["hero_note"]


def test_the_hero_note_with_no_candidates_does_not_dangle(tmp_path: Path) -> None:
    """A workspace with no released hero must not be told to pick "one of these"."""
    registry = _seeded(tmp_path, hero=False)
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.assemble_abm_page())

    assert result["status"] == "ok"
    assert result["hero_candidates"] == []
    assert "Released heroes" not in result["hero_note"]


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_the_marker_grammar_the_agent_reads_is_double_braced(prompt_of) -> None:
    """T25 review I-2, the silent law-breaker: the ABM blocks live inside f-strings, so
    `{{account.name}}` in the SOURCE rendered as `{account.name}` to the agent — a compliant
    author then writes a single-braced literal the derive never substitutes and the R25-7
    guard never sees. The assertion is on the RENDERED prompt, which is what the agent reads."""
    rendered = prompt_of()

    assert "{{account.name}}" in rendered
    assert "{{account.logo}}" in rendered
    # And no single-braced variant anywhere — the broken rendering, pinned extinct.
    assert re.search(r"(?<!\{)\{account\.(name|domain|logo)\}(?!\})", rendered) is None


def test_the_ladder_reaches_the_orchestrator_role() -> None:
    """F4 wave item 4 (the CP2 walk's F-4): the ladder lived only on the author role, so a
    director's "bind logos" delegation to a generic subagent bound NOTHING and reported
    success. Neither tool writes the document, so the author-owns-the-document law survives."""
    import inspect

    from lumen_agent import harness_web

    source = inspect.getsource(harness_web)
    start = source.index("orchestrator_tools = [")
    block = source[start : source.index("]", start)]
    assert "tools.fetch_logo" in block
    assert "tools.bind_account_logo" in block
