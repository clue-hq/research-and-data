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
