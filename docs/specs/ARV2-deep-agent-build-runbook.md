# ARV2 — Deep-agent build runbook: critical re-evaluation, line-by-line execution, day-one deliverables

**Status:** review document for the founders, 2026-08-23. Supersedes the *phasing* of
`ARV2-account-research-rebuild-plan.md` (whose provider verdict and keep/drop treaty stand).
Companions: `ARV2-schema-impact-audit.md` (proof of zero schema change + the claim-stamping
matrix), `ARV2-apollo-api-contract.md` (the Apollo wire-schema deep dive and the repo's mix-up).

---

## 1. Critical re-evaluation — what was wrong with the v1 plan

Putting the critical-engineer hat on my own proposal, six revisions:

1. **It front-loaded program strategy and back-loaded the agent.** The founder's requirement is a
   working deep agent *now*. The critical path is exactly four artifacts: a catalog bundle
   (prompt/profile/skills), ~9 tool wrappers, a v2 job driver, and a launcher — everything else is
   optional the first week. **Revised: Day-1 builds the agent Exa-only** (Exa + OpenRouter keys
   already exist in the env; Apollo needs a purchase that no code should wait on), **Day-2/3 adds
   Apollo** when the key lands.
2. **"Retire the ~20 judgment gates" was wasted scope.** Editing the old lane means moving frozen
   descriptor SHAs, aggregate digests, and R10 pinned tests for code we are abandoning. **Revised:
   the build touches zero old-lane files.** The gates die with the lane at the separately-ratified
   Phase-6 cleanup. The only "removal" ARV2 performs is *not importing* that machinery.
3. **The ICP-compiled qualifier-field mechanism was premature invention.** A registered static
   dossier pack (data rows, §5 of the schema audit) delivers dossier depth today; a Stage-0
   compiler for client-specific fields is a later product feature, not a build dependency.
4. **Melissa and the C7 governance change were noise on the critical path.** `/frontend/v1`
   already serves UNVERIFIED claims (it filters only REJECTED), and the C7 research-view surface
   has no consumer. **Revised: both dropped from build scope**, kept in the backlog (Melissa
   belongs to the direct-mail *export* epic, which doesn't exist yet).
5. **The v1 plan under-specified the write path — which is precisely where "mechanical failures"
   would have reappeared** as raw `IntegrityError`s from the claim table's ~14 CHECKs/triggers
   (tier4⟺llm_synthesis, facet governance, reuse-scope⟺workspace, per-source-key lineage CHECKs).
   **Revised:** the normative stamping matrix now exists (schema audit §3), the `write_claims`
   tool pre-checks every rule and refuses actionably, and a DB constraint firing at runtime is
   defined as an ARV2 bug with a red-proof test per constraint.
6. **The v1 plan was ambiguous about which durable layer v2 reuses.** Now explicit (schema audit
   §4): reuse fleet/lease + `entity_research_run/job/…/finalization` + the R3 turn journal +
   checkpointer + `external_research` snapshots + artifact + claim; **do not touch** the R4/R5
   authority/settlement tables — the layer whose job-scoped folds and checkpoint-replayed poison
   calls produced every live wedge in the Grok forensics. Aryan's "same durability schema"
   requirement is satisfied: those are exactly the tables the design subsystem also rides.

One more honesty item: **"today" means the Exa-only account agent driving end-to-end on one real
account.** Apollo committee flow is Day-2/3 (key procurement + webhook receiver), the per-contact
deep agent is Day-3/5. Anyone promising the full pipeline in one day is selling something.

---

## 2. What exactly happens at runtime — job by job, line by line

Everything below names the real module/table at each step. New code is marked **[NEW]**; everything
else exists today and is reused unmodified.

### Job 0 — Launch

1. Entry (Day-1): a driver script / API route **[NEW `platform/api/clue_api/arv2/launcher.py`]**
   takes `(workspace_id, project_id, account_ids[], directive_text)`. (Day-3: the same launcher is
   invoked from a Head-of-ABM tool so launch returns to chat; the human-approval gate is the
   existing selection/launch authority pattern.)
2. Launcher loads the `account_entity` rows (workspace-scoped, fail-closed — existing readers).
3. For the cohort it writes one `entity_research_run` row and per account one `entity_research_job`
   row via the existing `DbEntityResearchJobStore.begin/…` family, with an authorization pinning
   `agent-profile:arv2-account:v1` + its sha256 (the existing profile-fence mechanism, pointed at
   the **[NEW]** catalog).
4. One `fleet_task(kind=ENTITY_RESEARCH_JOB)` per job is enqueued. **No new tables, no new task
   kinds.**

### Job 1 — Worker pickup (unchanged fleet shell)

5. `LeasedWorkWorker` leases the task (existing heartbeat/generation fencing).
6. `EntityResearchJobWorkHandler` admits under per-run concurrency and calls the injected driver —
   composition selects **[NEW `Arv2JobDriver`]** when `arv2_account_research_enabled=true`;
   with the flag off, nothing anywhere changes. The old lane's driver keeps handling old-lane jobs;
   the two never share a job row.
7. The driver resolves the ARV2 definition **[NEW `definition.py`]**: loads the catalog folder
   (`platform/agents/catalog/entity-research/arv2-account/v1/`), verifies the profile sha against
   the job authorization (existing mechanism), and builds the tool list.
8. `EntityResearchAgentFactory` (existing R3) constructs the LangGraph agent —
   `create_agent(model, tools, response_format=finalization proposal, checkpointer=AsyncPostgresSaver)`
   — and every turn journals to `entity_research_agent_turn` / `_agent_event` (existing tables).

### Job 2 — The account research loop (the agent's tools, call by call)

Each tool is a thin wrapper **[NEW `platform/api/clue_api/arv2/tools.py`]**; provider transports
live in **[NEW `exa_client.py`, `apollo_client.py`]** (httpx via the existing shared wrapper;
credentials via the existing `Secrets.for_auth_ref`).

| # | Tool call | What happens, exactly |
|---|---|---|
| 1 | `read_research_state()` | SELECT current claims for this account (existing readers, explicit relaxed merge policy) + the registered dossier-pack fields **with their registry descriptions**. Returns a known/missing table. No writes. |
| 2 | `search_web(query, n)` | Exa `POST /search` (`type=auto\|fast`). Response persisted: raw JSON → `artifact` (B2 storage) + `external_research_operation/_snapshot` rows (existing family, idempotent on the request digest). Returns title/url/snippet list. |
| 3 | `fetch_page(url)` | Exa `/contents` for that URL; artifact-captured the same way; returns the page text — this is where verbatim quotes come from. |
| 4 | `research_deep(subject, intent, output_schema?)` | Exa `POST /search` `type=deep-reasoning`, `systemPrompt` from the skill, optional `outputSchema`. Snapshot persisted; returns the synthesized `output` + the `grounding` citations array. Freeform `intent` — no 1000-char cap, no bundling compiler. |
| 5 | `apollo_org(domain)` *(Day-2)* | `GET https://api.apollo.io/api/v1/organizations/enrich?domain=…`, header `x-api-key` (per the corrected contract — the repo resolver's URL/auth/response assumptions are wrong; see the Apollo doc). Snapshot persisted; returns the normalized skeleton (headcount, revenue, tech, funding events, hierarchy). The **agent** decides which values become claims. |
| 6 | `apollo_people(titles?, seniorities?)` *(Day-2)* | Apollo people search at this org (0 credits, no contact info returned). Returns the candidate skeleton for the committee. |
| 7 | `apollo_contact(person)` *(Day-2/3)* | `POST /people/match` with `reveal_personal_emails`; email is synchronous. Phone reveal needs the async webhook (+8 credits) — **[NEW webhook route]**, Day-3, email-only until then. |
| 8 | `lookup_registry("npi", query)` | The existing registries transport (public, no auth) — NPI first; identity anchors the dossiers cite constantly. |
| 9 | `write_claims(items[])` | Per item: resolve `FieldDef` → validate value against `value_schema` → apply the stamping matrix (schema audit §3) → `insert_claim` (the existing sole writer) → `record_run_lineage` (**mandatory** — this is what makes the claim visible in the frontend's project sections) → `stamp_reuse`. Any violation returns per-item `{field, violation, corrective_shape}` as tool content. **Never raises.** |
| 10 | `write_contacts(members[])` | Creates/links `contact_entity` rows via the existing workspace-scoped identity writers, then committee claims (persona, role, rationale-as-evidence). Used only after the agent's identity-confirmation step (a primary source naming the person at this org) — confirmation upgrades `identity_binding` to STRONG. |
| 11 | `verify_links(urls[])` | Batch `/contents` fetch; per-link ok/broken/quote-mismatch; writes the `account.research_audit` annotation claim (the dossiers' "links opened 11 of 14, flagged 4" block, as data). |
| 12 | `finalize_research(summary)` | v2 finalization **[NEW, ~verifies bookkeeping only]**: no in-flight provider call for this job, cited claim ids exist, honest-empty fields listed. Writes the immutable `entity_research_job_finalization` receipt (existing table), emits the job event, and the fleet task completes. **No coverage ratios, no quality vetoes.** |

### Job 2a — The failure-species law, implemented in the driver (this is the actual rebuild)

- Every tool wraps *all* exceptions into a typed refusal rendered as a **tool message** — including
  on checkpoint resume: the driver replays a restored poison call through the same renderer, so the
  corrective guidance reaches the model instead of re-crashing (Grok root-cause #2, fixed by
  construction).
- An exception the driver cannot type pauses the job **resumable with the reason recorded**
  (`entity_research_job_event`) — never a `worker_error` death.
- The recursion/tool-cap budget does not raise: at the cap the driver injects one final
  "finalize now with honest coverage" turn.
- Paid-call idempotency is digest-keyed on the run via the `external_research` family, so a
  replayed job **joins** settled work instead of waiting on another job's settlement forever
  (Grok root-cause #1, structurally avoided because the R5 fold machinery isn't on this path).
- One model per job; a model change relaunches, never resumes (encrypted-reasoning lesson).

### Job 3 — Committee (Day-2/3)

`apollo_people` skeleton → for each candidate the agent runs the confirmation step
(`fetch_page` on the org's team page / `lookup_registry` NPI) → `write_contacts` + committee
claims → optional `apollo_contact` for email. A provider having no such org/person is an **honest
terminal outcome** the agent writes down and moves past — never a job death (the branch has been
converging on exactly this rule one live crash at a time, e.g. commit `c5f41bcd`; ARV2 makes it
the design default rather than a per-crash patch).

### Job 4 — Contact deep research (Day-3/5)

Same driver, contact definition **[NEW catalog `arv2-contact/v1`]**, tool set = 2/3/4/8/9/11/12 +
`apollo_contact`; subject = one contact. Produces the career/education/publications/personal-hook
facet claims per the stamping matrix (facets carry binding + use_class; sensitive categories are
recorded but excluded from outreach by the existing hard floor).

### Job 5 — Serving (zero work)

Claims appear on the accounts screens through the existing reads: `neutralFacts` +
`projectSections[].insights` (via the `run_lineage` rows written in step 9), the committee panel,
and contact `professionalFacts`. No frontend change, no new endpoint. Prose (`account.summary`)
via the existing Lane-E synthesizer is a Day-5+ nicety, not a dependency.

---

## 3. Deliverables checklist — "to create this deep agent today, what is needed"

**From the founders (blocking, in order):**
1. Ratify: this runbook + the schema audit (esp. §4 dormant-tables trade-off) + base branch =
   `platform/comprehensive-account-contact-research`.
2. Confirm the research model id (one model; `CLUE_ARV2_MODEL`).
3. Running stack: Postgres 5432 + Redis + the branch worktree (the 2026-08-22 memory note is the
   runbook). Existing keys: `CLUE_EXA_API_KEY`, `CLUE_OPENROUTER_API_KEY`.
4. Purchase Apollo (API-enabled tier; confirm master-key + export credits with sales) —
   unblocks Day-2, not Day-1. Sumble cancellation only *after* the committee flow is proven.

**Code (Day-1 scope, ~14 files, all new except two data edits):**
- Catalog `platform/agents/catalog/entity-research/arv2-account/v1/`:
  `profile.md`, `prompt.md`, `skill-dossier.md` (the Insight-Health method), `skill-audit.md`,
  `manual.md` (refusal→reaction table for the v2 surface).
- `platform/agents/clue_agents/arv2/` **[NEW]**: `definition.py`, `driver.py` (failure-species
  law lives here).
- `platform/api/clue_api/arv2/` **[NEW]**: `tools.py`, `write_claims.py`, `exa_client.py`,
  `launcher.py`, `composition.py` (flag-gated wiring into `fleet_main`).
- `subsystems/research/clue_research/claimstore/arv2_pack.py` **[NEW]** (registry rows) +
  `sources/seeds.py` (+2 entries — the one frozen-fixture drift, documented in schema audit §6).
- Settings: `arv2_account_research_enabled=False` + model field; `.env.example` lines.
- Tests per schema audit §7.

**Day-1 exit gate (the definition of "the deep agent exists"):** on the live stack, launch one job
for Digestive Healthcare of Georgia (account entity created by domain), the agent runs
Exa-only, ≥15 claims land with verbatim quotes + source URLs across ≥5 dossier sections, the
audit claim reports its link check, the finalization receipt is written, and the account detail
screen renders the new facts. `make check` green; alembic head unchanged.

**Day-2/3:** Apollo client + `apollo_org`/`apollo_people`/`write_contacts` + committee exit gate
(Eagle Physicians committee on-screen). **Day-3/5:** contact agent + `apollo_contact` email +
webhook receiver for phones; contact-profile exit gate.

---

## 4. Risk register (what bites first, honestly)

1. **Apollo data thinness on small/local orgs** (LinkedIn-centric): mitigated by design — Apollo
   is skeleton-only, the agent confirms against primary sources before writing; a miss is an
   honest gap plus web fallback.
2. **The dormant-governance trade-off** (schema audit §4): v2 has no per-call authority journal.
   Accepted deliberately for the pilot; the compensating controls are turn journaling, snapshot
   idempotency, and spend recording. Revisit before multi-tenant production.
3. **Model discipline without judgment gates**: nothing mechanical stops a lazy dossier. The
   controls are the skill + manual (which the live runs showed the model follows), the audit
   skill, and the human reviewing output — by design ("engine disposes, never quizzes").
4. **Frozen-fixture drift** beyond the one documented seed test — if any other frozen test moves,
   that is scope leaking into the old lane; stop and re-check the quarantine boundary.
5. **Apollo contract residuals** — the corrected contract is doc-verified but not yet
   fixture-verified against a live key; Day-2 starts by recording real fixtures before any claim
   writes (the repo's own locked decision #3 pattern).
