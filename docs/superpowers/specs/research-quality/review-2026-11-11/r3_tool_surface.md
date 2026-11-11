# R3 review: research tool surface and persistence (acquire_research_evidence@3)

Scope: `git diff dd9a7d74a..HEAD` for footprint_operations.py, quality_provider_tools.py, the wiring,
settings/secrets/sinks, the r43/r44 catalog files and their tests. Read-only. Offline tests run:
`tests/arv2/test_acquire_v3.py tests/arv2/test_quality_recipe_4{2,3}.py tests/arv2/test_import_guard.py tests/footprint`.
All pass. Proof scripts are in this folder: `x_4xx.py` and `empty_vs_fail.py`.

## Findings

### 1. IMPORTANT: outages are saved as durable "empty", "refused" or "complete" results, and an identical retry is never possible again
- Files: `footprint_operations.py:330-342, 358-372, 392-402`; `quality_provider_tools.py:200-234, 251-271`;
  `footprint/video_search.py:187-188`; `footprint/handles.py:77-81`; `footprint/pdl_client.py:62-65`.
- What is wrong: the wrapper settles each operation once, per (workspace, job, kind, argument hash).
  The key does not include the restart count, so it lasts for the job's whole life, restarts included.
  The footprint jobs bundle many provider calls into one operation, and they turn transport or HTTP
  failures into ordinary answers:
  - `find_videos`: any YouTube non-2xx (other than a quota error), or a transport error on any
    search, runs `return [], [str(exc)]`. That throws away the results of the earlier searches,
    which were already paid for. The job then returns `state: "complete"`, `n_results: 0`.
  - `find_podcasts`: when every source fails, the job still returns `state: "complete"`, with the
    failures listed only under `gaps`.
  - `find_handles`: a PDL timeout, 401 or 402 becomes `None`. The result is `complete` with no
    gaps when the key is set.
  - Social readers: a 5xx on page 1 gives `unavailable`, which the wrapper settles as `failed`. A
    failure on page N gives `partial`, which settles as `succeeded`.
- Failure scenario: YouTube returns 503 once. The receipt says `status: "empty"`, `result_count: 0`,
  with the preview line "0 video results from 2 searches". The v2 description tells the agent
  "status empty means nothing came back", so it records "no videos". Repeating the call replays the
  same answer, and the description forbids changing the arguments cosmetically. A LinkedIn history
  that stops at page 7 can never be completed in that job. Its receipt says `completed` with no
  sign that it was partial; `state` and `gap` appear only in the saved file.
- Verified: `empty_vs_fail.py` prints `find_videos outage: complete (0, True)`, which the v2
  receipt reads as `empty`. The rest was verified by reading the code. The once-only wrapper is
  inherited from v1/v2, but these jobs are where transient faults are common.
- Confidence: high.

### 2. IMPORTANT: the X and company-LinkedIn readers report any 4xx as "not_found", or as a silent "complete"; treg has no halt rule
- Files: `footprint/social.py` x_posts parse (`return [], None, _closed(body, status) or "not_found"`);
  the same line in company_linkedin_posts; `_history` at lines 109-119; `footprint/treg_client.py:63-76`
  (no `halt_rule`).
- What is wrong: a treg 402 (out of credit), a 401 (bad token) or a 429 that persists after retries:
  - on page 1, is reported as `not_found` ("this account does not exist");
  - on page 2 or later, makes `closed` truthy, which skips the `status >= 400` gap branch. Paging
    then stops with `state: "complete"` and no gap.
  The wrapper then maps `not_found` to `refused` with `error_code: "provider_refusal"`, because the
  history has no gap and no code. The agent cannot tell "no such account" from a provider failure.
  A private account comes back as `empty`; "private" appears only in the saved file. treg never
  latches, so after a 402 every later treg job in the run keeps calling it. This goes against the
  "money truth blocks" rule.
- Verified by `x_4xx.py`:
  - `X page1 402 -> not_found None`
  - `X page2 429 -> complete None 1`
  - `company page1 402 -> not_found None`
  - LinkedIn is correctly `unavailable`.
- Confidence: high.

### 3. IMPORTANT: erasure does not reach a person's saved post history when an account job fetched it; raw pages are never bound to the person
- Files: `quality_provider_tools.py:318-329` (binds `person_subject_id or account_id`);
  `prompts/quality-account-research/v42/SYSTEM.md:95` ("read what [leaders] post with linkedin_activity");
  `tests/arv2/test_footprint_erasure_db.py`.
- What is wrong:
  - **Account jobs.** v42 tells account jobs to read leaders' whole LinkedIn activity and X feeds.
    The saved result is bound in `agent_artifact_subject` to the account entity only.
    `AgentPrivacyService.erase_subject(contact)` selects artifacts by subject, so a DSAR for that
    leader never finds it.
  - **Raw pages, in any job.** The raw treg pages and the PDL person record become
    `provider_record` evidence originals. Nothing binds them to the person. The wrapper's
    `artifact_derivation` edges run original → result, so erasing the result does not erase the
    originals.
  - **The test.** Plan Task 13 asked for an erasure that is then shown to make the post page,
    transcript and speaker-check data unreadable. The test only asserts that one person-job result
    has a binding row. It never erases, and it never covers an account job or the raw pages. Its
    second test asserts the field names of a constant.
- Failure scenario: a CISO researched as a committee member of an account files a DSAR.
  `erase_subject` runs, and the account job's saved copy of every LinkedIn post and reaction
  remains, as do the raw fetchinio and TikHub pages.
- Verified by reading the code (`agent_turn_wiring.py:1800` erase_subject; the trigger in alembic
  `aaae5d2e1fa4`).
- Confidence:
  - high for the account-job binding;
  - medium for raw pages in person jobs, because the S4-E turn closure might sweep some of them if
    the turn referenced them.

### 4. IMPORTANT: the full PDL person record is stored and indexed as citable evidence, with no data minimisation
- Files: `footprint/pdl_client.py:43-71` (no field selection; returns the whole `data`);
  `quality_acquisition.py:329-341` (non-ai_ark bodies are indexed whole; only `ai_ark` gets
  `enrichment_only`).
- What is wrong: `find_handles` needs only the twitter and facebook usernames. The raw PDL
  enrichment response becomes a `provider_record` under `/evidence/`, readable and citable by the
  agent. Depending on the PDL plan, it can include personal emails, mobile phone, street address
  and birth year. It is also not bound to the person (finding 3).
- Failure scenario: `find_handles` runs for an EU executive. Their personal email and phone are now
  durable evidence the agent can quote. This goes against the strict-case, minimum-data rule in
  CLAUDE.md.
- Verified by reading the code. I did not check which fields the account's PDL plan returns.
- Confidence: medium.

### 5. IMPORTANT (crash recovery): an unbounded footprint call keeps its whole spend record in memory; a worker death loses it, and the operation stays "running" with no sweep
- Files: `account_research_tools.py` `_dispatch`/`_land` (BufferedRawSink/BufferedLedger, drained
  only after `fn` returns); `research_operations.py:57-98` (2-hour lease, marked `unknown` only
  lazily); `footprint/treg_client.py:63-76` (no `estimate`).
- What is wrong: the footprint readers page with no page limit. A heavy poster's LinkedIn
  reactions can mean dozens of 120-second treg calls inside a single hop. Every ledger row, the
  pre-wire estimate row (Law 2) included, sits in memory until the hop ends.
  - A worker death or deploy during the hop loses the whole money trail for spend that really
    happened. The treg `CallSpec` has no estimate, so even the estimate rows record $0. A missing
    `X-Treg-Cost-Micro` header is recorded as $0 with source "estimate".
  - The `arv2_research_operation` row stays `running`. No sweep exists; only a later identical
    `begin` after 2 hours marks it `unknown`.
  - On resume, the re-issued call gets `outcome_unknown` / `dispatch_outcome_unknown` with "Inspect
    /evidence/index.json; record the gap without repurchasing". Nothing reached evidence, though.
    The person's LinkedIn is then closed for the rest of the job.
  - Recovery never replays spend, and the agent gets an honest "unknown". The money record and the
    data are both lost.
- The same happens on a cancelled turn (Stop or runtime cap): `CancelledError` is not caught by
  `_governed`, so the wrapper never settles the operation, even though the shielded hop lands its
  ledger later.
- Verified by reading the code. The buffering is inherited; footprint jobs make the window large.
- Confidence: high on the mechanism.

### 6. MINOR: Exa inside find_podcasts and find_videos can sink the whole job and latch the wrong label
- Files: `footprint_operations.py:301-315` (catches only `ProviderTransportError`/`RawParseError`);
  `footprint_operations.py:347-354` (find_videos' Exa fallback has no error handling at all).
- What is wrong:
  - Exa's `exa_halt_rule` raises `ProviderHalted` on a 402 or 403. Inside find_podcasts that error
    is not caught, so the whole job fails and the Apple and Podcast Index results are thrown away.
  - `_dispatch` then latches the label `podcast_index`, so every later find_podcasts in the job is
    refused, although Apple and Podcast Index are free. find_videos latches `youtube_data` the same
    way.
  - In the other direction, an Exa latch set earlier by search_web does not stop these jobs from
    calling Exa. The pre-dispatch check reads only the tool label.
  - A transport or parse error in the find_videos Exa fallback becomes `tool_error` and is saved as
    `failed` (see finding 1).
- Confidence: high, from reading the code.

### 7. MINOR: two identical calls in one round tell the agent to "record the gap" for a call that succeeds
- File: `quality_provider_tools.py:200-234`.
- What is wrong: the second call loses `begin` while the first is still `running`. It gets
  `outcome_unknown` with no `result_path`. `runtime.operate` added a per-request lock for exactly
  this case (run 7), but the footprint jobs call `call_provider` directly and the wrapper has no
  lock. This is a different root cause from the known parallel-call deadlock.
- Confidence: high.

### 8. MINOR: argument variants hash differently and are paid again
- Files: `footprint_operations.py:119-152`; `quality_provider_tools.py:178-180` (raw `arguments`
  hashed).
- What is wrong: the job descriptions invite `"@davegerhardt"` as well as `"davegerhardt"`. Other
  variants also hash differently:
  - `"company": null` versus the key left out;
  - duplicated `queries` (deduplicated inside the job, but not in the hash);
  - a LinkedIn URL with or without `?miniProfileUrn=`.

  Each variant buys again: $0.28 for PDL, or a whole history fetch. Hashing the validated,
  normalised model would avoid this.
- Confidence: high.

### 9. MINOR: the saved file does not open with the overview
- File: `footprint_operations.py:321-323` and 358-360.
- What is wrong: the comments say alphabetical key order keeps `overview` first. The verified order
  is `gaps, n_results, overview, report, state, videos`. `gaps` holds one line per failed search
  per source, so it can push the overview well down. Meanwhile the receipt says "Read the overview
  at the top of result_path".
- Confidence: high (`empty_vs_fail.py`).

### 10. MINOR: a replayed receipt loses its preview and turns "empty" into "completed"
- File: `quality_provider_tools.py:212-225`.
- What is wrong: the replay builds a v1 `AcquireResearchReceipt`. A resumed turn that re-issues an
  originally empty search sees `completed` with no preview. This is inherited from v2, but the
  crash path in finding 5 makes it more likely.

### 11. MINOR: .env.example has no CLUE_PDL_API_KEY line, and its comment's reason is wrong
- File: `.env.example:860-863`.
- What is wrong: the parity rule asks for a line. The comment says an empty value would shadow
  `PDL_API_KEY`, but `Secrets` has `env_ignore_empty=True`. Verified: `CLUE_PDL_API_KEY=` plus
  `PDL_API_KEY=real` resolves to `'real'`. The line can be added.

### 12. MINOR: shared result files plus job-wide derivation edges cause erasures across jobs
- File: `quality_provider_tools.py:306-346`.
- What is wrong: identical bodies are one content-addressed artifact per workspace, for example
  `{"gap":"treg_key_missing","state":"unavailable"}`, an empty not_found history, or an empty
  find_handles. Each job adds derivation edges from all of its own originals to that shared
  artifact. Erasing any one original in any job privacy-erases the shared artifact through the
  trigger. That job's operation result then becomes unreadable in unrelated jobs. The pattern is
  inherited; v3 adds many such identical bodies. No data leaks; this is collateral unreadability.

### 13. MINOR: the agent-facing tool description is still the v1/v2 text
- File: `quality_provider_tools.py:546-551`.
- What is wrong: v3 inherits the description that names only "company, people, web, ATS and media
  providers". It does not mention the social, podcast and video jobs. It also still says "status
  empty means nothing came back", which finding 1 shows is untrue for these jobs. The schema
  fingerprints are unaffected.

### 14. MINOR: the tests use mocks where the failure mapping matters
- What is missing: `test_acquire_v3.py` builds results with a fake `call_provider` and checks only
  the success shape. No test sends a `not_found`, `private`, `unavailable`, `partial` or outage
  result through `AcquireResearchToolV3.invoke` to pin the receipt's status and error code. The
  erasure test gap is covered in finding 3.

## Checked and fine
- Profile pins for `acquire_research_evidence@3` in v42 and v31-person
  (input `b6169af8…`, output `1cbfa188…`) match the live descriptors I computed. v1 and v2 are
  unchanged, and v2/v3 share the output schema.
- Every resource hash in `launch-v4-r43.json` and `launch-v4-r44.json` matches its file. Recipe 44
  is recipe 43 plus the two requirement pins (tested).
- No r44 resource mentions `discover_media`. CURRENT_RECIPE_VERSION is 44, and the profile choice
  for 43/44 is v42 / v31-person.
- The operation id is a uuid5 over workspace, job, kind and sha256 of `sort_keys` JSON. There is no
  key-ordering non-determinism and no collision between different requests. The result view is
  scoped by workspace, job, run, account and `kind LIKE 'quality_tool:%'`, with no cross-job or
  cross-workspace read. Previews come only from the job's own body.
- A crash or replay never re-dispatches a provider: a lost `begin` always returns a replay or
  `outcome_unknown`.
- `X-Treg-Token` is added to `SECRET_HEADERS`. Keys are `SecretStr`, and `_present()` filters empty
  values. The PDL key goes in a header, not the URL.
- `clue_api.footprint` imports nothing from arv2: the AST test, the import-linter contract, and no
  relative imports. The old paths are module-identical shims.
- Settings load from their env strings: the page-guide Literal includes v3/v4, and the ints have
  bounds. Every new setting and secret except `CLUE_PDL_API_KEY` is in .env.example.
- Short-link opening is limited to `t.co`/`lnkd.in` by a regex, so no SSRF surface.
- The argument models forbid extra keys. Every job has descriptions and examples, and the examples
  validate (tested).
