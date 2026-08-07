"""The D2.2 document-store switch: Postgres via ``clue_design``, behind the Repository seam.

Two pieces, both scoped to the DOCUMENT domain (documents / envelopes / op log / snapshots /
template revisions / diagnostics — the D1a tables). Everything else stays on the SQLite
``Repository`` until its own slice (brand/assets D2.3, personalization/web D2.4, runs D2.5).

**The O5 bridge** (:class:`DesignStoreBridge`) — DISPOSABLE scaffOLDING, deleted at D5 with the
daemon threads. Each call is ``asyncio.run`` of exactly ONE ``clue_design`` DAL coroutine
inside ONE engine/connection/transaction created for that call's private event loop (never a
pool from another loop). Anything atomic (allocate-seq + insert; CAS + stack update) is one
coroutine — the founder's binding O5 rule. Costs (per-call engine, awkward cancellation) are
accepted; a restart still kills in-flight work until D5.

**The hybrid store** (:class:`HybridRepository`) — a ``Repository`` subclass overriding ONLY
the document-domain methods to call the bridge, so main.py's call sites switch at one seam.
Python dispatch makes inherited SQLite methods that call ``self.require_document`` etc. hit
Postgres automatically. Two cross-domain seams are sequenced here, documented at each site:
custom-component reference VALIDATION (SQLite until D2.4) runs before the Postgres write;
scene-asset registry PROMOTION (SQLite until D2.3) runs after it — best-effort + idempotent,
the interim atomicity split of a staged port.

Workspace scoping (O4, staged): ``resolve_workspace_id`` takes ``X-Workspace-Id`` when the
caller sends it, else the configured dev workspace (``LUMEN_DEV_WORKSPACE_ID``, default
``ws_lumen_dev``). The strict 401-on-absent seam lands at D2.5 with the editor harness change.
The dev workspace row is ensured lazily (once per process per workspace) — Part-IV auth
deletes that scaffolding.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Iterable, List, Optional, Tuple

from clue_db import db_lifespan
from clue_design import diagnostics as design_diagnostics
from clue_design import documents as design_documents
from clue_design import history as design_history
from clue_design import snapshots as design_snapshots
from clue_design.errors import DesignNotFoundError, DesignVersionConflictError
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .database import (
    NotFoundError,
    Repository,
    WebDocumentVersionConflict,
    custom_component_nodes,
)

JsonObject = Dict[str, Any]

_DEV_WORKSPACE_ENV = "LUMEN_DEV_WORKSPACE_ID"
_DEV_WORKSPACE_DEFAULT = "ws_lumen_dev"
_WORKSPACE_HEADER = "X-Workspace-Id"

_ensured_workspaces: set[str] = set()
_ensure_lock = threading.Lock()


def default_workspace_id() -> str:
    return os.environ.get(_DEV_WORKSPACE_ENV, _DEV_WORKSPACE_DEFAULT)


def resolve_workspace_id(request: Request) -> str:
    """Header wins; else the configured dev workspace. Strict 401-on-absent arrives at D2.5."""
    return request.headers.get(_WORKSPACE_HEADER) or default_workspace_id()


class DesignStoreBridge:
    """Sync facade over the async ``clue_design`` DAL — one call, one loop, one transaction."""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id

    def _run[T](self, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        async def _one_transaction() -> T:
            async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
                await _ensure_workspace(conn, self.workspace_id)
                return await fn(conn)

        try:
            return asyncio.run(_one_transaction())
        except DesignNotFoundError as exc:
            raise NotFoundError(exc.kind, exc.key) from exc
        except DesignVersionConflictError as exc:
            raise WebDocumentVersionConflict(
                exc.key, exc.expected_version, exc.current_version
            ) from exc


async def _ensure_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    """Dev-only scaffolding (dies at Part-IV auth): the dev workspace row must exist for the
    tenancy FKs; ensured once per process per workspace, idempotently."""
    with _ensure_lock:
        already = workspace_id in _ensured_workspaces
    if already:
        return
    await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"
            " ON CONFLICT (workspace_id) DO NOTHING"
        ),
        {"w": workspace_id},
    )
    with _ensure_lock:
        _ensured_workspaces.add(workspace_id)


class HybridRepository(Repository):
    """The staged-port store: document domain on Postgres, everything else inherited SQLite."""

    def __init__(self, connection: Any, workspace_id: str | None = None) -> None:
        # None -> the configured dev workspace (request paths always pass explicitly; the
        # default serves direct constructions in scripts/tests, which read the same env the
        # per-test isolation fixture sets).
        super().__init__(connection)
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id)

    # --- documents ---------------------------------------------------------------------------

    def create_document(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject] = None,
        effective_brand_source: Optional[str] = None,
        effective_brand_mode: Optional[JsonObject] = None,
        doc_kind: str = "scene",
        template_document_id: Optional[str] = None,
        template_doc_version: Optional[int] = None,
        account_id: Optional[str] = None,
    ) -> JsonObject:
        if doc_kind == "web":
            # Cross-domain seam (SQLite until D2.4): component references validate against
            # the SQLite registry BEFORE the Postgres write — same fail-fast as before.
            self.validate_custom_component_reference_changes(
                before_web_doc={}, after_web_doc=scene, account_id=account_id
            )
        return self._bridge._run(
            lambda conn: design_documents.create_document(
                conn,
                workspace_id=self.workspace_id,
                scene=scene,
                brand_kit=brand_kit,
                effective_brand_source=effective_brand_source,
                effective_brand_mode=effective_brand_mode,
                doc_kind=doc_kind,
                template_document_id=template_document_id,
                template_doc_version=template_doc_version,
                account_id=account_id,
            )
        )

    def require_document(self, document_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.get_document(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def replace_scene(
        self, document_id: str, scene: JsonObject, diagnostics: List[JsonObject]
    ) -> JsonObject:
        document = self._bridge._run(
            lambda conn: design_documents.replace_scene(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                scene=scene,
                diagnostics=diagnostics,
            )
        )
        # Cross-domain seam (SQLite until D2.3): registry promotion runs AFTER the committed
        # document write — idempotent; a crash between the two re-promotes on the next save.
        self.register_scene_assets(scene)
        return document

    def update_document_state(
        self,
        document_id: str,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        operations: Iterable[JsonObject],
        source: str,
        actor_kind: str,
        actor_id: Optional[str],
        diagnostic_kind: str,
        effective_brand: Optional[Tuple[str, Optional[JsonObject], Optional[JsonObject]]],
        envelope: Optional[JsonObject] = None,
    ) -> JsonObject:
        ops = list(operations)
        document = self._bridge._run(
            lambda conn: design_documents.update_document_state(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                scene=scene,
                diagnostics=diagnostics,
                operations=ops,
                source=source,
                actor_kind=actor_kind,
                actor_id=actor_id,
                diagnostic_kind=diagnostic_kind,
                effective_brand=effective_brand,
                envelope=envelope,
            )
        )
        self.register_scene_assets(scene)
        return document

    def update_web_document(
        self,
        document_id: str,
        web_doc: JsonObject,
        *,
        intent: Optional[str],
        checkpoint_label: Optional[str],
        operations: List[JsonObject],
        inverse_operations: Optional[List[JsonObject]],
        actor_kind: str = "agent",
        source: str = "agent",
        push_undo: bool = True,
        reverts_batch_id: Optional[str] = None,
        reapplies_batch_id: Optional[str] = None,
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        before = self.require_document(document_id)
        self.validate_custom_component_reference_changes(
            before_web_doc=before["scene"],
            after_web_doc=web_doc,
            account_id=before.get("account_id"),
        )
        return self._bridge._run(
            lambda conn: design_documents.update_web_document(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                web_doc=web_doc,
                intent=intent,
                checkpoint_label=checkpoint_label,
                operations=operations,
                inverse_operations=inverse_operations,
                actor_kind=actor_kind,
                source=source,
                push_undo=push_undo,
                reverts_batch_id=reverts_batch_id,
                reapplies_batch_id=reapplies_batch_id,
                expected_base_version=expected_base_version,
            )
        )

    def set_agent_instructions(
        self, document_id: str, instructions: Optional[str]
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.set_agent_instructions(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                instructions=instructions,
            )
        )

    def set_layout_managed_editing(self, document_id: str, enabled: bool) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.set_layout_managed_editing(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                enabled=enabled,
            )
        )

    def create_web_template(
        self, web_doc: JsonObject, account_id: Optional[str] = None
    ) -> JsonObject:
        self.validate_custom_component_reference_changes(
            before_web_doc={}, after_web_doc=web_doc, account_id=account_id
        )
        return self._bridge._run(
            lambda conn: design_documents.create_web_template(
                conn,
                workspace_id=self.workspace_id,
                web_doc=web_doc,
                account_id=account_id,
            )
        )

    def list_web_templates(self) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_documents.list_web_templates(
                conn, workspace_id=self.workspace_id
            )
        )

    def set_document_account(
        self, document_id: str, account_id: Optional[str]
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.set_document_account(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                account_id=account_id,
            )
        )

    def count_documents_referencing(self, needle: str) -> int:
        return self._bridge._run(
            lambda conn: design_documents.count_documents_referencing(
                conn, workspace_id=self.workspace_id, needle=needle
            )
        )

    # --- cross-domain reads over the Postgres document feed ----------------------------------

    def list_running_runs(self) -> List[JsonObject]:
        """The startup-sweep read: runs are SQLite until D5, doc_kind lives on Postgres.

        The SQLite original joined ``agent_runs`` to ``documents``; that join is impossible
        now, so the run rows come from SQLite and each distinct document's ``doc_kind`` is
        resolved (and cached) through the Postgres document store.
        """
        rows = self.connection.execute(
            """
            SELECT run_id, document_id FROM agent_runs
            WHERE status = 'running'
            ORDER BY created_at ASC
            """
        ).fetchall()
        doc_kinds: Dict[str, Optional[str]] = {}
        running: List[JsonObject] = []
        for row in rows:
            document_id = row["document_id"]
            doc_kind: Optional[str] = None
            if document_id is not None:
                if document_id not in doc_kinds:
                    try:
                        doc_kinds[document_id] = self.require_document(document_id)["doc_kind"]
                    except NotFoundError:
                        doc_kinds[document_id] = None
                doc_kind = doc_kinds[document_id]
            running.append(
                {
                    "run_id": row["run_id"],
                    "document_id": document_id,
                    "doc_kind": doc_kind,
                }
            )
        return running

    def list_custom_component_usages(self, account_id: str, slug: str) -> List[JsonObject]:
        """Exact document/node pins for one account-local component (ported walk).

        The SQL account predicate in the DAL feed is the tenancy boundary. The JSON walk then
        performs an exact kind/slug match (rather than trusting a broad LIKE) and returns only
        location/version metadata, never another document's source or page content.
        """
        rows = self._bridge._run(
            lambda conn: design_documents.list_web_documents_for_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )
        usages: List[JsonObject] = []
        for row in rows:
            for (page_id, node_id), node in sorted(custom_component_nodes(row["scene"]).items()):
                if node.get("slug") != slug:
                    continue
                usages.append(
                    {
                        "document_id": row["id"],
                        "document_title": row["title"],
                        "document_version": row["current_version"],
                        "page_id": page_id,
                        "node_id": node_id,
                        "artifact_id": node.get("artifact_id"),
                    }
                )
        return usages

    # --- history -----------------------------------------------------------------------------

    def list_envelopes(
        self,
        document_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        newest_first: bool = True,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_history.list_envelopes(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                limit=limit,
                offset=offset,
                newest_first=newest_first,
            )
        )

    def require_envelope(self, document_id: str, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_history.get_envelope(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                batch_id=batch_id,
            )
        )

    def list_operations(self, document_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_history.list_operations(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    # --- snapshots + template revisions ------------------------------------------------------

    def create_snapshot(
        self, document_id: str, snapshot_id: str, reason: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.create_snapshot(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                snapshot_id=snapshot_id,
                reason=reason,
            )
        )

    def list_snapshots(self, document_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_snapshots.list_snapshots(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def require_snapshot(self, document_id: str, snapshot_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.get_snapshot(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                snapshot_id=snapshot_id,
            )
        )

    def create_template_revision(
        self,
        document_id: str,
        template_revision_id: str,
        source_snapshot_id: Optional[str],
        scene: JsonObject,
        slot_summary: List[JsonObject],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.create_template_revision(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                template_revision_id=template_revision_id,
                source_snapshot_id=source_snapshot_id,
                scene=scene,
                slot_summary=slot_summary,
            )
        )

    def require_template_revision(self, template_revision_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.get_template_revision(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
            )
        )

    # --- diagnostics -------------------------------------------------------------------------

    def store_diagnostics(
        self,
        document_id: str,
        kind: str,
        diagnostics: List[JsonObject],
        commit: bool = True,
    ) -> None:
        del commit  # SQLite-era knob; the bridge is one transaction per call.
        self._bridge._run(
            lambda conn: design_diagnostics.store_diagnostics(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                kind=kind,
                diagnostics=diagnostics,
            )
        )

    def latest_diagnostics(
        self, document_id: str, kind: Optional[str] = None
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_diagnostics.latest_diagnostics(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                kind=kind,
            )
        )
