# Display pages: written at settle, shared where the question is the same

**Status:** design agreed in chat with the founder, 2026-09-12. Branch `research-streaming`.
**Rulings (founder, 2026-09-12):** the account overview page is written when the account job
settles; the contact pages of an account are written, all of them, in the background, the first
time a user opens that account — its overview, its insights page, its contacts tab or "open as
page" — because artifacts are drafted from what the contacts care about, but only for accounts
the user actually looks at; the insights page stays lazy and is composed from blocks the other two pages
own wherever it asks the same question; a shared block is the stored body only (sentences + claim
cites), never the other page's heading, position or open/closed default; no synthesis is ever
written from another synthesis — every section cites claims.
~~**Ruling (founder, 2026-09-12):** a section whose block is not yet written is simply blank —
no spinner, no placeholder copy. The page shows what exists, the rest stays empty until the
block lands, and the page picks it up on its poll.~~
**Ruling (founder, 2026-09-21, replaces the one above):** a section whose block is not yet
written but is being written shows the one served sentence
`Synthesis in progress, please wait a few seconds.` in its empty state — no spinner, no other
placeholder copy. The section is served `pending: true` with that sentence as its
`emptyMessage`, and the page polls every 5 s while any section is pending. A section that will
never be written (its recipe matches no claim) is NOT pending: it keeps the client's ordinary
"No {section} information found for {name}." default, so the sentence is never a promise the
page cannot keep. **Status 2026-09-21:** implementation plan
`docs/superpowers/plans/2026-09-21-display-prewrite-and-shared-blocks.md`.
page cannot keep.
**Status 2026-09-22 — IMPLEMENTED** on branch `display/prewrite-and-shared-blocks` (plan
`docs/superpowers/plans/2026-09-21-display-prewrite-and-shared-blocks.md`, ledger
`.superpowers/sdd/2026-09-21-display-prewrite-and-shared-blocks/progress.md`, execution record
`_memory/2026-09-21-display-prewrite-execution.md`): the `arv2_display_page` fleet kind and handler,
the settle-time overview offer, contact pages offered on the first open of their account, the read
as scheduler (`pending` + the sentence + the 5 s poll) and shared blocks all shipped, in eight
tasks, with two migrations (`fd8795c4fd5a`, `2b702a116c15`). The five live proofs listed in the
execution record are owed (founder-triggered; they spend money).
**Ruling (founder, 2026-09-22):** the account **insights** page is written at settle too, offered by the
account job right after the overview (its four owned sections; the two shared sections still compose
from the overview's and the contact pages' blocks at read time). Implemented the same day on the
branch (`_SETTLE_PAGES` in `account_research_driver.py`).

## 1. Today

A page is generated on first read: `frontend_read/display_pages.py::page` calls `ensure_page`,
which writes every missing section inside the HTTP request (up to `arv2_display_max_parallel`
model calls, `arv2_display_timeout_s` ceiling). Sections that exist but went stale are served as
stored and rewritten by `schedule_regeneration` in the web process. Observed on 2026-09-12: an
account overview (6 sections) lands in ~3 s, a contact page (15–40 sections) in 10–17 s, all paid
by the first person to open the page, with no loading state. The insights page (6 recipes, one of
them per committee member, ~36 sections per account) re-synthesises claims the overview and the
contact pages already turned into prose: `context-only` is the same two keys as the overview's
`watch-outs`; `contact-insights` overlaps `why-this-person`/`angles`/`openers`; `buying-signals`
and `tools-they-already-use` overlap `why-now`/`why-they-fit`/`how-to-approach`.

## 2. Written at settle

* A new fleet task kind `arv2_display_page` (`FleetTaskKind`), work id
  `arv2_display_work_id(subject_kind, subject_id, page)`, payload
  `{workspace_id, subject_kind, subject_id, page}`. Handler `Arv2DisplayPageWorkHandler` in
  `arv2/display/fleet_handler.py`, composed in `fleet_main.py` beside the research handlers,
  behind the existing `arv2_display_generate_on_read` runner conditions (a key, the flag).
* The handler calls `ensure_page(..., regenerate_stale=True)` on the fleet's own connection and
  runner. Idempotent: `display_block_live` already makes a live section unique per
  `(workspace, subject_kind, subject_id, page, section_key)`, and `ensure_page` writes only what is
  missing or stale, so a redelivered task costs nothing it has not already paid for.
* Two enqueue points:
  * **at settle** — the account job settled → `("account", account_entity_id, "overview")`,
    offered after the settle transaction committed (the launch's own rule — rows first, offer
    second), never raising into the job. The offer rides `_offer_committee`'s pattern in
    `account_research_driver.py`; a worker with no queue logs `arv2.display_page_not_enqueued`
    exactly as the committee offer does.
  * **on open** — the first read of an account's overview page, insights page or contacts tab
    (the frontend-read account routes: detail, workspace, display pages) enqueues
    `("contact", member_id, "contact")` for every committee member that has a settled person job
    and no live contact page. The read already carries a side-effect seam
    (`schedule_regeneration`); this is the same seam, keyed per account in the web process's
    in-flight table so ten opens of one account enqueue once, and idempotent on the fleet by the
    work id. A contact opened before its task ran still writes inline (the fallback below).
  A person job settling enqueues nothing: contact pages are paid for only on accounts a user
  opens.
* Spend: the page's model calls land on the same provider ledger as the research, stamped with
  the research job as `job_id`, so the cost is visible where the research cost is.
* The web read is unchanged as a fallback: a page opened before its task ran still writes inline.

## 3. Shared blocks

* A recipe gains an optional `shared_from: {page, section_key}`. A recipe with `shared_from` owns
  no block of its own: at compose time the page renders the live block of the named
  `(subject, page, section_key)` under its own `h1`, `position` and `default_open`.
* First sharing set, by the founder's rule "same question, same block":
  * insights `context-only` ← overview `watch-outs` (identical allowed keys);
  * insights `contact-insights` ← the contact page's `why-this-person` (per committee member,
    the insights expansion already lists the members).
  `buying-signals`, `tools-they-already-use`, `how-they-sell`, `money-and-momentum` keep their own
  recipes (a different question, or fresh keys).
* Staleness: a shared block is scanned once, under its owner; a page that shares it reports it
  stale when the owner does. `schedule_regeneration` for a page never rewrites a block it does not
  own — it enqueues (or, in the web fallback, runs) the owner page's regeneration instead.
* Provenance is untouched: `cited_claim_ids` travel with the body; the evidence route's
  "may this caller stream this claim" check reads the composed page and therefore sees shared
  cites too.

## 4. Progressive read

The web read stops writing inline: `page()` serves what exists, schedules the rest (the same
`schedule_regeneration`, extended to missing sections), and reports the missing section keys as
`pending`. A pending section renders blank (the ruling above). The page polls the read every 5 s
while any section is `pending`, the way the Target accounts tab and the research card poll, and
stops when none is. The inline write survives only as the explicit "regenerate" command path.

## 5. Tests

Handler: writes the page once, a redelivery writes nothing (DB). Driver: the overview offer lands
after the settle commit and never raises (fakes). Read: the first account open enqueues one task
per settled member with no live page, a second open enqueues nothing, a member whose page exists
is skipped (DB). Recipes: a `shared_from` section composes the owner's
body under its own chrome, is absent when the owner is unwritten, and reports stale with the
owner (pure + DB). Insights page: the sharing set leaves exactly four generated recipes.

## 6. Out of scope

Rewriting the insights recipes' prose; ~~writing the insights page at settle~~ (ruled IN, 2026-09-22); any change to what
research writes; any placeholder visual beyond a blank section.
