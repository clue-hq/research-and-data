"""The governed presentation of the human product-**set** selection gate (ARV2 onboarding O6).

A project targets a *set* of products (``docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md`` §6.3, ruling
P1), so the question the Head of ABM puts to a human is "which of this brand's products is this
project about?" — and the answer may name more than one.

The model may decide the conversation is ready to ask. It may not author what is asked. Every value
in the presented gate is derived here from durable rows:

* the **presenting turn** supplies the project, the thread and the addressee;
* the project's **brand** supplies the candidates — the brand's ``product`` rows, which are the only
  things a project can actually be pointed at;
* the current ``product-catalog`` **knowledge document** and its ``onboarding_product_lineage`` rows
  annotate those candidates (the marketing copy, and how confidently onboarding matched a catalog
  entry to a spine row — a ``model_unsure`` match is shown as such rather than hidden);
* the project's confirmed **product set** is shown as the current answer, if it has one;
* an ICP document supplies a *suggestion* and nothing more.

This is the sibling of :mod:`clue_api.product_selection_gate_tools` (the S5-F single-product gate)
and deliberately not a version of it: the S5-F tool derives its catalog from a
``ClientKnowledgeCard`` pinned to a Client-KB version, and refuses (``product_catalog_unavailable``)
without one. Onboarding V2 workspaces have no Client-KB version at all, and the standing rule
(``_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md``; catalog contract §10) forbids one on
this path. Nothing in this module reads a Client-KB version, a readiness decision or a Stage-0 pin.

The tool writes only the immutable question. The chat route records the human's structured answer
and confirms the set outside the model surface.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, cast
from uuid import UUID

import yaml
from pydantic import Field, JsonValue, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.agent_gate import (
    KIND_PRODUCT_SET_SELECTION,
    insert_gate,
    product_set_selection_gate_id,
)
from clue_api.agent_gate_tools import gate_ref
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.brand_knowledge_context import (
    KnowledgeDocumentRef,
    current_knowledge_documents,
    current_project_knowledge_refs,
)
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import current_project_product_set, get_project, list_products
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "OpenProductSetSelectionGateInput",
    "OpenProductSetSelectionGateOutput",
    "OpenProductSetSelectionGateTool",
    "build_product_set_selection_gate_tools",
]

_CATALOG_KIND = "product-catalog"
_ICP_KIND = "icp-definition"
#: The catalog entry members the gate copies onto a candidate, when the catalog names it.
_CATALOG_MEMBERS = ("offering_kind", "family", "lifecycle", "official_url")


class OpenProductSetSelectionGateInput(ToolInput):
    #: The ICP the conversation is working from, if there is one. It only decides which candidates
    #: are *pre-checked*; it never decides what may be chosen, and it confirms nothing.
    icp_key: str | None = Field(default=None, min_length=1, max_length=200)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class OpenProductSetSelectionGateOutput(ToolOutput):
    gate_id: str
    gate_ref: str
    gate_kind: Literal["product_set_selection"]
    candidate_count: int
    suggested_count: int
    addressee_user_id: str
    created: bool


class _SelectionRefused(ValueError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _ResolvedSelection:
    gate_id: UUID
    turn_id: UUID
    thread_id: str
    project_id: str
    addressee: str
    subject_ref: str
    subject_revision: int
    digest: str
    snapshot: dict[str, JsonValue]
    candidate_count: int
    suggested_count: int


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _canonical(snapshot: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


class OpenProductSetSelectionGateTool(Tool):
    name = "open_product_set_selection_gate"
    version = "1"
    model_description = (
        "Ask the current human which of this brand's products this project is about. The platform "
        "derives the candidates from the brand's own product rows and the current product catalog; "
        "you may pass the icp_key you are working from to pre-check its products. This call "
        "confirms nothing. End the turn awaiting input with the returned gate_ref. "
        + tool_manual_link("open_product_set_selection_gate")
    )
    input_model: ClassVar[type[ToolInput]] = OpenProductSetSelectionGateInput
    output_model: ClassVar[type[ToolOutput]] = OpenProductSetSelectionGateOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one product-set presentation for one presenting turn and one brand catalog"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key",))
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenProductSetSelectionGateInput)
        try:
            await self._resolve(inputs, ctx)
        except _SelectionRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenProductSetSelectionGateInput)
        resolved = await self._resolve(inputs, ctx)
        async with self._conn_factory() as conn:
            row, created = await insert_gate(
                conn,
                gate_id=resolved.gate_id,
                workspace_id=ctx.workspace_id,
                project_id=resolved.project_id,
                thread_id=resolved.thread_id,
                turn_id=resolved.turn_id,
                kind=KIND_PRODUCT_SET_SELECTION,
                subject_ref=resolved.subject_ref,
                subject_revision=resolved.subject_revision,
                expected_subject_sha256=resolved.digest,
                subject_snapshot=resolved.snapshot,
                # A product question spends nothing, so it carries no amount at all — and the route
                # refuses an answer that echoes one back.
                max_spend_cents=None,
                currency=None,
                addressee_user_id=resolved.addressee,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "gate_id": str(row.gate_id),
                "gate_ref": gate_ref(row.gate_id),
                "gate_kind": row.kind,
                "candidate_count": resolved.candidate_count,
                "suggested_count": resolved.suggested_count,
                "addressee_user_id": row.addressee_user_id,
                "created": created,
            },
        )

    async def _resolve(
        self, inputs: OpenProductSetSelectionGateInput, ctx: ToolContext
    ) -> _ResolvedSelection:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _SelectionRefused(
                "the current turn reference is unavailable",
                reason_code="product_set_turn_not_found",
            ) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None:
                raise _SelectionRefused(
                    "the current turn reference is unavailable",
                    reason_code="product_set_turn_not_found",
                )
            if not turn.submitted_by_user_id:
                raise _SelectionRefused(
                    "the current turn has no human addressee",
                    reason_code="product_set_addressee_missing",
                )
            project = await get_project(conn, turn.project_id)
            if project is None or project.workspace_id != ctx.workspace_id:
                raise _SelectionRefused(
                    "the current turn's project is unavailable",
                    reason_code="product_set_project_unavailable",
                )
            brand_id = project.brand_id
            # An archived product stays for history and lineage, but a project can no longer be
            # pointed at it, so it is not a candidate (project_targeting_tools filters the same).
            candidates = [
                product
                for product in await list_products(conn, brand_id)
                if product.workspace_id == ctx.workspace_id and product.status == "active"
            ]
            if not candidates:
                raise _SelectionRefused(
                    "this brand has no products to choose between",
                    reason_code="product_set_no_candidates",
                )
            # Both scopes, because the ICP pre-check below must find the document this project
            # would actually be asked about: its own variant when it authored one, the brand's
            # otherwise. The brand reader no longer returns project rows, so they are unioned in
            # rather than filtered out.
            documents = (
                *await current_knowledge_documents(
                    conn, workspace_id=ctx.workspace_id, brand_id=brand_id
                ),
                *await current_project_knowledge_refs(
                    conn, workspace_id=ctx.workspace_id, project_id=turn.project_id
                ),
            )
            catalog = _current_catalog(documents)
            catalog_front = (
                {}
                if catalog is None
                else await self._front_matter(conn, ref=catalog, workspace_id=ctx.workspace_id)
            )
            lineage, unresolved_entries = (
                ({}, 0)
                if catalog is None
                else await _lineage_by_product(conn, document_id=catalog.document_id)
            )
            entries = _catalog_entries(catalog_front)
            selection = await current_project_product_set(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=turn.project_id,
            )
            suggested = await self._suggested_product_ids(
                conn,
                documents=documents,
                workspace_id=ctx.workspace_id,
                project_id=turn.project_id,
                icp_key=inputs.icp_key,
                candidate_ids=[product.product_id for product in candidates],
            )

        products: list[JsonValue] = []
        for product in candidates:
            flags = lineage.get(product.product_id, {})
            ordinal = flags.get("entry_ordinal")
            entry = (
                entries[ordinal] if isinstance(ordinal, int) and 0 <= ordinal < len(entries) else {}
            )
            member: dict[str, JsonValue] = {
                "product_id": product.product_id,
                "name": product.name,
                # A product row the catalog does not describe is honestly blank, never invented.
                "short_description": _as_text(entry.get("short_description")),
                "aliases": list(product.aliases),
                "status": product.status,
                "resolution_state": _as_optional_text(flags.get("resolution_state")),
                "reconcile_confidence": _as_optional_text(flags.get("reconcile_confidence")),
                "reconcile_reason": _as_optional_text(flags.get("reconcile_reason")),
            }
            for key in _CATALOG_MEMBERS:
                member[key] = _as_optional_text(entry.get(key))
            products.append(cast(JsonValue, member))

        snapshot: dict[str, JsonValue] = {
            "brand_id": brand_id,
            "catalog_document_id": None if catalog is None else str(catalog.document_id),
            "catalog_version": 1 if catalog is None else catalog.version,
            "products": products,
            # Catalog entries onboarding could not resolve to a product row: they exist in the
            # document the human may be reading, and they are deliberately not selectable here.
            "omitted_count": unresolved_entries,
            "current_selection": (
                None
                if selection is None
                else {
                    "selection_version": selection.selection_version,
                    "product_ids": list(selection.product_ids),
                }
            ),
            "suggested_product_ids": list(suggested),
        }
        digest = hashlib.sha256(_canonical(snapshot)).hexdigest()
        # D10: the subject is this brand's catalog as it currently stands. A brand with no catalog
        # document yet is still a legitimate subject — its products exist — so the reference names
        # the absence explicitly and the revision floors at 1 (the frontend refuses a revision < 1).
        subject_ref = (
            f"brand-product-catalog:{brand_id}:"
            f"{catalog.document_id if catalog is not None else 'none'}"
        )
        subject_revision = 1 if catalog is None else catalog.version
        return _ResolvedSelection(
            gate_id=product_set_selection_gate_id(
                workspace_id=ctx.workspace_id,
                turn_id=turn.turn_id,
                subject_ref=subject_ref,
                expected_subject_sha256=digest,
            ),
            turn_id=turn.turn_id,
            thread_id=turn.thread_id,
            project_id=turn.project_id,
            addressee=turn.submitted_by_user_id,
            subject_ref=subject_ref,
            subject_revision=subject_revision,
            digest=digest,
            snapshot=snapshot,
            candidate_count=len(candidates),
            suggested_count=len(suggested),
        )

    async def _front_matter(
        self,
        conn: AsyncConnection,
        *,
        ref: KnowledgeDocumentRef,
        workspace_id: str,
    ) -> dict[str, Any]:
        """One document's front matter, or nothing at all.

        Without a storage backend, or behind bytes that no longer verify, the document simply does
        not contribute: an annotation the platform cannot read is left blank rather than guessed.
        """

        if self._storage is None:
            return {}
        try:
            record, body = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=ref.artifact_key,
                workspace_id=workspace_id,
            )
        except ArtifactIntegrityError:
            return {}
        if record.content_sha256 != ref.artifact_sha256:
            return {}
        try:
            front, _ = parse_front_matter(body.decode())
        except (UnicodeDecodeError, ValueError, yaml.YAMLError):
            return {}
        return front

    async def _suggested_product_ids(
        self,
        conn: AsyncConnection,
        *,
        documents: Sequence[KnowledgeDocumentRef],
        workspace_id: str,
        project_id: str,
        icp_key: str | None,
        candidate_ids: Sequence[str],
    ) -> tuple[str, ...]:
        """The candidates an ICP already names — a pre-check, never an authority.

        A named ``icp_key`` that no servable ICP document carries is a refusal, not an empty list:
        the agent asked for a specific pre-check and must not be told silently that it got one.
        """

        allowed = list(candidate_ids)
        icp_documents = [ref for ref in documents if ref.kind == _ICP_KIND]
        if icp_key is not None:
            for ref in sorted(icp_documents, key=lambda ref: (ref.path, ref.version)):
                front = await self._front_matter(conn, ref=ref, workspace_id=workspace_id)
                if _document_icp_key(ref, front) == icp_key:
                    return _intersect(_front_product_ids(front), allowed)
            raise _SelectionRefused(
                f"no current ICP document carries the key {icp_key!r}",
                reason_code="icp_key_unknown",
            )
        confirmed: tuple[int, dict[str, Any]] | None = None
        for ref in icp_documents:
            front = await self._front_matter(conn, ref=ref, workspace_id=workspace_id)
            if (
                front.get("status") == "confirmed"
                and front.get("confirmed_for_project_id") == project_id
                and (confirmed is None or ref.version > confirmed[0])
            ):
                confirmed = (ref.version, front)
        if confirmed is None:
            return ()
        return _intersect(_front_product_ids(confirmed[1]), allowed)


def _current_catalog(
    documents: Sequence[KnowledgeDocumentRef],
) -> KnowledgeDocumentRef | None:
    """The **brand's** product catalog. A project-scoped row is never the product catalog.

    ``documents`` is a union of both scopes, because the ICP lookup beside this one must find the
    project's own variant. The catalog is the other kind of question: what this brand sells is the
    brand's fact, and the gate confirms a selection *from* it. A project-scoped `product/catalog.md`
    would otherwise silently become the authority for that project's product set — nothing in the
    schema forbids one, and the set of project-scoped kinds keeps growing.
    """

    catalogs = [ref for ref in documents if ref.kind == _CATALOG_KIND and ref.project_id is None]
    if not catalogs:
        return None
    return min(catalogs, key=lambda ref: ref.path)


def _catalog_entries(front: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = front.get("products")
    if not isinstance(entries, list):
        return []
    return [entry if isinstance(entry, dict) else {} for entry in entries]


async def _lineage_by_product(
    conn: AsyncConnection,
    *,
    document_id: UUID,
) -> tuple[dict[str, dict[str, Any]], int]:
    """How onboarding matched each catalog entry to a spine product, keyed by the product.

    Returns the per-product flags and the number of catalog entries that resolved to no product at
    all — those exist in the document a human may be reading and are deliberately not selectable.
    """

    rows = (
        await conn.execute(
            text(
                "SELECT entry_ordinal, product_id, resolution_state, reconcile_confidence, "
                " reconcile_reason FROM onboarding_product_lineage "
                "WHERE document_id = :document_id ORDER BY entry_ordinal"
            ),
            {"document_id": document_id},
        )
    ).mappings()
    flags: dict[str, dict[str, Any]] = {}
    unresolved = 0
    for row in rows.all():
        product_id = row["product_id"]
        if product_id is None:
            unresolved += 1
            continue
        flags[str(product_id)] = {
            "entry_ordinal": int(row["entry_ordinal"]),
            "resolution_state": row["resolution_state"],
            "reconcile_confidence": row["reconcile_confidence"],
            "reconcile_reason": row["reconcile_reason"],
        }
    return flags, unresolved


def _front_product_ids(front: Mapping[str, Any]) -> tuple[str, ...]:
    raw = front.get("product_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)


def _document_icp_key(ref: KnowledgeDocumentRef, front: Mapping[str, Any]) -> str:
    key = front.get("icp_key")
    if isinstance(key, str) and key:
        return key
    return ref.path.removeprefix("audience/icp-").removesuffix(".md")


def _intersect(named: Sequence[str], allowed: Sequence[str]) -> tuple[str, ...]:
    """The named ids that are really candidates, in the order the candidates are presented."""

    wanted = set(named)
    return tuple(product_id for product_id in allowed if product_id in wanted)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def build_product_set_selection_gate_tools(
    *,
    conn_factory: ConnFactory = transaction,
    storage: StorageBackend | None = None,
) -> tuple[Tool, ...]:
    return (OpenProductSetSelectionGateTool(conn_factory=conn_factory, storage=storage),)
