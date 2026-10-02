# ARV2 plan delta — 2026-09-03: what the Person-Depth and One-Account runs change

**Status: proposed amendment for founder ratification (Shashank + Aryan).** This document does NOT
replace anything. It amends three ratified/drafted artifacts in place:

1. `docs/specs/ARV2-R0-foundations-plan.md` (ratified 2026-09-01) — R0 is complete; only its
   Part 4 "what R0 leaves ready for R1" list changes (§3 below).
2. The R1–R5 sequencing ratified in discussion on 2026-09-01 (R1 providers → R2 account agent →
   R3 committee + contacts → R4 discovery + fleet → R5 serving) — the ORDER stands; the CONTENT of
   R1, R2, R3 and R5 changes (§3).
3. `docs/specs/ARV2-R0-seam-freeze.md` (DRAFT) — three decision boxes get recommended answers and
   the ICP body gains sections (§4; edits applied to that file in the same commit).

Evidence base, all read first-hand: the two new proof-of-concept runs on the chicago worktree
(`.context/arv2-person-depth/`, 2026-09-01, and `.context/arv2-one-account-aiark/`, 2026-09-02), their
code (35 scripts, 4,856 lines), the `head-of-abm-agent-refinements/` program (16 files, 12,400
lines), and the new presentation truth `conductor/workspaces/clue-frontend/chat-shell` at `b24f547`.

---

## 1. What the two new runs prove (findings, not opinions)

### 1a. Person-Depth run — 10 committee people to personal-dossier depth
- **$1.29 total, $0.13/person full recipe, $0.07 trimmed; 119 claims, every row with a verbatim
  quote + URL (2 unevidenced rows auto-purged); 8 of 10 people beat the Insight-Health bar of
  ~5 hooks; alma mater 10/10; a hobby/book/side project 7/10; long-form spoken voice 3/10.**
- The segment truth: **LinkedIn is the spine, then a cliff.** Public social (X/Bluesky/Threads/
  Reddit) yielded 0/10. Seniority buys voice, not personality: the three thinnest people are all
  marketing leaders — the buyers.
- **The deep-reasoning call out-finds the sweep that feeds it:** 16% of finally-cited URLs (incl.
  the best hook of the run) were never seen by any of the 120 sweep queries. Cut 5 dead sweep
  angles (27% of cost, zero unique URLs). `includeDomains` on Exa is a trap (forces same-name
  strangers).
- **One broad extraction call under-reports existence:** "thin footprint" for 7/10 people who had
  gold; one narrow $0.002 follow-up took the unique-insight hit rate 3/10 → 10/10.
- **Governance must live in code, not prompts:** both the deep prompt and the structuring prompt
  let a minors reference through; only the regex pass caught it. Origin-story facts are recorded
  as biography but forced `outreach_safe=false` and barred from hooks/openers.
- Media: YouTube's free caption endpoint is dead (7 forms, 200/0 bytes); Exa `/contents` on a
  YouTube watch URL returns the full ASR transcript for 4/5 videos at ~$0.001–0.004 (no
  timestamps); podcast MP3s need Gemini; modelled Gemini cost $0.04/hour; never embed raw audio
  (13.5× the text pipeline).
- Deep-reasoning **fails silently and cheaply** (9 results / ~$0.015 vs 18–20 / ~$0.023–0.025);
  one person was lost to it and manually retried — the guard belongs in the tool.

### 1b. One-Account run — Zafran end to end, AI Ark as the only database
- **0 Apollo calls (provable from the ledger); $0.166 + 11.6 AI Ark credits full recipe,
  $0.072 + 4.1 credits trimmed; 174 claims** (95 deterministic from provider fields, 21 from media,
  54 synthesised, 3 proposed fields, 1 recorded exclusion).
- **AI Ark is an excellent spine and knows nothing about timing, intent, reputation, or voice.**
  Best fields: `funding.rounds[]` (found a $40M Series B two prior runs missed), exact headcount,
  `technologies[]`, `position_groups[]` with dates, `department/seniority`, the email block with
  SMTP status + MX, and **`certifications[]`** — the champion is 6sense- and twice
  Demandbase-certified; two deep-research runs had that as NOT FOUND.
- **Name-scoped lookups only.** The 6-credit domain roster returned 10 sales/CS/finance seats and
  2 committee members; a STRICT full-name + domain search returned exactly the right person 3/3
  for 0.5 credit. Title filter is broken; `GET /v1/credit` is 401 (no balance endpoint); cached
  email verification is still billed.
- **Free primary sources beat the paid deep call at its own job:** the Ashby posting API (27 reqs
  with full descriptions) named the SDR stack and the 77-day-open ABM req; the deep call marked
  the stack NOT FOUND. Homepage testimonials named customers + CISOs the deep calls also missed.
- **Gemini media, run for real:** `gemini-3.5-flash-lite` silently LOOPED after 12:41 of a 42:49
  podcast, emitting confident fabricated timestamps (329 lines, 120 unique).
  `gemini-3.5-transcribe` re-ran it faithfully for less money — but returns text under
  `parts[].audioTranscription.text`, with no timestamps or speakers. Rule: two-model recipe +
  duplicate-line detector + every quote verified as an exact substring of the faithful transcript.
  YouTube costs 3.6× audio per minute (video tokens). Text embeddings cost 1/167th of raw-audio.
- A wrong-person video was transcribed ($0.006) and recorded as an explicit exclusion; identity
  for the true person was proven by a three-link chain before any claim was admitted.

### 1c. Code-level laws (from reading all 35 scripts) — see the porting list in §3.2
Plus one **law by counter-example**: the person run's "closed field catalog" was prompt-enforced
only and leaked pipe-joined keys (`contact.facet.recent_award|contact.facet.education_highschool`).
The catalog must be validated in code at write time (this is exactly the write gate R0 kept).

### 1d. The head-of-abm refinements program (Aryan, 2026-08-31)
- Its thesis is right and useful for Shashank's workstream: the agent is a "well-governed empty
  suit" — the gap is CONTENT (ABM canon, ideation craft, voice), not machinery. Three draft skills
  (`abm-craft`, `campaign-ideation`, `copy-voice`), a 20-line prompt delta, a corpus acquisition
  plan, and 10 founder decisions.
- **Three divergences from the v1 direction, all fixable by edits:** (1) every preference-capture
  line routes to **scoped memory**, which v1 parks — must become "record in project context";
  (2) `copy-voice` embeds a **reviewer lint + structural rubric judge** — a mechanical gate plus a
  secondary-LLM judgment, against the no-judges ruling; keep the em-dash and no-fabrication rules
  as prompt rules, delete the lint/judge lines; (3) it assumes Stage-0 recon and readiness floors
  persist — both are retired/reduced by R0.
- Silent on: `.md` onboarding research artifacts, 2–5 ICP proposals, the ICP artifact format,
  project context, the Exa MCP tool. Its audit baseline (prompt v4 / profile v38 / gpt-5.6-terra)
  is stale — live is **prompt v7 / profile v43 / grok-4.6** after the R0 merge, so its "v5 / v39"
  numbers become "v8 / v44".
- Infrastructure it assumes that does not exist: knowledge packs at `context/knowledge/`, an
  exemplar library, a voice linter, `make eval-abm`, a `corpus/` tree.

### 1e. The new presentation truth (`clue-frontend/chat-shell` @ `b24f547`)
- One commit past the copy studied on 2026-09-01: **the three fit sub-scores
  (`referralFit`/`directAccessFit`/`recallFit`) are deleted** and forbidden by a UI-contract pin;
  "Recall fit" survives only as the canonical example of a **`customFields[]` entry** — a
  workspace-defined variable system (`{id, label, value, presentation: text|badge|score, primary}`)
  "configured during onboarding or in Settings". **This is the sources-and-variables §2 custom-
  variables mechanism (= the field registry) rendered — the design and the architecture agree.**
- Added: `owner {id,name,avatarUrl?}` (a workspace user, not research), `industryLabels[]`
  (min 1 on detail), `headcountLabel`, `fitScore` now required on detail, `socials[]` (LinkedIn/
  Twitter/Facebook/Instagram), `createdAt`/`lastModifiedAt` (required ISO).
- Contacts: one real profile (hard-coded featured id), 13 display-only rows, email lookup is a
  fake timer, `emailStatus` never read — "in progress" as stated. Persona is a free-text string
  with 10 fixture values vs the backend's 4-enum and the seam draft's 5 — **one vocabulary is
  needed.**
- The co-founder's own `marketer.com findings` concede `/frontend/v1` as the production boundary
  ("do not revive this workspace's fixture fallback") — the serving strategy already ratified.

### 1f. Two coordination facts
- **Aryan's chicago branch (`install-agent-browser-global`) does NOT contain the R0 commits.** It
  merged `integration/design-improvement` at its pre-R0 state (`00f510f38`). R0 lives only as
  local commits on the semarang worktree (`aacdb977c`…`22556eceb`). **R1 cannot start on chicago
  until R0 is pushed and merged into the shared base.**
- Aryan's memory note (`_memory/2026-08-31-head-of-abm-refinements-program.md`) records that a chat
  transcript attachment on his worktree contained **two live API keys (Apollo, AI Ark)**. The
  attachment is untracked, but **rotate both keys**; add `CLUE_GEMINI_API_KEY` to `Secrets` +
  `.env.example` (parity rule) when the Gemini client lands.

---

## 2. What stands unchanged
R0 (complete); the keep/quarantine treaty; the two surviving gates (claim write-shape + human
authority) and the SENSITIVE-never-outreach floor; the R1→R5 order; Seam 1's launch signature;
"research never reads the conversation"; the frontend rules (dummy = presentation truth, re-lift
don't patch, serve via `/frontend/v1` + adapters, no new components); AI Ark in the
committee/enrichment slot, Apollo fallback-only, Sumble dead, Firecrawl out of research.

---

## 3. The delta, stage by stage

### 3.1 Pre-R1 (do first, this week)
1. Push R0 and merge it into the shared base before any R1 code (§1f).
2. Rotate the Apollo and AI Ark keys (§1f). Buy the AI Ark paid tier (free tier 429s at ~6 quick
   calls; production pacing rule stays ≥10 s until a paid tier is confirmed). Gemini key already
   exists (2026-09-02) — add to `Secrets` + `.env.example`.
3. **One small migration, scheduled now, not later:** `claim.signal_priority smallint NOT NULL
   DEFAULT 3 CHECK (1..3)` and `claim.outreach_safe boolean NOT NULL DEFAULT true`. Both runs
   depend on them; the frontend's "why now"/insights ordering depends on priority; the compliance
   floor depends on `outreach_safe`. (Optional same migration: `source_type` enum column; the
   rest of the PoC row extras — `claim_kind`, `media_url/timestamp`, `charter_category`,
   `source_field_path`, per-claim cost — ride `value_json` sub-fields or the existing
   provenance/lineage refs; no schema for them in v1.)

### 3.2 R1 — providers (content changes)
- **Drop the Apollo client from R1 entirely.** Fallback-only means "not built until needed".
- **AI Ark client laws (from `z_lib.py`/`z1*`):** `X-TOKEN` + browser UA + `Accept: application/json`;
  ≥10.5 s pacing; halt latch on 402/403/"credit"; envelope `totalElements`/`content[]`;
  **name-scoped only** (`contact.fullName` STRICT variants + domain include, size ≤3); email at
  `email.output[0].address` with `status/domainType/found/subStatus/mx.*` → `verified_smtp` |
  `catch_all_valid` | `not_found`; credits by result-count arithmetic (no balance endpoint);
  **`birth_date` scrubbed INSIDE the client before any persistence** (the PoC scrubbed after the
  raw write — not persistence-safe).
- **Exa client laws:** deep-reasoning request = `type=deep-reasoning`, `systemPrompt` (target lock +
  same-name exclusions), `numResults 20`, `contents.text 10000 + highlights`, `outputSchema` with
  exactly one string property `report`; **silent-fail guard in the tool** (`len(text)<3000 or
  (n_results<=9 and cost<=0.016)` → retry once); `includeDomains` is a measured per-angle choice,
  never a default; `/contents` on a YouTube watch URL is the free transcript path.
- **Free-source resolvers, promoted to first-class:** Ashby posting API (slug fallback list, read
  `descriptionPlain`, `publishedAt`, `isListed`, compensation), Greenhouse/Lever equivalents,
  podcast RSS (Apple lookup → `feedUrl`; exact episode-number match, not fuzzy), YouTube probe
  (`ytInitialPlayerResponse` for duration/title only; captions listing is dead).
- **Gemini media client (thin, used in R3):** `gemini-3.5-flash-lite` for short items with
  timestamps; `gemini-3.5-transcribe` for anything long (Files API resumable upload; read
  `parts[].audioTranscription.text`); duplicate-line loop detector; quote-mine + exact-substring
  verify; `gemini-embedding-2` 768-dim text embeddings (never raw audio); pull MP3 from RSS, not
  YouTube (3.6× cheaper). Cost from `usageMetadata` modality details.
- All clients: save-raw-before-parse → annotate → ledger; pre-spend estimate raised before the
  wire (`budget_guard`), which maps onto the platform's `external_research` ledger + pre-spend
  authority; retries honor `Retry-After` else 12·(n+1) s; media ceiling enforced (the PoC
  declared one and never checked it).
- **Exit gate (R1):** recorded live fixtures for every client above against Zafran + Probook;
  no claim writes yet.

### 3.3 R2 — the account agent (content changes)
- **Charter = the 10-section account dossier** with §9 "reputation and negatives" REQUIRED and an
  ALREADY-ESTABLISHED block so the agent never re-derives provider facts. Free-first ordering:
  ATS board → RSS → own site → AI Ark company + name-scoped people → Exa searches for gaps → ONE
  deep-reasoning call.
- **Two claim species, by construction:** deterministic claims assembled in code from provider
  fields (`source_field_path`, never through the LLM); synthesised claims from prose via
  `gpt-5-mini` (minimal reasoning, JSON mode, **one subject per call**), against the closed field
  catalog **validated in code**, with a `proposed_fields[]` escape hatch. Span verification =
  exact substring after normalization, fragments split on `…`; **failures are quarantined, not
  merely flagged** (the PoC only flagged).
- **New registered account fields (data rows, no code):** `account.hiring.gtm_open_roles` (G1,
  already planned) → generalize as `account.open_requisitions` (list of {title, dept, published,
  days_open, salary_band, still_listed, url}); `account.gtm_tooling_stack` with an explicit
  `absent[]` array (the flat `core.primary_tech_stack` cannot encode absence — v3 finding
  re-confirmed); `account.named_customers`; `account.reputation_risk` (born `outreach_safe=false`);
  `account.abm_program_maturity`; `core.legal_name`, `core.founded_year`.
- Unify the `use_class` vocabulary (three variants across the runs) to the platform's enum.
- **Exit gate (R2) unchanged in shape, widened in answer keys:** Probook (v3) AND Zafran
  (one-account run) researched end-to-end; ≥15 claims with quotes + URLs visible on the account
  detail screen; the deterministic/synthesised split and the negatives section present.

### 3.4 R3 — committee + contacts (the largest content change)
- **The personal-depth charter is the `contact-depth` skill**, verbatim in intent: background,
  life outside work only as self-stated, voice (3–5 verbatim quotes), professional identity,
  unique insight, three grounded openers, hard sensitivity floor.
- **Recipe (trimmed, measured):** 6 sweep angles (drop video-site/podcast-directory/Substack/
  awards/social — 27% of cost, 0 unique URLs), LinkedIn `/contents` + targeted follow-ups, ONE
  deep-reasoning call per person, ONE narrow unique-insight follow-up per person, one structuring
  call per person. Media layer **per person only when media exists** (3/10 do), one item each.
  Budget ~$0.07–0.10/person.
- **The compliance floor becomes a coded post-structuring pass (this is Part 3D's SENSITIVE floor,
  implemented — not a research veto):** minors clause absolute even when self-published; origin/
  nationality/faith recorded as biography only, `outreach_safe=false`, barred from hooks/openers;
  purge rows with no quote / no http URL / value NOT FOUND into `not_found[]`; every action logged.
- **New registered contact facets:** `contact.facet.hooks`, `.openers`, `.voice_quote`
  (`media_url` + `timestamp` sub-fields), `.certifications`, `.education_highschool`,
  `.self_summary`, `.excluded_lookalike` (same-name exclusions as durable audit evidence); source
  type `university_athletics`. `identity_binding` STRONG when AI Ark matched by LinkedIn URL.
- Media identity rule: verify who speaks (META block `guest_identity_evidence`) before quoting;
  company-named media is not a personal source until proven; LinkedIn/X-native video never fetched.
- **Exit gate (R3):** the 10-person set as answer key (person_*.md dossiers); a committee with
  verified emails + hooks/openers/voice quotes visible in the contacts screens per the new
  contract's slots (and honestly unserved where no slot exists yet).

### 3.5 R4 — discovery + fleet — unchanged
(Signal-first job-req search as primary angle; free ATS boards as decision-drivers; approval flow;
fleet fan-out. AI Ark company search as an optional cheap Pass-A skeleton.)

### 3.6 R5 — serving (target changed)
- **Serving target is `clue-frontend/chat-shell` @ `b24f547`, not the 2026-09-01 copy.** Gap 3
  (fit sub-scores) is **resolved by removal**. New backend asks: `customFields[]` = the field
  registry's custom variables (workspace-defined, per-response consistent `label`/`presentation`);
  `owner` (workspace user — CRM datum, never agent-written); `industryLabels[]` from
  `core.industry`/`industries_all` claims (min 1 forbids honest-empty → ruling); `headcountLabel`
  vs `employeeBand` (two renderings of one fact); `socials[]` (AI Ark `link.*` gives these free);
  `createdAt`/`lastModifiedAt` semantics (entity creation / last claim write).
- **Contacts serving:** `persona` free-text ↔ the ICP `persona_map` vocabulary (Seam 2, box 2c);
  `personaTone` and `influence` are display mappings (ruling: server-side mapping from persona +
  role confidence, or frontend-derived); `recentSignalsLabel` from priority-1 facet counts;
  `emailStatus` from the AI Ark email block; hooks/openers/voice quotes need the slot conversation
  (still unserved by the contract — record, don't invent).
- Insights feed ordering uses `claim.signal_priority` + date (§3.1 migration).
- Ruling list for step 7 is amended: gap 3 closed; add the six new fields above and the
  featured-contact hard-code removal; envelope stays `/frontend/v1` + BFF (conceded by the
  frontend's own research).

### 3.7 Workstream A (Shashank) — adopt the refinements content with three edits
1. Take the draft skills' substance (question canon, qualification floor, diagnostics, program
   numbers, ideation procedure, voice rules) but **replace every "route to scoped memory" line with
   "record in project context"** (project context is durable; that is exactly what those lines
   want).
2. **Delete the lint/reviewer-judge lines from `copy-voice`** (`SKILL.md:38, 98-99`); keep the
   em-dash and no-fabrication rules as prompt rules the agent applies itself. No secondary judge,
   no mechanical gate — per the ruling.
3. Drop the recon/readiness assumptions; rebase the prompt delta onto v7 → v8; mint profile v44
   (not v39); knowledge packs become project-context `.md` artifacts materialized into the
   workspace — which is precisely the `.md` onboarding-research design.
4. The corpus acquisition program (R1–R8 of file 09, decisions D1–D10) is **backlog after the
   onboarding rebuild ships**, except D6/D7 (voice rules) which ride the skill edits above.

### 3.8 The "gates keep popping up" complaint — closing the loop
R0 fixed the two kill-switch inversions and the readiness floor; the old lane is inert by one flag.
The remaining mechanical blockers on the legacy paths are enumerated (pre-spend authority gate,
canary needs-review suspension, contact identity admission floor, launch homogeneity, the Exa
cost-overrun quarantine, the agent plan-turn budget clamp, Stage-0 lane envelopes). **The ARV2
lane simply never calls any of them** — that is the structural fix, not more flags. They go on the
Phase-6 stub-and-delete list, executed only after the ARV2 lane has run in anger (trigger unchanged).
The PoC's own coded checks that DO survive are all write-side or compliance-side (closed catalog,
exact-substring spans, sensitivity floor, unevidenced purge) — none can veto research.

---

## 4. Seam-freeze amendments (applied to the DRAFT in this commit)
- **Box 1a:** recommend a small structured block in `directive_text` (effort rung full|reduced|
  cheap-pass; committee size cap) — the runs price the rungs ($0.155 / $0.086 / $0.015) and the
  refinements brief argues for an explicit ladder.
- **Seam 2 body sections:** add TAM/list-math estimate with the widen/tier/shrink choice;
  disqualifiers and red flags; closed-won/closed-lost patterns; the client's own wording; the
  qualification-floor verdict.
- **Box 2c:** the ICP `persona_map` is THE single persona vocabulary the skills, the research lane,
  and the frontend's free-text persona chips all speak; recommend adding `user` to the enum.

## 5. Founder decisions this delta needs
1. Ratify §3.1 (push R0; the two-column migration now).
2. Ratify §3.4's coded compliance pass as the implementation of the kept SENSITIVE floor.
3. Ratify §3.6's serving target = `chat-shell` @ `b24f547` and the amended ruling list.
4. Ratify §3.7's three edits to the refinements program; defer the corpus program.
5. Answer the three seam boxes (§4) at the joint session.
