"""The D2.2/D2.3/D2.4 store switch: Postgres via ``clue_design``, behind the Repository seam.

Seven domains now: DOCUMENTS (documents / envelopes / op log / snapshots / template revisions /
diagnostics — the D1a tables, D2.2); BRAND (kits + compatibility reports) and ASSETS (the
registry), D2.3; PERSONALIZATION (binding sets / instances / instance batches / the repair
queue) and WEB ACCOUNTS + WEB BATCHES (D2.4A); and since D2.4B WEB PUBLISHES + PUBLISH REVISIONS
and the CUSTOM-COMPONENT registry (components / source revisions / artifacts / compilations).
Only agent runs + ingestion-adjacent leftovers stay on the SQLite ``Repository`` (D2.5/D5).

**The O5 bridge** (:class:`DesignStoreBridge`) — DISPOSABLE scaffOLDING, deleted at D5 with the
daemon threads. Each call is ``asyncio.run`` of exactly ONE ``clue_design`` DAL coroutine
inside ONE engine/connection/transaction created for that call's private event loop (never a
pool from another loop). Anything atomic (allocate-seq + insert; CAS + stack update; scene write
+ asset promotion) is one coroutine — the founder's binding O5 rule. Costs (per-call engine,
awkward cancellation) are accepted; a restart still kills in-flight work until D5.

**The hybrid store** (:class:`HybridRepository`) — a ``Repository`` subclass overriding ONLY
the ported methods to call the bridge, so main.py's call sites switch at one seam. Python
dispatch makes inherited SQLite methods that call ``self.require_document`` etc. hit Postgres
automatically. **Every cross-domain seam is now CLOSED.** The scene-asset PROMOTION seam closed
at D2.3 (``register_scene_assets`` runs inside the document write's own transaction). The LAST
one — custom-component reference VALIDATION, which ran against the SQLite registry before the
Postgres document write — closes at D2.4B: ``validate_custom_component_reference_changes`` is
not forked, its two reads (``get_web_account``, ``get_custom_component_artifact``) are simply
ported, so validation now reads the SAME store the writes land in. (It is still a *separate*
transaction from the document write; the registry is append-only and immutable, so the only
residual interleaving is an account deleted between validation and write, which the
``design_custom_component`` CASCADE then makes structurally consistent anyway.)

Workspace scoping (O4, staged): ``resolve_workspace_id`` takes ``X-Workspace-Id`` when the
caller sends it, else the configured dev workspace (``LUMEN_DEV_WORKSPACE_ID``, default
``ws_lumen_dev``). Public publish serving cannot use a header at all — a visitor sends none —
so O6b (ratified: option (a)) puts the workspace in the PATH: ``/w/{workspace_id}/p/{slug}``,
served through main.py's ``public_repository`` dependency, which builds this store with
``ensure_workspace=False`` (an anonymous GET must never write) and therefore 404s on an unknown
tenant through the fail-closed workspace-scoped reads.
The strict 401-on-absent header seam lands at D2.5 with the editor harness change. The dev
workspace row is ensured lazily (once per process per workspace) — Part-IV auth deletes that
scaffolding, and Part-IV item 5 deletes the interim ``/w/{workspace_id}/p/...`` route.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

from clue_db import create_engine
from clue_design import accounts as design_accounts
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from clue_design import components as design_components
from clue_design import diagnostics as design_diagnostics
from clue_design import documents as design_documents
from clue_design import history as design_history
from clue_design import personalization as design_personalization
from clue_design import publishes as design_publishes
from clue_design import snapshots as design_snapshots
from clue_design.errors import (
    DesignArtifactConflictError,
    DesignNotFoundError,
    DesignSourceVersionConflictError,
    DesignVersionConflictError,
)
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from .database import (
    CustomComponentArtifactConflict,
    CustomComponentSourceVersionConflict,
    NotFoundError,
    Repository,
    WebDocumentVersionConflict,
    custom_component_artifact_candidate,
    custom_component_nodes,
    custom_component_source_candidate,
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


def _run_isolated[T](coro: "Awaitable[T]") -> T:
    """``asyncio.run`` the coroutine on a thread that owns no event loop.

    Normally that is the caller's own thread (a sync FastAPI endpoint runs in the threadpool).
    But some ported call sites run INSIDE a loop: the ingestion pipeline drives capture with its
    own ``asyncio.run(capture(...))`` and the stage reporter writes to the store from the
    callback (D2.3), and the one async endpoint would do the same. ``asyncio.run`` refuses that
    ("cannot be called from a running event loop"), so the call is handed to a one-shot worker
    thread instead — still exactly ONE loop / connection / transaction per call (the O5 rule),
    just not this thread's. Dies with the rest of the bridge at D5.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()  # type: ignore[arg-type]


class DesignStoreBridge:
    """Sync facade over the async ``clue_design`` DAL — one call, one loop, one transaction."""

    def __init__(self, workspace_id: str, *, ensure_workspace: bool = True) -> None:
        self.workspace_id = workspace_id
        # Public (unauthenticated) serving passes False: an anonymous GET must never create a
        # workspace row, so an unknown tenant simply reads nothing and 404s (O6b).
        self.ensure_workspace = ensure_workspace

    def _run[T](self, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        async def _one_transaction() -> T:
            # ``create_engine`` (a private engine) rather than ``db_lifespan``: the lifespan
            # registers a PROCESS-GLOBAL engine and refuses re-entry, so two bridge calls on two
            # threads collided with "db_lifespan is already active" (found at D2.4B by the
            # component source-CAS race test, which drives two concurrent writers on purpose).
            # Nothing under the bridge reads the global — every DAL coroutine is handed its
            # connection — so owning the engine locally is both correct and what O5 already
            # requires (one engine/connection/transaction per call, bound to THIS loop).
            engine = create_engine()
            try:
                async with engine.connect() as conn, conn.begin():
                    if self.ensure_workspace:
                        await _ensure_workspace(conn, self.workspace_id)
                    return await fn(conn)
            finally:
                await engine.dispose()

        try:
            return _run_isolated(_one_transaction())
        except DesignNotFoundError as exc:
            raise NotFoundError(exc.kind, exc.key) from exc
        except DesignVersionConflictError as exc:
            raise WebDocumentVersionConflict(
                exc.key, exc.expected_version, exc.current_version
            ) from exc
        except DesignArtifactConflictError as exc:
            # D2.4B: the immutable custom-component registry's two conflict species keep the
            # exact exception types main.py registers handlers for (409 DTOs), so the port is
            # invisible above this seam.
            raise CustomComponentArtifactConflict(exc.key) from exc
        except DesignSourceVersionConflictError as exc:
            raise CustomComponentSourceVersionConflict(
                exc.slug, exc.expected_version, exc.current_version
            ) from exc
        except (IntegrityError, DataError) as exc:
            # Constraint parity for the still-SQLite call sites: a duplicate brand-kit
            # version raised ``sqlite3.IntegrityError`` (→ the 409 duplicate DTO), and so did
            # a rejected ``source`` under the SQLite CHECK the ``design_brand_kit_source``
            # enum now replaces. Both stay one exception type to the API, exactly as before.
            raise sqlite3.IntegrityError(str(exc.orig)) from exc
        except DBAPIError as exc:
            # asyncpg does NOT map an unknown enum label to DataError — it surfaces
            # ``InvalidTextRepresentationError`` as a bare DBAPIError (found at D2.3 by the
            # ingestion suite's "bogus source is still rejected" case). Translate only SQLSTATE
            # class 22 (data exception, e.g. 22P02 invalid_text_representation), which is
            # precisely the family of CHECKs the design enums replaced; anything else is a real
            # database fault and must keep its own type.
            sqlstate = getattr(exc.orig, "sqlstate", None) or ""
            if str(sqlstate).startswith("22"):
                raise sqlite3.IntegrityError(str(exc.orig)) from exc
            raise


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

    def __init__(
        self,
        connection: Any,
        workspace_id: str | None = None,
        *,
        ensure_workspace: bool = True,
    ) -> None:
        # None -> the configured dev workspace (request paths always pass explicitly; the
        # default serves direct constructions in scripts/tests, which read the same env the
        # per-test isolation fixture sets).
        super().__init__(connection)
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(
            self.workspace_id, ensure_workspace=ensure_workspace
        )

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
            # D2.4B: component references now validate against the SAME Postgres registry the
            # write lands in (the last cross-domain seam) — same fail-fast as before.
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
        return self._bridge._run(
            lambda conn: design_documents.replace_scene(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                scene=scene,
                diagnostics=diagnostics,
            )
        )

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
        return self._bridge._run(
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

    # --- brand kits + compatibility reports (D2.3) --------------------------------------------

    def create_brand_kit(
        self,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.create_brand_kit(
                conn,
                workspace_id=self.workspace_id,
                brand_kit=brand_kit,
                brand_summary=brand_summary,
                diagnostics=diagnostics,
                source=source,
            )
        )

    def list_brand_kits(self, all_versions: bool = False) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_brand.list_brand_kits(
                conn, workspace_id=self.workspace_id, all_versions=all_versions
            )
        )

    def require_brand_kit(
        self, brand_kit_id: str, version: Optional[int] = None
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.get_brand_kit(
                conn,
                workspace_id=self.workspace_id,
                brand_kit_id=brand_kit_id,
                version=version,
            )
        )

    def update_brand_kit_approval(
        self, brand_kit_id: str, approval_status: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.update_brand_kit_approval(
                conn,
                workspace_id=self.workspace_id,
                brand_kit_id=brand_kit_id,
                approval_status=approval_status,
            )
        )

    def create_brand_compatibility_report(
        self,
        report_id: str,
        from_brand_kit: JsonObject,
        to_brand_kit: JsonObject,
        report: JsonObject,
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.create_brand_compat_report(
                conn,
                workspace_id=self.workspace_id,
                report_id=report_id,
                from_brand_kit=from_brand_kit,
                to_brand_kit=to_brand_kit,
                report=report,
                diagnostics=diagnostics,
            )
        )

    def require_brand_compatibility_report(self, report_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.get_brand_compat_report(
                conn, workspace_id=self.workspace_id, report_id=report_id
            )
        )

    # --- asset registry (D2.3) ----------------------------------------------------------------

    def create_asset_record(self, record: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.create_asset_record(
                conn, workspace_id=self.workspace_id, record=record
            )
        )

    def require_asset_record(self, asset_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.get_asset_record(
                conn, workspace_id=self.workspace_id, asset_id=asset_id
            )
        )

    def list_asset_records(
        self,
        kind: Optional[str] = None,
        q: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_assets.list_asset_records(
                conn,
                workspace_id=self.workspace_id,
                kind=kind,
                q=q,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
            )
        )

    def update_asset_status(self, asset_id: str, status: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.update_asset_status(
                conn, workspace_id=self.workspace_id, asset_id=asset_id, status=status
            )
        )

    def delete_asset_record(self, asset_id: str) -> None:
        self._bridge._run(
            lambda conn: design_assets.delete_asset_record(
                conn, workspace_id=self.workspace_id, asset_id=asset_id
            )
        )

    def count_assets_with_digest(
        self, digest_value: str, exclude_asset_id: Optional[str] = None
    ) -> int:
        return self._bridge._run(
            lambda conn: design_assets.count_assets_with_digest(
                conn,
                workspace_id=self.workspace_id,
                digest_value=digest_value,
                exclude_asset_id=exclude_asset_id,
            )
        )

    def register_scene_assets(self, scene: JsonObject, commit: bool = True) -> int:
        """The scene-persist paths call the DAL version in-transaction (D2.3); this override
        exists for the flows that promote a scene's assets on their own."""
        del commit  # SQLite-era knob; the bridge is one transaction per call.
        return self._bridge._run(
            lambda conn: design_assets.register_scene_assets(
                conn, workspace_id=self.workspace_id, scene=scene
            )
        )

    # --- scene-mode personalization (D2.4) ----------------------------------------------------

    def upsert_binding_set(
        self, binding: JsonObject, status: str, diagnostics: List[JsonObject]
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.upsert_binding_set(
                conn,
                workspace_id=self.workspace_id,
                binding=binding,
                status=status,
                diagnostics=diagnostics,
            )
        )

    def require_binding_set(self, binding_set_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_binding_set(
                conn, workspace_id=self.workspace_id, binding_set_id=binding_set_id
            )
        )

    def list_binding_sets(
        self, template_revision_id: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_binding_sets(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
            )
        )

    def delete_binding_set(self, binding_set_id: str) -> None:
        self._bridge._run(
            lambda conn: design_personalization.delete_binding_set(
                conn, workspace_id=self.workspace_id, binding_set_id=binding_set_id
            )
        )

    def upsert_instance(self, instance: JsonObject) -> JsonObject:
        """The derived instance's revision/binding/batch references are REAL composite FKs
        now (D1d), so a dangling reference surfaces as ``sqlite3.IntegrityError`` through the
        bridge's constraint-parity translation rather than as a silent orphan row."""
        return self._bridge._run(
            lambda conn: design_personalization.upsert_instance(
                conn, workspace_id=self.workspace_id, instance=instance
            )
        )

    def require_instance(self, instance_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_instance(
                conn, workspace_id=self.workspace_id, instance_id=instance_id
            )
        )

    def list_instances(
        self,
        template_revision_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_instances(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
                batch_id=batch_id,
            )
        )

    def create_batch(self, batch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.create_instance_batch(
                conn, workspace_id=self.workspace_id, batch=batch
            )
        )

    def update_batch_progress(
        self,
        batch_id: str,
        cursor: int,
        status: str,
        counts: JsonObject,
        manifest: List[JsonObject],
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.update_instance_batch_progress(
                conn,
                workspace_id=self.workspace_id,
                batch_id=batch_id,
                cursor=cursor,
                status=status,
                counts=counts,
                manifest=manifest,
                diagnostics=diagnostics,
            )
        )

    def require_batch(self, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_instance_batch(
                conn, workspace_id=self.workspace_id, batch_id=batch_id
            )
        )

    def upsert_repair_request(self, repair: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.upsert_repair_request(
                conn, workspace_id=self.workspace_id, repair=repair
            )
        )

    def list_repair_queue(
        self, template_revision_id: str, status: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_repair_queue(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
                status=status,
            )
        )

    # --- web accounts + web batches (D2.4) ----------------------------------------------------

    def create_web_account(
        self,
        account_id: str,
        name: str,
        domain: Optional[str],
        logo_asset_id: Optional[str],
        data: JsonObject,
        notes: Optional[str],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.create_web_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                name=name,
                domain=domain,
                logo_asset_id=logo_asset_id,
                data=data,
                notes=notes,
            )
        )

    def get_web_account(self, account_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_accounts.get_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def require_web_account(self, account_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.require_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def list_web_accounts(self) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_accounts.list_web_accounts(
                conn, workspace_id=self.workspace_id
            )
        )

    def update_web_account(self, account_id: str, patch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.update_web_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                patch=patch,
            )
        )

    def delete_web_account(self, account_id: str) -> None:
        """Delete the Postgres account row.

        Since D2.4B the account's CUSTOM COMPONENT families live on Postgres too, behind
        ``design_custom_component_account_fk … ON DELETE CASCADE`` — so components, their source
        revisions, artifacts and compilations now go WITH the account instead of being orphaned
        (SQLite had no FK to ``web_accounts`` and left them behind forever).
        """
        self._bridge._run(
            lambda conn: design_accounts.delete_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def create_web_batch(self, batch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.create_web_batch(
                conn, workspace_id=self.workspace_id, batch=batch
            )
        )

    def update_web_batch_progress(
        self, batch_id: str, cursor: int, status: str, manifest: List[JsonObject]
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.update_web_batch_progress(
                conn,
                workspace_id=self.workspace_id,
                batch_id=batch_id,
                cursor=cursor,
                status=status,
                manifest=manifest,
            )
        )

    def require_web_batch(self, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.require_web_batch(
                conn, workspace_id=self.workspace_id, batch_id=batch_id
            )
        )

    # --- web publishes + publish revisions (D2.4B) --------------------------------------------

    def register_web_publish_revision(self, revision: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.register_web_publish_revision(
                conn, workspace_id=self.workspace_id, revision=revision
            )
        )

    def require_web_publish_revision(self, publish_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.require_web_publish_revision(
                conn, workspace_id=self.workspace_id, publish_id=publish_id
            )
        )

    def upsert_web_publish(
        self,
        slug: str,
        document_id: str,
        doc_version: int,
        html: str,
        runtime_version: Optional[int],
        publish_id: Optional[str] = None,
    ) -> JsonObject:
        """Slugs are WORKSPACE-LOCAL now (O6): the PK is ``(workspace_id, slug)``, so two
        tenants publishing ``pricing`` no longer collide. The current→previous shift stays ONE
        statement."""
        return self._bridge._run(
            lambda conn: design_publishes.upsert_web_publish(
                conn,
                workspace_id=self.workspace_id,
                slug=slug,
                document_id=document_id,
                doc_version=doc_version,
                html=html,
                runtime_version=runtime_version,
                publish_id=publish_id,
            )
        )

    def require_web_publish(self, slug: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.require_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    def get_web_publish(self, slug: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.get_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    def get_web_publish_for_document(self, document_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.get_web_publish_for_document(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def set_web_publish_status(self, slug: str, status: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.set_web_publish_status(
                conn, workspace_id=self.workspace_id, slug=slug, status=status
            )
        )

    def rollback_web_publish(self, slug: str) -> Any:
        return self._bridge._run(
            lambda conn: design_publishes.rollback_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    # --- custom-component registry (D2.4B) ----------------------------------------------------

    def register_custom_component_artifact(self, artifact: JsonObject) -> JsonObject:
        """Contract validation (blob/slug/content-address) runs here against the SHARED
        ``database.custom_component_artifact_candidate`` helper — same errors as the SQLite era —
        and the DAL then stores + arbitrates the immutable id's equal-content rule."""
        candidate = custom_component_artifact_candidate(artifact)
        return self._bridge._run(
            lambda conn: design_components.register_custom_component_artifact(
                conn, workspace_id=self.workspace_id, candidate=candidate
            )
        )

    def get_custom_component_artifact(self, artifact_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_artifact(
                conn, workspace_id=self.workspace_id, artifact_id=artifact_id
            )
        )

    def get_custom_component_artifact_for_account(
        self, account_id: str, artifact_id: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_artifact_for_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                artifact_id=artifact_id,
            )
        )

    def require_custom_component_artifact(
        self, account_id: str, artifact_id: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_artifact(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                artifact_id=artifact_id,
            )
        )

    def list_custom_component_artifacts(
        self, account_id: str, slug: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_artifacts(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def list_custom_components(self, account_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_components(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def get_custom_component(self, account_id: str, slug: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def require_custom_component(self, account_id: str, slug: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def create_custom_component_source_revision(
        self, source: JsonObject, *, expected_version: int
    ) -> JsonObject:
        """SQLite serialized the CAS with ``BEGIN IMMEDIATE``; the DAL takes the identity row's
        ``FOR UPDATE`` lock inside the bridge's single transaction (the O5 atomicity rule)."""
        candidate = custom_component_source_candidate(source, expected_version)
        return self._bridge._run(
            lambda conn: design_components.create_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                candidate=candidate,
                expected_version=expected_version,
            )
        )

    def get_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                revision_id=revision_id,
            )
        )

    def require_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                revision_id=revision_id,
            )
        )

    def get_current_custom_component_source(
        self, account_id: str, slug: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_current_custom_component_source(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def list_custom_component_source_revisions(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_source_revisions(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def record_custom_component_compilation(
        self, compilation: JsonObject
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.record_custom_component_compilation(
                conn, workspace_id=self.workspace_id, compilation=compilation
            )
        )

    def require_custom_component_compilation(
        self, account_id: str, compilation_id: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_compilation(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                compilation_id=compilation_id,
            )
        )

    def list_custom_component_compilations(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_compilations(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    # NOTE: ``validate_custom_component_reference_changes`` is deliberately NOT overridden. Its
    # only two store reads are ``get_web_account`` and ``get_custom_component_artifact``, both
    # overridden above, so Python dispatch already runs the inherited walk against Postgres —
    # the LAST cross-domain seam, closed by porting its reads rather than by forking the method.

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
