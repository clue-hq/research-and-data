# 2026-08-27 — clone-fidelity F0 Task 3: source-truth styling (design ingestion)

Branch `integration/frontend-design-part-iv-v2`. Base `446e7ff01` → commits `8a07e4419`
(slice), `4b117abef` (regression pin), `0b3599bed` (fix round 1 — review I1+M1). Full report:
`.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/task-3-report.md`.

## What changed
Design-subsystem ingestion (`subsystems/clue-design/apps/api/lumen_ingestion/`, Python only,
no Rust). The site's own CSS declarations now outrank our clustering heuristics.

1. **Declared custom properties → direct role assignments.** New module
   `capture/declared_roles.py` holds the ONE bounded name→role table. A property name that
   states a role (`--base-color-brand--green`) becomes a `DeclaredRoleEvidence`, and
   `normalizer/roles.assign_light_roles(clusters, declared)` applies it as
   `basis="declared"`, provenance `custom-prop:<name>`, confidence 0.9
   (`normalizer/roles.DECLARED_ROLE_CONFIDENCE`), above the clustered candidate. NAMES
   QUALIFY, never values — but among names that all qualified for the SAME role, the value is
   allowed to rank (see fix round 1). Strong words (background/text/brand/accent families)
   beat weak ones (primary/secondary); two strong families or any variant word
   (hover/muted/border/dark/…) or any numeric token (`--brand-500`) → no role, keep today's
   weight-3.0 evidence path.
2. **Interaction states.** `:hover/:focus(-visible)/:active/:disabled` on an interactive
   SUBJECT selector → `evidence.StateStyle` on **`BrandEvidence.state_styles`** (new field).
   Capped at 200 with a loud `LUMI0517`. No kit tokens minted — F1/F2 and the brief agent are
   the consumers.
3. **Dark-scheme capture.** `@media (prefers-color-scheme: dark)` `:root` custom-prop
   overrides were previously invisible (`_collect_custom_props` walks top-level rules only),
   so real dark palettes came out `synthesized`. Now collected into their own table, emitted
   as `theme="dark"` evidence → `dark_colorway: captured`. Dark-block rules also resolve vars
   against the dark table. Dark states tagged `scheme: "dark"`.
4. **Parser hardening.** Both RUN-REPORT crashes were ALREADY fixed in-package at base (depth
   cap + opaque-alpha fallback) — verified live before editing. Closed the two residual
   fidelity gaps: the var walk now carries a visited set (cycle caught at the closing hop, and
   the diagnostic NAMES the whole chain), and a RESOLVABLE alpha var is resolved instead of
   flattened to opaque. `rgb()`/`hsl()` reading is now paren-balanced (`_function_body`) with
   the slash alpha slot taken verbatim (`_split_color_args`).

New diagnostics: **`LUMI0517`** (state-style budget), **`LUMI0518`** (a declared
`text.primary` that fails AA against the page is refused and the clustered path runs),
**`LUMI0519`** (a declared brand/accent that is a NEUTRAL is refused the same way — fix
round 1). Next free code: **LUMI0520**.

## Fix round 1 (`0b3599bed`) — review findings I1 + M1
**I1, the one worth remembering.** Webflow's Client-First convention names a brand's WHOLE
family off one prefix, neutrals included (`--base-color-brand--black` / `--…--green` /
`--…--white`). All three qualified by name, the tie-break was alphabetical, and BLACK won —
seated at `declared`/0.9, i.e. MORE authority than the clustered path it displaced, which had
always required saturation. Blast radius: the whole brand-derived half of the kit (primary
ramp, `surface.brand.subtle`, `border.brand`, `focus.ring`, and the >30-degree hue test that
picks the derived accent).

Fix is two-part and the split matters:
- **Names QUALIFY; among the qualified, the value may RANK.** `_rank` leads with chroma for
  `surface.brand`/`surface.accent` (rounded 4dp so float noise falls through to the
  deterministic name key). No change to which names TRIGGER a role — a hex still triggers
  nothing.
- **Fitness stays the normalizer's call.** An all-neutral family still has a most-chromatic
  member, so ranking alone would quietly demote rather than refuse; `assign_light_roles`
  refuses a near-neutral declared brand/accent back to clustering with `LUMI0519`.

Threshold is `NEAR_NEUTRAL_C` (0.03), deliberately NOT `_is_saturated`'s 0.07 — the gate is
for declarations that name a neutral as the brand, not a saturation minimum. Many real brands
are muted, and a declaration is exactly the evidence that lets us keep a slate-blue brand that
`_is_saturated` would have discarded in favour of the platform teal.

Note for anyone touching this: the guard covers `surface.accent` too, which the review named
only for brand — same bug, smaller blast radius. Flagged in the report as narrowable.

M1: deleted a U+200B in a test assertion that made it vacuous (the adjacent `all(...)` was
already covering the case). Only remaining zero-width/nbsp chars in `lumen_ingestion/` are
intentional BOM-stripping literals in `describe.py` and `capture/uploads.py`.

## Verification
- 22 tests in `apps/api/tests/test_ingestion_source_truth_styling.py` (19 + 3 from fix round 1), red-first
  (first run failed at collection).
- 22 ingestion/logo suites green: **438 tests, 0 failures, 0 errors, 4 skipped, exit 0** at
  `0b3599bed` (435 before fix round 1 added three). Run against a dedicated throwaway DB
  `postgresql+asyncpg://clue:clue@localhost:55040/clue_f0_task3` (created + `alembic upgrade
  head` for this task; still present, drop freely). Design tests run WITHOUT the platform
  `.env`.
- `ruff --select=F,E9`: 3 findings, all pre-existing at `446e7ff01`, no new ones.
- **Differential vs base**: ran the three snapshot fixtures through
  `build_evidence → normalize_evidence` on a temporary detached worktree at `446e7ff01` and on
  HEAD. Only `basis`/`pointer` moved on 4 rows; **all 96 role-assignment values byte-identical**
  — insighthealth.ai's `--brand`/`--ink` were already winning through clustering, so the slice
  changed the kit's story, not one hex. That is why no golden bundle needed regeneration, and
  it is pinned by `test_the_harvested_fixture_changes_attribution_but_not_a_single_value`.

## Open / carried forward
- `role_assignments` report rows still carry no `confidence` column (confidence lives on the
  kit token's provenance, as it always has). Flagged for Task 4's acceptance grep.
- The editor's `KitIngestionReport.tsx::BasisCell` has no `declared` arm — falls through to a
  generic chip, same as `measured` does today. Needs a design call; not touched (Python-only
  brief, and the editor is a designed surface).
- Sites declaring only ramp steps (`--brand-50…900`) get no declared brand by design; if the
  acceptance walk shows that is common, add a "prefer step 500/600" rule.
- shadcn's `--primary-foreground` maps to `text.primary` by name and is caught by the AA gate,
  not by naming cleverness. A dark-enough inverse foreground would slip through.
- NOT touched (out of scope, still open): the `<picture>` dark-rung ladder ordering residual,
  and Task 2's deferral that inlined data-URI `@font-face` faces are never custodied.
