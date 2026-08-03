# Stage-0 live acceptance run — 2026-08-01 (PASSED with findings)

Branch `platform/clue-trial` at `c7db75d`. Full repair plan
(`docs/superpowers/plans/2026-07-31-stage0-structured-output-repair.md`) implemented, reviewed
per-task, whole-branch reviewed, plus live-diagnosed fixes F6 (pin resolution before graph review,
merged args to pins_for), F7 (governed tool failures → typed visible model feedback, 3/turn budget,
`agent.tool_repair` log), F8 (enforced preconditions in model-facing field descriptions +
prevention-gate test + skill v5 + profile v7). All commits local; nothing pushed.

## Acceptance scenario (trial-acceptance-aura-c1, live Terra via OpenRouter, no Sumble spend)

- Multi-turn interview: campaign intent → product facts → personas → deliberate correction →
  summary probe → post-synthesis question. All committed turns `awaiting_input` with receipts
  reported per the v5 skill; one dense multi-fact paste finalized `blocked` HONESTLY ("nothing was
  recorded") with actionable repair advice — the fail-closed path is now survivable and truthful.
- Durable state: 9 interview statements (`project_state` + `unmapped`), correction supersession
  live (`correction_of_id` present and honored downstream), 3 system-actor readiness decisions,
  zero duplicate writes across an idempotent turn retry.
- Human gates: `/product:confirm` then `/icps/1:confirm` (`icp_key
  independent_neurosurgery_spine_practices_us` v1, `created_by human:stage0-trial-cli`).
- ICP synthesis: `status=grounded`, single proposal "U.S. independent neurosurgery and spine
  practices" honoring the mid-conversation correction (excludes hospital-employed departments),
  personas in the description, `healthcare_practice` pack, NPI-weighted rubric, US-geo discovery
  strategy, 4 justifying statement ids, honest `no_client_kb_claims` reason code. No generic
  fallback proposal anywhere.
- Fresh-process resume: server restarted; trial state, confirmed ICP, and history reconstruction
  (T5 summary proves context) all intact.

## Product findings for the quality evaluation (not defects in the repair)

1. **Claim-route entailment is stricter than a model can satisfy for composite facts.**
   `_exact_quote` requires the claim value verbatim inside the quoted span; list-valued facts
   ("SOAP, APSO, and H&P"), booleans, and normalized values can never pass. Terra correctly fell
   back to UNMAPPED evidence, so the Client KB stayed at 0 claims. Decide deliberately: keep the
   strict lock (facts enter the KB only via recon/research), teach the skill single-span atomic
   claims, or extend the verifier for typed composite values. Do NOT weaken casually — the
   honest-empty behavior is working as designed.
2. Product-scoped `client.*` claims additionally require the confirmed product; that precondition
   is still undocumented in the field descriptions (F8 re-review minor).
3. The `blocked` finalize status remains an unguarded-but-honest prose channel (watched, fine).

## Open follow-ups (deferred minors digest, survived from the SDD ledger)

- Server-side per-turn message limit decision (CLI caps 16KB; `TurnInput.message` unbounded);
  re-derive the client cap after deciding. Head-of-ABM `max_output_tokens` is the real echo bound.
- Plan-rejection reason text should ride the same 600-char bounding as operation failures;
  refusal tool-results use status-success vs finalize's status=error (presentation).
- `synthesize_icps@1` pinned contract exposes `proposal_count` only (agent can't see grounded
  status); `evaluate_stage0_readiness` passes model-supplied metrics into the readiness ledger
  (mark rows by `created_by_actor`); `_GUARDED_STATUSES` literal duplicated; delegate_specialist
  still raises on failure; `clue-agents`↔`clue-obs` now declared (fixed in F7 wave).
- Prevention gate doesn't catch a new rule on an already-described field; product-confirmation
  precondition description gap (finding 2 above) is the live instance.
- Pre-existing, unrelated: `tests/execution/test_recipe1_cutover.py` one failure; shared-DB
  cross-test pollution mode; `tests/icp/test_compiler.py::test_tier_plan_and_gate_carried_verbatim`.

Next step per the trial plan: `/account add <domain>` + supervised 3-credit Sumble canary — user-run.
The trial server was left running at `http://127.0.0.1:8010` (`clue_api.trial_main`).
