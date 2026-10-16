# Source document context validation — 2026-09-20

## What changed

Extracting a section previously discarded HTML/body inheritance. AWS's body class supplies Arial 14px/1.6 and descendant button resets; the detached section inherited the host's Inter typography instead. Separate, non-layout source HTML/body contexts now transport supported inherited declarations, custom properties and proven document-prefix rules. The compiler preserves specificity, rule conditions, relative units and source URL custody. Authored HTML/body direction/language are retained without giving presentation hints priority over authored CSS.

No brand names, font pixels or per-company overrides are embedded. Slots and dormant-state detection run on original section markup before adding the inheritance containers; the engine's slot selectors then receive the corresponding structural prefix. Unsupported document selectors, omitted ancestors/sibling positions, source state, layer approximation and dir=auto remain explicit limitations. This is DOM/CSS transport, not recovery of the original React or JavaScript program.

## Verification

Parent independently ran 164 focused tests, all passing: the new context suite, existing section-mint tests and root-unit tests. Tests use the real local renderer, checking universal/generic selectors, equal-specificity/root-versus-body cascade, responsive/inline units, source-owned asset refusal, real headline/visibility edits, container collisions, default/explicit/overridden direction, language and dormant fragments. Independent read-only review found and rechecked fixes for functional-selector diagnostics, host writing defaults and attribute-only activation. New files are Ruff-clean; diff whitespace is clean.

Frozen AWS artifacts were reminted without network/model calls or registry writes. All 12 remain draft. Actual production delivery/editor HTML was rendered, rather than using standalone admitted.html as the product comparison. Parent visually inspected desktop source/delivery and mobile delivery screenshots.

At widths 1440 and 375:

| Measurement | Source | Delivery | Editor |
| --- | --- | --- | --- |
| Hero H1 desktop box | 504 × 88 | 504 × 88 | 504 × 88 |
| Hero H1 mobile box | 279 × 108 | 279 × 108 | 279 × 108 |
| Geographic Regions H3 font/line | Arial 16.38 / 26.208px | Same | Arial 14 / 22.4px |
| Create-account CTA font/line | Arial 14 / 22.4px | Same | Same |
| Create-account CTA desktop height | 44px | 44px | 44px |

The editor H3 discrepancy is still open: the editor's default heading reset changes the browser's native heading size. Captured support-chat UI is also still present. These results do not establish full-page motion, interaction, account personalization or all-brand quality acceptance.

## Cost and retained evidence

The final frozen 12-section mint took 105.39 seconds wall / 103.90 seconds CPU. CSS totals were 32,731,643 bytes before this change, 62,135,848 in the first implementation, 45,219,928 with shorter collision-checked context tags, and 40,712,785 after omitting guards from compounds provably unable to match context containers. Final overhead is 24.4%. Repeated page CSS and parsing remain a material performance follow-up; no speed improvement is claimed against a timed pre-change run.

Ignored evidence: `.local-setup/website-capture/source-context-20260920/` holds final fragment JSON, measurements and six viewport screenshots; `source-context-parent.xml` holds the parent test result. Frozen capture inputs remain unchanged. Main checkout, live DB/environment/services and remote history were untouched.
