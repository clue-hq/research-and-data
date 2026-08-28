"""Minting the ABM page's own header and footer (clone-fidelity F4.1, rulings R23-1/2/3).

The durable half — the sanitizer, the slot manifest, the shape gate, content-address convergence
— is pinned DB-backed in ``apps/api/tests/test_campaign_shell.py``. This file is about the walk:

* **The mint source is the ENGINE's render**, never a string this process typed (ruling R23-1,
  the rule the repair mint already obeys). The engine rewrites what it is handed — it mints node
  ids, wraps loose copy in a ``data-tv`` container, resolves ``data-asset`` to the artifact's own
  byte spelling — and the assertions below are on that gap, so a future short-circuit to the
  composed string would go red.
* **On a SCRATCH document.** Minting a brand's shells is a library operation: the page the author
  is building must be exactly as it was, before and after.
* **The seller's mark is the kit's own logo**, never refetched and never redrawn — and with no
  kit, or no logo in it, the tool refuses by name rather than composing a header with a hole in
  it where the brand goes.
* **A composed shell is not part of any page's recreate**, and the picker says which is which.

The registry is a fake that answers what the real capability answers; the ENGINE is real.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools
from lumen_api.fragments.campaign_shell import (
    CAMPAIGN_SHELL_FOOTER,
    CAMPAIGN_SHELL_HEADER,
    COBRAND_PLACEHOLDER_ASSET_ID,
    COBRAND_PLACEHOLDER_PNG,
    COMPOSED_CAMPAIGN_SHELL,
    DEFAULT_CTA_LABEL,
    DEFAULT_PREPARED_FOR,
    MARK_CTA,
    MARK_CTA_LABEL,
    MARK_LEGAL,
    MARK_PREPARED_FOR,
    MARK_TARGET_LOGO,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SELLER_DIGEST = hashlib.sha256(PNG_1PX).hexdigest()
COBRAND_DIGEST = hashlib.sha256(COBRAND_PLACEHOLDER_PNG).hexdigest()

PAGE = "https://insight.example/"
FOOTER_ID = "frag_0000000000000f01"


def _asset_record(asset_id: str, digest: str) -> dict:
    return {
        "id": asset_id,
        "label": "Insight Health logo",
        "kind": "logo",
        "status": "ready",
        "source": {"kind": "brand_guide", "source_asset_id": asset_id, "label": "logo"},
        "media": {
            "mime_type": "image/png",
            "filename": "logo.png",
            "byte_length": len(PNG_1PX),
            "digest": {"algorithm": "sha256", "value": digest},
            "location": None,
        },
    }


def _brand_kit(**overrides) -> dict:
    kit = {
        "id": "brand_kit_1",
        "version": 3,
        "name": "Insight Health",
        "assets": {
            "fonts": {},
            "images": {},
            "logos": {
                "primary": {
                    "usage": "primary",
                    "variants": [
                        {"name": "reversed", "color_mode": "reversed", "asset_id": "logo_rev"},
                        {"name": "full", "color_mode": "full_color", "asset_id": "logo_full"},
                    ],
                }
            },
        },
    }
    kit.update(overrides)
    return kit


def _brand_kit_assets() -> dict:
    return {
        "logo_full": {"record": _asset_record("logo_full", SELLER_DIGEST), "title": "Full colour"},
        "logo_rev": {"record": _asset_record("logo_rev", SELLER_DIGEST), "title": "Reversed"},
    }


class FakeRegistry:
    """What the real capability answers, without a database."""

    def __init__(self, tmp_path: Path, *, legal_html: str | None = None) -> None:
        self.tmp_path = tmp_path
        self.mint_calls: list[dict] = []
        self.placeholder_calls = 0
        self.legal_html = legal_html
        self.rows: dict[str, dict] = {}
        self._minted = 0

    # --- the F4.1 half ------------------------------------------------------------------------

    def campaign_shell_placeholder(self) -> dict:
        self.placeholder_calls += 1
        return {
            "asset_id": COBRAND_PLACEHOLDER_ASSET_ID,
            "digest": COBRAND_DIGEST,
            "media_type": "image/png",
            "byte_length": len(COBRAND_PLACEHOLDER_PNG),
            "record": {
                "id": COBRAND_PLACEHOLDER_ASSET_ID,
                "label": "Co-brand placeholder",
                "kind": "raster_image",
                "status": "ready",
                "source": {
                    "kind": "generated",
                    "model": COMPOSED_CAMPAIGN_SHELL,
                    "request_id": None,
                },
                "media": {
                    "mime_type": "image/png",
                    "filename": "campaign-shell-cobrand.png",
                    "byte_length": len(COBRAND_PLACEHOLDER_PNG),
                    "digest": {"algorithm": "sha256", "value": COBRAND_DIGEST},
                    "location": None,
                },
            },
        }

    def legal_link_evidence(self, *, kit_id=None):
        self.legal_kit_ids = getattr(self, "legal_kit_ids", [])
        self.legal_kit_ids.append(kit_id)
        return [(self.legal_html, PAGE)] if self.legal_html else []

    def mint_campaign_shell(self, *, role, html, css, label, **kwargs):
        self.mint_calls.append(
            {"role": role, "html": html, "css": css, "label": label, **kwargs}
        )
        self._minted += 1
        slots = (
            {
                "prepared_for": {"kind": "text", "fallback": DEFAULT_PREPARED_FOR},
                "target_logo": {"kind": "image", "fallback": COBRAND_DIGEST},
                "cta_href": {"kind": "href", "fallback": "#contact"},
                "cta_label": {"kind": "text", "fallback": DEFAULT_CTA_LABEL},
            }
            if role == CAMPAIGN_SHELL_HEADER
            else {}
        )
        return {
            "fragment_id": f"frag_00000000000000{self._minted:02d}",
            "shell_role": role,
            "section_role": role,
            "status": "draft",
            "label": label,
            "composed": COMPOSED_CAMPAIGN_SHELL,
            "slot_keys": sorted(slots),
            "slot_manifest": slots,
            "asset_digests": [SELLER_DIGEST, COBRAND_DIGEST],
            "sanitizer_notes": [],
            "converged": False,
            "insertable": False,
        }

    # --- the F2.3/F3.1 half the recreate reads ------------------------------------------------

    def add(self, fragment_id: str, *, role: str, label: str, index: int, composed=None) -> None:
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
            "slot_keys": [],
            "page_url": "composed:campaign-shell" if composed else PAGE,
            "section_index": None if composed else index,
            "created_at": f"2026-08-28T00:00:{len(self.rows):02d}Z",
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
            "html": f'<section class="clone-{role}"><p>{label}</p></section>',
            "css": "",
        }

    def list_sections(self, section_role=None):
        sections = [
            {key: value for key, value in row.items() if key not in ("html", "css", "preview_path")}
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
            fragment_id: {"slots": [], "preview_path": self.rows[fragment_id]["preview_path"]}
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
            "render": {
                "html": row["html"],
                "css": row["css"],
                "slot_kinds": {},
                "asset_digests": [],
                "derived": False,
            },
        }


def _empty_doc() -> dict:
    return {
        "schema_version": 1,
        "id": "doc_shells",
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


def _tools(tmp_path: Path, registry, *, brand_kit=None, brand_kit_assets=None):
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
        brand_kit=_brand_kit() if brand_kit is None else brand_kit,
        brand_kit_assets=_brand_kit_assets() if brand_kit_assets is None else brand_kit_assets,
    )
    return LumenWebTools(config, "Build the ABM page", initial_web_doc=_empty_doc())


@pytest.fixture()
def registry(tmp_path: Path) -> FakeRegistry:
    return FakeRegistry(tmp_path)


@pytest.fixture()
def minted(tmp_path: Path, registry: FakeRegistry) -> dict:
    """One real mint walk, shared by the assertions about what it produced."""
    tools = _tools(tmp_path, registry)
    return {"result": json.loads(tools.mint_campaign_shells()), "tools": tools}


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #


def test_the_walk_mints_one_header_and_one_footer_for_the_kit(minted: dict) -> None:
    result = minted["result"]

    assert result["status"] == "ok"
    assert [shell["shell_role"] for shell in result["shells"]] == [
        CAMPAIGN_SHELL_HEADER,
        CAMPAIGN_SHELL_FOOTER,
    ]
    assert result["seller"] == "Insight Health"
    assert all(shell["status"] == "draft" for shell in result["shells"])
    assert all(shell["insertable"] is False for shell in result["shells"])
    # Truthful release wording (fix-round I1): the kit is usually ALREADY approved when the
    # shells mint, so the release act is re-approval — the message must not send a human to a
    # gate that already fired.
    assert "RE-approving the brand kit" in result["release"]


def test_the_header_reports_exactly_the_ruled_slots(minted: dict) -> None:
    header = minted["result"]["shells"][0]

    assert header["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "cta_label", "kind": "text"},
        {"key": "prepared_for", "kind": "text"},
        {"key": "target_logo", "kind": "image"},
    ]
    assert minted["result"]["shells"][1]["slots"] == []


def test_the_mint_source_is_the_engines_own_render_not_a_string_we_typed(
    minted: dict, registry: FakeRegistry
) -> None:
    """The engine rewrites what it is handed. What reaches the mint carries its rewrites — the
    `data-tv` wrapper it added and the asset digest it resolved — and carries none of the
    authoring vocabulary the composer wrote (ruling R23-1)."""
    header = registry.mint_calls[0]["html"]

    assert 'data-tv="body"' in header
    assert f'src="/asset-store/{SELLER_DIGEST}"' in header
    assert f'src="/asset-store/{COBRAND_DIGEST}"' in header
    # The composer's own wire format is gone: `data-asset` and `data-href` are authoring
    # attributes the engine consumes, so their survival would mean the mint read our string.
    assert "data-asset=" not in header
    assert "data-href=" not in header


def test_the_marks_and_the_slots_survive_into_what_is_minted(registry: FakeRegistry, minted) -> None:
    header = registry.mint_calls[0]["html"]

    assert MARK_PREPARED_FOR in header
    assert MARK_TARGET_LOGO in header
    assert MARK_CTA in header
    assert MARK_CTA_LABEL in header
    assert "Prepared for" in header
    # The empty co-brand mark carries no alt text, so a screen reader says nothing rather than
    # announcing a placeholder.
    assert f'src="/asset-store/{COBRAND_DIGEST}" alt=""' in header


def test_the_footer_carries_the_copyright_and_no_links_without_evidence(
    registry: FakeRegistry, minted: dict
) -> None:
    footer = registry.mint_calls[1]["html"]

    assert "All rights reserved" in footer
    assert "<a" not in footer
    assert minted["result"]["legal_links"] == []
    assert "no privacy or terms link was found" in minted["result"]["legal_links_note"]


def test_the_footer_carries_the_sellers_own_legal_links_when_the_evidence_has_them(
    tmp_path: Path,
) -> None:
    registry = FakeRegistry(
        tmp_path,
        legal_html=(
            '<section><a href="/privacy">Privacy Policy</a>'
            '<a href="/terms">Terms</a><a href="/careers">Careers</a></section>'
        ),
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.mint_campaign_shells())

    assert result["legal_links"] == [
        "https://insight.example/privacy",
        "https://insight.example/terms",
    ]
    footer = registry.mint_calls[1]["html"]
    assert footer.count("<a ") == 2
    assert "careers" not in footer.lower()


def test_the_shells_are_composed_on_a_scratch_document_and_the_page_is_untouched(
    minted: dict,
) -> None:
    """A library operation, not a document write: the author's page is exactly as it was."""
    tools = minted["tools"]
    page = tools.web_doc["pages"][0]

    assert page["nodes"]["root"]["children"] == []
    assert tools.web_doc["assets"] == {}
    assert tools.web_doc == _empty_doc()


def test_the_seller_mark_is_the_kits_own_logo_and_a_light_surface_variant_wins(
    registry: FakeRegistry, minted: dict
) -> None:
    """A reversed mark on a white strip is the defect `logo_policy` was written about, so the
    full-colour variant wins even though the kit lists the reversed one first."""
    header = registry.mint_calls[0]["html"]

    assert f'src="/asset-store/{SELLER_DIGEST}"' in header
    assert registry.mint_calls[0]["composition"]["seller_logo_asset_id"] == "logo_full"


def test_the_shells_are_bound_to_the_kit_that_releases_them(
    registry: FakeRegistry, minted: dict
) -> None:
    for call in registry.mint_calls:
        assert call["source_kit_id"] == "brand_kit_1"
        assert call["source_kit_version"] == 3


def test_the_real_render_passes_the_real_shape_gate(tmp_path: Path) -> None:
    """The two halves, joined — and the test that has to exist.

    The durable file checks the gate against a hand-written rendering; this checks it against the
    one the ENGINE actually produced, sanitized exactly as the mint sanitizes it. Without this,
    the two halves can each be right and the pair still broken: on the first live walk the footer's
    legal links were composed as inline anchors, and `inline.rs` drops `class` from an inline
    `<a>` — so the real footer arrived at the real gate carrying links with no marker on them and
    would have been refused as an escape route, while every isolated test passed.
    """
    from lumen_api.fragments import sanitize_fragment_html
    from lumen_api.fragments.campaign_shell import assert_campaign_shell_shape

    registry = FakeRegistry(
        tmp_path,
        legal_html=(
            '<section><a href="/privacy">Privacy Policy</a><a href="/terms">Terms</a></section>'
        ),
    )
    tools = _tools(tmp_path, registry)

    assert json.loads(tools.mint_campaign_shells())["status"] == "ok"

    for call in registry.mint_calls:
        sanitized = sanitize_fragment_html(call["html"], rehosted={}).html
        assert_campaign_shell_shape(call["role"], sanitized)
    # And the footer really does carry the two legal links through it.
    footer = sanitize_fragment_html(registry.mint_calls[1]["html"], rehosted={}).html
    assert footer.count(f'class="{MARK_LEGAL}') == 2


def test_the_compiled_styling_travels_with_the_shell(registry: FakeRegistry, minted) -> None:
    """A fragment's CSS is outside the page's utility scan (the W7 seal), so a shell minted with
    an empty stylesheet would look right in the editor and publish naked."""
    css = registry.mint_calls[0]["css"]

    assert ".max-h-8" in css
    assert "--color-primary" in css


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_a_turn_with_no_brand_kit_refuses_rather_than_inventing_the_sellers_chrome(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    tools = _tools(tmp_path, registry, brand_kit={})

    result = json.loads(tools.mint_campaign_shells())

    assert result["error_code"] == "shell.no_brand_kit"
    assert registry.mint_calls == []


def test_a_kit_with_no_usable_logo_refuses_by_name(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The seller's mark is the kit's own logo — never refetched, never redrawn. With none, the
    tool says so instead of composing a header with a hole where the brand goes."""
    kit = _brand_kit()
    kit["assets"]["logos"] = {}
    tools = _tools(tmp_path, registry, brand_kit=kit)

    result = json.loads(tools.mint_campaign_shells())

    assert result["error_code"] == "shell.no_seller_mark"
    assert registry.mint_calls == []


def test_a_logo_whose_record_is_not_in_this_turns_manifest_is_not_named(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    """The record is what the scratch document needs to render the mark at all; naming an asset
    we cannot resolve would be an engine rejection dressed as a shell."""
    tools = _tools(tmp_path, registry, brand_kit_assets={})

    result = json.loads(tools.mint_campaign_shells())

    assert result["error_code"] == "shell.no_seller_mark"


def test_no_registry_means_no_shells_and_says_so(tmp_path: Path) -> None:
    tools = _tools(tmp_path, None)

    result = json.loads(tools.mint_campaign_shells())

    assert result["error_code"] == "cloned_section.registry_unavailable"


# --------------------------------------------------------------------------- #
# The shells and the rest of the library
# --------------------------------------------------------------------------- #


def test_a_composed_shell_is_never_planted_on_a_recreated_page(tmp_path: Path) -> None:
    """The recreate is "every released clone of that page, in source order, nothing added". A
    shell came off no page, so it is not one of them."""
    registry = FakeRegistry(tmp_path)
    registry.add("frag_00000000000000a1", role="nav", label="Nav", index=0)
    registry.add("frag_00000000000000a2", role="hero", label="Hero", index=1)
    registry.add(
        "frag_00000000000000b1",
        role=CAMPAIGN_SHELL_HEADER,
        label="Campaign header",
        index=0,
        composed=COMPOSED_CAMPAIGN_SHELL,
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["status"] == "ok"
    assert [entry["fragment_id"] for entry in result["pinned"]] == [
        "frag_00000000000000a1",
        "frag_00000000000000a2",
    ]


def test_a_shell_does_not_make_a_single_page_workspace_look_ambiguous(tmp_path: Path) -> None:
    """A shell's own `page_url` is not a page. Without the exclusion, owning shells would make
    every whole-page recreate refuse as ambiguous — a regression bought with a feature."""
    registry = FakeRegistry(tmp_path)
    registry.add("frag_00000000000000a1", role="nav", label="Nav", index=0)
    registry.add(
        "frag_00000000000000b1",
        role=CAMPAIGN_SHELL_FOOTER,
        label="Campaign footer",
        index=0,
        composed=COMPOSED_CAMPAIGN_SHELL,
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.recreate_cloned_page())

    assert result["status"] == "ok"


def test_the_picker_tells_a_shell_from_the_clients_own_footer(tmp_path: Path) -> None:
    registry = FakeRegistry(tmp_path)
    registry.add("frag_00000000000000a4", role="footer", label="Footer — About Careers", index=3)
    registry.add(
        "frag_00000000000000b2",
        role=CAMPAIGN_SHELL_FOOTER,
        label="Campaign footer — Insight Health",
        index=0,
        composed=COMPOSED_CAMPAIGN_SHELL,
    )
    tools = _tools(tmp_path, registry)

    rows = {
        row["fragment_id"]: row
        for row in json.loads(tools.search_cloned_sections())["results"]
    }

    assert rows["frag_00000000000000b2"]["composed"] == COMPOSED_CAMPAIGN_SHELL
    assert "not lifted off the client's site" in rows["frag_00000000000000b2"]["composed_note"]
    assert "composed" not in rows["frag_00000000000000a4"]


# --------------------------------------------------------------------------- #
# Fix round — the review's seam and honesty findings, pinned
# --------------------------------------------------------------------------- #


def test_the_real_render_annotates_through_the_real_slot_annotator(tmp_path: Path) -> None:
    """Fix-round I5 — the §4 class of gap, one seam over. The gate test joins render+gate; this
    joins render+ANNOTATOR, which is equally class-dependent (`inline.rs` bit the footer's links
    on exactly this): a `<span>` class drop would raise `fragment.slot_selector_unmatched` in
    production while both isolated suites stayed green."""
    from lumen_api.fragments import sanitize_fragment_html
    from lumen_api.fragments.campaign_shell import campaign_shell_slots
    from lumen_api.fragments.slots import annotate_fragment_slots

    registry = FakeRegistry(tmp_path)
    tools = _tools(tmp_path, registry)

    assert json.loads(tools.mint_campaign_shells())["status"] == "ok"

    for call in registry.mint_calls:
        sanitized = sanitize_fragment_html(call["html"], rehosted={}).html
        annotated = annotate_fragment_slots(
            sanitized, list(campaign_shell_slots(call["role"]))
        )
        manifest = annotated.slot_manifest
        if call["role"] == CAMPAIGN_SHELL_HEADER:
            assert {key: entry["kind"] for key, entry in manifest.items()} == {
                "prepared_for": "text",
                "target_logo": "image",
                "cta_href": "href",
                "cta_label": "text",
            }
            assert manifest["target_logo"]["fallback"] == COBRAND_DIGEST
        else:
            assert manifest == {}


def test_the_evidence_read_is_scoped_to_the_turns_kit(minted: dict) -> None:
    """Fix-round I3, the tool half: the legal-link evidence read names THIS kit, so another
    brand's footer can never supply the links in a multi-brand workspace."""
    registry = minted["tools"]._cloned_section_registry()
    assert registry.legal_kit_ids == ["brand_kit_1"]


def test_a_foreign_hosted_legal_link_is_dropped_and_said(tmp_path: Path) -> None:
    """Fix-round C1, the honesty half: a legal-looking link on a third party's host is dropped —
    and the tool SAYS so, because "found none" would be a lie about a footer whose policy is
    genuinely hosted elsewhere."""
    registry = FakeRegistry(
        tmp_path,
        legal_html=(
            '<section><a href="https://trustarc.example/privacy-certified">Privacy'
            "</a></section>"
        ),
    )
    tools = _tools(tmp_path, registry)

    result = json.loads(tools.mint_campaign_shells())

    assert result["status"] == "ok"
    assert result["legal_links"] == []
    assert result["legal_links_dropped"] == ["https://trustarc.example/privacy-certified"]
    assert "different host" in result["legal_links_dropped_note"]
    # And the empty footer is still said to be empty, clean rather than broken.
    assert "legal_links_note" in result


def test_an_only_inverse_mark_kit_composes_but_says_so(tmp_path: Path) -> None:
    """Fix-round M4: a kit holding ONLY light/reversed logo variants still gets its shells (a
    mark the client owns beats none), but the tool says the mark was drawn for dark surfaces so
    a human reviews the header before release."""
    registry = FakeRegistry(tmp_path)
    kit = _brand_kit()
    kit["assets"]["logos"]["primary"]["variants"] = [
        {"name": "reversed", "color_mode": "reversed", "asset_id": "logo_rev"}
    ]
    tools = _tools(tmp_path, registry, brand_kit=kit)

    result = json.loads(tools.mint_campaign_shells())

    assert result["status"] == "ok"
    assert "seller_mark_note" in result
    assert "DARK surfaces" in result["seller_mark_note"]


def test_a_full_colour_mark_carries_no_dark_surface_warning(minted: dict) -> None:
    """The note is about the inverse-only kit, never noise on a healthy one."""
    assert "seller_mark_note" not in minted["result"]
