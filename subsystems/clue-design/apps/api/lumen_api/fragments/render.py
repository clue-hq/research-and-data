"""Resolving a page's cloned sections for a render (clone-fidelity F1.3).

The engine render stays PURE: it never reads a registry, never opens a blob, never decides which
artifact a node means. It is handed a map of already-resolved artifacts and a sheet of
already-scoped CSS, and it emits them. This module is the other half of that seam — the API's
answer to "which artifacts does this page need, what are they, and what should worry us about
putting them on the same page as the compiled utilities".

The shape mirrors :mod:`lumen_api.custom_component_runtime`, which does exactly this job for
custom components: a Python walk finds the referenced ids, the API resolves each one out of
durable custody, and an id that will not resolve is REPORTED rather than guessed at — the engine
renders its placeholder, so a document with a dead pin still loads, still edits and still renders
the rest of the page.

**The package travels by value.** The editor render route builds it per request; a web agent turn
builds it once at composition and hands it to the runtime in its config, because the runtime is
fleet work that never reads the API database. Both paths thread the same two things into
``core.web_render`` — ``fragments`` and ``fragment_css`` — so a section cannot render in one
preview and vanish from the other.

**The cascade note.** ``fragment_css`` is spliced through the theme's base layer, which puts it in
the head BEFORE any compiled utility sheet. Fragment selectors are all scoped under
``.lumen-frag-<hex>``, so ordinarily nothing collides. The exception is a cloned class name that
the surrounding document ALSO authors as a utility: the compiled utility then wins the tie and the
cloned section loses that rule. That is a ledgered, accepted risk — :func:`fragment_collision_diagnostics`
names it in the render's diagnostics rather than refusing a render over it.

**The whole order in a rendered head**, since three things now style one page (F1.5, recorded
rather than changed — this is what the engine already does):

1. the theme's base block, with the fragment sheet at its END (so a clone outranks the
   platform's own element defaults);
2. ``doc.custom_css``, emitted after it — so at EQUAL specificity the document's own CSS beats a
   cloned section's, which is the right way round: custom_css is the human's deliberate override;
3. the compiled utilities — in the editor by the ``@layer base`` wrapper, in delivery by source
   order (the export links ``site.css`` after the inline blocks). Either way they win ties, which
   is the plan's ruling and what makes admitting foreign CSS safe at all.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Mapping, Sequence

from clue_storage import StorageBackend

from ..database import NotFoundError
from .refs import ASSET_URL_PREFIX, FRAGMENT_ID_RE, FragmentRefused, fragment_wrapper_class
from .registry import read_web_fragment
from .slots import SLOT_KINDS

logger = logging.getLogger(__name__)

#: Version of the by-value package shape, so a fleet worker running older code against a newer
#: API refuses to improvise rather than silently rendering half a page. Read by
#: :func:`fragment_package_schema_refusal`, which is the ONE place the number is enforced.
#:
#: Bump this only for a shape change a previous reader would MISREAD. Adding a key nobody old
#: looks at is not one — every reader here uses ``.get`` — and bumping for it would refuse
#: perfectly readable packages in flight during a deploy, which is worse than the nothing it
#: would have prevented. (F1.4 added ``slot_kinds`` and F1.5 added ``asset_digests`` on those
#: terms; both stayed at 1.)
FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION = 1

#: Class names in a stylesheet: ``.foo``, ``.foo-bar``, ``.md\:flex``. Deliberately a scan, not a
#: parser — this feeds a DIAGNOSTIC, so a missed exotic selector costs a warning nobody sees, and
#: nothing about the render changes.
_CSS_CLASS_RE = re.compile(r"\.(-?[_a-zA-Z](?:[\w-]|\\.)*)")

#: An artifact-owned byte reference as the sanitizer and the CSS scoper write it: the one public
#: byte route, then a sha256. Anchored on the digest so nothing else in foreign markup matches.
_ARTIFACT_ASSET_RE = re.compile(re.escape(ASSET_URL_PREFIX) + r"([0-9a-f]{64})")


def empty_fragment_render_package() -> dict[str, Any]:
    """A package that resolves nothing — the honest value for a page with no fragments."""
    return {
        "schema_version": FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION,
        "fragments": {},
        "missing": [],
    }


# --------------------------------------------------------------------------- #
# The walks
# --------------------------------------------------------------------------- #


def _page(web_doc: Any, page_id: str) -> dict[str, Any] | None:
    """The named page, else the first one — the fallback ``_custom_component_nodes`` uses, so both
    resolvers agree about which page a render means."""
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    if not isinstance(pages, list):
        return None
    page = next(
        (item for item in pages if isinstance(item, dict) and item.get("id") == page_id),
        None,
    )
    if page is None:
        page = next((item for item in pages if isinstance(item, dict)), None)
    return page if isinstance(page, dict) else None


def web_doc_page_ids(web_doc: Any) -> list[str]:
    """Every page id this document carries, in document order, once each.

    The multi-page walks' index (F5): a caller that must answer for the WHOLE document — the
    agent turn, which composes one package for a run that can move between pages — asks here
    which pages exist rather than spelling one of them as a literal.

    A page with no usable id is skipped: :func:`_page` resolves a page BY id, so an unnamed page
    is not addressable by any of the per-page walks anyway, and inventing an index for it would
    make this the one place in the module that means a different page than everywhere else.
    """
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    if not isinstance(pages, list):
        return []
    ids: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        if isinstance(page_id, str) and page_id and page_id not in ids:
            ids.append(page_id)
    return ids


def _reachable_nodes(web_doc: Any, page_id: str) -> list[dict[str, Any]]:
    """Every node reachable from the page root, in document order, root first.

    Reachable-only on purpose: a node sitting in the map but off the tree is not on the page, so
    resolving its artifact would splice CSS for a section nobody can see.
    """
    page = _page(web_doc, page_id)
    if page is None:
        return []
    nodes = page.get("nodes")
    if not isinstance(nodes, dict):
        return []
    root = page.get("root") if isinstance(page.get("root"), str) else "root"
    pending = [root]
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    while pending:
        node_id = pending.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        found.append(node)
        children = node.get("children")
        if isinstance(children, list):
            pending = [child for child in children if isinstance(child, str)] + pending
    return found


def web_doc_page_section_count(web_doc: Any, page_id: str) -> int:
    """How many top-level bands this page carries — sections AND pinned fragments.

    The behavioural gate probes only fragment-wrapped bands (`.lumen-frag-…`), so a draft
    repair or a composed section riding as a plain document node is invisible to it. This
    count is the denominator that lets the gate SAY so (phase fix wave, final-review X1):
    "measured N of M bands" instead of a silence that reads as full coverage.
    """
    page = _page(web_doc, page_id)
    if page is None:
        return 0
    nodes = page.get("nodes")
    if not isinstance(nodes, dict):
        return 0
    root_id = page.get("root") if isinstance(page.get("root"), str) else "root"
    root = nodes.get(root_id)
    if not isinstance(root, dict):
        return 0
    children = root.get("children")
    if not isinstance(children, list):
        return 0
    count = 0
    for child_id in children:
        child = nodes.get(child_id) if isinstance(child_id, str) else None
        if isinstance(child, dict) and child.get("kind") in ("section", "fragment"):
            count += 1
    return count


def web_doc_fragment_ids(web_doc: Any, page_id: str) -> list[str]:
    """Every fragment artifact id this page references, in document order, once each.

    The Python analog of the engine's ``page_fragment_ids``. Both exist: the engine answers for
    itself, and the API — which is the thing that actually resolves artifacts — must not have to
    call into the engine to learn what to fetch before it can call the engine.
    """
    ids: list[str] = []
    for node in _reachable_nodes(web_doc, page_id):
        if node.get("kind") != "fragment":
            continue
        fragment_id = node.get("fragment_id")
        if isinstance(fragment_id, str) and fragment_id and fragment_id not in ids:
            ids.append(fragment_id)
    return ids


def web_doc_all_fragment_ids(web_doc: Any) -> list[str]:
    """Every fragment artifact id the WHOLE document references — every page's, in page order,
    once each (F5).

    :func:`web_doc_fragment_ids` answers for one page because a RENDER is of one page. A turn is
    not: the agent can author on any page of the document, so the by-value package it is handed
    must cover all of them or a band pinned on the second page comes back as the engine's
    placeholder in the agent's own screenshots.
    """
    ids: list[str] = []
    for page_id in web_doc_page_ids(web_doc):
        for fragment_id in web_doc_fragment_ids(web_doc, page_id):
            if fragment_id not in ids:
                ids.append(fragment_id)
    return ids


def web_doc_class_tokens(web_doc: Any, page_id: str) -> set[str]:
    """Every class token the DOCUMENT authors on this page.

    This is the utility vocabulary a compiled ``site.css`` is built from (and the vocabulary the
    editor's Tailwind runtime generates), so it is the live-utility side of the collision check.
    """
    tokens: set[str] = set()
    for node in _reachable_nodes(web_doc, page_id):
        classes = node.get("classes")
        if isinstance(classes, str):
            tokens.update(classes.split())
    return tokens


def css_class_names(css: str) -> set[str]:
    """Every class name a stylesheet declares. A scan (see ``_CSS_CLASS_RE``), not a parser."""
    return {match.group(1) for match in _CSS_CLASS_RE.finditer(css or "")}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def build_fragment_render_package(
    storage: StorageBackend,
    *,
    workspace_id: str,
    web_doc: Any,
    page_id: str,
) -> dict[str, Any]:
    """Resolve every fragment this page references into one by-value package.

    Fail-SOFT, deliberately and unlike creation: an id this workspace cannot resolve — deleted,
    another tenant's, or a purged payload — lands in ``missing`` and the engine renders its
    placeholder. Refusing the whole render instead would make one dead pin cost the entire page,
    and the F1.2 gate exists precisely so a document with a dead pin stays usable.

    **Unreadable counts as unresolvable.** :func:`parse_fragment_payload` refuses fail-closed on
    a blob that is not a payload this build understands — truncated JSON, a missing key, a
    ``schema_version`` from a newer writer — and that refusal used to travel straight out of
    here, past every caller, as a 500 on all four render paths. "The bytes are wrong" is a
    different fault from "the bytes are gone" but it is the SAME question for a page: this
    section cannot be shown. So both answers are the same one, and both are visible.

    They are the same answer to the PAGE and two different answers to an operator, though, and
    the log keeps them apart: a purged blob is a custody problem, a payload this build cannot
    parse is a schema or a write problem, and "the section did not render" is the same sentence
    for both. The refusal's own ``code`` is what tells them apart, so it is what gets logged.
    """
    package = empty_fragment_render_package()
    for fragment_id in web_doc_fragment_ids(web_doc, page_id):
        if not FRAGMENT_ID_RE.fullmatch(fragment_id):
            # Not an artifact address at all; there is nothing to look up. The
            # engine re-checks the same grammar and renders its placeholder.
            package["missing"].append(fragment_id)
            continue
        try:
            loaded = read_web_fragment(
                storage, workspace_id=workspace_id, fragment_id=fragment_id
            )
        except NotFoundError:
            logger.warning(
                "fragment_unresolved fragment_id=%s workspace_id=%s reason=fragment.not_held",
                fragment_id,
                workspace_id,
            )
            package["missing"].append(fragment_id)
            continue
        except FragmentRefused as refusal:
            logger.warning(
                "fragment_unresolved fragment_id=%s workspace_id=%s reason=%s detail=%s",
                fragment_id,
                workspace_id,
                refusal.code,
                refusal.message,
            )
            package["missing"].append(fragment_id)
            continue
        package["fragments"][fragment_id] = {
            "html": loaded.html,
            "css": loaded.css,
            "slot_kinds": slot_kinds(loaded.slot_manifest),
            # F3.1: is this a REPAIR (a fragment we composed) rather than a harvested clone? The
            # collision report below is the only reader, and it needs the distinction because a
            # repair's stylesheet is written in the platform's OWN class vocabulary — see
            # `fragment_class_collisions`.
            "derived": bool(loaded.row.get("derived_from")),
            # F1.5: the digests of every byte the ARTIFACT displays (its rehosted images and
            # fonts). The engine never sees these — the markup already names them as
            # `/asset-store/<digest>` — but a delivery build must put those bytes in the zip,
            # and the artifact is the only thing that knows which they are.
            "asset_digests": list(loaded.asset_digests),
        }
    return package


def build_fragment_render_package_for_document(
    storage: StorageBackend,
    *,
    workspace_id: str,
    web_doc: Any,
) -> dict[str, Any]:
    """The same package, resolved for EVERY page of the document (F5).

    A render is of one page, so :func:`build_fragment_render_package` is the primitive. A TURN is
    of a document — the agent may author on any page during it — so the by-value package a turn
    carries has to cover every page, or a band pinned on the second page renders as the engine's
    placeholder in the agent's own screenshots and the visual reviewer judges a hole.

    **The merge.** ``fragments`` is a dict union: resolution is keyed on ``(workspace, fragment
    id)`` and never consults the page, so the same id resolves to the same record on every page
    it is pinned to and the duplicate is a no-op. ``missing`` is an ordered union — a dead pin is
    reported once for the document, not once per page that carries it. Every OTHER key a page
    package carries is copied through as-is (today that is only ``schema_version``, a constant),
    so a later key added to the primitive travels out of here instead of being silently dropped
    by a variant that enumerated the shape.
    """
    package = empty_fragment_render_package()
    for page_id in web_doc_page_ids(web_doc):
        page_package = build_fragment_render_package(
            storage,
            workspace_id=workspace_id,
            web_doc=web_doc,
            page_id=page_id,
        )
        for key, value in page_package.items():
            if key not in ("fragments", "missing"):
                package[key] = value
        package["fragments"].update(page_package["fragments"])
        for fragment_id in page_package["missing"]:
            if fragment_id not in package["missing"]:
                package["missing"].append(fragment_id)
    return package


def slot_kinds(slot_manifest: Mapping[str, Any]) -> dict[str, str]:
    """``{slot key: kind}`` from an artifact's slot manifest — the half of the manifest the ENGINE
    needs (F1.4).

    The engine substitutes a node's slot values into the artifact's markers, and it cannot decide
    what a value MEANS without this: an href and a paragraph both ride the node's ``text`` tag
    (see :data:`lumen_api.fragments.slots.SLOT_KIND_TO_NODE_TAG`), so without the kind a link
    target could be written into a heading. The fallbacks stay behind — they are already in the
    markup, which is where the engine reads them from.

    Unknown kinds are dropped rather than passed on: the engine's enum is closed, and a value
    whose kind it cannot name falls back loudly instead of failing the whole render.
    """
    return {
        str(key): str(entry.get("kind"))
        for key, entry in (slot_manifest or {}).items()
        if isinstance(entry, Mapping) and str(entry.get("kind")) in SLOT_KINDS
    }


def fragment_package_schema_refusal(package: Any) -> dict[str, Any] | None:
    """A diagnostic when this package's shape is not one this code can read, else ``None``.

    The by-value package rides inside a turn's config, so the process that READS it can be
    running older code than the API that BUILT it — a fleet worker draining a queue across a
    deploy. Reading a shape it does not know with rules it does have is improvisation, and the
    honest move is the one the render arm already makes for an unresolvable pin: drop the map,
    render placeholders, and say why. A caller that refuses gets a page with visible holes and a
    named reason instead of a page that is quietly wrong.

    An EMPTY/absent package is not a version problem — it is a page with no fragments — so it
    passes.
    """
    if not isinstance(package, Mapping) or not package:
        return None
    version = package.get("schema_version")
    if version == FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION:
        return None
    return {
        "severity": "warning",
        "phase": "web",
        "code": "fragment.package_schema_unknown",
        "message": (
            f"the cloned-section package for this render carries schema_version {version!r}, "
            f"and this build reads {FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION}. Every cloned "
            "section renders its placeholder rather than being read under the wrong rules."
        ),
        "subject": None,
        "hint": (
            "The process rendering this page is older than the one that resolved its "
            "artifacts. Re-run the turn on an up-to-date worker."
        ),
    }


def rebase_artifact_assets(text: str, asset_base_url: str | None) -> str:
    """Point an artifact's OWN asset references at the origin THIS render can fetch.

    An artifact stores its bytes as ``/asset-store/<digest>`` — root-relative, deliberately: it
    is immutable and shared, so baking in an origin would make it wrong for every caller but
    one. Root-relative is also unresolvable in the two surfaces the previews use (Playwright's
    ``set_content``, the editor's srcDoc iframe), which have no document origin to resolve
    against. So every image and CSS background inside a cloned section 404'd there, while a
    SLOT-bound asset — which resolves through ``doc.assets`` and the engine's own
    ``asset_base_url`` — rendered fine. One asset kind worked, the other did not, and only the
    working one was ever probed.

    **This rebase belongs at the API layer and must never move into the engine's render arm.**
    The export renders with ``asset_base_url="assets"``; an engine-side rebase would emit
    ``assets/<digest>`` into the artifact's markup, and ``web_export``'s
    ``html.replace("/asset-store/<digest>", …)`` would then silently match nothing — the zip
    would ship the bytes as orphans under paths no element names. The delivery paths therefore
    pass no base at all and keep the stored reference exactly as it is: publish serves that
    route directly, and the export rewrites it to a relative path itself.

    Only ``/asset-store/`` immediately followed by a 64-hex digest is touched, so nothing else
    in somebody else's markup can be caught by it.
    """
    if not asset_base_url:
        return text
    base = asset_base_url.rstrip("/")
    if base == ASSET_URL_PREFIX.rstrip("/"):
        # Already the stored spelling — a no-op rather than a doubling.
        return text
    return _ARTIFACT_ASSET_RE.sub(lambda match: f"{base}/{match.group(1)}", text)


def fragment_render_map(
    package: Mapping[str, Any],
    fragment_ids: Sequence[str],
    asset_base_url: str | None = None,
) -> dict[str, dict[str, str]]:
    """The engine's ``RenderOptions.fragments`` — markup plus each slot's kind.

    CSS is deliberately absent: it reaches the page through the head, once per fragment, not once
    per node that pins it. The slot kinds ride here rather than in the head because they are read
    per node, at the moment the node's own values are applied (F1.4).

    ``asset_base_url`` rebases the artifact's own byte references (see
    :func:`rebase_artifact_assets`). Preview callers pass their absolute origin; delivery
    callers pass nothing.
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    return {
        fragment_id: {
            "html": rebase_artifact_assets(
                str(fragments[fragment_id].get("html") or ""), asset_base_url
            ),
            "slot_kinds": dict(fragments[fragment_id].get("slot_kinds") or {}),
        }
        for fragment_id in _unique(fragment_ids)
        if isinstance(fragments.get(fragment_id), Mapping)
    }


def fragment_css_sheet(
    package: Mapping[str, Any],
    fragment_ids: Sequence[str],
    asset_base_url: str | None = None,
) -> str | None:
    """The concatenated scoped CSS for these fragments, or ``None`` when there is none.

    Sorted by fragment id rather than laid out in document order: every rule is scoped, so the
    blocks cannot interact, which makes document order a source of byte churn (moving a section
    would rewrite the sheet) with no cascade meaning. Each block keeps a source comment naming its
    artifact, so a rule in a rendered head can be traced back to the fragment it came from.

    The sheet carries byte references too — a cloned hero's background image lives here, not in
    the markup — so it is rebased on exactly the same terms as the markup.
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    blocks: list[str] = []
    for fragment_id in sorted(set(fragment_ids)):
        record = fragments.get(fragment_id)
        if not isinstance(record, Mapping):
            continue
        css = str(record.get("css") or "").strip()
        if not css:
            continue
        blocks.append(
            f"/* fragment {fragment_id} */\n{rebase_artifact_assets(css, asset_base_url)}"
        )
    return "\n".join(blocks) if blocks else None


# --------------------------------------------------------------------------- #
# The cascade diagnostic
# --------------------------------------------------------------------------- #


def fragment_class_collisions(
    package: Mapping[str, Any],
    fragment_ids: Sequence[str],
    live_classes: Iterable[str],
) -> list[tuple[str, list[str]]]:
    """``(fragment_id, colliding class names)`` for each fragment the utilities can overrule.

    A collision is a class the fragment's own CSS styles that the document ALSO authors as a
    utility class. The compiled utility lands after the fragment CSS, so it wins — the cloned
    section quietly loses that rule. The wrapper class is excluded: it is ours, it is on the
    wrapper by construction, and reporting it would fire on every fragment ever rendered.

    **A REPAIR is excluded whole** (F3.1, ruling R-I1), and the reason is that for a repair this
    report would be false rather than merely noisy. Until F3.1 every fragment carried somebody
    else's stylesheet, so a shared class name was a coincidence worth naming. A repair's sheet is
    a compile of the platform's own vocabulary against the document's own theme, so it declares
    `.rounded-card`, `.py-section`, `.gap-stack` — a dozen classes the document declares too, on
    every single repair. Two things would then be wrong at once: the report would fire
    systematically on sections that are fine, and its claim would be untrue, because the value
    the utility "wins" with is the value the fragment already had, compiled from the same theme
    by the same compiler.

    A package written by an older build carries no ``derived`` key and reads as ``False``, which
    is the pre-F3.1 behaviour — the honest default for a reader that cannot tell.
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    live = {token for token in live_classes if token}
    collisions: list[tuple[str, list[str]]] = []
    for fragment_id in _unique(fragment_ids):
        record = fragments.get(fragment_id)
        if not isinstance(record, Mapping):
            continue
        if record.get("derived"):
            continue
        declared = css_class_names(str(record.get("css") or ""))
        try:
            declared.discard(fragment_wrapper_class(fragment_id))
        except FragmentRefused:
            # A malformed id has no wrapper class to exclude — and no artifact
            # either, so this loop will not reach here in practice.
            pass
        shared = sorted(declared & live)
        if shared:
            collisions.append((fragment_id, shared))
    return collisions


def fragment_collision_diagnostics(
    package: Mapping[str, Any], web_doc: Any, page_id: str
) -> list[dict[str, Any]]:
    """The collision report, in the engine's diagnostic shape so it merges into one list.

    A warning, never a refusal (the ledgered ruling): the render is correct, one rule of one
    cloned section may not be. Naming it is what lets a producer rename the class instead of
    discovering the loss in a screenshot.
    """
    fragment_ids = web_doc_fragment_ids(web_doc, page_id)
    live = web_doc_class_tokens(web_doc, page_id)
    diagnostics: list[dict[str, Any]] = []
    for fragment_id, classes in fragment_class_collisions(package, fragment_ids, live):
        joined = ", ".join(f"`{name}`" for name in classes)
        diagnostics.append(
            {
                "severity": "warning",
                "phase": "web",
                "code": "fragment.class_collision",
                "message": (
                    f"fragment `{fragment_id}` styles {joined}, which the page also authors as "
                    "utility class(es). Compiled utilities are applied after fragment CSS, so "
                    "the utility wins and the cloned section loses those rules."
                ),
                "subject": None,
                "hint": (
                    "Rename the colliding class on the document's own nodes, or accept the "
                    "utility's value for that property."
                ),
            }
        )
    return diagnostics


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = [
    "FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION",
    "build_fragment_render_package",
    "build_fragment_render_package_for_document",
    "css_class_names",
    "empty_fragment_render_package",
    "fragment_class_collisions",
    "fragment_collision_diagnostics",
    "fragment_css_sheet",
    "fragment_package_schema_refusal",
    "fragment_render_map",
    "rebase_artifact_assets",
    "slot_kinds",
    "web_doc_all_fragment_ids",
    "web_doc_class_tokens",
    "web_doc_fragment_ids",
    "web_doc_page_ids",
]
