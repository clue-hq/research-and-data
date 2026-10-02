"""The arv2_display_page fleet handler (spec 2026-09-12 §2): one task writes one page.

The handler is thin on purpose. Everything about *what* a page is — which sections are missing,
which went stale, the gather, the floor, the spend rows — already lives in
:func:`~clue_api.arv2.display.page.ensure_page`; the handler only decides what a task's ending
means to the fleet. Idempotent by construction: ``display_block_live`` keeps one live row per
section and ``ensure_page`` writes only what is missing or stale, so a redelivered task pays for
nothing it already paid for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from clue_api.arv2.display.gather import SubjectKind, SubjectNotFound
from clue_api.arv2.display.page import (
    PageSubjectMismatch,
    RunnerFactory,
    default_runner_factory,
    ensure_page,
)
from clue_api.arv2.display.recipes import PAGES, Page
from clue_api.arv2.errors import Arv2Error, ProviderHalted, ProviderTransportError
from clue_api.arv2.provider_ledger import ArtifactSink
from clue_config import Secrets, Settings
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind, WorkContext, WorkResult
from clue_obs import get_logger

__all__ = [
    "Arv2DisplayPageWorkHandler",
    "build_arv2_display_page_handler",
    "display_page_payload",
]

log = get_logger(__name__)


def display_page_payload(
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    page: str,
    job_id: UUID | None = None,
) -> dict[str, JsonValue]:
    """The one payload shape both enqueuers (the settle, the read) offer and the handler parses."""
    payload: dict[str, JsonValue] = {
        "workspace_id": workspace_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "page": page,
    }
    if job_id is not None:
        payload["job_id"] = str(job_id)
    return payload


@dataclass(frozen=True)
class _PageScope:
    workspace_id: str
    subject_kind: SubjectKind
    subject_id: str
    page: Page
    job_id: UUID | None


def _scope(payload: Mapping[str, JsonValue]) -> _PageScope | None:
    workspace_id = payload.get("workspace_id")
    subject_kind = payload.get("subject_kind")
    subject_id = payload.get("subject_id")
    page = payload.get("page")
    if not (
        isinstance(workspace_id, str)
        and subject_kind in ("account", "contact")
        and isinstance(subject_id, str)
        and page in PAGES
    ):
        return None
    try:
        UUID(subject_id)
    except ValueError:
        return None
    raw_job = payload.get("job_id")
    job_id: UUID | None = None
    if isinstance(raw_job, str):
        try:
            job_id = UUID(raw_job)
        except ValueError:
            job_id = None
    return _PageScope(
        workspace_id=workspace_id,
        subject_kind=cast(SubjectKind, subject_kind),
        subject_id=subject_id,
        page=page,
        job_id=job_id,
    )


class Arv2DisplayPageWorkHandler:
    """One display page, as one fleet work handler."""

    kind = FleetTaskKind.ARV2_DISPLAY_PAGE

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory,
        runner_factory: RunnerFactory,
        artifacts: ArtifactSink,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._runner_factory = runner_factory
        self._artifacts = artifacts

    async def handle(self, context: WorkContext) -> WorkResult:
        """Write the page. Never raises: every ending is a :class:`WorkResult`."""
        scope = _scope(context.payload)
        if scope is None:
            log.error("arv2.display_page_invalid_payload", payload=sorted(context.payload))
            return WorkResult(outcome="failed", references={}, requeue=False)
        try:
            async with self._conn_factory() as conn:
                result = await ensure_page(
                    conn,
                    workspace_id=scope.workspace_id,
                    subject_kind=scope.subject_kind,
                    subject_id=scope.subject_id,
                    page=scope.page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    artifacts=self._artifacts,
                    spend_conn_factory=self._conn_factory,
                    regenerate_stale=True,
                    job_id=scope.job_id,
                )
        except (SubjectNotFound, PageSubjectMismatch) as exc:
            # The row this task names does not exist (or the page cannot be about it). Nothing to
            # retry; the next read of a real subject offers a real task.
            log.warning(
                "arv2.display_page_refused",
                reason=type(exc).__name__,
                workspace_id=scope.workspace_id,
                subject_kind=scope.subject_kind,
                subject_id=scope.subject_id,
                page=scope.page,
            )
            return WorkResult(
                outcome="failed", references={"reason": type(exc).__name__}, requeue=False
            )
        except (ProviderHalted, ProviderTransportError, Arv2Error, OSError, ValueError) as exc:
            # The provider (or our own sink) failed; the sections stay unwritten and the next read
            # of the page re-offers this task (reopen_terminal). A requeue here would hammer a
            # provider that just refused us.
            log.warning(
                "arv2.display_page_failed",
                reason=type(exc).__name__,
                error=str(exc),
                workspace_id=scope.workspace_id,
                subject_kind=scope.subject_kind,
                subject_id=scope.subject_id,
                page=scope.page,
            )
            return WorkResult(
                outcome="failed", references={"reason": type(exc).__name__}, requeue=False
            )
        log.info(
            "arv2.display_page_written",
            workspace_id=scope.workspace_id,
            subject_kind=scope.subject_kind,
            subject_id=scope.subject_id,
            page=scope.page,
            generated=list(result.generated),
            regenerated=list(result.regenerated),
            failed=list(result.failed),
            cost_usd=str(result.cost_usd),
        )
        references: dict[str, JsonValue] = {
            "generated": list(result.generated),
            "regenerated": list(result.regenerated),
            "skipped_empty": list(result.skipped_empty),
            "failed": list(result.failed),
            "cost_usd": str(result.cost_usd),
            "finished_at": datetime.now(UTC).isoformat(),
        }
        return WorkResult(outcome="completed", references=references, requeue=False)


def build_arv2_display_page_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    artifacts: ArtifactSink,
    conn_factory: ConnFactory = transaction,
) -> Arv2DisplayPageWorkHandler | None:
    """Compose the handler on this worker, or refuse loudly and compose nothing.

    The same two conditions the web seam's ``_production_runner_factory`` checks (spec §2): the
    display flag, and a model key. Without either the tasks stay queued for a worker that has both,
    which is the honest outcome — a keyless handler would fail every task at its first call.

    The artifact sink is injected from *outside* the lane, like the discovery lane's: ARV2 may not
    open a second write path into the artifact table (Global Constraint 7).
    """
    if not settings.arv2_display_generate_on_read:
        log.info(
            "arv2.display_page_handler_not_composed",
            reason="CLUE_ARV2_DISPLAY_GENERATE_ON_READ is off",
        )
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "arv2.display_page_handler_not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail="display page tasks stay queued until a worker with the key drains them",
        )
        return None
    return Arv2DisplayPageWorkHandler(
        settings=settings,
        conn_factory=conn_factory,
        runner_factory=default_runner_factory(settings, secrets),
        artifacts=artifacts,
    )
