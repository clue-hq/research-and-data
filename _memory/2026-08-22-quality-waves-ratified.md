# 2026-08-22 — quality waves 1–4 ratified; geometry-token plan H1–H4+G2 ratified with carve-outs

Session: read-only strategy analysis (four Opus code explorers over the design
subsystem: deepagent anatomy, engine atomicity/granularity, token system, imagery
seam), then founder ratification. **No product code changed** — only the two plan
docs and this record.

## Founder rulings (this session, verbatim intent)

1. **Category A confirmed** — enforceable facts (radius, stroke, spacing, shadows,
   band/surface colors) get the token bridge; Design.md stays a projection of the
   structured `BrandBrief@1` (no separate agent-only tokenization exists or is
   needed). "A token the engine enforces is worth ten paragraphs the author may
   skim" — ratified as the working principle.
2. **`docs/superpowers/plans/2026-08-20-brand-geometry-tokens-in-the-web-grammar.md`
   RATIFIED (H1–H4 + G2)** with two binding carve-outs, recorded in its status
   header: (a) **no new human-facing diagnostics** — H2 phase-2 findings ship at
   Advice severity, agent-facing only (tool results + trace), excluded from every
   editor/brand-context UI surface; (b) **no hard blockers** — H2 phase 3 (strict
   hard lint + per-kit flag) is REMOVED from scope, not deferred.
3. **Waves 1–4 ratified** and written as
   `docs/superpowers/plans/2026-08-22-design-quality-waves.md`:
   - **Wave 1 — perception:** web-lane `view("asset:")`, SVG thumbnails (Rust),
     brand-card dimensions + class-shaped color-role names + Python/Rust token-list
     parity, describe-on top-16-by-area (fixes C9), `search_assets` id/description
     matching.
   - **Wave 2 — stop destroying work:** severity principle written into ingest.rs +
     LUMW0114 → warn-and-drop (ruling R3 pending on exact semantics), full-tree
     `view("doc")`, sub-section edit floor (fragment ingest gains parent context;
     nearest-stable-ancestor resolution), partial `set_node_props`, patch-first
     prompting, logo-in-link container teaching, false scene-doc "earlier lines
     already applied" claims corrected, `import_external_image` phantom hint fixed,
     asset-id counter fix.
   - **Wave 3 — the geometry plan G1–G4** + registered G5 (web retokenizer,
     scene-precedent).
   - **Wave 4 — prove + measure:** text-to-image live proof (plus
     `image_provider.py:458` https-URL fetch), structured imagery decision +
     deterministic finalize census (orphan/logo/band checks; agent-facing only),
     benchmark scoreboard over a fixed brand set with per-run JSON metrics, C15
     fleet version fence + C16/C17 hygiene.

## Open rulings the founder still owes (in the master plan §Open rulings)

- **R1** approve kit v8 (founder UI action; agent already requests v8 asset ids).
- **R2** force-render for website ingestion (blocks W1.4 exit gate; the HIGH
  unowned blocker from the slice-4 walk).
- **R3** LUMW0114 degradation semantics (proposed: drop node + warning; NOT
  nearest-name substitution).
- **R4** describe-at-ingestion default-on cost (top-16 + logos, one batched call).

## Key inspection findings that shaped the plan (grounded, file-anchored in the plans)

- Web engine enforces **color only**; of 28 measured geometry tokens only
  `radius.button` reaches CSS (`theme.rs::control_radius`). Scene has full token
  governance (LUMB0804–0811) + deterministic `retokenize.py`.
- Web lane cannot view assets at all (`view("asset:")` is scene-only); SVGs have no
  thumbnail on either lane; brand card omits pixel dimensions; the real kit had 46
  images with 0 descriptions (describe defaults OFF); `imagery_rules` is
  structurally empty for every website-ingested kit (PDF-only producer).
- Per-node editing already exists (`web_ops`) but `view("doc")` hides interior node
  ids (skills promise otherwise → 50 guessed-id rejections). The section clamp
  lives in exactly 3 places (`_enclosing_section`, `finish_node` LUMW0102,
  root-parented splice batch).
- The `text-brand` defect's real root: the brand card advertises kit roles
  (`text.brand`) one screen above the token list, and `text.brand` is unreachable
  through the `text-` utility namespace by construction; the Python token-name
  mirror also skips neither collision nor unresolvable colors (Rust does).
- The scene "partial application / earlier lines survive" belief traces to the
  Brilliant competitor teardown → phase-D plan requirement → never implemented;
  two live doc surfaces still teach it while `test_seeded_continuation.py` pins the
  opposite.
- Scene's deterministic imagery machinery (`verify_imagery`, rubric, judge) is
  dormant — no live caller. The web census (W4.2) is deliberately its own thin
  check wired into the live loop.
- Orchestrator gets no skills middleware despite "read design-guidance"; 8 of 14
  materialized skills are scene-only incl. the orphaned scene-idiom brand-imagery
  skill. (Skill-hygiene work is folded into Waves 1–2 prompt/skill slices; a
  web-native brand-imagery skill rides G3/W1 adoption work.)

## Process rules binding execution

Opus agents implement, orchestrating session reviews every diff inline; TDD;
design tests without platform `.env`; Rust slices carry the wasm+helper rebuild
ritual + 8010/fleet-worker restarts; never `git stash`; local commits only, never
push; no AI attribution; Wave-2 Rust and G1 not in parallel worktrees (same crate).
