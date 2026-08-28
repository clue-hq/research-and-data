"""Recreating the client's own page, and repairing the clones that came back broken (F3.1).

Two behaviours, one file, because they are two halves of one walk:

* **The recreate.** "Recreate our homepage" is an assembly, not a design brief — every released
  cloned section of that page, in the order it sat on the page, nothing added and nothing
  reordered. The pins land as ONE batch, so "all of them, in source order" is a property of the
  operation rather than of the model's obedience, and that is what these tests hold.
* **The repair ladder** (ruling D-F6). A clone is the starting reference, not an untouchable
  artifact. A broken band comes off the page, the composed replacement takes its exact place, and
  the ENGINE's own render of that replacement is minted as a NEW section carrying ``derived_from``
  lineage — while the original stays in the library, untouched, as the evidence of what the source
  site actually did.

The registry is a fake that answers exactly what the real capability answers; the ENGINE is real,
so every insert, swap and render is judged by the thing that judges them in production. The
durable half (the sanitizer, the lineage columns, content-address convergence) is pinned
DB-backed in ``apps/api/tests/test_fragment_repair.py``.
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

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

NAV_ID = "frag_00000000000000a1"
HERO_ID = "frag_00000000000000a2"
PROOF_ID = "frag_00000000000000a3"
FOOTER_ID = "frag_00000000000000a4"
DORMANT_ID = "frag_00000000000000a5"
REPAIR_ID = "frag_00000000000000b1"

PAGE = "https://insight.example/"
OTHER_PAGE = "https://insight.example/pricing"

#: The markup an author submits for a rung-3 repair: a compact static fallback in the platform's
#: own vocabulary. The engine rewrites it on ingest (it mints node ids, stamps `data-tv`, wraps
#: loose copy), which is exactly why the mint source has to be the RENDER and not this string.
REPLACEMENT_HTML = (
    '<section id="sec_repaired_proof" class="w-full py-section">'
    '<div class="mx-auto max-w-5xl px-6 text-center">'
    '<h2 class="text-3xl font-semibold text-primary">Trusted by 400 clinics</h2>'
    '<p class="mt-4 text-base text-muted">Three numbers that matter.</p>'
    "</div></section>"
)


class FakeRegistry:
    """The real capability's four answers, without a database.

    ``mint_repair`` records what it was handed rather than inventing an artifact: the whole
    question this file asks about the mint is *what reaches it*, and the durable half of that
    question has its own DB-backed file.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.rows: dict[str, dict] = {}
        self.mint_calls: list[dict] = []
        #: What `mint_repair` answers, per repaired id. Absent → a fresh draft repair.
        self.mint_result: dict | None = None

    def add(
        self,
        fragment_id: str,
        *,
        role: str,
        label: str,
        index: int,
        status: str = "approved",
        page_url: str = PAGE,
        degraded: bool = False,
        degraded_reason: str | None = None,
        derived_from: str | None = None,
        slots: list[dict] | None = None,
    ) -> None:
        path = self.tmp_path / f"{fragment_id}.png"
        path.write_bytes(PNG_1PX)
        self.rows[fragment_id] = {
            "fragment_id": fragment_id,
            "section_role": role,
            "label": label,
            "status": status,
            "source_url": page_url,
            "source_kit_id": "brand_kit_1",
            "source_kit_version": 3,
            "preview_digest": "d" * 64,
            "preview_path": str(path),
            "slot_keys": [slot["key"] for slot in (slots or [])],
            "slots": list(slots or []),
            "page_url": page_url,
            "section_index": index,
            "created_at": "2026-08-28T00:00:00Z",
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "degraded_note": (
                "the captured band is mostly artificial scroll height" if degraded else None
            ),
            "derived_from": derived_from,
            "derived_reason": "repair rung 3 (...)" if derived_from else None,
            "html": f'<section class="clone-{role}"><p>{label}</p></section>',
            "css": "",
        }

    # --- the capability -----------------------------------------------------------------------

    def list_sections(self, section_role=None):
        """Approved rows in document order, each carrying its repairs — the real shape."""
        repairs: dict[str, list[dict]] = {}
        for row in self.rows.values():
            if row.get("derived_from"):
                repairs.setdefault(row["derived_from"], []).append(row)
        sections = []
        for row in sorted(
            (
                row
                for row in self.rows.values()
                if row["status"] == "approved"
                and (section_role is None or row["section_role"] == section_role)
            ),
            key=lambda row: (row["page_url"], row["section_index"]),
        ):
            mine = repairs.get(row["fragment_id"]) or []
            releasable = [
                repair
                for repair in mine
                if repair["status"] == "approved" and not repair["degraded"]
            ]
            sections.append(
                {
                    key: row[key]
                    for key in (
                        "fragment_id",
                        "section_role",
                        "label",
                        "status",
                        "source_url",
                        "source_kit_id",
                        "source_kit_version",
                        "preview_digest",
                        "slot_keys",
                        "page_url",
                        "section_index",
                        "created_at",
                        "degraded",
                        "degraded_reason",
                        "degraded_note",
                        "derived_from",
                        "derived_reason",
                    )
                }
                | {
                    "repairs": [
                        {
                            "fragment_id": repair["fragment_id"],
                            "status": repair["status"],
                            "degraded": repair["degraded"],
                            "derived_reason": repair["derived_reason"],
                        }
                        for repair in mine
                    ],
                    "superseded_by": releasable[-1]["fragment_id"] if releasable else None,
                }
            )
        return {
            "schema_version": 1,
            "workspace_id": "ws_test",
            "sections": sections,
            "total": len(sections),
        }

    def describe(self, fragment_ids):
        return {
            fragment_id: {
                "slots": list(self.rows[fragment_id]["slots"]),
                "preview_path": self.rows[fragment_id]["preview_path"],
            }
            for fragment_id in fragment_ids
            if fragment_id in self.rows
        }

    def resolve_insertable(self, fragment_id):
        row = self.rows.get(fragment_id)
        if row is None:
            raise _refusal("fragment.unresolved", f"{fragment_id!r} is unknown", fragment_id)
        if row["status"] != "approved":
            raise _refusal(
                "fragment.not_approved",
                f"fragment {fragment_id!r} is {row['status']}",
                fragment_id,
            )
        return {
            "fragment_id": fragment_id,
            "section_role": row["section_role"],
            "label": row["label"],
            "source_url": row["source_url"],
            "slots": list(row["slots"]),
            "preview_path": row["preview_path"],
            "render": {
                "html": row["html"],
                "css": row["css"],
                "slot_kinds": {slot["key"]: slot["kind"] for slot in row["slots"]},
                "asset_digests": [],
            },
        }

    def mint_repair(self, *, replaces, html, css, rung, note, label=None):
        self.mint_calls.append(
            {
                "replaces": replaces,
                "html": html,
                "css": css,
                "rung": rung,
                "note": note,
            }
        )
        if self.mint_result is not None:
            return dict(self.mint_result)
        return {
            "fragment_id": REPAIR_ID,
            "replaces": replaces,
            "status": "draft",
            "section_role": self.rows[replaces]["section_role"],
            "label": f"Repaired — {self.rows[replaces]['label']}",
            "derived_from": replaces,
            "derived_reason": f"repair rung {rung} (...); trigger dead_height; {note}",
            "requested_derived_reason": f"repair rung {rung} (...); trigger dead_height; {note}",
            "slot_keys": ["headline"],
            "asset_digests": [],
            "sanitizer_notes": [],
            "converged": False,
            "lineage_kept": True,
            "insertable": False,
        }


def _refusal(code: str, message: str, fragment_id: str):
    from lumen_api.database import FragmentReferenceError

    return FragmentReferenceError(
        code, message, node_id="probe_cloned_section", fragment_id=fragment_id
    )


def _empty_doc() -> dict:
    return {
        "schema_version": 1,
        "id": "doc_recreate",
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


@pytest.fixture()
def registry(tmp_path: Path) -> FakeRegistry:
    fake = FakeRegistry(tmp_path)
    fake.add(NAV_ID, role="nav", label="Nav — Products Pricing", index=0)
    fake.add(
        HERO_ID,
        role="hero",
        label="Hero — The AI referral coordinator",
        index=1,
        slots=[{"key": "headline", "kind": "text"}],
    )
    fake.add(
        PROOF_ID,
        role="proof",
        label="Proof — Trusted by 400 clinics",
        index=2,
        degraded=True,
        degraded_reason="dead_height",
    )
    fake.add(FOOTER_ID, role="footer", label="Footer — About Careers", index=3)
    # Never listed, never pinned: the site hides it and D-F8 keeps it out of discovery.
    fake.add(DORMANT_ID, role="other", label="Other — hidden banner", index=4, status="dormant")
    return fake


def _tools(tmp_path: Path, registry: FakeRegistry | None, doc: dict | None = None):
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
    )
    return LumenWebTools(config, "Recreate our homepage", initial_web_doc=doc or _empty_doc())


def _sections(tools: LumenWebTools) -> list[str]:
    page = tools.web_doc["pages"][0]
    return list(page["nodes"]["root"]["children"])


def _pinned_in_order(tools: LumenWebTools) -> list[str]:
    """The fragment ids the page pins, top to bottom — what a visitor would scroll through."""
    page = tools.web_doc["pages"][0]
    nodes = page["nodes"]
    out = []
    for section_id in nodes["root"]["children"]:
        for child in nodes[section_id].get("children") or []:
            node = nodes[child]
            if node.get("kind") == "fragment":
                out.append(node["fragment_id"])
    return out


# --------------------------------------------------------------------------- #
# The recreate walk
# --------------------------------------------------------------------------- #


def test_the_recreate_pins_every_released_clone_in_source_order_and_adds_nothing(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The whole property, in one assertion: all of them, that order, nothing else."""
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["status"] == "ok"
    assert [entry["fragment_id"] for entry in result["pinned"]] == [
        NAV_ID,
        HERO_ID,
        PROOF_ID,
        FOOTER_ID,
    ]
    assert [entry["index"] for entry in result["pinned"]] == [0, 1, 2, 3]
    # The DOCUMENT, not just the report: four top-level sections, each holding exactly one
    # cloned section, in the order the source page had them.
    assert _pinned_in_order(tools) == [NAV_ID, HERO_ID, PROOF_ID, FOOTER_ID]
    page_nodes = tools.web_doc["pages"][0]["nodes"]
    assert len(page_nodes["root"]["children"]) == 4
    # Nothing composed, nothing invented: every node on the page is a wrapper or a pin.
    kinds = sorted({node["kind"] for node in page_nodes.values()})
    assert kinds == ["container", "fragment", "section"]


def test_the_recreate_never_pins_a_dormant_or_unreleased_section(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """D-F8: a section the source site hides never joins a recreated homepage."""
    tools = _tools(tmp_path, registry)

    json.loads(tools.recreate_cloned_page())

    assert DORMANT_ID not in _pinned_in_order(tools)
    assert len(_pinned_in_order(tools)) == 4


def test_a_degraded_clone_is_pinned_and_reported_as_work_not_as_a_note(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """D-F6's trigger reaches the author in the bucket the prompt calls mandatory."""
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert [entry["fragment_id"] for entry in result["needs_repair"]] == [PROOF_ID]
    assert result["needs_repair"][0]["reason"] == "dead_height"
    assert "artificial scroll height" in result["needs_repair"][0]["note"]
    warning = result["warnings"][0]
    assert warning["code"] == "LUMA0602"
    assert warning["severity"] == "warning"
    assert "repair_cloned_section" in warning["hint"]
    # And it IS on the page: D-F6 keeps the harvested original pinnable while it is the only
    # thing that exists. Leaving a hole would be the other failure.
    assert PROOF_ID in _pinned_in_order(tools)


def test_a_released_repair_is_pinned_instead_of_the_clone_it_replaces(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Once a human has released a repair, the broken original is not offered as if healthy."""
    registry.add(
        REPAIR_ID,
        role="proof",
        label="Repaired — Proof — Trusted by 400 clinics",
        index=2,
        derived_from=PROOF_ID,
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert _pinned_in_order(tools) == [NAV_ID, HERO_ID, REPAIR_ID, FOOTER_ID]
    assert result["needs_repair"] == []
    assert [entry["substituted_for"] for entry in result["substituted"]] == [PROOF_ID]
    # The repair inherited the original's page position, so nothing moved.
    assert result["substituted"][0]["index"] == 2


def test_the_recreate_fills_the_slots_it_is_given_and_leaves_the_rest_verbatim(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.recreate_cloned_page(
            slot_values_json=json.dumps({HERO_ID: {"headline": "Referrals, solved."}})
        )
    )

    hero = next(entry for entry in result["pinned"] if entry["fragment_id"] == HERO_ID)
    assert hero["slots_bound"] == ["headline"]
    nodes = tools.web_doc["pages"][0]["nodes"]
    bound = nodes[hero["node_id"]]["slots"]
    assert bound == {"headline": {"text": "Referrals, solved."}}
    nav = next(entry for entry in result["pinned"] if entry["fragment_id"] == NAV_ID)
    assert nav["slots_bound"] == []


def test_the_recreate_refuses_a_page_that_already_has_sections(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Adding to somebody's page is not recreating one, so it refuses rather than appending."""
    doc = _empty_doc()
    page = doc["pages"][0]
    page["nodes"]["sec_existing"] = {
        "id": "sec_existing",
        "kind": "section",
        "tag": "section",
        "classes": "",
        "children": [],
    }
    page["nodes"]["root"]["children"] = ["sec_existing"]
    tools = _tools(tmp_path, registry, doc)

    result = json.loads(tools.recreate_cloned_page())

    assert result["error_code"] == "recreate.page_not_empty"
    assert result["section_ids"] == ["sec_existing"]
    assert _sections(tools) == ["sec_existing"]


def test_the_recreate_refuses_to_guess_between_two_captured_pages(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    registry.add(
        "frag_00000000000000c1", role="hero", label="Pricing hero", index=0, page_url=OTHER_PAGE
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["error_code"] == "recreate.page_ambiguous"
    assert result["pages"] == [PAGE, OTHER_PAGE] or result["pages"] == [OTHER_PAGE, PAGE]
    assert _sections(tools) == []

    chosen = json.loads(tools.recreate_cloned_page(page_url=PAGE))
    assert [entry["fragment_id"] for entry in chosen["pinned"]] == [
        NAV_ID,
        HERO_ID,
        PROOF_ID,
        FOOTER_ID,
    ]


def test_the_recreate_says_so_when_the_workspace_has_released_nothing(
    tmp_path: Path
) -> None:
    tools = _tools(tmp_path, FakeRegistry(tmp_path))

    result = json.loads(tools.recreate_cloned_page())

    assert result["error_code"] == "recreate.nothing_released"
    assert _sections(tools) == []


def test_discovery_surfaces_that_a_clone_is_broken_and_what_repairs_it(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A picker that shows a degraded clone like a healthy one is how a broken band ships."""
    registry.add(
        REPAIR_ID,
        role="proof",
        label="Repaired — Proof",
        index=2,
        derived_from=PROOF_ID,
        status="draft",
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.search_cloned_sections(limit=20))

    proof = next(row for row in result["results"] if row["fragment_id"] == PROOF_ID)
    assert proof["degraded"] is True
    assert proof["degraded_reason"] == "dead_height"
    assert "artificial scroll height" in proof["degraded_note"]
    # A DRAFT repair is not a substitute — but the author must know it exists, or the next turn
    # composes the same replacement over again.
    assert proof["repairs"] == [
        {
            "fragment_id": REPAIR_ID,
            "status": "draft",
            "degraded": False,
            "derived_reason": "repair rung 3 (...)",
        }
    ]
    assert "superseded_by" not in proof
    healthy = next(row for row in result["results"] if row["fragment_id"] == NAV_ID)
    assert "degraded" not in healthy and "repairs" not in healthy


# --------------------------------------------------------------------------- #
# The repair ladder
# --------------------------------------------------------------------------- #


def _recreated(tmp_path: Path, registry: FakeRegistry) -> LumenWebTools:
    tools = _tools(tmp_path, registry)
    assert json.loads(tools.recreate_cloned_page())["status"] == "ok"
    return tools


def test_the_repair_swaps_the_broken_band_and_mints_the_engines_own_render(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling R17-1: what gets minted is what the ENGINE produced, never the model's markup."""
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(
            PROOF_ID,
            REPLACEMENT_HTML,
            3,
            "the band was 3200px of empty navy; this is the same proof copy at its natural height",
        )
    )

    assert result["status"] == "ok"
    assert result["repaired"] == PROOF_ID
    assert result["repair_fragment_id"] == REPAIR_ID
    assert result["rung"] == 3
    assert result["derived_from"] == PROOF_ID
    assert result["original_preserved"] is True
    # Born unreleased, and the tool says so instead of implying a pin.
    assert result["pinned"] is False
    assert "approving the brand kit" in result["release"]

    # The broken clone is OFF the page and the composed section stands in its exact place.
    assert _pinned_in_order(tools) == [NAV_ID, HERO_ID, FOOTER_ID]
    assert _sections(tools)[2] == result["section_node_id"]

    # The mint source is the RENDER: the engine stamps `data-tv` on a heading, which the
    # submitted markup never carried, and it is the engine's ids that come back.
    (call,) = registry.mint_calls
    assert call["replaces"] == PROOF_ID
    assert call["rung"] == 3
    assert 'data-tv="h2"' in call["html"]
    assert 'data-tv="h2"' not in REPLACEMENT_HTML
    assert call["html"].startswith("<section")
    assert "Trusted by 400 clinics" in call["html"]
    # And its styling was compiled, so the artifact is sealed rather than dependent on whatever
    # page it lands in.
    assert ".text-3xl" in call["css"]
    assert "--color-primary" in call["css"]


def test_the_repair_does_not_report_the_clone_it_replaced_as_an_accidental_loss(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The dropped-pin report is for rewrites that lose a band by accident. This is the opposite."""
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact static fallback")
    )

    codes = [warning.get("code") for warning in result.get("warnings") or []]
    assert "LUMA0601" not in codes
    assert "dropped_cloned_sections" not in result


def test_a_repair_that_converges_onto_an_existing_fragment_says_whose_lineage_it_kept(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Content addressing is first-writer-wins; a silent lineage overwrite would be the bug."""
    registry.mint_result = {
        "fragment_id": REPAIR_ID,
        "replaces": PROOF_ID,
        "status": "draft",
        "derived_from": PROOF_ID,
        "derived_reason": "repair rung 2 (...); trigger dead_height; somebody else's words",
        "requested_derived_reason": "repair rung 3 (...); trigger dead_height; mine",
        "slot_keys": [],
        "asset_digests": [],
        "sanitizer_notes": [],
        "converged": True,
        "lineage_kept": False,
        "insertable": False,
    }
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "mine")
    )

    assert result["converged"] is True
    assert result["lineage_kept"] is False
    assert "already existed" in result["note_on_lineage"]
    assert "rung 2" in result["note_on_lineage"]


def test_a_repair_that_converges_onto_a_released_fragment_is_pinned_as_the_artifact(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The one situation where the page can pin the repair without a human releasing it first."""
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2, derived_from=PROOF_ID
    )
    tools = _tools(tmp_path, registry)
    # Pin the broken original explicitly: with a released repair in the library the recreate
    # would have substituted it, and this test is about the OTHER door.
    assert json.loads(tools.insert_cloned_section(PROOF_ID))["status"] == "ok"
    registry.mint_result = {
        "fragment_id": REPAIR_ID,
        "replaces": PROOF_ID,
        "status": "approved",
        "derived_from": PROOF_ID,
        "derived_reason": "repair rung 3 (...); trigger dead_height; the same fallback",
        "slot_keys": [],
        "asset_digests": [],
        "sanitizer_notes": [],
        "converged": True,
        "lineage_kept": True,
        "insertable": True,
    }

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "the same fallback")
    )

    assert result["pinned"] is True
    assert _pinned_in_order(tools) == [REPAIR_ID]


def test_the_repair_refuses_a_clone_that_is_not_on_the_page(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "nothing to replace")
    )

    assert result["error_code"] == "repair.not_pinned"
    assert registry.mint_calls == []


@pytest.mark.parametrize("rung", [0, 4, "two", True, 2.5])
def test_the_repair_refuses_a_rung_outside_the_ladder(
    tmp_path: Path, registry: FakeRegistry, rung
) -> None:
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, rung, "a note")
    )

    assert result["error_code"] == "repair.bad_rung"
    assert registry.mint_calls == []
    assert PROOF_ID in _pinned_in_order(tools)


def test_a_rung_that_arrives_as_a_string_means_what_it_says(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A tool call carrying `"3"` should not cost a round to be told it meant 3."""
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, "3", "compact static fallback")
    )

    assert result["status"] == "ok"
    assert result["rung"] == 3
    assert registry.mint_calls[0]["rung"] == 3


def test_the_repair_refuses_an_empty_note_because_the_lineage_is_permanent(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _recreated(tmp_path, registry)

    result = json.loads(tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "   "))

    assert result["error_code"] == "repair.note_missing"
    assert registry.mint_calls == []


# --------------------------------------------------------------------------- #
# The amended law (ruling D-F6)
# --------------------------------------------------------------------------- #


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


@pytest.mark.parametrize("prompt_of", ["director", "author"])
def test_the_old_absolutist_law_that_protected_brokenness_is_gone(prompt_of: str) -> None:
    """F2's "never edit a cloned section's internals" is exactly what D-F6 amends away.

    Asserted on both prompts because both carried it, and a law removed from one surface while
    it still governs on the other is worse than not removing it at all.
    """
    prompt = _director_prompt() if prompt_of == "director" else _author_prompt()

    assert "NEVER EDIT A CLONED SECTION" not in prompt
    assert "never retype a cloned section" not in prompt.lower()


@pytest.mark.parametrize("prompt_of", ["director", "author"])
def test_the_amended_law_and_the_whole_ladder_reach_both_composing_roles(
    prompt_of: str,
) -> None:
    """The operative clauses, not the prose. A founder rewrite that keeps every clause stays
    green; one that drops the preserve-list, a rung, or the immutability of the original goes
    red, which is the only thing worth guarding."""
    prompt = _director_prompt() if prompt_of == "director" else _author_prompt()
    # Whitespace-collapsed: these prompts are hard-wrapped for a human reading the source, so a
    # clause that is present but broken across two lines is present.
    lowered = " ".join(prompt.lower().split())

    # 1. The governing principle, both halves.
    assert "the starting reference, not an untouchable artifact" in lowered
    assert (
        "never preserve a broken result merely because it came from the original site" in lowered
    )
    # 2. The amended law itself, replacing the absolutist one.
    assert "never casually rewrite a working cloned section" in lowered
    assert "preserve the original artifact" in lowered
    # 3. The ladder, three rungs IN ORDER.
    first = lowered.index("reproduce the original experience with supported primitives")
    second = lowered.index("equivalent interaction serving the same storytelling purpose")
    third = lowered.index("compact static fallback")
    assert first < second < third
    # 4. Rung 3's hard condition, and the thing that is never acceptable.
    assert "removed entirely" in lowered
    assert "blank dead space is never acceptable" in lowered
    # 5. The honest expectation — rung 1 is usually out of reach.
    assert "rung 1 is often unreachable" in lowered or "rung 1 to be unreachable" in lowered
    # 6. The preserve-list, every item of it.
    for clause in (
        "content hierarchy and order",
        "typography and colors",
        "image treatment",
        "proportions and density",
        "spacing",
        "section rhythm",
        "storytelling purpose",
        "brand's character",
    ):
        assert clause in lowered, clause
    # 7. The Grammar Audit governs the adaptation.
    assert "grammar audit" in lowered
    # 8. The mechanics: one tool, and the original survives it.
    assert "repair_cloned_section" in prompt


def test_the_recreate_walk_is_law_on_both_composing_roles() -> None:
    """"All of them, in source order, nothing added" is stated where the decision is made."""
    for prompt in (_director_prompt(), _author_prompt()):
        lowered = " ".join(prompt.lower().split())
        assert "recreate_cloned_page" in prompt
        assert "in the order it sat on the page" in lowered
        assert "nothing added" in lowered or "add nothing to it" in lowered
    # And the dormant rule (D-F8) is the director's, where the section plan is decided.
    director = " ".join(_director_prompt().lower().split())
    assert "hides never appears on a recreated page" in director


def test_replacement_markup_the_engine_rejects_never_reaches_the_mint(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """A repair is engine-validated like any authored section — a raw hex is still a hard error."""
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(
            PROOF_ID,
            '<section id="sec_bad" class="bg-[#ff0000]"><p>Nope</p></section>',
            3,
            "a fallback that uses a colour this brand never measured",
        )
    )

    assert result["status"] == "rejected"
    assert registry.mint_calls == []
    # The page is untouched: the broken clone is still there, which is the honest state.
    assert PROOF_ID in _pinned_in_order(tools)
