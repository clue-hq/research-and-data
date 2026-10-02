# ARV2 R3 — live fix wave 2 (walk findings W1–W4 + repair-script hardening), 2026-09-09

Branch `track-r3`. Fixes the four integration defects the R3 acceptance walk found when a real
person job's output was read through the live read surface
(`.context/arv2-r3-acceptance/acceptance.md`, "Walk findings"), plus two hardenings of
`scripts/arv2_repair_person_lookups.py`. One commit.

## What changed

- **W1 `core.work_email` shape.** `email_export_claim` writes `{address, status, checked_at}` —
  `status` is the graded `EmailVerdict`, `checked_at` is the provider's own check date
  (`email.output[0].date`), omitted when absent. `not_found` still writes no claim. The screen's
  verification date is the **claim's** `observed_at`/`collected_at`; `email_facts` reads no date
  key out of the value.
- **W3 career-history shape.** `_career_history` nests the dates under `date: {start, end}`; an
  entry the record dates nowhere carries no `date` at all. `account_research_driver`'s
  `employment_history_lines` reads `date` first and the flat spelling second, because the claims
  already at rest are immutable.
- **Migration `7c4f1a2b9d63`** (head was `60e51eba0123`) swapped both registry rows exactly at
  the time; **after the 2026-09-10 rebase onto `integration/design-improvement` it keeps only the
  `contact.facet.career_history` swap** (flat `start`/`end` → nested `date`). D4-b's
  `7332ac974920` had already moved `core.work_email` to `{address, status, checked_at?}` with the
  closed vocabulary `WORK_EMAIL_STATUSES`; `email_export_claim` writes that shape. The two chains
  join at `57e06d696d49`.
- **W2 on-demand seat.** `Arv2PersonLaunchRequest.persona: Persona = Persona.USER`; the launch
  writes `contact.persona` + `contact.role_on_committee` inside its transaction through
  `seat_person_on_committee` (new, in `account_research_launch.py`, reused by the repair script).
  `committee_member_claims` gained a `method=` seam so the seat is `ExtractionMethod.HUMAN`
  (tier 1, no URL required) rather than the account job's `LLM_SYNTHESIS`. A contact that already
  holds a live persona claim is never re-seated. `persona` is in the run-digest payload, so the
  same people at a different seat is a different run. CLI `--persona`, tool argument, journal
  safe-display field.
- **W4 title suffix.** `ai_ark_person_claims` cuts a trailing `" | <company>"` / `" at <company>"`
  when the tail folds equal to the record's current company **or** the job's account name; the raw
  string rides as marker `title_raw` only when something was cut.
- **Repair script.** Idempotent by default (`skipped_already_looked_up` when the contact already
  holds non-repaired `ai_ark:person` claims; `--force` overrides) and `--persona <role>` seats a
  finished person who holds no seat — including when the lookup itself is skipped.

## Blast radius accepted deliberately

`core.work_email` is shared with two **flag-off** old-lane writers that insert *strictly*
(`ValueSchemaError`, not a lenient marker), so both were moved to the object in the same commit:
`frontend_read/contact_email_lookup.py` (writes `{address}`, reads either shape) and
`contact_channel_enrichment.py` (writes `{address}` for the email field only; its corroboration
comparison now reads either shape through `_channel_value`). Neither grades a mailbox, so neither
states a `status` — a verdict they did not obtain would be a fabrication, and the chip's
fail-closed "offer a lookup" is the honest read of an ungraded address.

## Residuals recorded, not fixed

1. **The answer-key `core.work_email` rows are the provider's raw block**
   (`{address, status: "VALID", domain_type, verdict: "verified", checked_at}`), not the graded
   vocabulary. They were already invisible to `email_facts`, and they now also load with
   `schema_valid=false`. Fixing them is an answer-key data change, not a code one.
2. **`resolvers/{apollo,clay,zoominfo}` still map `core.work_email` to a bare address.** They have
   no production callers (they are unregistered in every entrypoint), so nothing writes through
   them today; the wrapper belongs with whoever composes them.
3. `tests/claimstore/test_merge.py::test_batch_scales_to_1k_entities` fails on the **shared lane
   DB** (`assert 1019 == 1000`): it counts every `account.recent_funding` claim in the database and
   the live acceptance rows are in there. Pre-existing pollution, unrelated to this wave; it passes
   on a clean DB.
4. `mypy` reports 4 errors across the two touched ARV2 modules — all on lines this wave did not
   change (verified against `HEAD`).

## Verification

`ruff format --check` + `ruff check` on every touched file; `lint-imports` 26/26 kept;
`alembic upgrade head` + up→down→up on `clue_san-salvador_smoke`; offline `tests/arv2` +
`tests/api/test_frontend_read_{contacts,v1_shared}.py`; on the lane DB additionally
`tests/claimstore` (minus the polluted one), `tests/contact_research`, `tests/resolvers`,
`tests/narrative/test_prose.py`, `tests/profiling`, `tests/agents`,
`tests/api/test_{arv2_launch_tools,fleet_wiring,frontend_read_account_detail,
frontend_read_display_pages_db,frontend_contact_email_lookup_db}.py`. Repair script exercised
`--dry-run --persona user` on three real finished jobs: all three reported
`skipped_already_looked_up`. No `*_live.py` test was run.
