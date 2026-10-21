# ARV2 v26 — 05. Verification harness and acceptance

**Lane L7 of the v26 document set. Status: draft for adversarial review, 2026-10-07.** Written
against main `fa4bed77b` (branch `shank-audit-account-research-cost-optimization`). This document
makes "the rebuild works" a **mechanical** verdict: a frozen evidence universe, one harness that
runs v25/r26 or r27 research against it, nine acceptance tests with fixtures and thresholds, two
cost/time checkpoints with the queries that compute them, a scripted depth rater, and the go/no-go
and rollback numbers. It owns nothing the other documents own: the stages are 03 §3, the items and
their unit tests are 04, the fixtures' contents are 01b, the baselines are 01 §2–§3. Where two
documents name the same thing differently, this document says which name it uses and records the
divergence for the synthesis document (06).

**Conventions (post-reconciliation, `RECONCILIATION-RULINGS.md` R1–R20).** Recipe numbering is
R2's: **r26** = the week-1 mint on v25 behaviour, **r27** = the v26 pipeline; "v26" is the
programme (03's "recipe 26" is r27). Every setting name is 03 §10's canonical sheet (R7):
`CLUE_ARV2_V26_*` for the pipeline, the P5 selector lines 03 §10 gains from 04
(`CLUE_ARV2_RECIPE_VERSION` / `CLUE_ARV2_RECIPE_PILOT_VERSION` / `CLUE_ARV2_RECIPE_PILOT_WORKSPACES`),
the model block's `RESEARCH_EXTRACT_AGENT_MODEL` / `PERSON_RESEARCH_AGENT_MODEL` (R4, R12), and the
four R16 caps (`CLUE_ARV2_V26_JUDGE_RAW_READS`, `CLUE_ARV2_V26_FALLBACK_MODELS`,
`CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS`, `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS`). The contact-research
role is `person_research` (R4); the deferred contact page is 04 §0.5's research-kind continuation
(R11); the judge emits the brief through `submit_brief@1` (R3); the two pool markers and the two
waits are 03's (R5). Test
tiers are 04 §0.1's: *offline* (`make check`), *DB* (`require_claimstore_db`, skips without
`CLUE_DATABASE_URL`), *replay* (this document's harness; skips with a named reason when the pool
root is absent). Prices are the plan's §3 sheet. "Pool" = a frozen evidence universe for one
account and its committee; "fixture" = a machine-readable expectation mined from production (01b).
Paths under `.artifacts/` are gitignored because they hold research about real people; paths under
`tests/arv2/v26/fixtures/` are committed and carry no personal data.

**What is deterministic here and what is not.** Provider responses and extraction are frozen or
recorded, so every pre-judge stage (A0–A3, B, the gap round) replays byte-identically. The judge is
a live Grok turn: its choices vary run to run, which is why the judge-dependent tests (AT-6, AT-9,
AT-5's served-brief half, AT-8's finding half) use recall thresholds derived from 01b's measured
rating noise (±15 % on a single run's A count, 01b §9) rather than exact lists, and why RC-2 must
pass **twice** (04 §7.3). A cassette mode exists for the judge so a failing run can be re-examined
without a new model bill, never to make a pass cheaper.

---

## §1 The frozen evidence pool

### 1.1 What a pool is, concretely

Everything one account research job and its five contact jobs bought, indexed, and derived — the
rows and blobs below, for one `(workspace, run, account)` and the six job ids. Nothing else is
evidence: the agent's own files (`work/`, `outputs/`), the model-input artifacts and the dossier are
*outputs*, not the universe, and are kept beside the pool only as the production reference.

| Layer | Rows / bytes (02 citation) | Why the replay needs it |
|---|---|---|
| Paid-call identity | `arv2_research_operation` (02 §3.3): `operation_id = uuid5("arv2-operation:v1:<ws>:<job>:<kind>:<sha(request)>")`, `kind`, `request_sha256`, `state`, `artifact_key` → the raw response | the `operate` replay path (`won=False` → `operations.body`, 03a §5.2) serves a stored body only when the same `(job, kind, request)` exists — the pool is what makes that true on a throwaway database |
| Money and timing | `provider_call_ledger` rows `phase='result'` for the six jobs (02 §3.6): `provider, operation, label, latency_ms, cost_usd, credits, http_status, response_artifact_key` | the cost baseline per account (01 §2) and the "provider time vs evidence-call time" split (01 §1.3) |
| Raw responses | `artifact` rows + blobs at `{ws}/{sha}` cited by the ledger's `response_artifact_key` (02 §3.7) | the bytes `index_acquisition` re-indexes on replay (`recover_acquisitions`, 02 §2.3) — the Exa search/contents/deep-reasoning bodies, AI Ark pages, ATS boards |
| Evidence index | `arv2_evidence_manifest` (revision counter per account) + `arv2_evidence_source` rows (02 §3.5): `source_id`, `kind ∈ web_snapshot/provider_record/research_report/transcript/acquisition_gap`, `revision` → `/evidence/NNNN-slug.json`, `source_url`, `origin_locator`, `artifact_key` → the normalised text | what B extracts over (03 §3.5.1), what the pool-read rule looks up by URL (03 §3.3.4), and what the nothing-lost tuples cite (01b fixtures cite `/evidence/NNNN-slug.json` paths) |
| AI Ark records | the `provider_record` sources with `content_kind=ai_ark_enrichment` (prose dropped, 02 §2.3) + `provider_identity` / `provider_artifact_subject` rows (02 §3.15) + the `account.committee_selection` claims and the person jobs' `input_refs.candidate_ref` | the frozen committee: who the five contacts are, their titles/employers/LinkedIn slugs (the A2 template variables and the subject anchor, 03 §3.3.3, §3.5.3) |
| Deep reports | `research_report` sources (one per `research_deep` operation; 52–60k chars in production, 02 §2.3) + the per-result `provider_record`/`web_snapshot` rows of the same operation | the single largest A-class producer (01b T7: 199 A findings) — a pool without full-length reports cannot carry AT-1 or AT-6 |
| Seller context | the pinned `arv2_context_document` bodies for the project's context (02 §3.4): ICP with `persona_map`, the `audience-persona` documents, product catalog / company overview | A0.0 compiles role titles from these (03 §3.2); the judge's L7 context block and the page writer's seller brief read them; without them the run is not the production run |
| v26 derivations (r27 only, produced by the replay itself) | the pool artifacts `application/vnd.clue.research-candidates+json` retained under the **two markers** of R5 — the first-pool marker `research_candidates_first:<job>:<plan_sha>` (after A1/A2 + B; what the contact judge waits for) and the final-pool marker `research_candidates:<job>:<plan_sha>` (after A3 + the gap round; what the account judge waits for on every child) — 03 §3.5.5's names, which 04 W3-21 uses; plus the `artifact_derivation` rows from every source | the judge's input; what AT-1/AT-2/AT-8 read; the harness's stage model (§2.3) |

A pool is therefore **two things**: a *request set* (every operation kind + request body the
production run issued, with its stored response) and an *evidence universe* (every text the run
could have read). The second is what the v26 acquisition stage is pointed at; the first is what
keeps replay semantics exact.

### 1.2 Three ways to capture it, and the one this document chooses

| Route | Bodies complete? | Deep reports | Search-result texts | AI Ark records | Evidence revisions (`/evidence/NNNN`) | Costs / timings | Cost to build | Needs |
|---|---|---|---|---|---|---|---|---|
| **A — production DB + storage** (04 §1 "preferred", plan D6) | yes, byte-exact as the agent saw them | full | full | full, with provider subject ids | the production numbering — the 01b fixture paths resolve directly | the real ledger | $0 | the read-only production user (not granted as of 2026-10-07: `_memory/2026-10-07-arv2-v26-program.md`) |
| **B — Langfuse I/O only** (what 01/01b did) | **no**: every string masked at 8,000 chars (`clue_obs/langfuse.py:74`; 04 §1), `read_file` outputs reduced to a 300-char head in the corpus | the 8k head of a 52–60k report | **none** (Exa search results store no text, 01b §5) | people records for the 33 v2-pulled traces | absent | model cost and Langfuse latency only | $0 | nothing |
| **C — re-issue the recorded request set once** through the real `ToolRuntime.operate` under a replay workspace (04 §1 "fallback") | yes, as of the freeze date (the web moved since October; a page may have changed or vanished) | full, at the D8-pinned surface | full | full (re-lookup by LinkedIn URL / export by record id) | the replay's own numbering; the fixtures are joined by **URL + source kind**, never by revision number | the replay's ledger | ≈ $0.6 per account (364 searches × $0.009 + 196 fetches × $0.004 + 47 deep ≈ $0 + ≈ 52 AI Ark credits over all seven) | Exa + AI Ark keys; the request set from Langfuse (`.artifacts/arv2-research-runs-20261007/fixtures/scripts/ops.json`: 753 operations with their arguments) |

**Decision: route C is the pool, route B is the request set and the fixtures, route A is what the
production database would add.** B alone cannot carry a replay: 102 of the 503 stored texts are cut
at the 8k mask, the deep reports are headless, and search results have no text, so AT-1 (candidate
recall over spans), AT-7 (quote verification against the source text) and B extraction itself have
nothing to run on. C is the harness in `--providers record` mode (§2.2) — the same code path the
replay runs, with live transports and every response written to the pool — so the freeze and the
replay are one mechanism, not two. What A would add, and is recorded in the manifest as absent:
(1) the **exact** bodies of the day (C's bodies are the web as of the freeze date; the gate treats a
tuple whose cited URL no longer resolves as *unreachable*, not *lost* — §3 "universe-adjusted
recall"); (2) the production evidence revision numbers, which would let the 01b tuples join by
path instead of by URL + kind; (3) the production ledger's provider timings for the per-account
baseline (01 T2.1 is model + page-writer cost from Langfuse; the provider spend per account is 01 §7
item 1's open query); (4) the **pinned seller context documents** — the one input C cannot
re-issue (see 1.5 and §2.6).

### 1.3 Pool layout on disk

Root `ARV2_REPLAY_ROOT` (default `.artifacts/arv2-v26-replay/`, gitignored; 04 §1 names the same
root). One directory per account domain:

```
.artifacts/arv2-v26-replay/
  fixtures/                      ← copied from .artifacts/arv2-research-runs-20261007/fixtures/ (01b)
    rule_table.json  chains/<account>.json  nothing_lost/<account>.json  quote_fidelity.json
    quote_subset.json  ratings.json  findings.json  namesakes/<account>.json  summary.json
  <account>/
    manifest.json                ← {account, prod: {workspace_id, run_id, job_ids[6], traces[6], day,
                                    profile}, method: "reissue"|"db", as_of: "2026-10-06",
                                    captured_at, pool_sha256, counts{operations, sources, chars},
                                    committee: [{name, title, persona, linkedin_url, provider_subject_id}],
                                    missing: [...], context_source: "export"|"db"|"none"}
    committee.json               ← the five AI Ark records (enrichment_only) exactly as production kept them
    context/                     ← icp.md, personas/*.md, product-catalog.md, company-overview.md (bodies verbatim)
    operations/<kind>/<request_sha256>.json
                                 ← {kind, provider, request, wire: {method, url, body_sha256},
                                    response: {status, headers, body}, cost: {usd, credits},
                                    latency_ms, recorded_at, origin: "prod-request"|"v26-plan"|"judge"}
    sources/<source_id>.json     ← the arv2_evidence_source row + the normalised text (what B reads)
    index/urls.json              ← url → [operation sha, source ids]  (the pool-read rule's table)
    index/bm25/                  ← a local lexical index over sources/ (titles, urls, text) for offline searches
    cassettes/transport.jsonl    ← body_sha256 → response for OpenRouter leaf calls (extract, compile, pages)
    cassettes/judge.jsonl        ← sha(messages+tools) → response for the judge (optional, §2.2)
    prod/                        ← references into the 01 corpus: sequences, findings, the dossier bodies
```

`pool_sha256` = sha256 over the sorted `operations/**` and `sources/**` file digests; the committed
manifest test (`tests/arv2/v26/test_replay_manifest.py`, 04 §1) verifies it. A pool is **append-only
within a label**: `record` mode adds files, never rewrites one, so a second freeze of the same
account is diffable.

### 1.4 Pointing the v26 acquisition stage at the pool — the seam

Every paid call in the lane, pre-step and judge alike, goes `ToolRuntime.operate` → `call_provider`
→ `_perform_hop` → `transport = self._transport_factory()` → `ProviderCaller(transport=…)` →
`Transport.send(HttpRequest)` (`account_research_tools.py:698-728`, `:496-575`; `clue_spend/transport.py`).
The provider clients build a byte-stable request (`json_request` sorts keys, `transport.py`), and
`operate` keys the operation on `fingerprint(request)` over the tool-level request mapping
(`research_operations.py:27-30`). **The stub is a `Transport`:**

```python
class PoolTransport:                       # platform/api/clue_api/arv2/replay/pool_transport.py (new, L)
    """Serve recorded provider responses; never a network call unless the policy says so."""
    def __init__(self, pool: PoolReader, *, on_miss: Literal["refuse", "record", "live"], live: Transport): ...
    def send(self, request: HttpRequest) -> HttpResponse:
        key = (request.method, host_path(request.url), sha256(request.body or b""))
        hit = self.pool.exact(key)                       # 1. byte-exact: the request set
        if hit is None:
            hit = self.pool.semantic(request)            # 2. per-provider semantic key (table below)
        if hit is not None:
            return hit
        if self.on_miss == "refuse":
            raise TransportFailure("pool_miss:" + describe(request))   # a failed operation, never a purchase
        response = self.live.send(request)               # record / live
        if self.on_miss == "record":
            self.pool.append(request, response)
        return response
```

| Provider · endpoint (as the wire sees it) | Exact key | Semantic fallback (offline mode) | Why the fallback is legitimate |
|---|---|---|---|
| Exa `POST /contents` (`fetch_page`) | body sha | `urls[0]` → the pooled page for that URL (`index/urls.json`), any `maxCharacters` | a page is a page; this is the pool-read rule (03 §3.3.4) applied one layer down |
| Exa `POST /search` `type=auto` (`search_web`, every template and every judge query) | body sha | the top-`numResults` hits of the local index over `sources/` for `query` (+ `includeDomains`/`excludeDomains`/`startPublishedDate` applied as filters on `source_url`/`published_at`), rendered in Exa's response shape with the pooled `text`/`highlights` | the universe is everything production found for this account; a follow-up that production answered ("Jen Grant" → her profile) is answerable from the pool, one that production never found is *unreachable* and excluded from the denominator (§3) — the offline mode measures **what v26 does with the same evidence**, which is exactly AT-6/AT-9's question |
| Exa `POST /search` `type=deep-reasoning` (`research_deep`) | body sha | the pooled deep response for `(subject, kind)` — one per subject per family (`origin: prod-request`), regardless of charter | the v26 charter differs from v25's; in `record` mode the v26 charter's own report is frozen once and becomes the exact hit for every later run |
| AI Ark `GET /v1/companies?domain=` (`company_lock`) | body/url sha | by `domain` | deterministic lookup |
| AI Ark `POST /v1/people` (`people_roles`, A0) | body sha | `committee.json`'s five records, filtered by the request's `seniority`/`function` when any matches, else all five | with `committee_cap=5` and five records, `committee_rank` (03 §3.2) nominates **exactly the frozen five** — the contact fixtures stay keyed by the same names; in `live` mode the committee may differ and the gate reports `committee_overlap` (§4) |
| AI Ark `/v1/people/export/single` (`enrich_contact`) and `people_by_name` (`lookup_person`) | body sha | by record id / by LinkedIn URL | deterministic |
| ATS boards (`read_ats_board`) | url sha | by host | free, deterministic |
| OpenRouter `chat/completions` from inside a hop (the extractor, the A0.0 compile — 03a §8b: `runtime.call_provider("extract", hop)`) | body sha (`cassettes/transport.jsonl`) | **none** — a miss is `refuse` or live by policy (`--model-leaf cassette|live`) | the extractor request is byte-identical given the same sources, chunking and prompt version (03 §3.5.2), so a cassette hit *is* a replay; a prompt change is a miss, by design |
| media hosts (`read_media`, `discover_media`) | — | **refused always** in v26.0 (03 §7) | media is off; the gate's zero-list counts any media request as a failure |

The judge's model calls do not pass through the transport — they go `GovernedAgentChatModel` →
`OpenRouterAgentModelProvider` (`agent_model_wiring.py:13`). The handler already takes
`model_provider: AgentModelProvider` (`account_research_driver.py:2410-2420`; protocol
`clue_agents/ports.py:197`), so the harness wraps the live provider in a `CassetteModelProvider`
(§2.2) without an A-owned change. The page writer builds its own `HttpxTransport()` inside
`provider_model_call` (`page_writer_runtime.py:109-176`) and is reached only through the
`page_writer: PageWriterModels | None` constructor seam — §2.6 asks for a transport parameter there.

**The one A-owned seam change.** `Arv2AccountResearchWorkHandler.__init__` has no transport
parameter and `_tool_runtime` (`account_research_driver.py:1257-1271`) builds `ToolRuntime` with the
default `HttpxTransport` factory. The harness needs `transport_factory: Callable[[], Transport] =
HttpxTransport` on the handler and on `build_arv2_account_research_handler`, threaded into
`_tool_runtime(... transport_factory=self._transport_factory)`. Nothing else in the lane changes:
`operate`, `_drain`, `index_acquisition`, the ledger and the evidence index all run for real on the
throwaway database, which is what makes the replay's own `arv2_research_operation` rows the exact
replay table for a second run of the same pool (03a §5.2 layer 1 — `won=False` serves the stored
body before the transport is ever asked).

### 1.5 The seven pools as the corpus can seed them today

Counted from `.artifacts/arv2-research-runs-20261007/fixtures/scripts/ops.json` (753 operations,
42 runs) and `findings.json`; "stored text" = an operation output the Langfuse pull kept inline
(fetched pages, deep-report heads, ATS postings, people records, media descriptions — never search
results). The request set is complete for every run (tool inputs are whole in Langfuse); the texts
are what route B cannot give and route C re-issues.

| Account (day, profile) | Ops (completed) | Ops with stored text · chars | Contacts (5) | What is missing before the freeze | Re-issue note |
|---|---|---|---|---|---|
| dialpad.com (10-06, v25) | 119 (116) | 64 · 169k | Flynn, Wall, Coupe, Edelstein, Rolfing | **Emily Wall's run has no stored outputs** (v1 pull: inputs only); 53 searches without text; 6 deep reports at the 8k head; 3 `read_media` (off in v26) | pilot account; re-issue all 116 non-media requests |
| loopio.com (10-06, v25) | 106 (102) | 103 · 241k | Mondesire, Oke, Pace, Lo, Hayter | searches without text; deep heads; 4 `read_media` | pilot account |
| firstfleetinc.com (10-04, v25) | 110 (95) | 107 · 194k | Henderson, Laney, Cole, Wilson, Getts | 13 `read_media` attempts (0 transcripts), 3 `lookup_person` subject-lock refusals (01 §3.8) — refused requests are **not** re-issued | — |
| jrayl.com (10-04, v25) | 103 (92) | 92 · 209k | Shippy, Yoder, Parks, Richards, Roberts | 5 exact repeats (01b T1) collapse to one pooled request each | — |
| nyc.gov (10-04, v25) | 88 (84) | 86 · 149k | Campion, Kushner, Hong, Levitt, McCormick-Sharf | one `read_media` | — |
| mckeefoods.com (10-03, v24) | 116 (107) | 49 · 110k | Lang, McKee, Lyons, Gladden, Vann | the account run shares one trace with Mortenson (split by timestamps, 01b §1.1); **Chris McKee and Don Gladden have no stored outputs**; v24 skills/prompts (the request set is still valid) | — |
| mortenson.com (10-03, v24) | 111 (103) | **2 · 16k** | Ritter, Locken, Bachhuber, McGrory, Burkholder | **four contacts have no stored outputs** (Ritter, Burkholder, Bachhuber, McGrory); 8 refused `research_deep` arguments before the one accepted report; the family is a request set only | the freeze supplies everything |

Across the seven: 102 of 503 stored texts hit the 8k mask (so even the "with text" column is
partial for every deep report and every long page); 54 refused operations and 14 exact repeats are
dropped from the request set; `discover_media`/`read_media` (47 requests) are never re-issued. The
**seller context documents** of the three workspaces (W1 Garner Health: McKee, Mortenson, NYC; W2:
FirstFleet, J. Rayl; W3 Clue: Dialpad, Loopio — 01 §1.1) are in no corpus file (the agent's
`/research/context.json` read is 5,021 chars in the trace, reduced to a 300-char head in the pull);
they must be exported from the workspaces (§2.6 item 3). Until a workspace's context is exported,
its pool runs with `context_source: "none"` and only the mechanical tests (AT-1, AT-3, AT-7) are
valid on it — the judge and the compile need the real ICP.

**Freeze order.** Dialpad and Loopio first (the plan's gate pair; both 10-06, v25, complete
request sets, W3 context exportable by the founder), then nyc.gov / FirstFleet / J. Rayl (10-04,
v25), then the two 10-03 families (v24; the request set is agent-written and the contacts are mostly
unrecorded — they add breadth to AT-9's rule-table coverage and nothing to RC-2).

---

## §2 The harness

### 2.1 Scripts and modules

| Path | Owner | Role |
|---|---|---|
| `scripts/arv2_v26_freeze_pool.py` (named in 03 §3.5.5) | L | builds a pool: reads the request set from the corpus (`ops.json` + `sequences/`), seeds the replay workspace, runs the harness in `--providers record` for the production request set **and** for the v26 plan (A0–A3 + gap, so the r27 templates are frozen too), writes `manifest.json`, `index/`, `pool_sha256` |
| `scripts/arv2_v26_replay.py` | L | runs **one** account + its contacts on a pool and writes one `result.json` (§2.4) |
| `scripts/arv2_v26_replay_gate.py` (named in 03 §8.4) | L | reads `result.json`(s) + fixtures → AT-1…AT-9, the RC numbers, the zero-lists → `gate.json` + a one-page Markdown verdict; exit code 0/1 |
| `scripts/arv2_v26_mine_runs.py` (04 §1) | L | W0: the fixtures (already produced by 01b's scripts; this script is their committed, re-runnable form and adds `namesakes/<account>.json` for AT-5) |
| `platform/api/clue_api/arv2/replay/{pool_transport.py, pool_reader.py, cassette.py, seed.py, collect.py, match.py, rater.py}` | L | the stub transport (§1.4), pool I/O, the model cassette provider, workspace seeding, result collection, the matching rules of §3, the depth rater of §5 |
| `tests/arv2/v26/…` | L | the test files of §3 (replay tier) and `test_replay_manifest.py` |
| `Makefile`: `arv2-replay`, `arv2-freeze`, `arv2-gate` | L | the three commands below |

The harness formalises what the 2026-09-28 evaluation did by hand (isolated databases, local
workers, Langfuse per run, the failure classes kept separate — `docs/benchmarks/research-model-evaluation-20260928/REPORT.md`)
and what `scripts/trial_page_writer.py` does for pages (saved research in, the production writer,
an in-memory ledger): the same discipline, with the provider universe frozen and the verdict scripted.

### 2.2 Invocation and modes

```
make arv2-freeze ACCOUNT=dialpad.com LABEL=freeze-20261010            # route C, ≈ $0.6 providers
make arv2-replay ACCOUNT=dialpad.com RECIPE=27 LABEL=rc2-run1 \
     PROVIDERS=offline MODEL=live PAGES=live                           # one account + 5 contacts
make arv2-gate   LABELS=rc2-run1,rc2-run2 CHECKPOINT=RC-2              # pass/fail
```

`scripts/arv2_v26_replay.py` flags:

| Flag | Values (default) | Meaning |
|---|---|---|
| `--account` | domain | the pool directory |
| `--recipe` | `26` \| `27` | which mint runs (sets `CLUE_ARV2_RECIPE_PILOT_VERSION` + the replay workspace in `…_PILOT_WORKSPACES`, 04 §2.5) |
| `--providers` | `offline` (default) \| `record` \| `live` | `PoolTransport` policy: offline = exact + semantic, miss refuses; record = exact, miss goes live and is appended; live = always the network (RC timing runs) |
| `--model` | `live` (default) \| `cassette` | the judge: live Grok through the gateway, or `CassetteModelProvider` (hit on `sha(messages + tool schemas)`, miss refuses) |
| `--model-leaf` | `cassette` (default) \| `live` | extractor / compile / page-writer OpenRouter calls through `cassettes/transport.jsonl` |
| `--pages` | `live` \| `cassette` \| `off` (default `live` for RC, `off` for AT) | `off` passes `page_writer=None`; the account job then lands `needs_review/page_writer_not_composed` (02 §3.2) **after** its import — the gate treats that code as expected in AT mode and as a failure in RC mode |
| `--as-of` | date (the pool's `as_of`) | pins `since` (03 §3.3.1) so the A1/A2 requests are byte-identical to the frozen ones — a new setting `CLUE_ARV2_V26_AS_OF_DATE` (blank = today; `.env.example` parity) read only by `acquisition_plan.plan` |
| `--committee` | `frozen` (default) \| `live` | frozen = A0's people search is answered from `committee.json` (§1.4); live = whatever AI Ark returns now |
| `--database-url` | `CLUE_DATABASE_URL` | must name a database `clue_arv2_replay_*` (the `quality_load_harness.py:289` guard pattern); the harness runs `alembic upgrade head`, `load_core_pack`, `load_display_recipes` |
| `--storage-root` | `<pool>/../blobs/<label>` | `FsStorage` |
| `--label` | string | the result directory `.artifacts/arv2-v26-replay/results/<account>/<label>/` |
| `--timeout-s` | 2400 | harness wall clock; a job still running at the end is recorded `harness_timeout` |

Mode matrix — what each checkpoint/test runs:

| Use | `--providers` | `--model` | `--model-leaf` | `--pages` | `--committee` | Spend per account+5 |
|---|---|---|---|---|---|---|
| freeze (route C) | record | — (no judge: `--stages acquire` runs A0–A3+gap+B only on r27; on r26 the production request set is re-issued directly through `operate`) | live, recorded | off | frozen | ≈ $0.6 providers + ≈ $0.6 extraction (Flash) |
| AT-1/2/3/7 (mechanical) | offline | — | cassette | off | frozen | $0 |
| AT-4/5/6/8/9 (judge) | offline | live | cassette | off | frozen | ≈ $1.3 (judge only: $0.32 + 5 × $0.19, 03 §5.5) |
| RC-1 (r26) | **live** | live | live | live | live | ≤ $17 target (04 §7.3) |
| RC-2 (r27) | **live** | live | live | live | frozen then live (two runs) | ≈ $3.5 expected, ≤ $9 ceiling (03 §5.5) |
| re-examine a failure | offline | cassette | cassette | cassette | frozen | $0 |

RC runs use live providers because provider latency is part of the target; every RC run is also a
`record` run, so the pool grows with each checkpoint and the AT tests can be re-run offline against
the exact universe the RC run saw.

### 2.3 What the runner does, step by step

1. **Guard and prepare.** Refuse unless the database name starts with `clue_arv2_replay_`; `alembic
   upgrade head`; `load_core_pack`, `load_display_recipes` (as `tests/arv2/quality_load_harness.py:300-304`);
   set `CLUE_LANGFUSE_ENVIRONMENT=replay-<label>` and `CLUE_RELEASE=<git sha>` in the process
   settings so the run's traces are filterable and never mix with production (02 §8.1); record
   `profile_sha256` for the recipe from `arv2_account_profile_sha256` / `arv2_person_profile_sha256`.
2. **Seed the workspace** (`replay/seed.py`): `seed_icp_fixture` generalised to take the pool's
   `context/` documents instead of the built-in Clue ICP (`tests/arv2/icp_fixture.py` seeds a spine,
   a confirmed ICP and its pin; the harness adds the persona and product documents as pinned
   `arv2_context_document` rows); `insert_account_entity` for the account; the replay workspace id
   `ws_replay_<account>_<label>`.
3. **Launch** exactly as production does: `launch_arv2_account_research` with `committee_cap=5`
   (the production value for all seven, 01 T1.1) then `enqueue_launched_jobs` (the
   `scripts/launch_arv2_account_research.py` path, seam 1).
4. **Compose the handler** with the seams: `Arv2AccountResearchWorkHandler(... transport_factory=
   lambda: PoolTransport(...), model_provider=CassetteModelProvider(live) | live, page_writer=…,
   queue=DbWorkQueue())` and the quality sweep (`sweep_quality` every 10 s, 02 §1.6). One handler
   suffices: the deferred contact page is a **research-kind continuation** on this handler (R11 /
   04 §0.5 — `handle()` dispatches on `payload["continuation"] == "contact_page"`), offered by the
   contact's settle when the parent is import-ready and otherwise by the sweep; no
   `arv2_display_page` handler is composed (its Luna writer is never used by a quality subject).
5. **Drive** with `LeasedWorkWorker` over `DbWorkQueue` in-process, `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=6`
   so the account and five contacts run together as the design intends (03 §6.2); the harness
   polls `arv2_research_job`, the `artifact_reference` markers and the page pointers until every
   job is terminal and the account's generation is `reconciled` (02 §3.10) or `--timeout-s`
   elapses. **Stage model (R5, two markers per subject):** `A1`/`A2` + `B` → the first-pool
   marker (`research_candidates_first`); `A3` + gap + `B` → the final-pool marker
   (`research_candidates`); a contact's `wait_account_pool` ends when the account's **first**
   marker exists or `CLUE_ARV2_V26_ACCOUNT_POOL_WAIT_S` (120 s) elapses; the account's
   `wait_pools` ends when every child's **final** marker exists, the child is terminal, or
   `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S` (240 s) elapses; `C_*` starts at the end of its wait. The
   harness timestamps each marker's `artifact_reference` row, so the stage walls exist even
   before the `arv2.v26.*` spans land (§2.6 item 7).
6. **Collect** (`replay/collect.py`, read-only SQL of §4.3 + the pool transport's own log +
   Langfuse ids): write `result.json`; copy the dossier documents and the brief JSON beside it;
   never print customer text to stdout (counts only).

The r26 path is the same loop with no pre-step: the agent issues its own operations, the pool
transport answers them (offline) or records them (live).

### 2.4 The result JSON (one file per run)

```json
{"harness": {"version": 1, "git_sha": "…", "clue_release": "…", "recipe_version": 27,
             "profile_sha256": {"account": "…", "person": "…"},
             "mode": {"providers": "offline", "model": "live", "model_leaf": "cassette", "pages": "off", "committee": "frozen"},
             "pool": {"account": "dialpad.com", "pool_sha256": "…", "as_of": "2026-10-06", "label": "freeze-20261010"},
             "started_at": "…", "finished_at": "…", "harness_timeout": false},
 "run": {"run_id": "…", "workspace_id": "ws_replay_…", "account_job_id": "…",
         "contacts": [{"job_id": "…", "name": "…", "persona": "champion", "in_pool_committee": true}],
         "committee_overlap": 5},
 "stages": {"A0_compile": {"wall_s": 6.1, "usd": 0.007, "calls": 1},
            "A0_committee": {"wall_s": 63.2, "credits": 12.6, "calls": 6},
            "A1": {"wall_s": 61.0, "usd": 0.11, "calls": 20, "replayed": 20, "pool_reads": 3},
            "B_account": {"wall_s": 20.4, "usd": 0.14, "calls": 60, "candidates": 173, "rejected": {"quote_partial": 9, "class_invalid": 4}},
            "A3_account": {"rounds": 2, "ops": 11, "rules_fired": {"person_name_search": 4, "...": 1}},
            "gap_account": {"classes": ["trigger"], "ops": 2},
            "A2": {"<contact_job>": {"wall_s": 61.0, "usd": 0.05, "calls": 15}},
            "B_contact": {"<contact_job>": {"candidates": 120, "rejected": {...}, "anchored": 112, "unanchored": 8}},
            "markers": {"<subject_job>": {"first_pool_at": "…", "final_pool_at": "…"}},
            "wait_account_pool": {"<contact_job>": {"waited_s": 12, "account_first_pool": "present"}},
            "wait_pools": {"waited_s": 48, "present": 5, "absent": 0},
            "C_account": {"wall_s": 160, "usd": 0.32, "rounds": 7, "rounds_max": 20, "operations": 4, "operations_max": 30, "error_rounds": 0, "resubmits": 0, "context_opening": 35800, "context_peak": 47900, "clear_events": 3, "compaction_events": 0},
            "C_contact": {"<contact_job>": {"...": "same shape, rounds_max 12, operations_max 15"}},
            "E_account": {"wall_s": 51, "usd": 0.13, "sections": 10, "repaired": 0, "skipped_unchanged": 0, "failed": []},
            "E_contact": {"<contact_job>": {"wall_s": 40, "usd": 0.06, "sections": 5}},
            "refresh": {"sections_checked": 2, "sections_changed": 1},
            "settle": {"account_status": "completed", "contact_statuses": {"<job>": "completed"}}},
 "time": {"launch_to_committee_s": 63, "nomination_to_first_person_start_s": 4, "launch_to_account_pages_s": 440,
          "launch_to_last_page_s": 455, "evidence_call": {"n": 101, "total_s": 310, "provider_s": 280, "platform_s": 30}},
 "cost": {"total_usd": 3.31, "model_usd": 1.25, "provider_usd": 0.66, "credits": 17.6, "unpriced_calls": 0,
          "cached_input_share": 0.88, "by_job": {"<job>": {"usd": 1.02, "credits": 12.6}},
          "launch_turn_usd": 0.31, "gated_total_usd": 3.31, "turns_per_subject": {"<job>": 1},
          "ceilings": {"modeled_usd": 9.0, "structural_usd": 21.4, "modeled_for_observed_rounds_usd": 4.1}},
 "caps": {"raw_view_reads": 0, "raw_view_read_refusals": 0, "fallback_model_calls": 0,
          "extract_output_tokens_max": 1840, "extract_length_splits": 2, "extract_skipped": 0, "page_attempts_max": 1},
 "settings_in_force": {"CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS": 45000, "CLUE_ARV2_V26_PERSON_CLEAR_TRIGGER_TOKENS": 42000,
                       "CLUE_ARV2_V26_CLEAR_KEEP_RESULTS": 4, "clear_exclude_tools": ["submit_brief", "finalize_turn"],
                       "CLUE_ARV2_V26_JUDGE_RAW_READS": false, "CLUE_ARV2_V26_FALLBACK_MODELS": "",
                       "CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS": 2000, "CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS": 2,
                       "...": "every CLUE_ARV2_V26_* value and the model-block lines"},
 "trace_bytes": {"<subject_job>": 4120000},
 "operations": {"planned": 97, "issued": 108, "replayed": 97, "pool_reads": 11, "duplicate_fetches": 0, "repurchased": 0,
                "refused": {"operation_budget_exhausted": 0, "invalid_acquisition_arguments": 0, "pool_miss": 0},
                "by_kind": {"search_web": 71, "fetch_page": 29, "research_deep": 6, "...": 0},
                "ledger": [{"op": "…", "subject": "…", "kind": "…", "template": "T_leadership", "rule": null, "follows": null,
                            "purpose": null, "query_or_url": "…", "state": "succeeded", "candidates": 11, "stage": "A1"}]},
 "candidates": {"<subject_job>": {"total": 173, "by_class": {"trigger": 31, "...": 0}, "unanchored": 0}},
 "brief": {"<subject_job>": {"items": [ "…the §2.3 finding records as imported, with candidate_ids, over_cap, quote_restored…" ],
                             "served": 44, "over_cap": {"stack": 2}, "restored_quotes": 1, "resubmits": 0, "claim_ids": 44}},
 "pages": {"<subject_job>/overview": {"sections": 6, "written": 6, "repaired": 0, "duration_s": 48}},
 "errors": {"schema_validation": 0, "trap_grep_refused": 0, "trap_search_evidence_unavailable": 0,
            "finalize_refused_unresolved_failures": 0, "finalize_workspace_conflict": 0, "listing_refused": 0,
            "read_refused": 0, "media_operations": 0, "provider_error": 0, "model_call_error": 0, "page_writer_failed": 0,
            "needs_review": [], "harness": []}}
```

`result.json` holds customer research (the brief items) and stays under `.artifacts/`; `gate.json`
holds counts and verdicts only and may be pasted into `_memory/`.

### 2.5 CI and local

- **Local:** `make arv2-replay …` on the developer machine against the lane's local Postgres
  (`make db-up`), reading `.env` for the Exa/AI Ark/OpenRouter keys. Nothing touches production or
  Railway. The replay tier of pytest (`@pytest.mark.replay`, registered in `pyproject.toml`
  `[tool.pytest.ini_options] markers`) reads `ARV2_REPLAY_ROOT` and the newest `results/<account>/<label>/result.json`
  for each account the test names; absent → `pytest.skip("replay pool/result absent: …")` — the
  same posture as the DB tests (`tests/claimstore/conftest.py:57-61`).
- **`make check`** runs the offline tier only (AT-3, AT-4 shape, AT-5 anchor, AT-7 normaliser,
  the manifest test's load-and-validate half). The replay tier is a **separate, manual or nightly
  job** on the lane machine (the pools are customer research and never enter CI storage); its
  output is `gate.json` attached to the `_memory/` entry of the checkpoint (04 §7.4 asks for the
  RC numbers there).
- **Determinism checks the harness runs on itself:** two `offline` + `cassette` runs of the same
  pool must produce byte-identical `candidates`, `operations.ledger` (timings excluded) and brief
  documents — `tests/arv2/v26/test_replay_determinism.py` (replay tier; a diff is a harness bug,
  not a research result).

### 2.6 What the harness needs from Aryan (A-owned) before it can run

1. **`transport_factory` on the handler** (§1.4): a constructor parameter on
   `Arv2AccountResearchWorkHandler` and `build_arv2_account_research_handler`, threaded into
   `_tool_runtime`. One parameter, one line. Without it the harness must monkey-patch
   `account_research_tools.HttpxTransport`, which the harness will do for the first dry-run and
   which must not be the lasting answer.
2. **A transport/caller seam on the page writer** (`page_writer_runtime.provider_model_call`,
   `:109-176`, builds `HttpxTransport()` inline) so `--pages cassette` is possible; until then
   `--pages live|off` only.
3. **The pinned context documents of the three workspaces** — an export of `arv2_context_document`
   bodies for the three production contexts (ICP, personas, product catalog, company overview;
   02 §3.4) into each pool's `context/`. This is the one input the corpus does not hold and the
   harness cannot re-issue. Either the read-only production query (plan D6) or an app-side export
   by the founder for W3 (Dialpad/Loopio — the gate pair) first.
4. **P5** (`CLUE_ARV2_RECIPE_VERSION` / `_PILOT_VERSION` / `_PILOT_WORKSPACES`, 04 §2.5) landed, so
   the replay workspace can be pinned to r26 or r27 without touching `CURRENT_RECIPE_VERSION`.
5. **The r27 pre-step exposed to the harness** as it is to the driver: `ResearchUnitRuntime.run`
   runs A0–B between `bindings` and the task artifact (03a §8a); the harness calls nothing new —
   but `acquisition_plan.plan` must read `CLUE_ARV2_V26_AS_OF_DATE` (item above; L can add it
   to the new module, A must accept the `.env.example` line).
6. **Settings parity lines** the harness sets per run: `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED=true`,
   `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=6`, `CLUE_ARV2_AI_ARK_MIN_GAP_S` (10.5 live; **0 in
   offline mode** — the pool answers instantly and the pacing lock would add 63 s of nothing),
   `RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` (D4, R12), `RESEARCH_NARRATIVE_AGENT_MODEL`,
   `PERSON_RESEARCH_AGENT_MODEL` / `_EFFORT` (R4; the `person_research` role), the clearing trio
   at 03 §5.3's values (R6: `CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS=45000`,
   `CLUE_ARV2_V26_PERSON_CLEAR_TRIGGER_TOKENS=42000`, `CLUE_ARV2_V26_CLEAR_KEEP_RESULTS=4`; the
   exclude list is `submit_brief`, `finalize_turn` only — `acquire@2` receipts are cleared; the
   candidates file is never cleared), the context caps `CLUE_ARV2_V26_ACCOUNT_CONTEXT_CAP_TOKENS=60000`
   / `…_PERSON_…=56000`, the budgets `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS=20` / `…_PERSON_…=12`,
   `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS=30` / `…_PERSON_…=15`, the four R16 caps
   (`CLUE_ARV2_V26_JUDGE_RAW_READS=false`, `CLUE_ARV2_V26_FALLBACK_MODELS=` empty,
   `CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS=2000`, `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS=2`),
   `CLUE_LANGFUSE_ENVIRONMENT`, `CLUE_RELEASE`. The harness records every `CLUE_ARV2_V26_*` value
   in `result.json.settings_in_force` and the gate **refuses to grade** a run whose clearing,
   budget or cap values differ from 03 §10 (a run under other values is a diagnostic, not a
   checkpoint). All exist or are introduced by their items; the harness only needs them to be
   *readable from the process environment* (they are).
7. **The `arv2.v26.*` spans and the `settle` attributes** (03 §8.1) before RC-2: the `time.*` and
   `stages.*.wall_s` fields are read from them; until they land, the harness derives stage times
   from the markers' `artifact_reference` creation order and `provider_call_ledger.recorded_at`
   (good to ±5 s), and says so in `result.json.harness.timing_source`.
8. **A fixture-loading helper for the DB tests** (`tests/arv2/v26/conftest.py::pool(account)`): loads
   `sources/*.json` into a migrated test database as `arv2_evidence_source` rows + artifacts for
   one job, so `test_prestep_db.py` (AT-2, AT-8) runs over real pooled sources rather than
   synthetic ones. L writes it; A reviews the write path (it must use `publish_sources`, never a
   second insert path — 02 §3.5 "only trusted acquisition code creates sources").

---

## §3 Acceptance tests AT-1…AT-9, executable

Common rules, implemented once in `arv2/replay/match.py` and unit-tested in
`tests/arv2/v26/test_match_rules.py` (offline):

- **Normalisation** is `arv2/text.py::normalize_for_match` (NFKC, straight quotes, collapsed
  whitespace, case-fold, non-alphanumerics blanked) **plus** the two 01b §5 additions as a wrapper
  `normalize_v26`: literal escape sequences (`\n`, `\t`) collapsed to a space before NFKC, and
  boundary punctuation stripped. Digits are never folded.
- **Content tokens** of a key phrase = its normalised tokens minus a fixed stoplist
  (`tests/arv2/v26/fixtures/stoplist.txt`: articles, prepositions, auxiliaries, the subject's own
  name tokens and employer tokens — so "Dialpad" never matches by itself).
- **Universe-adjusted denominators.** A fixture tuple or chain counts only if its cited evidence is
  *reachable* in the pool: for a tuple, ≥ 1 of its `source_kinds` has a pooled source for the
  record it cited (joined by URL + kind; for `research_deep`-produced records, the pooled deep
  response for the same subject); for a chain, its `source_ops` are in the pool or it is
  `inferred` (`source_ops=[]`). Unreachable items are reported under `unreachable[]` and are never
  silently dropped: the gate fails if `unreachable` exceeds 15 % of a file (that is a bad freeze,
  not a bad run).
- **Served** = an imported brief item with `over_cap=false`, `wrong_entity=false`, and (contacts)
  `outreach_safe=true` or class ≠ `hook`.
- **Class map** fixture → brief: account `watch_outs→watch_out`, `firmographics→firmographic`
  (never a research finding in v26 — firmographic tuples are matched against the registered claims
  instead); contact `hooks→hook`; all others identical.

| AT | Fixture | Exact assertion | Threshold | Test file (tier) | On failure: item to revisit → pre-decided fallback |
|---|---|---|---|---|---|
| **AT-1 candidate recall** | `fixtures/quote_subset.json` (488 spans whose cited record maps to exactly one operation that has text; 01b §5) joined to the pool by URL + kind; plus every A-class finding's quote in `fixtures/findings.json` whose source is reachable | for each reachable span `s`: ∃ candidate `c` in the subject's **final pool** (the `research_candidates:<job>:<plan_sha>` marker, R5) with `normalize_v26(s) ⊆ normalize_v26(c.evidence.quote)` **or** `⊆ normalize_v26(c.finding)` **or** (typed branch) `c.evidence.raw` normalises to a slice of `s` containing the span's digits/date | recall ≥ **0.95** over reachable spans per account; and ≥ 0.95 over the A-class subset | `tests/arv2/v26/test_extract_recall.py` (replay, mechanical: `--providers offline --model-leaf cassette`, no judge) | **W3-23.** Read `stages.B_*.rejected`: `quote_partial` dominant → extractor prompt v2 asks for the shortest exact span, never a paraphrase; `class_invalid` → the class table in the prompt lacks a class the span belongs to (add it or accept); span absent from every candidate → first read `caps.extract_length_splits` (a call that hit `CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS` = 2000, R16c, is split in half and re-run by 03 §3.5.4 — never retried unchanged and never raised past 2000), then `_EXTRACT_BATCH_SOURCES` 4→2 (more room per source under the cap); still < 0.95 → `CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT` stays true and the D9 text cap is raised 4000→6000 (cost +$0.03/contact). The freeze records **both** D9 request shapes (production 20 × 10k and v26 12 × 4k) and AT-1 runs on both once, as does the one Luna-vs-Flash comparison (review B §3 rows 1 and 3) — bounded comparisons, never a loop |
| **AT-2 minimums fire the gap round** | `fixtures/summary.json` minimums (03 §2.1 C2 defaults) and the Dialpad pool with every `people_roles` / `provider_record` of the committee removed | (offline) `plan_gap_round(counts, minimums, rules)` returns exactly the `gap_templates` of every class with `count < min`, ≤ `CLUE_ARV2_V26_GAP_OPS_PER_CLASS` each, one round; (DB) on the people-removed pool the committee gap round runs, `stages.gap_account.classes` contains `committee`, and `operations.ledger` holds ≥ 1 `v26_gap:committee` operation; with the full pool no committee gap fires | exact | `tests/arv2/test_followups.py::test_gap_round_fires_below_minimum` (offline); `tests/arv2/test_prestep_db.py::test_committee_gap_round_on_people_removed_pool` (DB, pool-loaded) | **W3-22 / W3-21.** The gap round is code; a failure is a bug, not a tuning question. Fallback: none — fix. If the gap round fires *too often* on the full pools (any class on > 2 of 7 accounts), the minimum is too high for that class → lower the `…_MIN_*` setting (env, no mint) |
| **AT-3 rule table is a pure function; the floor is expressible** | `fixtures/rule_table.json` (01b T6: 29 `(trigger kind → op)` pairs, 18 marked `floor`, collapsing onto the **11 floor pairs of 01b §3** — R9 fixes those 11, verbatim, as the floor) → `tests/arv2/v26/fixtures/rule_table_pairs.json` (committed: the 11 pairs with their T6 row ids, counts and the 03 §3.4 `entity` kind each maps to — person name, vendor, exact phrase, URL, subject-site page, event, prior employer — via `trigger_kind_map.json`; the personal-name examples stay in `.artifacts/`) | (a) `plan_followups(pool, ledger, rules, round)` is deterministic: same inputs → same `PlannedOperation` list, byte-identical requests (`plan_sha` stable); (b) **every one of the 11 floor pairs has a rule in `followups/v1/rules.json` that *fires*** — not merely exists — on a synthetic candidate carrying the matching `entities[{kind, text}]` entry (R9: the extractor emits `entities[]`; rules trigger on `class + entity.kind` and render `{entity.text}` / `{candidate.source.url}` / `{candidate.typed_value}`), producing a request that contains the entity text, and dedupes across rounds and against the ledger; (c) the three 03 §3.4 seed rows that assume a variable (`{vendor}`, `{initiative}`, the event URL) render through the same `entity` variables; (d) per-rule `max_per_trigger`/`max_per_round` ≤ 01b maxima + 1 and the per-round caps `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_ACCOUNT/PERSON` ≥ the 01b per-round maxima (03 Appendix C) | exact; (b) = 11 of 11 | `tests/arv2/test_followups.py` (offline; runs in `make check` because the committed pairs file carries no personal data) | **W3-22 (grammar) before W0's rules file is cut, then W0.** (b) failing = a floor pair the grammar cannot express → a grammar change (code + re-pin), which is exactly why this test and §3.1 run in W0/W1, not at RC-2; (a) failing = non-determinism (a `set` iteration, a clock) → fix |
| **AT-4 synthesis needs ≥ 2 paths; not_found cites the ledger** | `tests/arv2/v26/fixtures/brief_shapes.json` (synthetic records); replay: the nothing-lost tuples with `claim_type ∈ {sequence, not_found}` or `n_sources ≥ 2` in `fixtures/nothing_lost/<account>.json` (e.g. Dialpad F047 "sequence", F050 "CMO departure without named successor") | (offline) `submit_brief` returns `accepted=false` with `errors[].code ∈ {synthesis_needs_two_sources, not_found_operation_unknown, candidate_unresolved}` for the three bad shapes and accepts the good one; `finish_dossier` import keeps `source_paths` = the union of the cited candidates' paths; (replay) every matched multi-source tuple's brief item has `synthesis=true` with ≥ 2 distinct `source.url`s, or is a `not_found` item whose `operation_ids` resolve in `operations.ledger` | exact (offline); 100 % of matched tuples (replay) | `tests/arv2/test_dossier_json.py::test_submit_brief_shape_rules` (offline); `tests/arv2/v26/test_nothing_lost.py::test_multi_source_tuples_import_with_two_paths` (replay) | **W1-2 / W3-24.** A synthesis item with one source means the server default copied a single candidate — fix the derivation (§3.7 step 2 of 03), never relax the rule |
| **AT-5 subject anchor / namesake injection** | `fixtures/namesakes/<account>.json` (new W0 output: for each contact, the source ids/URLs of the records behind its namesake exclusions — 91 findings across 25 contacts, 01b §7 — resolved through `evidence_map.json`) | (offline) `subject_anchor(source_text, record)` is `matched=false` for a namesake page and `matched=true` for the contact's own profile/post; (replay) with the namesake sources present in the contact's pool: 0 served items cite a candidate whose `source.source_id ∈ namesakes`; every candidate from those sources has `subject_anchor.matched=false`; served `hook` items from them = 0; the imported claims from them carry `identity_binding=weak` | exact (0 leaks) | `tests/arv2/test_quality_extract.py::test_anchor_rejects_namesake` (offline); `tests/arv2/v26/test_namesake_injection.py` (replay, judge live) | **W3-23.** A leak means the anchor rule matched the employer name + a title token on a namesake page (same employer, different person): tighten to *slug or (employer and ≥ 2 title tokens)*; if a leak survives, the leaking class is served only with `attribution.kind=self` from an anchored source — a settings-free prompt change to the judge's contract |
| **AT-6 nothing-lost** | `fixtures/nothing_lost/<account>.json`: per account the A-class account findings (`account_findings[]`: id, class, key_phrase, date, source_kinds, n_sources, chain_depth, follow_up, trigger_kinds, claim_type, section) and per contact the same under `contacts[name].findings[]`; counts per 01b T11 (Dialpad 20 + 57, FirstFleet 27 + 44, J. Rayl 19 + 16, Loopio 23 + 52, McKee 23 + 17, Mortenson 27 + 34, NYC 20 + 22) | a tuple `t` is **present** iff ∃ served item `i` of the mapped class with `overlap(content_tokens(t.key_phrase), tokens(i.topic ‖ i.finding ‖ i.quote ‖ i.agent_interpretation)) ≥ 0.6` and, when `t.date` carries a year, that year ∈ `i.time_context ‖ i.finding`; **present_misclassed** when the same overlap holds in another class; **present_over_cap** when it holds on an `over_cap=true` item; **absent** otherwise. Every present item must have `source_paths ≠ []` and `time_context ≠ null` (quote-verified and URL-cited are by construction, 03 §3.7) | account tuples: present ≥ **0.90** per account, and the five Dialpad tuples the plan names (ABM/field hiring; Head of Growth May 2026; CMO vacant since Sept 2025 with no successor; SVP Marketing Feb 2026; the ABM manager's posts) **all** present; contact tuples: present ≥ **0.85** per contact and ≥ 0.90 per account family; `present_misclassed` ≤ 0.10 of tuples; `present_over_cap` counted and reported (it feeds the cap decision, §5) | `tests/arv2/v26/test_nothing_lost.py` (replay; the account tuples also committed as `tests/arv2/v26/fixtures/nothing_lost_accounts.json` — public company facts, 04 §1) | **W3-24 first, then W1-14 / W3-22.** Read the absent list by `follow_up`: `template` tuples absent → the A1/A2 template or the extractor lost them (check AT-1 for the same spans: if the candidate exists, the judge dropped it → prompt; if not, template/extractor); `strict` tuples absent → the chain was not reproduced (AT-9 names which rule); `present_over_cap` concentrated in one class → the caps are **already** 01b §6's values (R10: account Trigger 10, Initiative 5, Pain 5, Motion 5, Stack 8, Committee 10, Watch-outs 4, Not-found 3; contact remit 2, problem-now 5, own-words 8, proud-of 3, hooks 4, career-arc 1, do-not-mention 1), so a class still cutting A-rated items on ≥ 2 accounts is a **founder decision row for 06** (`gate.json.depth.caps_to_raise`), not an env change the gate makes; contact recall < 0.85 on a contact whose production run had no stored outputs (Wall, McKee's two, Mortenson's four) is reported but **not** gating until that family is frozen by route C |
| **AT-7 quote rule** | `fixtures/quote_subset.json` restricted to `producer_kinds == "fetch_page"` (89 spans: 55 verbatim, 2 near-verbatim boundary punctuation, 4 partial, 28 beyond the 8k mask — 01b §5) and the 4 `number/date` near-misses; after the freeze the 28 "beyond window" spans become judgeable against the full page | (offline, `tests/arv2/test_text.py`) **the rule is 01b §5's, as R8 fixes it, implemented as an extension of `substring_verdict` (`arv2/text.py:44`)**: `normalize_v26` folds literal escape sequences (`\n`, `\t`), boundary punctuation, NFKC, dashes, quotes, whitespace, case — and never digits; `quote_rule(span, source)` accepts iff `substring_verdict == "EXACT"` for every elision half (≥ 8 words each when `[…]` is present, one elision max, ≤ 600 chars), rejects `PARTIAL`, and rejects a span whose digits/dates differ from the source slice; the typed branch accepts `{kind, value, raw, source_offset}` iff the offset slice normalises to `raw` and `value` parses from `raw`. (replay) over the 89 + 28-now-judgeable spans against the pooled page text: accepted ⊇ (verbatim ∪ near-boundary-punct), accepted ∩ partial = ∅, accepted ∩ number/date-drift = ∅; the two title-format cases pass through the typed branch | rule recall on human-verbatim spans ≥ **0.98**; false accepts = **0**; the plan's "≥ 41 of 43" Dialpad regression holds as a subset | `tests/arv2/test_text.py` (offline); `tests/arv2/v26/test_quote_fidelity_replay.py` (replay, mechanical) | **W3-23.** A verbatim span rejected = the normaliser is too strict for a real boundary form (add the case to `test_text.py` and the fold); a partial accepted = a bug. The elision rule is never loosened below 8 words |
| **AT-8 the account judge receives the people candidates (R5)** | the Dialpad pool; `fixtures/nothing_lost/dialpad.com.json` F047 ("sequence" trigger: the org-sequence finding) | (DB, `tests/arv2/test_prestep_db.py::test_account_judge_input_carries_people_slice`) **a real assertion on the slice's contents, not a key check**: parse the account job's L7 `agent-turn-input` artifact (and the identical `inputs/candidates-account.json`, same sha); for **each** of the 5 contact jobs the embedded people slice (i) is non-empty and ≤ `CLUE_ARV2_V26_PEOPLE_SLICE_PER_CONTACT` (20), (ii) contains only candidate ids that resolve in that contact's **final** pool (`research_candidates:<contact>:<plan_sha>`), (iii) contains only classes ∈ {remit, problem_now, own_words, proud_of}, (iv) is ordered by class then confidence as 03 §4.3 states, (v) each candidate carries `subject.entity_id` = the contact and `subject_anchor.matched=true`; the ledger trailer carries each contact's `minimums` after its gap round and `absent_pools = []`; and, symmetrically, each contact job's L7 carries the account's **first-pool** slice filtered to `class ∈ {trigger, initiative, pain, stack}`, ≤ `CLUE_ARV2_V26_ACCOUNT_SLICE_MAX` (60), every id resolving in `research_candidates_first:<account>:<plan_sha>`. A second DB case removes one contact's final marker and asserts the account's L7 names it in `absent_pools` after `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S`. (replay) the served account brief contains ≥ 1 `trigger`/`committee` item whose `candidate_ids` include ≥ 1 id from a contact's pool, and the F047 tuple is present with `synthesis=true` | exact (DB); F047 present (replay, folded into AT-6's Dialpad must-list) | `tests/arv2/test_prestep_db.py` (DB, pool-loaded); AT-6 (replay) | **W3-21 / W3-24.** The slice is empty while the final markers exist → the L7 assembly bug; the slice is empty because the wait expired (`wait_pools.absent > 0`) → raise `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S` 240→360 before touching anything else; slice present but no cross-citing item → the judge prompt's committee instruction |
| **AT-9 follow-up chain recall (R9: computed from the ledger's `follows`)** | `fixtures/chains/<account>.json`: `chains[]` with `run, op_kind, trigger_kind, trigger_terms[], query_or_url, source_ops[], verified, depth, A_findings_strict[], A_findings_possible[]` (37 / 24 / 16 / 21 / 37 / 45 / 24 chains; strict-backed 10 / 10 / 1 / 4 / 8 / 21 / 6) | the v26 side is `operations.ledger[]` with, per operation, `template` (A1/A2 id or null), `rule` (A3 rule id or null) and **`follows`** (the operation id — or candidate id — of the lead, set by the A3 executor and by the judge's `acquire@2` call; 03 §3.4, §3.6.3). A chain `c` is **reproduced** iff ∃ `o` for the same subject (or, for an account-run chain whose A findings sit in a contact run, for that contact) such that (1) `o.kind` is in `c.op_kind`'s family (`fetch_page` ≈ `fetch_page` \| `pool_read`; `search_web` ≈ `search_web`; `lookup_person` ≈ `lookup_person`); (2) `o.query_or_url` contains ≥ 1 trigger term of `c` (a URL term by host + path prefix, a name by all its tokens, a phrase/vendor by ≥ 0.6 of its content tokens); and (3) **the lead matches**: either `o.follows` resolves to an operation/candidate whose source URL or record is one of `c.source_ops`' results (when `c.source_ops ≠ []`), or `c` is `inferred` (`source_ops = []`) and `o.follows ≠ null`, or `o.template ≠ null` and the term is in the rendered template (template-covered). `reproduced_by ∈ {template:<id>, rule:<id>, judge}` and the hop depth (`follows` chain length) are recorded per chain; a depth-2 chain needs an `o` whose `follows` is itself a follow-up | **three lines, computed on the RC-2 run's recorded (live-provider) universe, with the offline-mode number reported beside it (review B §2.4):** (i) **floor line, gating, deterministic** — every one of the 11 floor pairs is reproduced by a `rule:` or `template:` operation on ≥ 1 account = **1.0**; (ii) **chain recall, gating** — per account ≥ **0.90** of reachable chains on **both** RC-2 runs, and strict-backed chains ≥ 0.90 over all accounts; (iii) **judge-only share, reported** — recall over chains reproducible only by `judge` ≥ 0.75 warns, never fails (live-judge variance) | `tests/arv2/v26/test_followup_recall.py` (replay, judge live); the floor line also runs offline over the fixtures in §3.1 | **W3-22 then W3-24.** Unreproduced chains grouped by `trigger_kind`: a kind with ≥ 2 misses on ≥ 2 accounts → a rule row in `rules.json` (data, re-pin) — expressible by construction once §3.1 passes; a miss on a template-covered kind → the R10 templates (`T_homepage`, `T_site_pages`, `P_profile`, `P_post_pages`); judge-only misses with `budget_use_ratio(operations) = 1.0` → raise `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` / `…_PERSON_…` (30→40 / 15→20) before any prompt change (plan §8 "depth starved") |
| **Zero-lists** (RC) | — | `errors.schema_validation = 0`, `trap_grep_refused = 0`, `trap_search_evidence_unavailable = 0`, `finalize_refused_* = 0`, `finalize_workspace_conflict = 0`, `media_operations = 0`, `operations.repurchased = 0`, `brief.*.resubmits` ending in `needs_review/brief_invalid` = 0, served `wrong_entity` on class `committee` = 0; `listing_refused ≤ 2` per run on r26 and `= 0` on r27 (the v26 prompts never list); **the four R16 caps (§4.5):** `caps.raw_view_reads = 0` on r27 judges, `caps.fallback_model_calls = 0` on research roles, `caps.extract_output_tokens_max ≤ 2000`, `caps.page_attempts_max ≤ 2`; **extraction completeness:** `caps.extract_skipped = 0` or the job is `needs_review/extract_incomplete` (never a silently thinner pool — review B §3 row 16); extraction ledger rows for `pool_read` operations = 0 (a pool read serves the source operation's stored candidates and never re-runs B) | exact | `tests/arv2/v26/test_zero_lists.py` (replay; reads `result.json.errors`, `operations` and `caps`) | per class: `schema_validation` → W1-2; `trap_*` → W1-3; `finalize_*` → W1-3/W1-5; media → W1-12; repurchase → the pool-read rule (03 §3.3.4) or an unstable request (a date not rounded, a `max_chars` variant); `listing_refused` on r27 → the prompt still mentions `ls`/`glob`; a raw-view read → the r27 profile's readable set still includes the `research`/`evidence` views (03 §3.6.1) or the refusal is not wired; a fallback call → the research model is still built with the global chain; an extraction call over 2000 output tokens → the halving is not wired; page attempts > 2 → the sweep's `WHERE attempts < :max` selection is missing |

The `01b` numbers behind the thresholds: a single run's A count carries ±15 % rating noise
(01b §9), so a per-subject recall threshold above 0.85 would fail honest runs on rating noise alone;
account tuples are rated with the reviewer's own list for Dialpad and agree 100 % by construction on
the three reviewer-rated runs, hence 0.90 there; the five named Dialpad tuples are the plan's own
AT-6 text and are absolute.

### 3.1 The early offline check — floor expressibility (W0/W1, no model, no pool)

AT-9 cannot run before week 5 (it needs the r27 judge). Review B showed that the thing it would
catch — a rule grammar that cannot express a floor pair — is a code change plus a mint if found
then. So the grammar is checked the week the fixtures exist, with no model and no pool:

`scripts/arv2_v26_replay_gate.py --expressibility` and `tests/arv2/v26/test_floor_expressibility.py`
(offline; the floor half runs in `make check` over the committed `rule_table_pairs.json`, the chain
half skips with a named reason when `.artifacts/arv2-v26-replay/fixtures/chains/` is absent). Inputs:
`followups/v1/rules.json` (the W3-22 grammar — until it is cut, the test runs over the **rule shapes
03 §3.4 defines after R9**, i.e. the `entity` trigger kind and its variables, as a committed
`rules_draft.json` that W3-22 replaces), `trigger_kind_map.json`, `fixtures/rule_table.json`,
`fixtures/chains/<account>.json`, the r27 judge's allowed operation set (03 §3.6.1) and its
operation budgets (30 / 15).

For every chain `c` in every account's file, with no model and no provider, the check builds a
synthetic candidate of the chain's subject kind carrying `entities = [{kind: map(c.trigger_kind),
text: t} for t in c.trigger_terms]` (and, for URL/subject-site triggers, `source.url`) and asks:

1. **Expressible by rule** — `plan_followups([candidate], ledger=[], rules, round=1)` renders ≥ 1
   `PlannedOperation` of `c.op_kind`'s family whose request contains ≥ 1 of `c.trigger_terms`
   (the AT-9 term rule). Then `reproducible_by = "rule:<id>"`.
2. **Covered by template** — else, a rendered A1/A2 template for the subject (R10's
   `T_homepage`, `T_site_pages`, `P_profile`, `P_post_pages` included) contains the term →
   `"template:<id>"`.
3. **Reproducible by a budgeted judge operation** — else, `c.op_kind` ∈ the r27 judge's allowed
   operations for that subject kind and the running count of such chains for the subject ≤
   `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` (30) / `…_PERSON_…` (15) → `"judge"` with the count;
   beyond the budget → `"over_budget"`; an operation kind the judge may not issue (e.g.
   `research_deep`, media) → `"inexpressible"`.

**Pass:** every one of the 11 floor pairs is `rule:` on its own synthetic candidate (= 1.0);
every chain in every file is `rule:`, `template:` or `judge` — `over_budget` and `inexpressible`
are **0**; and the report (`gate.json.expressibility`) lists, per account, the counts by
`reproducible_by` and the judge-only share (the ceiling AT-9's line (iii) will be measured
against). **On failure:** `inexpressible` → the grammar lacks a trigger kind or a variable (W3-22
design, before the rules file is pinned); `over_budget` → the judge's operation budget is below
the corpus's own follow-up count for that subject (01b T1: 21 account / 14 contact maxima) and
must be raised before W3-24 is written, not after RC-2. Re-run when `rules.json` is cut (W3-22)
and at every re-pin of it.

---

## §4 The cost/time gate

### 4.1 The two checkpoints and their numbers

Both run on **Dialpad + Loopio** (two accounts launched together, as on 2026-10-06), live
providers, live judge, pages on; every number below is per **account + 5 contacts** unless marked.
The baseline column is 01 T2.1 (model + in-run page-writer cost from Langfuse; rewrites shared
between the two sibling accounts; provider spend is not in Langfuse — the replay's ledger supplies
it for the first time and is recorded as the baseline's missing term).

| Metric | Baseline 2026-10-06 (Dialpad / Loopio) | **RC-1** (r26, end of week 1; 04 §7.3) | **RC-2** (r27, end of week 5; 03 §5.5, plan §3) | Where read |
|---|---|---|---|---|
| Model + pages cost | $24.16 / $25.23 (+ $1.09 shared rewrites) | ≤ **$17** | expected **$3.48** (Flash) / **$2.72** (Luna); ceiling **$9.4** / **$8.1** — the gate fails above the ceiling and warns above 1.5× expected | §4.3 Q1 + Q2 |
| Provider cost | unmeasured (01 §7 item 1) | report | expected $0.66 Exa + $0.18 AI Ark; ceiling $3.16 + $0.25 (351 operations at the search price; ≈ 25 credits — 03 §5.5) (+ $3.00 if D8 unpinned) | Q1 |
| Credits | 9.7 (plan §3) | report | expected 17.6; ceiling ≈ 25 | Q1 |
| Time launch → last page | 56.1 min (side by side) | ≤ **40 min** | **≤ 10 min** (plan §3); design 7.3 min single, 8.5 min two accounts (03 §5.6); the gate fails > 10 min and warns > 8.5 | Q4 |
| Time launch → account pages | 30.4 / 29.0 min (account run) | report | ≤ 7.5 min | Q4 |
| Nomination → first person start | 8.5 / 7.6 min | ≤ **30 s** | ≤ 30 s (A0 writes the contact job rows at its end; the driver's 10 s sweep offers them, 03 §3.2 / 04 W3-21) | Q5 |
| Rounds per subject | account 59 / 56; contacts 39–59 | report (allowance 350) | account ≤ 20 (expected 7), contact ≤ 12 (expected 5); `budget_use_ratio(rounds)` < 1.0 on every subject | Q2, Q6 |
| Error rounds (any tool errored) | 159 of 1,956 corpus-wide (01 T3.7) | **0** in the T3.1 classes `schema_validation`, `trap_*`, `finalize_refused_unresolved_failures`, media; `listing_refused ≤ 2`/run | **0** everywhere; `listing_refused = 0` | Q7 |
| Evidence-call time vs provider time | 57 s per call platform overhead (plan §3); 01 §1.3 per day | after W2: evidence call ≈ provider + ≤ 8 s (04 §7.3; second RC-1 run) | `platform_s / n ≤ 8 s`; `drain_ms_sum` ≤ 10 % of `provider_ms_sum` | Q8 |
| Cached input share | 77–80 % (01 T2.4) | ≥ **85 %** | ≥ 85 % (the pool rides the cached prefix, 03 §5.1) | Q2 |
| Rewrites per account | 6 (shared) | ≤ **1** | 0 rewrites; ≤ 1 conditional refresh with ≤ 2 sections changed | Q9 |
| Context peak | 203k / 185k final | report | account ≤ 60k, contact ≤ 56k; `compaction_events = 0` | Q6 |
| Committee overlap with the frozen five (live committee) | — | — | ≥ 4 of 5 on each account, reported | `run.committee_overlap` |
| Pages | 1 writer failure (Dialpad) | 0 failures | 0 failures; every section written once; `skipped_unchanged` on the refresh | Q9 |
| Launch turn (Head of ABM) | $0.28–0.78 (01 §2.1) | report | reported as `cost.launch_turn_usd`, **excluded from the gated total** (out of scope by ruling; review B §1.2 row 21) | Langfuse `head-of-abm.turn` |
| Modeled vs structural ceiling (R16) | — | — | the gate prints **both** per account: the modeled ceiling ($9.4 / $8.1, 03 §5.5) that it enforces, and the structural ceiling from settings alone (§4.2; ≈ $22.7–25.8 Flash / $17.9–21.0 Luna after R16's four caps — 03 §5.5 holds the authoritative recomputation); realised > 0.5 × structural warns | §4.2 |
| R16 caps | — | report | `caps.raw_view_reads = 0`; `caps.fallback_model_calls = 0`; `caps.extract_output_tokens_max ≤ 2000`; `caps.page_attempts_max ≤ 2` | §4.5, Q10 |
| Trace bytes per job (review A M9: the 100 MB Langfuse trace cap) | the 100.16 MB 422 of 2026-10-03 (pre-PR #90) | ≤ **25 MB** per job trace (warn), 50 MB fails | same | Langfuse v2 observations: Σ input + output payload bytes per trace |
| `v26_stage` progress (review A M7) | — | — | `input_refs.v26_stage` observed at every stage value in order (compiling → committee → acquiring → extracting → following_up → gap → waiting_pools → judging → writing → settled); the progress card never reads 0.0 through the pre-step | Q3, polled |

Per-account expected cost is the same for all seven (the pipeline is deterministic by
construction, plan §3); the ceiling differs only through the committee size (five for every pool)
and D8. The gate therefore reads one target table and checks each account against it; the
baseline differs per account and is reported beside it (01 T2.1: McKee $31.58 / 176 min, Mortenson
$25.30 / 142 min, NYC $16.23 / 39 min, FirstFleet $18.48 / 50 min, J. Rayl $20.96 / 50 min, Loopio
$25.23 / 56 min, Dialpad $24.16 / 56 min).

### 4.2 The cost formula the gate applies (03 §5.5, verbatim)

```
cost(role) = p_n · [O + (R−1)·g + miss]  +  p_c · Σ_{r=2..R} min(O + (r−1)·g, cap)  +  p_o · [(R−1)·400 + B]
miss = T_role if R·g + O > T_role else 0
account: O = 35,800  g = 3,400  cap = 60,000  T = 45,000  B = 9,000 (expected) | 15,000 (max)
contact: O = 25,600  g = 3,400  cap = 56,000  T = 42,000  B = 5,000 | 12,000
prices (Grok 4.6): p_n = $2.00/M  p_c = $0.50/M  p_o = $6.00/M
```

The gate computes the **ceiling** for the observed `R` (rounds used) per subject and the
**realised** cost from the ledger, and fails when realised > ceiling(R) × 1.10 — a run that spent
more than its own round count can explain has a context leak (clearing off, a `read_file` of a
whole page, the L1 duplicate), and that is a bug, not a budget question. Extraction, pages and
providers are checked against their own §5.5 lines (B: $0.14 + 5 × $0.10 Flash; E: $0.13 + $0.31;
providers: $0.66 + $0.18) with the same ×1.10 tolerance on the expected path and the §5.5 ceilings
as hard bounds.

**The structural ceiling beside the modeled one (R16).** The modeled ceiling assumes a
well-behaved judge (≈ 400 output tokens on non-brief rounds, one emission, cache hits). The gate
also prints, per account, what the **settings alone** bound, with no assumption about model
behaviour:

```
structural(role) = R_max · [p_n · cap_role + p_o · max_output_role]       # every round a full miss at the context cap, at the profile's max output
structural(B)    = calls_max · p_o · EXTRACT_MAX_OUTPUT_TOKENS + chars_max/4 · p_n
                   # calls_max = sources at the count caps (templates + A3 + gap + judge ops) × chunking × (1 + EXTRACT_RETRIES)
structural(E)    = sections · PAGE_MAX_ATTEMPTS · (p_n · 9k + p_o · 1.5k)
structural(prov) = the §5.5 operation-count ceiling (351 operations → $3.16; AI Ark ≈ 25 credits → $0.25; $3.41) + $3.00 while D8 is unpriced
structural(acct+5) = structural(account) + 5 · structural(contact) + B + E + prov   # the launch turn is excluded
```

With R16's four caps in force (raw-view reads refused, so a kept tool result is ≤ 3k tokens and the
context cap is structural; no fallback chain, so every call is on the price sheet; extraction output
≤ 2,000 tokens per call; pages ≤ 2 attempts) this is ≈ **$22.7 / $25.8 Flash** (cache-friendly /
every call a miss; Luna ≈ $17.9 / $21.0) for an account + 5 — the judge terms dominate (account
$3.62–4.37, five contacts $8.76–11.2; 03 §5.5's table). Review B §1.3's earlier ≈ $23 / ≈ $29
were computed before the four caps existed. 03 §5.5 carries the authoritative recomputation; the gate computes
its own from `settings_in_force`, so the number moves with the settings. The gate **fails** on the
modeled ceiling (× 1.10 at the observed `R`, above) and **warns** when realised > 50 % of
structural; the three terms that separate the two — output tokens per round, resubmits, cache
misses — are each read by Q2 and printed with the warning. The launch turn is reported, never
gated. A **re-driven judge turn** after `needs_review/quality_unit_incomplete` is a second full
round budget: Q2 groups by `agent_turn.execution_id` so it is a separate turn, the gate reports
`cost.turns_per_subject`, and a subject with > 1 judge turn is graded on the sum and flagged
(review B §6 edit 15).

### 4.3 The queries

All against the replay database (the production pilot runs the same SQL on the read-only user when
granted; until then the Langfuse variants in 4.4). `:run_id` is the account research run.

**Q1 — provider spend and time by stage, per job**

```sql
SELECT j.job_id, j.subject_type,
       CASE WHEN l.provider = 'openrouter' AND l.label LIKE 'extract-%'        THEN 'B_extract'
            WHEN l.provider = 'openrouter' AND l.label = 'v26-compile'          THEN 'A0_compile'
            WHEN l.provider = 'openrouter' AND l.label LIKE 'page-writer-%'     THEN 'E_pages'
            WHEN l.provider = 'ai_ark'                                           THEN 'A_ai_ark'
            WHEN l.provider = 'exa'                                              THEN 'A_exa'
            ELSE l.provider END                                                    AS stage,
       count(*)                                        AS calls,
       sum(l.cost_usd)                                 AS usd,
       sum(l.credits)                                  AS credits,
       sum(l.latency_ms) / 1000.0                      AS wire_s,
       count(*) FILTER (WHERE l.cost_usd IS NULL AND l.credits IS NULL
                          AND l.provider IN ('exa', 'ai_ark', 'openrouter')) AS unpriced,  -- ATS boards are provider 'live_http', free by design
       count(*) FILTER (WHERE l.outcome <> 'ok')      AS not_ok
FROM provider_call_ledger l
JOIN arv2_research_job j ON j.job_id = l.entity_research_job_id
WHERE j.run_id = :run_id AND l.phase = 'result'
GROUP BY 1, 2, 3 ORDER BY 1, 3;
```

**Q2 — judge spend, rounds, cache share, peak context, per job and role**

```sql
SELECT q.job_id, m.role,
       count(*)                                                  AS rounds,
       count(*) FILTER (WHERE m.status <> 'completed')           AS failed_rounds,
       sum(m.cost_usd)                                           AS usd,
       sum(m.input_tokens)                                       AS new_in,
       sum(m.cache_read_input_tokens)                            AS cached_in,
       sum(m.output_tokens)                                      AS out,
       round(sum(m.cache_read_input_tokens)::numeric
             / NULLIF(sum(m.input_tokens + m.cache_read_input_tokens), 0), 3) AS cached_share,
       max(m.input_tokens + m.cache_read_input_tokens)           AS peak_context,
       sum(m.latency_ms) / 1000.0                                AS model_s,
       min(m.started_at), max(m.completed_at)
FROM agent_model_call m
JOIN arv2_quality_execution q ON q.execution_id = m.execution_id AND q.workspace_id = m.workspace_id
JOIN arv2_research_job j      ON j.job_id = q.job_id
WHERE j.run_id = :run_id
GROUP BY 1, 2;
```

**Q3 — the job rows (status, counters, recipe pin, attempts)**

```sql
SELECT job_id, subject_type, status, failure_code, attempt, started_at, finished_at,
       model_rounds, tool_calls, cost_usd, credits, media_seconds, profile_ref,
       input_refs->>'quality_recipe_version' AS recipe, input_refs->>'v26_stage' AS v26_stage
FROM arv2_research_job WHERE run_id = :run_id ORDER BY subject_type, started_at;
```

**Q4 — wall clock: launch → committee → account pages → last page**

```sql
WITH launch AS (
  SELECT min(enqueued_at) AS t0 FROM fleet_task
  WHERE kind = 'arv2_account_research' AND work_id = (SELECT job_id FROM arv2_research_job
                                                      WHERE run_id = :run_id AND subject_type = 'account')),
committee AS (
  SELECT min(enqueued_at) AS t_nom FROM fleet_task
  WHERE work_id IN (SELECT job_id FROM arv2_research_job WHERE run_id = :run_id AND subject_type = 'person')),
pages AS (
  SELECT b.subject_kind, b.page, min(b.generated_at) AS first_write, max(b.generated_at) AS last_write
  FROM display_block b
  JOIN arv2_research_job j ON j.workspace_id = b.workspace_id
   AND ((b.subject_kind = 'account' AND b.subject_id = j.account_entity_id AND j.subject_type = 'account')
     OR (b.subject_kind = 'contact' AND b.subject_id = j.subject_entity_id AND j.subject_type = 'person'))
  WHERE j.run_id = :run_id AND b.context_id IS NOT NULL
  GROUP BY 1, 2)
SELECT extract(epoch FROM (committee.t_nom - launch.t0))                                     AS launch_to_committee_s,
       extract(epoch FROM (max(first_write) FILTER (WHERE subject_kind = 'account') - launch.t0)) AS launch_to_account_pages_s,
       extract(epoch FROM (max(last_write) - launch.t0))                                      AS launch_to_last_page_s
FROM launch, committee, pages GROUP BY launch.t0, committee.t_nom;
```

(`display_block.generated_at` is the publish time per section; the r27 per-section writer publishes
each section as it lands, so `max(last_write)` of the refresh pass is the "final pages" instant.)

**Q5 — nomination → first person start**

```sql
SELECT extract(epoch FROM (min(j.started_at) - min(t.enqueued_at))) AS nomination_to_first_person_s
FROM arv2_research_job j JOIN fleet_task t ON t.work_id = j.job_id
WHERE j.run_id = :run_id AND j.subject_type = 'person';
```

**Q6 — budgets and context (r27)**: `arv2_quality_allowance` `model_calls / max_model_calls`,
`tool_calls / max_tool_calls` per job (02 §3.8) and, for operations, `count(*) FROM
arv2_research_operation WHERE job_id = :job AND kind LIKE 'quality_tool:%'` against
`CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` / `…_PERSON_…` — both ratios must be < 1.0; peak context from Q2;
`compaction_events` from the `arv2.v26.settle` span (4.4) or, until it lands, from the
`agent-model-input` artifacts (a shrink between consecutive calls' input sizes).

**Q7 — the zero-lists.** Error classes are not in the database as a vocabulary; the harness reads
them from the turn's tool results (`agent_tool_result` + result artifacts recovered through
`recover()`, 03a §5.2) and from `arv2_research_operation.error_code` / `provider_call_ledger.error_code`,
classifying with the 01 §3 message classes (`build_corpus.py`'s table, ported to
`replay/collect.py`). Media: `count(*) FROM arv2_research_operation WHERE job_id = ANY(:jobs) AND
kind IN ('media_discovery') OR kind LIKE 'quality_tool:%media%'` = 0 and `count(*) FROM
arv2_media_operation` for the jobs = 0. Repurchase: an operation row whose `(job, kind,
request_sha256)` appears with two different `operation_id`s cannot exist (UNIQUE); the harness
instead counts **transport sends** per exact key > 1 within one run (`PoolTransport` log) — the
honest definition of "bought twice".

**Q8 — evidence-call time vs provider time**

```sql
SELECT o.kind,
       count(*)                                                                 AS n,
       avg(extract(epoch FROM (o.finished_at - o.created_at)))                  AS op_s,
       avg(l.latency_ms) / 1000.0                                               AS wire_s,
       avg(extract(epoch FROM (o.finished_at - o.created_at)) - l.latency_ms / 1000.0) AS platform_s
FROM arv2_research_operation o JOIN provider_call_ledger l ON l.ledger_id = o.ledger_id
WHERE o.job_id = ANY(:jobs) AND o.state IN ('succeeded', 'empty')
GROUP BY 1;
```

`created_at → finished_at` spans `operations.begin` to `operations.finish` inside `_drain`, i.e. the
whole hop minus the governed envelope; on r26 the governed envelope is added from the Langfuse
`governed.acquire_research_evidence@2` span latency (as 01 §1.3 did); on r27 the pre-step has no
envelope and the `arv2.v26.acquire` attributes `provider_ms_sum / drain_ms_sum / wall_ms` are the
primary source once they exist.

**Q9 — pages: writes, repairs, refresh, rewrites**

```sql
SELECT subject_kind, page, section_key,
       count(*)                                           AS revisions,
       count(*) FILTER (WHERE superseded_at IS NULL)      AS live,
       min(generated_at), max(generated_at)
FROM display_block WHERE workspace_id = :ws AND context_id = :context_id
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
-- rewrites: executions of the reconciliation/continuation kind
SELECT count(*) FROM arv2_generation_signal s JOIN arv2_account_research_generation g USING (generation_id)
WHERE g.run_id = :run_id;
```

A section with `revisions > 1` on r27 is a refresh (allowed for `buying-committee`,
`how-to-approach` only) or a repair; anything else is a rewrite and fails the "0 rewrites" line.

**Q10 — the four R16 caps (§4.5)**

```sql
-- (b) no fallback-model repricing on research roles: every research call answered by the requested model
SELECT q.job_id, m.role,
       count(*) FILTER (WHERE m.answering_model IS DISTINCT FROM m.requested_model) AS fallback_calls
FROM agent_model_call m
JOIN arv2_quality_execution q ON q.execution_id = m.execution_id AND q.workspace_id = m.workspace_id
JOIN arv2_research_job j      ON j.job_id = q.job_id
WHERE j.run_id = :run_id GROUP BY 1, 2;                               -- must be 0 everywhere

-- (c) extraction output per call <= CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS, and how many calls were split
SELECT max((l.extras_json->'usage'->>'completion_tokens')::int)             AS extract_output_tokens_max,
       count(*) FILTER (WHERE l.extras_json->>'finish_reason' = 'length')   AS length_hits,
       count(*) FILTER (WHERE l.label LIKE 'extract-%-split%')              AS splits
FROM provider_call_ledger l JOIN arv2_research_job j ON j.job_id = l.entity_research_job_id
WHERE j.run_id = :run_id AND l.phase = 'result' AND l.provider = 'openrouter' AND l.label LIKE 'extract-%';

-- (d) page attempts: the contact-page continuation's fleet task never exceeds CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS
SELECT t.work_id, max(t.attempts) AS page_attempts_max
FROM fleet_task t JOIN arv2_research_job j ON j.job_id = t.work_id
WHERE j.run_id = :run_id AND t.kind = 'arv2_account_research'
  AND t.payload->>'continuation' = 'contact_page'
GROUP BY 1;                                                           -- max <= 2; past it the job reads needs_review/page_section_failed
```

(a) Raw-view reads by an r27 judge are not in a table as such: the harness counts, over the turn's
tool results (`agent_tool_result` + artifacts, Q7's recovery), every `read_file` whose path matches
`/research/operations/<id>/0.json`, `/research/operations/<id>/<N>.json` or `/evidence/…` — each must
be a **refusal receipt** (`CLUE_ARV2_V26_JUDGE_RAW_READS=false`; the r27 profiles' readable set
excludes the raw views) and the count of *served* raw reads is 0; reads of
`/research/operations/<id>/candidates.json` and `inputs/candidates-*.json` are the allowed ones and are
counted separately. The extractor's `finish_reason` and `completion_tokens` must ride the ledger
row's `extras_json` (the `openrouter_cost_reader` extras, 02 §3.6) — a requirement on W3-23 that
the gate checks for (a missing key is a failed grade, not a zero).

### 4.4 The Langfuse queries (production pilot, before the DB user exists)

The replay pulls the same facts from Langfuse as the corpus did (`.artifacts/arv2-research-runs-20261007/build_corpus.py`:
v2 observations for timing/usage/cost, tool I/O for receipts), filtered by the run's release and
environment. Each v26 trace carries `release=<git sha>` (03 §8.3; `CLUE_RELEASE` set by
`deploy/vm/deploy.sh`) and tags `v26`, `account:<domain>`, `job:<id>` (03 §8.1); r26 traces carry
only `execution_id` in metadata (02 §8.1), so RC-1 joins through `arv2_quality_execution.execution_id`
as 01 did.

```
# every observation of the pilot's traces (one trace per job since PR #90)
GET /api/public/v2/observations?fromStartTime=<t0>&toStartTime=<t1>&environment=production
    &fields=core,basic,usage,model,time&limit=100&page=N
  → keep rows whose trace has tag "account:<domain>" (v26) or metadata.execution_id ∈ the run's executions (r26)
  → model cost  = Σ totalCost over type=GENERATION, name=GovernedAgentChatModel          (judge)
  → leaf cost   = Σ totalCost over name=openrouter.chat/completions                        (compile, extract, pages)
  → cache share = Σ usageDetails.cache_read_input_tokens / Σ (input + cache_read)
  → stage walls = span latency of arv2.v26.<stage>; provider wire = exa.search / exa.contents / ai_ark.* span latency
  → errors      = rows with level=ERROR, classified by statusMessage (01 §3 classes)

# the one-line totals, once the Metrics API is used instead of paging
GET /api/public/metrics?query={"view":"observations","metrics":[{"measure":"totalCost","aggregation":"sum"},
   {"measure":"latency","aggregation":"p95"}],"dimensions":[{"field":"name"}],
   "filters":[{"column":"tags","operator":"any of","value":["account:dialpad.com","v26"],"type":"arrayOptions"},
              {"column":"release","operator":"=","value":"<git sha>","type":"string"}],
   "fromTimestamp":"<t0>","toTimestamp":"<t1>"}
```

Langfuse masks every string at 8,000 chars and holds no provider spend (02 §8.1); the pilot's
provider line therefore comes from the production ledger only. Until the read-only user is
granted, the pilot gate reads model cost, time and errors from Langfuse and marks provider cost
`unmeasured` — the same gap 01 §7 item 1 records.

### 4.5 The four structural caps the gate measures (R16)

| Cap | Setting (03 §10) | What the gate reads | Pass | Source |
|---|---|---|---|---|
| (a) No raw-view reads by r27 judges | `CLUE_ARV2_V26_JUDGE_RAW_READS=false` | `caps.raw_view_reads` = served `read_file`s on `/research/operations/<id>/{0,N}.json` or `/evidence/…` by an r27 judge; `caps.raw_view_read_refusals` = refusal receipts on the same paths | reads = 0 on every subject; refusals reported (a non-zero count is the judge still trying — a prompt note, not a failure) | the turn's tool results (Q7's recovery), per path |
| (b) No fallback-model repricing | `CLUE_ARV2_V26_FALLBACK_MODELS=` (empty for research roles) | `caps.fallback_model_calls` = `agent_model_call` rows with `answering_model ≠ requested_model` on roles `account_research` / `person_research`; a primary failure must appear as a failed round or a **suspended** job (`available_at = now + MODEL_RETRY_DELAY_S`; `needs_review/model_unavailable` only after `MODEL_RETRY_SUSPENDS` = 3 suspends, 03 §3.6.5), never as a priced call on another model | 0 | Q10 (b) |
| (c) Extraction output per call | `CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS=2000`, with halving of large sources | `caps.extract_output_tokens_max`, `caps.extract_length_splits`, `caps.extract_skipped` | max ≤ 2000; every `finish_reason=length` is followed by a split (never a retry of the same request); `extract_skipped = 0` or the job is `needs_review/extract_incomplete` | Q10 (c) |
| (d) Page attempts | `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS=2` | `caps.page_attempts_max` over the contact-page continuations' `fleet_task.attempts` and the account's in-job section repairs | ≤ 2; a page past it is `needs_review/page_section_failed` until `manual_refresh` | Q10 (d), Q9 |

The four counters are zero-list lines (§3) at both checkpoints, go/no-go item 11 (§6.1) and the
weekly production check (§6.2 item 7, §6.3). Their effect on the ceiling is §4.2: with (a) the
context cap is structural (a kept tool result is ≤ 3k tokens), with (b) every call is on the price
sheet, with (c) extraction's output term is bounded per call, with (d) pages are bounded per
section — which is what lets the gate print a structural number at all.

---

## §5 The depth gate

AT-6 and AT-9 prove nothing is *lost*; the depth gate proves what was *kept* is still the
seller-critical kind. It applies 01b's rubric (A = seller-critical: a dated trigger, a pain, an
initiative, a buyer/role with evidence, a why-now, a usable hook, the subject's own recent words
on their work; B = useful context; C = filler) to the v26 brief, by a scripted rater, and compares
per-class A counts with the production counts and the caps.

### 5.1 The scripted rater (`arv2/replay/rater.py`)

- **Prompt** `tests/arv2/v26/rater/SYSTEM.md` (v1): the rubric text of 01b §1.3 verbatim, the
  seller-relevance definition per workspace (Clue: ABM / marketing production; Samsara: fleet
  safety / telematics; Garner Health: employer health benefits — read from each pool's
  `context/product-catalog.md`, exactly as 01b read the deep-report charters), the class
  vocabulary of 03 §2.1, and a JSON output contract `{"rating": "A|B|C", "class": "<id>",
  "misattributed": bool, "why": "<one line>"}`. Input per finding: `topic`, `finding`, `quote`,
  `time_context`, `attribution`, `section/class` — never the seller brief or other findings (the
  rater rates one item, blind to the rest; the "seller-critical" judgement needs the product, not
  the campaign).
- **Model** `RESEARCH_EXTRACT_AGENT_MODEL` (D4's pick), `temperature=0`, `reasoning.effort=low`,
  JSON mode; one call per finding, batched 20 per request with ids; cassette-recorded by request
  sha so a re-rate of the same brief is free.
- **Calibration set** = `fixtures/ratings.json` (1,782 findings over 42 runs, rule-rated then
  hand-overridden — 401 A; the Dialpad account, Flynn and Wall carry the independent depth
  reviewer's ratings, `.artifacts/account-research-cost-20261006/depth-review/ratings.json`) with the
  finding texts from `fixtures/findings.json`. The rater runs over all 1,782 once
  (`scripts/arv2_v26_replay_gate.py --calibrate`, ≈ $0.40 on Flash).
- **Agreement thresholds, all required before any rater number gates anything:** A-vs-non-A
  accuracy ≥ **0.85** over the 1,782; Cohen's κ ≥ **0.60**; A-recall ≥ **0.80** and A-precision
  ≥ **0.75** (01b's rule-only pass over-rated A 1.3–2.2× — the rater must not); on the three
  reviewer-rated runs accuracy ≥ 0.85; class agreement on A items ≥ 0.80. Recorded in
  `fixtures/rater_calibration.json` with the prompt sha and model id; a prompt or model change
  re-runs the calibration.
- **If calibration fails:** the rater is **not** used. The depth gate for the pilot then rests on
  AT-6/AT-9 (mechanical) plus a hand rating of the two pilot accounts' briefs by two people on the
  01b rubric, with the rater's output as a draft only; this is recorded in `gate.json.depth.method`.

### 5.2 What the depth gate measures (per account, per run)

| Measure | Computation | Pass |
|---|---|---|
| A-class served items per class | rater over the served brief items, counted per class (account: trigger, initiative, pain, motion_proof, stack, committee, watch_out, not_found; contact: remit, problem_now, own_words, proud_of, hook, career_arc, do_not_mention) | per class ≥ **0.70** × the production A count of that class for that subject (`fixtures/summary.json` / 01b T8–T9), and the subject's total A ≥ 0.80 × production (the ±15 % noise band plus the dropped-by-construction categories) |
| A-class items **cut by a cap** | rater over the `over_cap=true` items; the caps in force are **01b §6's values (R10)** — account Trigger 10, Initiative 5, Pain 5, Motion 5, Stack 8, Committee 10, Watch-outs 4, Not-found 3; contact remit 2, problem-now 5, own-words 8, proud-of 3, hooks 4, career-arc 1, do-not-mention 1 — and the gate refuses to grade a run under other caps (`settings_in_force`) | at 01b's caps the corpus loses **0** A items to a cap (review B §2.3: 26 of 401 at the plan's old values), so an A-rated over-cap item on ≥ 2 accounts in one class is new evidence → recorded in `gate.json.depth.caps_to_raise[]` as a **founder decision row for 06**, never an env change the gate makes; the gate fails only when a class cuts ≥ 10 % of its subject's A-rated items on both RC-2 runs |
| C-class served items | rater | ≤ **5 %** of served items (production: 23 % of findings are C — filler is what v26 drops by construction, 03 §2.1) |
| Follow-up chain recall | AT-9 | as §3 |
| Quote verification rate | served items with a `quote`: `quote_rule` re-run by the gate against the pooled source (not the server's own verdict) | **100 %** (anything less is a `submit_brief` bug — the server restores the candidate's verified quote on mismatch, 03 §3.7) |
| Misattribution | (a) served items with `wrong_entity=true` = 0 by construction — checked; (b) served contact items whose cited candidate has `subject_anchor.matched=false` = 0 (hooks: `outreach_safe=false` never served); (c) rater `misattributed=true` on served items; (d) committee items whose person's employer (from the AI Ark record) ≠ the account = 0 — the 2026-09-28 Muse defect (`REPORT.md` "wrong-employer attribution") | (a), (b), (d) = **0**; (c) = 0 on a calibrated rater, else reported |
| Interpretation presence | served items of the classes 03 §2.1 marks "Interp. yes" with a blank `agent_interpretation` | 0 (a `submit_brief` shape error, 03 §3.7 step 7) |
| Own-words freshness | served `own_words` items whose `date` ≥ `as_of − 270 d` | ≥ 0.80 of served own-words per contact (01b's A definition is "recent"; the A2 templates are dated) |

The depth gate's output is `gate.json.depth` with the per-class table and the `caps_to_raise` list,
and a Markdown digest listing — by id, class and key phrase only — every production A item the
brief did not keep (from AT-6) and every C item the brief served (from the rater). The digest is
what a human reads; the verdict is the table.

---

## §6 Go / no-go

### 6.1 Flip the pilot workspace to r27 (W3's `CLUE_ARV2_RECIPE_PILOT_WORKSPACES`)

All of the following, from `gate.json` of **two** RC-2 runs on Dialpad + Loopio (04 §7.3 "passes
twice"), the second with `--committee live`:

1. AT-1, AT-2, AT-3, AT-4, AT-5, AT-7, AT-8 pass on both runs (mechanical and DB tiers green in
   `make check` + the local DB).
2. AT-6 and AT-9 pass on both runs on both accounts at §3's thresholds; `unreachable` ≤ 15 % per
   fixture file.
3. Cost realised ≤ the §4.2 ceiling for every subject, and the account+5 total ≤ 1.5× expected on
   at least one of the two runs; providers ≤ $3.41 (03 §5.5); no `unpriced` provider calls.
4. Time launch → last page ≤ 10 min on both runs (two accounts side by side); nomination → first
   person ≤ 30 s; `wait_pools.absent = 0`.
5. Every zero-list line is 0; `budget_use_ratio < 1.0` on rounds and operations for every subject;
   `compaction_events = 0`.
6. Depth gate: calibrated rater (or the hand rating on record), per-class ≥ 0.70, total ≥ 0.80,
   C ≤ 5 %, misattribution 0, quote verification 100 %.
7. `committee_overlap ≥ 4` on the live-committee run (a lower overlap is not a failure of research
   but blocks the flip until the founder has read the two committees side by side — D10 makes the
   committee automatic, so the nomination quality must be seen once).
8. The r27 mint passed the five hard-coded tests and `make manual-check` (04 §8.3); `make db-smoke`
   green for the three W2/W3 migrations (04 §10); `.env.example` parity for every v26 line, one
   name scheme (03 §10 after R7).
9. The observability of §7 is live on the worker image (the spans exist in a replay trace with
   `release` set).
10. **P6 landed (R14):** `stop_contact_jobs` and the claim writer's privacy block filter include
    every `agent-profile:arv2-person:v%` ref (04 P6's prefix filter — the person `profile_ref` is
    catalog-versioned, `…:v4` for every quality person job, never per recipe); the DB test
    `tests/arv2/test_privacy_stop_v4_db.py` is green; and the replay's privacy-stop walk (§6.2 item 4's `test_privacy_stop_mid_pipeline`)
    passes on an r27 contact: `input_refs.privacy_stopped` set, `job_available` false at the next
    operation, no page, `submit_brief` drops the items. No r27 pilot before this line.
11. **The four R16 caps are wired and measured** (§4.5): `caps.raw_view_reads = 0` with ≥ 1 refusal
    receipt proven by `tests/arv2/v26/test_raw_view_refused.py` (DB); `caps.fallback_model_calls = 0`
    and a forced primary failure **suspends** the turn for retry (`available_at` set, resume from the
    checkpoint; `needs_review/model_unavailable` only past `MODEL_RETRY_SUSPENDS` = 3 — never a
    repriced call); `caps.extract_output_tokens_max ≤ 2000` with ≥ 1 observed split on the
    dense fixtures (an ATS board, a report chunk); `caps.page_attempts_max ≤ 2` and a page forced
    past it stays `needs_review/page_section_failed` until `manual_refresh` (review B §6 edit 15).
12. **Clearing in force = 03 §5.3 (R6)** on both runs: `settings_in_force` shows 45,000 / 42,000,
    keep 4, exclude = {`submit_brief`, `finalize_turn`}; `C_account.clear_events ≥ 1` (the
    expected 7-round run crosses 45k at round 4) and `compaction_events = 0` everywhere.
13. **The deferred contact page runs as the research-kind continuation (R11):** every contact's
    page was written by a `fleet_task` of kind `arv2_account_research` with
    `payload.continuation = "contact_page"` (Q10 d), none by an `arv2_display_page` task.
14. **Fleet environment verified (review A M11):** `deploy/check_prod_env.py` output for the pilot
    worker pasted into the `_memory/` entry with `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`,
    `CLUE_FLEET_WORKER_CONCURRENCY`, `CLUE_DB_POOL_SIZE` / `CLUE_DB_MAX_OVERFLOW`, `CLUE_RELEASE`
    (set by `deploy/vm/deploy.sh`), the model-block lines (`RESEARCH_EXTRACT_AGENT_MODEL`,
    `PERSON_RESEARCH_AGENT_MODEL`, `RESEARCH_NARRATIVE_AGENT_MODEL`) and the image sha the worker
    runs; the values equal the ones the RC-2 runs used (`settings_in_force`).
15. **The pilot context's compile artifact reviewed once** (review B §3 row 13): the A0.0 compile for
    the pilot project (`tests/arv2/v26/fixtures/compile_<context>.json`, ≈ 50 terms) read by the
    founder; any ICP front-matter `search_terms:` override committed before the flip.
16. **DSAR binding of the pre-step and extractor artifacts (review A M15, K3):** the replay's DSAR
    walk shows the extractor's raw request/response envelope and the pool artifacts are
    subject-bound and erased with the contact —
    `tests/arv2/test_prestep_db.py::test_contact_erasure_reaches_pool_and_extract_artifacts` (DB).
17. The `_memory/` entry carries both `gate.json`s, the git sha, the pool shas, the
    `settings_in_force` block and the D4/D8/D9 values the runs used.

Then: add the pilot workspace to `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` with
`CLUE_ARV2_RECIPE_PILOT_VERSION=27`; run **one real request** in the pilot (a new account of the
pilot's choosing) and read it against the plan §3 numbers within the max column (04 §7.4 W3).

### 6.2 Flip every workspace (`CLUE_ARV2_RECIPE_VERSION=27`)

1. The pilot has researched ≥ **5 accounts** (≥ 25 contacts) on r27 with every job `completed` or
   an honest `needs_review` whose code is a provider outage (not `brief_invalid`,
   `quality_unit_incomplete`, `page_section_failed`, `pool_persist_failed`).
2. Production numbers over those ≥ 5 accounts (Langfuse + ledger, §4.4): median cost ≤ 1.5×
   expected and max ≤ ceiling; median time ≤ 10 min and max ≤ 15 min; zero-lists 0; no
   `budget_use_ratio = 1.0` on > 20 % of jobs.
3. The scripted rater (calibrated) over the ≥ 5 briefs: C ≤ 5 %, misattribution 0; and the founder
   has read two of them (the quality bar is the founder's, 00/06 record the reading).
4. No DSAR/privacy-stop regression: one privacy-stop exercised on a pilot contact mid-pipeline lands
   `failed/privacy_stopped`, no page, and `submit_brief` drops its items (03 §3.9) — proven once on
   the replay (`tests/arv2/test_prestep_db.py::test_privacy_stop_mid_pipeline`, DB) and once in the
   pilot.
5. The W2 throughput items are landed and `arv2.v26.db_lock_wait_ms` p95 < 50 ms on the pilot
   (03 §6.2's precondition for raising `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` to 6).
6. Rollback rehearsed once: a pilot workspace removed from the allowlist launches on r25/r26 and
   its in-flight r27 jobs finish on their pin (03 §9.4).
7. Over the ≥ 5 pilot accounts: the four R16 cap counters read 0 / 0 / ≤ 2000 / ≤ 2 on every job
   (§4.5), `turns_per_subject = 1` on every job (no re-driven judge turns), the structural-ceiling
   warning fired on none, and every job trace is ≤ 25 MB.
8. P6's privacy-stop path exercised once in the pilot on a real r27 contact (§6.1 item 10's
   replay proof repeated live).

### 6.3 Rollback triggers (observed numbers that move a workspace back)

| Trigger | Threshold | Action |
|---|---|---|
| Misattribution | **1** served committee or contact item with the wrong employer/person (rater or human) | immediate: remove the workspace from the allowlist (or `CLUE_ARV2_RECIPE_VERSION=25`); the item is unserved by marking `wrong_entity` on its claim; root-cause before re-enabling |
| Cost | any account+5 > **$9.4** (Flash) / **$8.1** (Luna) ceiling, or 3 consecutive accounts > 1.5× expected | roll back that workspace; read Q2 for the leak (context, rounds) before re-enabling |
| Time | any single account > **15 min** launch → last page, or median over 5 > 10 min | roll back; read `stages.*.wall_s` — the AI Ark gap and `wait_pools` are the two serial resources |
| Depth starvation | `budget_use_ratio = 1.0` (rounds or operations) on > **20 %** of jobs in a week | **not** a rollback: raise the budget settings (plan §8), then watch cost |
| Honest-empty rate | > **30 %** of contacts with ≤ 2 served items, or an account brief with < 10 served items, on ≥ 2 of 5 accounts | roll back; compare AT-6 on the frozen pool for the same accounts (a freeze of a production account is ≈ $0.6) |
| Failure codes | `needs_review` on > **10 %** of jobs in a week, or any `brief_invalid` / `pool_persist_failed` | roll back; the codes name the item |
| Zero-list breach | any media operation, any repurchase, any `schema_validation` on r27 | fix forward if the count is 1 and the cause is known within a day; otherwise roll back |
| Provider | AI Ark credit halt or Exa 5xx > 5 % of calls | not a recipe matter — pause launches (the halt latches per job, 02 §2.3) |
| Re-driven judge turn | any job with `turns_per_subject > 1` in a week (a re-drive after `quality_unit_incomplete` is a second full 20/12-round budget) | not a rollback by itself: the job's cost is graded on the sum (Q2 by `execution_id`); > 10 % of jobs re-driven in a week → roll back and read the first turn's failure |
| Page attempt ceiling | any contact page past `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (2) → `needs_review/page_section_failed`, re-offered only by `manual_refresh` | not a rollback: the page stays unwritten and visible as a gap; > 5 such pages in a week → roll back (the section guide or the writer model is wrong) |
| Structural-ceiling warning | realised > 50 % of the structural ceiling (§4.2) on any account | not a rollback: read Q2's three terms (output tokens per round, resubmits, cache misses); 3 consecutive accounts → roll back |
| R16 cap breach | any served raw-view read, any fallback-model call on a research role, any extraction call over 2,000 output tokens | fix forward within a day if the cause is one wiring site; otherwise roll back — each is a structural-ceiling term coming loose |

Rollback is configuration only (03 §9.4): no migration, in-flight jobs keep their pin, a relaunch
after rollback is a new run.

---

## §7 Observability needed to run the gate in production

From 03 §8, the subset the gate reads, with what breaks without it:

| Must exist before RC-2 | Read by | Without it |
|---|---|---|
| `CLUE_RELEASE` set by `deploy/vm/deploy.sh` from the git sha → Langfuse `release=` and the `clue.release` span attribute (03 §8.3; today never set, 02 §8.1) | every production filter in §4.4; the pair `(profile_sha256, clue.release)` is the version record of a job | the pilot's traces cannot be told from the previous deploy's; the gate cannot attribute a regression to a release |
| Judge-turn trace tags `v26`, `account:<domain>`, `job:<id>` and metadata `job_id` (03 §8.1; absent on v4 today) | selecting the pilot's traces per account without the DB | RC-2 falls back to the r26 join through `execution_id` (01's method) — workable, slower |
| `arv2.v26.acquire` with `ops_planned/issued/replayed/succeeded/empty/failed/unknown, pool_reads, duplicate_fetches, provider_ms_sum, drain_ms_sum, wall_ms, timed_out` per phase | §4.1 evidence-call vs provider time, repurchase and duplicate counts, stage walls | Q8 (DB) gives wire vs hop; `pool_reads`/`duplicate_fetches` have no other source |
| `arv2.v26.extract` with `candidates, rejected{reason}, floor_hits, anchored, unanchored, retries, failed` + one generation per call | AT-1's fallback diagnosis, AT-5's unanchored count, extraction cost by subject | the pool artifact's `stats` carries the same counts (03 §3.5.5) — the replay reads those; production needs the span |
| `arv2.v26.followups` `rules_fired{rule_id}`, `arv2.v26.gap` `classes_below_min`, `arv2.v26.wait_pools` `present/absent/waited_ms` | AT-9 attribution (`rule:<id>`), AT-2, AT-8 | the ledger entries in the pool artifact carry `rule`/`follows` (03 §3.4) — the replay is fine; production AT-9-style monitoring is not |
| `arv2.v26.pages` with `duration_ms{section}, repaired, skipped_unchanged, failed`; `arv2.v26.refresh` | §4.1 page lines, the 0-rewrites line | Q9 (DB) suffices for counts; per-section timing has no other source (02 §8.5 item 6) |
| `arv2.v26.settle` with `cost_usd, credits, rounds_used/max, operations_used/max, context_peak_tokens` (and `compaction_events`, `clear_events` — add to 03 §8.1's list) | Q6 budgets and context; the "depth starved" rollback trigger | `arv2_quality_allowance` + Q2 give rounds and peak; clearing/compaction events are visible only in the model-input artifacts |
| Metrics `arv2.v26.stage_duration_ms{stage}`, `budget_use_ratio{kind,subject_kind}`, `quote_rejections{reason}`, `cost_usd{stage}`, `duplicate_fetch`, `pool_read`, `over_cap_items{class}`, `brief_resubmits`, `db_lock_wait_ms` (03 §8.2; gated by `CLUE_ARV2_V26_METRICS_ENABLED`) | the four dashboards of 03 §8.4 and the weekly rollback triggers of §6.3 | the triggers must be computed by the gate script from Langfuse + the DB on a schedule instead of read off a dashboard |
| `critical_section("arv2.db_lock.wait")` (W2-20) | §6.2 item 5 | the lock wait stays unmeasured (02 §8.5 item 1) and the parallel-jobs raise cannot be taken |
| The four R16 cap counters as attributes — `raw_view_read_refusals` on the judge turn, `fallback_calls` and `turns_per_subject` on `arv2.v26.settle`, `finish_reason` / `completion_tokens` on every `arv2.v26.extract` generation (and in the ledger row's `extras_json`), `attempts` on the contact-page continuation's `fleet.task` span | §4.5 / Q10, the zero-lists, §6.3 | Q10's DB queries cover the replay; production monitoring of the caps needs the attributes |
| `input_refs.v26_stage` written at every stage boundary (03 §6.1) | the M7 progress line of §4.1 | the progress card reads 0.0 through the pre-step and the gate cannot time stages from the job row |

Two gaps 03 does not list and the gate needs: (1) **`agent_tool_result` has no duration**
(02 §8.2) — on r26 the per-call evidence time comes only from the Langfuse `governed.*` span; the
r27 pre-step needs none (no envelope), the judge's follow-ups ride `acquire@2`'s span. Accepted;
not a blocker. (2) **The replay's own traces must be separable from production**: the harness sets
`CLUE_LANGFUSE_ENVIRONMENT=replay-<label>` (`settings.langfuse_environment`, 02 §8.1), so a replay
never counts in a production dashboard.

---

## Appendix A — fixture index

| File | Produced by | Committed? | Consumed by |
|---|---|---|---|
| `.artifacts/arv2-v26-replay/fixtures/rule_table.json` (29 pairs with personal-name examples) | 01b `build_outputs.py` | no | AT-3 (examples), §5 digest |
| `tests/arv2/v26/fixtures/rule_table_pairs.json` (pairs, counts, `floor`, no examples) + `trigger_kind_map.json` | `scripts/arv2_v26_mine_runs.py` | yes | AT-3 |
| `…/fixtures/nothing_lost/<account>.json` (7 files) | 01b | no (contact tuples are personal data) | AT-6, AT-4 replay, AT-8 |
| `tests/arv2/v26/fixtures/nothing_lost_accounts.json` (account tuples only) | mine_runs | yes | AT-6 account half |
| `…/fixtures/chains/<account>.json` (7 files) | 01b | no | AT-9 |
| `…/fixtures/quote_fidelity.json`, `quote_subset.json` | 01b `quote_fidelity.py` | no (quote texts are not stored — ids, verdicts and lengths only — but the ids key into findings) | AT-1, AT-7 |
| `tests/arv2/v26/fixtures/quote_fidelity_counts.json` (the 01b §5 counts) | mine_runs | yes | AT-7 regression floor |
| `…/fixtures/namesakes/<account>.json` | mine_runs (new) | no | AT-5 |
| `…/fixtures/ratings.json`, `findings.json`, `summary.json`, `overrides.json` | 01b | no | §5 calibration, AT-6 counts |
| `tests/arv2/v26/replay_manifest.json` | freeze | yes (shas and counts only) | every replay test |
| `tests/arv2/v26/fixtures/stoplist.txt`, `brief_shapes.json` | L | yes | §3 rules, AT-4 |

## Appendix B — rulings applied, and what this document still proposes for 03 §10

Applied in this revision (`RECONCILIATION-RULINGS.md`): R2 (r26/r27), R3 (`submit_brief@1`), R4
(`person_research`, `PERSON_RESEARCH_AGENT_MODEL`), R5 (two markers, two waits, AT-8 as a slice
assertion), R6 (clearing = 03 §5.3; the gate refuses other values), R7 (03 §10 names throughout; the
P5 selector lines as 03 §10 gains them), R8 (AT-7 = 01b §5's rule on `substring_verdict`), R9 (AT-3
over the 11 floor pairs with the `entity` kind; AT-9 from `follows`), R10 (01b §6 caps in the depth
gate), R11 (research-kind continuation in the harness and §6.1 item 13), R14 (P6 as a go/no-go
line), R16 (the four caps measured in §4.5 / Q10; modeled and structural ceilings both printed,
§4.2), plus review B's early expressibility check (§3.1) and review A's gate/checklist pieces M7,
M9, M11, M15 (§4.1, §6.1, §7). Not applied here because they belong elsewhere: M10 (the production
DB queries — 01 §7 / 04 W0), M13 (the Head-of-ABM v71 mint — 04), M19 (the decision register — 06).

Proposed for 03 §10 / §8 (one line each, with `.env.example` parity where it is a setting):
1. `CLUE_ARV2_V26_AS_OF_DATE` (blank = today), read only by `acquisition_plan.plan` for the `since`
   variable — needed for byte-identical replays of dated templates across a month boundary.
   **Adopted** (03 §10 C4; 04 W3-22).
2. `arv2.v26.settle` gains `compaction_events`, `clear_events`, `fallback_calls`, `turns_per_subject`
   (03 §8.1); `arv2.v26.extract` generations and ledger rows carry `finish_reason` and
   `completion_tokens`.
3. The failure codes `needs_review/extract_incomplete` (review B §3 row 16) and
   `needs_review/model_unavailable` (R16 b: reached only after `MODEL_RETRY_SUSPENDS` = 3 suspends of
   the turn, 03 §3.6.5) named in 03 §3.5.4 / §3.6.5 so the zero-lists can read them. **Adopted.**
4. The scripts: 03 §3.5.5 names `scripts/arv2_v26_freeze_pool.py`, §8.4 `scripts/arv2_v26_replay_gate.py`,
   04 Appendix B `scripts/arv2_v26_mine_runs.py`; this document adds `scripts/arv2_v26_replay.py`.
