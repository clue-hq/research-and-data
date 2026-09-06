# ARV2 MASTER PLAN — the complete roadmap for account research, contact research, and their display

**This is the single authoritative plan. Version 1.3, 2026-09-05 (v1.1: lenient write gate, checks as flag-controlled annotations, human-stated facts need no URL, all fields optional; v1.2: the interview never requires word-for-word recording; v1.3: contract v1 re-based on the 5 Sep frontend `live-backend-v1` @ `84f8ee7` — clause-level citation segments, research excerpts, actor-based activity, account artifacts, owner/creator, nullable fit score — and the D0 rulings reduced to what remains). Both founders ratify by initialing
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
- Section recipes as registry-backed config rows: `(page, section_key, h1, order, allowed_field_keys[],
  restricted, default_open, instruction_version)`.
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
  `university_athletics`. `Persona` gains `user`. `use_class` uses the platform enum only.

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
the field catalog — the description *is* the research instruction). Body: the human-readable
definition in priority order, plus: TAM/list-math estimate and the widen | tier | shrink choice;
disqualifiers and red flags; closed-won/closed-lost patterns in the client's own words; the client's
own phrasing of who they sell to; the qualification-floor verdict. Stored in the durable artifact
store; materialized read-only into the deepagent's workspace via the project-context path.

## 6. Contract v1 — what the backend serves to the accounts screens

**Presentation truth:** the dummy frontend `clue-frontend`, branch `integration/live-backend-v1`,
commit `84f8ee7` (5 Sep 2026). Its Zod models in `src/features/accounts/model/*.ts` are the wire
shapes; its vendored `data/zafran/FRONTEND-SPEC-ZAFRAN.md` plus the fidelity tests
(`data/zafran/zafran-content-fidelity.test.ts`, `zafran-implementation.test.ts`) define what
"faithful to the research" means for the Zafran answer key. Contract v1 is recorded in
`apps/frontend/docs/api-contracts/accounts.md` and served on `/frontend/v1` (workspace-scoped),
with the frontend's repository adapters pointed at it. The five payloads:

- **Account list:** `id, name, logoPath, websiteUrl, researchStatus, researchStatusLabel?,
  researchIsRefreshing, overallFit (High|Medium|Low), fitScore (0–100 | null — never 0 for
  unknown), revenueBand, employeeBand, locationCount, locationsLabel?, owner (nullable),
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
- **Activity (list, detail, workspace):** `{id, kind ∈ contacts|summary|created|artifact|updated,
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
| `insightSummary` | computed: `"{n} insights"` (items across non-restricted sections), `"{m} people"`; no declared totals |
| `newSinceLastVisit` | the **frontend** computes it from `ResearchEvidence.verifiedAt` against a locally stored last-visit stamp; the backend serves `false` and no visit row (decision D5 resolved) |
| `fitScore` | `null` when unknown; never `0`; `overallFit` still required |
| `owner` / `createdBy` | workspace users (CRM data, never agent-written); `owner` nullable, `createdBy` recorded at creation; display precedence assigned owner → creator → (ruling R6 below) |
| `tenureLabel` / `employmentStartedAt` | the backend serves the start date; the frontend may format tenure, but the served `tenureLabel` is authoritative when present |
| `artifacts[]` | the workspace endpoint projects account-associated generated artifacts with `accountId`; `updatedAt` from the artifact record; no invented dates |
| `activity[]` | actor is `clue` for agent actions and `person {id,name}` for user actions; `occurredAt` ISO; unattributed events carry no actor; `isSample` only in fixtures |
| `customFields` | registry custom variables whose values are claims; `presentation` from the registry row |
| `BuyingCommitteeMember.email` + `emailClaimId` | from the `core.work_email` claim; verification state lives in the evidence hover, not inline |

Not on the wire by design: `field_key`, `use_class`, `source_type`; generic field rendering exists
only for `customFields`. The Next.js `/api/source-favicon` route and the accounts layout shell are
frontend-owned and travel with the re-lift.

## 7. The display layer

- **Page grammar:** each page is a fixed template of H1 sections (product vocabulary).
  Insights: Buying signals · Money & momentum · Tools they already use · How they sell, and who they
  win · Contact insights · Context only (restricted). Account overview: What they do · Why they fit ·
  Why now · Buying committee · How to approach · Watch-outs (restricted); rail: Core / Custom /
  Contacts / Activity. Contact: Why this person · Their problem right now · Openers · Angles · Do not
  mention (restricted, always open); rail: email, LinkedIn, location, best channel, education,
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
- **Generation policy:** a section is generated **once, on first request** (lazy — an unopened
  contact page costs nothing; the first open waits ~15 s), then **persisted and served as-is on every
  later visit**. It is regenerated **only on invalidation, and only the affected sections**.
  Invalidation is **recipe-scoped**: a section is stale when any claim for that subject whose
  `field_key` is in the section's recipe is added, superseded, or has its `outreach_safe` flag
  changed, or when the recipe/prompt version changes. On invalidation, serve the persisted block and
  regenerate in the background, swapping the new row in when it lands. No scheduled regeneration;
  `:batch` only for an accumulated invalidated set.
- **Empty state:** "No {section} information found for {name}." The H1 is never hidden.
- **Presentation (frontend-owned, decided 5 Sep):** Notion-style heading toggles, closed by
  default and independently expandable; no tabs, no jump menu, no priority accents, no boxed copy
  callouts; every item rendered in source order **without truncation** (P3 included); restricted
  content under a top "Internal notes" control; a "Sources" panel listing every cited URL; the
  overview shows "What they do" and "Why they fit" statically and "Why now / Buying committee /
  How to approach" as closed toggles, and omits "Watch-outs"; inline sources are favicon + compact
  domain; unknown fit score renders "—" from `null`.
- **Source chips:** rendered by the client from `claimId → ResearchEvidence`; favicon and domain
  resolved server-side and cached; a private record (email check, database row) shows a lock icon
  and a date, never a provider name on the page.

## 8. Rulings on the dummy frontend (D0)

**Resolved by Shashank's 5 Sep commits (`clue-frontend` @ `84f8ee7`):** the overview renders every
section except Watch-outs; the positional 3-item cut and "Show N more" are gone; tabs are gone
(independent closed toggles); the client-side section-title and channel relabel maps are gone; the
digest is dead code; contact chips show title/persona/email state on hover; `insightSummary` is
computed; unknown fit score is `null`; the hard-coded "Last updated yesterday" is gone; the
featured-contact hard-code is gone (`profileAction`); lint/build/tests green (118 tests).

**Remaining rulings (one line each; founders decide):**

| # | Item (file:line in `live-backend-v1`) | Recommendation |
|---|---|---|
| R1 | Dates on source chips and hover cards are not rendered (`research-content.tsx:40-44, 90-93`); the spec asks for "posted … · verified …" | v1: show `verifiedAt` (and `publishedAt` when present) in the hover card only; chips stay compact |
| R2 | Restricted sections live in the hidden "Internal notes" panel; the spec said "always open on the contact screen" | Accept Internal notes (it is the newer design decision); record it in the contract doc |
| R3 | Priority presentation dropped (no P1 accent, no P1-first sort) | Accept for v1; `priority` stays on the wire for ordering within a section (backend sorts P1 first) |
| R4 | Hover-card quote clamped to 4 lines (`account-research.module.css:371-380`) | Show the full quote; it is the evidence |
| R5 | Email chip found by substring match on evidence text (`contact-profile-content.tsx:91-95`) | Resolve via `emailClaimId` |
| R6 | Unowned accounts display the **current viewer** as owner (`account-owner.ts:16`) | Show "Unassigned" when both `owner` and `createdBy` are null; never fabricate ownership |
| R7 | `createLocalAccount` invents `fitScore: 0`, `overallFit: "Medium"` (`create-account.ts:7,15`) | `fitScore: null`, `overallFit` unset until scored; the create flow POSTs `{name, websiteUrl}` and the backend returns the row |
| R8 | Contact page header shows the **account's** `lastModifiedAt`; tenure is computed from the browser clock (`account-workspace-shell.tsx:179-185`, `contact-profile-content.tsx:217`) | Serve `tenureLabel` from the backend; contact "Updated" = the contact's own latest `verifiedAt` |
| R9 | Section `h1` counts and "Overall fit: High" are stripped/parsed client-side (`research-content.tsx:551-554, 787-805`) | Contract: `h1` is served bare; counts = `items.length`; overall fit = `overallFit` — remove the parsers |
| R10 | The four non-Nick contact pages synthesize an "Account context" section (`data/zafran/contacts.ts:147-152`) | Fixture-only; production pages come from `contactDisplay`; note it in the contract doc |
| R11 | The fixture markdown parser uses `readFileSync(process.cwd() …)` (`spec-content.ts:15-20`) | Fixture-only; must never reach a client bundle; the re-lift keeps fixtures server-side |
| R12 | `defaultOpen`, `empty`, `outreachSafe`, `emailClaimId`, `publishedAt`, `verificationKind` are on the wire but unread by components | Keep them in contract v1 (R1, R5 consume three of them); the rest are free to serve |
| R13 | The contract doc (`docs/api-contracts/accounts.md`) has none of the new fields | Record contract v1 (§6) — D0 task |

## 9. The roadmap — three tracks that meet at the claim store

### Track D — display and frontend integration (starts now)
| Step | What | Owner | Exit gate |
|---|---|---|---|
| D0 | Apply the remaining §8 rulings (R1, R4–R9) in the dummy frontend; write contract v1 (§6) into `accounts.md` | Shashank via agent; Aryan signs | Dummy lint/build/tests green (≥118 tests); the fidelity tests still pass; Zafran renders every section from fixtures |
| D1 | The §4 migration; the **claim loader** — a governed one-off writer that turns the Zafran and person research outputs into real claims through `insert_claim` (register the new fields first, unify `use_class`, stamp priority + `outreach_safe`, write run lineage, snapshot media transcripts, dedupe one-fact-one-flag) | Aryan (agent-built, founder-reviewed) | 174 + 119 rows in the store, catalog-valid, lineage-pinned; single alembic head; `make db-smoke` green |
| D2 | Section recipes seeded; the Luna section runner with the §7 checks; the evidence resolver; `display_block` persistence with the §7 generation policy | Agent under Aryan's review; Shashank owns recipes and prompts | Zafran overview, insights and Nick Fisher pages generated from the store; checks 0 leaks / 0 non-verbatim / 0 off-recipe |
| D3 | The five §6 payloads on `/frontend/v1`, including `researchEvidence`, the three DisplayBlocks with `segments`, `buyingCommittee`, actor-based `activity`, account-scoped `artifacts` | Aryan | Payloads validate against the dummy's Zod models (`live-backend-v1` @ `84f8ee7`) byte-for-byte |
| D4 | Re-lift the dummy's accounts feature from `live-backend-v1` into `apps/frontend` — the feature folder, the accounts layout shell, the `/api/source-favicon` route, and the design-system token changes; adapters → `/frontend/v1`; no new components | Shashank via agent; Aryan merges | With `CLUE_API_BASE_URL` set, Zafran pages render from the real backend; fixtures still demo offline |
| D5 | Acceptance: the three Zafran spec pages vs the live pages, section by section, with the dummy's fidelity tests as the mechanical check; the four remaining contact pages generated lazily on first open | Both | Founder walk-through signed; drift list empty |

### Track R — the research lane (in parallel; writes the same claim rows the loader wrote)
| Stage | What | Exit gate |
|---|---|---|
| R1 providers | AI Ark client, Exa client (search / contents / deep-reasoning with the silent-fail guard), ATS resolvers (Ashby / Greenhouse / Lever), podcast RSS + YouTube probe, the Gemini media client, the OpenRouter structuring client — all with save-raw-before-parse, cost ledger, pre-spend estimate, retries honoring `Retry-After`, an enforced media-seconds ceiling; keys in `Secrets` + `.env.example` | Recorded live fixtures for every client against Zafran and Probook; no claim writes |
| R2 account agent | One LangGraph agent per account on the existing fleet, behind `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED`, own catalog folder (`entity-research/arv2-account/v1`: profile, prompt, dossier skill, audit skill, manual), own driver implementing the failure law (every tool error is a recoverable refusal; caps push to finalize, never raise). Charter: the ten-section dossier with a required reputation/negatives section and an "already established" block; free-first ordering (ATS → RSS → own site → AI Ark company + name-scoped people → Exa gap searches → one deep call). Two claim species: deterministic (from provider fields, in code) and synthesised (one structuring call per subject against the code-validated catalog); verbatim checking as an annotation only (flag off by default) | Probook and Zafran researched end-to-end; ≥15 claims each with quotes + URLs on the account screens; the negatives section present |
| R3 committee + person agent | Web-first committee (team page, funding announcements, LinkedIn via Exa, ATS reporting lines) confirmed before any provider lookup; AI Ark name-scoped enrichment + email; one person agent per confirmed member with the personal-depth charter (background, life outside work as self-stated, voice with 3–5 verbatim quotes, professional identity, unique insight, three grounded openers); trimmed sweep (six angles), one deep call + one narrow unique-insight follow-up per person, media only where it exists; the **coded compliance pass** after structuring (minors references redacted from the value even if self-published; origin/nationality/faith recorded as biography only, `outreach_safe=false`, barred from hooks/openers; mark rows with no quote / no URL as `unevidenced` (purge only if `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=true`); every action logged; nothing is dropped whole) | The 10-person answer-key set reproduced; committee with verified emails, hooks, openers and voice quotes on the contact screens |
| R4 discovery + fleet | ICP-driven discovery (signal-first job-req search, free ATS boards, the $0.007 qualifier probe for stage + hiring gates), cohort approval, fleet fan-out over an approved cohort with a max-concurrency cap | A 20-account cohort discovered, approved, researched and displayed |

R1 starts the day D1's migration lands. When R2/R3 go live, the loader retires; D2–D5 do not change.

### Track O — the tech founder's lane
Onboarding as a research pipeline (parallel research agents writing `.md` artifacts into the
deepagent workspace), 2–5 ICP proposal artifacts, the prompt-driven interview, the final ICP
artifact under project + brand context, durable project context (replacing scoped memory for v1),
the Exa MCP search tool on the main agent, brand context, and the chat-shell output-pane motion
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

## 12. Open decisions (initial each line)

| # | Decision | Recommendation | Aryan | Shashank |
|---|---|---|---|---|
| D1 | Ratify the two-track split; Track D starts before Track R is live | Yes | ☐ | ☐ |
| D2 | The remaining §8 rulings R1–R13 | As written | ☐ | ☐ |
| D3 | Contract v1 = the dummy's models at `live-backend-v1` @ `84f8ee7` + §6 semantics, incl. "no field_key on the wire" and "h1 served bare" | Yes | ☐ | ☐ |
| D4 | The §4 migration bundled (priority + outreach_safe + display_block + recipes) | Yes | ☐ | ☐ |
| D5 | `newSinceLastVisit`: frontend-computed from `verifiedAt` + local last-visit; backend serves `false`, no visit row | Resolved by the 5 Sep frontend | ☐ | ☐ |
| D6 | Seam 1: structured block in `directive_text` (effort rung + committee cap) | Yes | ☐ | ☐ |
| D7 | Seam 1: launch requires existing `account_entity` rows | Yes | ☐ | ☐ |
| D8 | Seam 2: add `user` to the `Persona` enum now | Yes | ☐ | ☐ |
| D9 | Seam 2: the "Series A and above" gate gets an equivalence clause for self-funded operators | Founders' call | ☐ | ☐ |
| D10 | Keep the four compliance floors (pre-spend authority, born identity-binding, use gate, DSAR) | Keep all four | ☐ | ☐ |
| D11 | The 11 pre-existing test failures on the base: pay off now or with the lane work | With the lane work, one owner | ☐ | ☐ |
| D12 | The operating model (§10), esp. "agents never merge" | Yes | ☐ | ☐ |

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
