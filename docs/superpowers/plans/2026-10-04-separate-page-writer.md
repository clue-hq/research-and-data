# Separate page writer — implementation plan

Spec: `docs/superpowers/specs/archive/2026-10-04-research-narration-quality-design.md`.
Trial evidence: `_memory/2026-10-04-narration-quality.md` (iterations 1–5, two accounts).
Branch: `research/narration-quality`.

## Goal

New research launches stop writing their own pages. After the research agent finishes, the driver
writes the pages with one plain model call per page set (the trialled writer), and rewrites the
account pages once every person job of the account has settled. Publication, storage and the
frontend are unchanged.

## Global constraints

- Seller-agnostic: everything about the seller comes from the project's pinned context.
- No code counts words, lines or items in written prose (founder, 2026-10-04). Code checks only
  correctness: references resolve, quotations appear in a cited finding, owned sections present,
  private topics absent, send_line only in contact openers. One repair attempt on a failed check.
- Historical launches keep their pins and behaviour (recipe < 25 unchanged).
- Every model call goes through the platform gateway: Langfuse trace + model usage/spend ledger.
- Never a second write path into artifacts/display blocks: publication uses `publish_page`.

## Concepts

- `owns_narrative(scope)` (recipe ≥ 20) keeps meaning "this job's pages are research-quality pages
  with generations and continuations". New: `writes_pages_separately(scope)` (recipe ≥ 25) means
  "the driver's page writer authors them; the researcher does not".

## Tasks

1. **Writer core** — `platform/api/clue_api/arv2/page_writer.py`
   - load the seller brief (cached per context pin; generated on first use from the pinned seller
     documents with the `seller-brief` guide), the subject's dossier, the committee and person
     dossiers (account) or the account story and account dossier (person);
   - build the view (`page_writer_view.py`), call the model through the gateway with the guides as
     system prompt, parse JSON, validate (shared with the trial harness), one repair;
   - map references (`F012`, `A:F012`, `P2:F007`) to stored claim ids via the dossiers' receipts;
   - return typed `PageSectionDraft`s per page.
   Tests: reference mapping, validation, repair path, private-topic and send_line checks (stub model).

2. **First write at settle** — in `account_research_driver.handle`, after the quality runner
   returns and before `_settle_quality`, when `writes_pages_separately(scope)`: write the account's
   Overview + Insights or the person's contact page and publish with `publish_page` under the
   writer's own `execution` row. A writer failure is logged and leaves the pages missing
   (the job settles `needs_review`, as today).
   Tests: DB test that a settled v25 job gets published blocks; failure leaves job needs_review.

3. **Completion without researcher pages** — `quality_completion`: the missing-pages refusal
   applies only when the researcher owns writing (20 ≤ recipe < 25).

4. **Account rewrite after people** — `_focused_reconciliation`: when `writes_pages_separately`,
   call `run_reconciliation` in full-rewrite mode (every owned account section allowed, every claim
   of the account and its people supplied) with the writer as `generate`; replies cite through the
   packet's aliases; uncited advice sentences are allowed in this mode.
   Tests: DB test of a full rewrite publishing all sections and settling the generation.

5. **Catalog v25** — recipe/launch/profiles/prompts at 25 without the narrative tools, skills and
   instructions; launches select 25. Resource/pin tests updated.

6. **Trial harness** reuses the production writer core (no duplicate validation code).

7. **Verification** — focused unit + DB tests on a throwaway DB; ruff/mypy on changed modules; one
   live writer run against one account's saved inputs through the production code path.

## Out of scope

Removing already-stored sensitive data; stopping its collection; the automatic Miscellaneous
append of uncited findings (separate founder ruling); the legacy `arv2_display_page` writer.
