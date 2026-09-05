# 2026-09-04 — web editor: annotations, human names, clone text edits (implementation log)
Spec: docs/superpowers/specs/2026-09-04-web-editor-annotations-and-clone-text-edits-design.md
Plan: docs/superpowers/plans/2026-09-04-web-editor-annotations-and-clone-text-edits.md

## Slice 1 — names
- Task 1: `displayNameForNode` + layers wired; `fragmentMeta` parsed from GET /documents.
  - New `adapter/node-names.ts` owns the ONE precedence order (R-A5): own `name` →
    by kind (text words capped at 40 / button label / image alt / fragment registry
    role+label / a section wrapping exactly one fragment inherits that fragment's
    name) → capitalised kind. Plus `innerElementLabel` (R-A4, `"h2 · headline"`).
  - `layers.ts`: `labelFor` (which fell back to the raw node id) is DELETED;
    `buildWebLayerRows` takes an optional third `fragmentMeta` arg.
  - Two PRE-EXISTING tests asserted the old id fallback and were updated to state
    the new rule instead: `layers.test.ts` (an unnamed section now reads "Section",
    was "hero") and `web-fragment-kind.test.ts` (an unmeta'd fragment now reads
    "Cloned section", was "frg_hero"). Both were assertions of the behaviour R-A5
    deliberately removes, not incidental breakage.
  - `webDocuments.ts`: `LoadedWebDocument.fragmentMeta` is REQUIRED and defensively
    parsed from the GET's `fragment_meta`; the design API does not send that key yet
    (Task 2), so today every document loads `{}` and clones name themselves
    "Cloned section". Making it required forced `fragmentMeta: {}` into three test
    literals that build a `LoadedWebDocument` by hand (custom-component-form,
    page-address, rich-text-commit) — without it those three files gained new `tsc`
    errors. Frontend typecheck baseline is unchanged at 49 pre-existing errors.
  - Gate: `npm run lint` clean (2 known pre-existing `canvasOperations.ts` warnings),
    `npm test` 2108/2108 pass.

## Slice 1 — names (cont.)
- Task 3: the AGENT's pin tools stamp the same name at pin time, so new documents
  are born human-readable instead of relying on the editor's derivation.
  - New module-level `pin_display_name(resolved)` in
    `apps/agent_runtime/lumen_agent/tools/web_substrate.py` — `"{Role} — {label}"`
    from the resolved registry entry's `section_role` + `label`, degrading to
    role / label / `"Cloned section"`. Word-for-word the frontend's `fragmentName`.
  - `_cloned_section_pin_nodes` gained a keyword-only `name`; when truthy BOTH the
    wrapper section and the fragment leaf carry it. All SIX call sites pass
    `name=pin_display_name(resolved)`: `insert_cloned_section`,
    `recreate_cloned_page`, `assemble_cloned_sections`, the repair swap inside
    `repair_cloned_section`, `assemble_abm_page`, and `_pin_repair_in_place`.
  - The name rides inside the existing `insert_node` payload — no second operation,
    so the commit gate's ledger replay reproduces it for free (asserted in the test).
  - `WebNode.name: Option<String>` already exists in `crates/lumen-web/src/doc.rs`,
    so the engine accepts it with no schema change.
  - Python `.capitalize()` vs the frontend's first-char-only `capitalise` diverge only
    on a non-lowercase role; every writer lowercases `section_role` at write time
    (`agent_cloned_sections.py` `clean_role`, the ingestion role enum is
    nav/hero/proof/testimonial/security/footer/other), so no real row can diverge.
  - Gate: the five pin-touching agent_runtime files (cloned_sections, substrate,
    recreate_and_repair, abm_assembly, campaign_shells) = 279 passed / 2 failed.
    BOTH failures are pre-existing and unrelated — `test_web_cloned_sections.py::
    test_the_author_holds_both_halves_of_the_ladder_and_the_director_only_discovery`
    and `test_web_abm_assembly.py::test_the_walk_is_registered_on_the_author_role`
    both look up the `lumen-web-author` subagent, which `harness_web.py` quarantines
    (`reason=web_solo_2026_09_04`, landed in 7056d600c). Each verified failing at
    HEAD 62a6e3b24 by stashing this task's two files and re-running.

## Slice 1 done — Task 4: the agent reads the same names the human does
- `_web_node_label(node, nodes=None, fragment_meta=None)` in
  `subsystems/clue-design/apps/api/lumen_api/main.py` now mirrors the frontend's
  `displayNameForNode` precedence: own `name` (capped 40) → fragment: the registry's
  `"{Role} — {label}"` (role `.capitalize()`d, degrading to role / label /
  `"Cloned section"`) → a section whose ONLY child is a fragment inherits that
  fragment's name → text/label/alt copy with inline markup stripped → None, and the
  caller then prints the bare kind exactly as before.
- `_describe_web_turn_targets(web_doc, target_node_ids, fragment_meta=None)` threads
  the page's node map and the meta into the label call. Called without `fragment_meta`
  a clone still reads honestly (`fragment "Cloned section"`), so no caller breaks.
- Wiring: `run_web_agent_turn` builds the meta itself with
  `fragment_meta_for_document({"doc_kind": "web", "scene": web_doc},
  HybridRepository(workspace_id=...).list_web_fragments())`. Deviations from the brief,
  both deliberate: (a) the brief said "the route already has `repo` in scope" — it does
  not; this is a module function called from `execute_web_turn_job`, so the workspace-
  scoped repository is constructed here, the same way `DurableAgentClonedSectionRegistry
  ._repository()` already does inside a turn; (b) the read is skipped entirely unless
  `web_doc_all_fragment_ids(web_doc)` is non-empty, so a clone-free turn pays for no
  registry scan (Task 2's route applies the same rule to a scene GET).
- The `if target_node_ids:` prompt append MOVED inside the function's existing try. It
  used to sit outside it, so anything it raised escaped a function whose contract is
  "never raises: any failure folds into a failed envelope". Pure dict-walking rarely
  raises; a registry read can, so the relocation is part of this change rather than
  incidental tidying.
- Gate: `apps/api/tests/{test_web_turn_pages,test_web_turns,test_public_document_fragment_meta}.py`
  33 passed; `test_agent_cloned_sections.py` 70 passed; `test_web_turn_asset_base_url.py`
  + `test_web_fragment_render.py` + fragment_meta 25 passed. Ruff on `main.py`: 395 → 398,
  the delta being exactly three new `Optional[...]` annotations (UP045), which is the
  file's own style.
- Known cosmetic divergence: Python caps a node's own `name` at 40 chars (bounding the
  prompt line); the frontend does not cap it. Only a >40-char stamped name diverges, and
  the pin tools' generated names are far shorter.

## Slice 1 — closed 2026-09-04 (controller review)
Commits e444c6025 (T1) → 62a6e3b24 (T2) → 8951d213c (T3) → e337d1c9b (T4) → 92494fad4 (fix: layer
label ellipsis). Live-verified in a headless browser on the Ramp doc in Edit mode: Layers rows read
"Hero — Repaired ×3 — ABM hero — …", "Proof — …", "Cta — …"; the agent's TURN TARGET line names the
same clone with the same words (checked against the real registry). Gates: frontend lint/2108 tests/
build green; design api + agent_runtime suites (see ledger). Parked for the founder: registry labels
for repairs carry provenance ("Repaired ×3 — ABM hero — …") so the role shows twice in a row name —
strip the prefix in the naming function, or keep the registry's words. Process notes: design-API
tests need `.env` sourced; never `git stash` (one implementer did, no damage).
Gate residuals (all pre-existing, verified at the pre-slice commit): compiler tests needed `npm ci` in
`apps/custom-component-compiler` (node_modules was empty → transient_error; done on this box);
ingestion tests are not hermetic — a real OpenRouter key in `.env` activates the brand-brief agent
and the live model call exceeds the 60s job timeout (pass with the key blanked); three trio tests
fail only under LUMEN_AGENT_WEB_SOLO=1. See the SDD ledger for detail.

## Slice 2 — Task 5 (bridge: hover chip, `annotate`, badges) — landed `d28b94402`
Files: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py` (+ new
`apps/api/tests/test_web_bridge_annotations.py`), the `/web/render` bridge branch in
`main.py`, and one attribute in `crates/lumen-web/src/render.rs`.

- **Python.** New `_bridge_node_names(web_doc, page_id, fragment_meta=None)` — the display
  name of EVERY node on the rendered page, via the shared `main._web_node_label` (imported
  lazily inside the function; a module-level import is a cycle). A node with nothing cheap
  to say falls back to its capitalised kind, so the chip says "Container" rather than the
  script's own fallback "div". Unknown `page_id` returns `{}` — deliberately NOT
  `_bridge_page_capabilities`' fall-back-to-first-page, because a name map for the wrong
  page puts the wrong words on the wrong band. `render_bridge_script` gained a
  `fragment_meta` kwarg and substitutes `__LUMEN_NODE_NAMES__` through `_script_json`.
  The render route passes `fragment_meta_for_document(document, repo.list_web_fragments())`
  — the same call the GET route makes — only when `bridge=1`.
- **Script (template v11).** Every element is hoverable now, not only `[data-node-id]`
  ones: a hover box + name chip (`isBridgeEl`/`ownerNode`/`elementPath`/`addressOf`/
  `labelFor`/`showHover`/`hideHover`). Click still `setSelected`s the OWNING node and
  additionally posts `{type:"annotate", address:{nodeId,path?,slot?,tag}, name, geometry,
  textLike}`. Inbound `{type:"annotations", items:[{address,n}]}` draws numbered badges via
  `resolveAddress` (a true inverse of `addressOf`, same bridge-chrome exclusion);
  `items:[]` clears. `lastAnnotations` is re-rendered on scroll/resize.
- **Engine.** The Fragment arm's real wrapper emits `data-fragment-root="true"` under
  exactly `node_attr`'s condition (`editor && !suppress_node_ids`) so the bridge can tell a
  clone root from a vocabulary node. NOT emitted on the unresolved-pin placeholder branch
  (engine-authored markup, nothing to address by path). The existing exact-wrapper-string
  test had to grow the attribute; a new test pins editor-yes / delivery-no.
- **Brief defects found and fixed, worth remembering:** (a) the brief's step-1 test and its
  step-3 implementation contradicted each other — the impl maps every node so the fixture's
  `root` yields "Container", the expected dict omitted it; kept the impl, amended the test.
  (b) the brief's escaping assertion was a tautology (`script.split(...)[-1][:0]` is `""`),
  replaced with a real one that plants `</script><img src=x>` as a node name.
- **Live verification** (headless `browse`; note `$B frame` does NOT exist in the installed
  build — use Playwright's `iframe >> internal:control=enter-frame >> <sel>`): chip reads
  `h1 · headline` on a clone's headline; a real `annotate` message was captured in the shell
  with path `:nth-child(1) > :nth-child(1) > :nth-child(2) > :nth-child(2)`; posting
  `annotations` back drew badge 1 on the h1 (path-resolved) and badge 2 on the whole hero
  band (node-resolved); `items:[]` cleared both. Screenshots `/tmp/task5-{hover,badges,cleared}.png`.
  NOT photographed: the band-name chip variant (`labelFor`'s no-path branch) — `browse` can
  only hover an element CENTRE and every band's wrapper is fully covered by a full-bleed
  child, and the sandboxed iframe cannot be scripted from the parent. Hover the gap between
  two bands by hand to close it.
- **Gate.** `cargo test --workspace` 0 failures; `cargo build -p lumen-api-helper --release`;
  wasm rebuild + `HANDSHAKE OK` (`2f8c4edaf3b6` both sides, unchanged — lumen-core untouched,
  tracked wasm artifacts unmodified); the four brief suites 51 passed; 9 adjacent
  fragment/render suites 169 passed; `agent_runtime/test_web_fragment_preview.py` 11 passed;
  stack restarted from the repo root. Ruff: `web_bridge.py` back at its 4-E501 baseline
  (long CSS wrapped), `main.py` 398 before and after.
- **Full `apps/api` suite ran to completion: 2134 tests, 10 failed, all 10 PRE-EXISTING —
  proven, not argued.** `test_api.py` ×4 (`test_w14_model_not_found_404_…`,
  `test_w17a_text_only_…`, `test_w17b_aspect_ratio_…`, `test_w17b_result_reports_…`),
  `test_asset_custody.py` ×2 (`test_pure_python_reads_survive_a_wiped_cache`,
  `test_the_public_route_falls_back_to_sniffing_for_octet_stream_rows`),
  `test_asset_store_serving.py::test_asset_store_serves_content_addressed_bytes`, and
  `test_ingestion_grammar_audit.py` ×3. Each was re-run at base `6527f298f` in a throwaway
  worktree (`git worktree add`, removed after — never `git stash`) and fails identically
  there; the six non-`test_api` ones also fail in isolation, so it is not suite ordering.
  Same class as the recorded non-hermetic residual: a real `OPENROUTER_API_KEY` in `.env`
  makes these routes perform live model calls. **This is the number to diff against next
  time: 10 pre-existing failures in `apps/api` on this box with a live key.**
- **Residuals for later:** `lumen-hover` is now vestigial (nothing adds the class; comment
  left at the CSS rule); badges do not follow a reflow that is neither scroll nor resize, so
  the shell should re-post after a mutation (Task 6 owns the payload); `elementPath` is
  positional, so a structural edit inside a clone invalidates an address and
  `renderAnnotations` silently skips it (the safe direction).

### Fix round 1 (review) — `0dca9621f`
`addressOf`'s `isFragment` also treated any id-less element under any owner as
fragment-like (`el !== owner && !el.hasAttribute("data-node-id")`), so a `<strong>` in a
vocabulary text node's rich-text markup, or a plain child of a section/container, got a
structural path that nothing downstream could resolve (it would be looked up against a
fragment HTML that does not exist). Spec 3.1: vocabulary nodes have `path` absent. Now
`var isFragment = owner.hasAttribute("data-fragment-root");` and nothing else — the
engine stamps that on every clone wrapper in editor mode, so it is the whole truth.
Consequence kept: an id-less element under a vocabulary node addresses as
`{nodeId, tag}`, `labelFor` shows the owner's display name, `resolveAddress` returns the
owner. Pinned by a SOURCE-LEVEL test (the branch lives in the injected script):
`test_only_a_clone_root_gets_a_structural_path` asserts the gate line is present and the
retired clause appears nowhere. 7 passed with `test_fragment_mobility.py`.

**Technique worth reusing:** the Ramp doc is clone-only and cannot exercise the
vocabulary branch, and `browse` cannot script a sandboxed iframe. Fix: render a document
that has BOTH kinds (`doc_d6492814b017542ca1a4dbd9c56e673b` — 42 text/33 container/9
button/8 section + 1 fragment) through the real `bridge=1` route, then mount the served
HTML in a local `sandbox="allow-scripts"` harness page whose parent listens for
`annotate` (`/tmp/task5-harness.html`). Same trust shape as production, fully
controllable, and a red-proof is one string replacement away — restoring the retired
clause in the same DOM reproduced `path ":nth-child(1)"` on the id-less `<p>`.

## Slice 2 — Task 11: the ANNOTATIONS block in the solo prompt — landed `8b1dbea0b`

`build_web_solo_prompt(..., annotations=)` renders the "ANNOTATIONS ARE THE BRIEF" law right after `{account_block}` only when notes ride, and `harness_web.py`'s single solo call site passes `runtime_config.turn_target_notes`; pinned by `test_web_solo_mode.py` (6 passed, 1 pre-existing fail — `.env` sets `LUMEN_AGENT_WEB_SOLO=1`, so the flag-off trio test cannot pass on this box; whole file green with `LUMEN_AGENT_WEB_SOLO=0`).

## Slice 2 — closed 2026-09-05 (controller review)
Commits d28b94402/0dca9621f (T5 bridge) → 0de0705db/36e3bfd8f (T6 shell) → ec9d0c629 (T7 chips + wire) →
b06e1e571 (T8 note column, migration 4cbfa56e52a8) → c209d9e94 (T9 web targets + the submit-time
validator plan gap) → 246047ccd (T10 ANNOTATION lines, wrapper-relative paths) → 8b1dbea0b (T11 prompt
block). Rulings that matter later: paths are WRAPPER-relative (first step = a top-level element of the
stored artifact HTML; Tasks 12–15 must match); click-away with text ADDS; the comment box never leaves
the iframe band; an annotated target replaces its TURN TARGET line. Live acceptance (three annotations →
one real turn) is the founder's walk: in Edit mode click three elements (one inside a clone), Add each,
press send with an empty composer; expect "See annotations." as the message, three noted refs, ANNOTATION
1–3 lines in the worker's brief, and the finalize summary confirming each by number.

## Slice 3 + 4 — closed 2026-09-05

Commits: T12 `19730a98a` (engine model + `set_fragment_text_override`) → T13 `5558f8662` (render) →
T14 `5fc307cbc` (manual-edit endpoint + inspector list) → T15 `345101546` + `64bc67c90` (in-frame clone
text editor; the nearest-text-like fix) → T16 this commit ("Edit text" quick action, the D-F3 amendment
recorded everywhere the ruling is quoted, this entry, the CLAUDE.md backlog bullet).

Load-bearing rulings, one line each:

- **`SetNodeProps` preserves `text_overrides`.** A prop write on a fragment node never silently drops
  the override map — the overrides are a sibling of the slot values, not part of the props being replaced.
- **Render emits `data-lumen-override` + `data-lumen-size`, and the size step is an `em` font-size.**
  Relative, so the clone's own type scale still governs; the two attributes are how the frame and the
  inspector recognize an overridden element without re-deriving anything.
- **Paths are wrapper-relative, and the hidden-slot mirror (`hidden_slot_keys`) reconciles rendered vs
  stored counting.** The first step of a path is a top-level element of the STORED artifact HTML; slots
  the render hides would otherwise shift the child indices, so the mirror keeps the stored and rendered
  counts talking about the same element.
- **The API refuses dead paths only at the manual-edit endpoint.** A path that resolves to nothing is
  rejected where a HUMAN writes it; render and inspect stay tolerant (a stale override is skipped, never
  an error), so a structural change to a clone can never break an existing document's render.
- **The double-click target is the NEAREST text-like element**, not the clone wrapper and not the deepest
  node — the same element a single click would have annotated.
- **The inspector list is read from the document node.** Overrides are per-instance values on the
  fragment node; the fragment card (a registry read about the harvested artifact) does not and must not
  carry them.
- **D-F3 amended by R-A6** — recorded in `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md`
  under the D-F3 bullet, and woven into the four places the ruling is quoted in code
  (`web_bridge.py` allowlists, `webDocuments.ts` allowlists, `model/fragment-card.ts`,
  `fragment_inspector.py`). A clone moves as a whole and exposes slot values AND per-element text
  overrides; nothing else inside it is editable.

### Founder's live acceptance walk (not run by the implementer)

1. Layers panel on the Ramp page: every row is a human name.
2. Hover the Visa image inside a clone: outline + `img`; hover a band: "Hero — …".
3. Three annotations (one inside a clone), Add each, badges 1–3, send with empty composer → agent run
   confirms 1–3 by number; the inner one edited via a variant or rebind, nothing else touched.
4. Single-click a clone headline → Edit text quick action → type, B, Enter → override rendered; inspector
   lists it; Clear removes it; undo/redo round-trip.
5. Double-click does the same directly.
6. Reload drops chips and badges (R-A3); the document keeps the override (it is an operation).

## Controller close-out — Slices 3 + 4 (2026-09-05)
Every task reviewed first-hand at its gate (no reviewer subagents, per the founder's rule). Live-verified
in a headless browser on the Ramp page: double-click → in-frame editor → B + A+ → Enter → the re-render
carried `data-lumen-override`/`data-lumen-size="1"`/`font-size:1.125em` with `<strong>`; `design_document`
v10 stored the override; the inspector listed it with Clear; Clear restored the clone's words. The comment
box's "Edit text" dismissed the box and opened the same editor; Escape closed it. Final gates on
b6f188b61: platform targeted 17, lumen-web 252, design api 27, agent_runtime 62 (SOLO=0), frontend
2137/2137 + lint + tsc 49 + build. Known env-dependence: `.env` sets `LUMEN_AGENT_WEB_SOLO=1`, so the
trio-shape tests (`test_web_solo_mode.py` flag-off case, `test_the_author_holds_both_halves…`) need
`LUMEN_AGENT_WEB_SOLO=0`. Still the founder's: the live annotation send (three notes → one turn) and the
Slice 4 walk items 1–6; undo/redo of an override was not exercised live (engine-tested).
