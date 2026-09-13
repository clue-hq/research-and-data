# 2026-09-13 — live walk findings (plan 4 in anger) and the workspace reorganisation rulings

**Lane:** `research-streaming`, worktree `san-salvador`, stack on profile v49 / recipe v26.
**Branch state:** rebased onto `origin/brand-context-polish` (`dedd196b2`, one alembic head).

## The failed turn (thread `thr_befd7bf520e95e73bf66eac9f189d355`, 05:23 UTC)

The founder asked "what was researched about Arthur Direct Care?"; the turn died `runtime_error`.
Worker logs (`/tmp/san-salvador_fleet_worker_{2,3,4}.log`) show five distinct causes:

1. **`read_discovery_run@1` fails its own output contract, every call.** `DiscoveryCandidateView.pass_`
   has only `serialization_alias="pass"`; the tool dumps by alias and the toolbelt runner re-validates
   the JSON against the same model, which accepts only `pass_` → "Field required" ×8. The offline
   test asserts on the dumped dict and never goes through `validate_tool_result`. **Defect, ours.**
2. **`read_account_research@1` claims read exceeds the 16 KiB governed-receipt bound**
   (`clue_agents.execution.GovernedOperationReceipt`, `reference_values` > 16_384 bytes). Bounds
   MAX_CLAIMS=120 / EVIDENCE_CHARS=240 / BODY_CHARS=6000 were set without that cap; Arthur Direct
   Care's 72 claims overflow it. The overview path (6 sections × 6000 chars) has the same exposure.
   **Defect, ours.**
3. **`overview_not_written` was honest.** Overview blocks are written lazily by `ensure_page` on the
   first account-page view (a spend path). Of five "Researched" accounts only two have overviews.
   "Researched" = research job completed, not overview written. Decision open: render at research
   completion.
4. **The agent guessed `field_prefix="firmographic"`** → `no_claims_under_prefix`. Real prefixes on
   the account: `core.*`, `account.icp_fit_verdict`, `account.committee_candidate`,
   `account.resonance`, … The refusal names no prefixes; the tool description only shows one example.
5. **The turn died because `_MAX_GOVERNED_TOOL_FAILURES = 3` is per turn across all tools**
   (`agent_runtime_wiring._tool_failure`). Five parallel account reads → fourth refusal raised
   `RuntimeError`, LangGraph cancelled the two in flight (asyncpg `CancelledError`). Pre-existing
   runtime rule; honest read refusals should not spend it (ruling W10 below).

DB facts used (lane DB via `CLUE_DATABASE_URL`, TCP 55040): Arthur Direct Care
`4da436a7-0936-4e19-b858-4f8c9f25ea3d`, 72 claims, account job `completed`, 0 `display_block` rows;
Aura Psychiatry / Preferred Primary Care have 6 live overview blocks each.

## The workspace as it is today (verified on disk)

`CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-san-salvador/<ws>/<project>/<execution>/`
— one directory **per turn** (execution id derived from the turn id; turn id = uuid5(workspace,
thread, idempotency key); thread id = uuid5(workspace, operation id) at create-thread or Home
bootstrap). Layout `.deepagent/ inputs/ context/ work/ delegations/ outputs/`; inputs and context
are materialized from rows filtered by workspace/project (brand knowledge ≈ 330 KB copied per turn);
thread history (L6) is read from `agent_thread_message`, never from files; `outputs/` snapshots to
artifacts at close; retention 24 h; quota 200 files / 10 MiB per turn. Isolation is per workspace
(tenant), enforced by fd-anchored `O_NOFOLLOW` walks, 0700 dirs, segment validation, ambient
`workspace_id` from the membership-proved principal (`WORKSPACE_FORBIDDEN` on mismatch).

## Rulings taken (founder, in discussion) → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md`

W1 four levels (workspace library / project library / thread scratchpad / turn); W2 the project
library is a materialized view of rows, mounted read-only, written through one save operation;
W3 pinned/current version only in view; W4 artifacts by reference; W5 thread scratchpad persists;
W6 one `save_project_document@1` replaces the three document tools, folder decides kind, one skill
per kind; W7 the pin gate stays human; W8 personas written by the Head of ABM, not via an
onboarding run; W9 reads page (`offset`/`limit`/`next_offset`) and spill to `reads/` above the
receipt bound, plus `read_claims@1` and `read_artifact@1`; W10 honest read refusals do not spend
the failure budget; W11 brand knowledge mounted once per version. Constraints kept: Postgres is
the truth, versioned documents, human pins, no agent claim writes, replay pins, DSAR, 16 KiB
receipts. Build order in the spec §6; the two contract/receipt defects ship first as a hotfix.

## Owed

- The plan-1…4 live walk remains owed; the checklist given to the founder this session (27 items)
  supersedes the per-note lists in scope but not in SQL.
- Hotfix on the current tools before the reorganisation: `pass` alias on input, byte-bounded reads,
  prefixes in the `no_claims_under_prefix` refusal, W10 in the runtime.
- Decision: render the overview at research completion vs on first view.
