# Typography ingestion: confirmed failures and implementation plan

Audit branch: `brand-context-fixes/typography`, created from the pushed
`codex/design-agent-v1` checkpoint `b0ccdbb0`. This checkpoint adds an audit and
plan only. No live kit, page, runtime process or generation job changed.

## What was actually wrong

Website ingestion already forces browser-rendered capture in
`apps/api/lumen_ingestion/pipeline.py` (`_ingest`, capture call around line 982).
Simply enabling JavaScript is not the missing fix.

The parser collects stylesheet declarations first, then computed browser styles
(`capture/parse.py`, `parse_site`). Before `efe828f3`, normalization retained the
first sample for each tag. An incomplete CSS rule could therefore beat a later
complete browser measurement. Missing measurements became default sizes and
weights, which were then adjusted to available font faces. The resulting kit
and generated guidance presented that derived scale too authoritatively.

The prior push fixes this selection/provenance defect and makes missing authored
typography mappings visible in final review. It does not repair stored kits or
the remaining capture/representation issues below.

## Saved evidence replay across the four test brands

Read-only database query: examined the fifteen stored jobs with evidence, selected
the six most recent workspace/source captures matching the four test brands, and
ran their saved evidence through both the pre-fix normalizer and the current one.
No fresh scraping, provider call or database write was performed.

| Saved brand capture | Role | Pre-fix selection | Current replay selection |
| --- | --- | --- | --- |
| Conduit Fresh, September 21 | Main heading | 32px / 500 | 56px / 400 |
| Conduit Fresh, September 21 | Section heading | 23px / 500 | 48px / 400 |
| Google Cloud, September 17 | Main heading | 20px | 45px |
| AWS, September 17 | Main heading | 32px / 700 | 40px / 500 |
| Clue, September 17 | Section heading | 40.5px | 60px |

Two older Conduit captures show the same selection failure. All four brands have
changed roles on replay. This establishes a shared failure, not a Conduit-only
special case. These are historical captured measurements and offline selections,
not a visual certification of every current source site or every imported brand.

Local receipt: `.local-setup/typography-branch-audit-20260929/saved-evidence-replay.json`.

## Remaining failures, reproduced or located in current code

### 1. Hidden samples can still win (reproduced)

`capture/rendered.py:46` takes the first three matching headings without a
visibility filter. `_parse_computed_samples` keeps their typography without
visibility or element identity. Current normalization resolves equal-ranked
samples by source order.

An offline Chromium page with a hidden 96px/700 H1 before a visible 56px/400 H1
produced 96px/700 as the kit headline. At 375px, its visible H1 became 32px/400,
but the same hidden 96px/700 still won. The diagnostic invoked the actual capture
JavaScript, parser and normalizer, with all external browser requests blocked.

Fix visibility at capture, and retain eligibility/identity through normalization.
Do not treat a visible below-fold section as hidden merely because its current
viewport intersection is zero. Distinguish rendered visibility from location.

### 2. A measured role's font family can be overwritten (reproduced)

`normalizer/typography.py:52` elects a global heading family by frequency;
`build_type_styles` around line 288 applies it to every heading role. A controlled
input with a serif H1 and sans H2/H3 changed the H1 to the sans family despite
having an explicit measured serif family.

Keep each measured style together: family/face, size, weight, line height and
tracking. Do not combine one element's dimensions with another element's font.
Derived roles may still use a disclosed fallback; measured roles retain their
own source identity and need a compatible font-asset binding.

### 3. Typography loses responsive and component context (code-confirmed)

`TypeSample` currently holds label, family, weight, size, line height, tracking
and pointer. It has no viewport, visibility, element identity or component role.
Locators such as `rendered :: h2` do not distinguish multiple H2s on a page.
The typography harvest runs at one actual viewport: plain Chromium requests
1440px while the default stealth backend uses its own coherent browser viewport.

A source site can legitimately have several heading families/sizes and responsive
variants. Flattening them into one sample per HTML tag cannot represent that.
The current twelve-role ramp also derives several values; for example, H3 is
captured but has no direct dedicated anchor in `ANCHOR_LABELS`.

### 4. Extra pages do not enrich the global type evidence (code-confirmed)

`capture/evidence_builder.py:106` parses the entry snapshot to build type samples.
Its secondary-page loop harvests asset dependencies, not additional type samples.
Source fragments retain their own styling, but the normalized typography kit is
still based on the entry page. More captured pages alone do not fix this.

### 5. Readiness and actual face use need explicit evidence (code-confirmed risk)

The main harvest waits for network/scroll/hero settling, but does not explicitly
record font readiness or which font actually painted a text run. CSS family names
alone cannot prove that the intended face loaded. The generated-page review has
glyph-font measurement machinery; extend a shared capability where practical
instead of introducing a competing definition of font identity.

This is a remaining risk, not the cause of Conduit's observed medium weight:
the earlier native glyph audit confirmed both its regular and medium faces loaded.

Local reproduction receipt:
`.local-setup/typography-branch-audit-20260929/synthetic-capture-reproduction.json`.

## Implementation sequence and acceptance gates

1. **Preserve capture evidence.** Add backward-compatible metadata for capture
   method, page, stable element/section identity, visibility, actual viewport,
   role and font readiness. Keep complete samples together; sample visible hero,
   section, card, body and CTA text, including below-fold content. Capture bounded
   desktop/tablet/mobile measurements and preserve relevant source CSS/media
   rules rather than inventing breakpoint behavior from three numbers. Verify
   behavior with the default stealth backend as well as Chromium.
2. **Select and normalize without flattening.** Store measured variants across
   relevant captured pages. Preserve per-role families and face bindings; resolve
   duplicate/hidden/menu samples deterministically. Keep measured, derived and
   unavailable fields distinct. Validate static, PDF and old-evidence compatibility
   rather than silently interpreting old samples as full new-format evidence.
   Preserve source component typography when adapting a selected section.
3. **Make the consumer contract consistent.** Brand Context, kit summary, grammar,
   runtime brand card and website skills must agree on measured styles and their
   provenance. A derived ramp is a fallback, not an instruction to resize a
   captured component. Any needed UI/API contract change must be reviewed at its
   normal repository seam before implementation.
4. **Repair existing kits through a versioned dry run.** Use saved evidence and
   snapshots where sufficient; report precise gaps and fetch only missing
   measurements. Compare proposed typography/guidance changes, preserve curated
   overrides and unrelated brand content, and publish an immutable new version
   through the normal publication seam with a base-version check. Do not rewrite
   prior kits or silently repin all documents. Existing literal page CSS needs
   its own explicit revision; a new kit version is not a retroactive page fix.
5. **Qualify before spending on another generation.** Convert the two reproduced
   failures into regression tests; add responsive, duplicate heading, mixed-family,
   late/missing font, variable-face and incomplete-evidence cases. Replay the four
   brands and held-out fixtures. Compare actual fonts, size, weight, leading and
   tracking at each viewport; preserve selected structure and content fit. The
   existing runtime coverage check should flag missing/mismatched roles. Only
   after these gates should a separately approved native page test assess agent
   adherence and visual quality.

This is a shared producer/consumer correction for future customers, with a
controlled repair path for existing customers. No brand-name conditionals,
manually seeded type values or per-project instructions are proposed.

## Existing backfill utility is not safe for this repair as written

`scripts/rederive_kit_type_units.py` repairs a historical pre-September-4 unit
conversion, not this selection defect. It changes only line height/tracking and
rescales all rendered samples as if their stored units were old. Running it on
already-correct recent evidence can apply the conversion twice; it also cannot
repair family/size/weight or all derived guidance. Reuse reviewed versioning
patterns where applicable, but do not run that legacy `--apply` for this issue.

## Branch and scope

The two previously excluded seller-context test edits remain untouched and
unstaged in this checkout. Branch creation does not isolate those physical files.
The current audit adds no runtime implementation and makes no quality-completion
claim. New fixes belong on `brand-context-fixes/typography`; no further merge into
the design branch is implied.
