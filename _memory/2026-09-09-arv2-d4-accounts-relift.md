# ARV2 D4 — the accounts re-lift into `apps/frontend` (the screens now read the real backend)

Date: 2026-09-09. Branch `track-d4`, worktree `managua`, base `origin/integration/design-improvement`
@ `a758b5b1f` (D2, D3, R2 merged). Plan:
`docs/superpowers/plans/2026-09-09-arv2-d4-accounts-relift.md`. SDD ledger:
`.superpowers/sdd/2026-09-09-arv2-d4-accounts-relift/progress.md` (per-task reports beside it).
Spec: `ARV2-MASTER-PLAN.md` §6/§7/§8/§9 D4, `ARV2-DATA-SOURCE-MAP.md` §1/§6, work-split S8.
Source of truth for presentation: the design build `clue-frontend` `integration/live-backend-v1`
@ `84f8ee7` (read-only). Operating rule: implementers were Opus subagents; **every review was the
controller's own, first-hand** (founder memory 2026-09-02); never `git stash`.

D3 gave the five accounts screens a backend. **D4 gave the backend its screens.** The dummy's
accounts feature is now `apps/frontend`'s accounts feature, reading `/frontend/v1/…?contract=v1`
through the authenticated BFF, with the sixteen client-side derivations gone. **No backend
behaviour changed** — the FI-2 deletion is a follow-up PR.

## The governing constraints (read these first)

- **Presentation truth is the design build.** Components were lifted, not rewritten; nothing was
  invented; anything without a designed slot stays unserved. Where a lifted file changed, the change
  is one of three kinds: the model amendments, a §6 derivation removal, or the transport swap.
- **Contract v1 on the wire, exactly.** `model/*.ts` are the amended D3 Zod byte-for-byte, and they
  are now *also* the Python parity oracle's source (`tests/api/contract_v1/zod/` deleted).
- **`?contract=v1` on every request**, including `/workspace` which has only ever served v1 — one
  request shape, and a typo'd value fails identically everywhere.

## Founder rulings 2026-09-09 (plan Global Constraint 2), binding

| | Ruling |
|---|---|
| 2a | The full CSS re-sync of every feature from the design build is **its own later job**; D4 does the additive token merge only. |
| 2b | Keep the FI-2 bulk actions with **exactly two** options — add to project, send to chat. Remove the bulk email lookup. Keep the single-contact email-lookup button. |
| 2c | Keep the design build's **browser-side** search / filter / sort / pagination and its UI — no server paging in the table. |
| 2d | Keep the **typed recovery screen**. |
| 2e | **Drop the Band-2 views** (`account-facts`, `evidence-list`, `table-pagination`, `account-avatar` and their models/formatters) — nothing of them survives. |
| 2f | Keep **create-account** as a local, non-optimistic draft: every unknown field blank / `"Unknown"` / `null`, never an invented score or band. The write endpoint is a recorded follow-up. |
| 2g | The sidebar profile derives from the **protected session** — no settings feature is ported. |
| 2h | A **fixture mode behind one explicit flag** for demos; the live path has **no fixture fallback of any kind**. |
| 2i | The backend FI-2 branch deletion is a **follow-up PR**. |
| 2j | Spend on generating the four remaining contact pages is approved. |

## What landed, per task (commit shas)

| Task | Commit(s) | What |
|---|---|---|
| — | `7a493f149` | The plan. |
| 1 | `24061965a` | The design-system port: the design build's package replaces ours (`source/production`, its `build-tokens.mjs`; `tokens.css` regenerates **byte-identical** — `cmp` clean), plus `generated/legacy-compat.css` — the **48** variables only the pre-D4 token set defined, extracted once by `scripts/extract-legacy-compat.mjs` and imported in `app/layout.tsx` right after `tokens.css`. `src/design-system-tokens.test.ts` asserts every `var(--clue-…)` under `src/` resolves, with a **shrink-only** allowlist for two pre-D4 dangling names. |
| 2 | `42442251e` | The lift: 131 files (59 added, 19 deleted, 53 modified) — the feature, the eight `(protected)/accounts/**` route bodies, the new accounts `layout.tsx`, `AccountsLayoutShell`, `workspace-profile-context.tsx`, the `/api/source-favicon` proxy, `model/workspace-profile.ts`, `data/repository-mode.ts`. Band-2 views gone (grep guards 0); no `CLUE_API_BASE_URL` in the feature; no settings imports; the flag read in one module; live selectors threw the Task-4 placeholder; the layout renders session recovery → accounts recovery → shell. |
| 3 | `2c085bee1` + `77ab5a4dd` | The oracle re-pointed at `apps/frontend`'s models and `tests/api/contract_v1/zod/` deleted; then the models = contract v1 byte-for-byte, the **sixteen §6 derivations** removed (16 guards RED→GREEN in `account-ui-contract.test.ts`), fixtures on contract keys with bare `h1`s, the profile fallback fixed. |
| 4 | `25d23e562` | The five live adapters on `fetchRead` with `contract=v1`; E1 cursor paging (`limit=200`, cap 25 pages); `{data}` parsing; record-404 → `null`; no fixture fallback; the committee-slot rule; docs updated. |
| 5 | `fff60995c` + fix `69347eeda` | The kept behaviours: the bulk toolbar (add to project / send to chat) ported onto the design build's components with its own CSS-module vocabulary; the real start-and-poll email lookup; the non-optimistic local create; the contact-side bulk pieces deleted. |
| 6 | (no code) | Step 1: the four remaining contact pages generated live. Step 2: the rendered walk — `.superpowers/sdd/2026-09-09-arv2-d4-accounts-relift/task-6-report.md`. |
| 7 | this note's commit | The records and the close-out. |

## Rulings taken during execution (from the SDD ledger, in order)

1. **(pre-flight)** The two token misses that exist in the design build's own `tokens.css` are
   **recorded, not fixed** — presentation truth. T1's resolution test covers `src/**`, so T2's
   lifted CSS is checked once it lands.
2. **(T2) `Button` gains the design build's `transparent` variant and `md` size as ADDITIVE entries
   only** — the existing variants stay byte-identical. The whole-Button port belongs to the CSS
   re-sync job (ruling 2a). Cost if wrong: two entries to remove.
3. **(T2) `avatarColor` = the design build's one avatar colour (`#8343A5`).** Plan decision 4's
   hashed palette is dropped — no palette exists in the design build and no lifted component reads
   the colour. Presentation truth beats an invented palette.
4. **(T3) The overview's served `buying-committee` section duplicates the committee TABLE** the
   design build renders at that slot. The frontend renders the **table** in the `buying-committee`
   slot and drops the section's generated items (they restate `whyTheyMatter`); when a block omits
   the section, the split falls back to `how-to-approach`. Recorded for D5 — a later ruling may drop
   the recipe section entirely. Implemented in T4 as rendering rule (e).
5. **(T5, controller finding) Selection must persist across search / filter / sort** — the design
   build's behaviour. The port had copied the pre-lift controller's clearing. Fixed in `69347eeda`:
   plain setters restored, `clearSelection` only after a successful add-to-project or the explicit
   control, and `visibleSelectedAccountIds` drives the bar / submit / handoff.
6. **(T5, controller finding) The email-lookup poll needs a ceiling** — the pre-lift behaviour
   polled forever. Capped at **40 polls** (3s apart, ~2 minutes) with an honest timeout state; also
   fixed `presentEmailLookup`'s error-before-pending ordering.
7. **(T5, accepted)** `emailLookup` dropped from the bulk item model (nothing reads it once the
   bulk email action is gone); the add-to-chat dialog was exercised but not driven to completion —
   pressing through creates a thread and a composer draft, which is project-flow territory (D5 walk).
8. **(T3, accepted beyond brief)** `formatTenure` moved into the Zafran fixture (it is the
   backend's label to write, and the fixture pins it to `RESEARCHED_ON` instead of the browser
   clock); a `loadAccountContact` server action was added so the contacts drawer opens on row click
   (§6 item 15 removed the `profileAction === "preview"` scan that used to pick a featured contact).
9. **(process)** Never `git stash` on this stack — a temporary WIP commit or a second worktree.

## The live checks (all against the real store, no seeded payloads)

**T4 — the five routes from the real backend.** Backend `clue_api.projections_main` on
127.0.0.1:8072 (`CLUE_FRONTEND_READ_ENABLED=true`, `CLUE_ARV2_DISPLAY_GENERATE_ON_READ=false`, no
provider keys), frontend `next dev` on localhost:3025, fixture mode off. `/accounts` served the four
real workspace accounts; the Zafran overview served six sections with the committee table in its
slot and `—` for the unscored fit; insights, contacts and Nick Fisher's page all rendered from the
store. With the flag on, the design build's fixtures rendered instead.

**Dev-identity rows planted in the worktree DB (T4, still in place).** The worktree DB
(`clue-pg-managua` :55060) had **zero `platform_user` and zero `workspace_membership` rows** —
nobody had ever signed into this stack — while the ARV2 data lives in `ws_arv2_answer_key`. The
implementer inserted the founder's dev identity so the runbook sign-in could resolve a workspace:
`platform_user usr_4d8ed1e26919437594a856f78a1e3381`, one `auth_identity` for the Clerk dev subject,
and `workspace_membership wsm_d4acceptance00000000000000000001` → `ws_arv2_answer_key`, role
`owner`. **Dev-only rows on a synthetic DB, deliberately left in place** so the walk and D5 can sign
in. `.env` was untouched; both flags were overridden in the launcher only.

**T5 — the bulk action against the real endpoint, twice.**
`POST /frontend/v1/accounts/bulk-actions/add-to-project → 200`. First press returned the truthful
**"2 already in project"** (all four accounts had been seeded into `prj_arv2_answer_key` on
2026-09-07, so `unchanged: 2` is the correct answer and the idempotent path is the one that ran). To
exercise the *added* path the implementer deleted UPTIQ's seeded membership row, reloaded, and
pressed again: **"1 added · 1 already in project"**, the row written back at `2026-09-08 11:55:49Z`.
Net DB state restored — all four are members, only UPTIQ's `added_at` moved (verified first-hand
after the review). The **email lookup's honest failure is the pass**: the real
`POST …/email-lookup → 503 EMAIL_LOOKUP_UNAVAILABLE` (no provider configured locally) surfaced as a
disabled "Email enrichment unavailable" on that one row while the other four still said "Look up".
The local draft rendered as "Northwind Roboti… **Not saved yet**" with no fit, no score, `Unknown`
bands, `Not started`, and no checkbox.

**T6 step 1 — the four remaining contact pages, generated live (ruling 2j, controller-run).** Via
the D2 CLI against the worktree DB: **Vari Kaur $0.0127, Sanaz Yashar $0.0134, Tom Anthony $0.0103,
Ben Seri $0.0098** (~$0.046 total). Each 5/5 sections, none empty, none failed. `display_block` now
holds **37** live blocks. The SQL leak check — an `outreach_safe=false` claim cited outside a
restricted section, over all 37 blocks — printed **0**. Outputs `.artifacts/arv2/display-<name>.json`
(git-ignored).

**T6 step 2 — the rendered walk.** 12 routes + 6 interactions from the real backend, 19 screenshots
in `.context/d4-acceptance/` (untracked). **No money was spent**: `max(display_block.generated_at)`
predates the backend's start. Every exit-gate check passed — the committee table sits in the
`buying-committee` slot; source chips resolve (a real favicon for `zafran.io` through the proxy
route, the neutral lock + `Record` fallback for provider records) and the hover card opens with its
evidence quote; restricted blocks sit behind the "Internal notes" control on both pages that have
one; `h1`s render bare; every opener carries its "In your email" send line with a working `Copy`;
all merged tokens resolve and nothing is unstyled. **Restricted-content leak check with Internal
notes closed: none of the unsafe strings appears anywhere on the overview, the insights page or a
contact page.** The **only** console error on any route — and the only non-2xx/3xx request of the
whole walk — is the app shell's `GET /api/clue/api/v1/projects/sidebar → 404`:
`clue_api.projections_main` does not mount the projects API, so it is an artefact of this standalone
acceptance stack, not the accounts read surface.

## The drift list — D5's input (recorded, not fixed)

Section-by-section against `.context/frontend-page-content/ZAFRAN-PAGES.md`; wording differences are
excluded by design. Full text with screenshot references in the T6 report.

**The three that matter most**

- **D1 — the Revenue rail fact prints machinery text and overflows.** The overview, the contacts tab
  and the preview drawer all render
  `amount_max: 25000000; amount_min: 10000000; as_of: 2026-08-22; currency: USD; estimate_kind:
  provider_estimate`; the reference expects `Revenue: $10–25M`. It is clipped at the rail edge and
  runs past the drawer's right edge. Backend fix (D3 follow-up 5: `revenue_label` / `funding_label`
  over the registry objects' own keys). Every other structured rail value formats correctly.
- **D2 — contact emails exist in the data but render nowhere.** `claim.core.work_email` holds
  `nick@`, `vari@`, `sanaz@`, `tom@zafran.io` (and `core.company_email` on the account). Live: no
  email string appears on any contact page (regex-checked), the contacts table's Email column is
  off-screen, and the committee Reach column prints `Not requested` for all five. Four verified
  reach facts invisible — the D3 finding (no `core.work_email` verdict writer) reaching the screen.
- **D3 — persona and provenance render as raw pipeline strings.** `economic_buyer`,
  `technical_evaluator`, `champion`, `user` printed as enum literals in the committee table (wrapping
  mid-word: `economic_buye / r`), the contacts table and the contact H1 chip; the committee "Why they
  matter" column prints research machinery as prose ("role derived from the committee persona
  recorded by the name-scoped AI Ark lookup" ×3).

**The rest**

| # | Where | Drift |
|---|---|---|
| D4 | Insights → Buying signals | The insight body quotes raw claim JSON (`"open_reqs_total: 27; published_last_30_days: 9; …"`). |
| D5 | Source hover card | Footer prints the raw pipeline method id `structuring_pass`; a public `zafran.io` URL chip is labelled "Verified **private** record". |
| D6 | App shell sidebar footer | The hard-coded literal `Aakash Shrivastava` at `apps/frontend/src/components/shell/app-sidebar.tsx:119`, shown on every accounts page while signed in as someone else. The accounts feature's own `getWorkspaceProfile()` resolves this correctly; the shell bypasses it. |
| D7 | Insights → Internal notes | The Cisco and Amex Ventures strategic investments are classified **restricted**; the reference explicitly rules the investments safe to reference (only the acquisition rumour is not). Two usable buying signals buried. |
| D8 | Internal notes (insights) | Every item repeats "This is restricted context and must not be used in outreach." under a block already headed "Do not use in outreach" — 8 identical restatements. |
| D9 | Internal notes (both pages) | The block has no `Internal notes` heading of its own; the only occurrence of that string is the toggle-button count. |
| D10 | Overview / insights / contacts | Everything past the second section is a **collapsed accordion by default** (the committee table, Why now, How to approach, all four contact sections). The reference presents them open. |
| D11 | Overview rail | `Overall buying fit —` / `Fit Score —` (reference: `Overall fit: High`). The `Why they fit` H2 carries an inline `Overall fit: —` badge inside the `<h2>` element, so `h2.textContent` reads `Why they fitOverall fit:—` although it renders as a separate pill. |
| D12 | Overview rail | No `Custom` block at all (the client's registry variables); also absent: Founded, HQ, Funding, LinkedIn/X links, and the "Contacts · 5 (4 with verified email)" / "Activity" summary lines. |
| D13 | Overview rail → Contacts | Shows 3 of 5 plus `See all`; the reference shows all five. |
| D14 | Overview | No `Watch-outs` section — correct per the task's own rule (restricted must be absent from the overview) but a structural difference from the reference. D5 decides whether the overview gets an Internal-notes control like the other two pages. |
| D15 | Committee table | Vari Kaur's Title prints a machinery aside: `Head of Growth Marketing (Varinder / Vari Kaur referenced as Head of Growth Marketing)`; the same string labels her contact chip in Insights. |
| D16 | Committee personas | Sanaz Yashar is `economic_buyer` (reference: Executive sponsor) — two economic buyers; Tom Anthony is `user` (reference: Adjacent buyer). |
| D17 | `/accounts` table | Zafran's six industry chips are squeezed into the Industry column and truncated to unreadable stubs (`co…`, `r…`, `c…`); Overall fit and Fit score are `—`. |
| D18 | `/accounts/<id>/contacts` | The table is clipped at the rail edge after `Influence` with no visible horizontal scroll (Email and later columns unreachable); the rail renders only `Core` + `See all` and leaves ~250px empty (no Contacts / Activity blocks, unlike the overview). |
| D19 | Insights top strip | `17 insights · 5 people` (reference: `42 insights · 5 people · Researched 2 Sep 2026 · 3 new since your last visit`). No researched date in the strip; no "new since your last visit" divider. |
| D20 | Contact page header | Only name + persona chip. The reference expects the full header line (title, persona, location, verified email, LinkedIn followers, tenure). The follower count, creator badge, education and tenure are present but hidden behind `See all details`; `Best first channel` and `Reports: Vari Kaur` are absent entirely. |
| D21 | Nick Fisher → Openers | Three openers; the reference expects five including the cocktail-chemistry personal hook it calls "strongest, and safe". A generated-content difference. |
| D22 | Ben Seri | A full four-section page for a contact the reference says to skip, and its lead insight prints pipeline confidence as prose ("the committee role is **marked as plausible**"). |
| D23 | Activity | Ten rows, all relative times, no absolute dates in words; five rows read "Clue contact generated" with no contact named, so they are indistinguishable. |
| D24 | Environment (not a page defect) | The projects-sidebar 404 above, which also raises Next.js's red `1 Issue` dev overlay in every screenshot. Recorded so D5 does not chase it. |

**Layout glitches, collected:** the Revenue chip overflows both the rail and the drawer (D1); the
persona enum wraps mid-word (D3); industry chips truncate to single letters (D17); the contacts
table is clipped with no scroll affordance beside a large empty rail (D18); the sidebar profile row
is clipped by the viewport bottom edge at 1440x900.

**No broken links:** every committee Person cell resolves to a real contact route, LinkedIn chips
point at real profile URLs, and the favicon route answers 200.

## Close-out gate (2026-09-09)

| Gate | Result |
|---|---|
| `npm run design-system:build` | pass (regenerates `tokens.css` unchanged) |
| `npm run lint` | **0 errors**, 2 warnings — both pre-existing, in `features/design-editor/engine/scene/canvasOperations.ts` |
| `npm run build` | pass |
| `npm test` | **2178 pass / 0 fail / 0 skipped**, 113 suites |
| `uv run pytest tests/api/contract_v1 tests/api/test_frontend_read_v1_live_zafran_db.py -q` | **51 passed, 0 skipped** — the Node oracle half ran (it would have skipped without Node) and the live Zafran DB walk ran against `clue-pg-managua` |
| `git diff --stat origin/integration/design-improvement..HEAD -- platform libs subsystems` | **prose only** — `arv2/README.md`'s module table (1 line) and `frontend_read/contract_v1.py`'s module docstring (6 lines), both re-pointing at `apps/frontend/src/features/accounts/model/` after the vendored Zod was retired. **No backend behaviour changed in D4.** |
| `git status` | clean except the untracked `.context/attachments/` and `.context/d4-acceptance/` (screenshots deliberately not committed) |
| Alembic | untouched — D4 adds no migration |

## Follow-ups

1. **The backend FI-2 deletion PR (ruling 2i) — the next backend change.** Delete the FI-2 readers
   in `accounts_list.py` / `account_detail.py` / `contacts.py` (with `AccountDetail`, `neutralFacts`,
   `projectSections`), `app.contract_mode` / `ContractDep` and the `contract` query parameter, and
   the FI-2 route tests with them; then drop `?contract=v1` from the five adapters.
2. **`POST /frontend/v1/accounts`** — there is no write endpoint for account creation, so "New
   account" is a browser-local draft that dies on reload (ruling 2f).
3. **The CSS re-sync job (ruling 2a)** — every feature's CSS, the application shell and the shared
   `Button` from the design build; then delete `generated/legacy-compat.css`,
   `scripts/extract-legacy-compat.mjs` and the shrink-only allowlist in `design-system-tokens.test.ts`.
   It also owns the hard-coded sidebar person (drift D6). Unowned and unscheduled.
4. **`AccountContactDetailV1.linkedinUrl` should be nullable**, like `BuyingCommitteeMember`'s now
   is, so the backend's `https://www.linkedin.com/` site-root fallback can go away (backend).
5. **`revenueLabel` / `fundingLabel` must read the registry objects' own keys** the way
   `employeeBand` and `locationsLabel` do — this is drift D1 on the screen (backend, D3 follow-up 5).
6. **A `core.work_email` verdict writer** — no writer produces the `{address, status}` shape the
   reader grades, so `emailStatus` is `"lookup"` for everyone and four verified addresses render
   nowhere (drift D2). Backend / R-lane; the alternative is a product ruling that a bare address may
   be shown ungraded.
7. **Persona display labels and the derived-role rationale wording** (drift D3) — the enum literals
   and the pipeline prose are served, so the fix is backend-side vocabulary, not a client map.
8. **The projects sidebar 404** — `clue_api.projections_main` does not mount the projects API, so
   the app shell's sidebar fetch 404s on every accounts page of a projections-only stack (drift D24).
9. **A session display name** — the session DAL carries none, so a signed-in profile renders the
   user id as the name (honest, ugly): the draft row's Owner shows `usr_4d8ed1e2…`. Carried over
   from D3.
10. **The `Aakash Shrivastava` placeholder in `components/shell/app-sidebar.tsx:119`** (drift D6) —
    folded into the CSS/shell re-sync job above; recorded separately because it is a visible
    falsehood on every page, not a styling nit.
