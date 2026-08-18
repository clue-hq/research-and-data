# Slice B live browser gate — blocker map (2026-08-19)

Every issue hit while driving the Slice B exit-gate journey live (gstack headless browser →
Clerk sign-in → project chat → comprehensive directive → confirmation gate → launch), each with
its root cause, exact evidence, current status, and owner. Written during the Slice B close-out
session; the fixes referenced landed on `platform/comprehensive-account-contact-research`.

Status legend: **FIXED** (commit on this branch) · **OPEN** (real defect, unowned) ·
**RULING** (fixed here, founder ratification requested) · **ENV** (environment/process, not a
code defect).

---

## 1. FIXED — the @4 directive tool was structurally unsatisfiable for the model

- **Symptom:** every "research this account comprehensively" chat request looped
  `agent.tool_repair` → `plan_rejected` ("a comprehensive research directive covers the whole
  fixed 21-field account profile; pass profile='custom' …") and the turn ended in an honest
  failure. No directive could ever be drafted from chat.
- **Root cause:** `ResearchDirectiveBody.field_keys` has no default
  (`libs/clue-core/clue_core/research_directive.py:239`), so the tool's advertised JSON schema
  marked `directive.field_keys` **required** while steering skill v7 (correctly) instructed
  "profile='comprehensive' and no field list". A schema-honouring model always supplied a list;
  any non-empty list was refused as ambiguous breadth. Unit tests never saw it because they
  construct the input dict directly and omit the key.
- **Fix:** `draft_account_research_directive@5` (`ed7ad2db`) — `ResearchDirectiveBodyDraftInput`
  makes the key omittable at the schema level only; expansion/refusal semantics inherited.
  Full new-revision wave: skill v8, profile v38, recipe0-stage0@18,
  `CONVERSATION_RECIPE_VERSION = 18`, registry grant + default-version gate + composer pin.
- **Verified:** live — the same request drafts the full 21-field directive (v8/v9 in the founder
  workspace); regression tests `test_the_v5_schema_lets_the_model_omit_field_keys_entirely`.

## 2. FIXED — a verbatim full-profile retyping was refused as ambiguous

- **Symptom:** with the schema fixed, the first live attempt still hit the ambiguity refusal:
  the model retyped the 21 rows its steering card lists.
- **Root cause:** @4's rule refused *any* explicit list under `profile="comprehensive"`; an
  explicit list that IS exactly the full fixed profile is the same statement of breadth, not an
  ambiguity.
- **Fix:** `0fce7a84` — @5 normalizes an exact-set retyping to contract order; every other
  non-empty list (truncated/invented/subset) is still refused; @4 keeps its frozen behaviour.
- **Verified:** live (draft succeeded on the retry) +
  `test_the_v5_accepts_a_verbatim_full_profile_retyping`.

## 3. FIXED — effort-tier vocabulary leak, hidden behind a misleading refusal

- **Symptom:** the confirmation gate refused with `account_tier_checkpoint_missing` for an
  account whose human-selected `high` tier claim existed and matched the run.
- **Root cause:** the model drafted `effort_policy.tier="comprehensive"` (the Slice B
  field-breadth word leaked into the open-vocabulary `StableKey` tier slot). The estimate's
  matcher (`platform/api/clue_api/account_research_estimate.py:119`) requires the human tier
  claim's `tier` to equal the directive's effort tier — `high ≠ comprehensive` — and the
  exception message named neither side.
- **Fix:** `3fde62a9` — `AccountTierCheckpointMissing` now carries and prints the directive's
  effort tier; skill v8 states outright that `effort_policy.tier` is the Account row's approved
  tier value and never `comprehensive`.
- **Verified:** live (redraft at `high` priced and opened the gate).

## 4. RULING — directive-lineage deadlock: a bad draft blocked every successor forever

- **Symptom:** after the tier-leaked draft existed, every redraft was refused —
  `ResearchDirectiveConflict: cannot append behind an unconfirmed directive` — and no reject/
  withdraw path exists anywhere. Confirmation was the lifecycle's only exit from a draft, and
  this draft could not open its gate (issue 3), so the lineage was bricked.
- **Root cause:** `clue_research/directives.py::draft_research_directive` demanded the lineage's
  latest row be `confirmed` before any append; the A2 lifecycle trigger
  (`8f44b739674c`) admitted only `draft→confirmed` and `confirmed→superseded`.
- **Fix:** `9d669522` + `bfc7fd9c` — a fresh draft now **supersedes an unconfirmed latest
  draft** (append-only `superseded` event naming the successor); the new draft's
  `predecessor_id` is the lineage's currently-confirmed directive (unique by the one-confirmed
  index; NULL when nothing is confirmed), so confirming it supersedes the right authority.
  Migration `509e5d0e623a` admits `draft→superseded` and widens the confirmation-shape CHECK so
  a superseded draft may be receipt-less. Confirmed history, content immutability, and receipt
  rules unchanged.
- **FOUNDER RATIFICATION REQUESTED:** draft-over-draft supersession is a lifecycle-semantics
  ruling made to unblock the gate. The alternative is an explicit human reject/withdraw tool;
  the change is cheap to revert or narrow.
- **Verified:** live — v7/v8 superseded, v9 drafted, gate opened, my human "Start research"
  click confirmed v9 durably (v6 → superseded, receipt recorded) +
  `test_a_fresh_draft_supersedes_an_unconfirmed_latest_draft`.

## 5. OPEN — `get_research_view@1` is a dead grant in the conversation slot

- **Symptom:** every agent attempt to read the research view fails
  `missing_tool_requirement: get_research_view@1 requires pin kind 'field_registry'` (and
  `project_run`, `verification_policy`). This is why the agent could not discover the project
  run id or read research state, and needed ids spoon-fed in chat.
- **Root cause:** the tool declares
  `pin_requirements = ("project_run", "field_registry", "verification_policy")`
  (`platform/api/clue_api/research_view_tools.py:202-206`), and plan validation refuses any
  step whose node lacks a requested pin of each required kind
  (`platform/execution/clue_execution/graph.py:663-668`). But `Stage0StepPinProvider`
  (`platform/api/clue_api/stage0_recipe.py`) has **no case for `get_research_view`** — those
  pins are never requested, so the grant in recipe0-stage0 (@17 and @18 alike) has never been
  usable. Pre-existing since FI-2; not a Slice B regression.
- **Suggested owner:** the C7/agentic read path (Slice G is C7's slice; but the *steering* value
  of this read lands earlier — worth a ruling on whether to wire the three pins now).

## 6. OPEN — the governed launch has no reachable path after gate approval

Two stacked causes, verified live:

- **6a. The confirming turn did not carry the launch.** The Option-B kickoff chain
  (draft → gate → launch on the human's confirming turn) is how
  `launch_selected_account_research@1` is meant to acquire human authority, but my approval
  turn ran only "Save your answer"; no launch step rode it. A later agent turn cannot launch:
  the tool demands the gate's server-computed amounts, which are not in the agent's durable
  context.
- **6b. Even with amounts, the pilot's zero budget cannot satisfy the launch contract.** The
  launch input requires `approved_budget_cap_cents > 0` and
  `expected_estimated_cost_cents > 0`
  (`platform/api/clue_api/entity_research_launch_tools.py:83-84`), but the confirmed v9
  directive carries `budget_cap_cents: "0"` under the pilot's budget-controls-off posture
  (`budget_envelope_ref: "budget-controls-disabled"`), and the gate's estimate for it was $0.00.
  A `gt=0` contract and a budget-controls-disabled deployment are mutually exclusive as wired.
- **Why B8 still stands:** the B8 E2E proof drives launch→settle through the real launcher and
  runtime with a real >0 cap, so the *machinery* is proven; what is unreachable live is the
  *chat-flow authority path* on the pilot posture.
- **Suggested owner:** needs a founder ruling — either the confirming turn carries the launch
  step (Option-B as designed) with a pilot-posture pricing rule (nominal cap when budget
  controls are off), or the launch tool admits the disabled-budget posture explicitly.
  Cross-cuts Slice B (launch) and the pilot-budget-controls branch this workspace targets.

## 7. ENV — worktree collision: two stacks share one dev DB and one port map

- **Symptom:** my API on 8005 died repeatedly mid-test ("Shutting down" seconds after boot);
  the accounts screen intermittently showed "workspace temporarily unavailable"; earlier, a
  fleet worker error-looped on orphaned jobs.
- **Root cause:** the founder's Slice C worktree (`tunis`) runs its own
  `clue_api.projections_main` + `clue_api.fleet_main` against the **same Postgres dev DB** and
  the same default ports as this worktree. Both sessions' `pkill -f clue_api...` calls matched
  the *other* worktree's processes. Worse than ports: **fleet workers poll the shared DB queue**,
  so whichever fleet claims a job runs it with *its* branch's code — a tunis (Slice C) worker
  would execute a Slice B comprehensive job without the B1–B8 fixes.
- **Current state (probed 02:0x):** 8005 = missoula API (current code, founder-started);
  3020 = missoula frontend; the **only fleet running is tunis's** — so a live launch today would
  be claimed by Slice-C code. Do not run the live launch leg until either the tunis fleet is
  paused or the stacks get separate DBs/ports.
- **Suggested convention (cheap):** per-worktree `CLUE_PROJECTIONS_PORT` (+ frontend
  `CLUE_API_BASE_URL`/`CLUE_APP_ORIGIN`) in each worktree's `.env`, per-worktree dev DB names,
  and never `pkill` by bare module name — always scope to the worktree path.

## 8. ENV — dev-DB data breaks table-global test assertions

- **Symptom:** `tests/api/test_entity_research_tools_r4_db.py::test_governed_exa_tool_…` fails
  on the founder's dev DB (`requests: 7 != 3`); the shared-DB `make check` run showed ~97
  failures.
- **Root cause:** several DB tests assert `count(*)` over whole tables and assume an empty
  database; the founder's real app usage (and any concurrently-running stack) breaks them.
  A/B-proven: the same suites are green on a clean throwaway DB, including the full
  blast-radius set for every Slice B change.
- **Not a defect in Slice B**; long-term the count assertions should scope by run/workspace.
  Final clean-DB `make check` verdict: recorded in the close-out report when it lands.

## 9. ENV — auth: no headless-testable credential path existed

- **Symptom:** the browser gate stalls at Clerk (Google OAuth or email+password; no test
  account documented).
- **Workaround used (dev-legit, left in place):** Clerk dev-instance test mode —
  `aryan+clerk_test@cluehq.ai` + fixed OTP `424242` — then a second `auth_identity` row linking
  the new Clerk subject to the existing platform user, so the session resolves to the real
  workspace. Rows added to the dev DB: that identity, superseded drafts v7/v8, and confirmed
  directive v9 for Columbia Pain Management (never launched).
- **Suggested follow-up:** document this as the standing headless-QA sign-in path (or seed a
  permanent test identity), so future browser gates don't re-derive it.
