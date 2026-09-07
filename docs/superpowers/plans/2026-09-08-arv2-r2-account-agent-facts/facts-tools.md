# R2 facts — toolbelt, claim writer, pack keys, display, R1 client signatures, ledger table, import guard (scouted 2026-09-08)

Toolbelt package: `platform/toolbelt/clue_toolbelt/` (`envelope.py`, `errors.py`, `idempotency.py`, `invoker.py`,
`registry.py`, `runner.py`). ONLY the launch/read tools join the toolbelt; the agent's twelve tools are LangChain
`StructuredTool`s inside the arv2 driver (the M8D precedent: only `launch_account_research@1` is a toolbelt tool).

## Toolbelt contract (`envelope.py`)
```python
class ToolInput(BaseModel): model_config = ConfigDict(frozen=True, extra="forbid")            # :69
class ToolOutput(BaseModel): model_config = ConfigDict(frozen=True, extra="forbid", strict=True)  # :77
class ReplayPolicy(StrEnum): UNCERTIFIED, EFFECT_FREE, DOMAIN_IDEMPOTENT, OPERATION_IDEMPOTENT, AT_LEAST_ONCE  # :94
class ExternalReplayBoundary(StrEnum): NONE, AT_LEAST_ONCE, IDEMPOTENCY_KEY                     # :104
class ToolEffectClass(StrEnum): READ, WRITE, SPEND, STEERING                                    # :112
@dataclass(frozen=True, slots=True)
class ReplaySafety: policy; durable_identity: str; operation_id_required=False; external_boundary=NONE; notes=""  # :121
@dataclass(frozen=True, slots=True)
class PreconditionFailure: reason_code: str; message: str                                        # :294
class ToolEstimate: cost_cents: Decimal = 0; detail; @classmethod free()                         # :303
class ToolResult(BaseModel): tool: str; version: str; references: dict[str, Any]; replayed=False; meta: dict   # :319
class Tool(abc.ABC):                                                                             # :333
    name: ClassVar[str]; version: ClassVar[str] = "1"; model_description: ClassVar[str | None]
    input_model: ClassVar[type[ToolInput]]; output_model: ClassVar[type[ToolOutput]] = UntypedToolOutput
    replay: ClassVar[ReplaySafety]; effect_class: ClassVar[ToolEffectClass] = WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(); pin_requirements: ClassVar[tuple[str, ...]] = ()
    async def preconditions(self, inputs: ToolInput, ctx: ToolContext) -> Sequence[PreconditionFailure]
    def estimate(self, inputs: ToolInput) -> ToolEstimate
    @abc.abstractmethod
    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult
```
`ToolContext` (:218): workspace_id, actor, conn_factory, operation_id, principal_kind, actor_id, membership_id,
action_ref, quality_mode, execution_id, …  A granted tool must be `recipe_safe` (typed output + certified replay) and
not STEERING. `JournalParameterPolicy(safe_display_fields=(...))` names must be top-level input fields.
Registration: `registry.register(tool, make_default=True)` inside `build_toolbelt(...)` (`toolbelt_wiring.py:2607-2642`,
entity-research launch tools registered at :2773 via `build_entity_research_launch_tools(services, *,
budget_controls_enabled, conn_factory)`). Authority: `C6_AGENT_TOOL_AUTHORITY: dict[str, tuple[AgentRole, ...]]`
(`agent_registry_wiring.py:90`), e.g. `"launch_account_research": (AgentRole.HEAD_OF_ABM,)` (:223); composition
asserts `set(registry.names()) == set(C6_AGENT_TOOL_AUTHORITY)` (:538). Test `tests/agents/test_tool_authority_audit.py`
asserts `len(C6_AGENT_TOOL_AUTHORITY) == 120` (:80) — bump with a reviewed comment. Reference tool:
`LaunchAccountResearchTool` (`entity_research_launch_tools.py:459-487`): SPEND, DOMAIN_IDEMPOTENT, preconditions
`_not_composed()` / `_trusted_action(ctx)` (refuses `launch_action_ref_missing` when `ctx.action_ref is None`).

## Claim writer (`platform/api/clue_api/arv2/claim_writer.py`)
```python
@dataclass(frozen=True)
class ClaimDraft:  # :60
    entity_id: EntityId; entity_type: EntityType; field_key: str; value_json: JsonValue
    extraction_method: ExtractionMethod; run_id: RunId; research_mode: ResearchMode; workspace_id: str
    source_url: str | None = None; source_key: str | None = None; evidence_span: str | None = None
    observed_at: datetime | None = None; confidence: float = 0.5
    identity_binding: IdentityBinding | None = None; use_class: UseClass | None = None
    signal_priority: int = 3; outreach_safe: bool = True; artifact_key: str | None = None
    product_id: str | None = None; field_description: str | None = None
    markers: Mapping[str, JsonValue] = field(default_factory=dict)
@dataclass(frozen=True)
class WriteReceipt: claim_id: ClaimId; field_key: str; markers: dict[str, JsonValue]; registered_field: bool  # :87
class LenientClaimWriter:
    def __init__(self, *, lenient: bool) -> None                                   # :105
    async def write(self, conn: AsyncConnection, draft: ClaimDraft) -> WriteReceipt  # :108
```
Tier by method (`TIER_FOR_METHOD`): API/CRM_IMPORT/HUMAN=1, SCRAPE=2, LLM_SYNTHESIS=4. Lenient: missing URL → marker
`source_missing`; unknown key → auto-registered proposed field + marker `proposed_field`; schema miss → `schema_valid=False`.
Enums (`libs/clue-core/clue_core/enums.py`): `EntityType.ACCOUNT|CONTACT`; `ExtractionMethod.API|SCRAPE|LLM_SYNTHESIS|HUMAN|CRM_IMPORT`;
`ResearchMode.ACCOUNT_DISCOVERY|ACCOUNT_PROFILING|COMMITTEE_DISCOVERY|CONTACT_PROFILING`.

## Registered keys
ARV2 pack (`catalog_seed.py:67-388`, `ARV2_FIELD_KEYS`, `load_arv2_pack(conn)`), account side: `account.open_requisitions`
(list[object] {title*, dept, published, days_open:int, salary_band, still_listed:bool, url}), `account.gtm_tooling_stack`
(object {present[], absent[], notes}), `account.named_customers` (list[str]), `account.reputation_risk` (object {what*, status,
source_note}; born outreach_safe=false), `account.abm_program_maturity` (object), `core.legal_name`, `core.founded_year`,
`core.company_crunchbase_url`, `core.company_languages`, `core.company_twitter_url`, `core.company_type`,
`core.industries_all`, `core.tech_stack_categorised`, `account.employee_roster_sample`, `account.hiring_velocity`,
`account.media_layer_index`, `account.media_transcript_quality_warning`, `account.claimed_customer_logos`,
`account.claimed_outcomes_metrics`, `account.product_packaging`; contact side 21–38 (R3). Builders `_row(key, value_type,
schema, description, *, pass_kind=DEEP, ttl_days=90, use_class_hint=None)`. Core pack keys seen in discovery policy:
`core.annual_revenue`, `core.company_email`, `core.company_linkedin_url`, `core.company_phone`, `core.employee_count`,
`core.employee_range`, `core.hq_location`, `core.industry`, `core.primary_domain`, `core.revenue_band`.
`register_field` refuses redefinition → new keys must not collide.

## `account_activity_event` (D1): kinds `created|contacts|summary|artifact|updated`, `actor_kind clue|person`; writer
example `display/page.py:130-160` (`record_page_written`).

## R1 client signatures (see `platform/api/clue_api/arv2/README.md` + the scout brief; the load-bearing ones)
`ProviderCaller(*, transport, raw_sink, ledger, ceilings=None, sleep=time.sleep, monotonic=time.monotonic, now)`;
`.call(spec) -> CallResult`; `.halted(provider) -> str|None`; `.reset_halt(provider)`; `.totals() -> SpendTotals`.
`CallResult(response, latency_ms, attempts, raw_ref, raw_refs, ledger_row_id, cost: CostReading, over_ceiling, call_cost: CallCost)`.
`CallCost(cost_usd, credits, media_seconds, cost_source, ledger_row_id, raw_ref, provider, operation)`.
`AiArkClient(caller, api_key, *, min_gap_s, base_url=…, sleep, monotonic)`: `.company_by_domain(domain) -> AiArkCompany|None`
(fields name, domain, linkedin, industry, employee_count, revenue, technologies, location, raw, cost);
`.people_by_name(name_variants, domain, *, size=3) -> AiArkPeople` (people: AiArkPerson(full_name, title, headline,
linkedin_url, location, current_company, current_company_domain, department, ark_id, raw); cost); `.export_email(url)`.
`ExaClient(caller, api_key, *, base_url, sleep, monotonic)`: `.search(query, *, type="auto", num_results=8, include_domains=None,
include_text=None, start_published_date=None, end_published_date=None, category=None, text_max_chars=1500, highlights=None,
label, timeout_s=180) -> ExaSearchResult(results: ExaHit(url,title,published_date,author,text,highlights), status, cost_usd,
request_id, raw_ref, ledger_row_id, cost)`; `.contents(urls, *, text_max_chars=8000, livecrawl=None, highlights=None, label,
timeout_s=240) -> ExaContentsResult(results, statuses, …)`; `.deep_reasoning(*, system_prompt, query, output_schema,
num_results=20, additional_queries=None, include_domains=None, text_max_chars=10000, highlights_query=None,
highlights_max_chars=2000, label, timeout_s=1200) -> ExaDeepResult(output_text, output_object, report_text, grounding,
results, status, cost_usd, request_id, raw_ref, ledger_row_id, cost, retried)`; `report_output_schema() -> dict`;
`is_thin_deep_response(*, n_results, cost_usd, report_chars) -> bool`.
ATS: `find_board(company_url, caller) -> AtsBoard|None`; `fetch_postings(board, caller) -> BoardPostings(board, url, postings:
JobPosting(title, department, team, location, published_at: date|None, days_open, is_listed, compensation, description_plain,
url, apply_url, provider_fields), raw_ref, ledger_row_id, cost)`; `career_page_candidates(homepage_html, homepage_url)`;
`detect_boards(html, page_url)`; `BoardNotFound(kind, slug, url)`, `BoardFetchFailed(kind, slug, url, status)`.
Media: `fetch_feed(url, caller) -> Podcast(title, feed_url, episodes: Episode(number, title, enclosure_url, enclosure_bytes,
duration_s, published_at, link, description), cost)`; `find_episode(podcast, *, number=None, title_contains=None)`;
`download_enclosure(episode, dest: Path, caller, *, max_bytes) -> AudioFile(path, bytes, sha256, duration_s, content_type, cost)`;
`youtube_metadata(watch_url, caller) -> YouTubeMeta(video_id, title, length_s, cost)`; `youtube_words(watch_url, page_text:
PageTextFetcher, *, title=None, cost=None) -> YouTubeWords(url, title, text, cost)`; `reject_native_video(url)` raises.
`GeminiMediaClient(caller, *, openrouter_api_key, openrouter_base_url, gemini_api_key, short_model, transcribe_model,
embedding_model, media_budget: MediaBudget, short_max_seconds, ledger: LedgerSink, sleep, now)`: `.transcribe_short(audio,
*, context: SpeakerContext) -> Transcript`; `.transcribe_long(...)`; `.mine_quotes(transcript_text, *, context, n=6,
speaker_verified=None) -> MinedQuotes(quotes: QuoteCandidate…, cost)`; `MediaBudget(ceiling_s)` `.reserve/.release`;
`transcription_input_from_enclosure(...)`; `verify_speaker(...)`; `detect_loops(...)`; `SpeakerContext(person_name,
person_role="", organisation="", named_in_metadata=False)`; `Transcript(model, text, lines, meta, quotes, has_timestamps,
cost, upload_costs)`; `MediaCeilingExceeded(*, ceiling_s, used_s, requested_s)`.
Structuring: `StructuringClient(caller, *, api_key, base_url, model)`: `.structure_account(subject: AccountSubject(name, domain,
already_known=None), bundle: str, catalog: FieldCatalog) -> StructuredOutput(claims: StructuredClaim(field_key, value,
evidence_span, source_url, source_kind, confidence, use_class, outreach_safe, priority, media_timestamp, evidence_verbatim,
schema_valid), proposed: ProposedField(suggested_key, why, value, evidence_span, source_url, origin), negatives:
NegativeOrRisk(what, status, evidence_span, source_url, outreach_safe), model, cost_usd, request_id, raw_ref, cost)`;
`.structure_person(subject: PersonSubject(name, company, linkedin_url), bundle, catalog)`; `FieldSpec(key, description,
value_schema=None)`; `FieldCatalog(account=(), contact=(), facet=())` `.specs()/.keys()/.spec(key)`; `catalog_menu_text(catalog)`.
Sinks: `RawSink.save(record: RawRecord, body: bytes) -> str`; `LedgerSink.record(row: LedgerRow) -> str`; `LedgerRow(row_id,
call_id, phase, provider, operation, label, recorded_at, http_status, latency_ms, attempts, estimate_usd, estimate_credits,
estimate_media_seconds, cost_usd, credits, media_seconds, over_ceiling, outcome, error_code, provider_request_id, raw_ref,
extras)`; `RawRecord`/`RawRequest`/`RawResponse` (`sinks.py:87-130`); `FileRawSink(root)`, `JsonlLedger(path)`,
`MemoryRawSink()`, `MemoryLedger()`. `text.substring_verdict(needle, haystack, *, window=40, stride=10) -> "EXACT"|"PARTIAL"|"NOT_FOUND"`.
Import-guard cost test (`tests/arv2/test_import_guard.py:137-181`): every listed client return dataclass must carry `cost`.

## `provider_call_ledger` (D1 `65fb2128c904:205`)
columns: ledger_id uuid PK default gen_random_uuid(), call_id uuid NOT NULL, workspace_id text, project_id text,
project_run_id text, entity_research_job_id uuid, provider, operation, label (NOT NULL), phase CHECK ('estimate','result'),
http_status int, latency_ms int, attempts int DEFAULT 0, estimate_usd numeric(12,6), estimate_credits numeric(12,3),
estimate_media_seconds int, cost_usd numeric(12,6), credits numeric(12,3), media_seconds int, over_ceiling bool,
outcome CHECK ('estimate','ok','client_error','retry_exhausted','halted','transport_error'), error_code, provider_request_id,
request_artifact_key, response_artifact_key, recorded_at. Indexes (workspace_id, recorded_at), (call_id).
NO `extras` column and NO `raw_ref` column → the R2 migration adds `extras_json jsonb` and maps `raw_ref` → `response_artifact_key`.

## Import guard allowlist (`tests/arv2/test_import_guard.py:20`)
clue_api.arv2, clue_core, clue_config, clue_obs, clue_storage, clue_db, clue_gateway, clue_locks, clue_spine, clue_toolbelt,
clue_fleet, clue_agents, clue_execution, clue_auth, clue_projections, clue_research.claimstore, clue_research.identity,
clue_research.membership, clue_research.durable.project_run, clue_api.composition, clue_api.arv2_wiring. Forbidden SDK roots:
openai, google, exa_py, firecrawl, sumble. Third-party (langchain, langgraph, httpx) unrestricted.
