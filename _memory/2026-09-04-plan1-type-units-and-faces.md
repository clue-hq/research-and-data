# 2026-09-04 — Plan 1 shipped: ingestion type units + instanced font faces + honest Bold/Italic

Plan: `docs/superpowers/plans/2026-09-04-ingestion-type-units-and-faces.md` (roadmap Plan 1, items A+B).
Commits `9ee9f571d..3f6c3085d` (+ the Task 5 fix commit); SDD with Opus implementers, every diff
reviewed and every test re-run first-hand by the controller. Restart the design API + fleet worker
after pulling: the Python side changed (parser, normalizer, evidence builder).

## What changed
- `capture/parse.py`: `_line_height(value, font_size_px)` / `_letter_spacing(value, font_size_px)`
  are ratios of the ELEMENT size (px ÷ element, rem×16 ÷ element, %/em/unitless as-is; a length with
  no element size → None, never px/16). Both declared-CSS and rendered-sample call sites pass the
  size. Letter-spacing was folded in: the stored Apollo h1 had ls -0.045 (= -0.72px/16; true -0.01).
- `normalizer/typography.py`: `LINE_HEIGHT_RATIO_RANGE=(0.5,2.5)`, `LETTER_SPACING_EM_LIMIT=0.5`,
  `type_unit_diagnostic` → LUMI0233; an out-of-band anchor value keeps the role's derived default.
- `capture/font_instances.py` (new): `plan_font_instances(family, bytes, *, italic)` decodes
  WOFF/WOFF2, and for a `wght` axis instances 400/500/600/700 with the Google-library instancer
  (`font_library._instance_bytes`: OS/2 weight + name table + RIBBI bits rewritten). Pure.
- `capture/evidence_builder.py`: a variable face becomes the four static instances as kit faces
  (each its own `asset_ing_<sha16>` TTF asset, provenance note "static instance wght=…"); the
  declared-weight instance keeps the variable url so `source.url` survives; the variable file stays
  rehosted. LUMI0234 (info) per instanced family, LUMI0235 (warning) keeps the single face on failure.
  Italic `@font-face` blocks already passed through parse→evidence; pinned by test, no new harvest code.
- `scripts/rederive_kit_type_units.py` (new, dry-run default): re-derives ONLY `line_height` /
  `letter_spacing` of `tokens.typography.type.*` from the job's stored `evidence_json` (rendered
  samples re-based ×16/size; declared px line-heights outside the band re-based), publishes the
  NEXT kit version via `publish_next_brand_kit_version`, `--repin-documents` moves
  `effective_brand_kit_version` (old→new). Reads `CLUE_DATABASE_URL`; `--workspace`, `--kit`, `--apply`.
- Editor: `loadCanvasKit.boldChangesFace(family)` (700 selects a different registered face than
  400; Inter fallback like `hasItalicFace`); `sceneTextMarkState` gains `family`/`faces` and returns
  `reason`; toolbar Bold/Italic render disabled with the reason as `title`; ⌘B/⌘I no-op the same way.
  Copy (exact): `No bold face for “<family>” in the brand kit` / `No italic face for …`.
  `SceneTextEditModel.family` = the node's declared family.

## Live proof (colombo, Apollo `doc_cf05190c…`, 03:24–03:45 IST)
- Re-ingested apollo.io into `brand_kit_ing_10c2b0ea…` → v3 (and a duplicate v4, my retry after
  misreading the nested `job` response; identical content). v3/v4: headline lh 1.0 / ls -0.01 /
  weight 600 (rendered 550 → nearest custodied, LUMI0232 as designed), 4 faces per family,
  LUMI0234 ×2. v3/v4 are `approval_status=draft` (v2 was approved) — founder's call.
- The EDITOR reads the kit version from `scene.meta.brand_kit`, NOT `design_document.effective_*`:
  repinning the row did nothing visible; `POST /documents/{id}/brand-kit {version:4}` (attach route,
  snapshotted) moved the scene (doc v203) and the editor then fetched all 8 instance assets from v4.
  Side effect: v4's palette differs slightly from v2 (page bg #F8FF2C→#ECF414, CTA black→dark purple).
- Caret on the headline: Bold enabled (`Bold (⌘B)`), Italic disabled with the ratified sentence.
  Bold over 0–32 → span `font_weight 700` (doc v204), canvas visibly heavier.
- Export SVG failed on LUMV0903 from the stray "x" node (lh 4.5 in a 71px box — item A's symptom in
  old content); one `update_node` op (lh 1.0, ls -0.01; doc v205) cleared it. The SVG embeds
  seasonMix 400 AND 700 as TTF; headline `<tspan font-weight="700">`. Evidence in `/tmp/plan1-evidence-keep/`.
- Backfill dry-run on colombo hit a job row whose `evidence_json` is a stub `{"schema_version":1}`
  → Task 5 fix round 1 landed (`43495e521`: `UnusableEvidence` → SKIP per kit, read-phase failures
  roll back the aborted transaction). Colombo dry-run after the fix: 51 examined, 12 needing change
  (all in pilot/logosweep workspaces; the Apollo kit v4 is already element-relative), 29 without
  evidence, 0 failed. Nothing applied — owner action per environment.

## Open for the founder
- Approve kit v4 (or v3) and decide whether v2's approved status should carry.
- Run `scripts/rederive_kit_type_units.py --apply --repin-documents` per environment once the fix
  round lands (dry-run first); note the repin only moves `effective_brand_kit_version` — a document's
  SCENE binding needs the attach route.
- The `_` in `LIKE 'brand_kit_ing_%'` is a wildcard (harmless: only widens the dry-run list).
- Test-DB hygiene ruling still open; this session used a throwaway `clue_plan1_test` DB.
