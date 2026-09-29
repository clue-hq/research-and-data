# Native website cross-run audit — 2026-09-28

Status: historical failure analysis and implementation priorities. The page-quality goal is **not achieved**. No new generation or live-page repair was performed for this audit.

## Scope and method

Read the model-completion/tool-request records, relevant returned tool evidence, saved plans, document snapshots, review receipts and rendered images for **21 turns across five design sessions**. This covers the initial account, HE Labs and named-contact pages, their repairs, the later simple-prompt page and its revision, and the latest failed validation page. It excludes the older baseline and other workspace experiments. Some trace input summaries are truncated and some intermediate tool results are not fully saved; the frozen handoffs, authoring arguments and available evidence manifests fill only the portions they actually contain. This is not a claim to possess every original provider input or tool output.

The two parallel read-only reviews covered the original account session and the HE Labs/contact sessions. The parent reviewed both later sessions, recomputed all counts, spot-checked the raw records behind the incorrect acronym, font and source-CSS findings, and inspected saved latest-run scroll captures. No new model/provider generation, network research, database query/write, ingestion, runtime restart, publication or push was performed. Saved previews establish historical output, not current browser behavior.

There are **8,970 JSONL records, 448 design model-completion/usage receipts, 1,180 requested tool calls, 34 requested preview renders and 11 requested clone reviews** in this bounded set. Recorded design-model cost is **$38.749376**, including three canceled/failed turns. This excludes Head-of-ABM cost, other provider costs and earlier experiments; it is not total project spend. Requested calls are not all proven executions. Canceled requests and successful transport envelopes containing application errors are counted separately from successful mutations when analyzing causality.

| Session / document family | Turns | Model receipts | Requested tools | Recorded design cost | Phone output, initial → last saved |
| --- | ---: | ---: | ---: | ---: | --- |
| Original account | 8 | 162 | 380 | $13.813476 | 375×7635 → 375×7986 |
| HE Labs | 5 | 91 | 246 | $7.776154 | 375×4108 → 375×3591 |
| Named contact | 5 | 103 | 255 | $8.338828 | 375×3828 after first repair → 375×3824 |
| Later simple-prompt page and revision | 2 | 58 | 187 | $5.700662 | 375×10799 → **379**×7464 for a requested 375px capture |
| Latest validation | 1 | 34 | 112 | $3.120256 | 375×19447 → 375×19352 within the run |

Page height alone is not a quality score. Here the saved copy and pictures show repeated arguments, oversized captured sections and a large footer; the measurements corroborate the user's endless-scroll complaint. These images must not be confused with the earlier manual browser measurement of approximately 19.6k pixels.

## Evidence addressing the user's complaints

### 1. The page brief was already over-prescribed before design started

Frozen handoffs appended a simple human request after an expanded strategy brief specifying header/logo treatment, pilot framing, demo destination and page structure. The latest design plan copied those choices into its requirements. The resulting page was partly optimizing an agent-authored prescription rather than choosing the smallest useful account story.

Evidence: frozen conversation histories for sessions H/B below; latest L/log line 524 contains the written plan, including the header, walk and checklist prescriptions. This is not evidence that the model never received the original request: it did.

**Implication:** improving downstream copy instructions alone cannot correct an upstream brief treated as user authority. The provenance checkpoint described below addresses this ambiguity, but its behavioral effect has not been validated in a new run.

### 2. Research was available, but grounding failed in different ways

- **Original account:** overview pages were read, but the first two runs did not read seller/product files. In a revision, “ITR” became “Marriott Instant Travel Response”; the page added rebate, response-time and product configuration/pricing assertions. The imported overview did not establish that acronym expansion, and advisory recommendations were promoted into capability promises. A subsequent turn fetched sources, recovered “Intent to Recommend” and removed the unsupported assertions. Evidence: A/run_bd532…/log lines **146,155**; corrective A/run_d1e5….
- **Initial contact page:** research pagination stopped before the named-contact/buying-committee slice. The role came primarily from the brief. The composed page exposed internal statements about imported company materials and what the memo was not. Evidence: B/run_4dcaf…/log **67,410**, plus `native-v3` research receipts.
- **Latest page:** all three overview pages and seller files for agents, inbox, operator and workflows were read. Its weak personalization therefore cannot be explained by a total lack of context. The agent added five request-path steps, retained multiple product bands, and added a six-part pilot checklist. Much of this repeats the same mechanism and could apply to many hotel operators. Evidence: L/log **91,158,197,524,712,730** and the final document.

The last saved HE Labs grounding has no citations; the contact page's single grounding citation is for its font asset. This is a missing persisted argument-to-evidence record, **not proof that no research was read**.

**Implication:** each visitor-facing claim needs its account evidence and seller capability distinguished from a proposed use case. Each section must advance a different reader decision. Contact personalization needs the relevant contact slice and permitted professional insight; inserting a person's name or turning a research disclaimer into copy is insufficient.

### 3. Reuse preserved the wrong things and discarded useful ones

The system is reusing captured HTML/CSS/media and authoring derivatives or typed components. It is **not recovering and importing the original website's React component source and JavaScript controllers**.

Initial HE Labs planned source variants, then abandoned them after inspecting approximately 201k characters of feature CSS and 190k of FAQ CSS. It kept the source FAQ questions, unslotted titles and inert controls to avoid reconstructing the stylesheet. Evidence: H/run_70d…/log **393** and trace **32–33,59–60**.

In the simple-prompt create, plan maintenance explicitly called inert tabs an acceptable first state and avoided a switcher because that resembled a prior page. In its revision a native tab reconstruction was built. The latest independent run reverted to four static blurbs plus one screenshot after inspection reported `controller_not_retained`, four buttons and three hidden frames. Evidence: S/run_b4bd…/log **864,961**; S/run_e1c…/log **317,494**; L/log **532,587,985**.

An earlier account revision also built four CSS-radio image controls (A/run_bd532…/log **164,399**), and the next user correction acknowledged that they worked. That is useful partial success. It would be inaccurate to say no interaction was ever built. The defect is incomplete verification and failure to preserve the behavior in later compositions, alongside the missing original controller and layout fidelity.

**Implication:** these were conscious fallback decisions, not merely an animation failing after otherwise correct generation. The source-preservation rule and repair ladder must preserve appearance without treating static behavior or untouched generic copy as fidelity success. Missing controller evidence should route to the interaction skill and an implemented reconstruction; a fallback must remain explicitly below the requested behavior target.

### 4. Typography and image framing were reconstructed by guesswork

The contact repairs tried a `seasonFont` family and then `var(--font-season-family)` with an Instrument Sans fallback, while reporting a Season heading match. The actual captured font was registered only in the final scoped repair. Even then new type sizes/weights were chosen independently. Evidence: B/run_8f603…/log **67,202,311**; B/run_139cec…/trace **15–19**.

The latest run had real font assets but used new 32px/500 headings alongside captured 48px/400 source headings. It also put already-composited product images inside another aurora background with padding. That produces the visible extra rim. Transparent product UI requires composition; a finished product/background image generally does not require another frame. Evidence: L/log **650,678,685,694,712,730**; saved `compose-*.html`; latest `review_1/walk_scroll_025.png` and `walk_scroll_050.png`.

The “missing text” complaint is not all absent content. The five request-path text blocks are present, but short copy is vertically centered beside much taller fixed image stages. Combined with repeated large source bands this creates unproductive whitespace. Static source reveal/hidden states are a separate problem and must not be diagnosed from this geometry alone.

**Implication:** reuse a measured type scale, loaded font face, crop, asset composition type and responsive geometry. “Use the brand font/background” is too ambiguous to enforce the intended result.

### 5. Several repair loops treated symptoms before locating the constraint

One HE Labs revision rendered five times while changing broad shared classes. The actual fixed-height hero constraint (`md:h-[692px]`) was identified later, after enlarged copy collided with the CTA at tablet width. Evidence: H/run_55d…/log **178,292,560** and H/run_7a358…/log **68,115**.

An account repair meant for the first Inbox product panel instead replaced the charcoal feature panel, requiring a second prompt naming the first panel. A shared multi-page correction was also routed into each single-document session. One canceled account run planned sibling routes but ended before its requested compose call executed; it did not create those routes. The canceled contact turn did record mutations, but current persisted cancellation/resume continuity was not queried and must not be called a confirmed persistence bug.

**Implication:** repair requests must name the actual document/page/node and expected defect. Inspect bounding boxes, winning CSS declarations and current document version before spending on replacement. Parallelism should divide independent artifacts only after routing scope is explicit.

### 6. Review success was broader than the evidence

- Full-page screenshots were often the only images viewed. A phone screenshot thousands of pixels tall is an overview, not legible inspection of every section.
- The latest run inspected only desktop strips 0/9/11 and phone strip 0 on the first render. After mutation it inspected desktop strip 9 only, with no final phone/tablet strips. The source comparison was unavailable because the reference was 1920px and the comparison render 1440px; the previous clone review was stale after the last edit. Exact replay: `native-skill-repair-validation/review-observation-replay.json`.
- Initial source tabs had zero state captures. Final HE Labs created state captures without viewing them in that turn. The contact CSS-radio switcher produced no state captures. The later simple revision saw only the default and one selected native-tab state, not all four at desktop and phone.
- At the audit baseline, `_capture_states` clicked `tabs[1]` at 1440px, silently did nothing if absent, then recorded `tab-selected` without checking selected state. `_interactive_capture_plan` scanned all pages although a render is for one active page. CSS-radio controls were not covered by this typed-component scanner. These were confirmed **runtime gaps**, not just historical model mistakes; the offline interaction checkpoint below subsequently changed them.

Evidence: `tools/web_substrate.py` around **669,9991,10084–10115**; S/run_e1c…/log **368,439**; H/run_7a358…/trace **28–32**; B/run_139cec…/trace **25–29**; L/log **847,877,916,958,971,985**.

An empty `broken_clones` list or media-readiness success does not prove meaningful content is visible. The background-only mobile Inbox panel had one ink node and was reported as fully occupied. Self-written “STRICT checked” statements are not independent acceptance.

## Why the cycle consumed time without converging

1. **Repeated broad retrieval.** The simple create made 14 clone searches. Three differently worded source queries returned the identical first 20 fragment IDs. There were 44 matches for those queries, but the audit-baseline tool capped at 20 and had no offset. This was fuzzy text matching, not a captured-origin filter: authored labels could match too. Empty queries returned eight authored derivatives in both later creates; `role=features` initially returned authored compositions while important captured bands were classified elsewhere. This increases rediscovery and selection ambiguity. The current result includes lineage, but does not rank by proven output quality. The retrieval checkpoint below addresses paging, not visual-quality ranking.
2. **Large source/context payloads.** The latest run reached 164,945 input tokens before building the page. Its compaction took 53.4 seconds and initial plan write 70.5 seconds. The simple create spent 92.3 seconds in two compactions. These are logged model-call durations, not additional wall time to add to the run total.
3. **Narrative state drift.** The original account compaction said no plan had been written after a successful plan write, and forgot relevant failure/assembly state. Reads were repeated. Evidence: A/run_0d643…/log **365,373,478,484,499,590**. Its final accumulated plan is 319 lines/28,051 characters with eight amendments, canceled sibling plans and superseded IDs/assertions. The last small copy/type request still used 24 model calls and 51 tool requests. A compact artifact/version/evidence ledger is more reliable than re-summarizing a large conversation.
4. **Repair ambiguity.** Broad prompts, wrong-node changes, typography guesses and preserved dead controls caused follow-up paid turns. More concurrent generators would amplify these mistakes.
5. **Weak stopping evidence.** The system could finish with warnings and an optimistic summary despite visible failures. Rendering and file delivery were repeatedly treated as progress toward quality without showing that the user's actual complaints had been resolved.

The 21-turn cost is historical evidence, not an estimate of future savings. No quantitative savings claim follows from a prompt change alone.

## Implementation order, tied to these failures

These are runtime/tool improvements plus focused updates to the existing skill families. Creating many more prose skills without fixing their tools would repeat the failure.

| Priority | Change in Clue | Existing skills to strengthen | Offline acceptance before a new paid run |
| --- | --- | --- | --- |
| 1 | Trustworthy interaction and review receipts: active-page scope, actual activation and state assertion, all required panel states at desktop/phone within explicit bounds, failures/omissions rather than false receipts; distinguish CSS-radio/custom/native implementations | `web-motion-fidelity`, `review-website`, source readiness | Reproduce a dead/missing control, four tabs, wrong-page component and CSS-radio example; assert selected control, correct visible image/panel, keyboard operation and scope; replay stale/missing review coverage |
| 2 | Reusable source contracts and bounded edits: real font-face origin, source type hierarchy, responsive constraints, asset already-composited vs transparent, targeted card/FAQ/CTA text replacement preserving unaffected bytes; interaction reconstruction capability | `repair-cloned-sections`, `web-product-story`, `web-media-composition`, `custom-components` where actually required | Replay the real tablet fixed-height collision and mobile-hidden product issue; verify at 767/768/769 and phone; compare type and framing against matching source widths; original assets/lineage preserved |
| 3 | Account argument and CTA contract: attributed requirement vs agent choice; relevant research pages consumed; fact/proposal/capability separated; each section earns its place; one primary action label/destination with clearly different secondary actions only when useful | `web-account-personalization`, `web-contact-personalization`, `web-decision-material`, `conversion-copywriting`, campaign workflow | Saved research cannot become unsupported promises; no internal caveats in visitor copy; account, team and person variants answer distinct decisions; source slots do not leave incompatible CTA labels or generic copy |
| 4 | Retrieval and continuity: source/origin/lineage filters, bounded pagination, compact selected-section records, current document/version and mutation outcomes across cancellation/compaction | source readiness, planning, scoped editing | More than 20 matching sections remain reachable without repeated identical queries; unchanged evidence reused; canceled/resumed turn starts from the actual persisted version; no sibling-page writes from a single-page assignment |
| 5 | One native candidate after the no-new-run restriction is lifted; inspect before fan-out | Review and account/contact families together | Full current desktop/tablet/phone readable inspection; all four panel states and keyboard behavior; loaded fonts, bounded crop and no accidental overflow; a useful, nonrepetitive evidence-backed account story and consistent action; user quality judgment |

Priority 1 restores trustworthy measurement; it does not itself make a page attractive. Priority 2 supplies capabilities the author lacked or guessed. Priority 3 turns research into a purposeful page. Priorities 1–3 must converge on one source-faithful component/story example before more page generations. These checks are acceptance evidence for this work, **not new Stage-0/readiness gates that block platform turns**.

For this target the editorial direction should be a concise account-relevant opening, one clear portfolio-operation argument, a working product demonstration supporting that argument, a useful decision section, and one justified next step. This is a revisable outline, not a universal section-count template, forced demo/pilot CTA, or permission to invent buyer-specific pain.

## Already changed locally versus still owed

The historical failures above precede these local checkpoints:

- `b6d55ef2`: bounded source CTA-label/href repair and broader semantic heading/CTA slots. Does not retrofit all older fragments or solve every card/FAQ adaptation.
- `95c6101d`: version-bound review observation ledger, stale/unseen evidence and comparison limits. It records coverage; it does not judge design or prevent unsupported agent verdicts.
- `ef7f02ec`: distinguishes agent-authored handoff choices from actual user requirements; aligns planning instructions. Offline probes did not establish a quantitative behavioral improvement.

Subsequent offline checkpoints under the same no-new-generation constraint:

- `4d7ffdc0`: active-page, bounded interaction receipts assert actual activation,
  selected panels/images and keyboard behavior, including eligible CSS-radio
  implementations at desktop/phone. Failures and omitted states stay explicit.
  This does not recover the original source controller or repair an existing page.
- `e776dda4`: paged plain-text inventory and exact text variants keep captured
  HTML/CSS/assets and existing pin state. Replayed all six eligible text targets
  in the held large feature fragment without transcribing its 201k CSS.
- `7512c94e`: the ordinary native preview caches text styles,
  boxes, media visibility and image-container geometry at 1440/768/375.
  `view("layout:<width>")` and per-node reads reuse that evidence and refuse stale
  document/page/preview iterations. Shared containers are described once. The
  source/media/product/review skills point to the same bounded diagnostic contract.

Held-artifact browser replay independently reproduced the source 48px/400 versus
authored 32px/500 desktop heading styles, authored image wrappers with 18px top /
12px side padding plus a background, and the phone source Inbox with visible
background but CSS-hidden product imagery. It served 20 existing local assets,
used no network/provider and changed no workspace artifact. This is a replay of
the saved fragments/compose call, not a current native-page acceptance test.
At that checkpoint the measurements left actual glyph-font identity, image alpha /
baked-composite classification, occlusion and aesthetic quality unverified. The
glyph-font follow-up below adds usage measurements; the other limits remain.

Those checkpoints have focused offline tests. None has yet demonstrated an
improved native Hotel Equities page. Source controller reconstruction, source-font
asset identity, asset-pixel classification and framing repair, retrieval/continuity
and native visual acceptance remain open. Copy planning and glyph measurement
have bounded follow-ups below. No migration or standalone page implementation is needed
to continue the next mechanical slice.

## Copy planning follow-up

Implemented locally in `5bddc95c`; native output remains unqualified.

Re-read the latest run's actual plan write and composition arguments, not only its
final summary. `L/log:524` drafted the hero words but described most later bands
as topics, screenshots and component choices. It retained both a five-step request
walk and a three-frame inbox stack, justifying the latter as the strongest source
exhibit. It explicitly tolerated inherited demo labels in some bands and proposed
a pilot label over a demo endpoint in others. `L/log:694,712,730` then introduced
the longer argument, source caveats and evaluation questions inside raw composition.
The current plan template still asked for a "copy angle" and said content specs
only "gesture at" the words, despite the copy skill requiring finished explanations.

The latest run did request the four seller product documents (`L/log:197`), unlike
the earliest account revisions. The retained seller files support inbox assignment,
connected systems and published package pricing; the pricing mention alone should
not be labeled invented. They do not establish the composed promise that procedures
written once per flag are automatically inherited by properties. This is a failure
to retain the distinction between documented capability and recommended application,
not evidence that no research was read. Saved local files do not reverify their
underlying public sources or prove every returned excerpt was consumed.

The bounded change replaces that vague handoff with **Adds / Words / Evidence /
Actions** in the existing section plan. Unchanged source text can be referenced
exactly; evidence is recorded once; each inherited button gets a deliberate
disposition. The shared runtime router, copy guide, campaign workflow and reviewer
use this record. There is no new artifact schema, hard readiness gate or agent.

A pre-change synthetic skill-comprehension check already produced sensible complete
copy, omitted repetitive screenshots and avoided an unjustified demo. This does
**not** demonstrate that all the old instructions were absent or that this edit
causally improves model performance. A separate post-change logistics fixture
used the explicit section records, preserved account fact boundaries, replaced
the unwanted booking action and left uninspected states unresolved. A review also
clarified active-plan amendments and truthful section status. The correction
resolves an observed planning contradiction and makes omissions reviewable.
Native generation under long context, final visitor copy and visual quality remain
unqualified; the no-new-run restriction remains in place.

## Glyph-font follow-up

The layout evidence previously exposed the computed CSS family stack, which
could not distinguish a working alias from a fallback. The ordinary preview now
adds Chromium's actual font family, PostScript name, custom-font flag and glyph
count for bounded measured text owners. It reuses the same browser page, with no
new page render or provider call. Nested component records share a measurement;
later sections are sampled before further text from the first section. Missing
protocol support, changed text, hidden owners and cap/time omissions are explicit.
The existing native `view("layout:...")` path retains document/page/iteration
freshness checks. This is evidence for diagnosis, not an automatic style repair.

Replaying the same saved source feature and authored request-walk sections with
20 existing local assets confirmed more than a CSS-name difference:

| Width | Source heading | Authored heading |
| --- | --- | --- |
| 1440 | `SeasonMix-Regular-TRIAL`, 48px / 400 | `SeasonMix-Medium-TRIAL`, 32px / 500 |
| 375 | `SeasonMix-Regular-TRIAL`, 32px / 400 | `SeasonMix-Medium-TRIAL`, 32px / 500 |

Both used custom fonts. The authored face was different even where phone sizes
matched. The font probe measured 32 distinct owners per replay, with no failed
or omitted selected probes, in 105ms desktop / 56ms phone. These local timings
are observations, not a production latency promise. The underlying layout still
has explicit text caps; this does not establish complete page coverage.
The background-only phone Inbox replay had 16 CSS-hidden captured text owners
and no visible text owner to measure. It must not be reported as a font success.

The source/product instructions now compare measured faces together with size,
weight, line-height and responsive role. Twenty focused layout/font tests cover
alias versus fallback, mixed fonts, protocol failure, replaced text, section
sampling, duplicate nested owners and time-budget omissions. Twelve skill-loading
checks pass; a separate native capture-to-view assertion confirms these receipts
are exposed and stale/wrong-page reads are refused. Browser checks use blocked
external requests and local fixtures. The held replay used no external requests.

Font names do not establish stored-file identity, variable-axis or synthetic
weight fidelity. Asset pixels/cropping, original controller reconstruction,
actual visitor copy and native visual acceptance remain outstanding. No new
Clue generation, current artifact repair or service restart occurred.

## Image composition follow-up

Re-read `L/log:450,712` and the five exact image digests in the saved request-walk
composition. The run requested explicit asset views for two of those five images;
others may also have been visible in section previews. It is not accurate to say
the agent never looked at product imagery. The composition nevertheless applied
one `.abm-shot` background and 18px top / 12px side padding to all five images
(12px / 8px on phone), despite their different layering needs.

Inspection of the five existing, digest-verified blobs shows:

| Saved image | Pixels | Fully transparent | Translucent | Visible composition |
| --- | --- | --- | --- | --- |
| Voice example | 1140×929 | 0% | 5.7506% | Product plus an existing textured brand field |
| Inbox detail | 1520×1238 | 0% | 0.1076% | Product plus an existing brand field |
| Operator/inbox | 2048×963 | 0% | 0.0140% | Product plus an existing brand field |
| Workflow overlay | 2032×1752 | 26.2996% | 9.6869% | UI layers with transparent space |
| Escalation cards | 2032×1752 | 62.1655% | 7.6429% | UI layers with transparent space |

Composition descriptions above come from viewing the pixels; percentages alone
do not establish them. All five files have non-opaque pixels, so a boolean alpha
check would incorrectly treat finished composites like product-only overlays.
The extra CSS padding exposes a second brand frame around the first three. A
blanket removal of the background would instead harm the last two. Original
source staging and edge blending still govern whether a backdrop is retained.

The scene/ad viewer already had a shared transparency inspection helper, but the
web viewer did not use it. The native web asset view now returns decoded-preview
alpha counts/bounds and an identifying hash, plus a controlled white/charcoal
comparison for non-opaque previews. Opaque previews return a text receipt without
another image. It uses the same byte read for the shown image and observations;
the original asset and document are unchanged. No new tool, generation, cropping
operation or automatic composition classifier was added.

The default asset resolver still prefers an available thumbnail. Consequently
these receipts describe the inspected preview and **do not certify unavailable
original pixels**. This audit did not establish that thumbnail quality caused the
historical double-frame error. The new comparison surfaces are inspection-only,
and alpha bounds are not suggested crop rectangles.

A read-only baseline comprehension probe already chose distinct treatments under
the existing skills. The prose update clarifies mixed classes, feathered corners,
transparent margins and the new receipts; it is not proof of a causal improvement
in agent behavior. Independent code review and a different-industry comprehension
case found no concrete blocker. Native quality acceptance remains outstanding.

Verification: 68 focused web/scene asset-view, format and skill-loading cases pass.
Two initial regression failures proved the web evidence was missing. Two old label
assertions were scoped to the metadata label so separate decoded measurements
remain truthful. Shared scene behavior is covered. Replaying the helper on all
five held blobs verified matching hashes and alpha counts, taking 24–33ms per file
locally; this is not a production latency guarantee. Ruff reports unchanged legacy
debt in the touched files and no new finding relative to HEAD; whitespace checks
pass. No live page, source asset, service or provider changed.

## Section retrieval checkpoint — offline, 2026-09-28

Re-read S/simple-create's 14 search calls and saved tool responses. Trace lines
11, 25 and 37 record the same 20 IDs for `conduit.ai`, `www.conduit.ai/ section`
and `from:https://www.conduit.ai/`. The latter is not a supported search operator;
all three are fuzzy text. Saved responses report 44 matches. A source-worded
query therefore neither paginated nor established captured origin.

The native `search_cloned_sections` now accepts `offset` and exact `page_url`,
returns `next_offset`, and describes only the returned page (still at most 20).
Exact page filtering precedes pagination, retains URL query parameters, and
keeps associated derivatives with their existing lineage/degradation fields.
Existing ranking, workspace scoping and release filtering are unchanged. No
quality score or inferred source-authenticity classification was introduced.

The registry separately caps its row projection at 200 per role selection.
Search now exposes scanned/total inventory and explicit truncated/unknown state.
`next_offset=null` ends matches in that scan; it does not waive the registry cap.
Role filtering precedes the cap, while query/page filtering follows it. This
checkpoint exposes that remaining retrieval limit, rather than removing it.
Offsets are not versioned snapshots: restart after library changes. The existing
source-readiness family documents those limits and stops retrieval once the
necessary bands have been inspected.

Offline historical-response replay used the **73 distinct rows actually exposed**
by the saved searches, not a fabricated reconstruction of all 87 registry rows.
The first page matches the saved 20 IDs exactly; two further pages expose 21
additional observed matches (20/20/1). Only 38 rows have a Conduit source URL;
three other matches arise from fuzzy text, illustrating the origin distinction.
The exact homepage filter finds 11 observed rows. The replay preserves the
document and describes each returned row once. Receipt:
`/tmp/clue-search-held-replay-20260928.json`. Missing historical rows remain
missing; these results are not an exhaustive current-inventory claim.

The old skill already advised pagination and avoiding duplicate searches; its
tool lacked pagination. A read-only baseline probe correctly refused to invent
unsupported parameters. Independent review found no blocker, and a separate
capped-inventory comprehension case distinguished query exhaustion, lineage,
unknown coverage and library changes. This supplies a missing capability;
it does not prove fewer paid calls or better website aesthetics.

Verification: 22 focused discovery/search checks and 12 skill-materialization
checks pass, including real native tool-schema invocation and read-only document
behavior. Eight new regression cases failed before implementation. The broader
reuse/repair/shell run initially had 182 passes and two wording failures: the
changed pagination-note assertion was replaced by checking that the remaining
rows are actually reachable, then passed. The other still expects the historical
phrase “never casually rewrite a working cloned section”; it fails identically
with the pre-change HEAD search method. It remains an explicit pre-existing
test issue, so the broader suite is not claimed green. Ruff adds no finding
relative to HEAD (297 existing tool-file findings; five test-file findings),
and whitespace checks pass. No live/provider generation or service change.

## Interaction continuity: historical decision versus a separate runtime defect

Follow-up at `905f8925`, still without a new generation or live-page mutation.
The distinction below changes the implementation priority: fetching scripts or
adding a motion instruction alone does not make a reusable working component.

### What the two saved runs actually did

1. The saved inspection of `frag_a0f5b8c49c2d5dce` reports four stateful controls,
   three hidden candidates and `controller_not_retained`. It explicitly records
   `basis: sanitized_html_snapshot`, `behavior_test: not_performed` and
   `relationships: not_inferred`. This is evidence that the capture lacks a
   retained controller, not evidence of tested source timing or image mapping.
   Full saved result: `.deepagent-workspace/conversation_history/`
   `dsess_2c2741c027db5344badce796469dcbd7.md:18242–18248`.
2. S/revision built a native four-panel Tabs component. Its actual tool call is
   `S/run_e1c…/log:261`; `trace:34–35` records the replacement and minted repair
   `frag_22f91fef87c52cdc`. The returned repair remained **draft, not pinned**;
   the page retained typed `abm_procedures` containing `cmp_9` (`tabs`). The saved
   result at conversation-history lines 20189–20234 and `final_web_doc.json:741`
   agree. The final report only observed default plus one additional state.
3. The latest independent run explicitly changed its plan to **static** at
   `L/log:587`. `L/log:730` supplies the static HTML/CSS; `L/trace:73,75` records
   approval and insertion of `frag_741d2e1294428ddc`. It did not pin the earlier
   native-tab repair. Its final tool call (`L/log:985`) acknowledges static output
   while claiming a broad strict check.
4. The latest log records explicit reads of planning, account, source, campaign,
   copy, product and media skills (`L/log:44,57,91,158`), but no explicit read of
   `web-motion-fidelity` or `repair-cloned-sections` before the static choice.
   This does not prove their descriptions or other injected guidance were absent.
   It does establish a missing explicit motion/reconstruction investigation in
   the saved tool path. Current motion and repair guidance permits a compact
   static fallback; requested interaction quality must remain unmet in that case.

Thus the historical regression is a **fallback/continuity problem**: a partial
native reconstruction existed on another page but was not a released reusable
fragment, and the new run independently chose static output. Do not attribute
that result to the runtime defect below.

### Offline reproduction of the reusable-fragment defect

Used the actual native author/repair tools, Rust helper render, static CSS
compiler, sanitizer, slot detector and content-addressed artifact builder.
Only registry/storage were replaced by the existing in-memory test fixture;
release and pin operations affected that fixture, not any real workspace.
Chromium blocked every browser network request. The fixture has four synthetic
text panels and uses no customer assets or model calls.

| Case | Approved platform JS present? | Observed click on second tab |
| --- | --- | --- |
| Authored typed section after repair | Yes | Selected state and visible panel both change correctly. |
| Same repaired content, released and pinned as a fragment | No | Neither selection nor visible panel changes. |
| Same pinned HTML, adding only the exact approved platform runtime for diagnosis | Yes | Selection and visible panel change correctly. |
| Two pins, adding the same approved runtime for diagnosis | Yes | Clicking the second pin changes its selected tab but the **first pin's panel**; the second pin's panel stays unchanged. |

The first defect is at serialization/render dependency boundaries:
`repair_cloned_section` renders a page and extracts only the section subtree
(`tools/web_substrate.py:7288–7330`). The runtime lives in the page head.
`page_needs_runtime` considers typed components, not Fragment content
(`crates/lumen-web/src/render.rs:209–236`). The reusable artifact therefore
retains tab markup but has no declared runtime dependency.
The saved render also loses the platform's tab base styles: authored HTML has
`.lumen-tabs-list` rules, reused HTML does not (`styles.json`).
`compile_section_css` compiles theme/utility styles, while the renderer emits
platform component CSS only for recognized component nodes. Dependency retention
must cover approved styling as well as behavior.

The second defect is an instance-identity problem. Repeated pins retain the same
internal IDs, while `initTabs` resolves panels with global
`document.getElementById` (`crates/lumen-web/src/runtime/lumen-runtime.v2.js:79`).
Adding a script to every fragment page would mask the first defect while leaving
the second, so that is not a complete repair. Raw source-script replay is also
not a supported remedy.

The current state-observation code only receives native groups from typed nodes
and additionally discovers CSS-radio groups. It does not discover native-tab
markup hidden inside Fragment leaves. This coverage gap is established by code
inspection (`web_interaction_capture.py:160–162`), not a separate browser receipt
in this replay. The next regression must include it explicitly.

Reproduction source, four rendered HTML cases, exact before/after browser
observations and checksums are saved locally under repo-root
`.local-setup/native-account-skills/trace-audit-20260928/interaction-reuse/`.
`replay.py` uses no model/API/DB writes; `result.json` contains the observations.
The initial fixture attempt used the wrong slot-manifest shape and was corrected.
The first browser launch was sandbox-denied; the authorized offline retry passed.
No product runtime or live page was modified by this audit.

### Next bounded implementation and acceptance

Before describing a reconstruction as reusable, preserve **declared approved
behavior/style dependencies and per-instance identity** through the native component
and fragment seam. Use the existing governed component representation where
possible; do not infer executable authority from arbitrary source class names or
accept foreign scripts. Verify fresh authoring, saved/reopened reuse, two copies,
editor and delivery, all four states, keyboard controls and reduced motion. The
existing observation tooling must include retained fragment behavior or report
its explicit untested status.

For this page's immediate design route, the existing typed native tabs can provide
working behavior, but their horizontal layout does not preserve the source's
two-left/two-right cards around a central image. That layout/mapping gap needs a
bounded source-faithful reconstruction in the native platform and an offline
comparison before another paid page. A static substitute remains incomplete for
the user's requested interaction. Original source timing and control-to-media
mapping must be observed or marked unresolved, never guessed from filenames.

This follow-up confirms two runtime hazards and the historical fallback path.
It does not establish a fixed component, recovered source JavaScript, improved
visitor copy, or an accepted Hotel Equities page. The next generation remains
on hold under the user's restriction.

## Native tab reuse repair checkpoint

Implemented inside the existing Clue author/repair/artifact/render path after the
offline reproduction above. This is a **tabs-only capability repair**, not a
new standalone page, another generated candidate, or a claim of visual quality.
The historical latest run's deliberate static choice remains a separate issue.

- The vocabulary repair derives an internal dependency record from the subtree
  already accepted by the engine. Sanitization and artifact reads validate the
  exact tab roots, controls, panels and ARIA relationships. Captured scripts and
  reserved renderer markers are still stripped; source class names cannot grant
  platform behavior. The model receives no dependency-descriptor argument.
- Ordinary capture payloads keep v1 content identity. A native repair is v2 and
  hashes its declared dependencies into its immutable identity. Registry reads,
  pin admission, isolation previews and export render packages preserve them.
  The explicit helper action refuses on an older helper instead of silently
  losing the newly declared behavior. No database migration is introduced.
- The renderer supplies the approved tab runtime and tab base CSS, then scopes
  declared control IDs and references to each pin. The runtime resolves panels
  inside their owning group. Two copies and nested tabs remain independent;
  stored artifacts and source originals are unchanged. Other captured controls
  do not acquire the tab controller or marquee styling merely by coexistence.
- Other built-in dependencies, external command targets and unsupported
  duplicated-container cases refuse reusable mint/render rather than claiming
  preservation. The checked typed replacement remains available on the page
  when minting is refused. Raw HTML/CSS replacement of a native artifact must
  use the checked reconstruction route; exact text/link variants retain the
  validated dependency record.
- The existing interaction capture now discovers declared native groups inside
  pinned fragments. Its existing caps and omitted-state reporting still apply.
  Inspection reports `declared_native_runtime` separately from an actual
  behavior test; a declaration alone continues to say `not_performed`.

Regression evidence uses production authoring, sanitizer, CSS compilation,
artifact and helper paths with a synthetic in-memory registry, plus a separate
real registry/read/approval/package/isolation round trip in a disposable test
database. Four states are exercised in desktop/phone capture (eight receipts),
with keyboard assertions; repeated-pin delivery also works under reduced-motion
preference. Additional cases cover nested ownership, custom spacing overrides,
captured lookalikes, unknown versions, malformed relationships and unsupported
dependencies. Browser regression requests are blocked. No provider/model call
or live workspace write was used for these checks.

The first red browser replay failed on missing flex/tab styles; a second red
case accepted an unsupported carousel as a preserved repair. Both now pass.
Independent review also found canonical command-field, CSS-specificity and
unowned-dialog-polyfill issues; those were corrected before the final tests.

Verification at this checkpoint: the Rust workspace suite, release helper build,
wasm build and handshake pass. The full agent suite returned 2,821 passed,
one skipped and five failures. Four were caused by a relative helper path in
the test invocation; their corrected absolute-path rerun passes all 31 tests in
the selected files. The remaining exact-wording assertion in
`test_web_recreate_and_repair.py::test_the_tool_docstrings_carry_the_amendment_too`
also fails at HEAD: the relevant search docstring is unchanged by this patch.
It remains explicit rather than weakening that test to declare a green suite.
The final expanded four-panel browser regression passes all five cases.

The API gate returned 2,904 passed, six skipped and six failures. Four isolation
fixtures lacked the `LoadedFragment.payload` field newly consumed by this path;
their fixtures now represent ordinary captures with no native dependencies,
without changing their font/asset assertions. The two isolation files plus new
dependency/custody tests pass **39/39** after that correction. The other two
failures are `test_agent_preview_uses_media_readiness_at_each_width`: their fake
agent lacks `web_doc`. Replaying those tests with the exact committed
`_capture_pass` method reproduces the same failure. The production method is
unchanged. These two baseline failures and the one agent wording failure remain
open; neither entire Python suite is claimed green. Targeted fatal-error lint
and whitespace checks pass. Tests used a session-created disposable database,
which was removed after verification; the live database was not migrated.

Local gate logs: `/tmp/clue-native-reuse-{cargo-tests,helper-build,wasm-build,`
`handshake,runtime,runtime-retry,four-panels,api,api-final,api-baseline}.log`.
Logs are disposable local evidence; committed tests provide the reproducible
checks. No live service restart or publication was performed.

Still owed: faithful two-left/two-right layout and actual source control/media
mapping; source motion/timing; the account argument, CTA choice, typography and
image framing on a real page; readable final phone/tablet review; and human
quality acceptance. These checks establish retained native behavior, not those
qualities. The user's no-new-generation restriction remains in force.

## Rich-card styling and conflicting authoring guidance follow-up

Continued from `060d99c8`, still without another native generation. Inspected the
held feature artifact and, separately, the public source section read-only. The
source has four rich card controls, four distinct product images and a separate
background. Clicking each live source card selected its corresponding image.
This observation establishes manual control/image mapping, not recovered React
source or measured autoplay/progress timing. The live desktop columns also have
independent card heights; one shared two-row grid is not an exact reproduction.

The existing typed tab label accepts `span[class]` runs, so number/title/body
labels do not by themselves require a new component type. However, a production
author → repair → artifact → fresh pin fixture found **custom CSS was omitted**:
`compile_section_css` sealed utilities but not accepted document custom rules.
The controls still switched, while the grid disappeared and 24px serif labels
became 16px sans-serif. The same component worked on its authoring page because
that page still supplied its custom stylesheet. This is an independently
reproduced reuse defect, not a claimed cause of the historical latest run's
explicit static-fallback choice.

The bounded repair now carries local, unlayered custom rules through the existing
artifact scoper. Review found dependencies that this scoper cannot preserve
across independently pinned sections: renamed IDs, global at-rules, layer order
and indirect keyframe names. Those refuse library minting explicitly; the checked
typed section remains on the authoring page. This does not loosen capture-script,
asset or release rules. The new rich-control reference teaches source mapping,
rich labels, hidden panels, geometry comparison and those refusal boundaries.

There was also a concrete instruction conflict. The finished Words / Evidence /
Actions handoff coexisted with authoring instructions that said copy should first
be written in markup. That guide also encouraged shortening copy regardless of
lost meaning, mandatory header actions, treating fallback theme values as brand
proof, and booking placeholders. The guide now carries resolved wording/actions
into assembly, amends the active record for necessary changes, preserves important
capability limits, permits no navigation/action, and checks source typography.
Missing booking destinations remain dependencies. These were real contradictions;
we cannot identify a single sentence as the cause of an individual model decision.

Read-only application probes used an unrelated synthetic account. Before changes,
the reviewer could produce a sensible handoff only by explicitly overruling
conflicting instructions. Afterwards it followed the finished copy, preserved a
measured 48px regular/flat treatment against 32px medium/shadow defaults, chose a
roomier source-based card instead of deleting a capability limit, and omitted an
unrequested booking header. A missing-destination case remained incomplete rather
than gaining a fake link. A separate four-state probe retained manual interaction
and reported geometry/timing/font portability limits. These are comprehension
checks, not an estimate of Clue model adherence or better generated-page quality.

Browser regression compares the actual typed render with two fresh pins at
1440/768/375 across all four states, checking layout, label typography, selected
appearance, hidden content, no horizontal overflow, arrow keys and independent
instances under reduced-motion preference. Refusal cases cover the unsupported
CSS dependencies above. All requests are blocked; registry custody is in-memory.
No live database, generation, ingestion, service restart or publication occurred.
Exact Conduit visual parity, asset-layer rendering with those source images,
source timing and a readable account-specific final page remain outstanding.

Final focused regression: **247 passed, one existing exact-docstring assertion
failed** (`test_the_tool_docstrings_carry_the_amendment_too`). Its expected search
phrase is absent from the unchanged tool docstring, as recorded at the previous
checkpoint. No assertion was removed to manufacture a green result. The new
13-case styling/refusal file passes; materialization, native behavior, campaign
shell, CSS/artifact and dependency checks are included. Fatal-error lint and
whitespace checks pass. Logs: `/tmp/clue-card-custody-final.{log,xml}`. These are
focused checks, not a rerun or a green claim for both full Python suites.

## Held-source image and font comparison

Follow-up at `c169c4c2`: compared the held public Conduit feature capture with an
offline **production author → checked repair → artifact → fresh pin → render**
path. Registry custody was in-memory. Images and fonts came from the existing
local capture store, not generated or seeded into a workspace. All browser
requests were intercepted and only local digest-addressed bytes were served.
This is a diagnostic of the native rendering path, not another model-generated
page, a deployed repair, or account-copy acceptance.

The four product layers are palette PNGs with genuine transparent pixels
(`RGBA` conversion gives alpha 0–255); roughly 30.6–69.8% of their pixels are
not fully opaque. The separate source background is 1200×1034; the four product
layers are 2032×1752. Here background plus product is the correct composition.
This differs from the latest run's *other*, already-composited screenshots: an
extension/MIME/filename alone cannot select a layering strategy.

Six source font faces were resolved from the held CSS into a temporary input
using the existing brand-font interface. Chromium reports actual
`SeasonMix-Regular-TRIAL` glyphs for both the held source heading and the native
rich label, at 24px/400 with 25.92px line height. This proves the font interface
can render those bytes; it does not prove every workspace's kit resolver has
selected the same faces. No live kit was modified.

| Viewport | Source/native grid | Measured outcome |
| --- | --- | --- |
| 1440 | Both 1160×438 | Same media bounds and left cards. Source right cards are 224.59375/205.40625px; shared-row native recipe makes both 215px. |
| 768 | Both 728×980.203125 | All four control rectangles and both visible image rectangles match. |
| 375 | Both 335×974.703125 | All four control rectangles and both visible image rectangles match; no horizontal overflow. |

All four native selections were exercised at all three widths. Each selected
exactly one panel, with the expected background/product digest pair loaded and
decoded. An initial immediate `decode()` failed for offscreen lazy images; the
diagnostic now brings the selected panel into view and waits for its actual load
before asserting readiness. This was a test-observation timing issue, not evidence
of a broken source asset. Desktop states and phone/tablet compositions were
visually inspected. Manual selection is demonstrated; the source's captured
partial progress bar was not turned into a fake timer. Autoplay and transition
timing are still not reproduced or qualified.

Pixel inspection also exposed misleading source metadata: the “response review”
alternative text belongs to a resolution-rate chart, and the “calling systems”
description belongs to an integrations marketplace image. Those visuals may
support a product explanation, but they do not independently prove a target's
outcome, installed tools or specific automation. The existing media/product
skills already require pixel inspection and claim-to-state pairing; this is an
adherence/verification case, not a reason to append another generic instruction.

The comparison narrows the next work. Native rich labels, authentic media layering
and source fonts are feasible with existing interfaces after the reuse fixes.
Exact desktop independent-column sizing remains a declared recipe gap; do not
hide it with text-specific fixed heights. A source-faithful component is also
not yet a concise account story: the captured feature grid alone is about 975px
tall on phone. Choose only product demonstrations that advance the account's
decision, then verify the entire page's readable mobile flow. Preserve the
no-new-generation boundary until the user authorizes a new candidate.

Local evidence, not committed customer artifacts:
`.local-setup/native-account-skills/source-parity/native-feature-comparison/`
contains `comparison.json`, source/native screenshots at the three widths,
four native panel screenshots per width, the rendered diagnostic HTML and
`replay.py`. The replay uses held source bytes, checked native helper operations
and no model. It deliberately does not run the application or publish a page.

## Evidence locations and run index

All paths below are relative to `subsystems/clue-design/` unless stated otherwise. `log` means `logs/run.jsonl`; line numbers above are physical JSONL lines. `trace` means `trace.jsonl`. Read the logged `write_file`/`edit_file` payloads for the plan as it existed at that turn; the session's current `workspace/plan.md` can be overwritten by later turns.

- A: `.deepagent-workspace/sessions/dsess_93439b51246755fe98c834640c0900f6/turns/`
- H: `.deepagent-workspace/sessions/dsess_72552d165df95c238e06af9f4ffa1581/turns/`
- B: `.deepagent-workspace/sessions/dsess_79eec2f19f535dc1ba8c9a4adb4af1a9/turns/`
- S: `.deepagent-workspace/sessions/dsess_2c2741c027db5344badce796469dcbd7/turns/`
- L: `.deepagent-workspace/sessions/dsess_ab7b0037ce5b5601ac94fb13f2f65055/turns/run_193b5f759ebc5b9694e8aeb34529450b/`

| Family | Exact run IDs included |
| --- | --- |
| A | `run_0d6436028cac55ae9f474fa8924bba6f`, `run_bd532e62f99458bfabe9a3071d1f32f3`, `run_d1e5ef269d6d56efab5c64c8f0913158`, `run_5011ec358e9255c4ba87622af3d2eecf`, `run_7be33c269c0450e893582ef2cbcf98e5`, `run_a15d163254da5c399728478aeacb09df`, `run_255cf71d5ad45b4db3142961b92b1c48`, `run_2a563f5d6b345f96b34fbcd57473fcce` |
| H | `run_70d203d974fc5f56a276d502d20cfa23`, `run_55d9b7ab21a1595f861863a05ba9e889`, `run_da36c9421b4c54509db70feeb01d2d85`, `run_f318e3fa252f54f4a41e583eee5b7262`, `run_7a358207c2f9575f88421061135c8853` |
| B | `run_4dcaf65dac225164aebdb2f40aeca4d3`, `run_418cfaa71c645a1296e02f8bf9944652`, `run_8f60368550e25f55ac72506329663ca3`, `run_ba694cff6a7457b9bbf2d1159f4cfaad`, `run_139cecdbca555e31a853b09da89c3c81` |
| S | `run_b4bd402ca8475c60addf2a97f0991323`, `run_e1c6758102d95db2a245a70bdafd55dc` |

Repo-root ignored tool-output indexes: `.local-setup/hotel-equities-import/{native-v3,native-account-revision,native-account-final,native-quality-batch,native-scoped-quality-batch,native-simple-prompt,native-skill-repair-validation}/`. Some early manifest status snapshots say running; terminal saved traces/finals establish the historical end state. They are not evidence of a live worker that should be restarted.

The previous detailed latest-run report remains at `docs/hotel-equities-native-run-trace-audit-2026-09-27.md`; this audit does not overwrite its existing working-tree edit. Source logs and snapshots remain local/ignored. No raw trace or customer dossier is added to durable operational memory.

## Upstream design-start guidance follow-up

The active Head-of-ABM prompt already said the first design turn starts from the
opening message. Its tool descriptor and three manual chapters still said the
user must send another message. Runtime inspection and existing database tests
confirm a captured submission is queued automatically, replay adds no duplicate,
and an opening without a captured submission queues nothing.

Manual v9 / Head-of-ABM v62 correct this contradiction without changing execution,
models, permissions, caps or the prompt. Catalog generation and hash verification
pass. The broader agent/catalog/registry suite has 418 passing tests and four
skips; one existing unrelated refusal-documentation failure was reproduced with
the previous manual inputs. Twelve runtime/design-entry DB tests and migration
up/down/up pass on a disposable database. Root `make check` stops on formatting
in an unrelated untracked research test. No global-green claim is made.

The user has now authorized one fresh native account draft. This checkpoint is
still an offline correction, not evidence that the new page is better.
