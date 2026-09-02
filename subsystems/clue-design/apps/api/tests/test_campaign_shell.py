"""The campaign shell fragments (clone-fidelity F4.1, rulings R23-1/2/3).

An ABM page does not wear the client's global navigation — every link on it is a way off the one
page written for this account. It wears a page-local shell: a header with the seller's mark, the
words "Prepared for <account>", the target's own logo when we hold one, and exactly ONE call to
action; and a footer with the seller's mark, a copyright line and their legal links.

The agent-side walk — the scratch document, the engine's own render, which markup reaches the
mint — is pinned against the real engine in
``apps/agent_runtime/tests/test_web_campaign_shells.py``. This file is about the durable half:

* **The identical mint path.** A shell goes through the same sanitizer, the same fail-closed
  reference gate and the same CSS scoper a harvested clone does. There is no relaxed door for
  markup we composed ourselves.
* **The slot contract** (R23-2), exactly: the header declares ``prepared_for``, ``target_logo``,
  ``cta_href``, ``cta_label`` and nothing else; the footer declares none.
* **The campaign-shell shape** (R23-3, demoted to ADVICE by founder ruling R-F5-8): an extra
  link, a nav or a menu is still DETECTED at the mint and handed back as a note in ``advice`` —
  it is poor practice on a campaign page, not a refusal.
* **Empty is correct.** An unbound target logo shows no second mark at all, and a footer with no
  discoverable legal links has no legal block.
* **Born ``draft``, and content-addressed.** Released by the human who approves the brand kit;
  re-minted, it converges.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F3.1 neighbour.
"""

from __future__ import annotations

import hashlib

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import (
    CAMPAIGN_SHELL_FOOTER,
    CAMPAIGN_SHELL_HEADER,
    CAMPAIGN_SHELL_SOURCE_URL,
    COBRAND_PLACEHOLDER_ASSET_ID,
    COBRAND_PLACEHOLDER_PNG,
    COMPOSED_CAMPAIGN_SHELL,
    DEFAULT_CTA_HREF,
    DEFAULT_CTA_LABEL,
    DEFAULT_PREPARED_FOR,
    FragmentRefused,
    LegalLink,
    SlotSpec,
    assert_campaign_shell_shape,
    campaign_shell_shape_notes,
    campaign_shell_slots,
    compose_campaign_footer,
    compose_campaign_header,
    create_web_fragment,
    discover_legal_links,
    read_web_fragment,
    set_web_fragment_status,
)
from lumen_api.fragments.campaign_shell import (
    MARK_CTA,
    MARK_CTA_LABEL,
    MARK_LEGAL,
    MARK_PREPARED_FOR,
    MARK_TARGET_LOGO,
)

PAGE = "https://insight.example/"

SELLER_DIGEST = "a" * 64
COBRAND_DIGEST = hashlib.sha256(COBRAND_PLACEHOLDER_PNG).hexdigest()

#: What the ENGINE's delivery render of the composed header looks like: node classes preserved,
#: `data-asset` already resolved to the artifact's own byte spelling, text nodes wrapped in
#: `data-tv` containers, the container-link rendered as a real `<a>`. Written out rather than
#: produced here so the durable half can be tested without an engine; the agent-side file proves
#: this IS the shape the engine emits.
def _rendered_header(
    *,
    cobrand_digest: str = COBRAND_DIGEST,
    prepared_for: str = DEFAULT_PREPARED_FOR,
    cta_href: str = DEFAULT_CTA_HREF,
    cta_label: str = DEFAULT_CTA_LABEL,
    extra: str = "",
) -> str:
    return (
        '<section id="sec_campaign_header" class="w-full border-b border-border bg-light"><div class="mx-auto flex max-w-6xl flex-wrap items-center '
        'justify-between gap-4 px-6 py-4"><div class="flex items-center gap-3">'
        f'<img src="/asset-store/{SELLER_DIGEST}" alt="Insight Health" loading="lazy" '
        'class="lumen-shell-seller-mark max-h-8 w-auto">'
        f'<img src="/asset-store/{cobrand_digest}" alt="" loading="lazy" '
        f'class="{MARK_TARGET_LOGO} max-h-8 w-auto">'
        '<div data-tv="body" class="text-sm text-muted"><p>Prepared for '
        f'<span class="{MARK_PREPARED_FOR}">{prepared_for}</span></p></div></div>'
        f'<a href="{cta_href}" data-lumen-container-link="" '
        f'class="{MARK_CTA} inline-flex items-center rounded-button bg-primary '
        'px-5 py-2"><div data-tv="body" class="text-sm font-semibold text-inverse"><p>'
        f'<span class="{MARK_CTA_LABEL}">{cta_label}</span></p></div></a>'
        f"{extra}</div></section>"
    )


def _rendered_footer(*, legal: str = "", extra: str = "") -> str:
    return (
        '<section id="sec_campaign_footer" class="w-full border-t border-border bg-light"><div class="mx-auto flex max-w-6xl flex-wrap items-center '
        'justify-between gap-4 px-6 py-6">'
        f'<img src="/asset-store/{SELLER_DIGEST}" alt="Insight Health" loading="lazy" '
        'class="lumen-shell-seller-mark max-h-6 w-auto">'
        '<div data-tv="body" class="text-xs text-muted"><p>© Insight Health. '
        "All rights reserved.</p></div>"
        f"{legal}{extra}</div></section>"
    )


def _legal_block(*hrefs: str) -> str:
    """The RENDERED legal block: container-links, each keeping its own marker class. An inline
    anchor would lose it (`inline.rs` drops `class` on `<a>`), which is why the composition uses
    this shape — see the agent-side file's real-render gate test."""
    anchors = "".join(
        f'<a href="{href}" data-lumen-container-link="" '
        f'class="{MARK_LEGAL} inline-flex items-center">'
        '<div data-tv="body" class="text-xs text-muted"><p>Privacy</p></div></a>'
        for href in hrefs
    )
    return f'<div class="flex flex-wrap items-center gap-4">{anchors}</div>'


SHELL_CSS = ".max-h-8 { max-height: 2rem } .bg-primary { background: var(--color-primary) }"


def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_shell_1", version: int = 3) -> dict:
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": kit_id, "version": version, "name": "Insight", "approval_status": "approved"},
        {},
        [],
        "website",
    )


def _registry(workspace_id: str, storage: FsStorage, cache_dir):
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


def _fragment(workspace_id: str, fragment_id: str) -> dict:
    return HybridRepository(workspace_id=workspace_id).require_web_fragment(fragment_id)


def _mint_header(registry, kit: dict | None = None, html: str | None = None) -> dict:
    return registry.mint_campaign_shell(
        role=CAMPAIGN_SHELL_HEADER,
        html=html if html is not None else _rendered_header(),
        css=SHELL_CSS,
        label="Campaign header — Insight Health",
        source_kit_id=(kit or {}).get("brand_kit_id"),
        source_kit_version=int(kit["version"]) if kit else None,
        composition={"seller_name": "Insight Health"},
    )


# --------------------------------------------------------------------------- #
# Red case 1 — the full sanitizer path, born draft, released by kit approval
# --------------------------------------------------------------------------- #


def test_a_header_shell_mints_through_the_full_sanitizer_path_and_is_born_draft(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The mint is not a softer door because we wrote the markup ourselves (ruling R23-1)."""
    kit = _seed_kit(workspace_id)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry, kit)

    assert minted["shell_role"] == CAMPAIGN_SHELL_HEADER
    assert minted["status"] == "draft"
    assert minted["insertable"] is False
    row = _fragment(workspace_id, minted["fragment_id"])
    assert row["section_role"] == CAMPAIGN_SHELL_HEADER
    assert row["source_kit_id"] == kit["brand_kit_id"]
    assert row["source_kit_version"] == int(kit["version"])
    assert row["source_url"] == CAMPAIGN_SHELL_SOURCE_URL
    assert row["degraded"] is False
    assert row["derived_from"] is None


def test_the_shell_sanitizer_strips_exactly_what_it_strips_from_a_harvested_clone(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """An `on*` handler and a `<script>` do not survive a shell any more than they survive a
    cloned band: the same one-time sanitizer runs, with no relaxation."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    poisoned = _rendered_header().replace(
        '<div data-tv="body" class="text-sm text-muted">',
        '<div data-tv="body" onclick="steal()" class="text-sm text-muted">'
        "<script>steal()</script>",
    )

    minted = _mint_header(registry, html=poisoned)

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert "onclick" not in stored.html
    assert "<script" not in stored.html
    assert "steal()" not in stored.html
    # And the shell is otherwise intact — stripping is not refusing.
    assert "Prepared for" in stored.html


def test_a_shell_naming_bytes_we_do_not_hold_refuses_like_any_other_fragment(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The fail-closed reference gate, unchanged: a remote image is not a shell we can keep."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    remote = _rendered_header().replace(
        f'src="/asset-store/{SELLER_DIGEST}"', 'src="https://cdn.example/logo.png"'
    )

    with pytest.raises(FragmentRefused) as refusal:
        _mint_header(registry, html=remote)

    assert refusal.value.code == "fragment.unrehosted_reference"


def test_a_released_shell_is_released_by_the_kit_approval_surface_and_then_pins(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Nothing in the mint can put a shell on a page; a human's kit approval can (R-I5).

    Through the REAL cascade, not `set_web_fragment_status` (fix-round I1): the shells bind to a
    kit that is normally ALREADY approved when they mint, so the release act is RE-approving it —
    `update_brand_kit_approval` is not transition-gated, and the version-scoped cascade then moves
    every draft fragment of that kit version, these shells included.
    """
    kit = _seed_kit(workspace_id)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = _mint_header(registry, kit)

    assert registry.list_sections()["sections"] == []

    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )

    assert _fragment(workspace_id, minted["fragment_id"])["status"] == "approved"
    resolved = registry.resolve_insertable(minted["fragment_id"])
    assert resolved["fragment_id"] == minted["fragment_id"]
    assert resolved["render"]["slot_kinds"]["prepared_for"] == "text"


# --------------------------------------------------------------------------- #
# Red case 2 — the slot manifest, and the empty logo
# --------------------------------------------------------------------------- #


def test_the_header_declares_exactly_the_ruled_slots_with_the_ruled_kinds(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry)

    manifest = minted["slot_manifest"]
    assert {key: entry["kind"] for key, entry in manifest.items()} == {
        "prepared_for": "text",
        "target_logo": "image",
        "cta_href": "href",
        "cta_label": "text",
    }
    # The defaults are the composition's own words — never a fabricated account.
    assert manifest["prepared_for"]["fallback"] == DEFAULT_PREPARED_FOR
    assert manifest["cta_href"]["fallback"] == DEFAULT_CTA_HREF
    assert manifest["cta_label"]["fallback"] == DEFAULT_CTA_LABEL


def test_the_footer_declares_no_slots_because_nothing_in_it_is_per_account(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_campaign_shell(
        role=CAMPAIGN_SHELL_FOOTER,
        html=_rendered_footer(legal=_legal_block("https://insight.example/privacy")),
        css=SHELL_CSS,
        label="Campaign footer — Insight Health",
    )

    assert minted["slot_keys"] == []
    assert minted["slot_manifest"] == {}


def test_prepared_for_marks_only_the_name_so_the_framing_cannot_be_rewritten(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """"Prepared for" is static artifact text; only the account's display name is a slot. No
    binding can turn the header into a claim of partnership (F4.2's guardrail, made
    structural)."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry)

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert 'Prepared for <span data-lumen-slot="prepared_for"' in stored.html.replace(
        f'class="{MARK_PREPARED_FOR}" ', ""
    ).replace(f' class="{MARK_PREPARED_FOR}"', "")


def test_prepared_for_substitutes_the_account_name_through_the_f14_derive_shape(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """`account_values()` hands the derive `account.name` as a Text value, and a fragment node
    reads it through a whole-value `{{account.name}}` template (derive.rs). What this pins is the
    half F4.1 owns: the slot the template lands in exists, is a text slot, and its marker is in
    the stored markup where the substitution walk looks for it."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry)

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert 'data-lumen-slot="prepared_for"' in stored.html
    assert stored.slot_manifest["prepared_for"]["kind"] == "text"
    # The account name is the WHOLE of what the slot holds, so binding "Acme Health" produces
    # "Prepared for Acme Health" and can produce nothing else.
    assert stored.slot_manifest["prepared_for"]["fallback"] == DEFAULT_PREPARED_FOR


def test_an_empty_target_logo_renders_as_nothing_at_all(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Empty is CORRECT, permanently (the never-synthesize register). The unbound co-brand slot
    is a 1×1 fully transparent pixel under a `max-h` cap: no broken image, no grey box, no
    words — and no invented logo."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry)

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert stored.slot_manifest["target_logo"]["fallback"] == COBRAND_DIGEST
    assert COBRAND_DIGEST in minted["asset_digests"]
    # The element the visitor would meet: an image with an EMPTY alt (a screen reader says
    # nothing), and no text anywhere near it standing in for a logo.
    assert f'src="/asset-store/{COBRAND_DIGEST}" alt=""' in stored.html
    for placeholder in ("logo here", "Logo", "placeholder", "Your logo"):
        assert placeholder not in stored.html


def test_the_cobrand_placeholder_is_one_transparent_pixel_in_durable_custody(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The artifact cites the digest, so the bytes have to be ours — an export walks them."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    placeholder = registry.campaign_shell_placeholder()

    assert placeholder["asset_id"] == COBRAND_PLACEHOLDER_ASSET_ID
    assert placeholder["digest"] == COBRAND_DIGEST
    assert placeholder["record"]["media"]["digest"]["value"] == COBRAND_DIGEST
    assert (
        DesignBlobStore(design_storage, workspace_id).read(COBRAND_DIGEST)
        == COBRAND_PLACEHOLDER_PNG
    )
    # Idempotent: content-addressed, so a second call is the same digest and no second blob.
    assert registry.campaign_shell_placeholder()["digest"] == COBRAND_DIGEST


# --------------------------------------------------------------------------- #
# Red case 3 — the campaign-shell shape, as ADVICE (R23-3, demoted by R-F5-8)
# --------------------------------------------------------------------------- #
#
# FOUNDER RULING R-F5-8 (2026-09-02): links are structurally free. Every detection below is
# unchanged — the same anchors are counted, the same nav/menu/second control is spotted, the same
# unmarked link is named — but the consequence is a NOTE the mint hands back in `advice`, never a
# refusal. The gate wrapper (`assert_campaign_shell_shape`) survives for the tests that pin the
# detections; no production path calls it any more.


def test_the_composed_header_carries_exactly_one_anchor_and_it_is_the_cta() -> None:
    html = compose_campaign_header(seller_name="Insight Health", seller_logo_asset_id="logo_1")

    assert html.count("<a ") == 0  # composed as a container-link; the engine renders the anchor
    assert html.count("data-href=") == 1
    assert MARK_CTA in html
    assert "<nav" not in html


def test_a_multi_anchor_header_is_a_NOTE_not_a_refusal() -> None:
    """R-F5-8, in one line: the same finding, said as a sentence."""
    with_menu = _rendered_header(extra='<a href="https://insight.example/pricing">Pricing</a>')

    notes = campaign_shell_shape_notes(CAMPAIGN_SHELL_HEADER, with_menu)

    assert notes and "anchors" in notes[0]
    assert "2" in notes[0]
    # The words the ruling chose: practice, not prohibition.
    joined = " ".join(notes).lower()
    assert "forbidden" not in joined and "refus" not in joined


def test_a_header_with_a_second_link_mints_and_says_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Not refused — noted. The mint hands the finding back in `advice` (R-F5-8)."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    with_menu = _rendered_header(extra='<a href="https://insight.example/pricing">Pricing</a>')

    minted = _mint_header(registry, html=with_menu)

    assert minted["fragment_id"]
    advice = " ".join(minted["advice"]).lower()
    assert "pricing" in advice
    assert "anchors" in advice


def test_a_header_whose_seller_mark_links_home_mints_and_says_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The classic escape route: a logo that goes to the homepage. Still detected, now advisory."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    linked_mark = _rendered_header().replace(
        f'<img src="/asset-store/{SELLER_DIGEST}"',
        f'<a href="https://insight.example/"><img src="/asset-store/{SELLER_DIGEST}"',
    ).replace('class="lumen-shell-seller-mark max-h-8 w-auto">', 'class="max-h-8 w-auto"></a>')

    minted = _mint_header(registry, html=linked_mark)

    assert minted["fragment_id"]
    assert minted["advice"]
    assert "insight.example" in " ".join(minted["advice"])


def test_a_shell_carrying_a_nav_or_a_menu_mints_and_says_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    nav = _mint_header(registry, html=_rendered_header(extra="<nav><p>Products</p></nav>"))
    assert nav["fragment_id"]
    assert any("<nav>" in note for note in nav["advice"]), nav["advice"]

    button = _mint_header(registry, html=_rendered_header(extra="<button>Menu</button>"))
    assert button["fragment_id"]
    assert any("<button>" in note for note in button["advice"]), button["advice"]


def test_a_footer_link_that_is_not_a_legal_link_mints_and_says_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    with_careers = _rendered_footer(extra='<a href="https://insight.example/careers">Careers</a>')

    minted = registry.mint_campaign_shell(
        role=CAMPAIGN_SHELL_FOOTER,
        html=with_careers,
        css=SHELL_CSS,
        label="Campaign footer",
    )

    assert minted["fragment_id"]
    assert "careers" in " ".join(minted["advice"]).lower()


def test_the_shape_notes_are_silent_on_the_lawful_shells() -> None:
    """The notes name what is off the practice; the real thing draws none."""
    assert campaign_shell_shape_notes(CAMPAIGN_SHELL_HEADER, _rendered_header()) == []
    assert campaign_shell_shape_notes(CAMPAIGN_SHELL_FOOTER, _rendered_footer()) == []
    assert (
        campaign_shell_shape_notes(
            CAMPAIGN_SHELL_FOOTER,
            _rendered_footer(
                legal=_legal_block(
                    "https://insight.example/privacy", "https://insight.example/terms"
                )
            ),
        )
        == []
    )
    # And the kept wrapper still lets them through without raising.
    assert_campaign_shell_shape(CAMPAIGN_SHELL_HEADER, _rendered_header())
    assert_campaign_shell_shape(CAMPAIGN_SHELL_FOOTER, _rendered_footer())


def test_a_footer_with_more_legal_links_than_a_legal_block_has_is_noted() -> None:
    """Three "legal" links is a nav wearing a legal block's clothes — said, not refused."""
    notes = campaign_shell_shape_notes(
        CAMPAIGN_SHELL_FOOTER,
        _rendered_footer(legal=_legal_block("/a", "/b", "/c")),
    )

    assert notes and "anchors" in notes[0]
    # The wrapper is kept for exactly this: the detections still have a raising form.
    with pytest.raises(FragmentRefused):
        assert_campaign_shell_shape(
            CAMPAIGN_SHELL_FOOTER,
            _rendered_footer(legal=_legal_block("/a", "/b", "/c")),
        )


# --------------------------------------------------------------------------- #
# Red case 4 — the footer with no legal links
# --------------------------------------------------------------------------- #


def test_a_footer_with_no_discoverable_legal_links_is_composed_without_the_block() -> None:
    html = compose_campaign_footer(
        seller_name="Insight Health", seller_logo_asset_id="logo_1", legal_links=()
    )

    assert "<a" not in html
    assert MARK_LEGAL not in html
    # And nothing stands in for the absent links: no bullet, no dead label.
    assert "&middot;" not in html
    assert "Privacy" not in html
    assert "&copy; Insight Health. All rights reserved." in html


def test_a_footer_with_no_legal_links_mints_and_is_a_lawful_shell(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_campaign_shell(
        role=CAMPAIGN_SHELL_FOOTER,
        html=_rendered_footer(),
        css=SHELL_CSS,
        label="Campaign footer — Insight Health",
    )

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert "<a" not in stored.html
    assert "All rights reserved" in stored.html


def test_legal_links_come_from_the_sellers_own_markup_and_are_made_absolute() -> None:
    """"From the kit/source evidence where present" — read out of harvested footers, resolved
    against the page they came from, because a campaign page is served from OUR origin."""
    links = discover_legal_links(
        [
            (
                '<footer><a href="/legal/privacy-policy">Privacy Policy</a>'
                '<a href="/legal/terms">Terms of Service</a>'
                '<a href="/careers">Careers</a></footer>',
                PAGE,
            )
        ]
    )

    assert [link.kind for link in links] == ["privacy", "terms"]
    assert links[0].href == "https://insight.example/legal/privacy-policy"
    assert links[1].href == "https://insight.example/legal/terms"


def test_a_legal_href_that_cannot_be_made_absolute_is_dropped_not_shipped_broken() -> None:
    links = discover_legal_links([('<footer><a href="/privacy">Privacy</a></footer>', "")])

    assert links == ()


def test_no_legal_evidence_finds_nothing_rather_than_guessing_a_url() -> None:
    assert discover_legal_links([]) == ()
    assert discover_legal_links([("<footer><p>Insight Health</p></footer>", PAGE)]) == ()


def test_a_privacy_hostname_is_not_a_privacy_policy() -> None:
    """The PATH decides, not the host: `https://privacy.example/about` is somebody's homepage."""
    links = discover_legal_links(
        [('<footer><a href="https://privacy.example/about">About</a></footer>', PAGE)]
    )

    assert links == ()


# --------------------------------------------------------------------------- #
# Fix round — C1: the classifier's false positives, each the review's live repro
# --------------------------------------------------------------------------- #


def test_the_legal_classifier_decides_by_path_segments_never_by_words() -> None:
    """Fix-round C1, the reviewer's own table. A footer anchor whose PATH is not a legal page is
    not a legal link, whatever its words say — because whatever discovery returns is structurally
    gate-blessed on every account page, a false positive here is a permanent escape route."""
    for html in (
        # `tos` matched inside "photos" (no leading boundary).
        '<footer><a href="/photos">Photos</a></footer>',
        # The words decided while the path said otherwise.
        '<footer><a href="/gallery">Our Photos</a></footer>',
        # "conditions" alone is a medical page on exactly the persona the walk used.
        '<footer><a href="/conditions/diabetes">Conditions we treat</a></footer>',
        # A blog title carrying the word "privacy".
        '<footer><a href="/blog/2026-outlook">Privacy in healthcare: what changes</a></footer>',
    ):
        assert discover_legal_links([(html, PAGE)]) == (), html

    # And the real shapes still classify — by their path, not their words.
    links = discover_legal_links(
        [
            (
                '<footer><a href="/privacy-policy">whatever the anchor says</a>'
                '<a href="/terms-and-conditions">also unread</a></footer>',
                PAGE,
            )
        ]
    )
    assert [link.kind for link in links] == ["privacy", "terms"]
    links = discover_legal_links([('<footer><a href="/tos">TOS</a></footer>', PAGE)])
    assert [link.kind for link in links] == ["terms"]


def test_a_third_party_legal_host_is_dropped_and_named() -> None:
    """Fix-round C1: a legal-looking URL on somebody else's host never ships on an ABM page —
    and the drop is REPORTED, because "no legal links were found" would be a lie."""
    dropped: list[str] = []
    links = discover_legal_links(
        [
            (
                '<footer><a href="https://trustarc.example/privacy-certified">Privacy '
                "certified</a></footer>",
                PAGE,
            )
        ],
        dropped_foreign=dropped,
    )

    assert links == ()
    assert dropped == ["https://trustarc.example/privacy-certified"]


def test_a_www_subdomain_is_the_sellers_own_site() -> None:
    """The same-site rule is host-or-subdomain, so `www.` never costs a real legal link."""
    links = discover_legal_links(
        [
            (
                '<footer><a href="https://www.insight.example/privacy">P</a></footer>',
                "https://insight.example/",
            )
        ]
    )

    assert [link.href for link in links] == ["https://www.insight.example/privacy"]


def test_legal_labels_are_canonical_never_the_anchors_words() -> None:
    """Fix-round C1: the label is what the link IS ("Privacy Policy" / "Terms of Service"),
    never the anchor's arbitrary words — a 40-char blog title is not a footer label."""
    links = discover_legal_links(
        [
            (
                '<footer><a href="/privacy">Read all about how we handle your data here</a>'
                '<a href="/terms">The fine print, every last word of it</a></footer>',
                PAGE,
            )
        ]
    )

    assert [(link.kind, link.label) for link in links] == [
        ("privacy", "Privacy Policy"),
        ("terms", "Terms of Service"),
    ]


# --------------------------------------------------------------------------- #
# Red case 5 — the provenance marker, and discovery
# --------------------------------------------------------------------------- #


def test_a_shell_is_distinguishable_from_a_harvested_clone_in_discovery(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    harvested, _artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html='<section class="f"><p>About Careers</p></section>',
        css=".f { color: #111 }",
        rehosted={},
        source_url=PAGE,
        section_role="footer",
        label="Footer — About Careers",
        slots=(SlotSpec(selector="body > *:nth-child(1)", key="visible", kind="visibility"),),
        provenance={"page_url": PAGE, "section_index": 4},
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=harvested["fragment_id"], status="approved"
    )
    shell = _mint_header(registry, kit)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=shell["fragment_id"], status="approved"
    )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    assert rows[shell["fragment_id"]]["composed"] == COMPOSED_CAMPAIGN_SHELL
    assert rows[shell["fragment_id"]]["section_role"] == CAMPAIGN_SHELL_HEADER
    assert rows[shell["fragment_id"]]["page_url"] == CAMPAIGN_SHELL_SOURCE_URL
    # The harvested band says nothing about being composed, because it was not.
    assert rows[harvested["fragment_id"]]["composed"] is None


def test_an_unapproved_shell_is_not_offered(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    _mint_header(registry)

    assert registry.list_sections(CAMPAIGN_SHELL_HEADER)["sections"] == []


def test_the_shell_row_records_what_composed_it(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = _mint_header(registry)

    provenance = _fragment(workspace_id, minted["fragment_id"])["provenance"]
    assert provenance["composed"] == COMPOSED_CAMPAIGN_SHELL
    assert provenance["shell_role"] == CAMPAIGN_SHELL_HEADER
    assert provenance["composition"] == {"seller_name": "Insight Health"}
    # A shell sat on no page, so it claims no position on one.
    assert provenance["page_url"] is None
    assert provenance["section_index"] is None


# --------------------------------------------------------------------------- #
# Red case 6 — re-mint convergence
# --------------------------------------------------------------------------- #


def test_minting_the_same_shell_twice_converges_rather_than_duplicating(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    first = _mint_header(registry, kit)
    second = _mint_header(registry, kit)

    assert first["fragment_id"] == second["fragment_id"]
    assert first["converged"] is False
    assert second["converged"] is True
    rows = HybridRepository(workspace_id=workspace_id).list_web_fragments()
    assert [row["fragment_id"] for row in rows].count(first["fragment_id"]) == 1


def test_a_shell_whose_composition_changed_is_a_different_shell(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Content addressing cuts both ways, and that is the honest behaviour: a header composed
    with a different CTA is not the same artifact, and both can exist."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    first = _mint_header(registry)
    second = _mint_header(registry, html=_rendered_header(cta_label="Talk to us"))

    assert first["fragment_id"] != second["fragment_id"]


def test_a_re_mint_after_a_human_released_the_shell_keeps_the_release(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """First-writer-wins on the row's judgements: re-minting must not demote an approved shell
    back to draft under the human who released it."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    first = _mint_header(registry)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=first["fragment_id"], status="approved"
    )

    second = _mint_header(registry)

    assert second["fragment_id"] == first["fragment_id"]
    assert second["status"] == "approved"
    assert second["insertable"] is True


# --------------------------------------------------------------------------- #
# The contract itself
# --------------------------------------------------------------------------- #


def test_the_slot_contract_is_spelled_once() -> None:
    header = campaign_shell_slots(CAMPAIGN_SHELL_HEADER)
    assert [(spec.key, spec.kind) for spec in header] == [
        ("prepared_for", "text"),
        ("target_logo", "image"),
        ("cta_href", "href"),
        ("cta_label", "text"),
    ]
    assert campaign_shell_slots(CAMPAIGN_SHELL_FOOTER) == ()
    with pytest.raises(ValueError):
        campaign_shell_slots("nav")


def test_slot_keys_obey_the_engines_own_grammar() -> None:
    """Keys ≤64 characters of `[a-z0-9_-]`, per F1.1 — a key the engine would refuse is a stored
    trap that only detonates when somebody binds it."""
    from lumen_api.fragments import MAX_FRAGMENT_SLOTS, slot_key_is_valid

    for role in (CAMPAIGN_SHELL_HEADER, CAMPAIGN_SHELL_FOOTER):
        specs = campaign_shell_slots(role)
        assert len(specs) <= MAX_FRAGMENT_SLOTS
        for spec in specs:
            assert slot_key_is_valid(spec.key), spec.key
            assert len(spec.key) <= 64


def test_a_role_that_is_not_a_shell_cannot_be_minted_as_one(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(ValueError):
        registry.mint_campaign_shell(
            role="footer", html=_rendered_footer(), css=SHELL_CSS, label="not a shell"
        )


def test_the_legal_link_evidence_is_read_from_this_workspaces_footer_clones(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row, _artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html='<section class="f"><a href="/privacy">Privacy</a></section>',
        css=".f { color: #111 }",
        rehosted={},
        source_url=PAGE,
        section_role="footer",
        label="Footer",
        provenance={"page_url": PAGE, "section_index": 4},
    )
    # RELEASED evidence only (fix-round I3): a draft footer has not been judged fit to reuse,
    # and dormant/deprecated ones are excluded for their own reasons.
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    links = discover_legal_links(registry.legal_link_evidence())

    assert [link.href for link in links] == ["https://insight.example/privacy"]


def test_legal_evidence_reads_only_approved_footer_clones_of_the_kit(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Fix-round I3. A dormant footer is hidden on the source site (D-F8) and a deprecated one is
    retired; a nav is full of product links; another brand's footer is another brand's law. None
    of them may supply the legal links that ship on every ABM page for THIS kit."""
    _seed_kit(workspace_id, kit_id="brand_kit_other", version=1)
    _seed_kit(workspace_id, kit_id="brand_kit_ours", version=1)

    def _seed(html: str, *, role: str, status: str, kit: str | None = None) -> str:
        seeded, _ = create_web_fragment(
            design_storage,
            workspace_id=workspace_id,
            html=html,
            css=".f { color: #111 }",
            rehosted={},
            source_url=PAGE,
            section_role=role,
            label=f"{role} ({status})",
            source_kit_id=kit,
            source_kit_version=1 if kit else None,
            provenance={"page_url": PAGE, "section_index": 1},
            # Dormancy is a BIRTH fact (D-F8); approval is a transition.
            status="dormant" if status == "dormant" else None,
        )
        if status not in ("draft", "dormant"):
            set_web_fragment_status(
                workspace_id=workspace_id, fragment_id=seeded["fragment_id"], status=status
            )
        return str(seeded["fragment_id"])

    _seed('<section><a href="/its-privacy">A</a></section>', role="footer", status="draft")
    _seed('<section><a href="/its-privacy">B</a></section>', role="footer", status="dormant")
    deprecated = _seed(
        '<section><a href="/its-privacy">C</a></section>', role="footer", status="approved"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=deprecated, status="deprecated"
    )
    _seed(
        '<section><a href="/its-privacy">D</a></section>',
        role="footer",
        status="approved",
        kit="brand_kit_other",
    )
    _seed('<section><a href="/its-privacy">E</a></section>', role="nav", status="approved")
    _seed(
        '<section><a href="/privacy">Ours</a></section>',
        role="footer",
        status="approved",
        kit="brand_kit_ours",
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    evidence = registry.legal_link_evidence(kit_id="brand_kit_ours")

    assert len(evidence) == 1
    assert 'href="/privacy"' in evidence[0][0]
    links = discover_legal_links(evidence)
    assert [link.href for link in links] == ["https://insight.example/privacy"]


def test_a_composed_footer_puts_the_discovered_links_where_the_gate_expects_them() -> None:
    html = compose_campaign_footer(
        seller_name="Insight Health",
        seller_logo_asset_id="logo_1",
        legal_links=(
            LegalLink(kind="privacy", label="Privacy", href="https://insight.example/privacy"),
            LegalLink(kind="terms", label="Terms", href="https://insight.example/terms"),
        ),
    )

    assert html.count(f'class="{MARK_LEGAL} ') == 2
    assert "https://insight.example/privacy" in html
    # Container-links, so the marker survives the engine (an inline `<a>` loses its class).
    assert html.count("data-href=") == 2


# --------------------------------------------------------------------------- #
# The derive walk — the shell personalizing, through the REAL F1.4 path
# --------------------------------------------------------------------------- #
#
# The payoff, and the half of red case 2 that only a real derive can prove: ONE header artifact
# serves every account, the account's display name lands after the words "Prepared for", and an
# account we hold NO logo for gets a header that is clean rather than broken. Modeled on
# `test_web_fragment_derive.py`, which is the same walk for a harvested clone.

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def _shell_template_doc(document_id: str, fragment_id: str, slots: dict) -> dict:
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
                    "root": {"id": "root", "kind": "container", "classes": "", "children": ["sec"]},
                    "sec": {
                        "id": "sec",
                        "kind": "section",
                        "tag": "section",
                        "classes": "",
                        "children": ["frg_shell"],
                    },
                    "frg_shell": {
                        "id": "frg_shell",
                        "kind": "fragment",
                        "fragment_id": fragment_id,
                        "slots": slots,
                        "classes": "w-full",
                    },
                },
            }
        ],
        "assets": {},
        "custom_css": "",
    }


SHELL_SLOT_TEMPLATES = {
    "prepared_for": {"text": "{{account.name}}"},
    "target_logo": {"text": "{{account.logo}}"},
    "cta_label": {"text": "See the {{account.name}} walkthrough"},
    "cta_href": {"text": "https://{{account.domain}}/demo"},
}


@pytest.fixture()
def shell_client(tmp_path, design_storage: FsStorage):
    from conftest import make_client

    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _released_header(workspace_id: str, design_storage: FsStorage, tmp_path) -> str:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.campaign_shell_placeholder()
    minted = _mint_header(registry)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=minted["fragment_id"], status="approved"
    )
    return minted["fragment_id"]


def test_the_header_personalizes_per_account_through_the_real_derive_path(
    shell_client, workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    fragment_id = _released_header(workspace_id, design_storage, tmp_path)
    logo_asset_id = shell_client.post(
        "/assets",
        files={"file": ("acme.png", TINY_PNG, "image/png")},
        data={"label": "Acme logo", "kind": "raster_image"},
    ).json()["asset"]["id"]
    HybridRepository(workspace_id=workspace_id).create_document(
        _shell_template_doc("doc_abm_tmpl", fragment_id, SHELL_SLOT_TEMPLATES), doc_kind="web"
    )
    account = shell_client.post(
        "/web/accounts",
        json={"name": "Acme Health", "domain": "acme.example", "logo_asset_id": logo_asset_id},
    ).json()

    derived = shell_client.post(
        "/documents/doc_abm_tmpl/web/derive", json={"account_id": account["account_id"]}
    )
    assert derived.status_code == 200, derived.text
    document_id = derived.json()["document_id"]

    html = shell_client.get(f"/documents/{document_id}/web/render").json()["html"]
    # The framing is the ARTIFACT's; only the name came from the account. The name lands inside
    # its own marked span, which is exactly why the framing cannot be rewritten by a binding.
    assert 'Prepared for <span class="lumen-shell-prepared-for"' in html
    assert ">Acme Health</span>" in html
    assert "your team" not in html
    assert "See the Acme Health walkthrough" in html
    assert 'href="https://acme.example/demo"' in html
    # The account's own logo replaced the empty co-brand mark.
    digest = HybridRepository(workspace_id=workspace_id).require_asset_record(logo_asset_id)[
        "asset"
    ]["media"]["digest"]["value"]
    assert f"/asset-store/{digest}" in html
    assert COBRAND_DIGEST not in html
    # Every marker survives, so the page is re-derivable rather than baked.
    for key in ("prepared_for", "target_logo", "cta_href", "cta_label"):
        assert f'data-lumen-slot="{key}"' in html
    # Still exactly one anchor on the header: personalization cannot add an escape route.
    assert html.count("<a ") == 1


def test_an_account_with_no_logo_renders_a_clean_header_not_a_broken_one(
    shell_client, workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Empty is CORRECT (the never-synthesize register). The unbound co-brand slot falls back to
    the transparent pixel: no broken image, no placeholder words, no invented mark."""
    fragment_id = _released_header(workspace_id, design_storage, tmp_path)
    HybridRepository(workspace_id=workspace_id).create_document(
        _shell_template_doc("doc_abm_nologo", fragment_id, SHELL_SLOT_TEMPLATES), doc_kind="web"
    )
    account = shell_client.post(
        "/web/accounts", json={"name": "Acme Health", "domain": "acme.example"}
    ).json()

    derived = shell_client.post(
        "/documents/doc_abm_nologo/web/derive", json={"account_id": account["account_id"]}
    )
    assert derived.status_code == 200, derived.text
    body = derived.json()
    html = shell_client.get(f"/documents/{body['document_id']}/web/render").json()["html"]

    assert ">Acme Health</span>" in html
    # The co-brand image is still there and still empty — an invisible pixel with no alt text.
    # (The render route serves an absolute asset base, so match the digest tail.)
    assert f'/asset-store/{COBRAND_DIGEST}" alt=""' in html
    for placeholder in ("Logo", "logo here", "placeholder", "?"):
        assert f">{placeholder}<" not in html
    # And nothing about the missing logo broke the rest of the strip.
    assert "See the Acme Health walkthrough" in html


# --------------------------------------------------------------------------- #
# Fix round — I2: the sibling repair door mints under the shell contract too
# --------------------------------------------------------------------------- #
#
# `mint_repair` is the shells' one other producer: an agent may repair a pinned shell. Without
# these rules a "repair" of a campaign header could carry a nav full of escape routes (the gate
# never ran), drop the `composed` marker (the picker reads it as a harvested clone, and the
# recreate's page-set sees its sentinel source_url again), and swap the RULED editing surface for
# whatever the harvest detector found. Ruling R23-F1: a shell-role repair goes through the shell
# gate, keeps the ruled slots, and inherits `composed`.


def test_a_repair_of_a_shell_carrying_a_nav_mints_and_says_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """R-F5-8: the repair door still RUNS the shape check — it just hands the finding back."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = _mint_header(registry)

    repair = registry.mint_repair(
        replaces=minted["fragment_id"],
        html=_rendered_header(extra="<nav><p>Products</p></nav>"),
        css=SHELL_CSS,
        rung=2,
        note="a nav wearing a repair's clothes",
    )

    assert repair["fragment_id"]
    assert any("<nav>" in note for note in repair["advice"]), repair["advice"]


def test_a_lawful_shell_repair_stays_composed_and_keeps_the_ruled_slots(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = _mint_header(registry)

    repair = registry.mint_repair(
        replaces=minted["fragment_id"],
        html=_rendered_header(cta_label="Talk to us"),
        css=SHELL_CSS,
        rung=2,
        note="a calmer call to action",
    )

    row = _fragment(workspace_id, repair["fragment_id"])
    provenance = row["provenance"]
    assert provenance["composed"] == COMPOSED_CAMPAIGN_SHELL
    # A shell sat on no page, and neither does its repair: never the sentinel source_url.
    assert provenance["page_url"] is None
    assert row["derived_from"] == minted["fragment_id"]
    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=repair["fragment_id"]
    )
    # The RULED surface, not the harvest detector's: exactly the four header slots.
    assert sorted(stored.slot_manifest) == ["cta_href", "cta_label", "prepared_for", "target_logo"]


def test_a_shell_repair_that_loses_the_marker_classes_refuses(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A repair that dropped a marker has no place for the ruled slot to live — refused typed,
    telling the composer to keep the markers, never minted with a shrunken surface."""
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = _mint_header(registry)
    unmarked = _rendered_header(cta_label="Different words").replace(
        f'class="{MARK_PREPARED_FOR}"', 'class=""'
    )

    with pytest.raises(FragmentRefused) as refusal:
        registry.mint_repair(
            replaces=minted["fragment_id"],
            html=unmarked,
            css=SHELL_CSS,
            rung=2,
            note="lost the prepared-for marker",
        )

    assert refusal.value.code == "fragment.slot_selector_unmatched"


# --------------------------------------------------------------------------- #
# Fix round 2 — the re-review's pins (N2, N4)
# --------------------------------------------------------------------------- #


def test_the_composed_cta_carries_the_kits_measured_button_radius() -> None:
    """Fix-round I4/N4: the one control the shell has wears `rounded-button` — the engine
    resolves it through the kit's measured `radius.button` chain, so the Grammar Audit's corner
    law governs it. Reverting to a platform radius goes red here."""
    html = compose_campaign_header(seller_name="Insight Health", seller_logo_asset_id="logo_1")

    assert "rounded-button" in html
    assert "rounded-md" not in html


def test_a_shell_carrying_a_second_control_or_an_image_map_is_noted() -> None:
    """Fix-round M3/N4, still DETECTED under R-F5-8: an `<input>`/`<textarea>` is a second
    control, and a `<map>`/`<area>` is a navigation target `css(\"a\")` never counts."""
    for extra, element in (
        ('<input type="text">', "<input>"),
        ("<textarea></textarea>", "<textarea>"),
        ('<map name="m"><area href="/pricing" shape="default"></map>', "<map>"),
    ):
        notes = campaign_shell_shape_notes(CAMPAIGN_SHELL_HEADER, _rendered_header(extra=extra))
        assert notes, extra
        assert any(element in note for note in notes), (extra, notes)


def test_a_same_host_link_with_an_explicit_port_is_the_sellers_own() -> None:
    """Fix-round N2: `insight.example:443` is the same site, not a stranger — a port must never
    make a real legal link report as foreign."""
    dropped: list[str] = []
    links = discover_legal_links(
        [
            (
                '<footer><a href="https://insight.example:443/privacy">Privacy</a></footer>',
                PAGE,
            )
        ],
        dropped_foreign=dropped,
    )

    assert [link.kind for link in links] == ["privacy"]
    assert dropped == []
