# 2026-09-07 — R2 prerequisites, wave 1: Seam 1 signed, Probook seeded, stand-in ICP + persona, S7 substance

Branch `track-R2` (worktree san-salvador), off `origin/integration/design-improvement` @ `602a2dac5`
(O1 + O2 + D1 merged; single alembic head `3742d1281a10`). Session ruling: the user executes both
founders' lanes, so "sign seam 1" = both columns, same day.

## Done this wave
- **Seam 1 RATIFIED** (`docs/specs/ARV2-R0-seam-freeze.md`): boxes 1a (structured block, D6) and 1b
  (entities exist first, D7) recorded inline; signature amended with `product_selection_version`
  (master plan §5.1 / P1–P2). Seam 2: 2b (automatic registration, onboarding plan §6.1) and 2c
  (`user` in the enum, D8, shipped by D1) recorded; **2a = D9 stays open** — the only unsigned box.
  Master plan §12 D6/D7 now co-signed in Shashank's column.
- **Probook seeded** as the fifth `AccountSpec` in `ZAFRAN_MANIFEST` (entity only — R2 researches it
  live; `.context/arv2-clue-sample-v3/claims.json` is the comparison key, deliberately NOT loaded).
- **Stand-in knowledge documents** in `.context/arv2-answer-key-knowledge/`:
  `icp-clue-abm-buyers.md` (kind `icp-definition`, §6.1 shape: 4 hard gates with `test`, 8
  exclusions, five-role `persona_map{titles[]}`, 10 `qualifier_fields` on registered keys with
  `display:` slugs) and `persona-clue-abm-buyers.md` (kind `audience-persona`, §6.2 shape).
  **One ICP, not two:** both answer-key accounts pass the same Clue ICP (Probook Series A 2026-06,
  Zafran Series C 2025-12; both US, hiring, with a GTM requisition as the Q1 intent signal) and D16
  says one ICP per project — the second artifact became the persona document R2's committee
  resolution needs (`titles[]`). Told the user explicitly.
- **Loader** (`answer_key_loader.py`): `_confirm_product_set` (synthetic `platform_user`
  `usr_arv2_answer_key`, synthetic gate id — `project_product.gate_id` is not an FK — version 1) and
  `_knowledge_documents` (front matter parsed, confirmation-only fields stamped at load, rendered via
  O2's `render_markdown`, content-addressed artifact + `brand_knowledge_document` row: ICP
  `confirmed`, persona `ready`). `ensure_project_run` now pins `icp_key="clue-abm-buyers"`.
  `LoadReport` gained `product_selection_version` + `documents`. O3's `open/publish_document`
  helpers own this write once merged — the loader should call them then.
- **Dev DB** `clue_san-salvador` (port 55040) created (did not exist), migrated to head, answer key
  loaded for real: 294 claims, 5 accounts, product set v1, both documents. Reload = fresh DB.
- Tests: `tests/arv2/test_answer_key_knowledge.py` (new, pure §6.1/§6.2 shape checks); loader DB
  test asserts product set v1 + document statuses + rendered confirmation fields; `created` events
  now 5. 24 pass; ruff/mypy/import-linter clean.
- **S7 substance** for founder review: `docs/superpowers/plans/2026-09-07-arv2-s7-agent-content-
  substance.md` — proposed 12-tool surface, profile policy (effort rungs 24/14/6 rounds), prompt
  constitution, ten-section dossier skill (z5 generalised; §9 negatives REQUIRED), audit skill
  (`verify_links` + `substring_verdict` as annotation), refusal→reaction manual (14 codes). §6 lists
  the four founder calls needed before files are written. No catalog file written.

## AI Ark credit — NOT resolved
`/v1/companies` returns 200 (0.1 cr), but `/v1/people` (name-scoped, size 3) returns **402** and the
client latches `ai_ark_credit_exhausted_or_denied`, so 6 of 7 live tests fail. The account still
lacks credit/plan for people + export. User action; re-run `tests/arv2/test_ai_ark_client_live.py`
(≈3.2 cr, ~1 min) after the top-up.

## Open / next
- D9 (equivalence clause) — founder ruling; then tick Seam 2.
- Founder review of the S7 substance (§6 questions) → Opus writes the five catalog files.
- O3 next (production sinks + fleet driver pattern), then the R2 plan.
- `display:` slugs in the ICP follow master plan §7 names kebab-cased; D2 fixes the vocabulary.
