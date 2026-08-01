# 2026-08-01 — F9: Sumble Organizations select-list drift (fixed)

Branch `platform/clue-trial`. Base HEAD `d73b972`. Fix commit `52766a1`.
Full report: `.superpowers/sdd-f9-report.md`.

## What broke

`resolve_organization` selected only `{"attributes": ["employee_count"]}`. Sumble v9's `select` is
**exhaustive, not additive** — the response returns *only* the named attributes. The live payload
for `oregonclinic.com` was `attributes: {"employee_count": 488}` with `matched_count: 1` and no
`id`/`url`. The normalization gate (`row.attributes.id is not None and row.attributes.url`) accepted
zero rows and returned `[]` / `None` — the *same* disposition used for a legitimate no-match.

Live consequence: 2 credits spent on a real match, zero claims written, `organization_id` null so
the jobs call was never keyed, fit scored 0.0 over nothing, C7 composed empty. No error anywhere.

**Root cause was the fixture, not the code.** `organizations_match.json` modelled identity
attributes as returned for free *and unrequested*, so the whole suite passed against a shape the
live API never produces for that request.

## Free-vs-paid verdict (settled — do not re-litigate)

Per <https://docs.sumble.com/api/core-data/organizations> "Credit cost": cost is **1 base credit +
1 credit per paid attribute**, and `id`, `name`, `slug`, `url`, `sumble_url` are **free**.

So selecting the identity attributes costs **0 extra credits**. Organizations stays at 2, Jobs at 1,
aggregate bounded cap of 3 stays truthful. **No preview/estimate arithmetic needed correcting** —
`coordinator._research_preview` and `scripts/README.md` were already right and were left alone.

The docs contradict themselves ("nothing is mandatory" vs "always included for free"). Resolution:
**free governs price, not delivery.** An unrequested free attribute is simply absent.

## The invariant now enforced

`matched_count >= 1` + zero rows the normalization can key on ⇒ raise `SumbleSchemaDrift`
(subclass of `SumbleContractError`), never return empty. One shared `_identified_rows` gate backs
both `normalize_organization` and `matched_organization_id` (they previously duplicated the filter).

Deliberately preserved: `matched_count == 0` is still a successful empty result (plan §5 rule 11);
absent `matched_count` makes no drift claim; multi-row ambiguity still returns `[]` / `None`.

`slug` is intentionally NOT selected — nothing normalizes it. Adding it later is free.

## Gotchas for the next session

- **Two Postgres instances on :5432.** A Homebrew PG 17 shadows the `clue-postgres` container.
  `docker exec clue-postgres psql ...` creates a DB the app *cannot see*. Use
  `psql "postgresql://clue:CHANGEME@localhost:5432/postgres"` to create throwaway DBs.
- **Pre-existing test-isolation failure (NOT F9).** `tests/api/test_clue_trial_spine.py` +
  `tests/sources` in one process against one DB ⇒ 7 `test_waterfall.py` failures with
  `SourceManifestRedefinitionError: source 'crm' ... already registered`. The spine test's
  `load_research_packs` seeds manifests that `tests/sources` re-registers differently. Verified
  identical on stashed/unmodified HEAD. Each directory is green alone on a fresh DB. Unfixed.
- `account.hiring_velocity_eng` is `PassKind.DEEP` gated `tier>=3`, so it is *correctly* absent at
  the tier checkpoint. The spine test asserts the bound jobs resolver's output instead of faking a
  DEEP write.

## Open follow-ups

1. Other Sumble select lists are structurally immune today (jobs normalizes envelope fields only;
   tech-stack is a GET with no select), but **any future request that normalizes a new attribute
   must add it to its select list** — the failure mode is silent by construction.
2. No drift guard on the jobs/tech-stack surfaces; only Organizations has a `matched_count`
   cross-check. Not added without live evidence.
3. `matched_count` stays `Optional` in the model, so drift detection is conditional. Tightening it
   is a live-contract claim not yet evidenced.
4. Fixture `credits_used` values are asserted but not mechanically derived from their select lists.
5. The tech-stack and jobs fixtures were NOT re-verified against live payloads (would cost credits).
   Only a T6 live canary can confirm them.
6. **Re-run the T6 live canary.** The previously-silent case is now loud: a live run either writes
   real claims or fails with a named `SumbleSchemaDrift`.

## Verification performed

`tests/resolvers/test_sumble.py`, `tests/api/test_trial_sumble.py`,
`tests/api/test_clue_trial_spine.py`, `tests/clue_trial` → 43 passed.
`tests/sources` + `tests/api/test_clue_trial_http.py` (fresh DB) → 96 passed.
Ruff check/format, mypy (3 changed files), `lint-imports` (24 kept, 0 broken) all clean.
No live Sumble call and no model call was made; the docs page was fetched read-only.
