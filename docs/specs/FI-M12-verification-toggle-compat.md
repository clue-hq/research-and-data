# FI — M12 / Lane-E compatibility with the runtime verification toggle

**Status: RATIFIED 2026-08-08 (founder; spec review complete same day) — ready for implementation.**
Date: 2026-08-08. Branch: `platform/frontend-integration`.
Parent: the temporary M9 runtime toggle `CLUE_VERIFICATION_ENABLED` (`Settings.verification_enabled`, default `true`; commit `784fb662`; context `_memory/2026-08-08-m9-runtime-verification-toggle.md`). Sibling: `docs/specs/FI-lane-E-on-completion-synthesis.md` (ratified same day — its E1/E2/E3 writers are first consumers of this contract).

## 1. Problem

The toggle only touches the **write** side of verification: when `false`, the VERIFICATION phase skips M9.2 corroboration and the M9.3 faithfulness judge, and the composition roots construct no judge. The **read** side is untouched: `claimstore/merge.py::_is_eligible` (governed by `MergePolicy.require_verified_tier4 = True`, `merge.py:103,136-141`) still refuses to serve any tier-4 claim whose `verification_status` is not `VERIFIED`. With the judge off, no tier-4 claim ever becomes `VERIFIED`, so the entire tier-4 layer goes invisible. That breaks M12 twice:

1. **Inputs** — the Positioner reads account evidence through `current_values` (`positioner.py:263`), so M11-synthesized tier-4 evidence vanishes → thin or refused narratives.
2. **Output** — the value narrative (and Lane E's `account.summary` / `contact.overview`) are themselves tier-4 `LLM_SYNTHESIS` claims; unverified, they are excluded by the merge and by the handoff's own VERIFIED-only filter (`handoff.py:506`) → nothing reaches the handoff or the frontend.

Plus a construction hazard: `Positioner.__init__` **requires** a `judge:` argument with no `None` guard (`positioner.py:198,463`). With verification off no judge exists, so composing M12/E3 as-is would fail to construct (or crash at the judge call with an explicit `judge=None`).

Verified baseline (2026-08-08 code studies): the Positioner has **zero production callers** today, and HANDOFF is parked behind the independent `c7_production_handoff_enabled` flag — so this is a design constraint on the upcoming Lane-E/E3 composition, not a retrofit of live behavior.

## 2. Ruling

**M12 and the Lane-E prose writers must work in both toggle states.** When `CLUE_VERIFICATION_ENABLED=false`, the tier-4 verification gate drops **globally** (founder-approved recommendation): every unverified tier-4 claim becomes servable as current truth, M12's inputs and outputs included. This deliberately reverses, *for the disabled mode only*, the toggle's original "never promotes unverified data" stance; the run is already stamped `verification_enabled=false`, and a served claim's `verification_status ≠ VERIFIED` remains the durable, queryable marker of its basis. Default `true` preserves every existing behavior bit-for-bit.

Rejected alternative, recorded: scoping the relaxation to M12's narrative output only (per-field or per-writer). More code, and useless in practice — M12 would still synthesize from a verified-only *input* picture, which is empty in disabled mode.

## 3. Changes

### A — Write paths tolerate a missing judge

- `Positioner` accepts `judge: FaithfulnessJudge | None`. When `None`: skip the inline judge call (`positioner.py:442-443,463`); the claim is written and left unverified (its born `verification_status` stands); `claim_support` provenance is still written; a metric records the skip (`research.narrative.judge_skipped`). When a judge is present, behavior is unchanged.
- The same optional-judge contract is a **build requirement** for Lane E's `prose.py` unit (E1/E2) — same skip/metric discipline.
- `HandoffAssembler._read_value_narrative`'s VERIFIED-only filter (`handoff.py:506`) becomes verification-aware: in disabled mode it accepts unverified (non-REJECTED) narrative claims, carrying the actual `verification_status` in the assembled handoff so downstream consumers see the basis honestly.
- Composition roots (`run_composition.py`, Lane-E fleet steps) pass `judge=None` instead of refusing to construct when `settings.verification_enabled` is false — mirroring what `784fb662` already does for the reverse-profiling and toolbelt judges.

### B — The tier-4 merge gate becomes verification-aware at its single chokepoint

- Every production read resolves to the one module constant `DEFAULT_MERGE_POLICY` (`merge.py:115`); no caller anywhere overrides `require_verified_tier4` (verified by sweep 2026-08-08). The fix is therefore one seam: the **effective default merge policy** is derived from settings — `require_verified_tier4 = settings.verification_enabled` — via a small accessor at the claimstore boundary (e.g. `active_merge_policy()`), so all defaulted call sites flip together and no per-site threading is needed.
- `fallback_to_unpromotable` stays `False`; `exclude_rejected` and `exclude_weak_binding` stay `True` in **both** modes — a judge-REJECTED claim and a weak-bound contact claim are never served regardless of the toggle (identity protection is not verification).
- Acknowledged debt: this bypasses the dormant `clue_config.schema.MergePolicy` seam (pre-existing backlog item "[M9.2×M0.4]"); the accessor is the temporary-toggle-era shape, and folding it into the config seam rides that existing backlog item, not this change.

## 4. Non-goals

- No change to pre-spend gating, identity binding, freshness/retention, or the M10 use gate — all remain active in both modes.
- No new mode enum (`CLUE_VERIFICATION_MODE=judge_only` etc.) — the shipped boolean is the contract.
- No per-run pinning of the toggle (deployment-scoped, as shipped; the known restart caveat stands).
- No production composition of the Positioner here — that is Lane E slice E3; this change only guarantees E3 composes cleanly in both states.

## 5. Tests

- Merge: with verification disabled, an unverified tier-4 claim wins `current_value`; a REJECTED claim and a WEAK-bound contact claim still never win; with verification enabled, the existing exclusion tests stay green unchanged.
- Positioner/prose: `judge=None` ⇒ claim + `claim_support` written, no judge call, skip metric emitted; `judge` present ⇒ verdict-driven behavior unchanged.
- Handoff: disabled mode assembles narratives carrying `verification_status ≠ VERIFIED`; enabled mode is VERIFIED-only as today.
- Composition: both API roots construct in both toggle states (no `TypeError`/`AttributeError` path).

## 6. Scope

Small — `merge.py` (+ accessor), `positioner.py`, `handoff.py`, the composition roots touched by `784fb662`, Lane-E `prose.py` when it is born, and tests. On the order of one focused day; small precisely because M12 is not yet composed in production.

## 7. Ownership & landing (demarcation ruling)

**This change is NOT Lane E's to implement.** `FI-lane-demarcation.md` §2.5 forbids Lane E from editing `current_values`/merge and the positioner's internals — exactly the files §3 touches. Therefore:

- The A+B change is implemented **from the primary integration worktree** (where `784fb662` landed), as its own small commit series on `platform/frontend-integration`, independent of Lane E's worktree.
- **Lane E consumes the contract only:** its new `prose.py` (E1/E2) is *born* honoring the optional-judge rule (§3-A), and its E1/E2/E3 acceptance runs validate with `CLUE_VERIFICATION_ENABLED` in **both** states (the demarcation §2.5 awareness note, now concrete).
- Landing order: **E0 needs none of this** (no LLM, no judge). Land the A+B change before or alongside **E1**; E3 (Positioner composition) requires it in place.
