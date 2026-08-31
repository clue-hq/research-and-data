"""The ABM assembly contract (clone-fidelity F4.2, rulings R24-1…R24-6).

F4.1 minted the shells. This is what an ABM page is MADE of: the released campaign shells as
chrome (header first, footer last), a personalized hero pinned slot-bound, and token-lawful new
sections under the Grammar Audit. The walk itself — the tool, its refusals, what it pins where —
is pinned against the real engine in ``apps/agent_runtime/tests/test_web_abm_assembly.py``. This
file is the durable half:

* **The contract is a module, not a tool.** ``lumen_api.fragments.abm_page`` holds the account
  markers, the shell binding map, the escape-route role set, the shell picker and the ``abm_``
  convention — one place, so the walk and the review both read the same law.
* **Personalization is MARKER-BOUND, never baked** (ruling R24-2). The assembled page is a
  TEMPLATE: its slots carry ``{{account.name}}`` / ``{{account.logo}}`` / ``{{account.domain}}``,
  which the F1.4 derive path substitutes per account. Proven here through the REAL derive route
  over a REAL minted shell, not by asserting the shape of a dict.
* **An empty target logo is CORRECT, permanently** (the never-synthesize register). An account we
  hold no logo for derives to the transparent pixel: no placeholder words, no invented mark.
* **No relationship claims** (ruling R24-5). The shells' static text says "Prepared for" and
  never "partner", "trusted by" or "customer" — and because only the NAME is a slot, no binding
  can add one.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F4.1
neighbour.
"""

from __future__ import annotations

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import (
    CAMPAIGN_SHELL_FOOTER,
    CAMPAIGN_SHELL_HEADER,
    COBRAND_PLACEHOLDER_PNG,
    SlotSpec,
    compose_campaign_footer,
    compose_campaign_header,
    create_web_fragment,
    read_web_fragment,
    set_web_fragment_status,
)
from lumen_api.fragments.abm_page import (
    ABM_SECTION_ID_PREFIX,
    ACCOUNT_DOMAIN_MARKER,
    ACCOUNT_LOGO_MARKER,
    ACCOUNT_NAME_MARKER,
    ESCAPE_ROUTE_ROLES,
    ACCOUNT_MARKERS,
    RELATIONSHIP_CLAIM_WORDS,
    AbmAssemblyRefused,
    account_slot_binding,
    is_abm_section_id,
    newest_released_shell,
    shell_slot_bindings,
    template_markers,
)
from lumen_api.fragments.campaign_shell import (
    COBRAND_PLACEHOLDER_ASSET_ID,
    COMPOSED_CAMPAIGN_SHELL,
    MARK_PREPARED_FOR,
    MARK_TARGET_LOGO,
)

import hashlib

COBRAND_DIGEST = hashlib.sha256(COBRAND_PLACEHOLDER_PNG).hexdigest()
SELLER_DIGEST = "a" * 64

SHELL_CSS = ".max-h-8 { max-height: 2rem } .bg-primary { background: var(--color-primary) }"

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


# --------------------------------------------------------------------------- #
# The pure contract
# --------------------------------------------------------------------------- #


def test_the_shell_bindings_are_the_ruled_account_markers() -> None:
    """R24-2: the header's per-account slots carry the markers the F1.4 derive substitutes."""
    header = shell_slot_bindings(CAMPAIGN_SHELL_HEADER)

    assert header["prepared_for"] == {"text": ACCOUNT_NAME_MARKER}
    assert header["target_logo"] == {"text": ACCOUNT_LOGO_MARKER}
    # The CTA is the CAMPAIGN's, not the account's — unbound unless the caller names it.
    assert "cta_href" not in header and "cta_label" not in header
    # The footer has nothing per-account (R23-2, read literally).
    assert shell_slot_bindings(CAMPAIGN_SHELL_FOOTER) == {}


def test_a_named_cta_rides_the_same_bindings_and_may_carry_a_marker() -> None:
    bound = shell_slot_bindings(
        CAMPAIGN_SHELL_HEADER,
        cta_href="https://{{account.domain}}/demo",
        cta_label="Book a walkthrough",
    )

    assert bound["cta_href"] == {"text": "https://{{account.domain}}/demo"}
    assert bound["cta_label"] == {"text": "Book a walkthrough"}


def test_an_image_slot_marker_rides_as_text_so_the_derive_can_substitute_it() -> None:
    """The one deliberate exception to kind-tagging, and the whole of R24-2's mechanism.

    An ``image`` slot's AUTHORED value is an asset id, but ``{{account.logo}}`` is not one — it is
    a template the derive resolves into an asset (``derive.rs``'s ``SlotBinding::Asset`` arm).
    Tagged as an asset it would be an invalid id; tagged as text it substitutes.
    """
    assert account_slot_binding("target_logo", "image", ACCOUNT_LOGO_MARKER) == {
        "text": ACCOUNT_LOGO_MARKER
    }
    # A real asset id still binds as an asset — the exception is about markers, not about images.
    assert account_slot_binding("target_logo", "image", "asset_123") == {"asset": "asset_123"}
    # And a plain string on a text slot is unremarkable.
    assert account_slot_binding("headline", "text", "Hello") == {"text": "Hello"}
    assert account_slot_binding("cta_href", "href", "https://x.example/") == {
        "text": "https://x.example/"
    }


def test_a_marker_on_a_visibility_slot_is_refused_rather_than_silently_dropped() -> None:
    """``derive.rs``: assets and visibility flags are authored, not templated. A boolean has
    nothing to substitute, so a marker there would simply never bind — a silent nothing."""
    with pytest.raises(AbmAssemblyRefused) as refusal:
        account_slot_binding("show_badge", "visibility", ACCOUNT_NAME_MARKER)

    assert refusal.value.code == "abm.untemplatable_slot"
    assert "show_badge" in refusal.value.message


def test_a_visibility_slot_still_takes_a_boolean() -> None:
    assert account_slot_binding("show_badge", "visibility", True) == {"visible": True}


def test_a_marker_the_derive_cannot_substitute_is_refused_by_name() -> None:
    """Only ``account.*`` reaches a fragment slot: ``account_values()`` is the whole namespace
    the F1.4 derive builds, so a ``{{brand.name}}`` would be carried onto a published page
    verbatim (or drop the node's whole slot map, LUMW0607)."""
    with pytest.raises(AbmAssemblyRefused) as refusal:
        account_slot_binding("headline", "text", "Welcome, {{brand.name}}")

    assert refusal.value.code == "abm.unknown_marker"
    assert "{{brand.name}}" in refusal.value.message


def test_the_account_markers_are_the_three_the_derive_substitutes() -> None:
    """Renamed from "guaranteed…every account has" (fix-round M2): `account_values()` emits
    domain/logo only when the account carries them — unbound markers fall back gracefully."""
    assert ACCOUNT_MARKERS == (
        ACCOUNT_NAME_MARKER,
        ACCOUNT_DOMAIN_MARKER,
        ACCOUNT_LOGO_MARKER,
    )
    # An account's own `data` entries reach the derive as `account.<key>` too, so they are
    # allowed — just not guaranteed.
    assert account_slot_binding("stat", "text", "{{account.beds}}") == {
        "text": "{{account.beds}}"
    }


def test_template_markers_reads_whole_and_embedded_markers() -> None:
    assert template_markers("{{account.name}}") == ("account.name",)
    assert template_markers("See the {{account.name}} walkthrough at {{account.domain}}") == (
        "account.name",
        "account.domain",
    )
    assert template_markers("no markers here") == ()


# --------------------------------------------------------------------------- #
# The shell picker (ruling R24-1 / the I6 interim law)
# --------------------------------------------------------------------------- #


def _shell_row(fragment_id: str, role: str, created_at: str) -> dict:
    return {
        "fragment_id": fragment_id,
        "section_role": role,
        "label": f"Campaign {role}",
        "composed": "campaign_shell",
        "created_at": created_at,
    }


def test_the_newest_released_shell_wins_and_the_siblings_are_named() -> None:
    """Shells carry no supersession (T23 review I6). Until the founder rules the lineage
    semantics, the picker is deterministic and SAYS a sibling exists rather than choosing in
    silence."""
    rows = [
        _shell_row("frag_old", CAMPAIGN_SHELL_HEADER, "2026-08-01T00:00:00Z"),
        _shell_row("frag_new", CAMPAIGN_SHELL_HEADER, "2026-08-20T00:00:00Z"),
        _shell_row("frag_mid", CAMPAIGN_SHELL_HEADER, "2026-08-10T00:00:00Z"),
        _shell_row("frag_foot", CAMPAIGN_SHELL_FOOTER, "2026-08-02T00:00:00Z"),
    ]

    chosen, siblings = newest_released_shell(rows, CAMPAIGN_SHELL_HEADER)

    assert chosen["fragment_id"] == "frag_new"
    assert siblings == ["frag_mid", "frag_old"]


def test_the_picker_is_deterministic_when_two_shells_share_a_timestamp() -> None:
    rows = [
        _shell_row("frag_aaa", CAMPAIGN_SHELL_HEADER, "2026-08-20T00:00:00Z"),
        _shell_row("frag_zzz", CAMPAIGN_SHELL_HEADER, "2026-08-20T00:00:00Z"),
    ]

    chosen, siblings = newest_released_shell(rows, CAMPAIGN_SHELL_HEADER)
    again, _ = newest_released_shell(list(reversed(rows)), CAMPAIGN_SHELL_HEADER)

    assert chosen["fragment_id"] == again["fragment_id"] == "frag_zzz"
    assert siblings == ["frag_aaa"]


def test_a_harvested_row_is_never_mistaken_for_a_shell() -> None:
    """The `composed` marker decides, never the role name: a harvested band whose role happened
    to read `campaign_header` is not a shell this workspace composed."""
    rows = [
        {
            "fragment_id": "frag_harvest",
            "section_role": CAMPAIGN_SHELL_HEADER,
            "composed": None,
            "created_at": "2026-08-25T00:00:00Z",
        },
        _shell_row("frag_shell", CAMPAIGN_SHELL_HEADER, "2026-08-01T00:00:00Z"),
    ]

    chosen, siblings = newest_released_shell(rows, CAMPAIGN_SHELL_HEADER)

    assert chosen["fragment_id"] == "frag_shell"
    assert siblings == []


def test_no_shell_of_that_role_answers_none_rather_than_something_else() -> None:
    assert newest_released_shell([], CAMPAIGN_SHELL_HEADER) == (None, [])


def test_the_pick_is_scoped_to_one_brand_when_the_caller_knows_which() -> None:
    """Brand B's shell is brand B's chrome. Wearing it on brand A's account page dresses the page
    as the wrong company — the same defect T23's fix round closed for the legal-link evidence."""
    mine = _shell_row("frag_mine", CAMPAIGN_SHELL_HEADER, "2026-08-01T00:00:00Z")
    mine["source_kit_id"] = "kit_a"
    theirs = _shell_row("frag_theirs", CAMPAIGN_SHELL_HEADER, "2026-08-20T00:00:00Z")
    theirs["source_kit_id"] = "kit_b"

    chosen, siblings = newest_released_shell(
        [mine, theirs], CAMPAIGN_SHELL_HEADER, kit_id="kit_a"
    )

    # Newest loses to same-brand: scope first, recency second.
    assert chosen["fragment_id"] == "frag_mine"
    assert siblings == []
    # A brand with no shell of its own gets NOTHING, not somebody else's.
    assert newest_released_shell([theirs], CAMPAIGN_SHELL_HEADER, kit_id="kit_a") == (None, [])
    # Unscoped is workspace-wide — the honest answer when the caller does not know the brand.
    unscoped, _ = newest_released_shell([mine, theirs], CAMPAIGN_SHELL_HEADER)
    assert unscoped["fragment_id"] == "frag_theirs"


# --------------------------------------------------------------------------- #
# The escape-route roles and the abm_ convention (rulings R24-1 / R24-3)
# --------------------------------------------------------------------------- #


def test_the_cloned_nav_and_footer_are_escape_routes_on_an_abm_page() -> None:
    assert "nav" in ESCAPE_ROUTE_ROLES
    assert "footer" in ESCAPE_ROUTE_ROLES
    # The shells' own roles are not escape routes — they ARE the answer.
    assert CAMPAIGN_SHELL_HEADER not in ESCAPE_ROUTE_ROLES
    assert CAMPAIGN_SHELL_FOOTER not in ESCAPE_ROUTE_ROLES
    # A hero, a proof band, a testimonial: reusable on an ABM page, they carry no navigation.
    for role in ("hero", "proof", "testimonial", "security", "other"):
        assert role not in ESCAPE_ROUTE_ROLES


def test_the_new_section_convention_is_a_prefix_a_machine_can_read() -> None:
    """The engine's id charset has no ``-``, so the plan's ``abm-*`` family reads as ``abm_``."""
    assert ABM_SECTION_ID_PREFIX == "abm_"
    assert is_abm_section_id("abm_peer_proof")
    assert not is_abm_section_id("sec_1a2b3c4d")
    assert not is_abm_section_id("proof_band")
    # The wrapper ids a pinned clone gets are `sec_<8 hex>`, so the two families cannot collide.
    assert not is_abm_section_id("sec_abm_hero")


# --------------------------------------------------------------------------- #
# Relationship-language guardrails (ruling R24-5) — the structural half
# --------------------------------------------------------------------------- #


def test_the_shells_static_text_claims_no_relationship_that_does_not_exist() -> None:
    """A campaign page is a pitch, not a case study. "Prepared for" is the whole of what the
    shell says about the relationship, and it is ARTIFACT text — only the name is a slot, so no
    binding (agent, derive or human) can turn it into "Partnering with Acme"."""
    header = compose_campaign_header(
        seller_name="Insight Health",
        seller_logo_asset_id="logo_full",
        cobrand_asset_id=COBRAND_PLACEHOLDER_ASSET_ID,
    )
    footer = compose_campaign_footer(
        seller_name="Insight Health", seller_logo_asset_id="logo_full"
    )

    for markup in (header, footer):
        lowered = markup.lower()
        for word in RELATIONSHIP_CLAIM_WORDS:
            assert word not in lowered, word
    assert "Prepared for " in header


def test_the_relationship_vocabulary_names_the_claims_the_ruling_names() -> None:
    for word in ("partner", "partnership", "customer", "trusted by", "client of"):
        assert word in RELATIONSHIP_CLAIM_WORDS, word


# --------------------------------------------------------------------------- #
# Red case 6 — the assembled TEMPLATE derives per account, and an empty logo is clean
# --------------------------------------------------------------------------- #
#
# T23 proved one shell derives. This proves the ASSEMBLY derives: header shell, a hero clone
# bound to account markers, footer shell — one document, three fragment nodes, one derive.


def _registry(workspace_id: str, storage: FsStorage, cache_dir):
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


def _rendered_header() -> str:
    return (
        '<section id="sec_campaign_header" class="w-full border-b border-border bg-light">'
        '<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 '
        'px-6 py-4"><div class="flex items-center gap-3">'
        f'<img src="/asset-store/{SELLER_DIGEST}" alt="Insight Health" loading="lazy" '
        'class="lumen-shell-seller-mark max-h-8 w-auto">'
        f'<img src="/asset-store/{COBRAND_DIGEST}" alt="" loading="lazy" '
        f'class="{MARK_TARGET_LOGO} max-h-8 w-auto">'
        '<div data-tv="body" class="text-sm text-muted"><p>Prepared for '
        f'<span class="{MARK_PREPARED_FOR}">your team</span></p></div></div>'
        '<a href="#contact" data-lumen-container-link="" '
        'class="lumen-shell-cta inline-flex items-center rounded-button bg-primary px-5 py-2">'
        '<div data-tv="body" class="text-sm font-semibold text-inverse"><p>'
        '<span class="lumen-shell-cta-label">Book a walkthrough</span></p></div></a>'
        "</div></section>"
    )


def _rendered_footer() -> str:
    return (
        '<section id="sec_campaign_footer" class="w-full border-t border-border bg-light">'
        '<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 '
        'px-6 py-6">'
        f'<img src="/asset-store/{SELLER_DIGEST}" alt="Insight Health" loading="lazy" '
        'class="lumen-shell-seller-mark max-h-6 w-auto">'
        '<div data-tv="body" class="text-xs text-muted"><p>© Insight Health. '
        "All rights reserved.</p></div></div></section>"
    )


#: A harvested hero, as the segmentation would hand one over: a headline and a paragraph, whose
#: slots the annotator finds by the selectors the mint declares.
HERO_HTML = (
    '<section id="sec_hero" class="py-section">'
    '<h1 class="hero-headline">Clinical notes, written for you</h1>'
    '<p class="hero-subhead">One record, every clinician.</p>'
    "</section>"
)
HERO_SLOTS = (
    SlotSpec(selector=".hero-headline", key="headline", kind="text"),
    SlotSpec(selector=".hero-subhead", key="subhead", kind="text"),
)


def _released_shell(registry, role: str) -> str:
    minted = registry.mint_campaign_shell(
        role=role,
        html=_rendered_header() if role == CAMPAIGN_SHELL_HEADER else _rendered_footer(),
        css=SHELL_CSS,
        label=f"Campaign {role} — Insight Health",
        composition={"seller_name": "Insight Health"},
    )
    set_web_fragment_status(
        workspace_id=registry.workspace_id,
        fragment_id=minted["fragment_id"],
        status="approved",
    )
    return minted["fragment_id"]


def _released_hero(workspace_id: str, storage: FsStorage) -> str:
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=HERO_HTML,
        css=".py-section { padding: 4rem 0 }",
        rehosted={},
        source_url="https://insight.example/",
        section_role="hero",
        slots=HERO_SLOTS,
        label="Hero — clinical notes",
        provenance={"page_url": "https://insight.example/", "section_index": 1},
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )
    return row["fragment_id"]


def _assembled_doc(document_id: str, header: str, hero: str, footer: str) -> dict:
    """The page the F4.2 walk builds: header shell first, hero, footer shell last."""

    def pin(node_id: str, fragment_id: str, slots: dict) -> dict:
        return {
            "id": node_id,
            "kind": "fragment",
            "fragment_id": fragment_id,
            "slots": slots,
            "classes": "",
        }

    def wrap(section_id: str, node_id: str) -> dict:
        return {
            "id": section_id,
            "kind": "section",
            "tag": "section",
            "classes": "w-full",
            "children": [node_id],
        }

    return {
        "schema_version": 1,
        "id": document_id,
        "title": "ABM page",
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
                        "children": ["sec_h", "sec_hero_pin", "sec_f"],
                    },
                    **{
                        node["id"]: node
                        for node in (
                            wrap("sec_h", "frg_h"),
                            pin("frg_h", header, shell_slot_bindings(CAMPAIGN_SHELL_HEADER)),
                            wrap("sec_hero_pin", "frg_hero"),
                            pin(
                                "frg_hero",
                                hero,
                                {
                                    "headline": account_slot_binding(
                                        "headline",
                                        "text",
                                        "Clinical notes, written for {{account.name}}",
                                    )
                                },
                            ),
                            wrap("sec_f", "frg_f"),
                            pin("frg_f", footer, shell_slot_bindings(CAMPAIGN_SHELL_FOOTER)),
                        )
                    },
                },
            }
        ],
        "assets": {},
        "custom_css": "",
    }


@pytest.fixture()
def abm_client(tmp_path, design_storage: FsStorage):
    from conftest import make_client

    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_the_assembled_page_is_a_template_that_derives_per_account(
    abm_client, workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """R24-2 end to end: ONE document, chrome + hero, personalized by the real derive route —
    and every marker still on the page afterwards, so it is re-derivable rather than baked."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.campaign_shell_placeholder()
    header = _released_shell(registry, CAMPAIGN_SHELL_HEADER)
    footer = _released_shell(registry, CAMPAIGN_SHELL_FOOTER)
    hero = _released_hero(workspace_id, design_storage)

    logo_asset_id = abm_client.post(
        "/assets",
        files={"file": ("acme.png", TINY_PNG, "image/png")},
        data={"label": "Acme logo", "kind": "raster_image"},
    ).json()["asset"]["id"]
    HybridRepository(workspace_id=workspace_id).create_document(
        _assembled_doc("doc_abm_assembled", header, hero, footer), doc_kind="web"
    )
    account = abm_client.post(
        "/web/accounts",
        json={"name": "Acme Health", "domain": "acme.example", "logo_asset_id": logo_asset_id},
    ).json()

    derived = abm_client.post(
        "/documents/doc_abm_assembled/web/derive", json={"account_id": account["account_id"]}
    )
    assert derived.status_code == 200, derived.text
    html = abm_client.get(
        f"/documents/{derived.json()['document_id']}/web/render"
    ).json()["html"]

    # Chrome first and last, the hero between them.
    assert html.index("sec_campaign_header") < html.index("Clinical notes, written for Acme")
    assert html.index("Clinical notes, written for Acme") < html.index("sec_campaign_footer")
    # The account, in all three of its shapes.
    assert ">Acme Health</span>" in html
    assert "Clinical notes, written for Acme Health" in html
    digest = HybridRepository(workspace_id=workspace_id).require_asset_record(logo_asset_id)[
        "asset"
    ]["media"]["digest"]["value"]
    assert f"/asset-store/{digest}" in html
    # Re-derivable: the markers are still there for the next account.
    for key in ("prepared_for", "target_logo", "headline"):
        assert f'data-lumen-slot="{key}"' in html
    # And the ONE anchor rule survives personalization — chrome plus hero, still one CTA.
    assert html.count("<a ") == 1


def test_an_account_with_no_logo_derives_a_clean_page_not_a_broken_one(
    abm_client, workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The never-synthesize register, on the assembled page: empty is CORRECT. No placeholder
    words, no grey box, no invented mark — the transparent pixel and nothing else."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.campaign_shell_placeholder()
    header = _released_shell(registry, CAMPAIGN_SHELL_HEADER)
    footer = _released_shell(registry, CAMPAIGN_SHELL_FOOTER)
    hero = _released_hero(workspace_id, design_storage)
    HybridRepository(workspace_id=workspace_id).create_document(
        _assembled_doc("doc_abm_nologo", header, hero, footer), doc_kind="web"
    )
    account = abm_client.post(
        "/web/accounts", json={"name": "Acme Health", "domain": "acme.example"}
    ).json()

    derived = abm_client.post(
        "/documents/doc_abm_nologo/web/derive", json={"account_id": account["account_id"]}
    )
    assert derived.status_code == 200, derived.text
    html = abm_client.get(
        f"/documents/{derived.json()['document_id']}/web/render"
    ).json()["html"]

    assert f'/asset-store/{COBRAND_DIGEST}" alt=""' in html
    for placeholder in ("Logo", "logo here", "placeholder", "Your logo", "?"):
        assert f">{placeholder}<" not in html
    # The rest of the page personalized anyway.
    assert "Clinical notes, written for Acme Health" in html
    # And no relationship claim reached the rendered page.
    lowered = html.lower()
    for word in RELATIONSHIP_CLAIM_WORDS:
        assert word not in lowered, word


def test_the_stored_shell_artifacts_carry_no_relationship_claim(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Not the composer's output — the BYTES that ship, after the sanitizer and the scoper."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.campaign_shell_placeholder()
    for role in (CAMPAIGN_SHELL_HEADER, CAMPAIGN_SHELL_FOOTER):
        fragment_id = _released_shell(registry, role)
        stored = read_web_fragment(
            design_storage, workspace_id=workspace_id, fragment_id=fragment_id
        )
        lowered = stored.html.lower()
        for word in RELATIONSHIP_CLAIM_WORDS:
            assert word not in lowered, (role, word)


# --------------------------------------------------------------------------- #
# Fix round (T24 review I2) — R24-7's API half, pinned on the REAL registry
# --------------------------------------------------------------------------- #


def test_resolve_insertable_reports_composed_for_a_shell_and_none_for_a_clone(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The agent-side pin doors carry `composed` from THIS read (R24-7). Every agent test fakes
    the registry, so without this assertion the real `resolve_insertable` could stop returning
    the key and every suite would stay green while production regressed to the N6 defect."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    shell_id = _released_shell(registry, CAMPAIGN_SHELL_HEADER)
    hero_id = _released_hero(workspace_id, design_storage)

    shell = registry.resolve_insertable(shell_id)
    hero = registry.resolve_insertable(hero_id)

    assert shell["composed"] == COMPOSED_CAMPAIGN_SHELL
    assert hero["composed"] is None
