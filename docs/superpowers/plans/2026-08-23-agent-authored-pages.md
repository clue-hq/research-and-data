# Agent-Authored Pages (genad2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer asks for *any* design artifact in chat — "LinkedIn banner", "A4 flyer for print", "18×24 inch poster" — and the **design deepagent itself** authors the page at the right dimensions and unit (px/pt/mm/in) via its DSL; the platform births a **zero-page** document, honestly renders the pageless window, refuses pageless "successes", and the editor stops destroying or misreporting physical pages.

**Architecture:** This lane REVERSES the birth-owns-the-page mechanism from the genad lane (ratified by the founder 2026-08-23, superseding the format-parameter half of genad ruling 2): `open_design_leg@4` births a scene document with **no pages** and **no format parameters**; Head-of-ABM only routes and delegates the user's words; the trio authors `page <id> size(w,h,unit)` and the engine (`page_geometry.rs` via the DSL compile) normalizes any unit — the platform's hand-rolled page geometry (`ad_birth_page`/`AD_FORMAT_PRESETS`/`mint_empty_ad_document`) is **deleted, not generalized**. Three consequences are then owed: zero-page lifecycle states on the visible surfaces, a ≥1-page success gate in the persist path, and the platform editor's unit-fidelity fixes (the px-hardcoded commit that silently converts physical pages to raster, and the pt-box-shown-as-pixels misreport). No Rust/engine changes anywhere in this lane.

**Tech Stack:** Python (platform `clue_api`, design `lumen_api`), TypeScript (platform design-editor adapter + chat-shell), pytest, vitest/frontend suite. Engine, wasm, and helper are consumed as-is.

**Spec:** The founder rulings, ratified in-chat 2026-08-23 (recorded in `_memory/2026-08-23-genad-rulings.md` addendum + this plan):
1. **Zero-page birth; the design deepagent authors every page.** `open_design_leg` (scene kind) creates the durable document + brand binding but NO page and takes NO format/dimension parameters. Head-of-ABM must not resolve presets, translate units, select dimensions, or create artboards — it routes design requests and delegates the user's words verbatim.
2. **No preset registry / catalog.** The design deepagent's own knowledge is the catalog; the engine's DSL (`size(w,h,pt|px|mm|in)`, `preset(a4|us_letter|linkedin_ad|envelope_dl|custom)`) is the only normalization path.
3. **300 DPI** remains the design subsystem's default when rasterizing physical dimensions (no platform involvement).
4. **No-dims requests are resolved inside the design leg**: the agent proposes dimensions and states them (or asks), never Head-of-ABM.
5. Surviving from genad unchanged: one document = one artifact; brand-kit stamping at birth; leg pin/CAS discipline; F1 stays as **legacy support only** (existing empty-page docs) — nothing new depends on it.

**Fact base:** `.context/genad2-readiness-scout.md` (2026-08-23 read-only scout; every file:line below is verified there). Headline: the engine, DSL grammar, print-export machinery, and zoom math are READY; the px-only narrowness is confined to two adapter functions, one inspector section, one export-profile builder, one Python birth helper, one tool input model, and one wire schema.

## Global Constraints

- **Local commits only; never push; no AI attribution in commits** (repo rule).
- **No Rust/engine/helper/wasm changes.** Everything in this lane is aperture code (Python + TS). No wasm rebuild, no handshake step.
- **P3.7 layering rule binds Task 3**: a NON-leg scene turn (no `leg` block) must produce a byte-identical result envelope; the success gate applies to leg turns' persist path only.
- **Presentation-truth rule**: the dummy frontend is the only source of designed UI. Task 5's empty-state *visual* is a flagged founder/design decision (the plan ships a minimal neutral state and marks it). Task 6 adds NO new controls — it fixes truthfulness of the existing W/H display and stops destructive writes; the dropped standalone page-setup controls (unit selector, orientation, bleed/safe-area — scout §5e) are OUT of scope, deferred to a future editor-parity lane with designed UI.
- **Print export intent stays deferred** (`scene-export.ts:76-77` — deliberate, pending approved mockups per contract §1.11). Preview-intent PDF export of a physical page is already correctly sized (MediaBox in true pt — design API `main.py:7392-7400`) and is the v1 answer; flipping print intent (bleed/marks/CMYK — all ported, zero call sites, `exportRunner.ts:186-194`) is a future lane with its own mockups.
- **DB for platform DB-gated tests:** `postgresql+asyncpg://clue:clue@localhost:55040/clue` (NEVER port 5432). Design-subsystem suite: `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest apps/api/tests` from `subsystems/clue-design/` (known pre-existing reds — A/B via stash on doubt).
- Deliberately OUT of scope: multi-page (staged later per founder — but nothing here may foreclose it; the success gate reads "≥1 page", never "exactly 1"), the 17 dropped page-setup controls, print-intent export UI, preset-vocabulary sync of the inspector's display labels, `medium` selection (birth keeps `medium="ad"`; the DSL parses scene-level medium — `dsl.rs:2921-2926` — so agent-side adjustment is possible later; recorded residual).

## File Structure (whole-plan map)

```
platform/api/clue_api/design_leg_tools.py                MODIFY  Task 1 (@4: zero-page birth, format params deleted)
platform/api/clue_api/design_tools.py                    MODIFY  Task 1 (retire minter/presets/birth-page)
tests/api/test_genad_leg_document_birth_db.py            MODIFY  Task 1 (rewrite for zero-page contract)
tests/api/test_design_tools_ad_mint.py                   DELETE  Task 1 (its subject retires)
platform/agents/catalog/profiles/head-of-abm/v39/        CREATE  Task 2
platform/agents/catalog/prompts/head-of-abm/v7/          CREATE  Task 2
platform/api/clue_api/agent_registry_wiring.py (+wave)   MODIFY  Task 2 (v38→v39, recipe v19 — full ef4884d0-template wave)
subsystems/clue-design/apps/api/lumen_api/main.py        MODIFY  Task 3 (≥1-page success gate in the leg persist path)
subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py  MODIFY  Task 3 (+ gate tests)
subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py  MODIFY  Task 4 (author prompt: physical-unit examples)
apps/frontend/src/features/design-editor/…               MODIFY  Task 5 (zero-page states), Task 6 (unit fidelity)
apps/frontend/src/features/chat-shell/…                  MODIFY  Task 5/6 (inspector display touchpoints)
docs + _memory                                            Task 7 (walk, supersessions, close-out)
```

---

### Task 1: `open_design_leg@4` — zero-page scene birth; the format aperture is deleted

**Files:**
- Modify: `platform/api/clue_api/design_leg_tools.py` (input model `:244-248`; `_ResolvedDelegation.birth_format` `:307-310`; `_resolve_ad_format` `:397-433` and `_refuse_ad_format_on_web` `:435-445`; `model_description` `:449-473`; `parameter_policy` `:492`; `_default_scene_document_minter`/`_birth_scene_document` `:352-378, :711-761`; module docstring supersession)
- Modify: `platform/api/clue_api/design_tools.py` (DELETE `AD_FORMAT_PRESETS` `:110-115`, `ad_birth_page` `:118-142`, `mint_empty_ad_document` `:145-179`; shrink `__all__`)
- Modify: `tests/api/test_genad_leg_document_birth_db.py` (rewrite to the zero-page contract)
- Delete: `tests/api/test_design_tools_ad_mint.py` (its entire subject retires)

**Interfaces:**
- Consumes: `CoreClient.new_scene(document_id, title, artifact_type, medium)` (existing; a pageless scene is its natural output — `Scene::new` creates zero pages), `create_document(conn, workspace_id=…, scene=…, doc_kind="scene")` with the Task-1(genad) brand stamper (works on a pageless scene — it reads/writes only `meta`).
- Produces: version `"4"`; a document-less `doc_kind="scene"` open births `{schema_version, meta:{id,title,brand_kit?,status:draft, artifact_type:"ad"→None?, medium:"ad"}, pages:{}, nodes:{}, …}` — **zero pages** — pinned at `document_version_guard=0`. The scene turn envelope keeps carrying `document_base_version` (Task-5(genad) seam, unchanged). Task 2 references `open_design_leg@4`.

**Contract decisions (binding):**
- Input model: `ad_format`, `ad_width`, `ad_height` are **removed** (ToolInput rejects unknown fields — an agent still sending them gets a loud validation refusal, which is correct during the profile transition; Task 2 lands in the same lane).
- The scene minter becomes one engine call: `core.new_scene(document_id, title, None, "ad")` — `artifact_type=None` (no format key exists anymore; the gallery's channel-chip substring match simply finds nothing, the current behavior for preset names anyway — `gallery.ts:35-44`), `medium="ad"` (constraint-listed residual).
- `_birth_scene_document` keeps its transaction shape verbatim (mint on a thread → `create_document` inside the caller's conn → pin read-back off `effective_brand_kit_*`) — only the minter call simplifies.
- `model_description` rewrite: the px-literal sentence (`:462-464`) is replaced with (verbatim):
```
"For a NEW ad or any designed page pass doc_kind='scene' and no document_id: an empty
design document is created (no page yet) and the design agent authors the page itself —
size, unit (px for digital, mm/in for print) and layout come from the user's own words,
so put everything the user said about format, dimensions, medium and purpose in brief.
Do not infer or restate dimensions yourself; Design owns them."
```
- Module docstring: dated supersession note on the @3 format-parameter paragraphs (never rewrite history).

- [ ] **Step 1 (TDD):** Rewrite `tests/api/test_genad_leg_document_birth_db.py` to the new contract — keep the file's arrangement machinery (fixtures, fake-minter injection seam, invoke harness) and replace the ten @3 tests with:
```
1. test_a_document_less_scene_open_births_a_zero_page_document
   doc_kind="scene", NO format fields → document_created True, guard 0, doc_kind="scene",
   scene["pages"] == {}, scene["nodes"] == {}, title from brief/title input.
2. test_the_zero_page_birth_is_twin_proof_under_replay   (same ids, one row, second call created=False)
3. test_an_approved_kit_is_stamped_on_the_pageless_birth_and_the_leg_pins_it_read_back
   (real DAL create; meta.brand_kit stamped on the PAGELESS scene; leg pin == stamp)
4. test_without_an_approved_kit_the_pageless_birth_is_unbranded_no_pin
5. test_format_fields_are_rejected_as_unknown   (ad_format="square" → input validation refusal,
   no leg row, no document row)
6. test_the_zero_page_birth_appears_in_the_gallery_feed_with_no_dimensions
   (kind == "ad"; document_page_pixels honest None → wire dims None — anchors scout §3)
7. test_web_birth_is_byte_unchanged   (doc_kind="web" path identical to @3 — regression pin)
```
Run → FAIL (fields still exist / minter still mints pages).
- [ ] **Step 2:** Implement per the contract decisions. The genweb file's trip-wire attitude applies in reverse: the @3 tests being deleted are the ones this plan's spec supersedes — note that in the test-file docstring with the date and this plan's path.
- [ ] **Step 3:** Delete `AD_FORMAT_PRESETS`/`ad_birth_page`/`mint_empty_ad_document` + `tests/api/test_design_tools_ad_mint.py`. Repo-grep proves zero remaining consumers (`grep -rn "ad_birth_page\|AD_FORMAT_PRESETS\|mint_empty_ad_document" platform/ tests/ apps/` → only historical docs/_memory).
- [ ] **Step 4:** Gates: `CLUE_DATABASE_URL=… .venv/bin/pytest tests/api/test_genad_leg_document_birth_db.py tests/api/test_genweb_leg_document_birth_db.py tests/api/test_p34_design_leg_tool_db.py -q` → green. Note: adjacent p34/p35/p37 + registry tests will red on the @4 pin exactly as in genad Task 3/4 — the known cross-task state; Task 2 heals them (dispatch Task 2 immediately; carry the full pin inventory from the genad ledger pattern: `recipe_contracts.py`, `agent_registry_wiring.py`, `composer_context.py`, `conversation_turns.py`, `recipe_wiring.py`, + test pins incl. `test_agent_registry_wiring.py`, `test_c8_trial_surface.py`, `test_catalog.py`, `test_recipe_contracts.py`, `test_client_knowledge_privacy_s4e.py`).
- [ ] **Step 5:** Commit: `feat(platform): open_design_leg@4 — zero-page scene birth; the design agent authors every page (genad2 ruling 1); format parameters and the platform page-minter retire`.

### Task 2: Head-of-ABM v39 + prompt v7 + recipe v19 wave

**Files:** profile `v39/` (copy of v38 + @4 flip), prompt `v7/` (copy of v6 with the ad-format paragraph REPLACED), `agent_registry_wiring.py` `"v38"→"v39"`, `recipe0-stage0-v19.json` + `CONVERSATION_RECIPE_VERSION` 18→19 + the full pin wave per the `ef4884d0` template (the genad Task-4 commit `45102e4d` is the immediate precedent — diff it first).

**Prompt v7's design-delegation paragraph** (replaces v6's format-inference guidance; keep v6's voice):
```
When the user asks for an ad, a banner, a flyer, a poster, or any designed page, open the
design leg with doc_kind='scene'. Do not choose or restate dimensions, formats, units or
page sizes — Design owns all of that. Put the user's own words about what they want (the
channel, any sizes or units they mentioned, print vs digital, the content) in brief,
verbatim where possible. Tell the user the design session is open; the design agent will
choose and state the page setup itself, and they can correct it in the same conversation.
```

- [ ] Steps: template-diff → v39/v7/v19 wave → all pins flipped (production + tests) → gate: the genad Task-4 gate set (8 files) + `tests/execution` recipe tests knowingly-red-on-shared-DB noted → repo-grep zero live `open_design_leg@3`/v38/v6/v18 refs outside history → commit `feat(platform): head-of-abm v39 — open_design_leg@4 grant + prompt v7 route-and-delegate (genad2)`.

### Task 3: The ≥1-page success gate (design-side persist path)

**Files:** `subsystems/clue-design/apps/api/lumen_api/main.py` (the leg persist path — `_persist_leg_scene_proposal` and/or its gate site in `execute_agent_turn_job`); `apps/api/tests/test_scene_turn_persist.py`.

**Contract:** a LEG scene turn whose applied result would leave the document with **zero pages** is refused honestly — no write, typed failure (`code: "agent_turn.pageless_result"`, summary naming the fact: "Design finished without creating a page — nothing was saved; send another message to try again."). Gate reads the **applied scene** (post-replay), `len(applied["scene"].get("pages") or {}) >= 1`. It must also cover the proposed-with-zero-ops-on-a-pageless-doc shape (today's empty-ops proposals pass through as success — on a pageless document that would tell the user their design is ready when nothing exists; the gate turns that into the same honest failure **only when the document has no pages**; empty-ops iteration turns on content-bearing docs stay success, byte-identical). Non-leg turns: byte-identical (P3.7).

- [ ] **Step 1 (TDD):** tests in `test_scene_turn_persist.py` (existing harness):
```
a. pageless doc + stub proposal whose ops create a page → persists, success (the happy zero-page path).
b. pageless doc + stub proposal with ops that create NO page (e.g. meta-only) → typed
   agent_turn.pageless_result failure, zero envelopes, doc untouched.
c. pageless doc + "proposed" with empty ops → same honest failure (no fake success).
d. content-bearing doc + empty ops → unchanged pass-through success (regression pin).
e. non-leg turn on a pageless doc → byte-identical result envelope (dict equality).
```
- [ ] **Step 2:** Implement; run persist file + full design api suite (A/B for pre-existing reds). Commit: `feat(design): leg scene turns refuse a pageless result honestly — the zero-page birth's success gate (genad2)`.

### Task 4: Trio author-prompt touch-up — physical units become first-class in the always-on prompt

**Files:** `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py` (`:319-322`); the prompt tests under `apps/agent_runtime/tests/` that pin the author prompt (locate by grep before editing).

**Change (minimal, per scout §6b "one prompt line closes most of gap 6b"):** extend the existing custom-page-dimensions passage so it reads (keeping the surrounding sentences intact):
- digital surfaces: `page page_id size(width,height,px)`;
- physical/print surfaces: `page page_id size(210,297,mm)` or `size(8.5,11,in)` (or `preset(a4,portrait)` / `preset(us_letter,portrait)`);
- **always give an explicit `size(...)` or `preset(...)`** — a bare `page <id>` silently defaults to A4 portrait (`dsl.rs:1714-1718`), which is almost never the intent for a digital ask;
- when the user names no dimensions, choose canonical ones for the medium and STATE them in the report.

- [ ] Steps: locate prompt-pinning tests → red on the changed lines → edit → green → run `pytest apps/agent_runtime/tests` (full) → commit `feat(design-agent): author prompt teaches physical page units first-class (genad2 ruling: the agent owns page setup)`.

### Task 5: Zero-page lifecycle states (frontend)

**Files (verify each against the checkout; the T6-genad scout mapped the chain):**
- `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (+ module css) — zero-page render state
- `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (ad branch) — the stage's pageless presentation
- `apps/frontend/src/features/design-editor/adapter/scene-hydrate.ts` — canvas-schema hydration on `pages == {}` (inspector shows a non-editable placeholder, not fabricated px defaults — note scout §1b: the un-hydrated panel currently fabricates "1200×1200"; the pageless state must NOT show that)
- Tests: the adapter/component test files adjacent to each (follow the AD-lane harnesses)

**Contract:** with zero pages, (a) the stage shows a deliberate neutral state — copy: **"Design hasn't created the page yet — it will appear when generation completes. Send a message to start (or retry)."** — no canvas, no crash, no console errors; (b) the inspector renders no size/background controls (nothing fabricated); (c) the gallery card renders honest-empty (scout §3 says the backend is already honest — pin it frontend-side); (d) auto-open still opens the tab (the state above is what it shows). **FOUNDER-DESIGN FLAG:** the neutral state's *visual* (typography/illustration/placement) is a design decision — this task ships plain text in the stage's existing empty-frame idiom and records the flag; do not invent styled UI.

- [ ] Steps: TDD the adapter/hydration behavior (zero-page → placeholder schema, no fabricated defaults) → component states → browser proof on a hand-made pageless doc (create via `create_document` with `pages:{}` through a scratch script or the @4 birth itself once Task 1 lands) → commit `feat(ad-editor): zero-page lifecycle states — honest pageless stage, no fabricated inspector defaults (genad2)`.

### Task 6: Editor unit fidelity — stop destroying and misreporting physical pages

**Files:**
- `apps/frontend/src/features/design-editor/adapter/scene-apply.ts` (`:1340-1398` — the size-commit builder; `:1743-1777` — the canvas cases)
- `apps/frontend/src/features/design-editor/adapter/scene-hydrate.ts` (`:1042-1066` — `pagePixelSize`; `:1011-1041` — canvas-state hydration)
- `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`:504-513` — W/H display only; NO new controls)
- Tests: `scene-apply.test.ts` (the pin at `:1501-1515` gets consciously rewritten — it currently PINS the destruction), `scene-hydrate.test.ts`

**Contract (fixes truthfulness only; adds no capability):**
1. **Commit preserves the page's unit** (`scene-apply.ts:1390`): a size commit reads the page's authored unit (`size.source?.unit ?? size.unit`) and normalizes through the existing byte-identical `pageGeometry.ts` in THAT unit — an A4 (mm) page's W/H edit writes mm, keeping `output.physical`; a px page's writes px, keeping `output.raster` (current behavior for px pages byte-identical — pin it). The `preset` field: preserve the stored `page.size.preset` instead of stamping `"custom"` when only W/H changed… **only if** the numbers still match the preset; otherwise `custom` (matching engine semantics; keep this branch small).
2. **Display tells the truth** (`scene-hydrate.ts:1057-1066`): `pagePixelSize` grows a unit-aware sibling (`pageDisplaySize → {width, height, unit}`) preferring `output.physical` (210×297 mm) then `source` (any unit) then raster then the canonical box labeled `pt`; the inspector's W/H row displays the unit as inert text beside the existing inputs (presentation-minimal; the existing labels idiom). The px-only `pagePixelSize` remains for the render-path consumers that genuinely need px.
3. **Physical pages: W/H inputs commit in the DISPLAYED unit** (typing 300 into H on an A4 means 300 mm — consistent with what the field shows; this is what makes 1+2 coherent).
- [ ] Steps: TDD red on the rewritten destruction-pin (an mm page's H commit preserves `output.physical` + unit mm), the display test (A4 → 210/297/mm), px-regression pins (byte-identical ops for px pages) → implement → frontend gates (`npm run design-system:build && npm run lint && npm run build` + suite) → browser proof (needs a physical-unit doc: author one via the design API's `POST /documents` with an A4 scene, or via a Task-7-walk A4 birth) → commit `fix(ad-editor): physical pages survive the inspector — unit-preserving size commits, truthful unit display (genad2; closes the px-hardcode data-loss bug)`.

### Task 7: Acceptance walk, supersessions, close-out

- [ ] **The walk** (live stack, Fable-driven, all services on the colombo `.env`; worker restarted on this lane's code):
```
1. "Make me a LinkedIn banner for Insight Health" → zero-page birth (card appears, honest
   pageless state) → generation → agent AUTHORED the page (expect ~1584×396 px — judge:
   did it state its choice?; any reasonable banner px size passes; the point is
   agent-owned setup, not a magic number) → persists → editor renders.
2. "Make an A4 flyer for the clinic open house — we'll print it" → agent authors
   size(210,297,mm) or preset(a4) → verify the STORED page: output.physical present,
   canonical pt box → editor shows 210×297 mm truthfully → nudge H in the inspector →
   output.physical PRESERVED (the Task-6 proof) → PDF export (preview intent) → MediaBox
   ≈ 595×842 pt.
3. "18 by 24 inches poster, portrait" → size(18,24,in) authored; stored physical intact.
4. No-dims ask ("make me something beautiful for our launch") → the agent proposes-and-
   states dimensions in its report (transcript evidence) — ruling 4 proven.
5. Failed-generation window: observe the pageless state live (between send and finish, or
   after an induced failure) — Task 5 proven in anger.
6. Legacy: the two existing empty-page ads (doc_da2edcb8/doc_6a13f8fe) still generate via
   F1 unchanged.
```
- [ ] Root `make check` (five documented reds, zero new) + design suite + frontend suite.
- [ ] Supersessions: `@3` docs/plan notes get dated supersession annotations (genad plan §Task 3, the close-out memory, the seed script if it references presets); `_memory/2026-08-23-genad-rulings.md` addendum recording THIS ruling set; new `_memory/` close-out for the lane (founder items carried: medium="ad" residual, print-intent export pending mockups, the empty-state visual design flag, multi-page staged).
- [ ] **Deferred minors ledgered during execution (Tasks 1–2, review findings parked by the controller — sweep here or consciously carry into the close-out as residuals):**
  - [T1] `design_leg_tools.py:391` imports the module-private `_core_client` across the `design_tools` boundary — a public `mint_empty_scene_document` (three lines) would restore web/scene symmetry.
  - [T1] `_default_scene_document_minter` has zero direct coverage (the explicit `brand_kit_ref`-authoritative stamp is unpinned on the scene path since `test_design_tools_ad_mint.py` retired; matches the web sibling's level) — a `LUMEN_CORE_HELPER`-gated round-trip asserting `pages == {}` / `meta.medium == "ad"` / `artifact_type is None` closes it cheaply.
  - [T1] `test_web_birth_is_byte_unchanged` overstates its name (field/DB assertions + `minter.calls == []`, not bytes); its `engine_web_doc` fixture cross-import couples the genad/genweb test files.
  - [T1] `medium="ad"` hardcode at `design_leg_tools.py:393` is docstring-stated but carries no call-site residual marker.
  - [T2] `apps/frontend/docs/api-contracts/projects.md:1628` still reads "`open_design_leg@3` births a scene" — stale live contract prose (out of the platform-only Task-2 scope; this task's doc sweep owns it).
  - [T2] `v39/profile.yaml:70` "the @3 schema is frozen for replay" is imprecise since Task 1 deleted the @3 input model (only the v38 pin is frozen) — copied precedent phrasing shared by the whole lineage; fixing it is a lineage-wide honesty sweep, decide deliberately.
  - [T2] Prompt-v7 ambiguity (plan-mandated verbatim text): "any designed page" → scene sits after the retained "website / landing page / microsite" → web paragraph; mitigated by reading order and the ad/banner/flyer/poster list, but live in a production prompt — founder-visible residual.
  - [T1/T2, no lane owner] Two pre-existing `tests/api` reds surfaced by the Task-2 sweep and controller-verified NOT this lane's (`test_toolbelt_wiring::test_out_of_order_matrix` — research-directive input model; `test_production_context_s31_fleet_db` — red at `d81c4b6e`), plus seven more pre-existing reds inventoried in the Task-2 report — unowned, surface to founder in the close-out.
  - [T3] `main.py:8337-8341` — the LUMV0100→pageless-refusal branch drops `error.message` from the diagnostic detail (its replay-failure sibling passes the engine's text through); one-line fix.
  - [T3] Untested edge: a leg turn whose ops DELETE the last page of a content-bearing doc now gets the pageless refusal (inside contract, more honest than the old "could not be replayed", but the prose misdescribes a deletion and no test pins it) — add the pin.
  - [T3] `is_pageless_scene_refusal`'s `isinstance` guard is unreachable (`CoreError.diagnostics` is always a list); two persist-test dict-equality pins share the `operations` list by reference with the expected envelope (deepcopy one side).
  - [T3, informational] The empty-ops refusal arm is defensive today — the production trio cannot emit `proposed` with empty operations (`agent_response_from_trace` blanks it); and the refusal prose is not delivered to chat (`_fail_turn` short-circuits the summarizer — standing genad founder item on failure routing; the leg does return to `open_awaiting_user`, so retry works).
  - [T4] `prompts.py:319-320` ownership clause ("YOU author every page") is welded onto the units bullet and is the one new sentence no test pins — own bullet + pin, or drop.
  - [T4] The print-preset list reads closed (3 of 5 DSL presets named); prefix "for example," to keep the agent-side catalog open. The "(pt works too)" parenthetical is droppable.
  - [T4 → founder] The engine never refuses a size-less `page <id>` line (silent A4-portrait default, `dsl.rs:1714-1718`); the prompt now warns, but a `lower_page` warning diagnostic would be the mechanical guard — Rust change, outside this lane's fence.
- [ ] Commit: `docs(genad2): close-out — agent-authored pages live end-to-end; birth-owns-the-page superseded (dated)`.

## Self-review (performed at authoring)

- **Spec coverage:** ruling 1 → Tasks 1+2 (zero-page birth, params deleted, route-and-delegate); ruling 2 → Task 1 (registry never built; presets deleted) + Task 4 (the agent's knowledge is the catalog, sharpened); ruling 3 → constraint (design-side DPI untouched); ruling 4 → Task 2 prompt + walk item 4; the three owed consequences → Tasks 5 (states), 3 (gate), 4 (prompt); the editor-fidelity half → Task 6; evidence → Task 7. The founder's 7-item change list maps: item 1→T1, 2→T5, 3→T3, 4→T4, 5→T6, 6 (legacy/F1/mint retirement)→T1+constraints, 7→T7.
- **Type consistency:** `open_design_leg@4` referenced identically in Tasks 1/2/7; `agent_turn.pageless_result` named once (T3); `pageDisplaySize` (T6) is new and single-sited.
- **Placeholder scan:** Task 5/6 name files whose exact line anchors the implementer must verify against the checkout (the scout report carries them; the plan cites the report as fact base). Task 2's wave rides the named `ef4884d0`/`45102e4d` precedent rather than restating 13 files. No TBDs.
- **Foreclosure check (multi-page):** the gate reads ≥1; the birth scene is `pages:{}` (N-ready); nothing new keys on "exactly one page." Clean.
