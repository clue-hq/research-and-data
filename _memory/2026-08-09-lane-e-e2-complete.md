# 2026-08-09 — Lane E slice E2 COMPLETE (`contact.overview` + G6 + the binding stamp)

## Process
Same orchestrated loop as E1 (keep for E3): one Opus contact-side study → Fable brief
(`.context/e2-implementation-brief.md`, incl. two orchestrator rulings) → WP-A2 + WP-B2 Opus
implementation → Fable review gates → commits `89345e9b` (synthesizer) + `bf9da426`
(tool/step/threading).

## The two rulings (recorded deviations from the charter's literal wording)
1. **Binding stamp = fail-closed re-read.** The merge excludes WEAK contact claims in both
   toggle modes, so the charter's "all cited STRONG else WEAK" is vacuous over a plain
   `current_values` read. Shipped semantics: re-read winners via `claims_by_ids` (same txn);
   STRONG iff every cited CONTACT claim is explicitly STRONG; `None` counts as not-STRONG (the
   merge serves `None`-bound plain contact claims — the hole a future writer could ship). AC:
   `None`-bound input ⇒ overview born WEAK, stored-but-never-served (three independent gates,
   both modes); literally-WEAK inputs never surface ⇒ coverage gap.
2. **G6 = claim-level `use_class` filter, never a field-key denylist.** Facet escalation to
   SENSITIVE is per-claim at extraction; `CurrentValue` carries no governance columns; the
   re-read drops SENSITIVE and (fail-closed) `use_class=None` CONTACT claims — totally: no
   prompt text, no coverage credit, no span, no support id. Import-legal (pure `clue_core`;
   `narrative` may not import `clue_research.compliance`). `causes`/`stated_interests` stay ON
   the allowlist by key — claim-level filtering is what lets a de-escalated claim be material.
   Extension point if policy-aware eligibility is ever needed: injected reader on the
   `narrative.seams` FacetHook/CommitteeReader pattern.

## What landed
- `prose.py`: `synthesize_contact_overview` on the shared `ProseSynthesizer` (additive
  `contact_policy` kwarg; `DEFAULT_CONTACT_PROSE_POLICY` = contact_overview_v1, min_facts=2
  counting CONTACT facts only); `_read_contact_evidence` (one-txn merge read + governance
  re-read); employer context (`PROSE_ACCOUNT_CONTEXT_FIELDS` off `parent_account_id`) is
  optional garnish — second fence, support ids, span; never coverage, never the binding rule;
  contact claim born `contact_claim(identity_binding=computed, use_class=PROFESSIONAL_PUBLIC,
  research_mode=CONTACT_PROFILING)`; shared `_PROSE_SCHEMA` with `project_id: None`; shared
  `_finish` so the tenants can't drift on judge/metric discipline. FakeJudge in the test suite
  corrected to mirror `status_for_verdict`'s `can_be_promoted` guard (the old unconditional
  promote would have masked the WEAK guarantee).
- Tool: `ProseSynthesisServices.contact` REQUIRED (production passes ONE synthesizer instance
  as both fields — the split is a future-divergence seam); per-field `field_not_composed`;
  `invoke` routes by field key; contact branch passes nullable `parent_account_id`.
- Step: `after_contact_job` → shared `_offer` (structural `_FinalizedJobSummary` Protocol over
  both lanes' summaries; one never-raises catch-all; field-parameterized operation id — scope
  string `lane_e_prose` FROZEN). Contact handler: `prose_step` kwarg + one naked call after
  `project()` — that handler has NO try/except; the step's never-raises guarantee is the entire
  containment (comment at the call site says exactly this). One step instance, both lanes; no
  new bind; no authority/matrix/count changes.
- E1 suite deltas: `test_contact_overview_is_refused_as_not_yet_composed` deleted (pinned the
  behavior E2 retires, per brief §2.2); services constructions gained `contact=`.

## Verification (Fable-re-run, :55060)
E2 acceptance 10/10 under `CLUE_VERIFICATION_ENABLED` true AND false; tool/step/composition 57;
E1 acceptance + toolbelt wiring + narrative (138) + contact_research + agents all green; wide
api/integration/fleet sweep green except the two known pre-existing failures (agent-registry
snapshot v9/v10 pin; b4 composed-run cross-suite ordering). mypy 587 clean; contracts 25/0;
ruff/format clean. WP-B2 red-proofed the acceptance suite by reverting all six platform files
and re-running (all 10 RED on the two expected TypeErrors).

## Defect found and recorded (NOT Lane E's) — see the CLAUDE.md backlog bullet [C7×core]
Contact view fails composition outright on a NULL-binding + non-null-use_class plain `contact.*`
merge winner (`research_view.py:334-335` both-or-neither vs. facet-only CHECK/model validation).
Latent (no production writer emits the pair; `contact_claim` requires both) but armed; SUMMARY
goes down with the whole view. Owner: C7/FI-2. Suggested posture: NULL binding ⇒ drop statement
as not-displayable, never fail composition. Until fixed, E2's AC3 asserts the substrate
guarantee (born WEAK, unserved both modes) instead of the composed empty state — AC1/AC2 prove
the SUMMARY section reads through the same merge.

## Notes for E3 (Positioner composition — the last slice)
- Sequencing gate long satisfied (FI-2 slice-3 T1 `5fa0403c`+`6626edf3`); D3 ratified IN.
- The trigger + optional-judge patterns are now proven twice; E3 composes the existing
  `Positioner` (zero production constructors — `judge: FaithfulnessJudge | None` since A+B) with
  the api-root seams (`build_client_knowledge_retriever`, `ProductionHandoffCommitteeReader`,
  `FaithfulnessJudgeImpl`) behind its own flag, invoked from the same post-finalize account
  step per charter §5-E3.
- The account-lane step currently offers only `account.summary`; E3 adds the narrative offer
  (own flag, own operation-id field key `account.value_narrative`).
- Remember the E1 residual: the tool's `gateway` param is redundant at runtime — revisit
  during E3 if the tool grows a narrative field.
