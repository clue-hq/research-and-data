# Shared website skills: controlled native qualification

**Result: not qualified.** The single approved native test completed with warnings.
Shared skill delivery improved and target identity moved out of navigation, but
typographic drift, lost account binding, static interaction fallback and excessive
mobile length remain. Do not promote this result or start another paid run from
these observations alone.

## Test boundary and receipts

- Source checkpoint: `1f01aee6e7fe15163be544d2fa5016a471c942c7` on
  `codex/design-agent-v1`.
- Fresh project in the existing Conduit Fresh workspace; Home prompt with the real
  Hotel Equities account mention: “Create a one-on-one landing page for
  @Hotel Equities using our branding and saved account research.”
- No Project Instructions added; no corrective follow-up, manually authored page,
  model change, second generation or source modification during the test.
- Three APIs and four owned workers were reloaded after Docker/image health and
  an empty active-task check. Frontend and other checkouts stayed unchanged.
- Project: `prj_b60c93f2decd5c2cbf516789d7149cb0`.
- Chat: `thr_06d494490683560599aba819380dcf2b`.
- Run: `run_23b89f6a84755a41bca4649b271f63f2`.
- Session: `dsess_770d11612a81524392eb1f5e2e2305a0`.
- Document: `doc_c79393ede1ca5b26ab09a984009bbe96`.
- Database execution status: `succeeded`; design outcome:
  `completed_with_warnings`. These are execution results, not visual acceptance.
- Design log interval: 06:55:56–07:06:28 UTC, 29 September 2026 (about 10m32s).
  Recorded design model usage: 26 calls, $2.8693; excludes strategy-agent and
  provider costs. Largest prompt: 182,310 tokens.

Ignored diagnostic directory:
`.local-setup/native-account-skills/shared-skill-native-20260928/`.
It contains the sanitized design checkpoint audit, strategy handoff audit,
typography measurements and screenshots. Native render/layout/finalization
receipts remain in this session's `turns/<run>/` directory. Do not copy raw
research, credentials or checkpoint dumps into tracked notes.

## Findings with causal evidence

### 1. An account-specific request became an unbound document

The strategy agent successfully read the tagged account's overview and claims.
Its `read_project_accounts` returned zero members for the newly created project.
Its first `open_design_leg@5` explicitly supplied the correct account entity ID.
The tool refused with `design_leg_account_not_on_project`, advising that the
caller could add the account to the project **or drop the account from the item**.
The second call omitted `artifacts[0].account_id` and succeeded.

Consequently, Design's `view("account")` said no target was attached and both
project-account reads were empty. It received a prose research summary and claim
IDs, not a usable account binding; it made no `read_account_research` calls. This
was not a lost logo or missing database row. The strategy agent deliberately
removed the binding after a membership refusal. The membership guard itself is
correct; weakening it would violate the scope boundary.

Next fix: preserve explicit tagged-account intent through the shared project
membership and design-birth flow. Use the normal authorized membership seam or
return a clear unresolved prerequisite; do not silently remove the binding.
First regression case: fresh Home project + an existing workspace account tag.

### 2. Typography instructions were delivered, but measurement was skipped

There were 19 successful skill/reference reads (including rereads), now covering
`create-website`, media composition, product story and `review-website`. The
canonical source/format contract was materialized in the active runtime. Yet the
run made zero `set_web_typography_reference` calls and declared no references.
Its plan listed family aliases and utility names instead of a measured role map.

Final render measurements, corroborated in the live native iframe:

| Role | Captured source band | Newly composed band |
|---|---|---|
| Desktop/tablet section heading | Season Mix Regular, 48px, weight 400 | Season Mix Medium, 32px, weight 500 |
| Phone section heading | Season Mix Regular, 32px, weight 400 | Season Mix Medium, 32px, weight 500 |
| Card heading | Season Mix Regular, 24px, weight 400 | Season Mix Medium, 23px, weight 500 |

Actual glyph-font evidence identifies both custodied Regular and Medium faces.
This is explicit authored CSS drift, not an unloaded font or frontend cache.
The agent rendered once, observed the result, and did not repair it.

Next fix: make the inspected source-role measurements part of the construction
path, with a focused offline regression for raw sibling sections. A rule loaded
in context is not proof that its required operation happened. The existing
typography gate only checks explicitly declared references; undeclared roles
remain unverified.

#### Follow-up: ingestion caused the incorrect typography authority

A read-only trace through the approved kit and its saved ingestion evidence
identified an upstream cause as well. The capture already contained rendered
headings: h1 56/400 and h2 48/400, both with line-height 1 and tracking -0.03em.
Earlier stylesheet samples named an unresolved CSS family variable and lacked
the numeric properties. `resolve_anchors` kept the first sample for each label,
discarding the later complete rendered sample. It therefore used the 32px/700
fallback, then font custody selected 500 from the available 400/500 faces.
The derived title became 23px/500. The source fragments retained their own CSS.

The normalizer stamped derived roles as evidence merely because some type
samples existed. The grammar audit likewise called them measured and instructed
the agent never to restate the theme ramp. The native brand view delivered those
incorrect values. Newly composed styles matched them, while captured sections
retained the correct original typography. Loaded Regular and Medium glyphs rule
out font download/cache failure for this case.

The local fix selects complete rendered samples ahead of incomplete/conflicting
stylesheet declarations, retains deterministic source order for equal evidence,
and does not choose by largest size. Provenance now distinguishes measured fields
from defaults and custody substitutions. The generated grammar puts measured
source component typography and responsive CSS ahead of the fallback kit ramp,
consistent with the existing shared source-format contract.

Verification: the regression first failed on the original first-sample behavior.
The final focused offline matrix passed 76 checks (six database-dependent cases
excluded). Reviewed golden changes affect provenance/confidence, not fixture token
values. Replaying this exact ingestion in memory over a read-only connection now
produces h1 56/400 and h2 48/400 with the rendered sample locators. No providers,
kit publication, page generation, service reload or database writes were used.
The already-approved kit and generated page remain unchanged. This is a producer
fix, not live quality qualification; required reference coverage, kit refresh and
native visual acceptance remain outstanding.

### 3. Interactive source was flattened before evaluating the available route

The agent inspected the procedures component, received
`controller_not_retained`, four controls and three hidden states, then authored a
static four-card replacement. It never read `web-motion-fidelity` or its rich-card
reference and never attempted the supported typed-tabs reconstruction.

The account-local custom-component registry was unavailable, but native tabs do
not require that registry. A missing captured JavaScript controller did not
establish that all supported interaction paths were unavailable. The final report
honestly names a static fallback, but the intended interaction is still absent.
The new feature image also lost the source's surrounding branded background.

Next fix: route captured state controls to the existing native-interaction
reference before choosing a static fallback; retain the source visual wrapper and
record any genuinely unsupported autoplay/transition behavior separately.

### 4. Review coverage improved without producing a quality pass

The current local document version was 10 for render, clone walk and finalization.
Desktop tiles 0–5 and phone tiles 0–7 were all shown. Tablet tiles 2 and 4–6 were
not shown. Source comparison was unavailable because its reference was 1920px
and the review render was 1440px. Typography status was `not_declared`; overall
quality remained `not_computed`.

All 27 checked images settled at each render width. No broken clones or page
console errors were reported. Those technical checks did not detect or correct
the editorial and visual defects. The final report acknowledged class collisions,
tablet logo crowding, redundant identity text and retained hero top padding.

Exact helper renders: 1440×5847, 768×7157, 375×8204. The live phone iframe's smaller
content viewport measured 356×8304, with no horizontal overflow. The prior failed
375px page was 8267px tall; this run did not meaningfully resolve the length issue.
The three product cards, static feature block and enterprise-security section
remain especially tall on phones.

The account argument is still weak: the hero and most feature text apply to many
hotel groups; account specificity is concentrated in identity and evaluation
questions. Internal qualifications such as not assuming a PMS or not being labor
scheduling became visitor-facing copy. This is not the researched account story
the requested page requires.

Next fix: distinguish evidence restrictions from finished copy; map a small number
of supported account observations to product capabilities and an appropriate
reader action. Review density and relevance, not only absence of blank space.

## Improvements and remaining qualification

The fetched target logo is outside the seller header, above the main heading.
Primary CTA labels consistently use Book a demo with the verified booking
destination. The large product screenshot uses its existing composite instead of
adding a second background frame. Original captured sections were preserved.

However, the new identity band repeats the account name and adds excessive space;
the procedures imagery loses its original background; typography still drifts;
and the account binding and interaction are missing. The shared-skill changes are
therefore useful delivery progress, not a completed quality fix.

Do the next fixes in this order: account-binding preservation; measured
source-format construction; mandatory interaction-route evaluation; then
account-argument and mobile-density review. Validate against these saved receipts
and offline regression cases before requesting another paid native test. Do not
add project-specific instructions or hand-edit this generated page to conceal the
system failures. No push or further generation was performed in this audit.
