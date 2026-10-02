# 2026-08-18 — Lane-3 accounts visual-parity re-study (post-Phase-C)

## What was done
Founder asked for a thorough re-study of visual parity between the dummy frontend (design
baseline) and the integrated frontend for the Lane-3 accounts/contacts screens, with both
running side-by-side, categorized as: components EXTRA in integrated / components MISPLACED /
components MISSING vs the design. Deliverable:
**`docs/superpowers/plans/2026-08-18-lane3-accounts-visual-parity-restudy.md`** — the
exhaustive inventory (~30 EXTRA / 4 MISPLACED / ~35 MISSING / ~40 STYLE-DRIFT findings, all
anchored file:line in both trees, live-verified where data existed). It complements (does not
replace) the 2026-08-17 governance doc.

## Stack used (still running at session end)
- Dummy: `/tmp/clue-frontend-tip` (git tip `c7f2bc5` = `codex/chat-shell`, same as
  port-of-spain repo which still serves 3080) → **localhost:3000** (`npm ci` + design-system
  build done today; log `/tmp/clue-dev-3000.log`). The stale singapore-workspace dev server
  that occupied 3000 was killed.
- Integrated: this branch on **localhost:3020** (untouched), backend
  `clue_api.projections_main` on **127.0.0.1:8005** against DB
  **`clue_combined_browser_20260817_m1`** (the migrated clone; the original
  `clue_combined_browser_20260816_c1` remains untouched/behind-schema per founder ruling).
- Sign-in: the 20260814 Clerk test account, code 424242, workspace `ws_1a147cb6…`.

## Traps hit / operational facts (verify before reuse)
1. **`CLUE_FRONTEND_READ_ENABLED` is NOT in the repo `.env`** — the 8005 backend was running
   without it, so `/frontend/v1/accounts*` 404'd and `/accounts` showed the recovery card.
   Restarted 8005 with the flag exported (same fix as recorded 2026-08-16). If anyone restarts
   the backend from bare `.env`, accounts will "break" again the same way.
2. Dummy fixtures are narrow: account detail answers only `openai`; full contact only
   `denise-dresser`; other ids 404 by design (`notFound()` on fixture miss).
3. The clone DB has **0 rows in `contact_entity`** — contacts screens can only show empty
   states live; contact-surface findings are code-verified.
4. Integrated artifacts tab is hardcoded `state="capability_unavailable"` at the route.
5. Screenshot pairs: `/tmp/lane3-parity-20260818/` (ephemeral, not committed).

## Key findings worth remembering (full detail in the doc)
- Routes + workspace shell (five tabs Overview/Contacts/Insights/Artifacts/Activity) are AT
  parity — the 2026-08-17 doc's "invented five-tab navigation" §8 line is stale; the tabs are
  designed.
- Worst screen: account overview — "Research by project" section renders raw Tier cards (Icp
  key, Project id, Fit/Intent claim UUIDs, Cutoff/Rubric versions, Disposition) as UI.
- Raw strings still render live: ALL-CAPS registry account names, `10m_50m`,
  `provider_estimate`, `company.financials.revenueAnnual`, claim UUIDs, raw JSON in evidence
  blockquotes.
- Design-only component `contacts/components/contact-preview.tsx` (in-place contact drawer)
  has NO integrated counterpart — contact inspection became navigate-away.
- R9 undesigned set confirmed and extended: + "Research by project" section, Coverage panel,
  Activity "Current state" strip, email-result rendering.
- Two MISSING items need seam/founder decisions, not restyles: "Last updated" (value not
  served) and fit/influence pills (schemas dropped `overallFit`/`influence`).

## Process
Three Opus subagents did the exhaustive two-tree component reads (list surface / detail+
workspace+routes / contacts); browser passes done directly via gstack browse. No production
code touched; only the doc + this note were written and committed.
