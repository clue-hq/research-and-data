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
   action, the account's identity, header/footer choice, the brief, asking. ← step 1 done 2026-10-27
2. Wording and evidence — copy, claims, proof, numbers.
3. Imagery and media — brand images, product screenshots, generation, logos, video and motion.
4. Visual design and brand fidelity — hero, rhythm, type, source fidelity, contrast.
5. Review — the self-check after render.
6. Mechanics — only where a mechanics skill repeats or contradicts a judgement rule.

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

## Log
- 2026-10-27: branch `design/site-harness-alignment` from origin/main 166bafd70; capture taken; family 1
  ledgered (A1, B1, D1–D6, H1 site; L1–L6 legacy) = 200 rows; 13 conflict groups P1–P13 in `issues.py`;
  page `rule-ledger.html`. P1 direction already ruled (R1). No prompt/skill/code edits.
- 2026-10-27: P1 ruled (R1.1–R1.4): judgement + honest inputs, no field; Head of ABM brief opens with who the page is for; untagged pages named for their context; kinds = one account, segment, event, product/offer (not several named accounts).
- 2026-10-27: P2–P7 ruled (see RULINGS.md). Correction: the site agent DOES receive the person's own message (last, after the brief); G1 added and P8 corrected.
