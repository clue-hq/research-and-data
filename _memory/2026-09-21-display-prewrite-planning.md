# 2026-09-21 — display prewrite: the 09-12 design resurfaced, one ruling changed, plan written

Founder question: how is prose synthesised over account/contact claims today, when, where stored.
Answer (verified first-hand): `platform/api/clue_api/arv2/display/` writes three fixed pages
(overview 6 / insights 6 / contact 5 sections), one Luna call per section
(`CLUE_ARV2_DISPLAY_MODEL=openai/gpt-5.6-luna`, 240 s timeout, 8 in flight, no reasoning block),
LAZILY on first open of the account detail / workspace / contact routes when
`CLUE_ARV2_DISPLAY_GENERATE_ON_READ=true` (inline, the request waits; stale sections served as
stored and rewritten by an in-process background task); persisted in `display_block` (one live row
per section, superseded on rewrite; prompt/recipe versions stamped); spend on
`provider_call_ledger` labelled `display-<page>-<section>`. Nothing runs after research settles;
the agent's `read_account_research` reads stored overview blocks only (`overview_not_written`).

Prior discussion FOUND: `docs/superpowers/specs/2026-09-12-display-prewrite-and-shared-blocks-design.md`
(founder rulings 2026-09-12: overview at settle on the fleet; contact pages in the background on
the first open of their account; insights lazy + shared blocks; a not-yet-written section blank).
Never implemented (no `arv2_display_page` kind, no handler, no `shared_from`).

**Ruling change (founder, 2026-09-21):** a section being written shows
`Synthesis in progress, please wait a few seconds.` (served as `pending: true` + `emptyMessage`),
page polls every 5 s; a section that will never be written is NOT pending. Recorded in the spec.

Plan written: `docs/superpowers/plans/2026-09-21-display-prewrite-and-shared-blocks.md` — 8 tasks:
(1) fleet kind + work id + enum migration; (2) `Arv2DisplayPageWorkHandler` + `ensure_page(job_id=)`
+ worker wiring; (3) settle-time overview offer in the research driver; (4) `ResearchSection.pending`
on both contract sides; (5) the read seam as scheduler (`pending` via the gather step, page offers
with `reopen_terminal=True`, contact offers on open with a 60 s per-process cooldown, contacts tab
offers, `DbWorkQueue` threaded into `DisplayPages`); (6) frontend `usePendingSectionsRefresh`
(`router.refresh()` every 5 s) mounted in the three renderers; (7) shared blocks (recipe
`shared_from`, migration + retire the two sections' own blocks, `shared_blocks`/`compose(..., shared=)`
/`cited_claim_ids`, owner staleness re-offers the owner page); (8) docs + memory + owed live proofs.
Design choices the plan fixes: no `RECIPE_VERSION` bump (would invalidate every stored page); pending
only where `gather_section_inputs` returns a non-empty input; failed offers serve honestly empty;
the inline write survives as the queue-less fallback and the CLI; outage sentence wins over the
placeholder. Not started; nothing committed for the plan yet (plan + spec edit are uncommitted).
