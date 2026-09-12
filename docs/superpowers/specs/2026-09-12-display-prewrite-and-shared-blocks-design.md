# Display pages: written at settle, shared where the question is the same

**Status:** design agreed in chat with the founder, 2026-09-12. Branch `research-streaming`.
**Rulings (founder, 2026-09-12):** the account overview page and every contact page are written
when their research job settles — both are read, because artifacts are drafted from what the
contacts care about; the insights page stays lazy and is composed from blocks the other two pages
own wherever it asks the same question; a shared block is the stored body only (sentences + claim
cites), never the other page's heading, position or open/closed default; no synthesis is ever
written from another synthesis — every section cites claims.
**Open ruling (founder):** what a section shows while its block is not yet written (the dummy
frontend has no such state). Until ruled, a missing section is simply absent, as today.

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
* Enqueue points, both after the settle transaction committed (the launch's own rule — rows
  first, offer second), never raising into the job:
  * account job settled → `("account", account_entity_id, "overview")`;
  * person job settled → `("contact", subject_entity_id, "contact")`.
  The offer rides `_offer_committee`'s pattern in `account_research_driver.py`; a worker with no
  queue logs `arv2.display_page_not_enqueued` exactly as the committee offer does.
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

## 4. Progressive read (after the open ruling)

Once the founder rules the placeholder state, the web read stops writing inline: `page()` serves
what exists, schedules the rest (the same `schedule_regeneration`, extended to missing sections),
and the page polls the read every 5 s while any section is reported `pending`, the way the
Target accounts tab and the research card poll. Until then the inline write stays.

## 5. Tests

Handler: writes the page once, a redelivery writes nothing (DB). Driver: the two offers land after
the settle commit and never raise (fakes). Recipes: a `shared_from` section composes the owner's
body under its own chrome, is absent when the owner is unwritten, and reports stale with the
owner (pure + DB). Insights page: the sharing set leaves exactly four generated recipes.

## 6. Out of scope

Rewriting the insights recipes' prose; writing the insights page at settle; any change to what
research writes; the placeholder state itself (a founder ruling first).
