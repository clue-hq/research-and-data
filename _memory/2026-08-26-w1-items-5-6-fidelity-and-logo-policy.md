# W1.5 + W1.6 — typed reference_fidelity, and the logo placement policy vocabulary

Spec: `subsystems/clue-design/docs/brand-ad-assets-v1-spec.md` §5 W1 items 5 and 6.
Base attested: `1324539a7` (worktree arrived at `5ea7a8791`, which did NOT contain
the base — reset before any work).

## W1.5 — `reference_fidelity` always lands in the TYPED field

**Root cause.** In the fast loop there is no reviewer and no typed critique
writer. The author writes `critique.json` with the generic deepagents
`write_file` tool; the only thing shaping it is
`prompts._AUTHOR_SELF_AUDIT_CONTRACT`, whose JSON template names
`accepted`/`summary`/`issues`/`acceptance_notes`/`confidence` and never named
`reference_fidelity`. The field is `Optional[...] = None` on `VisualCritique`, so
an omission validates. Only the reviewer prompt (`_REVIEWER_REFERENCES_BLOCK`)
ever instructed the field — and the reviewer is quarantined in the fast loop.
That is the whole Cursor-vs-Apollo divergence: nothing REQUIRED the typed field,
so the model sometimes typed it and sometimes wrote prose.

`substrate.submit_visual_critique` (the one typed writer) is dead code in the
deepagent runtime — registered only in `lumen_pipeline_archive`.

**Fix.** New `lumen_agent/critique_fidelity.py` — one pure module — applied at
the two seams a critique passes through on a reference turn:

1. `fs_backend.AgentWorkspaceBackend.write` (new `reference_turn` ctor flag,
   set from `runtime_config.reference_assets` in `harness.py`) normalizes any
   `critique.json` write. This is the fast loop's ONLY choke point for the file.
2. `substrate.finalize_run` normalizes the critique it was handed before the RC
   gate reads it, covering an orchestrator re-serialization.

Promotes a score the author WROTE (prose in `acceptance_notes` /
`requirement_coverage_notes` / `summary` / `repair_instruction`); also coerces
`2.0` and `"2"`, which the gate's `isinstance(score, int)` rejects. With no
score anywhere it stamps `score: 0` — the model's own default, and the gate
still refuses `<= 1`, so this cannot launder an unjudged run into an accepted
one. Bools are excluded (`isinstance(True, int)` is true).

A reference-turn-only clause was added to the FAST-LOOP author prompt so the
author types a real judgment rather than relying on the 0 fallback. Flag-off
prompt bytes untouched; the byte-identity tests stay green.

**Residual.** `edit` on an existing `critique.json` is not normalized (only
`write` is). No caller does that today — each round writes a fresh file.

## W1.6 — logo placement policy vocabulary + LUMB0810 severity

**Root cause of the vocabulary gap.** `allowed_backgrounds` is a `Vec<String>`
on the Rust `LogoAsset` and is SLOT-level. `normalizer/emit.py::add_logos`
appended `surface.inverse` only when a variant's `color_mode_hint` was exactly
`"reversed"`, and never `surface.brand`. The human-curation endpoint
(`main.py::set_brand_kit_logo`) rewrote `variants` but left
`allowed_backgrounds` alone, so promoting a reversed logo into a light-only slot
left the kit unable to say the mark may sit on a dark field.

**Fix.** New `lumen_ingestion/logo_policy.py`, called by BOTH producers:
light surfaces always allowed; a slot holding a `reversed` OR `light` variant
additionally allows `surface.inverse` + `surface.brand`. Strictly more
permissive — it can never create a diagnostic where none fired before. Curation
widens an existing policy and never narrows it; an EMPTY list stays empty
(empty means "do not check this slot" in the engine).

**Severity — verified ADVISORY, no downgrade needed (founder ruling D5 holds).**
LUMB0810 is emitted only in Rust (`crates/lumen-core/src/brand.rs`, in
`validate_scene_brand_governance`) and its severity is `error` under
`strictness=strict`, `warning` under `advisory`. The agent calls governance at
`strictness="advisory", raise_on_error=False` (`substrate.preflight_design`), and
governance diagnostics are deliberately kept OUT of
`_latest_preflight_diagnostics`, which is what the P0.3 finalize gate partitions.
`export_policy` only classifies preflight diagnostics. So LUMB0810 blocks
nothing anywhere. Now pinned by tests; nothing pinned it before.

**Live engine probe** (throwaway script, prebuilt helper from the main checkout;
this worktree makes no `crates/` changes). Reversed logo on a `$surface.inverse`
artboard:

| kit | advisory | strict |
|---|---|---|
| `["surface.page","surface.card"]` (pre-W1.6) | LUMB0810 **warning** | LUMB0810 error |
| `[…,"surface.inverse","surface.brand"]` (post-W1.6) | none | none |

Exactly the required red case.

## Findings NOT fixed (out of scope, recorded)

1. **Per-variant surface policy needs an engine change.** `allowed_backgrounds`
   lives on `LogoAsset`, not `LogoVariant`, so a slot holding both a full-colour
   and a reversed mark permits EITHER on EITHER surface. Expressing "the reversed
   variant may go on inverse, the full-colour one may not" requires a field on
   the Rust `LogoVariant` struct plus a change to the check in
   `validate_scene_brand_governance`. Rust serde drops unknown fields, so it
   cannot be faked from Python. NOT DONE — engine changes were forbidden.
2. **Website ingestion never detects logo colour mode**, so a website-ingested
   kit still gets `["surface.page","surface.card"]` and the new vocabulary is
   unreachable on that path. `capture/evidence_builder.py` builds `LogoEvidence`
   with no `color_mode_hint`; the upload path has a luminance detector
   (`capture/uploads.py::_logo_hints`) and the PDF path has vision hints, and
   both now produce the right policy. The bytes ARE available in
   `evidence_builder` (`sha_bytes`), so wiring the detector is feasible — but it
   is a DETECTION gap, not the vocabulary gap this item names, most website logos
   are SVG (which the luminance detector skips), and `w1-ingestion` owns those
   files this wave. Unowned.
3. **`strictness="finalize"` is not a Rust enum variant.** Python's
   `models.py` `Literal["advisory","strict","finalize"]` and the editor
   (`engine/brandGovernance.ts`) both use `"finalize"`, but
   `BrandGovernanceStrictness` in Rust is `Advisory | Strict` with no serde
   alias — a real `finalize` request should fail helper request parsing.
   Pre-existing; not touched.
4. **A brand kit the engine cannot deserialize yields SILENTLY zero governance
   diagnostics.** Hit while building the probe: the helper returns
   `{"ok": false, "error": {...}}` and the agent's
   `governance.get("diagnostics", [])` reads `[]`. Advisory-only surface, so no
   safety impact, but "no governance findings" and "governance never ran" are
   indistinguishable at that call site.
5. **Pre-existing test failures at base** (verified by stashing): several in
   `apps/api/tests/test_ingestion_routes.py` (flaky — a varying subset across
   runs), all of `test_ingestion_brief.py`'s brief tests, and
   `test_ingestion_ui_api.py::test_pipeline_ingested_assets_get_db_records`.
   Not caused by this work.

## Tests

- `apps/agent_runtime/tests/test_critique_reference_fidelity.py` — 27 new.
- `apps/agent_runtime/tests/test_deepagent_harness.py` — 3 new finalize-gate tests.
- `apps/api/tests/test_logo_policy.py` — 24 new.
- `apps/api/tests/fixtures/ingestion/expected/evidence_pdf_insight.json` — the
  one golden that moved (it has a reversed variant, so it now also carries
  `surface.brand`). The website golden is byte-identical, as expected.
- Red proof for W1.5: stashing the fix makes 6 of the new tests fail.
- Full `apps/agent_runtime/tests` green.
