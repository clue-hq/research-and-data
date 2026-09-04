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
