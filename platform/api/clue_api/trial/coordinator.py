"""Local-development coordinator for the resumable Sumble-only Clue Trial.

The JSON files in ``trial_root`` are opaque resume/report handles. Postgres, artifact storage, the
project state machine, and C7 remain authoritative for business and research state.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text

from clue_api.stage0_trial import (
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
    create_stage0_trial_session,
)
from clue_api.trial.spine import (
    ClueTrialSpine,
    SumbleAcquisitionResult,
    TrialReadinessOverrideRequired,
    TrialResearchState,
)
from clue_api.trial.stage0_runtime import (
    memory_assembly_factory,
    memory_write_factory_builder,
)
from clue_config import Secrets, Settings
from clue_core import EntityId, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_locks import get_redis
from clue_toolbelt import DbIdempotencyStore, body_sha256

_SCHEMA_VERSION = "1"


class CreateTrialInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str | None = Field(default=None, min_length=1, max_length=63)
    company_name: str = Field(min_length=1)
    website: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    project_name: str = Field(min_length=1)


class TurnInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1)


class AccountInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    icp_key: str = Field(min_length=1)
    icp_version: int = Field(ge=1)
    domain: str = Field(min_length=1)
    name: str | None = None
    project_budget_cap_cents: Decimal = Field(default=Decimal(5_000), ge=0)
    readiness_override_reason: str | None = None
    sumble_credit_cap: int = Field(default=3, ge=3)
    allow_unbounded_tech: bool = False


class ResearchInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["preview", "acquire", "approve_direct_research"]


class SumbleReceiptRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    request_id: str | None = None
    credits_used: int = Field(ge=0)
    credits_remaining: int | None = None
    artifact_key: str
    estimated_max_credits: int | None = None
    unbounded_call_approved: bool = False


class ClueTrialManifest(BaseModel):
    """Non-authoritative local handles needed to resume the backend run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    trial_id: str
    create_request_sha256: str
    created_at: datetime
    updated_at: datetime
    icp_key: str | None = None
    icp_version: int | None = None
    project_run_id: UUID | None = None
    readiness_decision_id: UUID | None = None
    readiness_overridden: bool = False
    account_entity_id: UUID | None = None
    account_domain: str | None = None
    account_name: str | None = None
    project_budget_cap_cents: Decimal | None = None
    sumble_credit_cap: int = 3
    allow_unbounded_tech: bool = False
    sumble_receipts: tuple[SumbleReceiptRef, ...] = ()
    sumble_skipped: tuple[str, ...] = ()
    phase: str | None = None
    run_status: str | None = None
    research_view_error: str | None = None


class TrialPaths(BaseModel):
    """Path resolver kept as data so report writers cannot confuse sessions."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def timeline(self) -> Path:
        return self.root / "timeline.jsonl"

    @property
    def research_view(self) -> Path:
        return self.root / "research-view.json"

    @property
    def sanitized_requests(self) -> Path:
        return self.root / "sumble-requests.sanitized.jsonl"

    @property
    def claims(self) -> Path:
        return self.root / "claims.json"

    @property
    def verification(self) -> Path:
        return self.root / "verification.json"

    @property
    def failures(self) -> Path:
        return self.root / "failures.json"

    @property
    def report_html(self) -> Path:
        return self.root / "report.html"

    @property
    def scorecard(self) -> Path:
        return self.root / "scorecard.md"

    @property
    def report(self) -> Path:
        return self.root / "trial-report.json"


class TrialIdempotencyConflict(RuntimeError):
    """One HTTP idempotency key was reused for another route/body or is still pending."""


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, Decimal, UUID)):
        return str(value)
    raise TypeError(f"cannot encode {type(value).__name__}")


def _json_object(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


class ClueTrialCoordinator:
    """Compose Stage 0, the operational spine, durable idempotency, and inspection export."""

    def __init__(
        self,
        *,
        settings: Settings,
        root: Path | None = None,
        spine_factory: Callable[[], ClueTrialSpine] | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._root = (root or Path(settings.trial_root)).resolve()
        self._conn_factory = conn_factory
        self._spine_factory = spine_factory or (
            lambda: ClueTrialSpine(settings=settings, conn_factory=conn_factory)
        )
        self._idempotency = DbIdempotencyStore(conn_factory=conn_factory)

    def _stage0_paths(self, trial_id: str) -> Stage0TrialPaths:
        return Stage0TrialPaths.for_session(self._root, trial_id)

    def _paths(self, trial_id: str) -> TrialPaths:
        return TrialPaths(root=self._stage0_paths(trial_id).root)

    def _load_state(self, trial_id: str) -> Stage0TrialState:
        paths = self._stage0_paths(trial_id)
        if not paths.state.exists():
            raise FileNotFoundError(f"unknown trial {trial_id!r}")
        return paths.load_state()

    def _load_manifest(self, trial_id: str) -> ClueTrialManifest:
        path = self._paths(trial_id).manifest
        if not path.exists():
            raise FileNotFoundError(f"trial {trial_id!r} has no manifest")
        return ClueTrialManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_manifest(self, manifest: ClueTrialManifest) -> None:
        paths = self._paths(manifest.trial_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        updated = manifest.model_copy(update={"updated_at": datetime.now(UTC)})
        temporary = paths.root / ".manifest.json.tmp"
        temporary.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(paths.manifest)

    def _event(self, trial_id: str, kind: str, payload: dict[str, JsonValue]) -> None:
        paths = self._paths(trial_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": _SCHEMA_VERSION,
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "payload": payload,
        }
        with paths.timeline.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    async def _stage0(self, trial_id: str) -> Stage0Trial:
        state = self._load_state(trial_id)
        return await Stage0Trial.build(
            state=state,
            paths=self._stage0_paths(trial_id),
            memory_assembly_factory=memory_assembly_factory,
            memory_write_factory_builder=memory_write_factory_builder,
            settings=self._settings,
            conn_factory=self._conn_factory,
        )

    async def execute_idempotent(
        self,
        *,
        trial_id: str,
        route: str,
        key: str,
        body: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Execute one route once per workspace/key and replay its prior response."""

        state = self._load_state(trial_id)
        request_sha = body_sha256(body)
        prior = await self._idempotency.lookup(
            state.workspace_id,
            key,
            ttl_s=self._settings.toolbelt_idempotency_ttl_s,
        )
        if prior is not None:
            if (
                prior.tool_name != route
                or prior.body_sha256 != request_sha
                or prior.status != "completed"
                or prior.response_json is None
            ):
                raise TrialIdempotencyConflict(
                    "Idempotency-Key is pending or was used for a different route/body"
                )
            return prior.response_json
        reserved = await self._idempotency.reserve(
            state.workspace_id,
            key,
            tool_name=route,
            body_sha256=request_sha,
            ttl_s=self._settings.toolbelt_idempotency_ttl_s,
        )
        if not reserved:
            raise TrialIdempotencyConflict("Idempotency-Key was claimed concurrently")
        try:
            response = await operation()
            await self._idempotency.complete(
                state.workspace_id,
                key,
                response_json=response,
            )
            return response
        except BaseException:
            await self._idempotency.release(state.workspace_id, key)
            raise

    async def create(self, body: CreateTrialInput, *, key: str) -> dict[str, Any]:
        request = body.model_dump(mode="json")
        request_sha = body_sha256(request)
        key_sha = hashlib.sha256(key.encode()).hexdigest()
        receipt_path = self._root / ".create-idempotency" / f"{key_sha}.json"
        trial_id = body.trial_id or f"trial-{key_sha[:16]}"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                not isinstance(receipt, dict)
                or receipt.get("request_sha256") != request_sha
                or receipt.get("trial_id") != trial_id
            ):
                raise TrialIdempotencyConflict(
                    "Idempotency-Key was used for a different trial creation request"
                )
            return await self.get(trial_id)
        paths = self._stage0_paths(trial_id)
        if paths.state.exists():
            manifest = self._load_manifest(trial_id)
            if manifest.create_request_sha256 != request_sha:
                raise TrialIdempotencyConflict(
                    f"trial {trial_id!r} already exists with a different creation request"
                )
            return await self.get(trial_id)
        paths, state = await create_stage0_trial_session(
            paths_root=self._root,
            session_name=trial_id,
            company_name=body.company_name,
            website=body.website,
            product_name=body.product_name,
            project_name=body.project_name,
            conn_factory=self._conn_factory,
        )
        moment = datetime.now(UTC)
        self._save_manifest(
            ClueTrialManifest(
                trial_id=state.session_slug,
                create_request_sha256=request_sha,
                created_at=moment,
                updated_at=moment,
            )
        )
        trial = await self._stage0(state.session_slug)
        try:
            await trial.export_report()
        finally:
            await trial.close()
        self._event(
            state.session_slug,
            "trial.created",
            {"workspace_id": state.workspace_id, "project_id": state.project_id},
        )
        self._write_json(
            receipt_path,
            {
                "schema_version": _SCHEMA_VERSION,
                "request_sha256": request_sha,
                "trial_id": state.session_slug,
            },
        )
        return await self.get(state.session_slug)

    async def get(self, trial_id: str) -> dict[str, Any]:
        state = self._load_state(trial_id)
        manifest = self._load_manifest(trial_id)
        trial = await self._stage0(trial_id)
        try:
            snapshot = await trial.snapshot()
        finally:
            await trial.close()
        research: dict[str, Any] | None = None
        if manifest.project_run_id is not None and manifest.account_entity_id is not None:
            research_state = await self._spine_factory().research_state(
                state=state,
                project_run_id=ProjectRunId(manifest.project_run_id),
                account_entity_id=EntityId(manifest.account_entity_id),
            )
            research = research_state.model_dump(mode="json", exclude={"research_view"})
        return {
            "schema_version": _SCHEMA_VERSION,
            "trial_id": trial_id,
            "session": state.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "stage0": snapshot,
            "research": research,
            "canonical_research_view_url": self._canonical_view_url(state, manifest),
        }

    async def turn(self, trial_id: str, body: TurnInput) -> dict[str, Any]:
        trial = await self._stage0(trial_id)
        try:
            outcome, assistant = await trial.run_turn(body.message)
            response = {
                "schema_version": _SCHEMA_VERSION,
                "status": outcome.status.value,
                "assistant": assistant,
                "next_turn": trial.state.next_turn,
            }
        finally:
            await trial.close()
        self._event(
            trial_id,
            "stage0.turn.completed",
            {"status": response["status"], "next_turn": response["next_turn"]},
        )
        return response

    async def confirm_product(self, trial_id: str) -> dict[str, Any]:
        trial = await self._stage0(trial_id)
        try:
            await trial.confirm_product()
        finally:
            await trial.close()
        self._event(trial_id, "stage0.product.confirmed", {})
        return {"schema_version": _SCHEMA_VERSION, "confirmed": True}

    async def synthesize_icps(self, trial_id: str) -> dict[str, Any]:
        trial = await self._stage0(trial_id)
        try:
            proposals = await trial.synthesize_icp_proposals()
        finally:
            await trial.close()
        response = {
            "schema_version": _SCHEMA_VERSION,
            "proposals": [item.model_dump(mode="json") for item in proposals],
        }
        self._event(
            trial_id,
            "stage0.icps.synthesized",
            {"proposal_count": len(proposals)},
        )
        return response

    async def confirm_icp(self, trial_id: str, proposal: int) -> dict[str, Any]:
        trial = await self._stage0(trial_id)
        try:
            confirmation = await trial.confirm_icp_proposal(proposal)
        finally:
            await trial.close()
        response = {
            "schema_version": _SCHEMA_VERSION,
            "icp_key": confirmation.ref.icp_key,
            "icp_version": confirmation.ref.icp_version,
        }
        self._event(
            trial_id,
            "stage0.icp.confirmed",
            {
                "icp_key": confirmation.ref.icp_key,
                "icp_version": confirmation.ref.icp_version,
            },
        )
        return response

    async def add_account(self, trial_id: str, body: AccountInput) -> dict[str, Any]:
        state = self._load_state(trial_id)
        manifest = self._load_manifest(trial_id)
        spine = self._spine_factory()
        await spine.bootstrap()
        project_run = await spine.prepare_project_run(
            state=state,
            icp_key=body.icp_key,
            icp_version=body.icp_version,
            budget_cap_cents=body.project_budget_cap_cents,
            readiness_override_reason=body.readiness_override_reason,
        )
        entity_id = await spine.admit_direct_account(
            state=state,
            project_run=project_run,
            icp_key=body.icp_key,
            icp_version=body.icp_version,
            domain=body.domain,
            name=body.name,
        )
        updated = manifest.model_copy(
            update={
                "icp_key": body.icp_key,
                "icp_version": body.icp_version,
                "project_run_id": UUID(str(project_run.project_run_id)),
                "readiness_decision_id": UUID(str(project_run.readiness_decision_id)),
                "readiness_overridden": project_run.readiness_overridden,
                "account_entity_id": UUID(str(entity_id)),
                "account_domain": body.domain,
                "account_name": body.name,
                "project_budget_cap_cents": body.project_budget_cap_cents,
                "sumble_credit_cap": body.sumble_credit_cap,
                "allow_unbounded_tech": body.allow_unbounded_tech,
                "phase": "discovery",
                "run_status": "active",
            }
        )
        self._save_manifest(updated)
        self._event(
            trial_id,
            "account.admitted",
            {
                "account_entity_id": str(entity_id),
                "domain": body.domain,
                "matched_channel": "import",
            },
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "account_entity_id": str(entity_id),
            "project_run": project_run.model_dump(mode="json"),
            "research_preview": self._research_preview(updated),
        }

    async def research(
        self,
        trial_id: str,
        account_id: UUID,
        body: ResearchInput,
    ) -> dict[str, Any]:
        state = self._load_state(trial_id)
        manifest = self._load_manifest(trial_id)
        self._assert_account(manifest, account_id)
        if body.action == "preview":
            return self._research_preview(manifest)
        if manifest.project_run_id is None or manifest.account_entity_id is None:
            raise ValueError("trial has no prepared project run/account")
        if manifest.account_domain is None:
            raise ValueError("trial account is missing its domain")

        spine = self._spine_factory()
        await spine.bootstrap()
        acquisition = await spine.acquire_sumble(
            state=state,
            project_run_id=ProjectRunId(manifest.project_run_id),
            account_entity_id=EntityId(manifest.account_entity_id),
            domain=manifest.account_domain,
            max_credits=manifest.sumble_credit_cap,
            allow_unbounded_tech=manifest.allow_unbounded_tech,
        )
        if body.action == "acquire":
            research = await spine.drive_to_tier_checkpoint(
                project_run_id=ProjectRunId(manifest.project_run_id),
                account_entity_id=EntityId(manifest.account_entity_id),
            )
        else:
            research = await spine.approve_direct_research(
                state=state,
                project_run_id=ProjectRunId(manifest.project_run_id),
                account_entity_id=EntityId(manifest.account_entity_id),
            )
        updated = self._with_research(manifest, acquisition, research)
        self._save_manifest(updated)
        if research.research_view is not None:
            self._write_json(self._paths(trial_id).research_view, research.research_view)
        self._event(
            trial_id,
            f"account.research.{body.action}",
            {
                "account_entity_id": str(account_id),
                "phase": research.project_run.phase.value,
                "status": research.project_run.status.value,
                "realized_sumble_credits": acquisition.realized_credits,
            },
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "action": body.action,
            "acquisition": acquisition.model_dump(mode="json"),
            "research": research.model_dump(mode="json", exclude={"research_view"}),
            "canonical_research_view_url": self._canonical_view_url(state, updated),
        }

    async def events(self, trial_id: str) -> dict[str, Any]:
        self._load_state(trial_id)
        path = self._paths(trial_id).timeline
        events = (
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            if path.exists()
            else []
        )
        return {"schema_version": _SCHEMA_VERSION, "events": events}

    async def cost(self, trial_id: str) -> dict[str, Any]:
        manifest = self._load_manifest(trial_id)
        realized = sum(item.credits_used for item in manifest.sumble_receipts)
        return {
            "schema_version": _SCHEMA_VERSION,
            "sumble": {
                "hard_credit_cap": manifest.sumble_credit_cap,
                "realized_credits": realized,
                "tech_unbounded_call_approved": manifest.allow_unbounded_tech,
                "receipts": [item.model_dump(mode="json") for item in manifest.sumble_receipts],
            },
            "note": (
                "The hard cap covers Organizations and Jobs. Confirmed Tech Stack is excluded "
                "unless its separate unbounded per-result risk was approved."
            ),
        }

    async def report(self, trial_id: str) -> dict[str, Any]:
        status = await self.get(trial_id)
        events = await self.events(trial_id)
        costs = await self.cost(trial_id)
        manifest = self._load_manifest(trial_id)
        research_view: dict[str, Any] | None = None
        if manifest.project_run_id is not None and manifest.account_entity_id is not None:
            state = self._load_state(trial_id)
            research = await self._spine_factory().research_state(
                state=state,
                project_run_id=ProjectRunId(manifest.project_run_id),
                account_entity_id=EntityId(manifest.account_entity_id),
            )
            research_view = research.research_view
        report = {
            "schema_version": _SCHEMA_VERSION,
            "generated_at": manifest.updated_at.isoformat(),
            "status": status,
            "events": events["events"],
            "cost": costs,
            "research_view": research_view,
            "quality_limits": {
                "account_only": True,
                "buying_committee_complete": False,
                "sumble_only": True,
                "website_scraping_performed": False,
                "exa_performed": False,
            },
        }
        self._export_inspection_artifacts(trial_id, report)
        return report

    async def doctor(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        try:
            async with self._conn_factory() as conn:
                heads = (
                    (await conn.execute(text("SELECT version_num FROM alembic_version ORDER BY 1")))
                    .scalars()
                    .all()
                )
            checks["database"] = "ok"
            checks["migration_heads"] = [str(value) for value in heads]
            checks["single_migration_head"] = len(heads) == 1
        except Exception as exc:  # noqa: BLE001 - doctor reports the boundary failure.
            checks["database"] = f"error:{type(exc).__name__}"
            checks["single_migration_head"] = False
        try:
            checks["redis"] = "ok" if await get_redis().ping() else "error:no_pong"
        except Exception as exc:  # noqa: BLE001 - doctor reports the boundary failure.
            checks["redis"] = f"error:{type(exc).__name__}"
        secrets = Secrets()
        checks["openrouter_key"] = secrets.openrouter_api_key is not None
        checks["sumble_key"] = secrets.sumble_api_key is not None
        checks["trial_enabled"] = self._settings.trial_enabled
        checks["c7_read_enabled"] = self._settings.c7_research_view_read_enabled
        checks["sumble_only_sources"] = sorted(self._spine_factory().allowed_source_keys)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / ".write-probe"
            probe.touch(exist_ok=True)
            probe.unlink(missing_ok=True)
            checks["report_root_writable"] = True
        except OSError:
            checks["report_root_writable"] = False
        ready = bool(
            checks.get("database") == "ok"
            and checks.get("single_migration_head")
            and checks.get("redis") == "ok"
            and checks.get("openrouter_key")
            and checks.get("sumble_key")
            and checks.get("trial_enabled")
            and checks.get("c7_read_enabled")
            and checks.get("report_root_writable")
        )
        return {"schema_version": _SCHEMA_VERSION, "ready": ready, "checks": checks}

    @staticmethod
    def _assert_account(manifest: ClueTrialManifest, account_id: UUID) -> None:
        if manifest.account_entity_id != account_id:
            raise FileNotFoundError("account is not part of this trial")

    @staticmethod
    def _research_preview(manifest: ClueTrialManifest) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "provider": "sumble",
            "calls": [
                {"surface": "organizations", "maximum_credits": 2, "bounded": True},
                {"surface": "jobs", "maximum_credits": 1, "bounded": True},
                {
                    "surface": "confirmed_tech_stack",
                    "maximum_credits": None,
                    "bounded": False,
                    "will_run": manifest.allow_unbounded_tech,
                },
            ],
            "hard_credit_cap": manifest.sumble_credit_cap,
            "minimum_required_cap": 3,
            "account_domain": manifest.account_domain,
            "requires_explicit_approval": True,
        }

    @staticmethod
    def _receipt_refs(acquisition: SumbleAcquisitionResult) -> tuple[SumbleReceiptRef, ...]:
        references: list[SumbleReceiptRef] = []
        for item in acquisition.snapshots:
            if item.artifact_key is None:
                raise RuntimeError("a completed Sumble acquisition is missing its artifact receipt")
            references.append(
                SumbleReceiptRef(
                    source_key=item.source_key,
                    request_id=item.request_id,
                    credits_used=item.credits_used,
                    credits_remaining=item.credits_remaining,
                    artifact_key=item.artifact_key,
                    estimated_max_credits=item.estimated_max_credits,
                    unbounded_call_approved=item.unbounded_call_approved,
                )
            )
        return tuple(references)

    def _with_research(
        self,
        manifest: ClueTrialManifest,
        acquisition: SumbleAcquisitionResult,
        research: TrialResearchState,
    ) -> ClueTrialManifest:
        return manifest.model_copy(
            update={
                "sumble_receipts": self._receipt_refs(acquisition),
                "sumble_skipped": acquisition.skipped,
                "phase": research.project_run.phase.value,
                "run_status": research.project_run.status.value,
                "research_view_error": research.research_view_error,
            }
        )

    @staticmethod
    def _canonical_view_url(
        state: Stage0TrialState,
        manifest: ClueTrialManifest,
    ) -> str | None:
        if manifest.account_entity_id is None:
            return None
        return (
            f"/v1/projects/{state.project_id}/accounts/{manifest.account_entity_id}/research-view"
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                default=_json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _write_text(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)

    def _export_inspection_artifacts(
        self,
        trial_id: str,
        report: dict[str, Any],
    ) -> None:
        paths = self._paths(trial_id)
        view = report.get("research_view")
        view_payload = view if isinstance(view, dict) else {}
        statements: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        for section in view_payload.get("sections", []):
            if not isinstance(section, dict):
                continue
            for item in section.get("items", []):
                if not isinstance(item, dict):
                    continue
                enriched = {"section_kind": section.get("kind"), **item}
                if item.get("item_kind") == "statement":
                    statements.append(enriched)
                else:
                    references.append(enriched)

        status_summary = view_payload.get("status_summary", {})
        coverage_summary = view_payload.get("coverage_summary", {})
        verification = {
            "schema_version": _SCHEMA_VERSION,
            "status_summary": status_summary,
            "coverage_summary": coverage_summary,
            "statement_states": [
                {
                    "statement_id": item.get("statement_id"),
                    "claim_id": item.get("claim_id"),
                    "state": item.get("state"),
                    "confidence": item.get("confidence"),
                }
                for item in statements
            ],
        }
        failures: list[dict[str, Any]] = []
        manifest = self._load_manifest(trial_id)
        if manifest.run_status == "failed":
            failures.append(
                {
                    "kind": "project_run_failed",
                    "project_run_id": str(manifest.project_run_id),
                    "diagnostic_only": True,
                }
            )
        if manifest.research_view_error:
            failures.append(
                {
                    "kind": "research_view_unavailable",
                    "reason": manifest.research_view_error,
                    "diagnostic_only": True,
                }
            )

        sanitized_lines = [
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "provider": "sumble",
                    "source_key": receipt.source_key,
                    "request_id": receipt.request_id,
                    "credits_used": receipt.credits_used,
                    "credits_remaining": receipt.credits_remaining,
                    "response_artifact_key": receipt.artifact_key,
                    "authorization_header_stored": False,
                    "response_body_embedded": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            for receipt in manifest.sumble_receipts
        ]
        self._write_json(paths.report, report)
        self._write_json(paths.research_view, view_payload)
        self._write_json(
            paths.claims,
            {
                "schema_version": _SCHEMA_VERSION,
                "statements": statements,
                "owner_references": references,
            },
        )
        self._write_json(paths.verification, verification)
        self._write_json(
            paths.failures,
            {"schema_version": _SCHEMA_VERSION, "failures": failures},
        )
        self._write_text(
            paths.sanitized_requests,
            ("\n".join(sanitized_lines) + "\n") if sanitized_lines else "",
        )
        self._write_text(paths.scorecard, self._scorecard_markdown(trial_id, report))
        self._write_text(paths.report_html, self._report_html(trial_id, report))

    @staticmethod
    def _scorecard_markdown(trial_id: str, report: dict[str, Any]) -> str:
        view = report.get("research_view")
        view_payload = view if isinstance(view, dict) else {}
        status = view_payload.get("status_summary", {})
        coverage = view_payload.get("coverage_summary", {})
        return "\n".join(
            (
                f"# Manual research quality scorecard: {trial_id}",
                "",
                "Rate each item from 1 (unacceptable) to 5 (excellent) after reading report.html.",
                "",
                f"- Available statements: {status.get('available_statement_count', 0)}",
                f"- Total statements: {status.get('total_statement_count', 0)}",
                f"- Terminal coverage gaps: {coverage.get('terminal_gap_count', 0)}",
                "",
                "| Criterion | Score (1-5) | Notes |",
                "|---|---:|---|",
                "| Factual correctness against linked evidence |  |  |",
                "| Relevance to the confirmed ICP |  |  |",
                "| Depth and specificity |  |  |",
                "| Usefulness for account strategy |  |  |",
                "| Honest handling of unknowns and gaps |  |  |",
                "| Cost relative to useful output |  |  |",
                "",
                "Decision: [ ] accept Sumble baseline  [ ] rerun  [ ] stop before Exa",
                "",
            )
        )

    @staticmethod
    def _report_html(trial_id: str, report: dict[str, Any]) -> str:
        view = report.get("research_view")
        view_payload = view if isinstance(view, dict) else {}
        cost = report.get("cost", {}).get("sumble", {})
        rows: list[str] = []
        for section in view_payload.get("sections", []):
            if not isinstance(section, dict):
                continue
            kind = html.escape(str(section.get("kind", "unknown")))
            items = section.get("items", [])
            if not items:
                reason = html.escape(", ".join(map(str, section.get("reason_codes", []))))
                rows.append(
                    f"<tr><td>{kind}</td><td colspan='4'><em>Empty</em> "
                    f"(explicit reasons: {reason or 'unknown'})</td></tr>"
                )
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_kind = str(item.get("item_kind", "reference"))
                owner = item.get("statement_id") or item.get("owner_ref") or item.get("item_id")
                field = item.get("field_key") or item.get("data_species")
                value: object = (
                    item.get("value_json")
                    if item_kind == "statement"
                    else "Reference-only; resolve through owning authority"
                )
                state = item.get("state") if item_kind == "statement" else "owner reference"
                rows.append(
                    "<tr>"
                    f"<td>{kind}</td>"
                    f"<td>{html.escape(str(field))}</td>"
                    f"<td><code>{html.escape(json.dumps(value, ensure_ascii=False))}</code></td>"
                    f"<td>{html.escape(json.dumps(state, ensure_ascii=False))}</td>"
                    f"<td><code>{html.escape(str(owner))}</code></td>"
                    "</tr>"
                )
        if not rows:
            rows.append(
                "<tr><td colspan='5'><em>No C7 research view is available yet.</em></td></tr>"
            )
        coverage = view_payload.get("coverage_summary", {})
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clue Trial — {html.escape(trial_id)}</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:32px auto;
padding:0 20px;color:#18212b}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #d7dde4;padding:8px;text-align:left;vertical-align:top}}
th{{background:#f3f6f8}}
code{{white-space:pre-wrap;word-break:break-word}}
.warning{{background:#fff5cf;padding:12px}}
</style>
</head>
<body>
<h1>Clue Sumble-only trial</h1>
<p><strong>Trial:</strong> <code>{html.escape(trial_id)}</code></p>
<p class="warning"><strong>Declared limitation:</strong> this is an account-only Sumble canary.
The buying committee is intentionally incomplete. No Exa or website scraping ran.</p>
<h2>Cost and coverage</h2>
<ul>
<li>Realized Sumble credits: {html.escape(str(cost.get("realized_credits", 0)))}</li>
<li>Bounded-call hard cap: {html.escape(str(cost.get("hard_credit_cap", 0)))}</li>
<li>Required fields: {html.escape(str(coverage.get("required_field_count", 0)))}</li>
<li>Filled fields: {html.escape(str(coverage.get("filled_field_count", 0)))}</li>
<li>Terminal gaps: {html.escape(str(coverage.get("terminal_gap_count", 0)))}</li>
</ul>
<h2>Governed C7 research view</h2>
<table>
<thead><tr><th>Section</th><th>Field/species</th><th>Value</th><th>State</th>
<th>C7 statement/owner ref</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<p>All research values above are rendered from C7 statements. Reference-only rows name their
owning authority. Empty sections remain visibly empty.</p>
</body>
</html>
"""


__all__ = [
    "AccountInput",
    "ClueTrialCoordinator",
    "ClueTrialManifest",
    "CreateTrialInput",
    "ResearchInput",
    "TrialIdempotencyConflict",
    "TrialPaths",
    "TrialReadinessOverrideRequired",
    "TurnInput",
]
