# Retiring the same-office gate — `match_policy: company_wide` (2026-08-20, ~11:50 IST)

## Founder ruling

"Remove the same-office gate for now — retire that policy for now." Reversible policy retirement,
not a deletion. Trigger: the v8 live committee execution (job `4e1bc4fd`, operation `8500325f`,
Millennium Physician Group — 913 people, multi-site physician group) fetched 7 real Sumble
candidates and admitted **zero**: 2 excluded, 5 ambiguous, because `same_office_strict` could not
evidence Fort Myers-HQ placement from provider profile values. For an HQ-level committee at a
multi-site company, office placement is the wrong veto.

## The change

- `AccountBuyingUnitScope.match_policy` (`platform/agents/clue_agents/account_entity_research.py`)
  widened to `Literal["company_wide", "same_office_strict"]`, **default `company_wide`**.
- `_location_scope_match` (`platform/api/clue_api/sumble_entity_research_tools.py`) returns `True`
  immediately under `company_wide` — the office-location tier does not run. `same_office_strict`
  keeps its exact prior body (most-specific-declared-tier + US-state twin normalization).
- Steering: `catalog/entity-research/account/v3/{manual.md,prompt.md}` edited **in place** (the
  `cd15398d` precedent; steering carries "the version of the day", only the authorization profile
  pin is frozen). No content hash is pinned anywhere — `test_entity_research_cutover_r10.py`
  asserts tool/refusal *coverage*, not bytes, and stays green.

## What deliberately did NOT change

Only the office-geography veto retires. Untouched under both policies:
- **Identity** — the `business_unit` discriminator (team names + provider-returned
  `organization_relationship.organization_name`) is *organization membership*, not geography.
- **Relevance** — `target_functions` matching.
- **Grounding** — a candidate with no `sumble_people` fact is still ambiguous/review.
- The `_bounded_office` validator still requires one of facility/locality/region/business_unit, so
  the declared office keeps riding the scope as descriptive, audited context.

No entanglement was found: location and employer are separate haystacks and separate checks.

## Persistence / replay

`scope_json` is `scope.model_dump(mode="json")` and `scope_sha256` hashes it, so the policy is
inside the replay guard ("buying-unit scope replay changed"). Audited every live DB with committee
scopes (`clue`, `clue_m8d_live1..9`, `clue_d5_live`): **all 11 rows and all 17 journalled
`discover_buying_committee` arguments carry `match_policy: "same_office_strict"` explicitly**, so
no historical scope can be silently repointed by the new default. New operations only. No
migration needed (no DB CHECK on `match_policy`).

## Tests

`tests/api/test_account_entity_research_r5_db.py`:
- `test_company_wide_policy_retires_the_office_veto_on_the_live_millennium_shape` (red first:
  `selected == ()` before the gate fix) — replays the live Fort Myers scope.
- `test_same_office_strict_classifies_the_live_millennium_shape_exactly_as_before` (green before
  AND after — the strict pin).
- `test_buying_unit_scope_defaults_to_company_wide_and_still_accepts_a_declared_office`.
- `test_persisted_buying_unit_scope_records_its_policy_and_replays_under_it`.
- The two pre-existing location-dependent gate tests (`..._exact_buying_unit`, `..._paramus_...`)
  now name `match_policy="same_office_strict"` explicitly; the two business-unit-only tests were
  left on the default, so they now also prove the org gate survives under `company_wide`.

91 passed across the r5 / committee-acceptance / gaps-s1 / evidence-span / comprehensive-execution
/ r4 / cutover-r10 / fresh-skip / harness suites. Two `test_fi2_slice3_economics.py` failures are
**pre-existing** (`no composed R5 source is authorized for account.project_angle`), byte-identical
at pre-change HEAD. ruff + mypy clean on the edited files (no new mypy errors).

## Open

- Reversal is a one-line default flip plus the steering wording; the strict body is intact.
- A scope declaring a *geographic* `business_unit` (e.g. "Fort Myers Campus") would still veto
  under `company_wide`, because business-unit is treated as organization membership. Not observed
  live (the v8 scope's `business_unit` was null); flag if it appears.
