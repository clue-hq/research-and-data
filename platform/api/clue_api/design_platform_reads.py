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
_PINNED_VERSIONS = {"read_account_research": "2"}


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
    "DesignPlatformReadError",
    "DesignPlatformReads",
    "DesignPlatformReadsFactory",
    "SellerDocument",
    "SellerKnowledge",
    "build_design_platform_reads_factory",
]
