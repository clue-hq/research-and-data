"""The isolation render, and the one-way preview attach it feeds (clone-fidelity F3.2, P-7).

F3.0 shipped D-F8's activation gate and recorded, honestly, that it could never pass: a section
the source site HIDES was never rendered, so the capture holds no pixels of it and the row is born
``preview_digest IS NULL``. Ruling P-7 closes the loop by rendering the ARTIFACT'S OWN BYTES in
isolation — our engine, the stored markup and scoped CSS, the rehosted assets — and storing that
as the fragment's preview. Ruling R17-2 needs the same thing for a repair, which nobody
photographed either.

What is pinned here is the pair of properties that make an isolation render trustworthy:

* **it is a picture of the artifact.** The render input is the fragment's own sanitized html and
  scoped css, not a crop of a source-site screenshot, and the assets it is allowed to load are the
  ones the workspace holds.
* **a preview is attached once.** The digest is part of the artifact's identity bytes, so
  replacing it would rewrite the picture a human's decision was made against while leaving the id
  unchanged. NULL → digest is allowed; anything else is refused, in the DAL and again in the
  database.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from clue_design.errors import DesignFragmentPreviewError
from clue_storage import FsStorage

from lumen_api.fragments import (
    ISOLATION_RENDER_BASIS,
    IsolationRenderFailed,
    attach_web_fragment_preview,
    create_web_fragment,
    fragment_wrapper_class,
    read_web_fragment,
    render_isolation_preview,
    set_web_fragment_status,
)
from lumen_api.fragments.isolation import (
    IsolationPage,
    build_isolation_page,
    held_isolation_asset,
    isolation_web_doc,
    screenshot_isolation_page,
)
from lumen_api.fragments.slots import SlotSpec

SENTINEL = "The clinic nobody was shown"
CLONE_DIGEST = "3c" * 32
HTML = (
    f'<section class="hidden-band"><h2 class="hidden-head">{SENTINEL}</h2>'
    f'<img class="hidden-art" src="/asset-store/{CLONE_DIGEST}" alt="Ward"></section>'
)
CSS = ".hidden-band { padding: 96px } .hidden-head { color: #0b3d2e }"
SOURCE_URL = "https://insight.example/"
PNG = b"\x89PNG\r\n\x1a\n-isolation-render-bytes"


def test_isolation_preview_loads_pinned_kit_font_bytes_without_network() -> None:
    from lumen_api.fragments.isolation import ISOLATION_ORIGIN, IsolationFonts

    digest = "7e" * 32
    font_url = f"{ISOLATION_ORIGIN}/asset-store/{digest}"
    css = f'@font-face{{font-family:"brandAlias";font-weight:500;src:url("{font_url}")}}'
    loaded = SimpleNamespace(
        fragment_id="frag_" + "ab" * 8,
        payload={},  # ordinary capture: no declared platform dependencies
        html='<section><h2 style="font-family:brandAlias">Brand heading</h2></section>',
        css=".section{padding:24px}",
        slot_manifest={},
        asset_digests=(),
    )
    core = _FakeCore()
    seen: dict[str, Any] = {}

    def shoot(page: IsolationPage, assets: Any) -> bytes:
        seen["assets"] = assets
        assert held_isolation_asset(font_url, assets) == ("font/woff2", b"custodied-font")
        assert held_isolation_asset("https://font-vendor.example/font.woff2", assets) is None
        return PNG

    png, page = render_isolation_preview(
        core,
        loaded,
        read_blob=lambda _digest: ("font/woff2", b"custodied-font"),
        fonts=IsolationFonts(css=css, asset_digests=(digest,)),
        shoot=shoot,
    )
    assert png == PNG
    assert core.calls[0]["font_face_css"] == css
    assert core.calls[0]["fragment_css"].endswith(loaded.css)
    assert page.asset_digests == (digest,)
    assert set(seen["assets"]) == {digest}
    assert loaded.asset_digests == ()  # Preview does not rewrite the stored artifact.


def test_missing_kit_font_cannot_escape_workspace_custody() -> None:
    from lumen_api.fragments.isolation import IsolationFonts

    digest = "7e" * 32
    loaded = SimpleNamespace(
        fragment_id="frag_" + "ab" * 8,
        payload={},  # ordinary capture: no declared platform dependencies
        html="<section>Heading</section>",
        css="",
        slot_manifest={},
        asset_digests=(digest,),
    )
    reads: list[str] = []

    def missing(value: str) -> tuple[str, bytes]:
        reads.append(value)
        raise LookupError("not held by this workspace")

    seen: dict[str, Any] = {}
    render_isolation_preview(
        _FakeCore(),
        loaded,
        read_blob=missing,
        fonts=IsolationFonts(css="@font-face{}", asset_digests=(digest, digest)),
        shoot=lambda page, assets: seen.setdefault("assets", dict(assets)) or PNG,
    )
    assert reads == [digest]
    assert seen["assets"] == {}


class _FakeCore:
    """Records what the engine was asked to render. The render itself is the engine's job and is
    covered by `test_web_fragment_render.py`; what THIS file is about is the INPUT."""

    def __init__(self, html: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._html = html

    def web_render(self, doc: Any, page_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"doc": doc, "page_id": page_id, **kwargs})
        fragment_id = next(iter(kwargs.get("fragments") or {}), "frag_unknown")
        body = self._html
        if body is None:
            body = (
                f'<div class="{fragment_wrapper_class(fragment_id)}">'
                f"{kwargs['fragments'][fragment_id]['html']}</div>"
            )
        return {"html": f"<!doctype html><html><body>{body}</body></html>", "diagnostics": []}


def _mint_dormant(workspace_id: str, storage: FsStorage) -> dict[str, Any]:
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=HTML,
        css=CSS,
        rehosted={f"/asset-store/{CLONE_DIGEST}": CLONE_DIGEST},
        source_url=SOURCE_URL,
        section_role="proof",
        slots=(SlotSpec(selector="h2.hidden-head", key="headline", kind="text"),),
        label="Proof — Pricing",
        status="dormant",
        provenance={
            "page_url": SOURCE_URL,
            "section_index": 7,
            "hidden_on_source": {
                "hidden": True,
                "evidence": ["class token 'w-condition-invisible'", "probe skipped the child"],
            },
        },
    )
    return row


# --------------------------------------------------------------------------- #
# What the isolation render is a picture OF
# --------------------------------------------------------------------------- #


def test_the_isolation_render_is_made_from_the_artifacts_own_bytes(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Red case 4: assert the render INPUT is the sanitized artifact html/css, not a crop."""
    row = _mint_dormant(workspace_id, design_storage)
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"]
    )
    core = _FakeCore()
    shot: dict[str, Any] = {}

    def _shoot(page: IsolationPage, assets: Any) -> bytes:
        shot["page"] = page
        shot["assets"] = dict(assets)
        return PNG

    png, page = render_isolation_preview(
        core,
        loaded,
        read_blob=lambda digest: ("image/png", b"real-ward-bytes"),
        shoot=_shoot,
    )
    assert png == PNG

    call = core.calls[0]
    handed = call["fragments"][row["fragment_id"]]["html"]
    # The artifact's OWN sanitized markup — the section's copy and its slot marker survive.
    assert SENTINEL in handed
    assert "data-lumen-slot" in handed
    # …and its OWN scoped stylesheet, scoped under this fragment's wrapper.
    assert fragment_wrapper_class(row["fragment_id"]) in call["fragment_css"]
    assert "#0b3d2e" in call["fragment_css"]
    # Not a screenshot: nothing in this path reads the capture's pixels.
    assert call["mode"] == "delivery"
    # The picture is of the BAND, not of a page around it.
    assert page.element_selector == f".{fragment_wrapper_class(row['fragment_id'])}"
    # Only bytes this workspace holds are offered to the browser.
    assert set(shot["assets"]) == {CLONE_DIGEST}


def test_the_isolated_document_is_the_shape_a_pinned_clone_actually_occupies() -> None:
    doc = isolation_web_doc("frag_" + "ab" * 8)
    nodes = doc["pages"][0]["nodes"]
    assert nodes["root"]["kind"] == "container"
    # LUMW0011: the root holds sections, and a fragment is a leaf — so the wrapper is not
    # decoration, it is the only shape the engine accepts.
    section = nodes[nodes["root"]["children"][0]]
    assert section["kind"] == "section"
    fragment = nodes[section["children"][0]]
    assert fragment["kind"] == "fragment"
    assert fragment.get("children") is None


def test_a_fragment_that_did_not_render_refuses_rather_than_photographing_a_placeholder(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """A placeholder is the one picture worse than none: a human would activate on it."""
    row = _mint_dormant(workspace_id, design_storage)
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"]
    )
    core = _FakeCore(html="<p>fragment unavailable</p>")
    page = build_isolation_page(core, loaded)
    assert page.element_selector not in page.html

    def _shoot(_page: IsolationPage, _assets: Any) -> bytes:
        raise IsolationRenderFailed("isolation.section_not_rendered", "nothing to photograph")

    with pytest.raises(IsolationRenderFailed) as refusal:
        render_isolation_preview(
            core, loaded, read_blob=lambda digest: ("image/png", b""), shoot=_shoot
        )
    assert refusal.value.code == "isolation.section_not_rendered"


def test_a_byte_the_workspace_no_longer_holds_leaves_a_gap_not_a_failure(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint_dormant(workspace_id, design_storage)
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"]
    )
    seen: dict[str, Any] = {}

    def _missing(_digest: str) -> tuple[str, bytes]:
        raise LookupError("purged")

    render_isolation_preview(
        _FakeCore(),
        loaded,
        read_blob=_missing,
        shoot=lambda page, assets: seen.setdefault("assets", dict(assets)) or PNG,
    )
    assert seen["assets"] == {}


def test_the_page_carries_the_kind_of_picture_it_is(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """P-7's labelling clause: the label comes from the thing that MADE the picture.

    Replaces an earlier version of this test that compared the constant to its own literal —
    which passed while the value reached no row and no reader (review finding M-9).
    """
    row = _mint_dormant(workspace_id, design_storage)
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"]
    )
    page = build_isolation_page(_FakeCore(), loaded)
    assert page.basis == ISOLATION_RENDER_BASIS

    attached = attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        preview=PNG,
        preview_basis=page.basis,
    )
    # …and it is DURABLE: the row itself now says what kind of picture it holds.
    assert attached["preview_basis"] == ISOLATION_RENDER_BASIS


def test_an_unlabelled_picture_is_refused_rather_than_stored(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """An unlabelled picture is the state P-7 exists to prevent, so it is not a valid write."""
    row = _mint_dormant(workspace_id, design_storage)
    with pytest.raises(ValueError):
        attach_web_fragment_preview(
            design_storage,
            workspace_id=workspace_id,
            fragment_id=row["fragment_id"],
            preview=PNG,
            preview_basis="",
        )


def test_only_bytes_this_workspace_holds_may_be_served_to_the_render() -> None:
    """The fail-closed rule, without a browser.

    It is the thing standing between "a picture of the artifact" and "a picture of the internet",
    and it used to be reachable only by launching Chromium (review finding M-8).
    """
    held = {CLONE_DIGEST: ("image/png", b"ward")}
    assert held_isolation_asset(f"https://x.invalid/asset-store/{CLONE_DIGEST}", held) == (
        "image/png",
        b"ward",
    )
    # A query string after the digest is still this digest — matching on the whole URL used to
    # abort a legitimate asset here, which fails quietly as a hole in the picture.
    assert held_isolation_asset(
        f"https://x.invalid/asset-store/{CLONE_DIGEST}?v=2", held
    ) == ("image/png", b"ward")
    # Everything else is aborted: another origin's font, a beacon, a digest we do not hold.
    assert held_isolation_asset("https://fonts.example/x.woff2", held) is None
    assert held_isolation_asset(f"https://x.invalid/asset-store/{'ff' * 32}", held) is None
    assert held_isolation_asset("https://x.invalid/asset-store/", held) is None


def test_a_missing_browser_refuses_typed_rather_than_escaping_as_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deploy note's claim, tested: an API process with no Playwright refuses by name."""
    import builtins

    real_import = builtins.__import__

    def _no_playwright(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("playwright"):
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_playwright)
    page = IsolationPage(
        fragment_id="frag_" + "ab" * 8,
        html="<html></html>",
        asset_digests=(),
        element_selector=".lumen-frag-x",
    )
    with pytest.raises(IsolationRenderFailed) as refusal:
        screenshot_isolation_page(page, {})
    assert refusal.value.code == "isolation.render_failed"


# --------------------------------------------------------------------------- #
# The one-way attach
# --------------------------------------------------------------------------- #


def test_a_dormant_clone_with_a_preview_can_finally_be_activated(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint_dormant(workspace_id, design_storage)
    assert row["preview_digest"] is None

    attached = attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        preview=PNG,
        preview_basis=ISOLATION_RENDER_BASIS,
    )
    assert attached["preview_digest"]
    # …and the gate that refused before now lets the human through.
    woken = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )
    assert woken["status"] == "approved"


def test_the_attached_bytes_are_readable_back_out_of_custody(
    workspace_id: str, design_storage: FsStorage
) -> None:
    from lumen_api.design_store import DesignBlobStore

    row = _mint_dormant(workspace_id, design_storage)
    attached = attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        preview=PNG,
        preview_basis=ISOLATION_RENDER_BASIS,
    )
    blobs = DesignBlobStore(design_storage, workspace_id)
    media_type, data = blobs.read_blob(attached["preview_digest"])
    assert data == PNG
    assert media_type == "image/png"


def test_a_preview_is_attached_once_and_never_replaced(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint_dormant(workspace_id, design_storage)
    attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        preview=PNG,
        preview_basis=ISOLATION_RENDER_BASIS,
    )
    with pytest.raises(DesignFragmentPreviewError) as refusal:
        attach_web_fragment_preview(
            design_storage,
            workspace_id=workspace_id,
            fragment_id=row["fragment_id"],
            preview=PNG + b"-different",
            preview_basis=ISOLATION_RENDER_BASIS,
        )
    assert refusal.value.reason == "already_present"
    assert row["fragment_id"] in str(refusal.value)


def test_attaching_a_preview_changes_nothing_else_about_the_row(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The relaxation is one column in one direction; the artifact stays as frozen as it was."""
    row = _mint_dormant(workspace_id, design_storage)
    attached = attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        preview=PNG,
        preview_basis=ISOLATION_RENDER_BASIS,
    )
    for key in (
        "fragment_id",
        "payload_digest",
        "provenance",
        "label",
        "source_url",
        "section_role",
        "status",
        "created_at",
        "derived_from",
    ):
        assert attached[key] == row[key], key


def test_a_foreign_workspaces_fragment_cannot_be_given_a_preview(
    workspace_id: str, design_storage: FsStorage, tmp_path: Path
) -> None:
    from lumen_api.database import NotFoundError

    row = _mint_dormant(workspace_id, design_storage)
    with pytest.raises(NotFoundError):
        attach_web_fragment_preview(
            design_storage,
            workspace_id=workspace_id + "_neighbour",
            fragment_id=row["fragment_id"],
            preview=PNG,
            preview_basis=ISOLATION_RENDER_BASIS,
        )


def test_an_invisible_render_refuses_typed_instead_of_timing_out():
    """Phase fix wave, walk F-3's inspector half: a pre-wave dormant artifact still obeys the
    source's hiding CSS. F4 wave item 1 (the CP2 walk's F-2 — missed at TWO checkpoints):
    the stylesheet countermand is a specificity fight it can lose (`.section:has(...)` outranks
    it), so `_shoot` now FORCES the root visible inline on the live DOM (an inline !important
    outranks any stylesheet rule), re-checks, and refuses only if the element STAYS invisible —
    with a message that is true (the old "re-ingest" remedy was false for artifacts minted with
    the mechanics active)."""
    import inspect

    from lumen_api.fragments.isolation import IsolationRenderFailed, _shoot

    # The premise, pinned at the source (the browser half stays unexecuted until a live walk,
    # the established pattern): the visibility check sits between finding the element and
    # photographing it.
    source = inspect.getsource(_shoot)
    assert "_surface_element" in source
    assert source.index("_surface_element") < source.index('element.screenshot(type="png")')
    assert "re-ingest the site" not in source  # the false remedy is gone
    assert "repair it through the ladder" in source

    refusal = IsolationRenderFailed(
        "isolation.section_hidden_by_its_own_css", "hidden by its own css"
    )
    assert refusal.code == "isolation.section_hidden_by_its_own_css"
    assert refusal.code != "isolation.section_not_rendered"


def test_the_force_reaches_the_artifacts_own_root_not_only_the_wrapper() -> None:
    """Wave round 2 (the re-walk's N-1, behaviourally): harvested CSS is scoped
    `.lumen-frag-<id> <sel>` — it hides DESCENDANTS, never the wrapper — so a force aimed at
    the wrapper alone can never surface any harvested artifact. The re-walk proved forcing
    the artifact's own root (the wrapper's first element child) yields the honest picture;
    hiding any deeper stays a refusal."""
    import asyncio

    from lumen_api.fragments.isolation import _surface_element

    class FakeNode:
        def __init__(self) -> None:
            self.forced = False

        async def evaluate(self, _js: str) -> None:
            self.forced = True

    class FakeWrapper(FakeNode):
        """Visible exactly when its hidden CHILD has been forced — the scoped-CSS shape."""

        def __init__(self, child, *, visible_when_child_forced: bool = True) -> None:
            super().__init__()
            self.child = child
            self._child_unlocks = visible_when_child_forced

        async def is_visible(self) -> bool:
            return bool(self.child and self.child.forced and self._child_unlocks)

        async def query_selector(self, selector: str):
            assert selector == ":scope > *"
            return self.child

    # The walk's shape: root-level hiding one element down → forced → surfaced.
    child = FakeNode()
    wrapper = FakeWrapper(child)
    assert asyncio.run(_surface_element(wrapper)) is True
    assert child.forced is True

    # Deeper hiding: even the forced child does not surface the wrapper → honest refusal.
    stubborn = FakeWrapper(FakeNode(), visible_when_child_forced=False)
    assert asyncio.run(_surface_element(stubborn)) is False
