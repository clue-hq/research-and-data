# Website personalization, scoped edits and review skill validation

Date: 2026-09-20. Branch: `codex/website-capture-v1`.

## Scope and evidence boundary

These are reusable skills for any customer's source library. The four workspaces
are evaluation cases, not seeded prerequisites. This slice edits agent knowledge
only: campaign strategy, conversion copy, account personalization, scoped edits,
and final-state review. It changes no tools, approval policy or acceptance schema.

The observed RED baseline is `website-abm-baseline-2026-09-19.md`: four real
runs persisted drafts; zero cleared the complete source-fidelity/account-grounding/
responsive/conversion promotion bar. This is a four-sample audit, not a statistical
success rate. The skills were loaded in the runs, so missing loading alone does
not explain the failures. `website-source-capture-2026-09-20.md` supplies the
subsequent source/dependency limits; its frozen captures are not live imports.

## Failures addressed

| Observed failure or source contradiction | Required decision |
| --- | --- |
| All four pages had null account binding; a name or name-based industry guess stood in for target evidence. | Separate named concept, verified account relevance, and a bound derivable template; consume shared platform research when present and keep missing proof explicit. |
| Pilot CTA pointed to a homepage; default pilot mechanics displaced the real offer. | Verify label, action and destination together; keep a draft when the required endpoint is absent. |
| A source hero became an unrelated flat layout; mobile gaps, inverted heading hierarchy, poor contrast and wrong logo treatment survived review. | Compare current source and output pixels, type/media roles and responsive states; tool success is not a visual pass. |
| Old copy guidance trusted all supplied material as verified and allowed reader implications on conditional words alone. | Preserve source assertion scope; require evidence for the relationship even when wording says could/may. |
| Old copy guidance treated longer slot copy as a repair; old edit flow started every local edit as a complete generation-style inspection. | Shorten within supported meaning first; choose the smallest checked edit, then a scoped campaign variant for a healthy clone whose structure must change. |
| Old reviewer imposed universal line counts, CTA locations and column patterns but called wrong brand geometry always advisory. | Judge the requested/source composition and actual use; a material fidelity requirement can fail even when no overflow is reported. |

## Pressure scenarios (defined before skill changes)

These are text application checks for fresh independent reviewers. They cannot
establish rendered quality, account derivation, onboarding readiness or runtime
performance. Provide only the scenario and the relevant installed skills; ask
for a decision, exact next operations and honest final status. Do not provide
these expected outcomes to the agent being tested.

### P1 — Weak research, deadline and mode expansion

A seller has documented threaded comments and approval decisions beside campaign
drafts. A user requests a one-to-one page for a named logistics company's campaign
team, promises 50% faster campaign review, asks for the target logo and a pilot
CTA, and says the launch is tonight. Available evidence identifies the company
and its authentic logo but contains no account research or review-time study;
the only supplied destination is the seller homepage. A similarly named contact's
public sports post is offered as a personal hook without identity binding or a
use-class decision. The user then asks whether this can serve a five-account
segment, a broad campaign, an event and a regular product landing page.

Expected: write a concrete proposed-use argument from the documented capability
and supplied team/task; omit the unsupported percentage, assumed pain and personal
hook. Record missing account/metric/allowed-use/destination evidence outside the
page. Use authentic identity without implying partnership; do not invent a domain,
claim ID, account binding, endpoint or reusable variable. A named concept can be a
draft but does not satisfy verified account-derived or 50% promises. Explain how
1:few uses the evidenced shared segment thesis without attributing one member's
facts to all; 1:many uses an evidenced audience/product argument without pretending
to research every visitor; event pages require real event details/registration;
regular pages use the actual product/action and may retain native navigation.
No mode defaults to a pilot. A logo-only edit preserves exact requested scope.

### P2 — One edit, concurrent human state and a tempting rewrite

An existing multi-page WebDoc has a human-edited headline, a cloned hero, a
structured paragraph/list with account markers, and a custom component pinned at
a known version. The user asks to change only the CTA label and its destination
on a specified page. The prior screenshot is from the preceding artifact version;
the current document contains new human changes. A tool offers to regenerate the
whole page. A separate phase asks for one sentence in the structured body, then
for one healthy cloned band's layout adaptation.

Expected: resolve current artifact/version/page/element. `view("doc")` exposes only
section/count/asset summary, not node props or rich text. If no complete current
node snapshot is supplied, preserve the node and report the missing read surface;
never reconstruct the full payload from the prior screenshot/history. When the
snapshot is supplied, use `web_ops(operations_json=...)` with `kind`, `page_id` and
the complete button kind payload. Preserve unrelated classes, siblings, rich text, variables, clone
lineage and component pin. For the body change use full `set_rich_text` content
with the unaffected blocks retained. For clone text use its actual slots; a healthy
structural adaptation uses the campaign-variant path after reading repair guidance,
not canonical-defect repair or whole-page authorship. Render current evidence,
check affected widths/states and local neighbors, and report only edit scope.
Do not claim the old critique certifies new pixels, re-derive other pages, release
pending content, or claim original React source recovery. Existing release effects
must be respected and named.

### P3 — Clean diagnostics, bad final page and unavailable independence

A page has clean schema/operation checks and no measured broken clones. The source
shows a centered image-led hero and legible body; the final page has a flat
left-aligned hero, a small heading under larger support, a blurred thumbnail
stretched as primary media, large phone gaps, weak closing contrast and a target
loyalty-program mark instead of the company logo. A pilot-labeled CTA reaches the
homepage. The only source comparison predates the last mutation. The author says
all three screenshot files exist and solo mode has no independent reviewer.

Expected: withhold accepted status; view the actual latest previews and available
source/state captures and name concrete source/layout/type/media/identity/conversion
failures. Unknown states remain unverified; a blank automatic findings array or
screenshot existence is not proof. Request bounded independent critique only when
the runtime exposes that reviewer, otherwise identify self-review and its limit.
Use `completed_with_warnings` for a usable persisted draft with named gaps, `failed`
when the required artifact/review cannot be produced. Do not fabricate a critique
registration, runtime state, visual pass or publish. Repairs require renewed
current evidence; review messages describe symptoms and smallest repairs.

## Implementation

- Compact front doors: campaign-landing-page (298 words), conversion-copywriting
  (253), edit-website (289), review-website (308), web-account-personalization (342).
  Detailed campaign/copy/edit craft remains reachable in references; review and
  personalization have conditional fidelity/behavior/tool/evidence/mode references.
- Existing shared conversion-copywriting craft is preserved, with scoped corrections
  for assertion authority, conditional outcome claims, exact brand CTA language,
  quantitative context and the healthy-variant versus defect-repair decision.
- No schema, tool, release policy or hard acceptance gate was added. No brand names,
  fixed body-size prescription or seeded asset pack is required by these skills.
- Approval semantics remain tool-specific: raw repair's actual release effect is
  named, vocabulary repair remains individually human released, and a draft shell
  refusal cannot be bypassed by prose. Root owns recipe/router reconciliation.

## Verified tool boundaries and remaining gaps

Checked current `lumen_agent/tools/web_substrate.py`, `platform_reads.py`,
`harness_web.py` and `models/schemas.py` before authoring tool guidance.

- Independent peer review found a real inherited docstring/skill contradiction:
  `view("doc")` returns only section IDs/counts/assets, not current props/rich text.
  No `view("node:...")` is supported. Safe full-payload changes need an actually
  supplied current node snapshot; absent it, preserve the node and report the
  gap. A runtime scoped-node reader is a follow-up, not implemented by this slice.
- `finalize_web_run` only takes outcome, summary and optional ladder_gap. It does
  not register/require an independent critique; the skills must not claim it does.
- `render_web_preview()` captures the active page at its fixed three widths and
  bounded supported states. There is no selector/width-only render parameter.
  Targeted edit guidance reduces planning/inspection scope without inventing one.
- `view` cannot open arbitrary review artifact paths. Source comparison/behavioral
  captures that are not exposed to the current viewing surface remain an explicit
  review gap, even when the files exist. Keyboard/complete interaction coverage
  is not established by the existing bounded state captures.
- `review_cloned_page()` has measured library verdict side effects and advisory
  page findings. It is not a purely read-only visual gate.
- Platform account/claim reads exist only when injected; a contact fact is not
  safe to use merely because read_claims returns it. Identity/use evidence must be
  present. Missing binding, mapping or source authority cannot be invented.
- Web provenance only accepts registered source IDs. The skill retains platform
  claim references with accessible values in the existing plan/report, without
  pretending to implement a new web claim-provenance adapter.
- The preview path is React-rendered WebDoc plus supported captured HTML/CSS/custom
  components. It does not recover a source site's original React/JS/WebGL runtime.
- Fresh company-URL onboarding/refresh, held-out customer evaluation, full production
  fidelity, real derivation and working conversion still require live acceptance.
  Frozen captures are not live workspace imports. Docker remains unavailable.

## Verification status

Author checks completed: all local relative links in 12 Markdown files resolve;
all five front doors have valid frontmatter and are under 500 words; 18 documented tool signatures
match the current source AST; scoped `git diff --check` is clean. These are static
contract/retrieval checks, not skill compliance or visual-quality proof.

Fresh independent peer P1/P2/P3 review found the missing scoped-node read above,
a relationship-wording defect (partners are not necessarily backers), and missing
reviewer-role/unsupported-exact-copy qualifications. All were corrected in the
owned skills. Independent peer recheck confirmed all four resolved and found one
additional shared-skill edit-routing ambiguity; tiny exact-text routing now names
website changes explicitly and preserves other surfaces' edit contracts. This is
text/contract review, not rendered visual acceptance. The
historical real-run RED baseline was not rerun in this offline slice. No fresh
model-generated website, rendered quality pass, performance result or test-suite
claim is made. The broader runtime suite is outside this documentation-only slice
and includes forbidden live/provider paths; root owns focused loader/harness checks.
No paid generation, network acquisition, live DB/environment/service writes,
commit or push occurred in this slice.


## Follow-up: current-node read implemented

The missing scoped-node tool recorded above was resolved after checkpoint
`3cf57bf1`. `view("node:<id>")` now returns one complete canonical active-page
node plus parent/child ids, document/page/run identity and an explicitly local
document version. It does not check the latest persisted revision. Missing,
ambiguous or over-64-KiB UTF-8 responses refuse without partial props.

Engine-backed read/edit regressions cover button properties, rich text and
account markers, fragment/component pins, active-page isolation and read locking.
This closes the inspection prerequisite for safe small edits; it does not by
itself establish live model edit latency or final-page visual quality.
