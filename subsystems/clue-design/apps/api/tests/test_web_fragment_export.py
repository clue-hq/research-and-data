"""A cloned section through PUBLISH (clone-fidelity F1.5).

Tasks 7 and 8 made a fragment render, in flow and personalized, on both PREVIEW paths. This
file is the other half of the phase's acceptance matrix: the DELIVERY path, where a page stops
being a preview and becomes bytes somebody else holds. (It covered the ZIP export too until the
founder ruling of 2026-10-13 removed every web/site export: publishing is the only delivery.)

Three things have to be true of it, and each is a different kind of failure when it is not:

1. **The section renders** — same substituted markup as the preview, not the placeholder. A
   fragment that previews and then publishes as "Cloned section unavailable" is the whole
   feature failing at the last step.
2. **Its CSS is in the head, ahead of the compiled sheet** — an unstyled clone is worse than no
   clone, and the compiled-utility tie-break is the plan's ruling, so it is pinned against a
   REAL compiled sheet here rather than against the document's own class tokens (which is all a
   preview has).
3. **Every byte it displays is named and readable** — the artifact's own rehosted assets AND
   anything bound into an asset slot, on the digest route the page origin serves.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from clue_design.storage import SOURCE_KEY_ASSET

from conftest import make_blob_store, make_client, published_html, published_manifest
from PIL import Image

from lumen_api.design_store import DesignStoreBridge, HybridRepository
from lumen_api.fragments import (
    create_web_fragment,
    fragment_wrapper_class,
    set_web_fragment_status,
)
from lumen_api.fragments.slots import SlotSpec
from lumen_api.main import create_app
from lumen_api.public_address import PublicSiteAddress
from lumen_api.web_export import build_publish_package

CLONE_HERO_URL = "https://clone.example/hero.png"
CLONE_LOGO_URL = "https://clone.example/logo.png"
SOURCE_URL = "https://clone.example/"

#: The clone's own words, so an assertion can tell "the artifact rendered" from "something did".
CLONE_HEADLINE = "Care, on your terms"
ACCOUNT_HEADLINE = "Care for Privia Health"

FRAGMENT_HTML = (
    '<section class="clone-hero">'
    f'<h1 class="clone-head">{CLONE_HEADLINE}</h1>'
    f'<img class="clone-logo" src="{CLONE_LOGO_URL}" alt="Clone Co">'
    '<a class="clone-cta" href="https://clone.example/demo">Book a demo</a>'
    "</section>"
)
FRAGMENT_CSS = (
    f'.clone-hero {{ background-image: url({CLONE_HERO_URL}); padding: 64px }} '
    ".clone-head { color: #123456 }"
)
SLOT_SPECS = (
    SlotSpec(selector="h1.clone-head", key="headline", kind="text"),
    SlotSpec(selector="img.clone-logo", key="logo", kind="image"),
)


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


# --------------------------------------------------------------------------- #
# Fixtures: real bytes, a real artifact, a real document
# --------------------------------------------------------------------------- #


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, "PNG")
    return buffer.getvalue()


def _register(client: TestClient, data: bytes, media_type: str = "image/png") -> str:
    """Bytes into durable custody under their digest — what F0's rehost does."""
    make_blob_store(client.app).register(
        data, media_type=media_type, source_key=SOURCE_KEY_ASSET
    )
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _upload_asset(client: TestClient, data: bytes, name: str = "logo.png") -> dict:
    response = client.post("/assets", files={"file": (name, data, "image/png")})
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def _mint_fragment(
    client: TestClient,
    workspace_id: str,
    *,
    html: str = FRAGMENT_HTML,
    css: str = FRAGMENT_CSS,
    rehosted: dict[str, str] | None = None,
    slots: tuple[SlotSpec, ...] = SLOT_SPECS,
):
    _row, artifact = create_web_fragment(
        client.app.state.storage,
        workspace_id=workspace_id,
        html=html,
        css=css,
        rehosted=rehosted or {},
        source_url=SOURCE_URL,
        section_role="hero",
        slots=slots,
    )
    # A fragment is born `draft` and a document may only pin an APPROVED one (F2.2's half of the
    # reference gate). This file is about delivery, not about the gate, so it releases the
    # fragment the way a human would and gets on with it.
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="approved"
    )
    return artifact


def _web_doc(
    document_id: str,
    *nodes: dict[str, Any],
    assets: dict[str, Any] | None = None,
    custom_css: str = "",
) -> dict[str, Any]:
    node_map: dict[str, Any] = {
        "root": {
            "id": "root",
            "kind": "container",
            "classes": "",
            "children": [node["id"] for node in nodes],
        }
    }
    for node in nodes:
        node_map[node["id"]] = node
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "Cloned landing page",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": node_map,
            }
        ],
        "assets": assets or {},
        "custom_css": custom_css,
    }


def _seed(client: TestClient, web_doc: dict[str, Any]) -> dict:
    response = client.post("/documents", json={"doc_kind": "web", "title": "Cloned landing page"})
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    web_doc = {**web_doc, "id": document["id"]}
    HybridRepository().update_web_document(
        document["id"],
        web_doc,
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
        push_undo=False,
    )
    return document


def _publish(
    client: TestClient, document_id: str, workspace_id: str, slug: str
) -> tuple[str, dict]:
    published = client.post(
        f"/documents/{document_id}/web/publish", json={"slug": slug}
    )
    assert published.status_code == 200, published.text
    return published_html(workspace_id, slug), published_manifest(workspace_id, slug)


def _compiled_sheet(html: str) -> str:
    """The page's compiled Tailwind sheet, which a publish INLINES (no external stylesheet)."""
    match = re.search(r'<style id="lumen-static-css">(.*?)</style>', html, re.S)
    assert match is not None, "the published page carries no compiled sheet"
    return match.group(1)


def _fragment_region(html: str, fragment_id: str) -> str:
    """The rendered fragment wrapper and everything inside it.

    A hand-rolled slice rather than a parser: the wrapper is a `div` the engine authors itself
    (one known opening tag, one closing tag at the end of the artifact), and the artifact's own
    markup must be compared BYTE for byte, which a parser would normalize away.
    """
    marker = f'<div class="lumen-fragment {fragment_wrapper_class(fragment_id)}'
    start = html.index(marker)
    depth = 0
    index = start
    while True:
        opened = html.find("<div", index)
        closed = html.index("</div>", index)
        if opened != -1 and opened < closed:
            depth += 1
            index = opened + 4
            continue
        depth -= 1
        if depth == 0:
            return html[start : closed + len("</div>")]
        index = closed + len("</div>")


# --------------------------------------------------------------------------- #
# 1 — a dead pin
# --------------------------------------------------------------------------- #


def test_a_dead_fragment_pin_still_publishes_and_says_so(
    client: TestClient, workspace_id: str
) -> None:
    """Fail-soft, exactly as the preview paths are: one dead pin must not cost the page.

    Built through :func:`build_publish_package` directly, because the F1.2 reference gate refuses
    to WRITE a document pinning an unresolvable fragment — which is the point. This state is
    reachable the way the gate cannot cover: a document written when the artifact existed, read
    back after it was purged. So the build is handed exactly that: a stored document whose pin
    no longer resolves.
    """
    dead = "frag_" + "ab" * 8
    repo = HybridRepository()
    package = build_publish_package(
        client.app.state.core,
        repo,
        {
            "id": "doc_dead_pin",
            "title": "Cloned landing page",
            "current_version": 1,
            "scene": _web_doc(
                "doc_dead_pin",
                {"id": "clone", "kind": "fragment", "fragment_id": dead, "classes": ""},
            ),
        },
        blobs=make_blob_store(client.app),
        slug="dead-pin",
        site_address=PublicSiteAddress(
            origin="https://acme.pages.test",
            site_path="/dead-pin",
            asset_origin="https://acme.pages.test",
        ),
        workspace_id=repo.workspace_id,
        node_bin=client.app.state.web_export_node_bin,
    )

    assert "lumen-fragment-placeholder" in package.html
    assert package.manifest["fragments"]["missing"] == [dead]
    assert any(dead in warning for warning in package.warnings)


# --------------------------------------------------------------------------- #
# 2 — which picture represents the page
# --------------------------------------------------------------------------- #


def test_the_og_image_is_still_the_first_image_node(client: TestClient, workspace_id: str) -> None:
    """A section's background is not the page's picture: the og:image is the first IMAGE node."""
    background = _upload_asset(client, _png((9, 9, 9)), "hero-bg.png")
    hero = _upload_asset(client, _png((240, 120, 10)), "hero.png")
    document = _seed(
        client,
        _web_doc(
            "doc_og",
            {
                "id": "hero",
                "kind": "section",
                "classes": "",
                "children": ["photo"],
                "background": {"asset_id": background["id"], "fit": "cover"},
            },
            {"id": "photo", "kind": "image", "asset_id": hero["id"], "alt": "Hero", "classes": ""},
            assets={background["id"]: background, hero["id"]: hero},
        ),
    )

    html, _manifest = _publish(client, document["id"], workspace_id, "og-image")

    og = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    assert og is not None, html
    assert hero["media"]["digest"]["value"] in og.group(1)


# --------------------------------------------------------------------------- #
# 3 — the cascade, against a REAL compiled sheet
# --------------------------------------------------------------------------- #

#: `text-center` is a live Tailwind utility. The document authors it, so the compiled sheet
#: really contains `.text-center`, and the fragment styles the same name — the exact collision
#: the diagnostic exists to name, now checkable against the sheet instead of against a guess.
COLLIDING_CSS = ".clone-head { color: #123456 } .text-center { text-align: right }"
COLLIDING_HTML = (
    '<section class="clone-hero text-center">'
    f'<h1 class="clone-head">{CLONE_HEADLINE}</h1>'
    "</section>"
)


def test_fragment_css_lands_before_the_compiled_sheet_and_a_real_collision_is_reported(
    client: TestClient, workspace_id: str
) -> None:
    artifact = _mint_fragment(
        client, workspace_id, html=COLLIDING_HTML, css=COLLIDING_CSS, slots=()
    )
    document = _seed(
        client,
        _web_doc(
            "doc_cascade",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                # the DOCUMENT authors the utility too, so the compiled sheet carries it
                "classes": "text-center",
            },
        ),
    )

    html, manifest = _publish(client, document["id"], workspace_id, "cascade-page")
    site_css = _compiled_sheet(html)

    # The compiled sheet really does declare the colliding utility…
    assert ".text-center" in site_css
    # …the fragment's scoped rule is in the head BEFORE the sheet that outranks it (delivery
    # mode is unlayered, so this ordering IS the tie-break)…
    fragment_rule = html.index(f".{fragment_wrapper_class(artifact.fragment_id)} .text-center")
    compiled_sheet = html.index('<style id="lumen-static-css">')
    assert fragment_rule < compiled_sheet
    # …and the collision is REPORTED, fed the real sheet rather than the document's own tokens.
    assert any(
        artifact.fragment_id in warning and "text-center" in warning
        for warning in manifest["warnings"]
    ), manifest["warnings"]


def test_doc_custom_css_lands_after_the_fragment_css(
    client: TestClient, workspace_id: str
) -> None:
    """A pin on a position, not a change to one: `custom_css` is emitted after the theme's base
    block (which carries the fragment sheet), so at equal specificity the document's own CSS
    wins over a cloned section's."""
    artifact = _mint_fragment(
        client,
        workspace_id,
        rehosted={
            CLONE_HERO_URL: _register(client, _png((10, 20, 30))),
            CLONE_LOGO_URL: _register(client, _png((40, 50, 60))),
        },
        slots=(),
    )
    document = _seed(
        client,
        _web_doc(
            "doc_custom_css",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                "classes": "",
            },
            custom_css=".clone-head { color: #abcdef }",
        ),
    )

    html, _manifest = _publish(client, document["id"], workspace_id, "custom-css-page")

    assert html.index(f".{fragment_wrapper_class(artifact.fragment_id)} .clone-head") < html.index(
        ".clone-head { color: #abcdef }"
    )


# --------------------------------------------------------------------------- #
# 4 — publish, and parity with the editor render
# --------------------------------------------------------------------------- #


def test_the_published_page_renders_the_fragment_and_the_manifest_lists_it(
    client: TestClient, workspace_id: str
) -> None:
    hero_digest = _register(client, _png((10, 20, 30)))
    logo_digest = _register(client, _png((40, 50, 60)))
    artifact = _mint_fragment(
        client,
        workspace_id,
        rehosted={CLONE_HERO_URL: hero_digest, CLONE_LOGO_URL: logo_digest},
    )
    document = _seed(
        client,
        _web_doc(
            "doc_publish",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                "classes": "",
                "slots": {"headline": {"text": ACCOUNT_HEADLINE}},
            },
        ),
    )

    html, manifest = _publish(client, document["id"], workspace_id, "cloned-hero")

    assert fragment_wrapper_class(artifact.fragment_id) in html
    assert ACCOUNT_HEADLINE in html
    assert "lumen-fragment-placeholder" not in html
    assert f".{fragment_wrapper_class(artifact.fragment_id)} .clone-head" in html
    # A published page serves its bytes from the digest route, so the artifact's own assets
    # need no copy — but they must be NAMED, and they must resolve.
    assert f"/asset-store/{logo_digest}" in html
    assert manifest["fragments"]["ids"] == [artifact.fragment_id]
    assert sorted(manifest["fragments"]["asset_digests"]) == sorted(
        {hero_digest, logo_digest}
    )
    assert client.get(f"/asset-store/{logo_digest}").status_code == 200


def test_a_published_page_says_when_a_cloned_asset_has_no_bytes(
    client: TestClient, workspace_id: str
) -> None:
    """The publish path must be loud about bytes a cloned section names and nobody holds.

    An artifact is immutable, but the bytes it names are not immortal: a DSAR erasure, a purge,
    a half-restored backup. Minted with bytes, published without them, the page renders a broken
    image — and the publish path used to say NOTHING, because it copies no files and therefore
    never touched the blobs at all. A clean manifest over a broken page is worse than a broken
    page, so the publish build sweeps custody before it builds and reports the finding.
    """
    hero_digest = _register(client, _png((10, 20, 30)))
    logo_digest = _register(client, _png((40, 50, 60)))
    artifact = _mint_fragment(
        client,
        workspace_id,
        rehosted={CLONE_HERO_URL: hero_digest, CLONE_LOGO_URL: logo_digest},
    )
    document = _seed(
        client,
        _web_doc(
            "doc_publish_purged",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                "classes": "",
            },
        ),
    )
    # The bytes go away AFTER the artifact was minted — the only way this state is reachable.
    assert make_blob_store(client.app).delete(logo_digest) is True

    html, manifest = _publish(client, document["id"], workspace_id, "purged-asset")

    assert manifest["fragments"]["missing_asset_digests"] == [logo_digest]
    assert any(logo_digest[:12] in warning for warning in manifest["warnings"]), manifest[
        "warnings"
    ]
    # The page still publishes, and still names the byte route — the section is otherwise fine,
    # and the reference is the only honest thing left to point at.
    assert f"/asset-store/{logo_digest}" in html
    # The digest that DID survive is not slandered.
    assert hero_digest not in str(manifest["fragments"]["missing_asset_digests"])


def test_the_fragment_region_is_identical_across_render_and_publish(
    client: TestClient, workspace_id: str
) -> None:
    """The phase acceptance's delivery half: ONE document, ONE artifact, two paths.

    "Same" is defined here rather than assumed. The two paths differ in exactly two ways by
    construction, and both are frame, not content:

    * asset URLs — the publish serves `/asset-store/<digest>`, the render route serves an
      absolute origin. Both name the SAME digest, so the digest is what is compared.
    * the editor's instrumentation — so the render route is asked for `mode=delivery`, which is
      the frame the publish uses.

    Everything else — the wrapper class, the node's utility classes, the substituted slot values,
    the artifact's markup byte for byte — must be identical, or a clone means something
    different depending on who is looking at it.
    """
    hero_digest = _register(client, _png((10, 20, 30)))
    logo_digest = _register(client, _png((40, 50, 60)))
    artifact = _mint_fragment(
        client,
        workspace_id,
        rehosted={CLONE_HERO_URL: hero_digest, CLONE_LOGO_URL: logo_digest},
    )
    account_logo = _upload_asset(client, _png((200, 30, 90)), "account-logo.png")
    document = _seed(
        client,
        _web_doc(
            "doc_parity",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                "classes": "w-full py-12",
                "slots": {
                    "headline": {"text": ACCOUNT_HEADLINE},
                    "logo": {"asset": account_logo["id"]},
                },
            },
            assets={account_logo["id"]: account_logo},
        ),
    )
    account_digest = account_logo["media"]["digest"]["value"]

    publish_html, _manifest = _publish(client, document["id"], workspace_id, "parity-page")
    rendered = client.get(
        f"/documents/{document['id']}/web/render", params={"mode": "delivery"}
    )
    assert rendered.status_code == 200, rendered.text
    render_html = rendered.json()["html"]

    def canonical(html: str) -> str:
        region = _fragment_region(html, artifact.fragment_id)
        # Collapse every spelling of "the bytes with digest X" to one token.
        for digest in (account_digest, hero_digest, logo_digest):
            region = re.sub(
                rf"[^\"']*{digest}(\.[a-z0-9]+)?", f"<asset:{digest[:12]}>", region
            )
        return region

    assert canonical(publish_html) == canonical(render_html)
    # …and the comparison is not vacuous: the region really carries the personalized content.
    assert ACCOUNT_HEADLINE in canonical(publish_html)
    assert f"<asset:{account_digest[:12]}>" in canonical(publish_html)


# --------------------------------------------------------------------------- #
# 5 — a payload this build cannot read (phase fix wave, FIX 2)
# --------------------------------------------------------------------------- #


def _fragment_row_over_a_hand_written_payload(
    client: TestClient, workspace_id: str, payload: bytes
) -> str:
    """A registry row whose payload blob is NOT something `parse_fragment_payload` accepts.

    Reachable for real in two ways: a payload written by a newer build (schema 2) that an older
    process then reads, and a blob that a restore or a partial write left truncated. Both are
    "the bytes are there and they are wrong", which is a different failure from "the bytes are
    gone" — and until this wave the two were handled by exactly one of the four render paths.
    """
    from clue_design import web_fragments as dal
    from clue_design.storage import SOURCE_KEY_WEB_FRAGMENT

    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    make_blob_store(client.app).register(
        payload, media_type="application/json; charset=utf-8", source_key=SOURCE_KEY_WEB_FRAGMENT
    )
    fragment_id = "frag_" + digest[:16]
    DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.insert_web_fragment(
            conn,
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            source_kit_id=None,
            source_kit_version=None,
            source_url=SOURCE_URL,
            section_role="hero",
            label=None,
            payload_digest=digest,
            preview_digest=None,
            provenance={},
        )
    )
    return fragment_id


FUTURE_PAYLOAD = json.dumps(
    {
        "schema_version": 3,
        "fragment_id": "frag_" + "0" * 16,
        "html": "<section>from the future</section>",
        "css": "",
        "asset_digests": [],
        "slot_manifest": {},
    }
).encode("utf-8")
TRUNCATED_PAYLOAD = b'{"schema_version": 1, "html": "<section>tru'


@pytest.mark.parametrize(
    "payload,label", [(FUTURE_PAYLOAD, "future schema"), (TRUNCATED_PAYLOAD, "truncated json")]
)
def test_an_unreadable_payload_degrades_on_every_path_and_never_500s(
    client: TestClient, workspace_id: str, payload: bytes, label: str
) -> None:
    """`parse_fragment_payload` refuses fail-closed — correctly. Nothing CAUGHT that refusal.

    The resolver caught `NotFoundError` only, so a blob that exists and cannot be read raised
    `FragmentRefused` straight through the render route (500), the publish (500) and the agent
    turn's composition. The module's own promise is that an artifact which
    will not resolve becomes a placeholder and a loud diagnostic, and it applies whether the
    bytes are absent or unreadable.
    """
    fragment_id = _fragment_row_over_a_hand_written_payload(client, workspace_id, payload)
    # Released like any other, so the document may pin it: this test is about a CORRUPT payload,
    # not about the approval gate.
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=fragment_id, status="approved"
    )
    document = _seed(
        client,
        _web_doc(
            f"doc_unreadable_{len(payload)}",
            {"id": "clone", "kind": "fragment", "fragment_id": fragment_id, "classes": ""},
        ),
    )

    # 1. the editor render route
    rendered = client.get(f"/documents/{document['id']}/web/render")
    assert rendered.status_code == 200, rendered.text
    assert "lumen-fragment-placeholder" in rendered.json()["html"]

    # 2. the published page
    published, publish_manifest = _publish(
        client, document["id"], workspace_id, f"unreadable-{len(payload)}"
    )
    assert "lumen-fragment-placeholder" in published
    assert publish_manifest["fragments"]["missing"] == [fragment_id]

    # 3. the agent turn's composition — the same resolver, called where the database is
    from lumen_api.fragments.render import build_fragment_render_package

    package = build_fragment_render_package(
        client.app.state.storage,
        workspace_id=workspace_id,
        web_doc=client.get(f"/documents/{document['id']}").json()["scene"],
        page_id="home",
    )
    assert package["missing"] == [fragment_id]
    assert package["fragments"] == {}


# --------------------------------------------------------------------------- #
# W7 — the Tailwind scan reads the DOCUMENT, never the clone
# --------------------------------------------------------------------------- #

#: `mt-24` is a live Tailwind utility that this document never authors. It reaches the page only
#: as a class on the CLONED section's own markup — a class name lifted verbatim from somebody
#: else's site.
CLONE_ONLY_UTILITY_HTML = (
    '<section class="clone-hero mt-24">'
    f'<h1 class="clone-head">{CLONE_HEADLINE}</h1>'
    "</section>"
)


def test_a_class_that_only_the_clone_carries_does_not_enter_the_documents_stylesheet(
    client: TestClient, workspace_id: str
) -> None:
    """W7. The compiler scans whatever html it is handed and mints a utility for every class that
    looks like one — so scanning the DELIVERED page let a cloned section decide what the
    DOCUMENT's stylesheet contains. A source-site `mt-24` became a live utility that then applied
    to the document's own markup: a fragment whose styling is supposed to be sealed inside its
    scoped sheet, leaking outward, invisibly, until a document class happened to collide."""
    artifact = _mint_fragment(
        client, workspace_id, html=CLONE_ONLY_UTILITY_HTML, css=".clone-head{color:#123456}",
        slots=(),
    )
    document = _seed(
        client,
        _web_doc(
            "doc_scan",
            {
                "id": "clone",
                "kind": "fragment",
                "fragment_id": artifact.fragment_id,
                "classes": "text-center",
            },
        ),
    )

    html, _manifest = _publish(client, document["id"], workspace_id, "scan-page")
    site_css = _compiled_sheet(html)

    # The clone-only utility is NOT in the document's sheet…
    assert ".mt-24" not in site_css
    # …while the class the DOCUMENT authors still is, so the scan did not simply go blind.
    assert ".text-center" in site_css
    # …and the delivered page still carries the clone's own markup verbatim.
    assert "mt-24" in html
    assert CLONE_HEADLINE in html


def test_the_cascade_report_no_longer_counts_utilities_our_own_scan_invented(
    client: TestClient, workspace_id: str
) -> None:
    """The same change de-noises the collision report: "a live utility" now means one the
    document really asked for, not one the compiler minted from the very fragment being checked."""
    artifact = _mint_fragment(
        client, workspace_id, html=CLONE_ONLY_UTILITY_HTML,
        css=".mt-24 { margin-top: 1px }", slots=(),
    )
    document = _seed(
        client,
        _web_doc(
            "doc_scan_noise",
            {"id": "clone", "kind": "fragment", "fragment_id": artifact.fragment_id},
        ),
    )
    _html, manifest = _publish(client, document["id"], workspace_id, "scan-noise-page")
    assert not [
        warning for warning in manifest["warnings"] if "mt-24" in warning
    ], manifest["warnings"]


def test_a_page_with_no_cloned_sections_is_not_rendered_a_second_time() -> None:
    """F3.4, the guard the F2 wave deferred. The second render exists only to take fragments OUT,
    so on a document that pins none it returns the html already in hand — and asking the engine
    for it costs a whole extra round trip on every publish of every ordinary page."""
    from lumen_api.web_export import _document_only_html

    class _CountingCore:
        def __init__(self) -> None:
            self.renders = 0

        def web_render(self, *args, **kwargs):
            self.renders += 1
            return {"html": "<main>document only</main>"}

    plain = _web_doc("doc_plain", {"id": "copy", "kind": "text", "text": "Hello"})
    core = _CountingCore()
    assert _document_only_html(core, plain, "<main>rendered</main>") == "<main>rendered</main>"
    assert core.renders == 0

    # …and a document that DOES pin one still gets its fragment-free render.
    pinned = _web_doc(
        "doc_pinned",
        {"id": "clone", "kind": "fragment", "fragment_id": "frag_0123456789abcdef"},
    )
    core = _CountingCore()
    assert _document_only_html(core, pinned, "<main>rendered</main>") == (
        "<main>document only</main>"
    )
    assert core.renders == 1


# --- the meta CSP (phase fix wave, walk criterion 4 / final-review X7) ----------------------------


def test_the_meta_csp_carries_no_frame_ancestors_while_the_header_keeps_it():
    """`frame-ancestors` inside a `<meta http-equiv>` CSP is ignored by spec, and the browser
    says so on the console — the walk's ONE console error, and it was ours. The serving header
    (main.py) still enforces it; the meta emitters stop claiming it.

    Since custom-domain publishing S1 the policy takes NO origin: published assets are
    same-origin by construction, so `'self'` covers them on whichever hostname served the page,
    and the CSP can no longer name the host it was built for."""
    from lumen_api.web_export import _delivery_csp

    header = _delivery_csp()
    assert "frame-ancestors 'self'" in header

    meta = _delivery_csp(meta=True)
    assert "frame-ancestors" not in meta
    # Everything else is unchanged between the two shapes.
    assert meta == header.replace("; frame-ancestors 'self'", "")
    # No origin allow-list on either shape — `'self'`, never a hostname.
    assert "script-src 'self' 'unsafe-inline' data:" in header
    assert "script-src 'self' 'unsafe-inline' data:" in meta
    assert "pages.example" not in header
    assert "pages.example" not in meta
