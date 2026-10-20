# Agent-authored account discovery — built, walked live, ready for PR (2026-09-30 / 2026-10-01)

Branch `discovery/target-discovery-trial` (worktree addis-ababa), base `research-streaming`.
Spec `docs/superpowers/specs/archive/2026-09-30-agent-authored-account-discovery-design.md`; plan
`docs/superpowers/plans/2026-09-30-agent-authored-account-discovery.md`; trial evidence and the
live-walk table in `docs/superpowers/drafts/2026-09-30-target-discovery-trial/README.md`.

## What shipped
- The Head of ABM writes the discovery brief (query, criteria, gates with roles must / must_not /
  prefer, source websets|search) on every `launch_arv2_discovery@2` call; `@1` refuses
  `discovery_tool_retired`. The ICP document is context, never parsed. The brief is never shown to
  the customer.
- Rounds re-use the same brief (max `CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3` top-ups); excluded
  companies stay off the accounts table and are recorded on the run (`excluded_by_gate`).
- One discovery per project (partial unique index); the thread is busy while it runs (messages
  held); Stop route `POST /api/v1/projects/{project_id}/discovery-runs/{run_id}/stop`; a derived
  `discovery_finished` wake turn reports every run; `read_discovery_run@3`.
- Head of ABM v70, stage0-interview v43 (section 7b), manual-* v16, icp-synthesis v4 (block YAML),
  onboarding-synthesis v4; migration `0a3a88c7e5ed`.
- Frontend: thread `discovery` field (list read only), composer running/Stop.

## Fixed during the live walk (2026-10-01)
- `ab9d4bc8e` the run's own wake turn takes the project lock over to relaunch (it was always
  refused `discovery_in_progress`). Proven live.
- `8c4ece872` verifier `quote_not_on_page` / `wrong_company` guards removed (founder ruling);
  `no_source`, `malformed`, `outside_window` kept.
- `9f4d04cc2` Exa `/search` + `category: company` returns 0 results whenever `excludeDomains` is
  sent (even `example.com` alone) — rounds now pad `numResults` by the known domains and skip them
  in code; `e05ce5f8b` caps verification at 2 × shortfall (an ask for 3 had verified 42).
- `7ff2f0a4c` tests/arv2/test_settings.py followed Task 7's removed switches; `7e6e63f1f` mypy.
- `45a3a63b7` removed the orphaned `data-model-settings.tsx` that broke `npm run build` on
  research-streaming (left behind by de80c454d).

## Founder rulings this session
- Wake message keeps `failed (provider_halted)`; no provider-neutral wording now; the "never name a
  provider" rule is not made global — a proper error registry comes later.
- Verifier guards: remove quote-on-page and right-company only.
- `must_not` gates ask about the company's MAIN business (`9f3d3f67d`); a company whose main
  business is the competitor's stays excluded even if it also operates. Own-site evidence rule not
  adopted. Replay: 15/15 correct.
- Transcript order: keep today's (a held message's answer sits under it, above the wake reports).

## Open (owed)
- "N messages queued" line does not show during a discovery hold; composer hint line (spec §7) not
  built — both await a design ruling.
- Pre-existing failures, not this branch: test_c8_trial_surface (5, stale
  open_directive_confirmation_gate expectation), test_account_research_port (recipe 24 vs 22),
  test_discovery_driver handler-composition test, 3 modules failing to collect (`duration_of`),
  mypy read_tools.py:537.
- manual-discovery v16 still lists the removed guard values (old rows may carry them).

## Verification
Backend: launch/driver/verifier/settings/read-tool/authority suites on throwaway DB
`clue_addis_sdd` (only the pre-existing failures above). Frontend: design-system build + lint +
build green; 28 chat/controller tests. Live walk: 10 runs, $3.82 on 2026-10-01 plus $0.86 of the
founder's runs; 65/65 added companies are hotel operators. Lane DB `clue_addis-ababa` is at
`0a3a88c7e5ed`; lane stack is UP on the branch head.
