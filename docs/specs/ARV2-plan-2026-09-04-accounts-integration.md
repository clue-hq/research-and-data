# ARV2 plan of action v2 (2026-09-04) — accounts research + display integration, and how the two founders work in parallel

**Status: proposed for founder ratification (Aryan + Shashank).** Supersedes the *sequencing* of
`ARV2-plan-delta-2026-09-03.md` §3 (its content findings stand); amends nothing in the ratified R0
plan. Written after reading, first-hand: the spec module `chicago/.context/frontend-page-content/`
(4 files), the display-layer control test (`chicago/.context/display-layer-control-test/REPORT.md`,
4 Sep), the port-of-spain frontend (`clue-frontend/port-of-spain` @ `6b623fe`, one commit on top of
the `chat-shell` truth `b24f547`, 28 files / +4,490), and the two PoC runs those specs are built from.

**Correction of record.** Git authorship settles the roles: the chicago PoC/spec commits are by
Shashank Keshri; this machine's git user is `akeshri003`. So **Aryan = the tech founder (this
session's user): platform deepagent, onboarding, brand context, ICP, project context, Exa MCP.
Shashank = the non-technical co-founder: account/person research PoCs, the frontend specs and dummy
frontend, and the accounts integration lane.** Earlier R0 documents used the two names the other way
round in places; read them by role. Everything below is written by role.

---

## 1. What the new work adds (verified)

1. **The display layer is now a designed product component, not a "labels pass".** The spec module
   fixes the page grammar: every page is a fixed template of H1 sections (product vocabulary, never
   model-written); each section has a **recipe** — the field keys it may draw from — held as config
   (registry rows, so a custom variable is just another key in a recipe); one `gpt-5.6-luna` call per
   section, fired in parallel; every sentence carries `claimIds[]`; the frontend renders a source
   chip by resolving `claimId → Evidence` (the model never sees or types a URL); `outreach_safe:false`
   claims reach only the "Do not mention" / "Context only" sections; an empty recipe is a real
   answer ("No {section} information found for {name}"); output is stored as a `display_block`
   row (page, section, subject, model, prompt version, cited claim ids, generated_at) and regenerated
   when a cited claim is superseded. Contact-page bodies end with a **send line** (the copy the user
   pastes; v2 seeds the email draft from it).
2. **The control test (4 Sep, 56 page runs, 11 models, blind judge) settles the open questions with
   data:** per-section beats whole-page on recipe discipline (0 off-recipe citations vs 3–6) and
   failure shape (a failed section = one retry, not a page); **no cheaper model passes** the two
   non-negotiables (unsafe leaks, non-verbatim quotes) — Luna stays; Luna is already the cheap layer
   (~5 cents per account with five contacts, ~$50 per 1,000 accounts vs ~$150+ research); **keep
   default reasoning effort** (at `low` it cited the unsafe hobby claim inside Openers in both runs
   and was not cheaper); the savings that matter are *when* pages regenerate (only sections whose
   claims changed; lazy P2/P3 contact pages; stable prompt prefix for provider cache — measured
   $0.0251 → $0.0077; `:batch` for nightly). **Two defects belong upstream in the claim store:** one
   fact → one `outreach_safe` flag (the cocktail hobby was stored twice with opposite flags), and
   dedupe near-duplicate unsafe rows.
3. **Port-of-spain (`6b623fe`) implements ~80% of that grammar** and is the presentation truth
   going forward: a `research-display.ts` model (`ResearchEvidence`, `ResearchSentence`,
   `ResearchItem` with `priority` + `sendLine` + `contactRefs` + `newSinceLastVisit`,
   `ResearchSection` with `restricted`/`defaultOpen`, `ResearchDisplayBlock`,
   `BuyingCommitteeMember`), new slots on account detail (`overviewDisplay`, `researchEvidence`,
   `buyingCommittee`, header/rail labels), on the workspace (`insightsDisplay`, `insightSummary`),
   and on contact detail (`contactDisplay`, `reports`, rail labels); Zafran as a second fixture
   account (37 evidence rows, overview 5 sections/20 items, insights 6/21, Nick's contact page
   5/20 with 15 send lines); the featured-contact hard-code generalized via `profileAction`; lint,
   build and the 50 tests green.
4. **The "trimmed off" complaint has a precise cause list (18 cut points).** The big ones: the account
   overview renders **only the "Why now" section** (`account-research-overview.tsx:20-22`) — 17 of
   20 overview items (What they do, Why they fit, How to approach, Watch-outs) never render; the
   digest is a hard `slice(0, 3)` and one sentence per item (`research-content.tsx:781-785`);
   every section shows 3 items then "Show N more" (`:436-438`, positional, not the spec's
   "P1/P2 visible, P3 collapsed"); sections are **tabs, one visible at a time** (`:682-760`) where
   the spec describes a stacked document; the hover-card quote is clamped to 4 lines; and several
   served fields are silently dropped (`section.empty` — no empty-state line; `outreachSafe`;
   `emailClaimId`/"✓ verified {date}"; per-item "new since last visit" divider). Full list with
   file:line in §4.
5. **Drift to rule on:** the commit shipped **zero** changes to `docs/api-contracts/accounts.md`
   (every new slot is undocumented — against the house rule); it added components beyond the spec
   (tab strip with per-section tones and hard-coded summary sentences; a channel-relabel map; a
   contact-page H1 retitle map that hard-codes "he/him"; a "+N" source carousel per sentence where
   the spec says one chip per clause); `insightSummary` is a literal ("42 insights" over 21 items);
   the detail rail shows `fitScoreLabel "—"` while the list shows 88.

## 2. Reflection — what changes in the plan and why

**Stands:** R0 (done); the treaty; the two gates + the coded SENSITIVE floor; AI Ark name-scoped /
Apollo dropped / Gemini two-model media / ATS-first; the R1–R4 *content* in the 09-03 delta; the
`signal_priority` + `outreach_safe` migration; frontend rules (dummy = truth, re-lift don't patch,
serve via `/frontend/v1` + adapters, contracts recorded).

**Changes — one big one.** Yesterday's sequence put "serving" last (R5). The spec module + control
test + port-of-spain make the display layer a *finished design with real data behind it*
(`claims_zafran.json` + `claims_people.json` are real, sourced claim rows), while the research lane
(R1–R4) is weeks of build. Waiting for the lane before the frontend sees real backend data is the
wrong order for two reasons: (a) it starves the co-founder's integration lane of anything to
integrate, and (b) the display layer is the seam that proves the whole contract. So the accounts
work splits into **two tracks that meet at the claim store**:

- **Track D — display + frontend integration, starting now.** Load the PoC claims into the real
  claim store through the real write path (the closed catalog validates them; the loader is the
  first "research writer"), build the display layer (recipes, Luna section runner, `display_block`),
  serve the five payloads the port-of-spain contract expects, re-lift the accounts feature, and prove
  Zafran end-to-end on the real backend with the spec module's pages as the answer key.
- **Track R — the research lane (R1–R4 as amended 09-03).** When it lands, it replaces the loader
  as the writer. Nothing in Track D changes, because both write the same claim rows.

This also fixes a role problem: Track D has a large share of work a non-technical co-founder can
drive through agents (contract recording, fixtures, section recipes, prompts, acceptance pages,
frontend re-lift), while the integration-critical backend pieces (migration, loader, read surface,
composition) are small, bounded, and sit with the tech founder to build or review.

## 3. Contract v1 = the port-of-spain models, with backend-owned semantics

The five payloads (`account list`, `account detail`, `account workspace/insights`, `contacts list`,
`contact detail`) and the shared `ResearchEvidence` / `ResearchDisplayBlock` are frozen as **contract
v1** exactly as `port-of-spain/src/features/accounts/model/*.ts` defines them — after the D0 rulings
in §4 are applied. Semantics the backend owns (the frontend must not re-derive):

| Wire field | Backend rule |
|---|---|
| `ResearchEvidence` | one row per claim cited anywhere on the page; `claimId` = claim id, `quote` = `evidence_span`, `sourceUrl` = `source_url`, `verifiedAt` = `observed_at`, `publishedAt` = source date when known, `mediaTimestamp` from the claim's media sub-fields, `outreachSafe` = the claim column, `provider` = source provider (hover only), `sourceDomain` + `faviconUrl` **resolved server-side** (never built client-side), `title` = page title when captured |
| `ResearchItem.priority` | the best (lowest number) `signal_priority` among the item's cited claims; P1 sorted first inside a section; P3 collapsed by the client |
| `ResearchItem.sendLine` | contact page only; Luna writes it as a separate field (control-test lesson: never inside quotation marks) |
| `ResearchSection.empty` | true when the recipe matched no claims; Luna is not called; client prints the empty line |
| `restricted` sections | `do-not-mention` / `context-only` / `watch-outs` are the only sections that ever receive `outreach_safe=false` claims |
| `BuyingCommitteeMember.email` + `emailClaimId` | from the `core.work_email` claim; the "✓ verified {date}" chip resolves `emailClaimId` |
| `insightSummary` | computed: `{n} insights` = items across non-restricted sections; `Updated {date}` = latest `observed_at`; `{n} new` = items newer than the viewer's last visit |
| `newSinceLastVisit` | needs a per-user last-visit timestamp (a small `account_visit` row) — or ship `false` in v1 and rule it deferred |
| `h1` per section | product vocabulary, served by the backend from the recipe config; the client must not retitle |
| `customFields` | registry custom variables (workspace-defined); values are claims; `presentation` from the registry row |

Not on the wire by design: `field_key`, `use_class`, `source_type` — the contract is display-shaped;
generic `fieldKey` rendering exists only for `customFields`. Record this as a ruling, not an accident.

## 4. D0 rulings — the truncation and drift list (founders decide, one line each)

| # | Cut / drift (file:line in port-of-spain) | Recommendation |
|---|---|---|
| 1 | Overview renders only "Why now" — 17 of 20 items never shown (`account-research-overview.tsx:20-42`) | **Show all five overview sections, stacked, in spec order**; keep "Open all insights" |
| 2 | Digest `slice(0,3)` + one sentence per item + chips dropped (`research-content.tsx:781-785`) | Keep "top 3" for Why now only; render full bodies + chips |
| 3 | 3 items per section then "Show N more", positional (`:436-438, 674`) | Replace with priority collapse: P1+P2 visible, P3 under "Show N more" |
| 4 | Sections are tabs, one visible (`:682-760`) | Stacked document with all H1s visible; only `restricted` sections collapsed by default (contact page: always open) |
| 5 | Hover-card quote clamped to 4 lines (`account-research.module.css:518-527`) | Show the full verbatim span (it is the evidence); expand inside the card |
| 6 | Source chip 152px ellipsis (`css:352, 389-393`) | Accept; popover carries the full label |
| 7 | Rail contacts 3 of N with "See all" (`account-detail-screen.tsx:115`) | Accept; add the count line "Contacts · 5 (4 with verified email)" |
| 8 | Rail "See all" collapses Founded/Funding/socials/secondary custom fields (`account-detail-primitives.tsx:169-340`) | Accept as progressive disclosure; promote Founded + Funding to the visible set |
| 9 | H1 retitle maps + channel relabel map + hard-coded "he/him" (`research-content.tsx:471-535, 297-306`; `contact-profile-content.tsx:77-86`) | **Delete the maps**: the payload `h1` and `sendLine.channel` are the vocabulary; never gendered titles |
| 10 | Unrendered served fields: `section.empty`, `outreachSafe`, `emailClaimId`, `emailState`/`persona` on chips, per-item new-since divider | Implement all five before serving starts (they are in the spec) |
| 11 | "+N" source carousel per sentence vs spec's one chip per clause (`:139-172, 268-285`) | Founder taste call; recommend spec (one chip after the clause it supports) |
| 12 | `insightSummary` literal "42 insights"; `fitScoreLabel "—"` vs list 88; email chip found by substring match (`contacts.ts:518-520`, `account.ts:91-92`, `contact-profile-content.tsx:72-76`) | Fixture bugs — computed by the backend per §3; remove the client heuristics |
| 13 | Zero contract-doc changes for ~40 new fields | Record contract v1 in `docs/api-contracts/accounts.md` (D0 task) |

## 5. The display-layer build (Track D) — what gets built

- **`display_block` table (one migration, alongside `signal_priority` + `outreach_safe`):**
  `(workspace_id, subject_kind account|contact, subject_id, page, section_key, body_json, cited_claim_ids[],
  model, prompt_version, generated_at, superseded_at)`.
  **Generation policy (founder ruling 2026-09-04):** a section is generated **once, on the first
  request** for that page/subject (lazy — an unopened contact page costs nothing; the first open
  waits ~15 s for the parallel section calls), then **persisted and served as-is on every later
  visit**. It is regenerated **only on invalidation, and only the affected sections**. Invalidation
  is **recipe-scoped, not cited-claim-scoped**: a section is stale when any claim for that subject
  whose `field_key` is in the section's recipe is added, superseded, or has its `outreach_safe`
  flag changed — or when the recipe/prompt version changes (cited-claim-only invalidation would
  miss a brand-new matching claim). On invalidation, serve the persisted block and regenerate in the
  background (stale-while-regenerating), swapping the new row in when it lands. No scheduled
  regeneration; `:batch` only for an accumulated invalidated set.
- **Section recipes as config** (registry-backed rows): `(page, section_key, h1, order, allowed_field_keys[],
  restricted, default_open, instruction_version)` seeded from the spec module's recipe table (README §2).
- **The Luna section runner:** stable prefix (system + client context + claims) / section suffix;
  parallel per section; JSON output = the `ResearchSection` shape; **three prompt lines from the
  control test** (never type claim ids into prose; dates as "17 June 2026"; the hobby hook at most
  once per page); mechanical post-checks in code, not the model: every quote ≥4 words is a substring
  of a cited claim's quote/value; every number ≥13 appears in the claims; every claim id valid and
  on-recipe; unsafe rows never cited outside restricted sections; a failed check = regenerate that
  section once, else `empty` with reason. This rides the Lane-E prose skeleton (idempotent per
  subject/section, supersede-on-regenerate).
- **Evidence resolution** server-side: `claimId → ResearchEvidence` incl. domain + favicon (cached)
  + page title (from the snapshot when captured); the presign/scope gate stays as recorded in CLAUDE.md.
- **Read surface:** the five payloads on `/frontend/v1` (existing router, workspace-scoped), with the
  port-of-spain repository adapters pointed at them (`/api/v1` paths → `/frontend/v1` + BFF header,
  the ruling already conceded by the co-founder's own marketer.com notes).
- **The claim loader (D1):** a governed one-off writer that turns `claims_zafran.json` +
  `claims_people.json` into real claims through `insert_claim` (registering the PoC's new field keys
  first, unifying `use_class` to the platform enum, stamping `signal_priority`/`outreach_safe`,
  run lineage for the project lens, snapshot artifacts for media transcripts). Upstream fixes from
  the control test applied here: one fact one flag; dedupe near-duplicate unsafe rows.

## 6. Tracks, owners, exit gates

### Track D — display + frontend integration (co-founder drives; tech founder integrates)
| Step | What | Owner | Exit gate |
|---|---|---|---|
| D0 | Rulings §4 recorded; contract v1 written into `docs/api-contracts/accounts.md`; port-of-spain components fixed per the rulings (stacked sections, priority collapse, maps deleted, empty lines, chips) | co-founder via agent; tech founder signs | port-of-spain green (lint/build/test); Zafran renders every section from fixtures |
| D1 | Migration (`signal_priority`, `outreach_safe`, `display_block`) + the PoC claim loader | tech founder (agent-built, founder-reviewed) | 174 + 119 rows in the store, catalog-valid, lineage-pinned; `make db-smoke` green |
| D2 | Section recipes config + Luna section runner + mechanical checks + evidence resolver | agent under tech-founder review; co-founder owns prompts/recipes | Zafran overview/insights/Nick pages generated from the store; checks 0/0/0 (leaks, non-verbatim, off-recipe) |
| D3 | Read surface: the five payloads on `/frontend/v1` | tech founder | payloads validate against port-of-spain Zod models byte-for-byte |
| D4 | Re-lift port-of-spain accounts feature into `apps/frontend`; adapters → `/frontend/v1`; no new components | co-founder via agent | `CLUE_API_BASE_URL` set: Zafran pages render from the real backend; fixtures still demo offline |
| D5 | Acceptance: the spec module's three Zafran pages vs the live pages, section by section; the four remaining contact pages generated lazily | both founders | founder walk-through signed; drift list empty |

### Track R — the research lane (co-founder drives specs/skills/answer keys; agents implement; tech founder reviews composition)
R1 providers → R2 account agent → R3 committee + contacts → R4 discovery + fleet, exactly as amended
in `ARV2-plan-delta-2026-09-03.md` §3.2–3.5, with one addition: **R2/R3 write the same claim rows
D1 loaded**, so D2–D5 need no change when the lane goes live. Exit gates unchanged (Probook + Zafran
answer keys; the 10-person set). Sequence relative to D: R1 can start the day D1's migration lands.

### Track O — the tech founder's own lane (unchanged)
Onboarding as research pipeline, ICP `.md` artifacts, project context, Exa MCP, brand context; the
refinements skills adopted with the 09-03 edits; the chat-shell output-pane motion handoff
(`chicago/.context/output-loading-animation/handoff/`) lands in `apps/frontend` under the same
no-invented-components rule.

## 7. Operating model for a non-technical co-founder (how Track D and R actually get executed)

1. **Every task is a written charter before any agent runs:** goal in one sentence; inputs (exact
   files/paths); the exact files the agent may touch; the exit gate (a command or a screen check);
   the rule "if you must decide something not in the charter, STOP and ask"; and where the raw
   evidence goes (`.context/<run>/`). The PoC BRIEF.md files are already this shape — keep it.
2. **Agents never merge.** They commit on a task branch; the tech founder reviews at the four
   integration points (migration, loader, read surface, composition) and merges to the shared base.
   Frontend-only and docs-only charters can be reviewed by the co-founder against the exit gate.
3. **House rules restated for every charter:** no invented components (presentation truth = the
   dummy); every new flag in `.env.example` in the same commit; contracts recorded in
   `docs/api-contracts`; save raw before parse; no keys in artifacts; no push without review.
4. **Cadence:** daily merge of the shared base (both founders pull before starting); one founder
   ruling session per week with the open-decision list; every run's cost ledger reviewed.
5. **Verification is first-hand:** every agent report is spot-checked by whoever signs the gate (the
   pattern that caught the three merge defects and the eleven pre-existing test reds).

## 8. The first ten steps, in order

1. Push R0 and merge into the shared base; rotate the Apollo and AI Ark keys. *(tech founder)*
2. Founder session: §4 rulings (13 lines), the three seam boxes, the four compliance floors. *(both)*
3. D0: fix port-of-spain per rulings; write contract v1 into `accounts.md`. *(co-founder + agent)*
4. D1: the migration + claim loader; Zafran + the 10 people in the store. *(tech founder + agent)*
5. R1 charters written from the 09-03 delta §3.2 (AI Ark, Exa, ATS, Gemini clients). *(co-founder)*
6. D2: recipes + Luna runner + checks; Zafran pages generated from the store. *(agent, tech review)*
7. D3: the five payloads on `/frontend/v1`. *(tech founder)*
8. D4: accounts feature re-lift + adapters; first real-backend render. *(co-founder + agent)*
9. R1 build starts on the merged base (parallel to D2–D4). *(agent, tech review)*
10. D5 acceptance walk-through; then R2 starts with the display layer already live. *(both)*

## 9. Founder decisions this plan needs
1. Ratify the two-track split (§2) and Track D before Track R goes live.
2. The 13 D0 rulings (§4).
3. Contract v1 = port-of-spain models + §3 semantics (incl. "no fieldKey on the wire" as a ruling).
4. The `display_block` migration bundled with `signal_priority` + `outreach_safe`.
5. `newSinceLastVisit`: ship `false` in v1 or add the visit row now.
6. The operating model (§7), especially "agents never merge; the tech founder owns the four
   integration points".
