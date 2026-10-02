"""Governed web-publish tools (Part II slice D6 Round A — reference domain 1).

Three writes, one seam. Before D6 the publish sequence was written twice — inline in the HTTP
handler (``main.publish_web_document``) and again, verbatim, inside the batch derive loop
(``main._derive_publish_account``). Both now call :class:`PublishWebDocumentTool` through the
design invoker, so the "static css compile → asset persistence → immutable revision row →
current/previous pointer swap" sequence exists exactly once and is journaled exactly once.

Replay honesty (R-D6-3):

* **publish** is ``OPERATION_IDEMPOTENT``, not domain-idempotent. Its *revision* row IS
  content-addressed (``webpub_<package_digest>``, insert-or-no-op, immutable by trigger) — but
  ``upsert_web_publish`` also rotates ``current -> previous`` in the same statement, so a *new*
  logical operation that republishes byte-identical content still burns the one-step rollback
  buffer. That is pre-existing behaviour the routes' response contract depends on
  (``previous_available`` flips), so D6 declares the truth rather than changing it.
* **unpublish** is ``DOMAIN_IDEMPOTENT``: a status assignment, not a swap — re-running converges.
* **rollback** is ``OPERATION_IDEMPOTENT`` and ``operation_id_required``. It is a genuine SWAP:
  running it twice returns the slug to where it started. It is the single clearest "a blind retry
  corrupts state" write in the design tree, and the reason the A9 key on this route matters most.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "PublishWebDocumentInput",
    "PublishWebDocumentTool",
    "RollbackWebPublishInput",
    "RollbackWebPublishTool",
    "UnpublishWebDocumentInput",
    "UnpublishWebDocumentTool",
    "WebPublishRef",
    "WebPublishStatusRef",
    "publish_web_document",
]

# The public publish-slug contract, duplicated from ``main`` deliberately: this module must not
# import the route module (``main`` imports the toolbelt, not the other way round). The two are
# pinned equal by ``tests/test_write_path_governance.py``.
WEB_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


# ---------------------------------------------------------------------------------------------
# typed reference outputs
# ---------------------------------------------------------------------------------------------


class WebPublishRef(ToolOutput):
    """References to one publish revision + the slug's current pointer state."""

    slug: str
    document_id: str
    #: Nullable only for a legacy row whose revision pin predates content-addressing.
    publish_id: str | None
    doc_version: int
    status: str
    runtime_version: int | None
    manifest_digest: str | None
    package_digest: str | None
    html_digest: str | None
    previous_available: bool
    #: F5 — the site this publish serves. ``routes`` is in document order (``/`` first for
    #: every ordinary site), so a caller can name every address it just published.
    page_count: int = 0
    routes: list[str] = []


class WebPublishStatusRef(ToolOutput):
    slug: str
    status: str


# ---------------------------------------------------------------------------------------------
# the operation core (one implementation, two callers)
# ---------------------------------------------------------------------------------------------


def publish_web_document(
    *,
    repository: Any,
    blobs: Any,
    core: Any,
    node_bin: str,
    document: dict[str, Any],
    slug: str,
    noindex: bool = False,
) -> WebPublishRef:
    """Build, persist and point one publish at ``slug``. The ONE publish write path.

    ``noindex`` is the REQUEST's answer; ``document["web_noindex"]`` is the PAGE's own, stored
    on the row (clone-fidelity F4.3, ruling R-F1). They are OR'd here, at the single write every
    publish path goes through — the plain HTTP route, the governed tool, the ABM batch — which
    is what makes "applied on every republish, whichever route publishes it" a property of the
    system rather than a promise each caller has to keep. The direction is one-way on purpose: a
    publish can only ever ADD the robots meta, and nothing that publishes can take it off.

    The site's public address comes from the hostname registry (custom-domain publishing §6.1,
    reconciliation 2026-09-28): ``site_address(repository, slug)`` on the workspace's always-live
    system hostname, never the request. And the first successful publish LOCKS the workspace's
    system label (F5 R-F5-5): something is now on the air at that address, so its host segment
    stops being editable.
    """

    from .. import web_export
    from ..database import utc_now
    from ..public_pages import site_address

    noindex = bool(noindex) or bool(document.get("web_noindex"))
    address = site_address(repository, slug)
    # Workspace page defaults (custom-domain publishing §4.2), read here — at the ONE publish
    # write path — so every route that publishes picks them up, and so a default set today
    # reaches a page on its next republish rather than only through the screen that set it.
    defaults = repository.pages_defaults()
    package = web_export.build_publish_package(
        core,
        repository,
        document,
        blobs=blobs,
        slug=slug,
        site_address=address,
        workspace_id=repository.workspace_id,
        default_description=defaults["page_description"],
        default_social_preview_sha256=defaults["social_preview_sha256"],
        node_bin=node_bin,
        noindex=noindex,
    )
    web_export.persist_publish_assets(
        blobs,
        package.assets,
        package.manifest["custom_components"].get("assets"),
    )
    publish_id = f"webpub_{package.package_digest}"
    repository.register_web_publish_revision(
        {
            "publish_id": publish_id,
            "slug": slug,
            "document_id": document["id"],
            "doc_version": document["current_version"],
            "html": package.html,
            "html_digest": package.html_digest,
            "manifest": package.manifest,
            "manifest_digest": package.manifest_digest,
            "package_digest": package.package_digest,
            "runtime_version": package.runtime_version,
            "created_at": utc_now(),
            # F5: the whole site, immutable beside the package that produced it. The DAL
            # materializes these into the served per-route pages when the pointer swaps, so a
            # rollback restores the routes as well as the bytes.
            "pages": [
                {
                    "route": page.route,
                    "page_id": page.page_id,
                    "html": page.html,
                    "html_digest": page.html_digest,
                }
                for page in package.pages
            ],
        }
    )
    # F5 R-F5-5: the label stops being editable once a revision exists to be served at it.
    # Idempotent, so every republish (and every account page of a batch) is a no-op that cannot
    # move `locked_at` off the moment the address first went public.
    repository.lock_system_hostname()
    publish = repository.upsert_web_publish(
        slug,
        document["id"],
        document["current_version"],
        package.html,
        package.runtime_version,
        publish_id,
    )
    # A document lives at ONE address. Republishing it under a new slug is a move (the share
    # menu's promise: "the site stays up at its current address until the marketer
    # republishes"), so the address it moved from stops serving — found live 2026-09-30, when a
    # renamed page kept answering at its old slug beside the new one.
    repository.unpublish_other_slugs(document["id"], slug)
    return WebPublishRef(
        slug=slug,
        document_id=document["id"],
        publish_id=publish["publish_id"],
        doc_version=publish["doc_version"],
        status=publish["status"],
        runtime_version=publish["runtime_version"],
        manifest_digest=publish.get("manifest_digest"),
        package_digest=publish.get("package_digest"),
        html_digest=publish.get("html_digest"),
        previous_available=publish["previous_html"] is not None,
        page_count=len(package.pages),
        routes=[page.route for page in package.pages],
    )


# ---------------------------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------------------------


class PublishWebDocumentInput(ToolInput):
    document_id: str
    slug: str
    #: Emit ``<meta name="robots" content="noindex">`` on this page (clone-fidelity F4.3, ruling
    #: R25-4). PER PAGE, defaulting off: CP2's ABM account pages are reachable by their explicit
    #: URL and by nothing else, so they ask for it; a homepage publish never does and stays
    #: byte-identical. It is part of the rendered bytes, so it belongs in the idempotency body —
    #: an indexed and a de-indexed page are two publishes.
    #:
    #: R-F1 added the page's OWN durable ``web_noindex``, and it deliberately does NOT appear
    #: here. It is a property of the document row, exactly like the scene the publish renders,
    #: and the document's content was never in this body either: the body names WHICH document,
    #: and the run reads the row. A same-operation retry still replays its recorded result; a new
    #: operation reads the row as it now stands, which is the whole point of a durable flag.
    noindex: bool = False


class PublishWebDocumentTool(DesignTool):
    """Publish one website-mode document to a workspace-local public slug."""

    name = "design_publish_web"
    version = "1"
    model_description = (
        "Publish a website-mode design document to a public slug. Returns publish references "
        "(slug, publish id, content digests), never the rendered HTML."
    )
    input_model: ClassVar[type[ToolInput]] = PublishWebDocumentInput
    output_model: ClassVar[type[ToolOutput]] = WebPublishRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + slug + content-derived webpub_<package_digest> revision",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the revision row is content-addressed and insert-or-no-op, but the slug's "
            "current/previous pointer rotates on every upsert, so only a same-operation retry "
            "(journal + A9) is a true no-op; the node static-css compile is a local subprocess, "
            "not an external provider"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "slug")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, PublishWebDocumentInput)
        from ..database import NotFoundError

        repository = self.host.repository(ctx.workspace_id)
        if not WEB_SLUG_PATTERN.fullmatch(inputs.slug):
            return (
                PreconditionFailure(
                    reason_code="design_publish_slug_invalid",
                    message=(
                        f"slug {inputs.slug!r} must match ^[a-z0-9][a-z0-9-]{{2,63}}$"
                    ),
                ),
            )
        try:
            document = repository.require_document(inputs.document_id)
        except NotFoundError:
            return (
                PreconditionFailure(
                    reason_code="design_document_not_found",
                    message=f"no design document {inputs.document_id!r} in this workspace",
                ),
            )
        if document.get("doc_kind", "scene") != "web":
            return (
                PreconditionFailure(
                    reason_code="design_document_not_web",
                    message=(
                        f"document {inputs.document_id!r} is not a website-mode document; "
                        "only web documents publish"
                    ),
                ),
            )
        existing = repository.get_web_publish(inputs.slug)
        if existing is not None and existing["document_id"] != inputs.document_id:
            return (
                PreconditionFailure(
                    reason_code="design_publish_slug_taken",
                    message=f"slug {inputs.slug!r} is already published by another document",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, PublishWebDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        return publish_web_document(
            repository=repository,
            blobs=self.host.blobs(ctx.workspace_id),
            core=self.host.need("core"),
            node_bin=self.host.need("web_export_node_bin"),
            document=repository.require_document(inputs.document_id),
            slug=inputs.slug,
            noindex=inputs.noindex,
        )


class UnpublishWebDocumentInput(ToolInput):
    slug: str


class UnpublishWebDocumentTool(DesignTool):
    """Take one published slug offline (a status assignment; the revisions survive)."""

    name = "design_unpublish_web"
    version = "1"
    model_description = (
        "Take a published design slug offline. The immutable publish revisions are retained."
    )
    input_model: ClassVar[type[ToolInput]] = UnpublishWebDocumentInput
    output_model: ClassVar[type[ToolOutput]] = WebPublishStatusRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + slug (design_web_publish.status)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning 'unpublished' twice converges on the same row",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("slug",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, UnpublishWebDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        if repository.get_web_publish(inputs.slug) is None:
            return (
                PreconditionFailure(
                    reason_code="design_publish_not_found",
                    message=f"no publish for slug {inputs.slug!r}",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, UnpublishWebDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        publish = repository.set_web_publish_status(inputs.slug, "unpublished")
        if publish is None:  # lost a race with a concurrent delete; loud, never silent
            raise RuntimeError(f"publish {inputs.slug!r} vanished between check and write")
        return WebPublishStatusRef(slug=inputs.slug, status=publish["status"])


class RollbackWebPublishInput(ToolInput):
    slug: str


class RollbackWebPublishTool(DesignTool):
    """Swap a slug back to its previous publish revision."""

    name = "design_rollback_web_publish"
    version = "1"
    model_description = (
        "Roll one published design slug back to its immediately previous revision. This is a "
        "swap, not an assignment: invoking it twice returns to the starting revision."
    )
    input_model: ClassVar[type[ToolInput]] = RollbackWebPublishInput
    output_model: ClassVar[type[ToolOutput]] = WebPublishRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + slug + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a current<->previous SWAP, so a blind retry is destructive; only the journal's "
            "node-terminal replay and the A9 record make a retry safe"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("slug",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, RollbackWebPublishInput)
        repository = self.host.repository(ctx.workspace_id)
        publish = repository.get_web_publish(inputs.slug)
        if publish is None:
            return (
                PreconditionFailure(
                    reason_code="design_publish_not_found",
                    message=f"no publish for slug {inputs.slug!r}",
                ),
            )
        if publish.get("previous_html") is None:
            return (
                PreconditionFailure(
                    reason_code="design_publish_no_previous",
                    message=f"slug {inputs.slug!r} has no previous publish to roll back to",
                ),
            )
        # R-F1 (T27 review I-1, reproduced live): rollback swaps STORED bytes with no
        # re-render, so a previous revision that predates the durable noindex stamp would be
        # re-served INDEXED while the document's flag still reads True — the robots meta taken
        # off a stamped page with no explicit clearing act, by a tool a model role holds.
        # Removal requires an explicit act (the founder's words), so a rollback that would
        # unindex a stamped page refuses: republish (which applies the flag) or have a human
        # clear the flag first.
        # Deferred import (T27 delta D-3): this module's load-bearing invariant is that it
        # pulls clue_toolbelt + pydantic and nothing else at import time; web_export drags the
        # DAL and FastAPI with it, so the constant is fetched only when the guard actually runs.
        from ..database import NotFoundError
        from ..web_export import ROBOTS_NOINDEX_META

        try:
            document = repository.require_document(str(publish.get("document_id")))
        except NotFoundError:  # unreachable (FK, NOT NULL) — but never fail OPEN on a guard
            document = None
        if (
            isinstance(document, dict)
            and document.get("web_noindex")
            # Refuse only when the rollback would REMOVE the meta from the live page (T27
            # delta D-1): if the current revision does not carry it either, rolling back
            # cannot worsen indexing and a content rollback stays available.
            and ROBOTS_NOINDEX_META in str(publish.get("html") or "")
            and ROBOTS_NOINDEX_META not in str(publish.get("previous_html") or "")
        ):
            return (
                PreconditionFailure(
                    reason_code="design_publish_rollback_would_unindex",
                    message=(
                        f"slug {inputs.slug!r} belongs to a document stamped noindex, and its "
                        "previous revision predates the stamp — rolling back would serve the "
                        "page INDEXED with no explicit clearing act. Republish the current "
                        "document instead (the publish applies the stamp), or have a human "
                        "clear the flag first."
                    ),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RollbackWebPublishInput)
        repository = self.host.repository(ctx.workspace_id)
        result = repository.rollback_web_publish(inputs.slug)
        if not isinstance(result, dict):
            # 'not_found' / 'no_previous' markers — refused by the precondition above, so
            # reaching here means we lost a race. Loud, never a silent-empty success.
            raise RuntimeError(f"web publish rollback refused at write time: {result}")
        return WebPublishRef(
            slug=inputs.slug,
            document_id=result["document_id"],
            publish_id=result["publish_id"],
            doc_version=result["doc_version"],
            status=result["status"],
            runtime_version=result.get("runtime_version"),
            manifest_digest=result.get("manifest_digest"),
            package_digest=result.get("package_digest"),
            html_digest=result.get("html_digest"),
            previous_available=result.get("previous_html") is not None,
        )
