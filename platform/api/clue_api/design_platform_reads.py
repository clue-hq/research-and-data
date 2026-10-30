"""What the design agent may read from the platform mid-turn (design note 2026-09-19).

Founder ruling: the brief stays the primary channel; the target account is reached by TOOLS, not
files; scope is the project, never a tag; the seller's knowledge is accessible as files. This
module is the platform half. It is composed at the composition root (``fleet_main``) with the
worker's shared ``ToolInvoker`` and storage, and handed to the design turn host — the same shape
as the scoped-preference resolver, for the same reason: the design runtime never opens the
platform database and imports none of this.

Three of the four reads are the governed tools head-of-abm uses (``read_project_accounts@1``,
``read_account_research@2``, ``read_claims@1``), invoked through the journaled invoker under the
turn's workspace, so a design turn's reads are receipts like any other. ``read_account_research``
is asked for at ``@2`` and nowhere else at ``@1``: ``@1`` is granted to no role, and ``@2`` is the
paged contract the design role was granted (Task 1, ``design@v2``).

Since 2026-09-22 the seam also carries ONE spend tool, ``web_search@1`` — the open-web search both
roles hold, used last. It rides the same invoker and the same fresh-operation-id rule; its ledger
row is workspace spend because the invoker's context carries no project.

The fourth is not a tool: it hands over the seller's brand-knowledge documents as pinned for the
turn that OPENED the leg (``get_knowledge_pin`` by the bundle's ``opened_by_turn_id``), plus the
project's confirmed product set and the path of the ICP it pinned — the same set head-of-abm's own
turn composed from, at the same versions. A leg whose opening turn pinned nothing gets an honestly
empty set, never a failure: a design turn that cannot find the seller's files still has its brief.

The project-context read exposes only the opening turn's pinned project instructions and
decisions, with their exact text and source references. This is not a live project view and
does not synthesize new instructions from the delegation brief. It stays behind the injected
adapter like every other read.

**Every read is its own logical operation.** A9 idempotency caches on
``(execution, operation_id)``, so a read that reused one operation id would have page two answered
by page one's receipt. Each call therefore mints a fresh operation id, which is correct rather than
wasteful: these tools are ``EFFECT_FREE``, so nothing is spent twice by running them twice.

**Spilled receipts do not arise here.** The ``spilled_to`` stub (ledger ruling PRE-1) is built by
``agent_execution_wiring``'s receipt builder, which sits ABOVE the invoker and names a file in the
deepagent's own thread workspace (``reads/<operation_id>.json``), not a storage artifact key. This
module calls ``ToolInvoker.invoke`` directly and returns ``result.references`` — the whole,
unspilled page — so there is nothing to inline and no receipt to rewrite. The page's own
``next_offset`` is the only continuation the design side needs.

Leg turns only: a direct editor turn has no ``leg`` block and gets ``None``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_agents.attachment_images import viewable_image
from clue_agents.attachment_names import safe_attachment_name
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.brand_knowledge_context import (
    PinnedDocument,
    confirmed_icp_for_project,
    get_knowledge_pin,
    read_pinned_documents,
)
from clue_api.design_loop_bridge import PlatformLoopBridge
from clue_api.project_context_files import get_project_files_pin, read_pinned_project_files
from clue_core import operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_design.envelopes import DesignTurnEnvelope
from clue_obs import get_logger
from clue_spine import current_project_product_set
from clue_storage import StorageBackend
from clue_toolbelt import PreconditionFailed, ToolContext, ToolInvoker

log = get_logger("clue_api.design_platform_reads")

_T = TypeVar("_T")

#: The one read asked for at a version other than its default alias (ruling T1-1).
_PINNED_VERSIONS = {"read_account_research": "3"}


class DesignPlatformReadError(RuntimeError):
    """One code, the way the memory runtime's errors are: ``platform_loop`` /
    ``loop_unavailable`` / ``timeout`` / ``read_failed``, plus ``refused:<codes>`` — a governed
    read's own machine-readable refusal (``refused:overview_not_written``), comma-joined when a
    tool names more than one. Never carries tool inputs or outputs in its message: a read's
    refusal is a code the design side can act on, not a payload it can quote."""


@dataclass(frozen=True)
class SellerDocument:
    """One of the seller's knowledge documents, as the design side reads it: a path, what it is,
    which version it is, and its markdown with the front matter already split off."""

    path: str
    kind: str
    version: int
    status: str
    body_text: str


@dataclass(frozen=True)
class SellerKnowledge:
    """The seller's own context for this leg: the pinned document set, the project's confirmed
    ICP path, and the product set it confirmed."""

    documents_sha256: str | None
    documents: tuple[SellerDocument, ...]
    confirmed_icp_path: str | None
    product_set: dict[str, Any] | None


EMPTY_SELLER_KNOWLEDGE = SellerKnowledge(None, (), None, None)


#: How many bytes of the thread's files one design run reads: this message's files first. The same
#: figure as the design folder's budget (``lumen_agent.platform_reads``) and a message's total.
THREAD_ATTACHMENTS_MAX_BYTES = 157_286_400


@dataclass(frozen=True)
class AttachedFile:
    """One file sent in the leg's chat thread (spec 2026-10-30 §3.3).

    ``current`` is true when the message this turn answers carried it. ``viewable`` is what an
    agent may look at and a design library may hold: the image itself for PNG, JPEG, WebP and GIF,
    a PNG copy for HEIC, AVIF, TIFF, BMP and ICO, the drawing itself for SVG, and ``None`` for
    every other file. ``unavailable`` names why the bytes were not read (``erased``,
    ``missing``, ``over_budget``); such a file carries no bytes.
    """

    filename: str
    media_type: str
    sha256: str
    data: bytes
    current: bool
    viewable: tuple[bytes, str] | None
    unavailable: str | None


def _viewable(data: bytes, media_type: str) -> tuple[bytes, str] | None:
    if media_type.lower() == "image/svg+xml":
        return data, "image/svg+xml"
    return viewable_image(data, media_type)


def _seller_document(document: PinnedDocument) -> SellerDocument:
    return SellerDocument(
        path=document.ref.path,
        kind=document.ref.kind,
        version=document.ref.version,
        status=document.ref.status,
        body_text=document.body_text,
    )


class DesignPlatformReads:
    """Sync, worker-thread-callable. Every governed read returns JSON-safe dicts; every failure is
    a :class:`DesignPlatformReadError` carrying one code."""

    def __init__(
        self,
        *,
        envelope: DesignTurnEnvelope,
        invoker: ToolInvoker,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        bridge: PlatformLoopBridge,
    ) -> None:
        self._envelope = envelope
        self._invoker = invoker
        self._storage = storage
        self._conn_factory = conn_factory
        self._bridge = bridge
        self._attachments: tuple[AttachedFile, ...] | None = None

    # --- the governed reads -------------------------------------------------------------------

    def _invoke(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            result = await self._invoker.invoke(
                name,
                body,
                ToolContext(
                    workspace_id=self._envelope.workspace_id,
                    # The leg's project scopes project-scoped reads (the account overview).
                    project_id=self._envelope.project_id,
                    actor="agent",
                    conn_factory=self._conn_factory,
                    # A read is not idempotent work: every call is its own operation, so the A9
                    # journal never replays an earlier page as the answer to a later one.
                    operation_id=operation_id_from_key(
                        f"{self._envelope.run_id}:{uuid4().hex}", "design-platform-read@1"
                    ),
                ),
                version=_PINNED_VERSIONS.get(name),
            )
            return dict(result.references)

        try:
            return self._guarded(call, tool=name)
        except PreconditionFailed as refused:
            # Ruling T2-1: a governed read's REFUSAL is an answer, not a failure. "this account's
            # overview has not been written yet" is a true sentence the design agent can act on
            # (read the claims instead); collapsing it into ``read_failed`` would make an honest
            # empty look like a broken platform. The reason codes are machine-readable and carry
            # no tool inputs, so they may cross the seam where the message may not.
            codes = ",".join(refused.reason_codes)
            log.info("design_platform_reads.read_refused", tool=name, reason_codes=codes)
            raise DesignPlatformReadError(f"refused:{codes}") from None

    def _guarded(self, operation: Callable[[], Coroutine[Any, Any, _T]], *, tool: str) -> _T:
        try:
            return self._bridge.wait(operation)
        except (DesignPlatformReadError, PreconditionFailed):
            # The bridge's own four codes, and a refusal its caller classifies, both pass through.
            raise
        except Exception:
            # A pydantic error or a DB adapter may put inputs into the exception string; the
            # design side gets the code and the platform keeps the trace.
            log.warning("design_platform_reads.read_failed", tool=tool, exc_info=True)
            raise DesignPlatformReadError("read_failed") from None

    def read_project_accounts(
        self, *, query: str | None = None, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """The leg's project's accounts — never a workspace-wide list and never a tag."""

        project_id = self._envelope.project_id
        if project_id is None:
            raise DesignPlatformReadError("read_failed")
        body: dict[str, Any] = {"project_id": project_id, "offset": offset, "limit": limit}
        if query:
            body["query"] = query
        return self._invoke("read_project_accounts", body)

    def read_account_research(
        self,
        *,
        account_entity_id: str,
        section: str = "overview",
        field_prefix: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """One account's written overview, or its claims — ``@2``'s paged contract."""

        body: dict[str, Any] = {
            "account_entity_id": account_entity_id,
            "section": section,
            "offset": offset,
        }
        if field_prefix:
            body["field_prefix"] = field_prefix
        if limit is not None:
            body["limit"] = limit
        return self._invoke("read_account_research", body)

    def read_claims(
        self,
        *,
        entity_id: str,
        field_prefix: str | None = None,
        tier: int | None = None,
        verification_status: str | None = None,
        since: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The live claims about one account or contact, gated as the account pages gate them."""

        body: dict[str, Any] = {"entity_id": entity_id, "offset": offset}
        for key, value in (
            ("field_prefix", field_prefix),
            ("tier", tier),
            ("verification_status", verification_status),
            ("since", since),
            ("limit", limit),
        ):
            if value is not None:
                body[key] = value
        return self._invoke("read_claims", body)

    def read_cited_claims(self, *, entity_id: str, claim_ids: list[str]) -> dict[str, Any]:
        """The claims an account's research cites, by id, each with its disposition.

        ``read_cited_claims@1`` (Contract 5): ``served`` claims come back in ``claims``; every id
        gets ``served``, ``held:<reason>`` or ``not_found`` in ``dispositions``. At most 200 ids
        per call; the caller chunks.
        """

        return self._invoke(
            "read_cited_claims", {"entity_id": entity_id, "claim_ids": list(claim_ids)}
        )

    # --- original project instructions --------------------------------------------------------

    def project_design_context(self) -> dict[str, Any]:
        """Exact opening-turn sources behind a delegated brief, never a live project view.

        Only the canonical instruction and decision files cross this seam. Account research
        still travels through the governed reads above; no project-wide file dump is exposed.
        """
        bundle = self._envelope.config.get("delegation_bundle")
        opened_by = bundle.get("opened_by_turn_id") if isinstance(bundle, dict) else None
        workspace_id = self._envelope.workspace_id
        project_id = self._envelope.project_id
        empty: dict[str, Any] = {
            "status": "not_pinned",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_turn_id": str(opened_by) if opened_by else None,
            "source_pin_sha256": None,
            "is_live_project_view": False,
            "files": [],
        }
        if not opened_by or project_id is None:
            return empty

        async def read() -> dict[str, Any]:
            async with self._conn_factory() as conn:
                pin = await get_project_files_pin(
                    conn, workspace_id=workspace_id, turn_id=UUID(str(opened_by))
                )
                if pin is None:
                    return empty
                if pin.project_id != project_id:
                    raise DesignPlatformReadError("read_failed")
                selected = tuple(
                    ref for ref in pin.files if ref.path in {"instructions.md", "decisions.md"}
                )
                # A bounded read view, not a new durable pin. The reported source digest
                # continues to identify the ORIGINAL full opening-turn pin.
                documents = await read_pinned_project_files(
                    conn, self._storage, pin=pin.model_copy(update={"files": selected})
                )
            return {
                **empty,
                "status": "available",
                "source_pin_sha256": pin.files_sha256,
                "pinned_at": pin.pinned_at.isoformat(),
                "files": [
                    {**doc.ref.model_dump(mode="json"), "body_text": doc.body.decode("utf-8")}
                    for doc in documents
                ],
            }

        return self._guarded(read, tool="project_design_context")

    # --- the one spend tool on this seam --------------------------------------------------------

    def web_search(
        self,
        *,
        query: str,
        num_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
    ) -> dict[str, Any]:
        """One open-web search (``web_search@1``), used last. The first SPEND tool on this seam:
        the ledger row it lands is workspace spend under the turn's identity, and — like the reads —
        every call is its own operation, so a second search is never answered by the first's
        receipt.

        The tool declares a ``project`` pin, which the execution layer asserts on head-of-abm's
        path. This seam invokes outside an execution, where no pin is checked, so the seam holds
        the same line itself: a leg with no project cannot spend — ``project_unbound``, before
        the invoker is reached."""

        if self._envelope.project_id is None:
            raise DesignPlatformReadError("project_unbound")
        body: dict[str, Any] = {"query": query, "num_results": num_results}
        for key, value in (
            ("include_domains", include_domains),
            ("exclude_domains", exclude_domains),
            ("start_published_date", start_published_date),
            ("end_published_date", end_published_date),
        ):
            if value is not None:
                body[key] = value
        return self._invoke("web_search", body)

    # --- the chat thread's files ----------------------------------------------------------------

    def thread_attachments(self) -> tuple[AttachedFile, ...]:
        """The files the envelope lists, with their bytes, read once for the run.

        The list itself was decided when the turn was offered (newest per filename, frozen in
        the envelope); this only fetches bytes. A file whose bytes were erased or are gone is still
        named, so the agent can say so instead of guessing.
        """

        if self._attachments is not None:
            return self._attachments
        listed = self._envelope.config.get("attachments")
        if not isinstance(listed, list) or not listed:
            self._attachments = ()
            return self._attachments
        workspace_id = self._envelope.workspace_id

        async def read_one(key: str) -> tuple[bytes, str | None]:
            async with self._conn_factory() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT erased_at IS NOT NULL OR purged_at IS NOT NULL AS gone "
                            "FROM artifact WHERE storage_key = :key AND workspace_id = :ws"
                        ),
                        {"key": key, "ws": workspace_id},
                    )
                ).one_or_none()
            if row is None:
                return b"", "missing"
            if row.gone:
                return b"", "erased"
            return await self._storage.get(key), None

        # Review I-4: the budget is spent on this message's files first, and decided from the
        # listed sizes before any byte is read; a file past it is named, never fetched. Each file is
        # its own read, so one that cannot be read is one unavailable file, not an empty folder.
        ordered = sorted(listed, key=lambda item: not item.get("current"))
        spent = 0
        files: dict[int, AttachedFile] = {}
        for item in ordered:
            key = str(item["artifact_key"])
            media_type = str(item["media_type"])
            data: bytes = b""
            unavailable: str | None = None
            size = int(item.get("byte_count") or 0)
            if spent + size > THREAD_ATTACHMENTS_MAX_BYTES:
                unavailable = "over_budget"
            else:
                try:
                    data, unavailable = self._guarded(
                        lambda key=key: read_one(key), tool="thread_attachments"
                    )
                except DesignPlatformReadError:
                    log.warning("design_platform_reads.attachment_unreadable", key=key)
                    unavailable = "missing"
                if unavailable is None:
                    spent += len(data)
            files[id(item)] = AttachedFile(
                filename=safe_attachment_name(str(item["filename"])),
                media_type=media_type,
                sha256=str(item["sha256"]),
                data=data,
                current=bool(item.get("current")),
                # Decoded here, on the calling worker thread, never on the platform's loop.
                viewable=None if unavailable else _viewable(data, media_type),
                unavailable=unavailable,
            )
        self._attachments = tuple(files[id(item)] for item in listed)
        return self._attachments

    # --- the seller ---------------------------------------------------------------------------

    def seller_knowledge(self) -> SellerKnowledge:
        """The opening turn's pinned brand documents, plus what this project confirmed."""

        bundle = self._envelope.config.get("delegation_bundle")
        opened_by = bundle.get("opened_by_turn_id") if isinstance(bundle, dict) else None
        if not opened_by:
            return EMPTY_SELLER_KNOWLEDGE
        workspace_id = self._envelope.workspace_id
        project_id = self._envelope.project_id

        async def read() -> SellerKnowledge:
            async with self._conn_factory() as conn:
                pin = await get_knowledge_pin(
                    conn, workspace_id=workspace_id, turn_id=UUID(str(opened_by))
                )
                if pin is None:
                    return EMPTY_SELLER_KNOWLEDGE
                documents = await read_pinned_documents(conn, self._storage, pin=pin)
                product_set = None
                icp_pin = None
                if project_id is not None:
                    product_set = await current_project_product_set(
                        conn, workspace_id=workspace_id, project_id=project_id
                    )
                    # Founder rulings 2026-09-10: what this project's ICP *is* comes from its
                    # durable pin, not from whatever the brand's documents currently claim — the
                    # same resolution the head-of-abm turn makes.
                    icp_pin = await current_project_icp_pin(
                        conn, workspace_id=workspace_id, project_id=project_id
                    )
            icp = confirmed_icp_for_project(
                documents,
                pinned_document_id=None if icp_pin is None else icp_pin.document_id,
            )
            # ``ConfirmedIcpRef`` identifies the document, not its path; the path is the pinned
            # set's own, so a confirmed ICP is only ever named by bytes this turn actually holds.
            confirmed_path = (
                None
                if icp is None
                else next(
                    (
                        document.ref.path
                        for document in documents
                        if document.ref.document_id == icp.document_id
                    ),
                    None,
                )
            )
            return SellerKnowledge(
                documents_sha256=pin.documents_sha256,
                documents=tuple(_seller_document(document) for document in documents),
                confirmed_icp_path=confirmed_path,
                product_set=(
                    None
                    if product_set is None
                    else {
                        "selection_version": product_set.selection_version,
                        "product_ids": list(product_set.product_ids),
                    }
                ),
            )

        return self._guarded(read, tool="seller_knowledge")


type DesignPlatformReadsFactory = Callable[[DesignTurnEnvelope], DesignPlatformReads | None]


def build_design_platform_reads_factory(
    *,
    invoker: ToolInvoker,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
    loop: asyncio.AbstractEventLoop | None = None,
    timeout_s: float = 20.0,
) -> DesignPlatformReadsFactory:
    """Capture the pool-owning loop once; hand each LEG turn its own reads object."""

    bridge = PlatformLoopBridge(loop=loop, timeout_s=timeout_s, error=DesignPlatformReadError)

    def factory(envelope: DesignTurnEnvelope) -> DesignPlatformReads | None:
        if not isinstance(envelope.config.get("leg"), dict):
            return None
        return DesignPlatformReads(
            envelope=envelope,
            invoker=invoker,
            storage=storage,
            conn_factory=conn_factory,
            bridge=bridge,
        )

    return factory


__all__ = [
    "EMPTY_SELLER_KNOWLEDGE",
    "AttachedFile",
    "DesignPlatformReadError",
    "DesignPlatformReads",
    "DesignPlatformReadsFactory",
    "SellerDocument",
    "SellerKnowledge",
    "build_design_platform_reads_factory",
]
