# 2026-08-10 — Founder ruling: interim verification scope reduction, recorded for Lane F

## The ruling

For the time being the platform runs with the M9 runtime verification toggle **off**
(`CLUE_VERIFICATION_ENABLED=false`): deterministic corroboration (M9.2) and the LLM
faithfulness judge (M9.3) are bypassed. This is a scope reduction, not new machinery —
the founder asked for a toggle that **already exists** on this branch:

- `Settings.verification_enabled` (`settings.py:107`, default `true`), landed 2026-08-08
  (`_memory/2026-08-08-m9-runtime-verification-toggle.md`).
- Extended 2026-08-09 by the A+B toggle-compat change (`5bc82f3d`): optional judge on every
  write path (positioner, Lane E prose) + the toggle-aware `active_merge_policy()` merge
  chokepoint, so with the flag off unverified tier-4 claims are *served*, not shelved
  (`_memory/2026-08-09-ab-verification-toggle-compat.md`).
- Lane E (merged 2026-08-10, `1fa11d42`) proved every writer in both toggle states.

A parallel-session conversation ("Explain M9 Verifier" transcript) concluded no such toggle
exists and sketched a `CLUE_VERIFICATION_MODE=full|judge_only` design — that conclusion was
**stale for this branch**; no new flag is needed. If a finer-grained mode (skip corroboration
but keep the judge, or vice versa) is ever wanted, that is a *future* extension of the
existing flag, not a competing one.

## What off-mode actually means (verified against code + memory notes)

Skipped: M9.2 corroboration; M9.3 judge at every call site (verification phase,
reverse-profiling `run_composition.py:292`, toolbelt entailment, M12.1/Lane-E synthesis) —
zero judge spend; `require_verified_tier4` relaxed at the one merge chokepoint.
Kept: pre-spend authorization, born contact identity binding, freshness/retention, M10 use
gate, rejected + weak-binding merge exclusions. The VERIFICATION phase still runs and
advances, recording `verification_enabled=false` + `accounts_skipped`.
Ops: set the env var and restart API + fleet worker. Deployment-scoped, not pinned per run
(a restart mid-run can change the mode before an uncommitted verification phase — known,
accepted for the interim).

## Where it is recorded

- `docs/specs/M8D-R11-deep-phase-bridge.md` **§1a** (new): the ruling + its binding
  consequence for R11 — the bridge is built and accepted against **both** toggle states;
  R11.3's fail-loud selector fires in both modes; no judge/gateway dependency may break
  disabled-mode composition (Lane E's optional-judge pattern is the precedent).
- Same spec **§5 AC 8** (new): every acceptance criterion holds under both toggle states,
  with the disabled-mode advance recording the skip honestly.

## Open

- R11 §6 (a)–(e) ratification still pending; the committee-bridge scope amendment (R11.5)
  and worktree-kickoff section still to be written before Lane F is staffed.
