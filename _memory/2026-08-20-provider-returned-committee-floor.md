# The provider-returned committee truth floor (2026-08-20, admission lane)

Implements founder rulings 1–3 recorded in `2026-08-20-seven-fix-night-close-out.md` §"committee
formation is agent-judged, provider-grounded". Follows `addc8364` (office gate retirement).
Sibling lanes the same day: spend (record-only caps) and steering
(`2026-08-20-committee-codefinition-steering.md`). **Not committed by this lane.**

## Live evidence fixed

v9, job `cd6a779e`, operation `8500325f`, Millennium Physician Group. Seven provider-returned
current CXO/SVP employees → 1 admitted, 2 excluded, 4 ambiguous.

- 2 excluded: `function_match` string test — plan said "Clinical", provider says "Physician".
- 4 ambiguous: Teams-path candidates. Their facts are stamped `sumble_teams`, so
  `_office_candidates`' `fact.source_key == PEOPLE_SOURCE_KEY` grounding filter saw no facts.
  (The two `_candidate` call sites in `sumble_committee_source.py:216/251` differ only in
  `direct_lineage` — People vs Teams — so a Teams-only person's *whole* fact set is Teams-stamped.)

## What changed

**A. Admission floor** (`sumble_entity_research_tools.py::_office_candidates`). Under
`company_wide` (default) the grounding filter and the function match both return True; only a
*declared* `business_unit` still narrows (organization membership the agent asserted on purpose —
kept, flagged, not decided unilaterally). `same_office_strict` keeps all three retired tiers
byte-identical; the addc8364 strict pin never moved.

**B. `target_functions` is advisory** — `Field(min_length=1)` → `Field(default=())` in
`AccountBuyingUnitScope`. Field kept (it is the audited record of confirmed-plan intent, and
`_validate_scope_against_plan` still refuses an invented function; an empty tuple widens nothing).

**C. Teams-path members now survive the projection and R4.** Admitting them exposed two
People-only assumptions downstream:
1. `_persist_committee_projection` queried member claims with `source_key = 'sumble_people'` and
   the People snapshot ref, then raised *"office-admitted committee member lacks direct People
   facts"*. Widened to **this operation's own succeeded component snapshots** (People + Teams),
   with per-row `source_key`/`provider_source_id`. Message now "admitted committee member lacks
   provider-returned facts from this operation" — the floor stays a floor.
2. `entity_research_tools.py::_validate_result_draft` refused any discovered-contact claim whose
   `source_key != draft.operation.source_key`. This fired end-to-end (the D5 acceptance test went
   red) because the widened projection now also carries the `contact.team_membership` claim for
   *People*-path members. Fixed with a bounded, provider-owned widening mirroring the existing
   `claim_source_snapshot_refs` precedent: new `ProviderResultLineage.claim_source_keys`, populated
   by `SumbleEntityResearchLineageReader` from `committee_acquisition_snapshot` /
   `account_gap_snapshot` rows (`_component_snapshot_refs` → `_component_snapshots`, now returns
   refs **and** source keys). Default `()` keeps every other provider on the strict one-source rule.
   `entity_research_tools.py` is outside this lane's stated ownership — flagged to the orchestrator.

Substrate needed no change: the M8C C1 CHECK already admits a `sumble_teams`-stamped professional
claim (`field_key <> 'contact.team_membership' AND provenance_kind='provider_returned'`), and the
lineage trigger matches `snapshot.source_key = claim.source_key`.

**D. Roles — nothing to retire; it was already gone.** The account-agent committee path has run
`role_inference="agent_deferred"` since Slice D D2, and role/persona claims are written by the
agent through the existing D3 tool `record_committee_role_inferences`. That is mechanism option 1
(existing tool surface); no new surface was invented. Pinned structurally now: the new DB test
injects a gateway whose `complete` **raises**, so the path has no branch that could call it.
`roles.py::infer_role`/`gate_role` remain live only on the R1-quarantined `deep/orchestrator.py`
(`worker_llm`) path.

**E. Steering** (`catalog/entity-research/account/v3/{manual,prompt}.md`, in place per cd15398d /
addc8364 precedent). Teaches: every provider-returned candidate is admitted; `target_functions` is
advisory and may be empty; compose scopes to widen honestly and hunt provider vocabulary; the
committee is actually *formed* at `record_committee_role_inferences`; provider-vocabulary
translation examples ("Physician" at a physician group is clinical leadership; a divisional CIO is
a technical evaluator). No content hash is pinned for the account v3 catalog, so no digest moved.

## Coverage / metadata

`excluded_candidate_count` / `ambiguous_candidate_count` still persist to
`entity_research_sumble_projection.metadata_json` (read at `account_entity_research.py:~1157`);
they are simply 0 on the company_wide path. `_committee_coverage_status` with `ambiguous == 0` and
`member_count > 0` returns `("complete", ())` — verified in code and end-to-end by the D5
acceptance test.

## Tests (red first)

- `test_account_entity_research_r5_db.py`: `_millennium_v9_candidates()` / `_millennium_v9_scope()`
  replay the live seven (3 People-path + 4 Teams-path).
  - `test_company_wide_admits_every_provider_returned_candidate_on_the_live_v9_shape` — red at
    `(1, 2, 4)`, the exact live board; green at 7/0/0.
  - `test_same_office_strict_pins_exactly_what_the_provider_returned_floor_retired` — green before
    and after; reproduces `(1, 2, 4)` under the named strict policy (negative control).
  - `test_target_functions_is_advisory_and_may_be_empty_end_to_end` — red on the pydantic
    `too_short`; covers schema, `DiscoverBuyingCommitteeInput`, `_validate_scope_against_plan`, and
    the admission floor.
  - `test_company_wide_policy_retires_the_office_veto_on_the_live_millennium_shape` (addc8364)
    updated: it asserted the two now-retired gates still stood.
  - the "starved member" negative in `..._defers_role_inference_to_the_agent` now matches
    "lacks provider-returned facts".
- `tests/api/test_committee_provider_returned_floor_db.py` (new, real Postgres): a Teams-only
  related person (id 2002) added to the recorded s2b Teams fixture. Proves admission → durable
  `sumble_teams` claims → projection with verbatim spans inside the retained Teams artifact →
  `claim_source_keys` bounded to the operation's own snapshots. Red at each of the three stages in
  turn.
- `test_committee_agent_inference_acceptance_db.py` (D5) was the end-to-end red proof for the R4
  validator fix, and already pins zero gateway calls + role claims with rationale/provenance.

## Verification

516 passed across r5 / committee-acceptance / evidence-span / comprehensive-execution / gaps-s1 /
s2b / s2c / r11-bridge / cutover-r10 / fresh-skip / `tests/agents` / `tests/profiling` / harness /
registry-wiring / comprehensive-contract. `uv run mypy` 733 files clean; `lint-imports` 26/26;
ruff clean + formatted.

**23 pre-existing failures** across `tests/api` (c7 production readers, exa websets wiring,
extractor composition, fi2-62 bundle shrink, frontend bulk actions, lane-bd/d4/d-b1, official-site
crawl wiring, p36, production-context s3/s31, projections app, toolbelt wiring) reproduce
byte-identically with this lane's six files reverted. None touch committee admission, projection,
or `target_functions`.

**Shared-worktree hazard, recorded:** three lanes are editing this one working tree. Two spurious
failure sets were caused by *another lane's* revert-for-red-proof window (the spend lane's
`test_pilot_provider_cap_record_only.py`, then the steering lane's SKILL.md/profile digest). Both
went green once that lane restored. Cross-lane test results are only trustworthy at a quiet moment.

## Flags / open

1. **`business_unit` kept as a narrowing discriminator** under `company_wide`. It is
   organization-membership the agent declares deliberately, not geography — and it is `None` in
   every live scope so far — so ruling 1 arguably does not reach it. Flagged, not decided.
2. **`entity_research_tools.py` touched** (16 lines) though not in this lane's ownership list; it
   was the only place the People-only contact-source rule lived. The widening is bounded by the
   provider's own ledger.
3. **`SumbleCommitteeSemanticResearchAction.__init__` still takes `gateway` / `role_model`** and
   forwards them to `discover_committee`, which never uses them in `agent_deferred` mode. Dead
   config, not dead code (the quarantined `deep/orchestrator.py` still needs the parameter on the
   shared function). Removing them is a separate cleanup.
4. **`admit_candidate` still drops a candidate with no strong key** (LinkedIn / verified email).
   That is M2 identity resolution — there is no contact to resolve to — not a committee judgment
   gate, so it was left alone. If a future provider returns named people without either key, this
   becomes the next floor question.
5. `payload["contract"]` is still `"m8d-r5-sumble-office-committee-v1"` (a durable string at rest;
   not renamed).
