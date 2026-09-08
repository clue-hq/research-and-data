# R2 facts — fleet plane, O3 driver pattern, store, settings (scouted 2026-09-08, verified refs)

Correction to the scout's note on alembic: `uv run alembic heads` on this branch returns exactly ONE
head, `9f81e5692fea` (the O3+O4 join). The "multiple heads" remark was a grep artefact. New
migrations chain off `9f81e5692fea`.

## 1. Fleet plane — `platform/fleet/clue_fleet/`

`FleetTaskKind` (`enums.py:17`), members in order: DRIVE_RUN, ACCOUNT_JOB, EXECUTE_GRAPH,
ENTITY_RESEARCH_JOB, AGENT_TURN, STAGE0_RECON, OFFICIAL_SITE_CRAWL, DESIGN_JOB, ONBOARDING_RUN.
Contract (`enums.py:46-49`): new members are APPENDED, never inserted; DB enum grown with
`ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS '<label>'`; parity test compares in order.

Change-set ONBOARDING_RUN needed (mirror it):
- member `enums.py:62`; migration `alembic/versions/af3cf1541ebe_arv2_onboarding_run_kind_and_lineage.py`
  (`_KINDS_BEFORE` tuple :52-62; upgrade :62-64; downgrade :113-134 refuses while rows exist, then
  RENAME → CREATE TYPE with old labels → ALTER COLUMN kind TYPE … USING kind::text::… → DROP old);
- `tests/fleet/test_fleet_db.py:57` `test_fleet_task_kind_enum_matches_db` (ordered parity);
- `tests/db/test_arv2_onboarding_kind_migration.py:26` asserts `labels[-1] == "onboarding_run"` —
  WILL BREAK when a new kind is appended; relax it to `"onboarding_run" in labels` in the same task;
- `tests/api/test_fleet_wiring.py:268` wiring guard test.

`work_worker.py`:
```python
@dataclass(frozen=True, slots=True)  # :35
class WorkContext:
    task_id: UUID; work_id: WorkId; worker_id: str; lease_generation: LeaseGeneration
    payload: dict[str, JsonValue]; stop_requested: asyncio.Event; lease_lost: asyncio.Event
    task_attempt: int = 1
@dataclass(frozen=True, slots=True)  # :47
class WorkResult:
    outcome: str; references: dict[str, JsonValue]; requeue: bool = False
    task_finalized: bool = False; requeue_after: timedelta | None = None
    def result_ref(self) -> dict[str, JsonValue]: return {"outcome": self.outcome, **self.references}
@runtime_checkable  # :66
class WorkHandler(Protocol):
    @property
    def kind(self) -> FleetTaskKind: ...
    async def handle(self, context: WorkContext) -> WorkResult: ...   # param is `context`
```
Handler exception → task FAILED `{"outcome":"error"}` (:274-279) — handlers contain everything.
Lease lost → handler cancelled → requeue (:266). Heartbeat is the worker's (:318-361); never
heartbeat from the handler. Constructor invariant: heartbeat_interval*2 < lease_ttl. One handler
per kind. `WorkId = NewType("WorkId", UUID)` (`lease.py:21`). `DEFAULT_TASK_STALE_AFTER=60s`.
No fleet-level concurrency: O3 uses an in-handler `asyncio.Semaphore(settings.onboarding_max_parallel_runs)`.

`WorkQueue` protocol (`queue.py:726`): `enqueue(*, kind, work_id, dedup_key, priority=0, payload=None,
reopen_terminal=False) -> bool`; `claim_next(...)`; `finish(...)`; `touch(...)`; `requeue(...)`.
`DbWorkQueue(queue: TaskQueue | None = None)` (`queue.py:769`). Dedup: duplicate
`(kind, project_run_id, dedup_key)` is a no-op unless `reopen_terminal=True` and the row is terminal.
Lower priority claims first (onboarding uses -150). Do NOT use `enqueue_work` (forces
`reopen_terminal=True`, `dedup_key=str(work_id)`); call `WorkQueue.enqueue` directly like O3.

## 2. O3 driver — `platform/api/clue_api/arv2/onboarding_driver.py`

```python
class OnboardingRunWorkHandler:  # :251
    kind = FleetTaskKind.ONBOARDING_RUN
    def __init__(self, *, settings: Settings, conn_factory: ConnFactory, artifacts: ArtifactSink,
                 exa: ExaClientFactory, client_binder: ClientEntityBinder | None = None,
                 synthesis: SynthesisLauncher | None = None, clock: Callable[[], date] = date.today,
                 store: Any = default_store, synchronize_catalog: Callable[..., Any] = default_synchronize) -> None
        ... self._db_lock = asyncio.Lock()   # at most ONE connection at a time
    async def handle(self, context: WorkContext) -> WorkResult:  # :289
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            return WorkResult(outcome="stopped", references={}, requeue=True)
        scope = self._scope(context.payload)
        if UUID(str(context.work_id)) != scope.run_id: raise ValueError(...)
        try: status = await self._run(scope)
        except Exception:
            log.exception(...); try: async with self._connection() as conn: await self._store.fail_run(conn, run_id=...)
            except Exception: log.exception(...)
            return WorkResult(outcome="failed", references={"run_id": str(scope.run_id)}, requeue=False)
        return WorkResult(outcome=status, references={"run_id": str(scope.run_id)})
    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:  # :324
        async with self._db_lock, self._conn_factory() as conn: yield conn
```
`ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]` (`libs/clue-db/clue_db/engine.py:45`);
production passes `transaction` (`engine.py:152`).

Caller factory (:193):
```python
def build_onboarding_provider_caller(settings: Settings, *, run_id: UUID, step_label: str) -> ProviderCaller:
    root = Path(settings.arv2_raw_root) / "onboarding" / str(run_id) / step_label.replace(":", "_")
    root.mkdir(parents=True, exist_ok=True)
    return ProviderCaller(transport=HttpxTransport(), raw_sink=FileRawSink(root / "raw"),
                          ledger=JsonlLedger(root / "ledger.jsonl"), now=lambda: datetime.now(UTC))
def build_onboarding_exa_client_factory(settings: Settings, secrets: Secrets) -> ExaClientFactory:  # :211
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip(): raise ValueError("CLUE_EXA_API_KEY is required ...")
```
Every provider call: `await asyncio.to_thread(client.agent_run, ...)` (:483). Failures → `_StepOutcome`
via `_failed_step(error)` (:758: status="failed", failure_code=type(error).__name__,
failure_message=str(error)[:500]); settled by `_settle` (bytes first, then rows).
Deterministic ids: `uuid5(NAMESPACE_URL, f"onboarding-step:{run_id}:{kind}:{subject or ''}")`.
Constants: `ONBOARDING_DEDUP_PREFIX = "onboarding-run:"` (:89); `onboarding_work_id(run_id) -> WorkId(run_id)` (:110).
Enqueue side `onboarding_routes.py`: `ONBOARDING_TASK_PRIORITY = -150`; `DbOnboardingEnqueuer.enqueue`
calls `self._queue.enqueue(kind=..., work_id=..., dedup_key=f"{PREFIX}{run_id}", priority=-150,
payload={...}, reopen_terminal=False)`.

## 3. Wiring

`fleet_wiring.build_multi_work_worker(settings, *, driver, graph_handler, entity_research_handler=None,
agent_turn_handler=None, stage0_recon_handler=None, official_site_crawl_handler=None,
design_handler=None, onboarding_handler=None, queue=None, leases=None, worker_id=None) -> LeasedWorkWorker` (:324);
guard :378-382 `raise ValueError("onboarding_handler must own onboarding_run tasks")`; append :397.
`fleet_main._build_onboarding_handler(settings, secrets, *, storage: StorageBackend, synthesis=None)
-> OnboardingRunWorkHandler | None` (:571): returns None when flag off; warns + None when key missing;
constructs with `conn_factory=transaction, artifacts=DurableAgentArtifactStore(storage=storage,
conn_factory=transaction), exa=..., client_binder=Stage0ClientEntityBinder(), synthesis=...` (:605).
Call site `fleet_main.py:968-990`. Test constructions: `tests/arv2/test_onboarding_driver.py:281`,
`tests/arv2/test_onboarding_driver_db.py:75`.

## 4. `arv2/onboarding_store.py` public API (all `async`, first arg `conn: AsyncConnection`)
`create_run(*, run_id, workspace_id, brand_id, company_domain, requested_by_user_id)`; `mark_run_running(*, run_id)`;
`start_step(*, step_id, run_id, workspace_id, kind, phase, subject_ref=None)`; `open_document(*, document_id,
workspace_id, brand_id, folder, path, kind, step_id) -> int`; `publish_document(*, document_id, artifact_key,
artifact_sha256, status="ready")`; `fail_document(*, document_id, status: Literal["empty","failed"])`;
`finish_step(*, step_id, status: TerminalStep, provider_run_id=None, raw_artifact_key=None, cost_usd=Decimal(0),
searches=0, failure_code=None, failure_message=None)`; `finish_run(*, run_id) -> str`; `fail_run(*, run_id)`;
`read_current_run(*, workspace_id) -> RunStatus | None`; `list_documents(*, workspace_id, brand_id,
all_versions=False) -> tuple[DocumentRow, ...]` where `DocumentRow(document_id, folder, path, kind, version,
status, artifact_key, artifact_sha256)`. `_SERVED_STATUSES = ("ready","proposed","confirmed")`.

### Resolving an ICP artifact ref to markdown
`libs/clue-storage/clue_storage/artifacts.py:158`:
```python
async def read_verified_artifact(conn: AsyncConnection, storage: StorageBackend, *, storage_key: str,
                                 workspace_id: str) -> tuple[ArtifactRecord, bytes]
```
(raises `ArtifactIntegrityError`). Used exactly this way in `onboarding_synthesis_wiring.py:456-470`
with the row query `_current_input_documents` (:304-327: `SELECT DISTINCT ON (path) path, kind, version,
artifact_key, artifact_sha256 FROM brand_knowledge_document WHERE workspace_id=:w AND brand_id=:b AND
status = ANY(:statuses) AND artifact_key IS NOT NULL ORDER BY path, version DESC`).
Alternative: `DurableAgentArtifactStore.read(ref: ArtifactRef) -> bytes` (`agent_turn_wiring.py:363`),
`persist_body(*, workspace_id, data, media_type, subject_bindings=(), project_bindings=()) -> ArtifactRef` (:204).
`ArtifactRef` (`platform/agents/clue_agents/contracts.py:242`): workspace_id, artifact_key, sha256, media_type, byte_count.
Front matter: `arv2/knowledge_frontmatter.py` `parse_front_matter(text) -> (dict, body)` (:13),
`document_identity(front) -> (kind, icp_key|None)` (:25). ICP kind string `"icp-definition"`; answer-key ICP
path `audience/icp-clue-abm-buyers.md`.

## 5. Settings
`libs/clue-config/clue_config/settings.py` `Settings(BaseSettings)` :101, `env_prefix="CLUE_"`.
`arv2_raw_root: str = ".artifacts/arv2"` (:333); onboarding block :339-357 (`onboarding_max_parallel_runs:
int = Field(default=6, ge=1)`). `.env.example:143-159` mirrors. Parity tests: `tests/arv2/test_onboarding_settings.py`
(defaults dict :22) and `tests/arv2/test_settings.py` — any new `CLUE_ARV2_*` field goes in Settings,
`.env.example`, and the defaults dict. (Both parity tests currently FAIL on the base for unrelated reasons:
`CLUE_ONBOARDING_V2_ENABLED=true` vs default False; quoted display pitch — not R2's.)
