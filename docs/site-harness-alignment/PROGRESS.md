# Site agent alignment — progress

Goal: one fixed, coherent set of skills for the **site-document design agent** (Puck sites), with the
direction-and-judgement side brought up to strength from the legacy web skills without contradictions,
and every landing-page kind handled (founder rulings 2026-10-27). Same five-step method as the scene-ad
alignment (`docs/design-harness-alignment/`), done **one family at a time**:

1. Rule ledger (exact text, one row per rule, conflicts grouped, published as a page).
2. Founder rulings, one conflict group at a time → `RULINGS.md`.
3. One home per rule (system prompt, skill, tool description or workspace file).
4. Rewrite, one topic per commit, each tagged; wording shown to the founder first; skill text stays
   uncommitted until trials.
5. Trial runs (one page per kind), compared with the 10-26 Pallet production page.

## Families
1. **The page's argument** — page kind, reader, message plan, structure and length, decision material,
   action, the account's identity, header/footer choice, the brief, asking. ← steps 1–3 done 2026-10-27 (P1–P13 ruled; homes approved in HOMES-family1.md)
2. **Wording and evidence** — sourcing, claim strength, proof, what stays off the page, voice, headlines, copy craft. ← steps 1–3 done 2026-10-28 (W1–W12 ruled; HOMES-family2.md approved)
3. **Imagery and media** — composition, choosing images, generation, logos, product screenshots, video and motion. ← steps 1–2 done 2026-10-28 (M1–M7 ruled); step 3 approved (HOMES-family3.md)
4. **Visual design and brand fidelity** — rhythm, hero, looking like the seller, type, brand-only styling, contrast. ← steps 1–2 done 2026-10-28 (V1–V6 ruled); step 3 approved (HOMES-family4.md, S4: separate page-design skill)
5. **Review** — render-and-fix rounds, what the self-check covers, the final report. ← steps 1–2 done 2026-10-28 (Q1–Q3 ruled); step 3 approved (HOMES-family5.md)
6. **Mechanics overlaps** — where the mechanics skills, the skill lines and skill delivery cut across rulings 1–5. ← steps 1–2 done 2026-10-28 (X1–X3 ruled); step 3 approved (HOMES-family6.md)

Organisation (S1, 2026-10-27): base planning skill → case direction per page kind → aspect skills (the how). Every family's rulings also record per-case direction.

## Sources — family 3
Site: D3 images-and-logos · D2 image lines · D4 image checks · D6 image/logo lines · D7 making-a-section-interactive · B1 view_asset, search_assets, generate_image ·
H4 brand/brand.md (logos, assets, motion; account logo section) · H3 clone card images · D1 "keep its layout, images and rhythm".
Legacy: L8 web-media-composition (+ asset-selection, composition-and-identity) · L9 web-product-story · L10 web-motion-fidelity (+ inventory-and-reconstruction, playback-verification, rich-card-controls) · L11 generative-imagery (ad-era).
Ploy (discussion only, S3): brand-adherence, plan-design, build-site-page image and motion parts.

## Sources — family 4
Site: A1 brand-only rule · D2 clone choice, rhythm, header over a photo, styling by hand · D4 rhythm check · D5 rebuilding fidelity · D6 writing-a-section brand and fidelity rules · B1 view_clone, compare_section · H4 brand/brand.md surfaces, type, spacing, buttons, cards, links, brand rules · H5 catalog/sections.md and index.md.
Legacy: L12 design-guidance · L13 color-and-contrast (scene era) · L14 web-source-readiness (+ authoring-vocabulary design guidance, faithful-repair) · L15 create-website (+ source-format-contract); L6 grammar audit and L1c layout rows from family 1.

## Sources — family 5
Site: A1 How to work 4–5, validate rule, edit routine · D4 page-review · D1 final-check opening · B1 render_page, validate_page · H6 harness FinishGuard and TurnLimits messages.
Legacy: L16 review-website (+ verdict-and-tools, fidelity-and-behavior); review rows from families 1–3 (L1b step 8, L2 steps 6–7, L3a, L6).
Checks sent to review by earlier rulings: R4.4, R5.5, W6.3, the W final-check rewording, M1.5, M4.6, V1.5, V4.2.

## Row schema
`id, src, loc, topic, applies, strength, text, note` (as the scene-ad ledger).
- **topic**, family 1: KIND · ARGUMENT · STRUCTURE · SUBSTANCE · ACTION · PEOPLE · IDENTITY · SHELL · PLAN · SCOPE · ASK;
  later families: EVIDENCE · COPY · IMAGERY · MOTION · LAYOUT · BRAND · REVIEW · TOOLS · READING · OUTPUT · MECHANICS.
- **applies**: always · account · contact · group · segment · event · product · new · edit · multi · no-research
- **strength**: must · must-not · should · prefer · may · default · fact

## Capture
`capture.py` builds the real site agent offline (scripted model, no spend) for a live-site workspace with
`research/claims.md`, on `design/site-harness-alignment` @ origin/main 166bafd70:
`sources/system_prompt_first_call.txt` (45,583 chars, system prompt + 7 skills), `sources/tool_schemas.json`
(19 tools, 6,360 chars), `sources/workspace_files.txt`. Legacy candidate skills copied verbatim to
`sources/legacy/` (18 skills with their references).

## Sources — family 1
Site (delivered every turn):
- [x] A1 system prompt (family-1 rules)
- [x] D1 account-page-copy · [x] D2 building-with-puck · [x] D3 images-and-logos (logo placement) · [x] D4 page-review
- [x] D5 rebuilding-a-section (video line) · [x] D6 writing-a-section (own header: account line, one button) · [x] D7 making-a-section-interactive (no family-1 rules)
- [x] B1 tool descriptions (fetch_logo placement; the rest have no family-1 rules)
- [x] H1 brief.md (`site_workspace_view.brief_text`), research/README.md (`workspace.materialize_workspace`)
- [x] G1 message wrapper (`render_leg_turn_prompt`): brief label, prompt order, multi-document assignment — added 2026-10-27
- [ ] catalog/index.md header-template wording (site-kit `catalog.ts`) — family 4

Legacy candidates (not delivered):
- [x] L1 campaign-landing-page · L1a action-selection · L1b argument-and-shell · L1c page-directions
- [x] L2 campaign-page-workflow
- [x] L3 web-account-personalization · L3a account-argument · L3b audience-modes · [~] L3c identity-and-evidence (family-1 rows only; evidence rows → family 2)
- [x] L4 web-contact-personalization (+ worked-contact)
- [x] L5 web-decision-material (+ worked-exhibit)
- [x] L6 plan-design (family-1 rows; grammar audit → family 4)

Out of scope: the Head of ABM's brief content (another agent), the exit judge.

## Sources — family 2
Site (appended to the family-1 source files): A1 (research line, seller line, tools line, "Use only the facts…", claims rule, Notes for Design) ·
B1 (fetch_page, web_search) · D1 (account-page-copy parts 2–6 wording and proof) · D2 (alt text, slot length) · D4 (words fit their space) ·
H2 research files and claims.md wording (`workspace.py`) · H3 clone cards (`site-kit/src/catalog.ts`).
Legacy: L7 conversion-copywriting · L7a copy-craft · L7b website-copy-brief · evidence rows appended to L1b, L3a, L3c, L5, L6.

## Log
- 2026-10-27: branch `design/site-harness-alignment` from origin/main 166bafd70; capture taken; family 1
  ledgered (A1, B1, D1–D6, H1 site; L1–L6 legacy) = 200 rows; 13 conflict groups P1–P13 in `issues.py`;
  page `rule-ledger.html`. P1 direction already ruled (R1). No prompt/skill/code edits.
- 2026-10-27: P1 ruled (R1.1–R1.4): judgement + honest inputs, no field; Head of ABM brief opens with who the page is for; untagged pages named for their context; kinds = one account, segment, event, product/offer (not several named accounts).
- 2026-10-27: P2–P7 ruled (see RULINGS.md). Correction: the site agent DOES receive the person's own message (last, after the brief); G1 added and P8 corrected.
- 2026-10-27: P8–P13 ruled; family 1 step 2 complete. Next: step 3 (one home per rule) for family 1.
- 2026-10-27: S1 (three layers), S2 (skills read on demand, reverses the 2026-10-08 inline ruling), S1.2 = six case skills, decision-material its own aspect skill. Founder edits folded in: R1.3a/R2.5 (ICP/personas + a few web searches without a tagged account), R4.3 softened. Family 1 step 3 approved. Next: family 2 (wording and evidence) ledger.
- 2026-10-28: family 2 ledgered (106 rows: 47 site, 59 legacy; ledger 302 rows in all); 12 conflict groups W1–W12, each with its case-specific note (S1.3). add_rows.py gained --append. Page shows family 2 open, family 1 ruled.
- 2026-10-28: W1, W2 ruled. S3: Ploy's skills are a discussion-only reference (not in the repo, never cited in a skill); brought into each later group's discussion.
- 2026-10-28: W3–W12 ruled; family 2 step 2 complete. R5.2 amended (W10.3), R5.5 form clause deferred (W10.5), W4.2 exception removed (W12).
- 2026-10-28: family 2 home table drafted (HOMES-family2.md); founder moved on to family 3 without changes to it. Family 3 ledgered (73 rows: 32 site, 41 legacy; 377 in all); 7 conflict groups M1–M7.
- 2026-10-28: M1–M7 ruled; family 3 step 2 complete; HOMES-family3.md drafted. Ploy consulted in family 3 only for M5 (founder's ask).
- 2026-10-28: founder approved the family 2 and 3 home tables ("rest sounds good", replying to the message presenting both); M2.8 narrowed to the seller's logo and product only.
- 2026-10-28: family 4 ledgered (57 rows: 29 site, 28 legacy; 436 in all); 6 conflict groups V1–V6.
- 2026-10-28: V1–V6 ruled (V3, V6: no change; V5: one reword); family 4 step 2 complete; HOMES-family4.md drafted with one open choice (separate page-design skill or fold into imagery).
- 2026-10-28: S4 ruled (page-design as its own small skill, well referenced); family 4 homes approved.
- 2026-10-28: family 5 ledgered (37 rows: 13 site, 24 legacy; 469 in all); 3 conflict groups Q1–Q3. Screenshots are already tiled (tools.py TILE_PX), so no screenshot-reading group.
- 2026-10-28: Q1–Q3 ruled; family 5 step 2 complete; HOMES-family5.md drafted.
- 2026-10-28: family 5 homes approved (founder: "lets move to the next step"). Family 6 ledgered (10 site rows; 479 in all); 3 groups X1–X3; no legacy candidates for this family.
- 2026-10-28: X1–X3 ruled; all six families through step 2; HOMES-family6.md drafted.
- 2026-10-28: family 6 homes approved; steps 1–3 complete for all six families. SKILL-SET-MAP.md compiled (step 4 blueprint); two homes corrected (R7.5 → code check; R4.4 explain-before-evaluating → decision-material).
