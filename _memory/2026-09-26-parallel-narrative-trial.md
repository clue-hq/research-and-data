# Parallel narrative isolated trial

- User explicitly authorized saved claim/context transmission to OpenRouter gpt-6-luna with Langfuse after the first automatic approval-review block; retry succeeded. No research providers, application DB writes, workers or publication.
- Added scripts/trial_parallel_narrative.py and focused tests. Uses existing governed model wrapper and Langfuse callbacks; no fallback. Eight concurrent section calls; native structured output. Preparation preserves full text and removes only equivalent nested mirrors. No runtime env/catalog edits.
- Initial 19-section run: 26 calls, 13 valid and six reference failures, 368.09s. Generic invalid-reference feedback was inadequate. Fixed exact bad-ID feedback and prepared per-packet reference enums; six targeted recovery calls all succeeded in 129.59s. Original requests/responses/executed scripts retained separately.
- Final assembled three pages and audit: .artifacts/parallel-narrative-trial-20260926/REVIEW.md. Winner manifest hashes prove assembled results are copied, not rewritten. All 19 revalidated offline.
- Accounting all 32 calls recovered: provider-reported upstream BYOK inference $0.47973107; router charge zero. Do not call this free. Initial usage receipts were unpriced due to generation-accounting availability delay. Both Langfuse traces confirmed; wrapper/provider generations duplicate observations, not spend.
- Target missed: 6m08 initial + 2m10 recovery, 9m33 elapsed including repair coding. Initial summary field page_ready_seconds actually reported settlement even failed pages; future runner now distinguishes those. Do not describe initial failed pages as ready.
- Content review: useful source-specific detail and seller context retained, but broad packets generate long repetitive pages. 336 selected distinct claims, 297 directly cited, 39 not directly cited (not an omission percentage). 32 missing primary coverage records, 15 nevertheless cited in same section. Coverage/advisory diagnostics are not rejection gates.
- Next: user reviews pages; improve section selection, repetition and coverage accounting, then measure again. No production activation or frontend changes. Tests: 9 focused pytest passed; ruff check passed. Full application testing not performed.

## Follow-up: remove model-generated claim ledger

- User approved replacing exhaustive model coverage dispositions with programmatic supplied-versus-cited accounting. Updated trial output v2 to section + selectionNotes + contextGaps. Notes are optional in substance (empty array valid); only meaningful selection decisions need explanation. Notes do not count as citations or mutate claim statuses.
- Updated exact prompt draft and spec; preserved previous prompt bytes in PROMPTS-v1.md. Prior paid artifacts remain unchanged. Manifest output_version prevents an old prepared request from silently running under the new schema.
- Code computes primary/context supplied, cited and not-directly-cited ID sets from intro/body/sendLine references. Uncited input is advisory, not an omission verdict, a completion gate or an automatic retry trigger.
- Offline prepared all 19 packets in .artifacts/parallel-narrative-trial-20260926/ledger-free-preview; confirmed inputs unchanged from original trial. Applied accounting to the earlier saved prose in memory only: same 336 supplied / 297 cited / 39 not directly cited. Saved separate offline diagnostic artifacts, not fake new model outputs.
- Twelve focused tests passed; ruff formatting/check passed. No paid calls, DB/fleet/provider changes or production integration. Model, concurrency, claim selection, context and prose guidance otherwise unchanged; latency improvement remains unmeasured.

## Follow-up: request-local claim aliases

- User approved short aliases in the isolated narrative trial. Contract v3 adds request-scoped C1/C2 references without changing stored claims, selection or finding text. PROMPTS-v2.md preserves the previous exact draft; PROMPTS.md is v3.
- Preparation retains canonical packet and generates a separate model packet plus saved reference-maps/<section>.json (request ID, canonical packet hash, alias-to-UUID map). Structured duplicate/conflict/supersession links use the same map. Missing linked records are reported during preparation instead of guessed; all 19 existing packets already contain those links.
- Every section now gets a per-packet native reference enum from the first call. Input/map/schema hashes and request binding checked before paid execution. Same alias in another request cannot resolve through its map. Contact and seller-document IDs unchanged.
- Responses are validated against aliases, then sentence and selection-note references are resolved and revalidated against canonical packet before saving sections/diagnostics/rendering. Original provider response retains model aliases for audit. Langfuse attempt metadata and receipts include request ID/map hash. No global lookup or approximate matching.
- Recovery preserves exact map/request identity and handles the actual final failed attempt number; it does not mint a fresh alias assignment. Full section retry behavior is otherwise unchanged; focused reference-only correction remains future work.
- 18 focused tests passed; ruff and diff checks passed. Prepared .artifacts/parallel-narrative-trial-20260926/local-reference-preview offline, round-tripped all 19 prior narratives through aliases to identical durable references and prose, and verified unchanged canonical inputs. No paid calls, workers, DB writes or production integration. Live reliability/latency improvement remains unmeasured.

## Follow-up: distinct section purpose and teaching example

- User approved clearer writing responsibilities and requested one bad/better example in the prompt. Updated PROMPTS.md to draft v4; preserved previous exact bytes in PROMPTS-v3.md. Output schema remains v3 (no contract change).
- Shared instructions distinguish overview synthesis from detailed insights, permit claim reuse with different explanation, preserve substantive public statements and necessary qualifications, and discourage repetitive setup/caveats. Added one explicitly fictional Acme scenario with a bad repeated conclusion and better fit/signal/voice treatments. The example is guidance only, never target evidence or mandatory ABM framing.
- Refined Why they fit, Buying signals and Contact insights assignments. No claim selection, metadata, model, concurrency, runtime or frontend changes.
- Offline preparation verified all 19 section requests contain the shared example; template parsing still resolves 18 assignments (research-notes shared). Prepared section-purpose-preview under the trial artifacts. No paid generation; quality and timing impact still require live comparison.

## Live follow-up: four largest account + four largest person sections

- User requested a fresh paid narrative trial and clarified four largest inputs for account plus four largest for person. Selected by rendered request characters from prompt-v4 prepared inputs; saved run-02-largest-eight separately. Eight slots, one process, no fleet. Same canonical claims/context as first run.
- Sections: account why-they-fit/how-to-approach/contact-insights/why-now; person angles/why-this-person/problem-right-now/experience-and-perspective. GPT-6-Luna served all eight, no fallback.
- All eight completed first attempt, no schema/citation repair, wall 51.375s including callbacks/section JSON storage; each call 30.6–51.3s and queues below 0.05s. This meets 60s for this subset only; offline packet preparation/review and production scheduling/persistence excluded. Full 19-section load not retested.
- All eight accounting records recovered: BYOK upstream inference $0.117255525, router charge zero. Same eight previous sections cost $0.280813335 including 15 attempts. Cloud Langfuse trace confirmed; wrapper/provider double observations are not duplicate purchases.
- Report and three partial pages at .artifacts/parallel-narrative-trial-20260926/run-02-largest-eight/REVIEW.md. Comparison.json has first-call vs current timings, counts and sizes; citation-differences.json retains records whose citation selection changed.
- Narrative words 6,963→5,564; serialized output chars 341,356→75,792, largely ledger removal. Some sections grew while becoming faster. Combined interventions/provider variance preclude attributing gains to one change.
- Targeted quality review: useful workflow/voice/project detail survives; some earlier public-statement detail omitted, some tangential third-party content and repetitive seller caveats remain. Do not call fewer citations an omission percentage or semantic completeness proof. No editorial alteration to model outputs.
- No research/provider enrichment, application DB writes or publication. No new code change/test suite needed for this run; prepared manifests/maps validated, all eight stored outputs structurally/reference valid. Further selection/prompt work and full-load acceptance still open.

## Founder rollback of section-focus prompt refinement

- User requested removal of the last section-focused narrative change. Archived exact active v4 as PROMPTS-v4.md and restored PROMPTS.md byte-for-byte from PROMPTS-v3.md (cmp verified).
- Retained request-local aliases, constrained references, programmatic citation accounting and optional selection notes. No code/schema/input selection/model/concurrency changes. Shared/section-specific focus changes and their example are reverted together.
- Clarified that ledger-removal instructions were also a model-input change since the first paid trial, besides aliases and section focus. Claim evidence and seller context were unchanged; causes of quality differences are not isolated.
- Existing paid results and v4 prepared previews remain frozen/historical, not future launch inputs. Fresh preparation reads restored v3. Verified prompt parsing and required aliases/ledger-free contract offline. No paid rerun or application mutation.

## Researcher classification guidance

- Founder approved field/category classification direction and requested thorough dossier-charter guidance. Inspected active quality revision19: both claim-ready skills v2, Finding/Entry lack field/category fields, importer hardcodes subject.research_finding. Narrative trial categories are manual overlay, not proof of researcher classification.
- Added draft shared supplement and trial/integration boundary under docs/superpowers/drafts/2026-09-26-dossier-classification/. Covers field meaning, typed values, subject/source/time distinctions, non-forced fallback, category precision, public-wording preservation, scoped field proposals, account/person section guidance, bad/better cases and correction review.
- Exact proposed system addition documented. Draft not installed: schema/import support must land with versioned resources, preserving typed values and original evidence without duplicate logical findings. Current skills/manifests remain untouched.
- This checkpoint is guidance only; actual classification trial, importer/schema changes and quality validation remain outstanding. No paid calls, DB changes or runtime activation.
