# 2026-08-20 — design-brief plan, slice 2: measured brand geometry (tier 3)

Plan: `docs/superpowers/plans/2026-08-20-brand-design-brief-and-craft-skill.md` §5 slice 2
(D3 ruling: exhaustive). Brief: `.superpowers/sdd/2026-08-20-brand-design-brief/slice2-brief.md`.
Branch `integration/frontend-design-part-iv-v2`. Commit `bef817cd` (code+tests+fixtures).

## What landed

The rendered website capture now MEASURES the brand's geometry instead of letting the
normalizer fabricate a scale.

- `subsystems/clue-design/apps/api/lumen_ingestion/capture/geometry.py` (new) — `GEOMETRY_JS`,
  the browser probe (one `page.evaluate`), plus `parse_geometry(raw, page_url=…)` which turns
  the raw harvest into `NumberSample` / `ShadowSample` evidence + structured shape records.
  Harvests: per-surface radii (per corner, `%` resolved, pill detected), border widths+style,
  box-shadows, paddings, flex/grid gaps, bg/text color and font, for buttons / inputs / chips /
  cards / nav / dividers / images; section background sequence in DOM order; content-band gaps;
  the vertical rhythm (paddings+margins) inside each band; focus rings (programmatic focus).
- `capture/rendered.py` — runs the probe AFTER the screenshot (the focus pass must not change
  the captured pixels); a throwing probe → LUMI0509 warning, never a failed capture.
- `capture/snapshot.py` — `SiteSnapshot.geometry: dict | None` (optional, older fixtures load).
- `evidence.py` — `SurfaceShape`, `SectionBackground`, `GeometryEvidence`;
  `BrandEvidence.geometry` (additive, schema_version stays 1). This rides the job row, so
  slice 3's brief agent reads it from the SAME job — no new store.
- `capture/evidence_builder.py` — attaches `numbers` / `shadows` / `geometry` from the harvest.
- `normalizer/geometry.py` (new) — clustering in `cluster.py`'s idiom (accumulate within
  tolerance, order by weight desc) + `assign_steps` (monotone ladder seating) +
  `build_shadows`. `MEASURED_CONFIDENCE = 0.8`.
- `normalizer/scales.py` — the base scales are now the FALLBACK; measured clusters claim what
  they can. Returns `(values, provenance)`; `build_strokes` takes evidence now.
- `normalizer/emit.py` — `add_numbers(..., measured=…)` per-token provenance; `add_shadows`;
  `build()` emits `self.shadows` instead of a hardcoded `{}`.

## Decisions worth remembering

- **Confidence 0.8** — above derived (0.6) because the number was read off the brand's own
  rendered page; below the 0.9 reserved for a directly observed atomic value (a hex, a font
  family) because a scale step is a *cluster representative*, one inference step removed.
- **Provenance format** `website:<page url> :: <what was measured>` — this is not a new idiom;
  the hand-authored evidence fixtures already used exactly that pointer shape.
- **Monotone ladder seating.** Clusters compete for seats by weight, then are SEATED in
  ascending order against the ascending step defaults, so a measured ladder can never invert
  (`space.10 = 96` above `space.12 = 32` was the failure mode). Steps sharing a default
  (`stroke.width.thin` / `.default` are both 1px) are claimed together.
- **Component padding is excluded from the layout ladder** (`scales._LAYOUT_HINTS = ("section",
  "gap")`). A button's 13.5px inner inset is a true measurement but it is the shape of a
  component, not a rung of the page's scale. First live run without this rule produced
  `space.md = 9px`, `space.lg = 13.5px`; with it, Stripe yields 4/8/12/16/28/32/36/48.
- **Cluster representative = the MOST-OBSERVED exact value**, not the largest or the mean.
  (First cut used `max(weight, value)` and gave `radius.sm = 5` for a brand that draws 4px on
  43 surfaces and 5px on two.)
- **`shadows` stays `{}` only when the site truly has none** — a flat brand IS the finding.
- **Overall kit confidence is unchanged**: number scales still stay out of
  `confidence_samples`, exactly as before, so `provenance.confidence` remains the color/type
  figure it has always been.
- The old `radius.xl` heuristic (`median >= 20 → min(median, 32)`) is gone — the measured
  ladder supersedes it.

## Verification

- New suite `apps/api/tests/test_ingestion_geometry.py` — 18 tests. Includes the
  byte-stability gate: for all three evidence fixtures, everything OUTSIDE the four measured
  token groups (plus the whole ingestion report) must equal the committed golden. It was
  written and run GREEN against the UNregenerated goldens before they were regenerated — that
  is the honest proof colors/type/assets are untouched.
- Golden kits regenerated (`UPDATE_INGESTION_SNAPSHOTS=1`): the diff is provenance/confidence
  only + the new `shadow.sm` on the website fixture. **No numeric token value changed.**
  (The PDF fixture's `space.section` now reads `pdf:page 8 :: grid` at 0.8 — correct: it was
  always evidence, only mislabelled derived.)
- Ingestion suites green: normalizer / capture / geometry / pdf / uploads / describe /
  font_metrics / jobs / routes / ui_api.
- Fixture `apps/api/tests/fixtures/ingestion/geometry/stripe_home.json` is a REAL harvest of
  stripe.com at the capture's own 1440 viewport (2026-08-20); `flat_brand.json` is the
  hand-authored honest-empty case.

## Live proof (2026-08-20)

Design API 8010 was up but had been started at 20:20 WITHOUT `--reload`, so its process held
the pre-slice-2 `lumen_ingestion` in memory; a re-extract through it would have proven nothing
and restarting servers is forbidden. Instead the SHIPPED path (`capture_website(force_render=
True)` → `build_evidence` → `normalize_evidence`) was run out-of-process against the live
https://stripe.com. No draft kit was created and no kit was approved.

    harvest: 234 number samples, 2 shadow samples, 29 shape records, 8 background bands
    band sequence: #FFFFFF ×3, #0D1738, #FFFFFF, #0D1738, #FFFFFF, #F8FAFD
    BEFORE (measurement suppressed): 115 tokens | website: 17 | derived: 96
    AFTER  (measured geometry):      118 tokens | website: 45 | derived: 71

    radius.button 4  radius.card 6  radius.badge 4  stroke.width.focus 3  stroke.width.card 1
    space.section 96  ladder 4/8/12/16/28/32/36/48
    shadow.sm  0 4 8 0 #0000001A
    shadow.md/brand  0 15.93 31.86 -8 #32325D1F   (Stripe's own rgba(50,50,93,.12))

## Open concerns (carried into slice 3/4)

1. `space.page.margin` reads the section's own horizontal padding (16px on Stripe). The
   *visual* gutter comes from an inner max-width container, so this is honest but thin.
   Measuring the content container's inset would be the improvement.
2. `space.card.padding` took 7px on Stripe — the frequency vote is won by small nav/menu tiles
   that match the `card` selector family. The shape records carry the per-variant paddings, so
   slice 3's recipes are not limited by this.
3. `radius.lg` / `radius.xl` stayed derived on Stripe (the home page only exposes 4/5/6). That
   is the honest fallback working, but a kit can mix measured and derived rungs — consumers
   should read provenance, not assume the whole group is measured.
4. The probe visits ONE page. D3 says "home + up to 3 same-origin pages the capture already
   visits" — the capture visits only the home page today, so no extra pages were added; a
   multi-page capture is a capture-layer change, not a geometry-layer one.
5. `tokens.shadows` has no consumer yet (nothing in `crates/` or the brand card reads it). It
   is evidence for slice 3's recipes and for future consumption; `ShadowToken` has no `role`
   field, so none is emitted.

## Trap recorded (cost ~20 minutes)

**Never `git stash` in this repo.** All ~20 conductor/codex workspaces are worktrees sharing
ONE `.git`, so `refs/stash` is global: a `git stash push` here raced another workspace's stash
operation and the subsequent `git stash pop` popped a DIFFERENT session's WIP into this tree
while this slice's work vanished from the stash list. Recovered by locating the dangling stash
commit (`git fsck --unreachable` → grep for a known new file) and `git stash apply <sha>`; the
other session's stash was restored with `git stash store <sha>`. To compare against a baseline,
use `git worktree add --detach /tmp/<name> <rev>` instead.

## Known pre-existing flake (NOT caused by this slice)

`test_ingestion_routes.py::{test_ingest_website_happy_path_persists_kit_and_report,
test_reingest_existing_website_kit_publishes_a_new_draft_version,
test_ingested_kit_attaches_to_document, test_stage_progression_reaches_preparing_before_success}`
fail when `test_ingestion_pdf.py` runs immediately before them: the job is claimed by a
leftover embedded fleet worker from an earlier test's app, which runs the REAL capture instead
of the monkeypatched stub (`CaptureError: blocked url — dns resolution failed:
https://www.insighthealth.example`). **Reproduced identically on HEAD~1 in a clean worktree**,
so it predates this slice. The suites pass file-by-file and in most orderings. Worth a
dedicated fix (per-test worker shutdown, or scoping the queue to the test's workspace).
