# Responsive Brand Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brand kits record how each kind of text changes size with the window on the seller's site, and every section we build (ours, agent-written, and inspector hand-set sizes) follows it.

**Architecture:** The rendered capture gains a last pass that narrows the same browser window and re-reads the type samples it already took. Ingestion parses each width exactly as it parses desktop, the normalizer derives the twelve roles at each width with the desktop selection kept, and the steps are stored in a new `responsive_type` kit section outside the engine (put back after every validation, like `measured_components`). site-kit's theme writes them as width rules on `--brand-text-*`, `brand.md` describes them, and inspector font sizes become a share of the nearest role's variable. A script re-measures existing kits.

**Tech Stack:** Python 3.12 (Playwright / patchright / scrapling capture, pydantic evidence), TypeScript (site-kit theme and edits), pytest, node:test.

**Spec:** `docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md` (read it; §3.4 is the founder's decision).

## Global Constraints

- Desktop sizes are byte-for-byte what they are today; only narrower widths are measured. Desktop = the capture's own width (`innerWidth`), not a forced 1440.
- Never force a viewport before or during the existing passes; the width pass runs last, after the screenshot, geometry and state passes.
- Nothing tuned to a seller, builder or list of known break points: widths come from the page's media queries plus 1024, 768, 390.
- `responsive_type` lives outside the engine: add it to `KIT_SECTIONS_OUTSIDE_ENGINE`; never add a field to the Rust kit types.
- A kit without `responsive_type` draws exactly as today (`fluid()`), and inspector sizes stay plain px there.
- In a measured kit, a role with no steps is a fixed size at every width; a role missing from the section (skipped by a re-measure) draws as today.
- No extraction, re-measure or repin runs on anyone's kit without the founder's yes and a time estimate.
- Never run `subsystems/clue-design/apps/api/tests` as a folder; named files only, through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh`.
- No new env flag (built features ship on).

## Review Focus

1. A sampled element hidden or removed at a narrower width (a mobile menu, a desktop-only heading): it must not create a step (no size 0, no jump to another element); the role keeps the wider size. Pinned in Tasks 1 and 3.
2. A capture whose own width is at or below the narrowest candidate (a narrow stealth window): no width is measured, and no `responsive_type` section is written (an empty section would claim "measured, never changes"). Pinned in Task 3.
3. Mobile-first sites (`min-width` media queries): the width just below each `min-width` break point is measured. Pinned in Task 1.
4. A kit's later re-validation (logo choice and the other routes that call `carry_kit_sections`) keeps `responsive_type`. Pinned in Task 3.
5. An inspector size on a kit without `responsive_type`, on a word span (`heading~1`), and on a copied section: px, calc, calc respectively, all resolving to exactly N at desktop. Pinned in Task 5.

---

### Task 1: The capture's width pass

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/capture/type_widths.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py` (`_EVALUATE_JS`, `_harvest_page`, `_snapshot_from_harvest`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/snapshot.py` (`SiteSnapshot.type_widths`)
- Create fixtures: `subsystems/clue-design/apps/api/tests/fixtures/capture/type_widths/{steps,mobile_first,slides,still,hidden}.html`
- Test: `subsystems/clue-design/apps/api/tests/test_capture_type_widths.py`

**Interfaces:**
- Produces: `media_query_widths(css_texts: list[str]) -> list[int]` (a `max-width: W` gives W, a `min-width: W` gives W−1; `px`, `em`/`rem` at 16px; ignores anything else); `type_measure_widths(capture_width: int, media_widths: list[int]) -> list[int]` (candidates = media widths ∪ {1024, 768, 390}, kept only if `320 <= w < capture_width`, unique, descending, at most 8 — the fixed three first, then media widths from the widest); `async measure_type_widths(page, sheets: list[dict], diagnostics: list[dict]) -> dict | None` returning `{"capture_width": int, "widths": [{"width": int, "samples": [ {"fontSize": str, "lineHeight": str, "letterSpacing": str} | None, ... ]}]}` with one entry per index of `data["samples"]`; `SiteSnapshot.type_widths: dict | None = None`.
- `_EVALUATE_JS` keeps the sampled elements in order on `window.__lumenTypeSamples` (no DOM change; the captured HTML must not gain attributes).

- [ ] **Step 1: Write the failing tests** — pure functions and a real page in both engines (copy the `_capture` pattern of `test_capture_fidelity.py`: `playwright` and `patchright`, `file://` fixtures, skip when Chromium is missing):
  - `test_media_query_widths_reads_max_and_min_width`: `media_query_widths(["@media (max-width: 991px){h2{font-size:40px}}", "@media screen and (min-width:48em){p{font-size:18px}}", "@media print{}"]) == [991, 767]` (order: descending).
  - `test_measure_widths_stay_below_the_capture_width`: `type_measure_widths(1280, [991, 1440, 300, 479]) == [1024, 768, 390, 991, 479]`; `type_measure_widths(390, [991]) == []`; a list of 12 media widths caps the result at 8 with 1024/768/390 present.
  - `test_a_stepping_page_is_read_at_each_width` (`steps.html`: h2 56px, `max-width:991px` → 40px, `max-width:767px` → 34px; body 18 → 16 at 767): the sample for the h2 reads `"40px"` at 991 and `"34px"` at 767 and 390; desktop `data["samples"]` unchanged.
  - `test_a_mobile_first_page_is_read_below_its_break_point` (`mobile_first.html`: body 16px, `min-width:768px` → 18px): read at 767 gives `"16px"`.
  - `test_a_hidden_or_removed_sample_reads_none` (`hidden.html`: an h2 `display:none` under 767px and a heading a script removes on resize): their entries are `None` at 390.
  - `test_the_captured_html_is_unchanged_by_the_pass`: the serialized HTML before and after `measure_type_widths` is identical.

- [ ] **Step 2: Run them; they fail** — `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_capture_type_widths.py` → import errors.

- [ ] **Step 3: Implement** `type_widths.py` (the two pure functions, `TYPE_READ_JS`, `measure_type_widths`). Stylesheet text: `data["sheets"]` entries with `text`, plus each `href` fetched through `page.request.get` (bounded: 5 s total, 2 MB per sheet; a failure skips that sheet). Resize with `page.set_viewport_size({"width": w, "height": <current innerHeight>})`, wait 400 ms, then read every element in `window.__lumenTypeSamples` (`None` when detached, `display:none`, or zero-sized). Wire it as the last step of `_harvest_page` (after the state pass) into `harvest["type_widths"]`, fail-soft with one warning diagnostic (an unused `LUMI05xx` code — grep before choosing), and pass it into `SiteSnapshot`.

- [ ] **Step 4: Run them; they pass.** Also run `test_ingestion_capture.py`, `test_capture_fidelity.py`, `test_ingestion_stealth_dispatch.py`, `test_capture_html_limits.py` — unchanged.

- [ ] **Step 5: Commit** — "capture: re-read type samples at narrower widths (responsive type, Task 1)".

### Task 2: Type evidence at each width

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/evidence.py` (`TypeSample.sample_index: int | None = None`; `TypeWidth` and `TypeWidths` models; `BrandEvidence.type_widths: TypeWidths | None = None`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py` (`_parse_computed_samples` records `sample_index`; new `parse_type_widths`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py`
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_type_widths.py`

**Interfaces:**
- Consumes: `SiteSnapshot.type_widths` (Task 1).
- Produces: `TypeWidths{capture_width: int, widths: list[TypeWidth]}`, `TypeWidth{width: int, type_samples: list[TypeSample]}`; `parse_type_widths(snapshot: SiteSnapshot) -> list[tuple[int, list[ParsedType]]]` — for each width, the computed samples with `fontSize`/`lineHeight`/`letterSpacing` replaced by that width's reads (samples read as `None` are left out), run through the same `_parse_computed_samples` (type samples only), each keeping its `sample_index`.

- [ ] **Step 1: Failing tests:** `test_each_width_is_parsed_like_desktop` (a snapshot with two samples and two widths → the same labels, families, weights; sizes from the width reads; same `sample_index` values as desktop); `test_a_sample_missing_at_a_width_is_left_out_there`; `test_evidence_without_widths_still_loads` (a stored `BrandEvidence` JSON with no `type_widths` validates; `schema_version` unchanged).
- [ ] **Step 2: Run; they fail.**
- [ ] **Step 3: Implement** the models, `sample_index`, `parse_type_widths`, and `evidence_builder` building `BrandEvidence.type_widths` (None when the snapshot has none or no width was measured).
- [ ] **Step 4: Run; they pass.** Also `test_ingestion_capture.py`, `test_ingestion_typography_authority.py`, `test_typography_measured_roles.py`.
- [ ] **Step 5: Commit** — "ingestion: type evidence at each measured width (responsive type, Task 2)".

### Task 3: The roles at each width, stored as a kit section

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/responsive_type.py`
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/typography.py` (`TypeAnchors.headline_index`, `TypeAnchors.body_index`, set in `resolve_anchors`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/__init__.py` (result field `responsive_type: dict | None = None`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py` (attach after validation, next to `_attach_measured_components`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/brand_kit_sections.py` (`KIT_SECTIONS_OUTSIDE_ENGINE` gains `"responsive_type"`)
- Test: `subsystems/clue-design/apps/api/tests/test_responsive_type.py`

**Interfaces:**
- Consumes: `BrandEvidence.type_widths` (Task 2); `build_type_styles` and the arguments the normalizer already passes it.
- Produces: `responsive_type_section(anchors: TypeAnchors, evidence: BrandEvidence, build: Callable[[TypeAnchors], dict[str, dict]]) -> dict | None`, returning
  `{"version": 1, "measured_from": <capture_width>, "widths": [...], "source": {"url": ..., "measured_at": ...}, "roles": {"type.headline": [{"max_width": 991, "font_size": 40.0}, {"max_width": 767, "font_size": 34.0}], "type.body": [...], ... every one of the twelve roles, [] when it never changes}}`.
  A width's anchors keep the desktop families, weights and chosen elements: sizes come from the width's sample with the same `sample_index` as the desktop headline / body / per-label sample (the desktop sample when that width has none). A step is recorded when `font_size` differs from the next-wider value by ≥ 0.5 (add `line_height` to the step only when it differs by ≥ 0.01). `None` when the evidence has no measured widths.

- [ ] **Step 1: Failing tests:**
  - `test_a_stepping_page_gives_headline_and_body_steps` (evidence from the Task 1 `steps.html` sizes: h2 56/40/34, body 18/18/16 at capture 1440 and widths 991/767): `roles["type.headline"] == [{"max_width": 991, "font_size": 40.0}, {"max_width": 767, "font_size": 34.0}]`, `roles["type.body"] == [{"max_width": 767, "font_size": 16.0}]`; derived roles follow (e.g. `type.title` steps at 0.72 × H).
  - `test_a_page_that_never_changes_gives_empty_steps` (every role `[]`, section present).
  - `test_no_measured_width_gives_no_section`.
  - `test_a_sample_hidden_at_a_width_keeps_the_wider_size` (Review Focus 1).
  - `test_desktop_styles_are_unchanged`: `build_type_styles` output with and without widths is identical.
  - `test_the_section_survives_revalidation`: `carry_kit_sections(stored_with_section, validated_without)` keeps `responsive_type`; and the pipeline's attach puts it on a freshly validated kit (extend the existing `test_measured_components.py` pattern if that is where attach is tested).
- [ ] **Step 2: Run; they fail.**
- [ ] **Step 3: Implement** the anchor indices, `responsive_type_section`, the normalizer result field (computed right after `build_type_styles` with the same arguments), the pipeline attach, and the section name.
- [ ] **Step 4: Run; they pass.** Also `test_ingestion_normalizer.py`, `test_measured_components.py`, `test_typography_measured_roles.py`, `test_ingestion_typography_authority.py`.
- [ ] **Step 5: Commit** — "ingestion: responsive_type kit section from the measured widths (responsive type, Task 3)".

### Task 4: site-kit draws the steps

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/brand-values.ts` (`typeSteps`)
- Modify: `apps/frontend/packages/site-kit/src/theme.ts` (root type variables)
- Modify: `apps/frontend/packages/site-kit/src/catalog.ts` (`brand.md` type part)
- Test: `apps/frontend/packages/site-kit/test/responsive-type.test.ts`

**Interfaces:**
- Consumes: `brand.kit.responsive_type` (Task 3 shape).
- Produces: `typeSteps(brand: BrandData): Map<string, { maxWidth: number; size: number; lineHeight?: number }[]> | null` (keyed by role name as in `TYPE_ROLES`, e.g. `"headline"`, `"body.small"`; null when the kit has no section). A role in the map is measured (plain px plus its steps, fixed when the list is empty); a role not in the map is drawn as today (`fluid()`).

- [ ] **Step 1: Failing tests** (kit fixture = `garner()` plus a `responsive_type` section with headline steps 991→40, 767→34 and body 767→16):
  - `test_a_measured_kit_writes_desktop_sizes_and_width_rules`: theme CSS has `--brand-text-headline:56px` (no `clamp(`) and `@media (max-width:991px){.brand-root{--brand-text-headline:40px}}` and the 767 rule with headline 34px and body 16px.
  - `test_a_measured_role_with_no_steps_is_fixed`: `--brand-text-caption` is plain px.
  - `test_a_role_missing_from_the_section_draws_as_today`: a section without `type.stat` leaves `--brand-text-stat` as `fluid()` output.
  - `test_a_kit_without_the_section_draws_as_today`: theme CSS equals the current output for `garner()` (snapshot the string before the change).
  - `test_brand_md_says_how_type_changes`: `brand.md` contains one line naming headline "56px; 40px at 991px and narrower; 34px at 767px and narrower" (exact wording is the implementer's; one short line, roles with steps only), and for a measured kit with no steps a line saying type sizes do not change with the window.
- [ ] **Step 2: Run; they fail.**
- [ ] **Step 3: Implement** `typeSteps`; in `theme.ts` use plain px for every role in `typeSteps` and push the media rules right after the `.brand-root` rule (one `@media` per width, all roles stepping there together); the `brand.md` line in `catalog.ts`.
- [ ] **Step 4: Run** site-kit `npm test` (all pass); `npm run build -w @clue/site-kit`.
- [ ] **Step 5: Commit** — "site-kit: draw the brand's measured type steps (responsive type, Task 4)".

### Task 5: Inspector font sizes follow the steps

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/edits.ts` (`declarations` font size)
- Test: `apps/frontend/packages/site-kit/test/edits.test.ts` (or the existing edits test file), `tests/site_editor/test_editor_element_styling.py`

**Interfaces:**
- Consumes: `typeSteps` (Task 4), `typographyOf`.
- Produces: `fontSizeCss(brand: BrandData, px: number): string` — `"${px}px"` when the kit has no section; otherwise role = `px >= titleSize ? "headline" : "body"` and `calc(var(--brand-text-<role>) * <px / desktopSize(role), 4 decimals>)`.

- [ ] **Step 1: Failing tests:** `test_a_hand_set_size_follows_the_nearest_role` (measured kit: 48 → `calc(var(--brand-text-headline) * 0.8571)`; 14 → `calc(var(--brand-text-body) * 0.7778)` with body 18; on a `heading~1` key too); `test_without_the_section_a_size_stays_px` (`font-size:48px !important`); browser `test_a_hand_set_size_shrinks_on_a_phone_with_the_brand` (measured kit in `garner_init()`, `set_props` `_edits.heading.fontSize: 48` on the StatsBand, frame viewport 1440 → computed 48px; resize the browser page to 390 wide → computed `48 × 34/56 ≈ 29.14px`, within 0.5px).
- [ ] **Step 2: Run; they fail.**
- [ ] **Step 3: Implement** `fontSizeCss` and use it in `declarations`.
- [ ] **Step 4: Run** site-kit tests, app tests (`npx tsx --test $(ls src/features/site-editor/**/*.test.ts src/features/chat-shell/**/*.test.ts*)`), rebuild site-kit and site-editor, the browser file.
- [ ] **Step 5: Commit** — "site-kit: inspector font sizes follow the brand's type steps (responsive type, Task 5)".

### Task 6: Re-measure an existing kit

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/responsive_type.py` (`remeasured_section`)
- Create: `subsystems/clue-design/scripts/remeasure_kit_type_steps.py`
- Test: `subsystems/clue-design/apps/api/tests/test_responsive_type.py` (more cases)

**Interfaces:**
- Produces: `remeasured_section(kit: dict, evidence: BrandEvidence, build_anchors: Callable[[BrandEvidence], TypeAnchors], build: Callable[[TypeAnchors], dict[str, dict]]) -> tuple[dict | None, list[str]]` — the section from fresh evidence with each step's size = fresh step size ÷ fresh desktop size × the kit's stored desktop size (rounded to 0.5); a role whose fresh desktop size differs from the stored one by more than 15% is left out of `roles` and listed in the returned skipped names; the theme draws a role absent from `roles` as an unmeasured role (`fluid()`, Task 4). The script: `--kit <brand_kit_id>` (required), `--workspace`, `--apply`, `--repin-documents`; dry run by default prints the section and the skipped roles; `--apply` writes a new kit version identical to the latest except `responsive_type`; `--repin-documents` moves documents pinned to the old version (reuse `_repin` from `scripts/rederive_kit_type_units.py`). Capture and evidence through the ingestion's own functions, as `pipeline.py` uses them (`fetch_rendered` → parse → `build_evidence`).

- [ ] **Step 1: Failing tests:** `test_steps_are_scaled_onto_the_stored_desktop` (stored headline 56, fresh 60 with steps 43/36 → stored steps 40.0/33.5); `test_a_role_far_from_the_stored_size_is_skipped_and_named`; `test_the_new_version_differs_only_in_the_section` (dry-run diff helper over two kit dicts).
- [ ] **Step 2: Run; they fail.**
- [ ] **Step 3: Implement** `remeasured_section` and the script (no run against any real kit here).
- [ ] **Step 4: Run; they pass.** `python scripts/remeasure_kit_type_steps.py --help` prints usage.
- [ ] **Step 5: Commit** — "scripts: re-measure an existing kit's type steps (responsive type, Task 6)".

### Task 7: Proof, review, records

- [ ] Gates: site-kit, site-editor and app tests; browser files `test_editor_element_styling.py`, `test_editor_buttons.py`, `test_editor_renders.py`; API named files: the new ones, `test_ingestion_capture.py`, `test_capture_fidelity.py`, `test_ingestion_normalizer.py`, `test_measured_components.py`, `test_typography_measured_roles.py`, `test_ingestion_typography_authority.py`, `test_site_render.py`, `test_site_publish_package.py`; frontend gate (`design-system:build`, `lint`, `build`) with the lane stack down.
- [ ] Ask the founder for the live check: a time estimate per kit for re-measuring Garner (Carmel Clay's kit), Conduit and Clue, with `--repin-documents` for the two microsites. Only after the yes: run, then compare at 390 / 768 / 1440 the computed font size of our section's heading and body with the seller's copied section beside it (Clue: its own website, as it has no microsite). Restore nothing automatically: the founder decides whether the re-measured versions stay.
- [ ] One end-of-plan review (Opus) over the whole diff; fix findings.
- [ ] Update the spec's status, `_memory/`, and the site element inspector design §7.7 if §3.4 changed anything there.
