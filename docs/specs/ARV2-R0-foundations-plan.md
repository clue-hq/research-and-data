# ARV2 R0 — Foundations plan for the research-lane rebuild

**Status: RATIFIED by founder (Shashank), 2026-09-01.**
The base-branch decision (Part 2) also
needs Aryan's sign-off per its own terms (it merges his branch). Authored 2026-09-01 from a
six-agent parallel study of this branch (`integration/design-improvement`, worktree `semarang`)
with every load-bearing claim re-verified first-hand against the code: the two kill-switch
inversions, the C7 read gate, the flag defaults, the DEEP-slot handler, the R1 quarantine list,
and the catalog version collision. Companions: the ARV2 spec set in `docs/specs/ARV2-*.md` on the
`install-agent-browser-global` branch (chicago worktree) and the proof-of-concept evidence in that
worktree's `.context/` (sample runs v1–v3, the AI Ark canary, the cluehq.ai smoke test).

> **Name correction (2026-09-04):** git authorship shows the ratifying/tech founder is **Aryan**
> and the PoC/spec author and accounts-lane co-founder is **Shashank**. This document's owner
> labels are swapped in places; read them by role: "Shashank" rows = the tech founder (Aryan),
> "Aryan" rows = the co-founder (Shashank). Body left as ratified.


**Program context this plan serves (founder rulings, 2026-09-01):**

- The v1 release drops the scoped-memory subsystem from composition; a durable **project context**
  (account count/list, artifacts, ICP ref, project state, conversation) replaces it.
- Stage-0 fast/background recon is retired; onboarding becomes a research pipeline — parallel
  research agents writing `.md` artifacts into the platform deepagent's workspace filesystem,
  ICP proposals as `.md` artifacts, prompt-driven interview, final ICP stored under project +
  brand context.
- **No mechanical gates, no secondary-LLM judges** anywhere in interview → ICP synthesis →
  account discovery. The Head-of-ABM deepagent is the only judge, via system prompt and skills.
  The two survivors: the claim write-shape gate (data integrity, not verification) and human
  authority gates.
- The account-research pipeline (discovery → enrichment → account deep research → committee →
  contact deep research) is rebuilt on the PoC's proven principles: Exa + AI Ark + free ATS APIs,
  web-first committee, no waterfall, single-source writes, claims with quotes + source URLs.
- The claim-store DB schema stays. The waterfall is quarantined, not deleted.
- Frontend: `conductor/repos/clue-frontend` (the dummy frontend) is presentation truth. No new
  or AI-invented components. The backend may fetch data the frontend does not show.
- Division of labor: Shashank — platform deepagent, onboarding/ICP rework, project context,
  Exa MCP search tool. Aryan — ARV2 research-lane productionization + accounts frontend/backend
  integration.

---

## Part 1 — Three verified facts that shape the whole plan

**Fact 1: The 15 days of pilot debugging live on a branch this line is not on.** The current line
(`integration/design-improvement`, pilot-budget-controls lineage) and
`platform/comprehensive-account-contact-research` split around 2026-08-18. Comprehensive has
**128 commits this line lacks** — the guard retirements, the record-only spend posture
(`spend_posture.py`), the crash-absorption fixes, the claim-lineage fixes, and the
`CLUE_PRODUCT_PATH` pilot overlay. This line has **~800 commits comprehensive lacks** — nearly
all design-subsystem and frontend work. Verified: the two sides are almost perfectly split by
module; **only 26 files were touched by both since the merge-base.**

**Fact 2: The old research lane is already behind one switch.** The entire M8D entity-research
runtime hangs on `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` (default `False` in code —
`libs/clue-config/clue_config/settings.py:266`). With it off: the fleet worker owns no
research-job handler, all six launch/read tools refuse with a typed "not composed" message, and a
project run parks safely at the DEEP phase (the R11 bridge holds it PAUSED, re-entrant —
`platform/api/clue_api/run_composition.py:555-561`). The pre-M8D orchestration is already dead
behind the R1 quarantine (nine replay-only tool stubs,
`platform/api/clue_api/entity_research_quarantine.py:49-61`). **Most of the old lane does not
need deleting — it needs one flag and a handful of surgical edits.**

**Fact 3: Flag flips alone cannot reach the "no gates" posture — two switches are wired
backwards.** Both confirmed in code:

- **Inversion (a):** turning verification OFF makes the Stage-0 interview *unable to write typed
  values* — with no entailment judge composed, any number/bool/list answer is refused outright
  (`subsystems/research/clue_research/stage0/interview.py:746-754`).
- **Inversion (b):** an inline `Corroborator` runs unconditionally inside Sumble claim
  materialization and can block field resolution even with verification off
  (`platform/api/clue_api/sumble_claim_materialization.py:159-181`).

These are the concrete reason the interview "asked everything of the user" and the pipeline felt
gated regardless of what was switched off. They are small, named edits — not a rewrite.

---

## Part 2 — Decision 1 (needs both founders): the base branch

**Recommendation: stay on this line and MERGE `comprehensive-account-contact-research` into it.**
Not cherry-pick, not rebase onto comprehensive.

- Rebasing onto comprehensive throws ~800 design/frontend commits into the same 26-file conflict
  zone from the harder direction.
- Cherry-picking is infeasible: the valuable fixes are interdependent families (the settlement
  fixes layer five commits deep; `spend_posture.py` is built across three commits) interleaved
  with 11 chained migrations.
- Of the 128 commits, **~35–40 fix substrate being kept** (fleet durability, gateway retry, claim
  lineage, spend-record-only, the memory-seam-cannot-veto fix, the `CLUE_PRODUCT_PATH` overlay
  with credential preflight) and **~30–35 fix machinery being quarantined anyway** (the Sumble
  committee family). The merge takes both for free; the quarantined ones simply go dark.

**The one real merge hazard, verified:** both branches independently minted **head-of-abm profile
v37/v38 and recipe v17/v18 with the same version numbers but different contents** (v38 diffed
directly: different prompt and skill pins). Comprehensive's versions must be **re-minted as
v41/v42 (recipes as v20/v21)** before the merge, with their pins repointed. Plus: one
`alembic merge` join (11 research migrations vs 14 design migrations, disjoint tables, two heads
after merging), ~12 shared-file textual resolutions (chat router/schemas, `agent_model.py`,
`settings.py`, `.env.example`), and one re-lift of comprehensive's research-task chat card onto
the current frontend. **Roughly one careful day of work.**

---

## Part 3 — The quarantine ledger (what gets cleaned up, exactly)

### A. Already inert — no action needed

| Component | Why it is already dead |
|---|---|
| Pre-M8D orchestration (~8.5 kLOC) | Behind the R1 quarantine; 9 tool addresses are replay-only stubs |
| Old quarantine DEEP handler | No longer registered anywhere; DEEP slot is the R11 join bridge |
| Apollo / Clay / ZoomInfo / BuiltWith / CRM / registries / Parallel resolvers | Only reachable via `register_deterministic_resolvers` / `register_synthesis_wiring` — **zero production callers** (verified) |
| C7 nine-block view + its verified-only read gate | Composed only under `c7_*` flags, all default false. Leave dark — the frontend flow does not use it |
| Derivation judge, LLM supervisor triage, deep-canary controller | Built but never composed |

### B. Quarantined by flag flip (R0 sets these)

| Flag | Set to | Effect |
|---|---|---|
| `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` | `false` | Whole old M8D lane inert (`.env.example` currently says `true` — flip it) |
| `CLUE_SUMBLE_*` (all four) | `false` / empty key | Sumble out everywhere |
| `CLUE_MEMORY_ENABLED` | `false` | Memory parked cleanly: L4 context layer assembles empty, interview memory-routes return `MemoryDisabled`, directive drafting records-and-proceeds. **Missing from `.env.example` — parity violation, fix in the same commit** |
| `CLUE_SELF_SERVE_PROVISIONING_ENABLED` | stays `false` | Fast/background recon never composes; `start_recon` refuses before spend. **Also missing from `.env.example`** |
| `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE` | stays `off` | Durable crawl parked |
| `CLUE_BUDGET_CONTROLS_ENABLED` | stays `false` | All budget caps record-only |
| `CLUE_VERIFICATION_ENABLED` | `false` — **only after the Part 3C inversion fixes land** | Removes corroboration, the faithfulness judge at all four roots, the reverse-profiling judge, the prose judge; the merge serves unverified tier-4 claims |

### C. Small surgical code edits (the actual cleanup work — each a named, bounded change)

1. **Fix inversion (a):** accept typed interview values without a judge — one branch at
   `stage0/interview.py:746` (record the basis instead of refusing). *Owner: Shashank (interview lane).*
2. **Fix inversion (b):** delete the inline `Corroborator` block at
   `sumble_claim_materialization.py:159-181` (moot once Sumble is off; cheap insurance).
   *Owner: Aryan.*
3. **Stage-0 readiness floor:** `min_verified_claims ≥ 1` (`libs/clue-config/clue_config/stage0.py:56-67`)
   can never pass with verification off — drop to 0, or bypass readiness entirely in the new
   onboarding flow. *Owner: Shashank.*
4. **Research-lane mechanical gates** — retired on comprehensive; if any survive the merge,
   neutralize on the new lane: canary needs-review suspension
   (`account_research_fleet.py:1063-1103`), launch override-homogeneity
   (`account_research_fleet_launch.py:303-323`), must-have evidence gate, contact identity
   admission floor. **ARV2's new driver simply never calls them** — no old-lane edits needed.
   *Owner: Aryan.*
5. **Residual blocking money guard:** the Exa "provider cost exceeds reservation → quarantine and
   suspend" (`exa_deep_acquisition.py:592-604`) throws away a paid response — route to
   record-only. *Owner: Aryan.*

### D. Keep — do not touch (with one recommendation)

- **The write gate** (`check_claim_writable` + the claim model + DB CHECKs): data integrity, not
  verification — it produced the PoC's 106/106 and 203/203 clean claim sets and refuses with
  actionable messages. It is the closed-catalog mechanism the custom-variables design depends on.
- **Human authority gates** (ICP confirm, product selection, directive confirmation, launch,
  contact selection) — these are product.
- **Tenancy, append-only triggers, artifact/snapshot family, the fleet substrate, run lineage.**
- **Founder sign-off items, not silent removals:** the pre-spend authority gate, born
  identity-binding, the use gate/`display_allowed`, DSAR machinery. These are legal/compliance
  floors, not research-quality judges. Recommendation: keep all four — they cost nothing at
  research time and removing them can hurt a client in public.

---

## Part 4 — What R0 leaves ready for R1 (the ARV2 build)

Verified reuse points, so R1 starts with zero substrate invention:

- **Injection point:** `build_multi_work_worker` accepts any handler for `ENTITY_RESEARCH_JOB`
  (`platform/api/clue_api/fleet_wiring.py:324-337`); a new `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED`
  flag selects the ARV2 driver at `fleet_main.py:844-846`. No existing handler changes.
- **Provider ledger:** AI Ark and the ATS APIs join the existing
  `external_research_operation/_snapshot` acquire→persist-raw→materialize family (the Exa deep
  coordinator at `exa_deep_acquisition.py:212` is the worked example to copy). Free ATS sources
  use `auth_ref=None` manifests — a proven pattern.
- **"No waterfall" without touching the waterfall:** the live M8D path already uses single-source
  `tier_plan` overrides, making the waterfall a pass-through writer — or write directly via
  `insert_claim` from settled snapshots (the Sumble idiom). Either satisfies "quarantine the
  waterfall, don't delete it".
- **Mandatory for frontend visibility:** ARV2's run-mint site must call `record_run_lineage` — a
  claim whose run is not registered is invisible in every project section (verified at
  `research_view_readers.py:211-218`).
- **New files** (per the ARV2 build runbook, plus study findings): catalog folder
  `entity-research/arv2-account/v1` (the sha-pinned profile-ref mechanism is how job immutability
  works), driver + tools + `ai_ark`/`exa` clients, `ai_ark_api_key` in `Secrets`, seeds rows, the
  GTM-hiring pack (pure data rows). **`claim.signal_priority` does not exist anywhere** — the
  PoC's P1/P2/P3 ranking needs one new column or side-table (a real, small migration to schedule).
- **Trap to respect:** the toolbelt has a boot-time set-equality audit against the C6 agent-tool
  authority dict — any tool ARV2 adds or renames must update that dict or the process refuses to
  start.
- **Display layer:** the Lane-E prose machinery (tier-4 prose claims, idempotent per job/field,
  superseding writes) is the right skeleton for the Luna display pass; it needs a new field-key +
  synthesizer pair, not new architecture.

---

## Part 5 — Frontend R0 (Aryan's integration prep)

- **Re-lift, don't patch:** `apps/frontend`'s accounts feature is a drifted superset — it deleted
  all fixtures and grew five components that do not exist in the dummy frontend
  (`account-facts`, `evidence-list`, `table-pagination`, `accounts-recovery-screen`,
  `account-avatar`). Replace the feature wholesale from `conductor/repos/clue-frontend`, keep the
  existing auth/error seam (`frontend-api.ts`), and re-point the dummy's HTTP adapters at
  `/frontend/v1`.
- **Serving strategy:** keep the existing `/frontend/v1` backend (workspace scoping, merge
  policy, lineage, display gates are already solved there) and do the label/band/icon mapping
  **inside the frontend's repository adapters** — the dummy contract is mostly a display-shaped
  rendering of data the backend already serves at truth level.
- **Ten contract gaps need founder rulings before wiring** (headliners): collapsing per-project
  research status into the dummy's single 4-state enum; picking one `fitScore`/`overallFit` per
  account (the backend deliberately refuses to today); the three fit sub-scores
  (`referralFit`/`directAccessFit`/`recallFit`) which exist nowhere; `logoPath`/avatars/socials
  (previously ruled OUT — re-ratify or relax the schema); the `min(1)` paragraph requirements vs
  honest empty states; `locationCount`/`influence`/`businessParagraphs`/`fitCriteria` field
  owners; the activity-event vocabulary mapping; account-scoped artifacts read; the query/sort/
  table-config surface; and the envelope (`/api/v1` + `{data}` wrappers vs `/frontend/v1` + BFF
  header). Each gets a one-line ruling recorded in `apps/frontend/docs/api-contracts/accounts.md`.
  **This is the anti-slop mechanism: rulings on paper, zero invented components.**

---

## Part 6 — R0 execution checklist

| # | Step | Owner | Depends on |
|---|---|---|---|
| 1 | Ratify base-branch decision (Part 2) | both founders | — |
| 2 | Re-mint comprehensive's colliding catalog/recipe versions → merge comprehensive in → `alembic merge` → resolve ~12 files → `make check` green | Aryan | 1 |
| 3 | Land the R0 flag posture + fix the three `.env.example` parity gaps (memory, provisioning, frontend-read flags) | Aryan | 2 |
| 4 | The two inversion fixes + readiness-floor drop | split per Part 3C | 2 |
| 5 | Flip `CLUE_VERIFICATION_ENABLED=false`; verify interview still writes typed values | Shashank | 4 |
| 6 | Freeze the two seams on paper: the launch contract (`workspace_id, project_id, account_ids[], icp_artifact_ref, directive_text`) and the ICP artifact format (`.md` + structured gates block) | both, half a day | 1 |
| 7 | Founder ruling session on the ten frontend contract gaps + the four compliance-floor keep/remove decisions | both | — |
| 8 | Skeleton the ARV2 lane: flag, empty driver registered at the injection point, catalog folder, `Secrets.ai_ark_api_key` | Aryan | 3 |

**R0 exit gate:** on the merged branch — `make check` green, single alembic head, old lane
provably inert (launching research refuses with the typed not-composed message), interview writes
typed values with verification off, both seam documents signed, and the ARV2 flag + empty driver
in place so R1 (providers: Exa client, AI Ark client, ATS resolvers) starts with pure new-code
work.
