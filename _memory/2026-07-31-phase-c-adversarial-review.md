# 2026-07-31 — Full Phase C adversarial review (multi-agent audit)

Review-only session on `platform/clue-trial` @ `d6541cf` (the Codex/GPT session committed the
Stage-0 persistence fixes mid-review; reviewers covered that commit). Method: 7 Opus reviewer
agents (C1+C2, C3+C4, C5, C6, C7, clue-trial, cross-phase-dependencies) + 1 transcript digest of
the founder's attached session log. Every finding verified against code with file:line; each
report carries its own refuted list. No code changed in this session.

## Process/meta findings

- **`make check` is RED on this branch right now**: 1 test failing —
  `tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
  (offender `platform/api/clue_api/trial/stage0_runtime.py:18` imports `clue_memory` directly);
  ruff format would rewrite 19 tracked files; 41% of tests skip without a DB.
- **Zero fixes landed for the 2026-07-27 C5/C6 confirmed defects** — `git log` shows no commits
  touching `platform/execution` or the C6 defect sites since that audit. All 10 top defects +
  second-tier items re-confirmed STILL PRESENT at current line numbers.
- **C7 post-review remediation was real**: 5 of 6 confirmed gaps genuinely closed
  (production governance reader exists and is fail-closed; C7-D7 support use-policy enforced for
  contact roots; multi-product fixes all landed; entailment parser shared; FLAGGED/REDACTED
  precedence fixed). Sweep-parity closed in code but has NO test.
- **Fixture-vs-production divergence**: all C7 HTTP/adversarial tests run against stub
  governance; production evaluator has 3 DB tests; `tests/api/test_c7_handoff_cutover.py`
  cross-product proofs exercise the DEAD `GovernedCommitteeViewReader` (production wires
  `DbCommitteeViewReader`). `c7_governance_shadow_compare_enabled` has ZERO consumers but the
  runbook lists it as rollout step 1.
- Root `CLAUDE.md` backlog stale: `[C1×C6]` evaluator placement is RESOLVED by C6-D11 (engine
  leaf kept as sole owner, machine-tested) but still listed as flagged/pending.

## Critical findings (headline set; full details in the conversation report)

Trust boundaries caller-controlled:
1. Interview grants tier-1 to any `client_entity_id` the caller nominates — client-about-target
   cap unenforceable (`stage0/interview.py:265`, `stage0_tools.py:241`). Agent-admitted tool.
2. Ingestion trust tier is caller-declared `material_context` (`ingestion/engine.py:739`).
3. Readiness floor computed from caller-supplied `metrics` dict — agent can mint READY and start
   discovery spend (`stage0/governed.py:739`, `stage0_tools.py:255`); only trial spine produces
   metrics; no production computation.
4. Interview stamps model-supplied immutable `identity_binding` (never calls `classify_binding`;
   `interview.py:299`); also `committee/admission.py:190` hardcodes STRONG;
   `import_accounts.py:667` heuristic.
5. C2 source promotion can silently REDEFINE an existing live source manifest (proposer controls
   `source_key`+`version`; `register_source` versioned-update, no new-key check;
   `proposals/service.py:286`, `sources/registry.py:308`). Field side has the guard; source side
   doesn't. Reachable autonomously with `auto_promote_tier3_sources=True`.

Spend/money:
6. Trial: Sumble credit-overage (`SumbleCreditContractViolation` ⊄ `SumbleContractError`)
   releases the idempotency ledger → unbounded repeat paid calls on retry
   (`trial/sumble.py:292`, `resolvers/sumble/__init__.py:82,290`).
7. §C8 "all spend paths gated" FALSE: Sumble paid call, M12 positioner, ICP synthesis, discovery
   query planning, C1 goal judge, C5 supervisor LLM all ungated; the spend-path inventory test
   scans only `subsystems/research`, keyword-presence only; all engine gates `None ⇒ allow`.
8. C6 agent model spend recorded as `cost_millicredits=0` hardcoded
   (`agent_runtime_wiring.py:213`) → delegation budget ledger, canary cost gate, telemetry all
   vacuous. Plus delegation steps excluded from slot ceilings → per-turn child wakes bounded only
   by recursion limit (~52).
9. C1 coverage spend commits on its own txn, ledger on the tool txn → attempts/spend do not
   reconcile; Redis-lock loss → double provider pay with one attempt row
   (`coverage/controller.py:258`, `repository.py:134`).

Concurrency/durability:
10. Trial spine calls `driver.advance()` in a loop with NO lease; M7 phase ledger `stale_after=0`
    assumes single driver; CLI mints fresh Idempotency-Key per attempt → concurrent duplicate
    phase drives (`trial/spine.py:436`).
11. Constant `worker_id`s (`stage0-trial-cli`, `agent-account-research-preparer`) defeat the C5
    generation fence via the re-entrant acquire branch (`lease.py:52-74`) — two processes share
    (worker_id, generation), all fence checks pass for both.
12. C5 NEW: `NODE_BLOCKED` → `AWAITING_INPUT` is absorbing — no resume path, no operator
    control, reachable via `advance_project_phase` precondition failures (`executor.py:851,1457`,
    `execution_tools.py:363`).
13. C5 prior stills: executor infinite spin (pre-begin raises swallowed, no attempt cap);
    review-approval stall (`review/composition.py:218`); map-expansion replay double-count;
    lineage guard only in router; supervisor/controls unlocked cursor reads; lease-expiry-in-place
    → task FAILED cursor RUNNING, no reconciler; binding-resolution failures die with no journal
    terminal; DSAR parameter erasure purges shared content-addressed artifacts across executions;
    SSE seq-vs-commit-order drops events.
14. C6 prior stills: workspace `.clue-tmp-*` crash-brick (turn unfinalizable forever); stale
    `agent_runtime_route` row (append-only, no liveness) crash-loops entire fleet boot — rollback
    one-way; FAILED finalize masked as `missing_finalize` (+ poisons delegation retry);
    required-context starvation; uncertified `research_account_gaps@1` default+HTTP-only version,
    mis-declared WRITE; A9 pending row after kill -9 bricks run for 24h TTL (no sweeper, no node
    retry → EXECUTION_FAILED).
15. C6.5/C6.6 have NO production composition (Stage-0 runtime only in trial with delegation
    disabled; `FreshWakeSpecialistRunner` unconstructed; `evaluate_agent_canary` never called).

Compliance/governance:
16. C7 NEW: DSAR-erased contact's full_name/verified_email/linkedin served verbatim by
    owner-reference endpoint IDENTITY branch (`research_view_owner_refs.py:200`); DSAR never
    touches `contact_entity`; surface missing from dsar_surface_map.
17. C7 NEW: retention sweep runs before HANDOFF; `write_handoff` erased-subject guard is
    reason/scope-blind → one expired sensitive facet permanently wedges HANDOFF
    (`handoff_store.py:98`, `handoff_retention.py:94`); `LegacyHandoffErasedSubjectError` never
    caught.
18. Retention-expired-cannot-win-merge is VACUOUS in production: `record_lawful_basis` has zero
    production callers; predicate keys on absent rows; merge retention-unaware; the proving test
    seeds the recorder itself.
19. Production handoff composed WITHOUT `require_finalized_review=True`
    (`run_composition.py:547`) → unreviewed accounts emit to content layer when flag on.
20. Doc M species split defeatable: no species gate on claim writes; agent-authored memory born
    ACTIVE/USER_STATED; trial reads memory via raw SQL bypassing assembly gate incl.
    objection-LOCKED memories (`stage0_trial.py:928`).
21. Entailment judge: zero adversarial fixtures, no MECH_ENTAILMENT in eval harness, manifest
    case points at a projection test; M9.6 deferrals repeated for a new injectable judge.
22. DSAR uncascaded: `AgentPrivacyService.erase_subject` + `clue_memory.erase_subject` never
    called from `DataSubjectRightsImpl`; C3 `IngestionEngine.erase` has no production caller
    (raw upload/segments survive subject DSAR); most agent artifacts have no subject binding.

Product isolation:
23. Corroboration + conflict_flag are product-blind → cross-product mutual demotion of
    legitimate claims AND cross-product corroboration inflation (`verification/corroboration.py`,
    consumed product-blind by C7 governance).

Other notable (Important tier): C3 ingestion engine never composed (upload route mounted →
orphan artifacts + 422); readiness enforced only at DISCOVERY gate (ICP_SYNTHESIS/DEEP_SPEND
recorded-and-ignored); `start_confirmed_project_run` accepts a DRAFT ICP; recon "background"
lane is synchronous inside one txn; C5 dispatch recheck covers none of the run-identity pins and
Recipe-#1 node pins are `__runtime__` placebos (`required=False` retired passes); trial 3-credit
cap not aggregate/atomic/durable + server accepts arbitrary `sumble_credit_cap`; 429/5xx
misclassified as spend-unknown → permanent wedge, `retry_persistence` uncallable; trial cost
surfaces non-cumulative/manifest-only; generic_web resolver never registered while ICP-synthesis
proposals hardcode `tier_plan=("generic_web",)` → promoted fields permanently unfillable;
d6541cf next-action fallback hollows honest-finalize envelope; finalize replay requires
byte-identical model output; C2 registries global → cross-tenant key-squatting DoS; C5 recipe
lifecycle unscoped; enum-parity tests missing for C1/C3 enums.

## Verified good (do not re-chase)

Fleet worker fencing (B1 repairs hold); C5 journal event/cursor/outbox atomicity + real
generation fence on journal writes; feature-gate no-double-drive on the fleet lane; C1 authority
boundary (evaluator advice non-authoritative, single owner via C6-D11, machine-tested); C2
policy safety floor + field-side redefinition guard + workspace fail-closed proposals; C3
idempotency/stage-separation/evidence-spans/contact governance born-correct; C4 human-only
overrides triple-enforced + PC-D4 closed on harness path + spend-path static inventory for
waterfall callers; C6 tool-surface middleware + allowlist narrowing + fresh-wake isolation +
workspace fs hardening + honest Head-of-ABM prompt; C7 production read stack live/fail-closed/
body-free, snapshot replay re-resolves, evidence single-presign + 300s cap, entailment mechanism
hardened (no rationale channel); handoff committee reader real, `narrative_emit_skipped` writers
gone; trial receipts archived-before-claims in one txn, tech-stack opt-in genuinely enforced,
tier-approval fix real and traced, no governance bypass on direct-account admission, secrets
clean; Alembic single head `6a7f8eed5b23`, all reversible, hash ids.

## Follow-ups / state

- Full consolidated report delivered in-conversation 2026-07-31. Fixes NOT applied.
- Founder context: no Sumble credit ever spent; founder never got past first Stage-0 message;
  canary runbook tells operator to enable `CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true` — reconcile
  against the review's "no C7 flag until blockers fixed".
- Root CLAUDE.md `[C1×C6]` entry stale (resolved by C6-D11) — update at next backlog pass.
- Pre-canary blocker shortlist: Sumble overage ledger release; per-request resolver-registry
  wipe (spine `clear_resolver_bindings()` on every HTTP request incl. doctor — silently discards
  paid data mid-run); trial lease/worker-id fixes; 429 unwedge path; cumulative /cost from
  Postgres.
