# ARV2 MASTER PLAN — the complete roadmap for account research, contact research, and their display

> **Factual visibility, 2026-09-22 — founder-adopted policy; implementation and activation pending.**
> For the next research-quality profile, retain authorized, policy-permitted invalid observations
> for audit while excluding them from ordinary factual summaries. Unresolved findings remain visible
> as uncertainty; valid partial research can still render. This narrowly revises §2's annotation-only
> presentation rule when that profile is implemented and activated. It does not require dropping
> observations, relax privacy/use restrictions, introduce monetary vetoes, or alter current/historical
> profile behavior today. The founder approved this policy, not application implementation or every
> remaining frontend/schema choice. See the [quality spec §1.2](../superpowers/specs/archive/2026-09-22-arv3-research-quality-design.md#12-policy-decisions-and-proposed-contract-changes)
> and [implementation plan](../superpowers/plans/2026-09-22-arv3-research-quality.md).

> **Committee discovery, 2026-09-22 — implemented; v2 default by founder instruction.** The v2 account
> agent researches the company, reasons about buying responsibilities from its ICP and pinned
> persona, then discovers unknown people through company-scoped AI Ark SMART title search.
> This supersedes §3's name-scoped-only rule and R2/R3's web-first committee sequence **for v2**.
> Selected profiles seed the existing person jobs; work-email and phone enrichment run alongside
> person depth without another named search. Exhausted account Exa failure leaves a gap and
> permits discovery. Web research fills gaps and corroborates profiles. Provider facts cite
> saved artifacts/JSON paths; committee responsibility is the agent's separate assessment.
> v1 resources remain intact for historical jobs. `CLUE_ARV2_RESEARCH_CATALOG_VERSION=v2` is now
> the default for new launches. The Probook/Zafran live canary remains outstanding; no live
> acceptance or deployment is implied by this default change. R4 account discovery, media,
> model settings and general-purpose `web_search@1` are unchanged. See the
> [design](../superpowers/specs/archive/2026-09-22-arv2-ai-ark-committee-discovery-design.md),
> [implementation plan](../superpowers/plans/2026-09-22-arv2-ai-ark-committee-discovery.md) and
> [acceptance record](../superpowers/plans/2026-09-22-arv2-ai-ark-committee-acceptance.md).

> **Scoped-field follow-up, 2026-09-16 (planning only).** The founder requested a detailed plan to
> make agent-proposed research definitions workspace-local. The current lenient writer still
> registers unknown definitions globally while keeping their claims private. The
> [implementation plan](../superpowers/plans/2026-09-16-workspace-agent-proposed-fields.md) covers
> trusted registration, historical vocabulary containment and versioned deepagent/research
> documentation. [Prepared agent guidance](../agents/research-field-scope.md) must activate with
> the backend change. This amendment does not assert that the change is shipped or relax current
> retirement, erasure, subject or privacy constraints under the “lenient” rule below.

**This is the single authoritative plan. Version 1.6, 2026-09-07 (v1.6: the product-catalog child doc `ARV2-PRODUCT-CATALOG-CONTRACT.md` — Exa request shape, `ProductCatalogResearch@1` artifact, and rulings P1–P4: a project targets a **set** of products, versioned, one ICP per project over the whole set; v1.5: Aryan's rulings recorded — §8 R1–R13, §12 D1–D8 and D10–D13, data-source rulings S1–S12 with S10 = read-time relaxation; v1.4: data-source map child doc, `display_section_recipe` name, D13; v1.1: lenient write gate, checks as flag-controlled annotations, human-stated facts need no URL, all fields optional; v1.2: the interview never requires word-for-word recording; v1.3: contract v1 re-based on the 5 Sep frontend `live-backend-v1` @ `84f8ee7` — clause-level citation segments, research excerpts, actor-based activity, account artifacts, owner/creator, nullable fit score — and the D0 rulings reduced to what remains). Both founders ratify by initialing
§12.** It consolidates every decision taken so far into one present-tense document. The earlier
documents in `docs/specs/ARV2-*.md` remain as the audit trail; where they differ from this one, this
one wins. There is no history in this document, only what we are building and how.

**Roles.** *Aryan* — tech founder: platform deepagent, onboarding, brand context, ICP, project
context, Exa MCP tool, and the four backend integration points named in §9. *Shashank* — co-founder
(non-technical, works through coding agents): research specs and answer keys, frontend specs and the
dummy frontend, section recipes and display prompts, the accounts integration lane.

---

## 1. What we are building (the one-paragraph version)

A research lane that turns a confirmed ICP into deeply researched target accounts and buying
committees — every fact a typed claim with a verbatim quote and a source URL, or an honest empty —
and a display layer that turns those claims into the pages a marketer reads (account overview,
insights, contact pages), with a source chip on every sentence and copy the marketer can paste. The
research is done by one real agent per account and per person using Exa, AI Ark, free job-board APIs
and Gemini for media, with no mechanical quality gates, no secondary-LLM judges, and no waterfall.
The pages are written once by a small display model, persisted, and regenerated only when the
underlying claims change. One frontend (the monorepo's `apps/frontend`), one backend (the monorepo),
one design source of truth (the dummy frontend, lifted screen by screen).

## 2. Principles that govern every task (non-negotiable)

0. **ARV2's own rows are the only truth; the old research lane is deleted, never bridged.**
   (Founder ruling, 2026-09-09.) No read, no write and no schema on the ARV2 path may reach for an
   `entity_research_*`, `research_view_*`, `account_run` or `icp_spec` row — not as a fallback, not
   as a compatibility shim, not "until the ARV2 writer lands". If ARV2 has no row for something, the
   honest answer is the empty one. Enforced by `tests/api/test_frontend_read_arv2_only_guard.py`
   (empty allowlist since D4-b) and `tests/arv2/test_import_guard.py`; the lane's own tables and
   code are inventoried for deletion in `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`.

1. **A claim needs a quote and a URL or it is not written.** Empty is a correct output; fabrication
   is the only failure. Conflicts between sources are recorded, never smoothed.
2. **Exactly two gates exist, plus one floor — and no mechanical blocker ever stops information from
   being stored.** (a) The claim write gate is a *shape* gate run in **lenient mode by default**
   (`CLUE_CLAIM_WRITE_LENIENT=true`): it stamps what the agent did not say (tier from the tool of
   origin, facet defaults, reuse scope) and stores the claim; a value that misses the field's schema
   is stored with `schema_valid=false`; an unregistered key is stored and auto-registered as a
   proposed field; a research claim with no source URL is stored with a `source_missing` marker.
   **A fact the user states in chat is written with `extraction_method=human`, its provenance is the
   conversation turn, and no URL is ever asked for.** The interview does **not** require the user's
   words to be recorded character-for-character: the agent may write the fact in its own words, the
   user's statement is attached as best-effort evidence when available, and the value is never
   required to be a substring of that statement (`CLUE_INTERVIEW_ENTAILMENT_CHECK=off` by default).
   Nothing on the Head-of-ABM path ever refuses a store for an evidence-shape reason. Strict
   refusals exist only when the flags are turned off. (b) Human authority: product selection, ICP confirmation, cohort approval, launch,
   contact selection. The floor: `outreach_safe=false` claims never reach outreach copy;
   special-category personal data (health, faith, politics, sexuality, family tragedy, minors) is
   redacted, never used. Everything else — coverage ratios, confidence thresholds, corroboration,
   faithfulness judges, verbatim checks, canary suspensions, budget vetoes — does not exist as a
   blocker in this lane. Judgment annotates; it never vetoes.
3. **Money truth still blocks; money caps only record.** A 4xx or unknown-spend state stops the
   call; a budget ceiling is recorded and surfaced, never enforced mechanically on the pilot.
4. **Free primary sources first, always.** Job-board APIs, RSS feeds, and the target's own site
   before any paid call. A known URL is fetched, never searched for.
5. **The claim store is the only seam.** Research writes claims; the display layer and the frontend
   read claims; nothing passes between them any other way. Research never reads chat history.
6. **Quality checks are annotations, flag-controlled, off by default, and never block a store or a
   page.** Verbatim-quote checking (`CLUE_EVIDENCE_VERBATIM_CHECK=off`), the unevidenced-row purge
   (`CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false`), and the interview's text-entailment rule
   (`CLUE_INTERVIEW_ENTAILMENT_CHECK=off`) only ever record a marker on the claim when turned on.
   The one check that runs by default is the sensitivity floor
   (`CLUE_SENSITIVITY_FLOOR_ENABLED=true`): it redacts references to minors from a value and marks
   origin/faith/health-type facts `outreach_safe=false`; it never drops a claim. v1 is operational
   first; verification is a later version, and when it comes it is fuzzy (token overlap), not
   exact-match.
7. **The dummy frontend is presentation truth.** No component is invented while wiring; screens are
   re-lifted from the dummy, never patched in place; data with no designed slot goes unserved.
8. **Every configuration flag appears in `.env.example` with its value in the same commit that
   introduces or changes it.** No env-only switches.
9. **Contracts are written down.** Every resolved backend/frontend decision lands in
   `apps/frontend/docs/api-contracts/*.md` before code depends on it.
10. **Agents never merge.** Task branches only; the tech founder reviews and merges at the
    integration points; nothing is pushed without review.

## 3. The stack (decided)

| Job | Provider / mechanism | Rules |
|---|---|---|
| Account discovery | Exa search (signal-first job-req queries as the primary angle) + free ATS boards; optional AI Ark company search as a cheap skeleton | `includeDomains` is a measured per-angle choice, never a default |
| Structured company + people data, emails, phones | **AI Ark** (the database) | `X-TOKEN` + browser User-Agent + `Accept: application/json`; ≥10.5 s between calls until a paid tier is confirmed; halt on 402/403/"credit"; **name-scoped people lookups only** (`fullName` STRICT variants + domain, size ≤3; the domain roster is a trap); email at `email.output[0].address` with `status/domainType/subStatus/mx.*` → `verified_smtp` / `catch_all_valid` / `not_found`; credits by result-count arithmetic (no balance endpoint); `birth_date` scrubbed inside the client before any persistence |
| Page fetch | Exa `/contents` (indexed copy) → Scrapling only on a real block | Firecrawl is not part of research |
| Deep research | Exa `/search` `type=deep-reasoning`, one call per subject | `systemPrompt` = target lock + same-name exclusions; `query` = the charter; `numResults 20`; `contents.text 10000 + highlights`; `outputSchema` with exactly one string property `report`; **silent-fail guard in the tool**: `len(text) < 3000 or (results ≤ 9 and cost ≤ $0.016)` → retry once |
| Job postings, RSS, own site | Ashby / Greenhouse / Lever public APIs (slug fallback list; read `descriptionPlain`, `publishedAt`, `isListed`, compensation), podcast RSS (exact episode-number match), the target's own pages | Free; these decide rankings more often than paid calls |
| Media (podcasts, videos) | Gemini: `gemini-3.5-flash-lite` for short items where timestamps matter; `gemini-3.5-transcribe` for anything long (Files API upload; text at `parts[].audioTranscription.text`, no timestamps); `gemini-embedding-2` (768-dim) on transcript **text** only | Duplicate-line loop detector on every transcript; every quote verified as an exact substring of the faithful transcript; pull the MP3 from RSS rather than YouTube (3.6× cheaper); YouTube's caption endpoint is dead, Exa `/contents` on a watch URL gives the words; never fetch LinkedIn- or X-native video; verify who speaks before quoting |
| Structuring prose → claims | OpenRouter `openai/gpt-5-mini`, reasoning `minimal`, JSON mode, **one subject per call** | The field catalog is the model's menu; an unregistered key is stored and auto-registered as a proposed field (lenient mode), never refused; deterministic provider facts are assembled in code with `source_field_path`, never sent through the model |
| Display copy | OpenRouter `openai/gpt-5.6-luna`, default reasoning effort, one call per page section, sections in parallel | See §7 |
| Apollo | Not built. Fallback only, if ever needed | — |
| Sumble, Melissa, the M4 waterfall, memory subsystem, Stage-0 recon | Off (see §11) | — |

Per-account cost, measured: full recipe ≈ $0.17 + 12 AI Ark credits (trimmed ≈ $0.07 + 4 credits);
per person ≈ $0.07–0.13; display copy ≈ $0.05 per account with five contacts.

## 4. Data model additions (one migration, done first)

- `claim.signal_priority smallint NOT NULL DEFAULT 3 CHECK (1..3)` — P1 active buying intent, P2
  qualifying facts, P3 context. Stamped at write time by the structuring pass.
- `claim.outreach_safe boolean NOT NULL DEFAULT true` — the appropriateness flag, distinct from
  accuracy. One fact, one flag: near-duplicate rows are deduped before they reach the display layer.
- `display_block` table: `(workspace_id, subject_kind account|contact, subject_id, page, section_key,
  body_json, cited_claim_ids[], model, prompt_version, generated_at, superseded_at)`.
- Section recipes as config rows in a table named **`display_section_recipe`** (not `recipe` — that
  name is already taken by Stage-0 execution recipes): `(page, section_key, h1, position,
  allowed_field_keys[], restricted, default_open, instruction_version, workspace_id NULL = system row)`.
- **`provider_call_ledger`** (D1 addition, 2026-09-07): one row per provider call **phase**
  (`estimate` before the wire, `result` after): `(ledger_id uuid PK, call_id uuid NOT NULL,
  workspace_id text NULL, project_id text NULL, project_run_id text NULL,
  entity_research_job_id uuid NULL, provider text NOT NULL, operation text NOT NULL, label text
  NOT NULL, phase text NOT NULL CHECK (phase IN ('estimate','result')), http_status int NULL,
  latency_ms int NULL, attempts int NOT NULL DEFAULT 0, estimate_usd numeric(12,6) NOT NULL
  DEFAULT 0, estimate_credits numeric(12,3) NOT NULL DEFAULT 0, estimate_media_seconds int NOT
  NULL DEFAULT 0, cost_usd numeric(12,6) NULL, credits numeric(12,3) NULL, media_seconds int NULL,
  over_ceiling boolean NOT NULL DEFAULT false, outcome text NOT NULL CHECK (outcome IN
  ('estimate','ok','client_error','retry_exhausted','halted','transport_error')), error_code text
  NULL, provider_request_id text NULL, request_artifact_key text NULL, response_artifact_key text
  NULL, recorded_at timestamptz NOT NULL DEFAULT now())`, indexes on `(workspace_id,
  recorded_at)` and `(call_id)`. Raw request and response bodies are `artifact` rows written
  through `record_artifact` with `source_key = 'arv2:<provider>:<operation>'`; the ledger row
  references their keys. R1 ships the wrapper and the file/memory sinks; the table and the
  artifact-backed sink land with D1/A7.
- **`claim.write_markers jsonb NULL`** (D1 addition, 2026-09-07): the markers' home. The write-time
  annotations named in this section (`schema_valid`, `source_missing`, `evidence_verbatim`,
  `unevidenced`, `entailment`, plus the writer's own `proposed_field`,
  `identity_binding_defaulted`, `use_class_defaulted`, `pipe_joined_key`) are one jsonb object
  written at insert. NULL means nothing to note. They are write-time annotations, not provenance,
  so they sit outside the append-only immutable-column guard.
- **A claim may exist without a source URL** (D1 addition, 2026-09-07). A claim whose
  `extraction_method` is `api`, `scrape` or `llm_synthesis` and whose `source_url` is NULL is
  constructible and storable, marked `source_missing`. Promotion, not construction, requires the
  URL: `can_be_promoted` returns `False` for such a row, so it is stored honestly and never served
  as verified truth.
- No visit table: "new since your last visit" is computed by the frontend from
  `ResearchEvidence.verifiedAt` against a locally stored last-visit stamp (decision D5 resolved).
- Other per-claim extras from the research runs (`claim_kind`, `media_url`, `media_timestamp`,
  `source_type`, `charter_category`, `source_field_path`, per-claim cost) ride `value_json`
  sub-fields and the existing provenance/lineage refs; no schema for them in v1.
- **What a claim row needs to exist (the true minimum):** `entity_id` + `entity_type`, `field_key`,
  `value_json`, `extraction_method` (`human` / `api` / `scrape` / `llm_synthesis` / `crm_import`),
  `source_tier` (stamped from the method), `run_id` + `research_mode` (lineage — what makes it
  visible on the project's pages), `workspace_id`, `confidence` (defaulted). **Optional:**
  `source_url`, `evidence_span`, `observed_at`, `source_key`, artifact/snapshot refs,
  `identity_binding`, `use_class`, `product_id`, `signal_priority` (defaults to 3),
  `outreach_safe` (defaults to true). Two database rules are satisfied by **stamped defaults, never
  by refusal**: a `contact.facet.*` claim gets `identity_binding=WEAK` + `use_class=professional-public`
  when the writer did not say; tier 4 ⟺ `llm_synthesis` is stamped from the tool of origin.
- **Leniency and check flags (all in `.env.example`):** `CLUE_CLAIM_WRITE_LENIENT=true` ·
  `CLUE_EVIDENCE_VERBATIM_CHECK=off` · `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false` ·
  `CLUE_INTERVIEW_ENTAILMENT_CHECK=off` · `CLUE_SENSITIVITY_FLOOR_ENABLED=true`. When a check is
  on, it records a marker on the claim (`schema_valid`, `source_missing`, `evidence_verbatim`,
  `unevidenced`, `entailment`); it never refuses a write.
- **Every field is optional.** The claim store is sparse: a field exists only when a claim for it was
  written; a missing field is absent, listed under `coverage.unresolvedFieldKeys`, and blocks
  nothing. Inside a field's own value schema every sub-field is optional except the one that
  identifies an item.
- **New registered fields (data rows, no code):** account — `account.open_requisitions` (list of
  `{title, dept, published, days_open, salary_band, still_listed, url}`), `account.gtm_tooling_stack`
  with an explicit `absent[]` array, `account.named_customers`, `account.reputation_risk` (born
  `outreach_safe=false`), `account.abm_program_maturity`, `core.legal_name`, `core.founded_year`;
  contact — `contact.facet.hooks`, `.openers`, `.voice_quote` (`media_url` + `timestamp`),
  `.certifications`, `.education_highschool`, `.self_summary`, `.excluded_lookalike`; source type
  `university_athletics`. `Persona` gains `user`. The Zafran answer key maps its two out-of-vocabulary
  values onto it: `executive_sponsor` → `economic_buyer` and `adjacent_buyer` → `user`.
  `use_class` uses the platform enum only.

## 5. The two seams between the founders' workstreams

### 5.1 The launch contract (Head-of-ABM → research lane)
```
launch_account_research(workspace_id, project_id, account_ids[], icp_artifact_ref, directive_text)
```
- A human approves the cohort and the launch (the agent proposes and opens the gate).
- `directive_text` carries free text plus a small structured block: `effort: full|reduced|cheap-pass`
  and `committee_cap: int`.
- Accounts must already exist as `account_entity` rows (discovery/import owns entity creation).
- The ICP ref is pinned on the run; job identity is sha-pinned to the agent profile; a profile change
  relaunches, never resumes.
- The run also pins `product_selection_version` — the project's current product **set** at launch
  (ruling P1/P2, `ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.4). A later set version never touches a
  running or finished run; nothing is re-researched automatically.
- Reverse edge: project context reads only accounts-per-project (run lineage), research job state
  (`not_started / in_progress / needs_review / completed / suspended`), run/job finalization, and
  the claims. Never research internals.
- Failure semantics: cannot-compose refuses with a typed message; zero yield is an honest terminal
  outcome; nothing on the research side vetoes or reorders a launch.

### 5.2 The ICP artifact
One markdown document per confirmed ICP, agent-authored, human-confirmed, then frozen (a new
confirmation mints a new version). Front matter: `kind: icp-definition`, `icp_key`, `version`,
`brand_id`, `confirmed_by`, `confirmed_at`, `hard_gates[] {key, rule}` (pass/fail with a citable
test — e.g. stage, geography, hiring, intent), `exclusions[]`, **`persona_map`** (the single persona
vocabulary the research lane, the skills, and the frontend all speak: economic_buyer, champion,
user, technical_evaluator, blocker), `qualifier_fields[] {field_key, description}` (compiled into
the field catalog — the description *is* the research instruction), `product_selection_version` (the
project product set the ICP was written against — provenance only; a project has exactly **one**
ICP and it targets the **whole** set, never a subset: rulings P3/P4 in
`ARV2-PRODUCT-CATALOG-CONTRACT.md`). Body: the human-readable
definition in priority order, plus: TAM/list-math estimate and the widen | tier | shrink choice;
disqualifiers and red flags; closed-won/closed-lost patterns in the client's own words; the client's
own phrasing of who they sell to; the qualification-floor verdict. Stored in the durable artifact
store; materialized read-only into the deepagent's workspace via the project-context path.

## 6. Contract v1 — what the backend serves to the accounts screens

**Where each value comes from — endpoint, SQL, table.column or claim `field_key` — is specified
element by element in `docs/specs/ARV2-DATA-SOURCE-MAP.md`.** This section states the wire shapes
and the semantics; that document states the sources. The dummy frontend defines what data is
needed, never where it is read from; production reads Postgres rows, never files.

**Presentation truth:** the dummy frontend `clue-frontend`, branch `integration/live-backend-v1`,
commit `84f8ee7` (5 Sep 2026). Its Zod models in `src/features/accounts/model/*.ts` are the wire
shapes; its vendored `data/zafran/FRONTEND-SPEC-ZAFRAN.md` plus the fidelity tests
(`data/zafran/zafran-content-fidelity.test.ts`, `zafran-implementation.test.ts`) define what
"faithful to the research" means for the Zafran answer key. Contract v1 is recorded in
`apps/frontend/docs/api-contracts/accounts.md` and served on `/frontend/v1` (workspace-scoped),
with the frontend's repository adapters pointed at it.

**How to read the field lists:** `name?` = optional (may be absent); `name|null` or "(nullable)"
= present but may be `null`; `name[]` = a list (may be empty); `a|b|c` or `∈` = exactly one of
those values; everything not marked is required and non-null. "Served" means the backend computes
it and the frontend displays it unchanged. The five payloads:

- **Account list:** `id, name, logoPath, websiteUrl, researchStatus, researchStatusLabel?,
  researchIsRefreshing, overallFit (High|Medium|Low|null — nullable per ruling R7), fitScore (0–100 |
  null — never 0 for unknown), revenueBand, employeeBand, locationCount, locationsLabel?, owner (nullable),
  createdBy (nullable), industryLabels[], socials[], createdAt?, lastModifiedAt?, primaryProjectId,
  projects[], customFields[] {id,label,value,presentation,primary}` + `meta {total, nextCursor}`.
- **Account detail:** the above plus `previewTitle, websiteLabel, headcountLabel, locationsLabel,
  revenueLabel, foundedLabel?, fundingLabel?, fitScoreLabel?, createdAt, lastModifiedAt (required),
  summaryParagraphs[], businessParagraphs[], fitCriteria[] (legacy, may be empty), contacts[]
  {id,name,avatarUrl?,title?,persona?,emailVerified?,hasDetail}, activity[] (see below),
  researchEvidence[], overviewDisplay (DisplayBlock, page "overview"), buyingCommittee[]
  {contactId,name,title,persona,email|null,emailClaimId|null,linkedinUrl,whyTheyMatter}`.
- **Account workspace / insights:** `insightSummary[] (computed: "N insights", "M people"),
  researchEvidence[], insightsDisplay (DisplayBlock, page "insights"), artifacts[] {id,title,
  type ∈ presentation|document|web|ad|email, accountId?, projectName?, updatedAt?, thumbnailPath,
  lastEditedLabel}, activity[]`.
- **Contacts list:** `id, name, title, persona, personaTone, influence, avatarUrl?, emailStatus
  (available|lookup), emailLabel?, socials[], profileAction (none|preview|page)`.
- **Contact detail:** the row plus `accountId, accountName, accountLogoPath, recentSignalsLabel,
  linkedinLabel, linkedinUrl, xLabel?, xUrl?, emailVerifiedAt?, locationLabel?, locationClaimId?,
  bestFirstChannelLabel?, educationLabel?, tenureLabel?, employmentStartedAt?, linkedinFollowers?,
  linkedinCreator?, reports[], overviewParagraphs[], evidence[], researchEvidence[], contactDisplay
  (DisplayBlock, page "contact")`.
- **Activity (on account detail and on the workspace payload; not on the list row):** `{id, kind ∈ contacts|summary|created|artifact|updated,
  text, timeLabel, actor? ({type:"clue"} | {type:"person", id, name, avatarUrl?}), action?,
  occurredAt?, isSample?}`.
- **Shared:** `ResearchEvidence {claimId, sourceUrl|null, sourceDomain, faviconUrl|null, title,
  quote|null, researchExcerpt?, publishedAt, verifiedAt, verificationKind ∈ verified|record,
  mediaTimestamp, provider, outreachSafe}`; `DisplayBlock {page, sections[] {key, h1, empty,
  emptyMessage?, intro[]?, restricted, defaultOpen, items[] {id, h2, body[] {text, claimIds[],
  segments[]? {text, claimIds[]}}, sendLine {channel, text, claimIds[]}|null, contactRefs[],
  subject?, inlineLead?, fitDisposition? ∈ support|caveat, priority 1|2|3, newSinceLastVisit}}}`.

**Backend-owned semantics (the frontend never re-derives these):**

| Wire field | Backend rule |
|---|---|
| `ResearchEvidence` | one row per claim cited on the page; `claimId` = claim id, `quote` = the verbatim evidence span **or `null`** with `researchExcerpt` = the research sentence when no original-source quote exists (never a fabricated quotation); `sourceUrl` = source URL or `null` for private records (`verificationKind: "record"`: email checks, database rows); `verifiedAt` = observed_at; `publishedAt` = source date when known; `mediaTimestamp` from the claim's media sub-fields; `outreachSafe` = the claim column; `sourceDomain` resolved server-side; `faviconUrl` may be `null` — the frontend resolves favicons by domain through its own proxy route; `title` = page title when captured |
| `body[].segments` | the display model's output is split into clause-level segments, each with the claim ids that support that clause; chips render after the clause, not the sentence |
| `ResearchItem.priority` | the best (lowest number) `signal_priority` among the item's cited claims |
| `fitDisposition` | on "Why they fit" items: `support` when the fit claim is satisfied, `caveat` when it is the honest negative |
| `intro[]` | narrative sections ("What they do", "Why they fit") carry their paragraphs as `intro`, items carry the evidence rows |
| `ResearchSection.empty` / `emptyMessage` | `empty` when the recipe matched nothing and the display model was not called; `emptyMessage` optional server text, else the client prints "No {section} information found for {name}." |
| `restricted` sections | `do-not-mention` / `context-only` / `watch-outs` are the only sections that ever receive `outreach_safe=false` claims; the frontend shows them under an "Internal notes" control and omits `watch-outs` from the overview |
| `sendLine` | contact page only; a separate field, never inside quotation marks; `channel` is served text |
| `h1` / counts / overall fit | `h1` is the section's served vocabulary **without counts or parentheticals**; counts are `items.length`; the overall fit is `overallFit`, never text inside an `h1` |
| `insightSummary` | computed by the backend: `"{n} insights"` where n = items across non-restricted sections, and `"{m} people"` where m = committee members; the fixture's "42 reported in research" declared total is a fixture artifact and does not exist in production |
| `newSinceLastVisit` | the **frontend** computes it from `ResearchEvidence.verifiedAt` against a locally stored last-visit stamp; the backend serves `false` and no visit row (decision D5 resolved) |
| `fitScore` / `overallFit` | both `null` when the account has not been scored (never `0`, never a guessed band); scoring writes both together (ruling R7 makes `overallFit` nullable) |
| `owner` / `createdBy` | workspace users (CRM data, never agent-written); `owner` nullable, `createdBy` recorded at creation; display precedence: assigned `owner`, else `createdBy`, else "Unassigned" (ruling R6) — never the current viewer |
| `tenureLabel` / `employmentStartedAt` | the backend serves both; the frontend displays `tenureLabel` as-is (it never computes tenure from the browser clock); `employmentStartedAt` exists for sorting and date display |
| `artifacts[]` | the workspace endpoint projects account-associated generated artifacts with `accountId`; `updatedAt` from the artifact record; no invented dates |
| `activity[]` | actor is `clue` for agent actions and `person {id,name}` for user actions; `occurredAt` ISO; unattributed events carry no actor; `isSample` only in fixtures |
| `customFields` | registry custom variables whose values are claims; `presentation` from the registry row |
| `BuyingCommitteeMember.email` + `emailClaimId` | from the `core.work_email` claim; verification state lives in the evidence hover, not inline |

Not on the wire by design: `field_key`, `use_class`, `source_type`; generic field rendering exists
only for `customFields`. The Next.js `/api/source-favicon` route and the accounts layout shell are
frontend-owned and travel with the re-lift.

**As built (D3, 2026-09-08) — contract v1 is executable.** The five payloads above are no
longer prose: they are pydantic models in `platform/api/clue_api/frontend_read/contract_v1.py`
(strict, alias-serialised, required-nullable vs absent-optional mirrored field for field) checked
against the frontend's **own** Zod — vendored under `tests/api/contract_v1/zod/` at D3 and moved to
`apps/frontend/src/features/accounts/model/` by the D4 re-lift — run for real through
`apps/frontend`'s `zod` package by `tests/api/contract_v1/oracle.py` — so "the payload matches the
contract" is a test, not a reading. They are served under **`?contract=v1`** beside the untouched
FI-2 payloads (source map §1); D4 re-points the adapters and deletes the FI-2 branches and the
parameter together. The §8 D0-a amendments are **staged in the vendored copy**, marked `// D3
ruling`, and are what D4 lifts back into `apps/frontend`. D3 made exactly two contract additions of
its own: `BuyingCommitteeMember.linkedinUrl` is **nullable** (a member resolved from a coverage row
may have no LinkedIn URL), and E4's envelope carries **`meta.total`** so the screen's contact count
is served rather than inferred from a page (additive — the dummy's envelope Zod is not strict).

## 7. The display layer

- **Page grammar:** each page is a fixed template of H1 sections (product vocabulary).
  Insights: Buying signals · Money & momentum · Tools they already use · How they sell, and who they
  win · Contact insights · Context only (restricted). Account overview: What they do · Why they fit ·
  Why now · Buying committee · How to approach · Watch-outs (restricted — served in the payload,
  shown only under the Insights page's Internal notes; the overview page omits it); rail: Core /
  Custom / Contacts / Activity. Contact: Why this person · Their problem right now · Openers ·
  Angles · Do not mention (restricted — shown under the contact page's Internal notes control,
  never in the main reading flow); rail: email, LinkedIn, location, best channel, education,
  tenure, reports.
- **Recipes:** each section lists the field keys it may draw from (config rows, §4). A custom
  variable is just another key appended to a recipe. Rail rows are plain fields, never sent to the
  display model.
- **Output shape:** each section returns `intro[]` (narrative sections) and `items[]`; each item's
  body sentences carry `segments[] {text, claimIds[]}` — clause-level citations — plus the
  sentence-level `claimIds`; contact-page items carry a `sendLine`; "Why they fit" items carry
  `fitDisposition`. Section `h1` is served without counts.
- **Generation:** one Luna call per section, all sections of a page in parallel, default reasoning
  effort (a lower effort leaks unsafe claims and is not cheaper). Prompt: stable prefix (system +
  client context + the section's claims) then the section instruction; three fixed lines: never type
  claim ids into prose; write dates as "17 June 2026"; use the personal-hobby hook at most once per
  page. Output = the `ResearchSection` shape; every sentence carries the claim ids it used; the model
  never sees or types a URL.
- **Checks after the model — annotations, not blockers.** Logged on the `display_block` row when
  `CLUE_EVIDENCE_VERBATIM_CHECK` is on: quoted spans found in the cited claims, numbers found in the
  claims, claim ids valid and on-recipe, send lines present. **The single hard rule** (the floor, on
  by default): an `outreach_safe=false` claim cited outside a restricted section regenerates that
  section once, then serves the section without the offending item. A page is never blocked.
- **Generation policy (2026-09-21 — written by the fleet, never inside a read):** a section is
  written **once, by a fleet task** (`arv2_display_page`, one task per `(subject, page)`) and then
  **persisted and served as-is on every later visit**. When each page is written: the account
  **overview and insights pages** at **settle** — the account research job offers both after the
  committee step, so the first human to open a researched account waits for nothing; the **contact
  pages** of an account the **first time that account is opened** (its overview or its contacts
  tab), all settled committee members at once, because an account nobody looks at costs nothing;
  every other page on **its own first open**. A **read never writes**: it serves the blocks that are
  stored, marks the sections the task will write `pending` with the one served sentence
  `Synthesis in progress, please wait a few seconds.`, and offers the page's task — the client
  re-reads the page every 5 s while any section is pending. A section that will *never* be written
  (its recipe matches no claim) is **not** `pending` and keeps the ordinary empty state, so the
  sentence is never a promise the page cannot keep. **Stale sections are served as stored and the
  page is re-offered**, swapping the new row in when it lands. It is regenerated **only on
  invalidation, and only the affected sections**. Invalidation is **recipe-scoped**: a section is
  stale when any claim for that subject whose `field_key` is in the section's recipe is added,
  superseded, or has its `outreach_safe` flag changed, or when the recipe/prompt version changes.
  No scheduled regeneration; `:batch` only for an accumulated invalidated set. (With no work queue
  composed — the CLI, a test root — the read falls back to the old inline write.)
- **Shared blocks (2026-09-21):** the **insights** page does not re-synthesise a question another
  page already answered. `context-only` is the overview's `watch-outs` block and `contact-insights`
  is the committee's `why-this-person` blocks in committee order — the stored bodies only (same
  items, same claim ids), under the insights page's own `h1` and open/closed default. They are never
  `pending` on the insights page: their owner page carries that, and a stale owner is re-offered
  from whichever page is being read. No synthesis is ever written from another synthesis.
- **Empty state:** "No {section} information found for {name}." The H1 is never hidden.
- **Presentation (frontend-owned, decided 5 Sep):** Notion-style heading toggles, closed by
  default and independently expandable; no tabs, no jump menu, no priority accents, no boxed copy
  callouts; every item rendered in source order **without truncation** (P3 included); restricted
  content under a top "Internal notes" control; a "Sources" panel listing every cited URL; the
  overview shows "What they do" and "Why they fit" statically and "Why now / Buying committee /
  How to approach" as closed toggles, and omits "Watch-outs"; inline sources are favicon + compact
  domain; unknown fit score renders "—" from `null`.
- **Source chips:** rendered by the client from `claimId → ResearchEvidence`. The backend serves
  `sourceDomain`; the frontend fetches the favicon for that domain through its own `/api/source-favicon`
  proxy (so `faviconUrl` may be `null`). A chip shows favicon + compact domain only. A private record
  (`verificationKind: "record"`: an email check, a database row) shows a lock icon and the label
  "Record"; the provider name appears only in the hover card. No dates appear on the chip or in the hover card (ruling R1); `verifiedAt` and `publishedAt` stay on the wire for the frontend's own computations.

**Note recorded at D2 (2026-09-08), when the display layer above was built as
`platform/api/clue_api/arv2/display/`.** The **section keys are contract v1** and are fixed:
insights `buying-signals` · `money-and-momentum` · `tools-they-already-use` · `how-they-sell` ·
`contact-insights` · `context-only`; overview `what-they-do` · `why-they-fit` · `why-now` ·
`buying-committee` · `how-to-approach` · `watch-outs`; contact `why-this-person` ·
`problem-right-now` · `openers` · `angles` · `do-not-mention`. The three restricted keys are
`context-only`, `watch-outs` and `do-not-mention`. **The display reads *live claims*, not the
merge:** `current_values` collapses `(entity, field)` to a single winner, and a page must show
everything the research found — several rows of the same field included — so the gather step reads
`claims_for_entities` and mirrors the merge's *eligibility* posture (with verification on,
unverified tier-4 rows are excluded) without its cardinality collapse. **Claims reach the model as
short aliases** `c1…cN` in a stable order, never as uuids, which is what makes "never type a claim
id into prose" a property of the payload rather than a hope about the model; the runner maps the
aliases back and drops (and counts) any it does not recognise. **The sensitivity floor is
defence-in-depth, not the primary control:** the gather filter already withholds every
`outreach_safe=false` row from a non-restricted section, so on real inputs the floor's
regenerate-once-then-drop path never fires — it exists for the case where the input filter is
wrong. **The two S4 content files are `display/recipes.py` (the 17 section recipes) and
`display/prompts.py` (the system prompt and the 17 section instructions);** everything else in the
package is A4 machinery. D2 adds no migration — `display_block` and `display_section_recipe` are
D1 tables.

## 8. Rulings on the dummy frontend (D0)

**Resolved by Shashank's 5 Sep commits (`clue-frontend` @ `84f8ee7`):** the overview renders every
section except Watch-outs; the positional 3-item cut and "Show N more" are gone; tabs are gone
(independent closed toggles); the client-side section-title and channel relabel maps are gone; the
digest is dead code; contact chips show title/persona/email state on hover; `insightSummary` is
computed; unknown fit score is `null`; the hard-coded "Last updated yesterday" is gone; the
featured-contact hard-code is gone (`profileAction`); lint/build/tests green (118 tests).

**Rulings — ruled by Aryan on 2026-09-07; Shashank's confirmation pending.** Every row is decided as its Recommendation column reads, except R1, whose ruling replaced the recommendation:

| # | Item (file:line in `live-backend-v1`) | Recommendation |
|---|---|---|
| R1 | Dates on source chips and hover cards are not rendered (`research-content.tsx:40-44, 90-93`); the spec asks for "posted … · verified …" | **Ruled: no dates anywhere** — not on the chip, not in the hover card. `verifiedAt` stays on the wire (it feeds the frontend's new-since-last-visit computation, D5); `publishedAt` stays on the wire, unrendered |
| R2 | Restricted sections live in the hidden "Internal notes" panel; the spec said "always open on the contact screen" | Accept Internal notes (it is the newer design decision); record it in the contract doc |
| R3 | Priority presentation dropped (no P1 accent, no P1-first sort) | Accept for v1; `priority` stays on the wire for ordering within a section (backend sorts P1 first) |
| R4 | Hover-card quote clamped to 4 lines (`account-research.module.css:371-380`) | Show the full quote; it is the evidence |
| R5 | Email chip found by substring match on evidence text (`contact-profile-content.tsx:91-95`) | Resolve via `emailClaimId` |
| R6 | Unowned accounts display the **current viewer** as owner (`account-owner.ts:16`) | Show "Unassigned" when both `owner` and `createdBy` are null; never fabricate ownership |
| R7 | `createLocalAccount` invents `fitScore: 0`, `overallFit: "Medium"` (`create-account.ts:7,15`) | `fitScore: null` until scored, and **make `overallFit` nullable in the model** (a contract-v1 change: `High|Medium|Low|null`, rendered "—"); the create flow POSTs `{name, websiteUrl}` and the backend returns the row |
| R8 | Contact page header shows the **account's** `lastModifiedAt`; tenure is computed from the browser clock (`account-workspace-shell.tsx:179-185`, `contact-profile-content.tsx:217`) | Serve `tenureLabel` from the backend; contact "Updated" = the contact's own latest `verifiedAt` |
| R9 | Section `h1` counts and "Overall fit: High" are stripped/parsed client-side (`research-content.tsx:551-554, 787-805`) | Contract: `h1` is served bare; counts = `items.length`; overall fit = `overallFit` — remove the parsers |
| R10 | The four non-Nick contact pages synthesize an "Account context" section (`data/zafran/contacts.ts:147-152`) | Fixture-only; production pages come from `contactDisplay`; note it in the contract doc |
| R11 | The fixture markdown parser uses `readFileSync(process.cwd() …)` (`spec-content.ts:15-20`) | Fixture-only; must never reach a client bundle; the re-lift keeps fixtures server-side |
| R12 | `defaultOpen`, `empty`, `outreachSafe`, `emailClaimId`, `publishedAt`, `verificationKind` are on the wire but unread by components | Keep all six in contract v1: R5 makes the frontend use `emailClaimId`; the other five are served now and rendered later only if a design needs them (R1 rules `publishedAt` unrendered) |
| R13 | The contract doc (`docs/api-contracts/accounts.md`) has none of the new fields | Record contract v1 (§6) — D0 task |

## 9. The roadmap — three tracks that meet at the claim store

### Track D — display and frontend integration (starts now)
| Step | What | Owner | Exit gate |
|---|---|---|---|
| D0 | Apply the remaining §8 rulings (R1, R4–R9) in the dummy frontend; write contract v1 (§6) into `accounts.md` | Shashank via agent; Aryan signs | Dummy lint/build/tests green (≥118 tests); the fidelity tests still pass; Zafran renders every section from fixtures |
| D1 | The §4 migration; the **claim loader** — a governed one-off writer that turns the Zafran and person research outputs into real claims through `insert_claim` (register the new fields first, unify `use_class`, stamp priority + `outreach_safe`, write run lineage, snapshot media transcripts, dedupe one-fact-one-flag) | Aryan (agent-built, founder-reviewed) | 174 + 119 rows in the store, catalog-valid, lineage-pinned; single alembic head; `make db-smoke` green |
| D2 | Section recipes seeded; the Luna section runner with the §7 checks; the evidence resolver; `display_block` persistence with the §7 generation policy | Agent under Aryan's review; Shashank owns recipes and prompts | Zafran overview, insights and Nick Fisher pages generated from the store; checks 0 leaks / 0 non-verbatim / 0 off-recipe |
| D3 | The five §6 payloads on `/frontend/v1`, including `researchEvidence`, the three DisplayBlocks with `segments`, `buyingCommittee`, actor-based `activity`, account-scoped `artifacts` | Aryan | Payloads validate against the dummy's Zod models (`live-backend-v1` @ `84f8ee7`) byte-for-byte |
| D4 — **DONE 2026-09-09** (branch `track-d4`; the feature, the eight routes, the accounts layout shell, the favicon proxy and the design-system package all lifted from `84f8ee7`; the sixteen §6 client-side derivations removed; the contract-v1 Zod is now the feature's own `model/*.ts` **and** the parity oracle's source; five adapters on `fetchRead` + the BFF with **`?contract=v1`** — that parameter stays until the backend FI-2 deletion PR; fixtures behind `CLUE_ACCOUNTS_FIXTURE_MODE=true` with **no** fallback; the kept FI-2 behaviours = bulk add-to-project / send-to-chat, the single-contact email lookup, the typed recovery screen; create is a local non-optimistic draft until `POST /frontend/v1/accounts` exists; **no backend code changed**. 12 routes walked live against the real store — see `_memory/2026-09-09-arv2-d4-accounts-relift.md` for the 24-item drift list, which is D5's input) | Re-lift the dummy's accounts feature from `live-backend-v1` into `apps/frontend` — the feature folder, the accounts layout shell, the `/api/source-favicon` route, and the design-system token changes; adapters → `/frontend/v1`; no new components | Shashank via agent; Aryan merges | With `CLUE_API_BASE_URL` set, Zafran pages render from the real backend; fixtures still demo offline |
| D5 | Acceptance: the three Zafran spec pages vs the live pages, section by section, with the dummy's fidelity tests as the mechanical check; the four remaining contact pages generated lazily on first open | Both | Founder walk-through signed; drift list empty |

**Track D — D4-b DONE 2026-09-09** (branch `track-d4b`, seven tasks, commits `ef273a666`,
`f06c5a3f6`, `14fd701f3`+`6e58459ad`, `18b092422`, `f96f99530`+`c424b7827`+`182080915`,
`ceb82f841`). D4 left the screens reading the old research lane through the FI-2 payloads; D4-b made
every read ARV2-native and deleted the old surface:

- **Research status** is one statement over `arv2_research_job` (`arv2_research_status_for`) — per
  account, not per project; the status string is served verbatim, `refreshing` = a non-terminal job
  newer than a completed one. The `entity_research_job` aggregation is gone.
- **The committee** is the account's contacts holding ≥1 live claim, persona-ranked then by name
  then by id, with **no coverage-row branch**; "why they matter" serves a researched rationale
  verbatim and otherwise `"{title} · {persona label}"`.
- **Persona is display text on the wire** (`"Economic buyer"`), everywhere including the contact
  refs inside stored display blocks (a one-shot rewrote 7 blocks / 26 personas, idempotent);
  `revenueLabel`, `revenueBand` and `fundingLabel` read the registry objects instead of printing
  `10m_50m` or `amount_max: 25000000` at a marketer.
- **`core.work_email` is an object** carrying the provider's verdict (`{address, status,
  checked_at?}`, migration `7332ac974920`), so a stored address can be graded; the four loaded
  Zafran rows were repaired in place, provenance preserved.
- **One contract.** The FI-2 readers, models, SQL and the `?contract=` selector are deleted
  (−7,087 lines over 39 files); E6 went with them; `/frontend/v1` serves ARV2 v1 only. The guard
  `tests/api/test_frontend_read_arv2_only_guard.py` keeps it that way.
- **The D1 answer-key loader writes ARV2 rows only** — one `arv2_research_run` + one
  `arv2_research_job` through `account_research_store`; its four legacy INSERTs are gone and the
  guard's file allowlist is now empty.

The old lane's own tables and modules are inventoried, not deleted, in
**`docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`** — that document is the Phase-6 PR's plan
input. D5's input is unchanged.

**Track D roadmap — the CSS re-sync job (founder ruling 2026-09-09, 2a).** D4 merged tokens
*additively*: the design build's `packages/design-system` package replaced ours, and the 48
variables only the old token set defined were extracted once into
`packages/design-system/generated/legacy-compat.css` so the not-yet-re-synced features keep
rendering. The re-sync is its own later job, unowned and unscheduled: bring **every** feature's CSS,
the application shell and the shared `Button` across from the design build (D4 added only the
`transparent` variant and the `md` size to `Button`, additively, so the lifted toolbar could render);
then **delete `legacy-compat.css` and its one-shot extractor**
(`packages/design-system/scripts/extract-legacy-compat.mjs`) and the shrink-only allowlist in
`src/design-system-tokens.test.ts`. It also owns the hard-coded placeholder person in
`apps/frontend/src/components/shell/app-sidebar.tsx:119` (`Aakash Shrivastava`), which the shell
prints on every accounts page while the accounts feature itself resolves the profile correctly from
the protected session.

### Track R — the research lane (in parallel; writes the same claim rows the loader wrote)
| Stage | What | Exit gate |
|---|---|---|
| R1 providers | AI Ark client, Exa client (search / contents / deep-reasoning with the silent-fail guard), ATS resolvers (Ashby / Greenhouse / Lever), podcast RSS + YouTube probe, the Gemini media client, the OpenRouter structuring client — all with save-raw-before-parse, cost ledger, pre-spend estimate, retries honoring `Retry-After`, an enforced media-seconds ceiling; keys in `Secrets` + `.env.example` | Recorded live fixtures for every client against Zafran and Probook; no claim writes |
| R2 account agent — **DONE 2026-09-08** (exit gate met live on Probook: 85 claims / Zafran: 104 claims; screens verified through the D2 CLI, the frontend screen check is owed to D3; evidence `.context/arv2-r2-acceptance/`). R2 close (2026-09-08): recall measured against the answer keys, model spend on the ledger from OpenRouter, structuring hardened (sources/notes, per-draft writes, coercion, widened AI Ark mapper), audit reasons, gate-keyed verdicts; re-run pending. | One LangGraph agent per account on the existing fleet, behind `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED`, own catalog folder (`entity-research/arv2-account/v1`: profile, prompt, dossier skill, audit skill, manual), own driver implementing the failure law (every tool error is a recoverable refusal; caps push to finalize, never raise). Charter: the twelve-section dossier (ten in the original Zafran charter; identity/disambiguation and culture/resonance joined from the Probook and five-account charters — ruled 2026-09-08) with a required reputation/negatives section and an "already established" block; free-first ordering (ATS → RSS → own site → AI Ark company + name-scoped people → Exa gap searches → one deep call). Two claim species: deterministic (from provider fields, in code) and synthesised (one structuring call per subject against the code-validated catalog); verbatim checking as an annotation only (flag off by default) | Probook and Zafran researched end-to-end; ≥15 claims each with quotes + URLs on the account screens; the negatives section present |
| R3 committee + person agent — **DONE 2026-09-09 (partial acceptance by ruling)** (six people researched end to end on the fixed code, Zafran's account job fanning its confirmed committee out into four person jobs (dequeued by ruling before they ran), the on-demand person launch, and the contact pages reading the ARV2 rows; evidence `.context/arv2-r3-acceptance/acceptance.md`). | Web-first committee (team page, funding announcements, LinkedIn via Exa, ATS reporting lines) confirmed before any provider lookup; AI Ark name-scoped enrichment + email; one person agent per confirmed member with the personal-depth charter (background, life outside work as self-stated, voice with 3–5 verbatim quotes, professional identity, unique insight, three grounded openers); trimmed sweep (six angles), one deep call + one narrow unique-insight follow-up per person, media only where it exists; the **coded compliance pass** after structuring (minors references redacted from the value even if self-published; origin/nationality/faith recorded as biography only, `outreach_safe=false`, barred from hooks/openers; mark rows with no quote / no URL as `unevidenced` (purge only if `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=true`); every action logged; nothing is dropped whole) | The 10-person answer-key set reproduced; committee with verified emails, hooks, openers and voice quotes on the contact screens |
| R4 discovery + fleet — **built 2026-09-10 (live exit gate owed; evidence path `.context/arv2-r4-acceptance/`)**. Built to the rev-5 plan of action (`docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md`), which supersedes the shape described in the next cell: Exa Websets finds the long list, Exa Answer verifies every hard gate with a quote and a source under three code guards, the accounts table is the approval surface, and there is no per-run concurrency cap (ruling 3′ — worker scheduling is its own discussion). Lane docs: `platform/api/clue_api/arv2/README.md` § R4. | ICP-driven discovery (signal-first job-req search, free ATS boards, the $0.007 qualifier probe for stage + hiring gates), cohort approval, fleet fan-out over an approved cohort with a max-concurrency cap | A 20-account cohort discovered, approved, researched and displayed |

R1 starts the day D1's migration lands. When R2/R3 go live, the loader retires; D2–D5 do not change.

### Track O — the tech founder's lane
**The Track O plan is `ARV2-ONBOARDING-PLAN.md` (proposed 2026-09-07; phases O0–O7, decision boxes
O-D1–O-D6): onboarding as a research pipeline on the fleet, the `onboarding-synthesis@v1` agent, the
brand-context Knowledge read surface, and the Head-of-ABM integration.**
**Product catalog:** the Exa request shape, the `ProductCatalogResearch@1` artifact, the sync
deltas, the `product_set_selection` gate, and the multi-product-per-project ruling are fixed in
`ARV2-PRODUCT-CATALOG-CONTRACT.md` (2026-09-07). **Company overview:** the Exa Agent request
(effort `high`), the validated `outputSchema`, the `CompanyOverviewResearch@1` artifact and its
fixed-heading rendering are fixed in `ARV2-COMPANY-OVERVIEW-CONTRACT.md` (2026-09-07, live-validated
on Insight Health: 67 s, $0.50). Fast recon = company overview ∥ product lineup → ICP synthesis →
persona documents; background = one Agent run per discovered product. Seller-company knowledge is
**artifacts, never Client-KB claims** (standing rule: catalog contract §10).
Onboarding as a research pipeline (parallel research agents writing `.md` artifacts into the
deepagent workspace), 2–5 ICP proposal artifacts, the prompt-driven interview, the final ICP
artifact under project + brand context, durable project context (replacing scoped memory for v1),
the Exa MCP search tool on the main agent (landed 2026-09-22 as the direct governed tool
`web_search@1`, not MCP — spec `docs/superpowers/specs/archive/2026-09-22-web-search-tool-design.md`),
brand context, and the chat-shell output-pane motion
handoff. The Head-of-ABM skills adopt the co-founder's refinements content with three edits: every
"route to memory" becomes "record in project context"; the copy-voice lint/reviewer-judge lines are
removed (the em-dash and no-fabrication rules stay as prompt rules the agent applies itself); recon
and readiness assumptions are dropped; the interview skill's "preserve exact statements /
value must appear inside the quote" rule is removed — statements are recorded as the agent
understands them, with the turn as provenance. The corpus-acquisition program is backlog until the
onboarding rebuild ships.

### Phase 6 — deletion of quarantined code
One dedicated stub-and-delete PR, only after **both** D5 and the R2/R3 exit gates pass: the Sumble
stack, the old research lane and its settlement layer, the Stage-0 scrapers, the judgment gates,
the unused waterfall consumers. The memory subsystem stays on disk until a product decision.

**The inventory is written (2026-09-09, D4-b Task 7): `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`.**
83 old-lane tables (with row counts, creating migration and every code reader/writer), the ~38 kLOC
of modules with their importers and flags, an eight-step stub-then-delete order with the blast
radius and gate per step, and an explicit survive list. Nothing has been deleted; the document is
the next PR's plan input.

## 10. Operating model (how a non-technical co-founder and coding agents execute this safely)

1. **Every task is a written charter before an agent runs.** Template: goal (one sentence) · inputs
   (exact paths) · files the agent may touch · exit gate (a command or a screen check) · "if you must
   decide something not written here, STOP and ask" · where raw evidence goes (`.context/<run>/`).
2. **Agents commit to task branches and never merge.** Aryan reviews and merges at the four
   integration points — the migration, the loader, the read surface, the fleet/composition wiring.
   Frontend-only and docs-only charters are checked by Shashank against their exit gate.
3. **Every charter restates the standing rules** (§2 items 7–10).
4. **Cadence:** one shared base branch, pulled by both founders daily; one founder ruling session per
   week with the open-decision list; every run's cost ledger reviewed.
5. **Verification is first-hand:** whoever signs a gate spot-checks the agent's report against the
   code or the screen.
6. **Answer keys are fixed:** Probook (account), Zafran (account + committee + media), the 10-person
   set (contacts), and the three Zafran spec pages (display). Every exit gate compares against them.

## 11. What is off and must stay off

By configuration (`.env.example` is the deployment truth): `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`
(the whole old research lane), all `CLUE_SUMBLE_*=false`, `CLUE_MEMORY_ENABLED=false`,
`CLUE_SELF_SERVE_PROVISIONING_ENABLED=false` (old onboarding recon), `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`,
`CLUE_VERIFICATION_ENABLED=false`, `CLUE_BUDGET_CONTROLS_ENABLED=false`. The `integration_pilot`
product path must not be used (it forces the old lane back on).

By construction: the new lane is new files with its own driver and imports none of the old modules;
a static test asserts nothing under the new lane imports a quarantined module; the toolbelt's
boot-time audit refuses to start if an old tool is re-granted; the old tools are replay-only stubs.

## 12. Decisions (initial each line) — Aryan ruled 2026-09-07 on every line except D9; Shashank's column is open

| # | Decision | Recommendation | Aryan | Shashank |
|---|---|---|---|---|
| D1 | Ratify the two-track split; Track D starts before Track R is live | Yes | ✓ (2026-09-07) | ☐ |
| D2 | The remaining §8 rulings R1–R13 | As written | ✓ (2026-09-07) | ☐ |
| D3 | Contract v1 = the dummy's models at `live-backend-v1` @ `84f8ee7` + §6 semantics, incl. "no field_key on the wire" and "h1 served bare" | Yes | ✓ (2026-09-07) | ☐ |
| D4 | The §4 migration bundled (priority + outreach_safe + display_block + recipes) | Yes | ✓ (2026-09-07) | ☐ |
| D5 | `newSinceLastVisit`: frontend-computed from `verifiedAt` + local last-visit; backend serves `false`, no visit row | Resolved by the 5 Sep frontend | ✓ (2026-09-07) | ☐ |
| D6 | Seam 1: structured block in `directive_text` (effort rung + committee cap) | Yes | ✓ (2026-09-07) | ✓ (2026-09-07, Seam 1 signing) |
| D7 | Seam 1: launch requires existing `account_entity` rows | Yes | ✓ (2026-09-07) | ✓ (2026-09-07, Seam 1 signing) |
| D8 | Seam 2: add `user` to the `Persona` enum now | Yes | ✓ (2026-09-07) | ☐ |
| D9 | Seam 2: the "Series A and above" gate gets an equivalence clause for self-funded operators | Founders' call — **still open** (no recommendation was made, so it is not covered by the 2026-09-07 rulings) | ☐ | ☐ |
| D10 | Keep the four compliance floors (pre-spend authority, born identity-binding, use gate, DSAR) | Keep all four | ✓ (2026-09-07) | ☐ |
| D11 | The 11 pre-existing test failures on the base: pay off now or with the lane work | With the lane work, one owner | ✓ (2026-09-07) | ☐ |
| D12 | The operating model (§10), esp. "agents never merge" | Yes | ✓ (2026-09-07) | ☐ |
| D13 | The data-source rulings S1–S12 in `ARV2-DATA-SOURCE-MAP.md` §5 — owner columns, nullable logo/title, fit thresholds, legacy slots default `[]`, artifacts `[]` in v1, the five-value `researchStatus` enum, and **S10 = read-time relaxation**: the new accounts endpoints (E2–E5) use an ARV2 display predicate that keeps the use-class rules and the sensitive fail-close but does not refuse a `WEAK`-bound contact claim that is `outreach_safe = true`; the old C7 `display_allowed` is left unchanged | As written | ✓ (2026-09-07) | ☐ |
| D14 (=P1) | **A project targets a set of products, not one** — `project_product` versioned set; `product_set_selection` gate with `selected_option_refs[]`; `project.product_id` frozen legacy (`ARV2-PRODUCT-CATALOG-CONTRACT.md` §6) | Aryan overruled the single-product recommendation | ✓ (2026-09-07, "a very important ruling") | ☐ |
| D15 (=P2) | The set changes any time as a new version; runs keep the version they pinned; nothing is re-researched automatically | Yes | ✓ (2026-09-07) | ☐ |
| D16 (=P3/P4) | Exactly one ICP per project, targeting the whole product set (no per-ICP subset) | Aryan's ruling (the recommendation had been "subset allowed") | ✓ (2026-09-07) | ☐ |
| D17 | The Exa `outputSchema` for the product catalog (8 properties, depth 2, `aliases` dropped) and the `ProductCatalogResearch@1` artifact mapping (`ARV2-PRODUCT-CATALOG-CONTRACT.md` §3–§4) | As written | ✓ (2026-09-07) | ☐ |

## 13. The first ten steps, in order

1. Push the current base and merge it into the shared branch; rotate the Apollo and AI Ark keys;
   buy the AI Ark paid tier; add `CLUE_GEMINI_API_KEY` to `Secrets` + `.env.example`. *(Aryan)*
2. Founder session: §12. *(both)*
3. D0. *(Shashank + agent; Aryan signs)*
4. D1. *(Aryan + agent)*
5. R1 charters written from §3 and §9. *(Shashank)*
6. D2. *(agent; Aryan review; Shashank owns recipes/prompts)*
7. D3. *(Aryan)*
8. D4. *(Shashank + agent; Aryan merges)*
9. R1 build on the merged base, in parallel with D2–D4. *(agent; Aryan review)*
10. D5 acceptance walk-through; R2 starts with the display layer already live. *(both)*

## Appendix A — the laws every research tool obeys (from the proof-of-concept code)

1. Save the raw provider response before parsing; annotate status, latency and the request; then
   write the cost ledger entry. Cost comes from the provider's own metering when it exists (Exa
   `costDollars.total`, OpenRouter `usage.cost_details.upstream_inference_cost`, Gemini
   `usageMetadata` by modality); AI Ark credits are result-count arithmetic corrected after parse.
2. Raise the pre-spend estimate before the wire; retries honor `Retry-After`, else 12·(n+1) s for
   429/5xx and 2·(n+1) s for transport errors.
3. Sensitive keys (`birth_date` and kin) are dropped inside the provider client, before persistence.
4. Deep-reasoning calls carry the target lock and same-name exclusions in the system prompt, the
   charter in the query, and an "already known" block; the silent-fail guard retries once.
5. Deterministic provider facts become claims in code with the JSON path recorded; only prose goes
   through the structuring model, one subject per call, with the field catalog as its menu
   (unregistered keys become proposed fields, never refusals).
6. Verbatim-quote checking, when enabled, is an annotation on the claim, never a blocker; v1 ships
   with it off. If added later it is a fuzzy match, not exact-substring.
7. The sensitivity floor runs after structuring, in code (§9 R3): it redacts and marks, never drops.
8. Depth scores and hook counts are computed, never asked of a model.
9. Free-first ordering; a known URL is fetched, never searched for; ATS slugs are read from the
   careers page, never guessed.
10. One broad extraction call never decides that something does not exist; a narrow follow-up does.
11. Media: two-model recipe, duplicate-line detector, exact-substring quote verification, speaker
    identity verified before quoting, text embeddings only.
12. Zero yield is an honest terminal outcome; an exception escaping to the supervisor is a defect.

## Appendix B — evidence and answer keys (references only)

Proof-of-concept runs and their reports (chicago worktree `.context/`): `arv2-clue-sample-v3`
(Probook), `arv2-smoke-cluehq` (five accounts), `arv2-one-account-aiark` (Zafran, AI Ark-only, media),
`arv2-person-depth` (ten people), `display-layer-control-test` (the display-layer decisions),
`frontend-page-content` (the three Zafran pages as they must render), `ai-ark-canary`. The dummy
frontend: `clue-frontend/port-of-spain` (accounts, insights, contact screens). Contract docs:
`apps/frontend/docs/api-contracts/accounts.md`.

## Media v3 amendment — approved 2026-09-22, activation pending

The approved [media design](../superpowers/specs/archive/2026-09-22-arv2-media-research-design.md)
and [implementation plan](../superpowers/plans/2026-09-22-arv2-media-research.md) extend
AI Ark v2 through an explicit `media_research` catalog capability. Only jobs pinned to v3
use these changes. The launch default stays v2 until founder-triggered live acceptance.

For v3, contextual media discovery replaces the fixed six-search sweep and blanket domain
prohibitions. Public YouTube uses the narrow native-Gemini video route; public recordings,
explicit publisher transcripts and captions become immutable, workspace-scoped evidence.
Transcript search/open replaces excerpt-only access, and quote audits resolve saved spans.
Supplied timing remains qualified; untimed speech remains valid. Metadata or ASR labels alone
never establish a person's voice. Empty resolution does not consume a substantive item slot.

AI Ark SMART role discovery within the exact company, seed reuse, independent work email and
phone enrichment, and continuation after recorded Exa failure remain unchanged. Existing
runtime/media allowances remain enforced, with durable seconds/source ownership. No new
monetary/call-count/zero-yield stopping rule is introduced. Old v1/v2 catalog files and job pins
remain immutable. This amendment records implementation authority, not live-provider or
research-quality acceptance.

The v3 public fetch adapter imports only the shared `official_site.safety` and
`official_site.url_policy` primitives for URL admission, DNS validation and pinned redirects.
These two modules are a narrow addition to the ARV2 import guard; the official-site acquisition
engine and the quarantined research pipeline remain forbidden.


## Research quality shared seams — implementation amendment, 2026-09-23

The approved [quality design](../superpowers/specs/archive/2026-09-22-arv3-research-quality-design.md)
reuses only `clue_research.narrative.fields` and `.support` for the existing narrative field
and two-sided support table, and `clue_research.compliance` for shared workspace/use policy.
The import guard admits these substrate helpers explicitly; it still rejects the legacy
narrative positioner, assembler, research graph and waterfall. Platform Langfuse callbacks and
project-library change notifications are shared platform seams, not alternate research owners.
This amendment does not promote a launch default or authorize historical data repair.
