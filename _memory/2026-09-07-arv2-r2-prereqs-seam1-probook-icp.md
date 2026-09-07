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

## 2026-09-08 — S7 substance rev 2 (founder rulings + PoC completeness pass)
- Ruled: **full mode only**; stop policy = 100 model rounds, 50 tool calls per round, 30 min wall
  clock; **no** total tool-call cap, **no** consecutive-zero-yield cap. A looping run is observed
  and fixed, never pre-restricted (the old lane failed under stacked caps). The seam-1 `effort`
  field stays in the contract (D6) but profile v1 runs full regardless and records the rung.
- Completeness pass: rev 1 generalised only z5; rev 2 merges step6 (Probook) + b1b (five accounts,
  SPECIAL PROBES) + b3 negatives + step9b/9c second-pass extractors + z2 free ladder + the three
  reports' lessons. Added to the prompt: prefer primary sources; CONFIRMED/DENIED/UNRESOLVED rule;
  evidence outranks the operator-supplied lock; one subject per structuring call. Dossier charter is
  now **twelve** sections (identity & disambiguation and culture & resonance were missing). Ladder
  gained: careers page without an ATS, per-account probes into the deep call, a cheap negatives
  search, name-scoped-only people lookups, audio over video. Structuring gained the narrow intent
  sweep (needs a `mode` on the R1 client — R2 owns) and a field-meaning review before write.
- Still open for the founder: §6 items 1–4 of the substance doc.

## 2026-09-08 — S7 rev 3: ICP hard gates are lenient fit verdicts, never an early exit
- Founder was alarmed by "gate" and asked for leniency. Ruled + applied: no `gate_failed` refusal,
  no early finalize; every launched account gets the full ladder (seam 1: research never vetoes a
  launch). Per gate the agent records `pass | likely | unclear | fail` with claim ids in the
  finalization summary (`fit_verdicts`); `fail` only on positive contrary evidence, NOT FOUND =
  `unclear`; the human decides fit. Pre-launch qualification belongs to R4 discovery.
- Stand-in ICP softened accordingly (stage test wording; §7 floor paragraph). The dev DB holds the
  earlier rendered version — reloading mints a new confirmed version; do it before the R2 live run.
- §6 open items now 2–4 only.

## 2026-09-08 — S7 substance fully approved
- Founder agreed to all remaining recommendations: section-11 negatives born `outreach_safe=false`;
  twelve-section charter (master plan §9 R2 row corrected); R2 extends the R1 structuring client
  with `mode=broad|intent_sweep`. No S7 ruling is open. Next: the R2 plan document
  (writing-plans) + the S7 file charter; AI Ark people credit is the only external prerequisite left.
