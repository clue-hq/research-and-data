# 2026-08-29 — Clone assembly left-skew: root cause (cascade layers vs Tailwind preflight)

**Status: FIXED (founder-approved option 1, capture-time flattening) — commit `02c55c8a6`,
2026-08-29.** New module `lumen_api/fragments/cssflatten.py` runs as the final pass inside
`scope_fragment_css` (after scoping, before the markup-breakout gate); 7 new capture-door tests
in `apps/api/tests/test_cssflatten.py` (red-then-green); 508 tests across 15 clone-fidelity
suites pass. Stored rows migrated via `scripts/flatten_stored_fragments.py --apply` (13 rows:
10 stripe clones + 2 campaign shells + 1 repair — the shells carried Tailwind's own 5 layers, so
ABM pages were exposed too; old blobs kept, previous digest in provenance_json.layer_flatten;
the content-immutability trigger is disabled/re-enabled inside the script's own transaction).
E2E proof: assembled recreate renders centered from stored payloads (x=87/1440, max-width
1266px, h1 48px) with the Tailwind runtime active. Full apps/api suite ran in background —
check the session close entry for its result. Dev stack restarted on the new code
(design API :8010, platform :8030, worker, frontend :3030).

## Symptom
Recreated Stripe homepage (10/10 real clones pinned) renders left-skewed in the agent's
editor-mode preview: every `.section-container` at x=0 with margin/padding 0 (should be
centered, max-width 1266 at 1440), hero display type collapsed to 16px, imagery layout off.
Publish/delivery path expected unaffected (unverified). Founder screenshot:
`.deepagent-workspace/run_2bd488be69bb41978a36e5bed892f48b/iter_2/preview_1440.png`.

## Root cause (proven by CDP cascade dump + bisect, /tmp/skew_repro/)
1. Stripe's captured CSS legitimately uses its own cascade layers (`@layer reset/base/app`).
2. Editor-mode render (crates/lumen-web/src/render.rs ~line 305) wraps `theme.base_css` in
   `@layer base { ... }`, and since F1.3 the fragment sheet rides at the END of base_css
   (crates/lumen-web/src/theme.rs ~line 791). So every cloned rule becomes a NESTED
   sub-layer of `base` (`base > base`, `base > reset`, ...).
3. The preview inlines the Tailwind v4 browser runtime (web_substrate._render_page_html),
   whose compiled preflight (`*{margin:0;padding:0}`, `h1{font-size:inherit}`, img rules)
   lands as DIRECT rules in the same `base` layer.
4. CSS cascade: a layer's direct rules form an implicit FINAL sub-layer that beats all its
   nested sub-layers regardless of specificity. Zero-specificity preflight therefore defeats
   every scoped clone rule → margins/paddings flattened, headings collapsed.

Proof: same html minus the tailwind runtime script → container centers (x=71, margin auto)
and h1 returns to 48px. Repro harness: /tmp/skew_repro/repro.py (rebuilds the recreate from
the empty birth doc + 10 fragments via the real helper binary, editor mode).

## Consequences
- The agent's pixel reviewer graded a degraded render all run; part of its "repair" work was
  fighting this phantom. Standalone fragment renders (isolation previews) are unaffected.
- Any fragment whose source CSS uses @layer has carried this risk since F1.3.

## Fix directions (none chosen; founder decides)
- Flatten/strip @layer from cloned CSS at capture (rewrite nested layers into plain rules in
  declared order), so cloned rules are direct members of the wrapper layer; or
- Emit the fragment sheet in its own dedicated layer declared AFTER tailwind's (`@layer
  lumen-fragments` last) so clones outrank preflight; decide whether compiled utilities
  should still outrank clones (slot-driven utilities on wrapper nodes need to).
- Whatever fix: apply to editor preview AND editor app render route (both wrap base layer);
  verify delivery mode separately (unlayered base + no runtime → likely already correct).

## Related same-day context
- Storage-root split incident + fix: CLUE_STORAGE_FS_ROOT now pinned absolute in .env
  (+ .env.example guidance). Lost-blob recovery from /private/tmp/lumen-dev-storage.
- Run run_3c06e19a (clone recreate, grok-4.6) died at the finish line on an OpenRouter
  `server_error` abort after a 7.5-min hang — no retry at that layer, transactional turn
  discarded ~35 min of good work. Resilience gap, unowned.

## Close-out verification (2026-08-29, post-implementation)
Full apps/api one-shot suite run hit one failure (test_ad_assets_onboarding empty-harvest);
proven environmental, not the fix: 16/16 at the fix commit in a clean worktree, 16/16 at the
parent, 16/16 on rerun in the working tree — the single failure coincided with the dev stack's
four processes booting (contention). Final tally: 508 tests / 15 clone-fidelity suites + the
16 ad-assets tests green. Dev stack restarted on the new code and healthy (design :8010 w/
embedded worker + CORS 3030, platform :8030, standalone fleet worker, frontend :3030).
Throwaway DB (clue_test_flatten) and comparison worktrees removed. Next founder step: re-send
the generation prompt in the design chat — stored library is migrated, so the recreate should
render centered end to end in the editor preview.
