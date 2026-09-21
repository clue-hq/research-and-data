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
from lumen_api.agent_cloned_sections import _resolve_lineages

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

    **The lineage verdict is not re-implemented here** — ``list_sections`` calls the registry's
    own :func:`_resolve_lineages` over these rows. A fake that computed "which repair supersedes
    which" for itself would be asserting its own arithmetic, and ruling R-C1 is precisely about
    that arithmetic being right.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.rows: dict[str, dict] = {}
        self.mint_calls: list[dict] = []
        #: What `mint_repair` answers, per repaired id. Absent → a fresh draft repair.
        self.mint_result: dict | None = None
        self._minted = 0
        #: F4.4 (ruling R-X9): what the release surface was asked to do, so a test can assert
        #: that a refused round released NOTHING rather than inferring it from a status.
        self.release_calls: list[str] = []
        self.render_calls: list[str] = []
        #: Set to an exception to make the isolation render fail (no browser on this host).
        self.render_raises: Exception | None = None

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
            # Distinct and increasing, because the lineage resolver's "oldest approved member"
            # fallback is an ordering over these — a fixture where every row is born at the same
            # instant would make that tie-break untestable.
            "created_at": f"2026-08-28T00:00:{len(self.rows):02d}Z",
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
        """Approved rows in document order, with the REAL lineage verdict on each."""
        rows = list(self.rows.values())
        repairs: dict[str, list[dict]] = {}
        for row in rows:
            if row.get("derived_from") and row["status"] != "dormant":
                repairs.setdefault(row["derived_from"], []).append(row)
        lineages = _resolve_lineages(rows)
        sections = []
        for row in sorted(
            (
                row
                for row in rows
                if row["status"] == "approved"
                and (section_role is None or row["section_role"] == section_role)
            ),
            key=lambda row: (row["page_url"], row["section_index"], row["fragment_id"]),
        ):
            fragment_id = row["fragment_id"]
            mine = repairs.get(fragment_id) or []
            verdict = lineages[fragment_id]
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
                    "lineage_root": verdict.root,
                    "superseded_by": (
                        verdict.representative
                        if verdict.representative
                        and verdict.representative != fragment_id
                        else None
                    ),
                    "lineage_ambiguous": list(verdict.ambiguous),
                    "lineage_ranked_over": list(verdict.ranked_over),
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
        # The real gate resolves lineage only for a DEGRADED answer (it costs a scan and nothing
        # else reads it); so does this, or the fake would prove the cheaper path works.
        superseded_by, ambiguous, ranked_over, degraded_fallback = None, [], [], False
        if row["degraded"]:
            verdict = _resolve_lineages(list(self.rows.values()))[fragment_id]
            if verdict.representative and verdict.representative != fragment_id:
                superseded_by = verdict.representative
            ambiguous = list(verdict.ambiguous)
            # Ruling R-X4: the pin gate carries the wholly-broken-family verdict too, so every
            # door that puts a band on a page can say "selected, not fixed".
            ranked_over = list(verdict.ranked_over)
            degraded_fallback = verdict.degraded_fallback
        return {
            "fragment_id": fragment_id,
            "section_role": row["section_role"],
            "label": row["label"],
            "source_url": row["source_url"],
            "slots": list(row["slots"]),
            "preview_path": row["preview_path"],
            "degraded": row["degraded"],
            "degraded_reason": row["degraded_reason"],
            "degraded_note": row["degraded_note"],
            "derived_from": row["derived_from"],
            "superseded_by": superseded_by,
            "lineage_ambiguous": ambiguous,
            "lineage_ranked_over": ranked_over,
            "lineage_degraded_fallback": degraded_fallback,
            "render": {
                "html": row["html"],
                "css": row["css"],
                "slot_kinds": {slot["key"]: slot["kind"] for slot in row["slots"]},
                "asset_digests": [],
                "derived": bool(row["derived_from"]),
            },
        }

    # --- F4.4 (ruling R-X9): the per-repair release surface ------------------------------------
    #
    # Two methods, and the SPLIT between them is the law, not an implementation detail: rendering
    # the picture is one act, releasing on the strength of it is another, and the human's answer
    # goes in between. The fake keeps them apart for the same reason the registry does.

    def render_repair_preview(self, fragment_id, core):
        row = self.rows.get(fragment_id)
        if row is None:
            raise _fragment_refused("fragment.unresolved", f"{fragment_id!r} is unknown")
        if self.render_raises is not None:
            raise self.render_raises
        if row.get("preview_digest"):
            return None
        path = self.tmp_path / f"{fragment_id}.png"
        path.write_bytes(PNG_1PX)
        row["preview_digest"] = "e" * 64
        row["preview_path"] = str(path)
        self.render_calls.append(fragment_id)
        return row["preview_digest"]

    def release_repair(self, fragment_id):
        row = self.rows.get(fragment_id)
        if row is None:
            raise _fragment_refused("fragment.unresolved", f"{fragment_id!r} is unknown")
        if not row.get("derived_from"):
            raise _fragment_refused(
                "repair.not_a_repair",
                f"{fragment_id} is not a repair — released by approving the brand kit",
            )
        if row["status"] != "draft":
            raise _fragment_refused(
                "repair.not_releasable",
                f"repair {fragment_id} is {row['status']!r}, not 'draft': it is already released",
            )
        if not row.get("preview_digest"):
            raise _fragment_refused(
                "repair.no_preview",
                f"repair {fragment_id} has no preview image. Render one first",
            )
        row["status"] = "approved"
        self.release_calls.append(fragment_id)
        return {
            "fragment_id": fragment_id,
            "status": "approved",
            "derived_from": row["derived_from"],
            "derived_reason": row["derived_reason"],
            "label": row["label"],
            "section_role": row["section_role"],
            "preview_digest": row["preview_digest"],
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


def _fragment_refused(code: str, message: str):
    """The registry's OWN refusal type (``FragmentRefused``), which is what the release surface
    raises — not the document write's ``FragmentReferenceError`` that the pin gate re-raises."""
    from lumen_api.fragments import FragmentRefused

    return FragmentRefused(code, message)


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
    assert warning["code"] == "LUMA0811"
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


# --------------------------------------------------------------------------- #
# One section per lineage (ruling R-C1) — both shapes the review reproduced
# --------------------------------------------------------------------------- #


def test_two_released_repairs_of_one_band_refuse_rather_than_pinning_it_twice(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Repro A. A repair is an ordinary approved row, so a second one is named by nobody.

    Before R-C1 this pinned FIVE sections where the page had four — the band twice and the
    footer displaced — and reported none of it. Picking one of the two would silently discard
    somebody's deliberate repair, so the answer is a human's.
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID)
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from=PROOF_ID)
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["error_code"] == "recreate.lineage_ambiguous"
    assert result["lineage_root"] == PROOF_ID
    assert sorted(result["candidates"]) == ["frag_00000000000000b2", "frag_00000000000000b3"]
    # Nothing was pinned: a half-built homepage is worse than none.
    assert _sections(tools) == []


def test_a_repair_of_a_repair_wins_and_never_lets_the_broken_original_back(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Repro B. The chain is walked transitively, and a degraded middle is stepped OVER.

    Before R-C1 the degraded intermediate stopped being anybody's `superseded_by`, so the
    original — the band D-F6 marked broken in the first place — went back on the page beside the
    healthy repair.
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID, degraded=True, degraded_reason="dead_height")
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from="frag_00000000000000b2")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["status"] == "ok"
    assert _pinned_in_order(tools) == [
        NAV_ID,
        HERO_ID,
        "frag_00000000000000b3",
        FOOTER_ID,
    ]
    assert PROOF_ID not in _pinned_in_order(tools)
    assert "frag_00000000000000b2" not in _pinned_in_order(tools)
    assert result["needs_repair"] == []
    assert [entry["substituted_for"] for entry in result["substituted"]] == [PROOF_ID]


def test_a_degraded_NEWEST_repair_never_costs_the_family_its_healthy_one(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling N1 — C1's Repro B one rung deeper, and it failed the same guarantee.

    `A(broken) → R1(approved, healthy) → R2(approved, later marked degraded)`. Counting EVERY
    approved child as superseding meant R2 knocked its own healthy parent R1 out of the leaf set;
    the leaf set emptied and the fallback jumped past R1 all the way to the broken original. The
    shipped tool pinned `nav, hero, PROOF(broken), footer` while a human-released healthy repair
    of that band sat unused. A repair nobody should pin supersedes nothing.
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID)
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from="frag_00000000000000b2", degraded=True,
                 degraded_reason="dead_height")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert _pinned_in_order(tools) == [
        NAV_ID,
        HERO_ID,
        "frag_00000000000000b2",
        FOOTER_ID,
    ]
    assert PROOF_ID not in _pinned_in_order(tools)
    assert result["needs_repair"] == []
    assert [entry["substituted_for"] for entry in result["substituted"]] == [PROOF_ID]


@pytest.mark.parametrize("middle_status", ["approved", "deprecated"])
def test_a_healthy_original_is_never_ambiguous_with_its_own_healthy_descendant(
    tmp_path: Path, registry: FakeRegistry, middle_status: str
) -> None:
    """Ruling R-X1 — supersession is transitive over DESCENDANTS, not children.

    `A(healthy) → M(broken) → L(healthy)`. Asking about children made the degraded middle stop
    shielding its ancestors, so the original AND its own grandchild both looked like ends of the
    chain: the family was declared ambiguous BETWEEN THEM, the whole page refused, and the
    message named the original as one of its own "2 released repairs". `L` supersedes `A`
    transitively; there is nothing ambiguous about it.

    The `deprecated` middle is the same bug wearing a different status, and it predates the
    round-2 regression — so it is parametrized rather than left for somebody to rediscover.
    """
    registry.add(
        "frag_00000000000000b2",
        role="nav",
        label="Repair one",
        index=0,
        derived_from=NAV_ID,
        status=middle_status,
        degraded=middle_status == "approved",
        degraded_reason="dead_height" if middle_status == "approved" else None,
    )
    registry.add("frag_00000000000000b3", role="nav", label="Repair two", index=0,
                 derived_from="frag_00000000000000b2")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["status"] == "ok", result.get("message")
    assert _pinned_in_order(tools) == [
        "frag_00000000000000b3",
        HERO_ID,
        PROOF_ID,
        FOOTER_ID,
    ]
    assert NAV_ID not in _pinned_in_order(tools)
    assert [entry["substituted_for"] for entry in result["substituted"]] == [NAV_ID]
    # And the picker no longer tells the same false story about the healthy original.
    listing = json.loads(tools.search_cloned_sections(limit=20))
    nav = next(row for row in listing["results"] if row["fragment_id"] == NAV_ID)
    assert "lineage_ambiguous" not in nav
    assert nav["superseded_by"] == "frag_00000000000000b3"


def test_a_chain_of_broken_middles_is_stepped_over_however_deep(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Transitivity is not a special case for depth 2."""
    registry.add("frag_00000000000000b2", role="proof", label="M1", index=2,
                 derived_from=PROOF_ID, degraded=True, degraded_reason="dead_height")
    registry.add("frag_00000000000000b3", role="proof", label="M2", index=2,
                 derived_from="frag_00000000000000b2", degraded=True,
                 degraded_reason="dead_height")
    registry.add("frag_00000000000000b4", role="proof", label="L", index=2,
                 derived_from="frag_00000000000000b3")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert _pinned_in_order(tools) == [
        NAV_ID,
        HERO_ID,
        "frag_00000000000000b4",
        FOOTER_ID,
    ]
    assert result["needs_repair"] == []


def test_when_every_released_version_is_broken_the_ranking_is_stated(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling N4, AMENDED BY FOUNDER RULING R-X4 (2026-08-29).

    It cannot refuse — a hole where the band goes is worse than a flagged band — so it says which
    broken candidate it pinned and what that beat. What R-X4 changed is WHICH one: under the
    default ``keep_flagged`` the NEWEST repair stays on the page, flagged, because "never
    silently return to a known-broken original". This test previously asserted the original
    (``PROOF_ID``) went back on the page; that expectation is superseded, not weakened — the
    fallback still picks exactly one, still ranks the rest, and still reports the band as work.
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID, degraded=True, degraded_reason="dead_height")
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from=PROOF_ID, degraded=True, degraded_reason="dead_height")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    # R-X4: the NEWEST approved member goes on the page — flagged — and the original it was
    # composed to replace is one of the things it beat.
    newest = "frag_00000000000000b3"
    assert newest in _pinned_in_order(tools)
    assert PROOF_ID not in _pinned_in_order(tools)
    assert [entry["fragment_id"] for entry in result["needs_repair"]] == [newest]
    (ranked,) = result["ranked"]
    assert ranked["fragment_id"] == newest
    assert sorted(ranked["ranked_over"]) == [PROOF_ID, "frag_00000000000000b2"]
    # ADVICE, not a warning: the band is already reported as work through `needs_repair`. And its
    # OWN code (ruling X4) — a consumer filtering by code alone must not get two entries under
    # LUMA0811 meaning different things.
    (advice,) = [item for item in result["advice"] if item.get("code") == "LUMA0812"]
    assert advice["severity"] == "advice"
    assert "SELECTED rather than fixed" in advice["message"]
    assert "requires review" in advice["message"]
    # And the warning half says it too, so a pin made by any other door reads the same law.
    (warning,) = [item for item in result["warnings"] if item.get("code") == "LUMA0811"]
    assert "REQUIRES REVIEW" in warning["message"]
    assert result["needs_repair"][0]["degraded_fallback"] is True
    codes = [item.get("code") for item in result["warnings"] + result["advice"]]
    assert codes.count("LUMA0811") == 1
    assert {item["severity"] for item in result["warnings"] + result["advice"]
            if item.get("code") == "LUMA0811"} == {"warning"}


def test_the_picker_says_when_a_family_has_two_released_repairs(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling N5: the first contact with an ambiguous family should not be a total refusal."""
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID)
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from=PROOF_ID)
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.search_cloned_sections(limit=20))

    proof = next(row for row in result["results"] if row["fragment_id"] == PROOF_ID)
    assert sorted(proof["lineage_ambiguous"]) == [
        "frag_00000000000000b2",
        "frag_00000000000000b3",
    ]
    assert "retires all but one" in proof["lineage_note"]
    healthy = next(row for row in result["results"] if row["fragment_id"] == NAV_ID)
    assert "lineage_ambiguous" not in healthy


def test_a_lineage_whose_only_repair_is_itself_broken_keeps_the_repair_flagged(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """FOUNDER RULING R-X4 (2026-08-29) supersedes this test's old expectation.

    It used to assert "else the original" — the broken original went back on the page, flagged.
    The founder's ruling is the opposite and says why: "never silently return to a known-broken
    original". The repair stays selected, in the original's page position, and it is still
    reported as work through ``needs_repair`` — the reporting half is unchanged, which is what
    makes this a change of choice rather than a loss of honesty.
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID, degraded=True, degraded_reason="dead_height")
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    repair = "frag_00000000000000b2"
    assert _pinned_in_order(tools) == [NAV_ID, HERO_ID, repair, FOOTER_ID]
    assert [entry["fragment_id"] for entry in result["needs_repair"]] == [repair]
    assert result["needs_repair"][0]["degraded_fallback"] is True


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
    # Born unreleased, and the tool says so instead of implying a pin. ~~"approving the brand
    # kit"~~ — superseded by FOUNDER RULING R-X9 (2026-08-29): the kit no longer releases
    # repairs, so the sentence the agent reads now names the chat approval and the tool that
    # enacts it. Superseded, not weakened: the tool still refuses to imply a pin.
    assert result["pinned"] is False
    assert "released ONE AT A TIME, by the user" in result["release"]
    assert "approving the brand kit does NOT release repairs" in result["release"]
    assert "release_repair(fragment_id)" in result["release"]

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
    assert "LUMA0810" not in codes
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


def test_a_repair_that_converges_onto_a_BROKEN_released_row_reports_it_rather_than_pinning_quietly(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling N3 — the third pin door.

    `fragment.repair_unchanged` blocks convergence onto the ORIGINAL and nothing else, so a mint
    whose bytes converge onto some other already-approved row can land on one a later pass marked
    broken. That row is `insertable`, so the tool pins it — and used to report a clean repair.
    """
    registry.add(
        REPAIR_ID,
        role="proof",
        label="Repaired — Proof",
        index=2,
        derived_from=PROOF_ID,
        degraded=True,
        degraded_reason="dead_height",
    )
    tools = _tools(tmp_path, registry)
    assert json.loads(tools.insert_cloned_section(PROOF_ID))["status"] == "ok"
    registry.mint_result = {
        "fragment_id": REPAIR_ID,
        "replaces": PROOF_ID,
        "status": "approved",
        "derived_from": PROOF_ID,
        "derived_reason": "repair rung 3 (...)",
        "slot_keys": [],
        "asset_digests": [],
        "sanitizer_notes": [],
        "converged": True,
        "lineage_kept": True,
        "insertable": True,
    }

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["pinned"] is True
    assert _pinned_in_order(tools) == [REPAIR_ID]
    # The band that landed is itself broken, and the third door says so like the other two.
    assert [entry["fragment_id"] for entry in result["needs_repair"]] == [REPAIR_ID]
    assert any(w.get("code") == "LUMA0811" for w in result["warnings"])


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


def test_pinning_a_broken_band_the_ordinary_way_reports_it_too(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling R-I4: the degraded warning fires from EVERY door, not only the recreate walk.

    Composing a page and reaching for one clone with `insert_cloned_section` is the commoner
    shape, and it used to return a clean `ok` — leaving nothing between a measured-broken band
    and a published page full of dead space but a picker attribute seen several turns ago.
    """
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(PROOF_ID))

    assert result["status"] == "ok"
    assert [entry["fragment_id"] for entry in result["needs_repair"]] == [PROOF_ID]
    assert result["needs_repair"][0]["reason"] == "dead_height"
    assert result["needs_repair"][0]["section_node_id"] == result["section_node_id"]
    warning = result["warnings"][0]
    assert warning["code"] == "LUMA0811"
    assert "repair_cloned_section" in warning["hint"]


def test_the_broken_pin_warning_never_claims_a_repair_does_not_exist_when_it_does(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling N2. The old text said "and have no released repair" from every door.

    That is true by construction of the recreate walk, which substitutes one when it exists, and
    a guess anywhere else. Told it from the insert door, an author composes a SECOND repair of a
    band that already has one — and after the next bulk kit approval that leaves two released
    siblings and a whole-page assembly that refuses.
    """
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2, derived_from=PROOF_ID
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(PROOF_ID))

    warning = result["warnings"][0]
    assert warning["code"] == "LUMA0811"
    assert "no released repair" not in warning["message"]
    assert "ALREADY HAVE a released repair" in warning["hint"]
    assert f"{PROOF_ID} -> {REPAIR_ID}" in warning["hint"]
    # ...and it does NOT tell the author to compose another one.
    assert "repair_cloned_section" not in warning["hint"]
    assert result["needs_repair"][0]["superseded_by"] == REPAIR_ID


def test_the_broken_pin_warning_never_advises_a_THIRD_repair_of_a_contested_band(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """Ruling X2 — `superseded_by is None` is two different worlds.

    "No repair exists" and "two released repairs exist and neither replaces the other" both
    answer `None`, and reading the second as the first pointed the author at
    `repair_cloned_section` for the ONE band that could least afford another: a third sibling
    deepens an ambiguity that already refuses the whole-page assembly. It is also the path the
    product steers onto, because the ambiguity refusal itself says "pin one explicitly".
    """
    registry.add("frag_00000000000000b2", role="proof", label="Repair one", index=2,
                 derived_from=PROOF_ID)
    registry.add("frag_00000000000000b3", role="proof", label="Repair two", index=2,
                 derived_from=PROOF_ID)
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(PROOF_ID))

    warning = result["warnings"][0]
    assert warning["code"] == "LUMA0811"
    assert "no released repair" not in warning["message"]
    assert "MORE THAN ONE released repair" in warning["hint"]
    assert "frag_00000000000000b2" in warning["hint"]
    assert "frag_00000000000000b3" in warning["hint"]
    # The instruction that would deepen it is withheld, exactly as in the single-repair branch.
    assert "repair_cloned_section" not in warning["hint"]
    assert "ask the user" in warning["hint"]
    entry = result["needs_repair"][0]
    assert entry["superseded_by"] is None
    assert sorted(entry["lineage_ambiguous"]) == [
        "frag_00000000000000b2",
        "frag_00000000000000b3",
    ]


def test_the_broken_pin_warning_still_says_so_when_no_repair_exists(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The claim is allowed once it has been resolved — and then it IS the right instruction."""
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(PROOF_ID))

    warning = result["warnings"][0]
    assert "none of them has a released repair" in warning["message"]
    assert "repair_cloned_section" in warning["hint"]
    assert result["needs_repair"][0]["superseded_by"] is None


def test_pinning_a_healthy_band_the_ordinary_way_says_nothing_new(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The key is always present and empty — an absent key reads as "fine" when it means
    "this build did not look"."""
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.insert_cloned_section(NAV_ID))

    assert result["needs_repair"] == []
    assert [w.get("code") for w in result["warnings"]] == []


# --------------------------------------------------------------------------- #
# The mint's failure branches (ruling R-I3)
# --------------------------------------------------------------------------- #


def test_a_replacement_that_is_two_sections_is_refused_before_the_mint(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _recreated(tmp_path, registry)

    result = json.loads(
        tools.repair_cloned_section(
            PROOF_ID,
            '<section id="sec_a" class="w-full"><p>One</p></section>'
            '<section id="sec_b" class="w-full"><p>Two</p></section>',
            3,
            "two bands where the page had one",
        )
    )

    assert result["error_code"] == "repair.not_one_section"
    assert len(result["roots"]) == 2
    assert registry.mint_calls == []


def test_a_render_that_fails_leaves_the_page_repaired_and_mints_nothing(
    tmp_path: Path, registry: FakeRegistry, monkeypatch
) -> None:
    """The swap has already happened by then, so the page is FINE — only the artifact is lost."""
    from lumen_api.core import CoreError

    tools = _recreated(tmp_path, registry)
    real_render = tools.core.web_render
    monkeypatch.setattr(
        tools.core,
        "web_render",
        lambda *a, **k: (_ for _ in ()).throw(CoreError("helper died", [])),
    )

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["error_code"] == "repair.render_failed"
    assert registry.mint_calls == []
    # The broken clone is OFF the page and the composed section is on it: the repair happened,
    # only its durable record did not.
    assert PROOF_ID not in _pinned_in_order(tools)
    assert "sec_repaired_proof" in _sections(tools)
    assert real_render is not None


def test_a_section_missing_from_the_render_mints_nothing_rather_than_the_nearest_thing(
    tmp_path: Path, registry: FakeRegistry, monkeypatch
) -> None:
    from lumen_agent.tools import web_substrate

    tools = _recreated(tmp_path, registry)
    monkeypatch.setattr(web_substrate, "_section_subtree", lambda *a, **k: "")

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["error_code"] == "repair.section_not_rendered"
    assert registry.mint_calls == []


def test_a_worker_with_no_css_toolchain_refuses_by_name_and_does_not_retry(
    tmp_path: Path, registry: FakeRegistry, monkeypatch
) -> None:
    """Ruling R-I3: the environment failure is told apart from a compile failure.

    "There is no compiler on this machine" and "the compile rejected your CSS" have different
    remedies, and only one of them is worth another round.
    """
    from lumen_agent.tools import web_substrate
    from lumen_api.web_export import WebExportToolchainMissing

    tools = _recreated(tmp_path, registry)
    monkeypatch.setattr(
        web_substrate,
        "compile_section_css",
        lambda *a, **k: (_ for _ in ()).throw(
            WebExportToolchainMissing("node is not on PATH (looked for 'node')")
        ),
    )

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["error_code"] == "repair.toolchain_unavailable"
    assert "node is not on PATH" in result["message"]
    assert "Do not retry" in result["message"]
    assert registry.mint_calls == []
    assert PROOF_ID not in _pinned_in_order(tools)


def test_a_compile_that_rejects_the_css_mints_nothing_rather_than_an_unstyled_artifact(
    tmp_path: Path, registry: FakeRegistry, monkeypatch
) -> None:
    from lumen_agent.tools import web_substrate
    from lumen_api.web_export import WebExportCompileError

    tools = _recreated(tmp_path, registry)
    monkeypatch.setattr(
        web_substrate,
        "compile_section_css",
        lambda *a, **k: (_ for _ in ()).throw(WebExportCompileError("tailwind exploded")),
    )

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["error_code"] == "repair.css_compile_failed"
    assert "publish unstyled" in result["message"]
    assert registry.mint_calls == []


def test_a_registry_refusal_reaches_the_author_as_the_registrys_own_code(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """`fragment.repair_unchanged` / `fragment.unrehosted_reference` are the registry's words."""
    from lumen_api.fragments import FragmentRefused

    tools = _recreated(tmp_path, registry)

    def refuse(**kwargs):
        raise FragmentRefused(
            "fragment.repair_unchanged", "this repair's markup is identical to the original"
        )

    registry.mint_repair = refuse

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "changed nothing")
    )

    assert result["error_code"] == "fragment.repair_unchanged"
    assert "still carries your replacement section" in result["message"]


def test_an_unexpected_mint_failure_says_the_page_is_still_fine(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _recreated(tmp_path, registry)

    def explode(**kwargs):
        raise RuntimeError("the database went away")

    registry.mint_repair = explode

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["error_code"] == "repair.mint_failed"
    assert "RuntimeError" in result["message"]
    assert "still carries your replacement section" in result["message"]


def test_a_pin_that_the_gate_refuses_reports_it_and_keeps_the_composed_section(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """`_pin_repair_in_place` failing costs the artifact's reuse, never the page's pixels."""
    tools = _tools(tmp_path, registry)
    assert json.loads(tools.insert_cloned_section(PROOF_ID))["status"] == "ok"
    registry.mint_result = {
        "fragment_id": REPAIR_ID,
        "replaces": PROOF_ID,
        "status": "approved",
        "derived_from": PROOF_ID,
        "derived_reason": "repair rung 3 (...)",
        "slot_keys": [],
        "asset_digests": [],
        "sanitizer_notes": [],
        "converged": True,
        "lineage_kept": True,
        "insertable": True,
    }
    # The repair id was never added to the fake, so the gate cannot resolve it.

    result = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "compact fallback")
    )

    assert result["status"] == "ok"
    assert result["pinned"] is False
    assert "FragmentReferenceError" in result["pin_refusal"]
    assert "sec_repaired_proof" in _sections(tools)


# --------------------------------------------------------------------------- #
# A repair that carries an image (review rider)
# --------------------------------------------------------------------------- #


def test_an_image_in_a_repair_reaches_the_mint_as_the_artifacts_own_byte_reference(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The asset half of ruling R17-1, end to end rather than on paper.

    The mint runs the fail-closed reference gate with an EMPTY rehost map, so the only reason a
    repair may carry an image at all is that the render is asked for the artifact's own spelling
    (`asset_base_url="/asset-store"`). If that ever changed, the engine would emit the turn's
    absolute origin, `resolve_asset_reference` would find no entry, and every repair with a
    picture in it would refuse.
    """
    digest = "c" * 64
    doc = _empty_doc()
    doc["assets"]["asset_hero_1"] = {
        "id": "asset_hero_1",
        "label": "Clinic",
        "kind": "raster_image",
        "status": "ready",
        "source": {"kind": "generated", "model": "test-model", "request_id": None},
        "media": {
            "mime_type": "image/png",
            "digest": {"algorithm": "sha256", "value": digest},
            "location": {
                "provider": "local-store",
                "opaque_ref": f"sha256/cc/{digest}",
                "url": None,
            },
        },
    }
    tools = _tools(tmp_path, registry, doc)
    assert json.loads(tools.recreate_cloned_page())["status"] == "ok"

    result = json.loads(
        tools.repair_cloned_section(
            PROOF_ID,
            '<section id="sec_repaired_proof" class="w-full py-section">'
            '<div class="mx-auto max-w-5xl px-6">'
            '<h2 class="text-3xl font-semibold text-primary">Trusted by 400 clinics</h2>'
            '<img data-asset="asset_hero_1" alt="A clinic">'
            "</div></section>",
            3,
            "the same proof band with its photograph, at its natural height",
        )
    )

    assert result["status"] == "ok"
    (call,) = registry.mint_calls
    # The engine emitted the artifact's own spelling, so the sanitizer resolves it with no
    # rehost map — which is the whole reason a repair needs none.
    assert f'src="/asset-store/{digest}"' in call["html"]
    assert "127.0.0.1" not in call["html"]


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


def _solo_prompt() -> str:
    from lumen_agent.prompts_web import build_web_solo_prompt

    return build_web_solo_prompt(
        doc_title="Insight Health", has_existing_content=False,
        brand_card="{}", theme_token_names="brand, ink",
    )


@pytest.mark.parametrize("prompt_of", ["director", "author"])
def test_the_old_absolutist_law_that_protected_brokenness_is_gone(prompt_of: str) -> None:
    """F2's "never edit a cloned section's internals" is exactly what D-F6 amends away.

    Asserted on both prompts because both carried it, and a law removed from one surface while
    it still governs on the other is worse than not removing it at all.

    **Whitespace-collapsed, and that is not cosmetic** (review finding I2). These prompts are
    hard-wrapped, so a raw `not in` can pass merely because the clause it forbids happens to be
    broken across two lines — an absence test that a prose reflow can flip is worse than none.
    What D-F6 forbids is the BLANKET ban; a rule protecting a WORKING clone is allowed to stay,
    so the second half asserts that every surviving "never rewrite/retype" clause carries its
    qualifier rather than asserting the clause away.
    """
    prompt = _director_prompt() if prompt_of == "director" else _author_prompt()
    flat = " ".join(prompt.lower().split())

    # The absolutist law, in either of the two spellings it had.
    assert "never edit a cloned section's internals" not in flat
    assert "never edit a cloned section" not in flat
    assert "its slots are the whole of what may change" not in flat
    # Every surviving prohibition on rewriting a clone names the case it governs.
    for clause, qualifier in (
        ("never retype a", "never retype a working cloned section"),
        ("never casually rewrite", "never casually rewrite a working cloned section"),
    ):
        if clause in flat:
            assert qualifier in flat, clause


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


def test_the_tool_docstrings_carry_the_amendment_too() -> None:
    """A tool's docstring IS prompt text — it is the description the model reads at call time.

    Report §7 claimed the amendment was "gone from every surface, asserted by test" when only
    the two prompts were asserted (review finding M8). This makes the claim true.
    """
    for tool in (
        LumenWebTools.search_cloned_sections,
        LumenWebTools.insert_cloned_section,
        LumenWebTools.repair_cloned_section,
        LumenWebTools.recreate_cloned_page,
    ):
        flat = " ".join((tool.__doc__ or "").lower().split())
        assert "never edit a cloned section" not in flat, tool.__name__
        if "its slots are the whole of what may change" in flat:
            assert "on a healthy one" in flat, tool.__name__
    ladder = " ".join(
        (LumenWebTools.search_cloned_sections.__doc__ or "").lower().split()
    )
    assert "never casually rewrite a working cloned section" in ladder
    assert "repair_cloned_section" in ladder


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


# --------------------------------------------------------------------------- #
# Releasing one repair, chat-only (F4.4, FOUNDER RULING R-X9)
# --------------------------------------------------------------------------- #
#
# The founder, 2026-08-29: "require individual approval for each repair. Brand-kit approval
# should not silently approve later repairs. … do not add approval gates to our UI. Just ask for
# approval via chat only. First of all you need to explain."
#
# So there are two things to pin here and they are different kinds of thing: the TOOL's
# structural gates (what it refuses, whatever anybody typed) and the PROMPT's law (that the agent
# explains and asks before it ever calls the tool). The tool cannot enforce the second — no gate
# can detect a human's consent — which is exactly why the wording is tested as law.


def _squashed(text: str) -> str:
    """The two prompt builders are f-strings and their source is hard-wrapped, so an assertion
    on a clause has to be made against the RENDERED, whitespace-collapsed prompt or a prose
    reflow flips it (the T25 I-2 lesson, and the neighbouring D-F6 tests' own rule)."""
    return " ".join(text.split())


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt, _solo_prompt])
def test_a_vocabulary_repair_is_released_only_by_the_user_in_chat_is_prompt_law(prompt_of) -> None:
    """R-X9 applies to vocabulary drafts, never raw repairs or campaign variants.

    Explain first, ask second, call third — and no UI gate anywhere, because there is none to
    point at.
    """
    prompt = _squashed(prompt_of())

    lowered = prompt.lower()
    assert "release_repair" in lowered
    assert "no approval button" in lowered
    # The kit no longer does it, said where the agent will read it before it tries.
    assert "does not release repairs" in lowered
    # And the ask lives in the conversation, because there is nowhere else for it to live.
    assert "user" in lowered
    assert "vocabulary" in lowered
    assert "existing explicit approval for this repair stands" in lowered
    assert "raw" in lowered and "released at mint" in lowered


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt, _solo_prompt])
def test_composing_role_explains_then_asks_then_calls(prompt_of) -> None:
    """"First of all you need to explain" — the ORDER is the law, not just the ingredients."""
    prompt = _squashed(prompt_of())

    explain = prompt.index("FIRST EXPLAIN")
    ask = prompt.index("THEN ASK")
    call = prompt.index("THEN CALL")
    assert explain < ask < call
    assert "wait for a yes" in prompt
    assert "No answer is not a yes" in prompt
    # What the explanation must contain — the reason, the change, the evidence.
    assert "why the repair exists" in prompt
    assert "which rung" in prompt
    assert 'view("cloned_section:<id>")' in prompt


def test_releasing_a_repair_with_a_preview_flips_exactly_that_row(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The affirmative case: one call, one repair, and it is pinnable afterwards."""
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2,
        derived_from=PROOF_ID, status="draft",
    )
    second = "frag_00000000000000d9"
    registry.add(
        second, role="proof", label="Repaired — Proof (two)", index=2,
        derived_from=PROOF_ID, status="draft",
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.release_repair(REPAIR_ID))

    assert result["status"] == "ok"
    assert result["fragment_id"] == REPAIR_ID
    assert result["repair_status"] == "approved"
    assert result["replaces"] == PROOF_ID
    assert registry.release_calls == [REPAIR_ID]
    # "Individual approval for EACH repair": the sibling draft did not move.
    assert registry.rows[second]["status"] == "draft"
    assert "every other draft repair still needs its own approval" in result["note"]
    # And it is now pinnable, which is the only thing releasing it was for.
    assert json.loads(tools.insert_cloned_section(REPAIR_ID))["status"] == "ok"


def test_a_repair_with_no_preview_is_rendered_and_the_release_still_refuses(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """"First of all you need to explain" made mechanical: the round that MAKES the picture is
    never the round that releases. It renders, hands the picture back, and says to ask."""
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2,
        derived_from=PROOF_ID, status="draft",
    )
    registry.rows[REPAIR_ID]["preview_digest"] = None
    tools = _tools(tmp_path, registry)

    refused = json.loads(tools.release_repair(REPAIR_ID))

    assert refused["status"] == "error"
    assert refused["error_code"] == "release.preview_rendered"
    assert registry.render_calls == [REPAIR_ID]
    assert registry.release_calls == []
    assert registry.rows[REPAIR_ID]["status"] == "draft"
    assert f'view("cloned_section:{REPAIR_ID}")' in refused["message"]
    assert "ask" in refused["message"]
    # The picture is viewable in THIS turn, not merely durable somewhere.
    blocks = tools._view_content(f"cloned_section:{REPAIR_ID}")
    assert any(
        isinstance(block, dict) and block.get("type") == "image" for block in blocks
    ), blocks

    # ...and the second call, after the user said yes, releases.
    released = json.loads(tools.release_repair(REPAIR_ID))
    assert released["status"] == "ok"
    assert registry.release_calls == [REPAIR_ID]


def test_a_repair_that_cannot_be_rendered_at_all_refuses_with_both_reasons(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """No browser on this worker. The gate's sentence alone would tell the agent to render a
    preview it has just failed to render, so the refusal carries why the remedy did not work."""
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2,
        derived_from=PROOF_ID, status="draft",
    )
    registry.rows[REPAIR_ID]["preview_digest"] = None
    registry.render_raises = RuntimeError("playwright is not installed on this worker")
    tools = _tools(tmp_path, registry)

    refused = json.loads(tools.release_repair(REPAIR_ID))

    assert refused["error_code"] == "repair.no_preview"
    assert "playwright is not installed" in refused["message"]
    assert "leave it as a draft" in refused["message"]
    assert registry.release_calls == []


def test_releasing_a_harvested_clone_is_refused_and_names_the_surface_that_does_release_it(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry)

    refused = json.loads(tools.release_repair(NAV_ID))

    assert refused["error_code"] == "repair.not_a_repair"
    assert "brand kit" in refused["message"]
    assert registry.release_calls == []


def test_a_preview_less_section_that_is_not_a_repair_is_refused_without_being_photographed(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The gates run BEFORE the render, and that ordering is load-bearing: rendering first would
    take a picture of a harvested clone on the way to refusing it anyway, and would answer
    "a preview has been rendered" to a caller whose real problem is that this is not a repair."""
    registry.rows[NAV_ID]["preview_digest"] = None
    tools = _tools(tmp_path, registry)

    refused = json.loads(tools.release_repair(NAV_ID))

    assert refused["error_code"] == "repair.not_a_repair"
    assert registry.render_calls == []
    assert registry.release_calls == []


def test_releasing_an_already_released_repair_says_so_rather_than_reporting_success(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2,
        derived_from=PROOF_ID, status="approved",
    )
    tools = _tools(tmp_path, registry)

    refused = json.loads(tools.release_repair(REPAIR_ID))

    assert refused["error_code"] == "repair.not_releasable"
    assert "already released" in refused["message"]


def test_the_repair_to_release_walk_end_to_end(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The shape R-X9 describes, in order: mint a repair, be told it is unreleased and how it
    gets released, render+ask, release, pin."""
    tools = _recreated(tmp_path, registry)

    repaired = json.loads(
        tools.repair_cloned_section(PROOF_ID, REPLACEMENT_HTML, 3, "flattened the dead height")
    )
    assert repaired["status"] == "ok"
    assert repaired["pinned"] is False
    assert "release_repair(fragment_id)" in repaired["release"]

    # The mint's fake answer is a fresh draft with no picture — exactly what production mints.
    registry.add(
        REPAIR_ID, role="proof", label="Repaired — Proof", index=2,
        derived_from=PROOF_ID, status="draft",
    )
    registry.rows[REPAIR_ID]["preview_digest"] = None

    first = json.loads(tools.release_repair(REPAIR_ID))
    assert first["error_code"] == "release.preview_rendered"

    released = json.loads(tools.release_repair(REPAIR_ID))
    assert released["status"] == "ok"
    assert json.loads(tools.insert_cloned_section(REPAIR_ID))["status"] == "ok"
