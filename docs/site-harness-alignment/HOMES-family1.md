# Family 1 · Step 3 — one home per rule (draft for founder review)

Layers (S1): **BASE** `planning-a-page` · **CASE** six case skills (one-to-one, contact, one-to-few, general
campaign, event, product campaign; S1.2 ruled A) · **ASPECT** skills (DECISION = `decision-material`, family 1;
COPY and EVIDENCE = family 2, IMAGERY = family 3, VISUAL = family 4, REVIEW = family 5) · **MECH** mechanics
skills (`building-with-puck`, `writing-a-section`, `rebuilding-a-section`, `making-a-section-interactive`) ·
**SYS** system prompt · **HOA** Head of ABM brief template (`manual-siblings`) · **CODE** workspace/harness code.

A rule homed in a later family's aspect skill is only *placed* here; its wording is ruled with that family.

Founder review 2026-10-27: sections A and B approved.

## A. Each ruling's home

| Ruling | Home | Notes |
|---|---|---|
| R0.1 fixed set; S2 on-demand reading | SYS + CODE | The system prompt lists the skills and the reading rule (S2.2, S2.4: full read only on a new document; follow-ups read what they need); `system_prompt_with_skills` stops pasting skill content; skills middleware or an equivalent list; contract test for named paths. |
| R1 every kind | SYS | Line 1 rewritten: a seller's landing pages for every kind, not "one named account". |
| R1.1 kind by judgement, "Who this page is for" | BASE | First step of the sequence. |
| R1.2 brief opens with who the page is for | HOA | `manual-siblings` new version + Head of ABM re-mint. |
| R1.3 untagged workspace honest; context names; R1.3a/R2.5 ICP, personas and a few web searches for context | CODE + BASE + CASE (general, one-to-few) + SYS (`web_search` and `seller/` lines widen) | CODE: `site_workspace_view.py:401` stops using the title as `account_name`; `workspace.py` README wording. BASE: the agent names the page (root title, headings) for its context. |
| R1.4, R2.5, R10.1 the page kinds | BASE (list) + CASE (one entry each) | |
| R2.1, R2.3 the eight-step sequence | BASE | |
| R2.2, R2.4 case direction from Shashank's skills | CASE | |
| R3.1 length follows the decision | BASE | |
| R3.2 usual shape per case | CASE | One line per case. |
| R3.3 word budget as a planning aid | BASE | |
| R3.4 "Clear beats clever" | COPY | "Short beats complete" deleted. |
| R4.1 substance before container | BASE | |
| R4.2 decision material | DECISION (method, its own aspect skill) + CASE (how much, per case) | Ruled: own aspect skill, pointed to by one-to-one, one-to-few and contact. |
| R4.3 slot length and the reuse order | MECH (`building-with-puck` "Reuse first") + COPY (a rewritten line is not overly verbose; light rule) | |
| R4.4 swap test, feature dumping, utility test, explain before evaluating | REVIEW (checks) + BASE (explain before evaluating) | |
| R4.5 research is input; prose via the copy skill | BASE + COPY | |
| R4.6 no over-explaining; R4.7 ≤20-word paragraphs | COPY | |
| R5.1 action from the decision | BASE (step 5) + CASE (usual action) | |
| R5.2 one primary action, decision points | BASE + MECH (`building-with-puck` "Buttons and links", `writing-a-section` own header) | "the one destination" wording becomes "the primary action". |
| R5.3 secondary links by case | CASE + MECH (`menuExtra` rule) | |
| R5.4 inherited clone buttons decided on purpose | MECH (`building-with-puck` "Filling a clone") | |
| R5.5 "more than one primary offer", lean forms | REVIEW | |
| R6.1–R6.3 identity by case | CASE + MECH (header section states the options, not the 1:1 default) | |
| R6.4 no implied partnership; logo wall | IMAGERY (logo method) + EVIDENCE (relationship claims) | |
| R7.1–R7.4 shell by case | CASE + BASE (write the choice in plan.md) + MECH (header/footer section lists the options) | |
| R7.5 shell style from the seller's page | VISUAL + CODE check | |
| R8 brief weight unchanged | SYS (no change) | |
| R9.1–R9.3 build by default, one question | SYS | Turn-level, beside the edit rules. |
| R9.4 clarification tool + card | CODE | |
| R10.2 contact page presentation and gates | CASE (contact) + SYS ("never name people" gains the contact exception) | |
| R10.3 role-aimed account page | CASE (1:1) | |
| R10.4 contact mechanics | CODE | Architecture decision to bring to the founder first. |
| R11.1–R11.3 ambient video kept; embedded players removed except a short demo | IMAGERY + BASE (the remove list in structure) | |
| R11.4 video mechanics | CODE | |
| R12.1–R12.3 editing an existing page | SYS ("When you are asked to change an existing page") | |
| R13.1–R13.4 several directions | BASE | The leg wrapper (G1-03) already covers R13.1/R13.4; no duplicate. |

## B. Today's site lines: where each goes

| Row | Line (short) | Fate |
|---|---|---|
| A1-01 | "You build landing pages for one named account" | Rewrite (R1). |
| A1-02 | brief.md: the strategist's direction | Keep (SYS workspace list). |
| A1-03 | Write plan.md, message plan first | Rewrite: base skill first, then the case, then the plan. |
| A1-04 | Finish with a short report | Keep (SYS). |
| A1-05 | Never name people … never suggest a customer | Rewrite: contact exception (R10.2). |
| A1-06 | The brief sets the goal, the reader and the offer | Keep (R8). |
| A1-07 | Update plan.md first | Keep. |
| A1-08 | Change only what was asked | Keep + R12 re-aim and unclear-case rules. |
| A1-09 | Ask before adding what isn't on the page | Keep + R9 asking rule. |
| B1-01 | fetch_logo | Keep (tool). |
| D1-01…D1-02 | account-page-copy description, "A 1:1 page is written for…" | → CASE 1:1. |
| D1-03…D1-11 | the message plan block | → BASE (rewritten to the eight steps); Insight/Priorities → CASE 1:1; Proof → EVIDENCE. |
| D1-12 | What an insight is | → CASE 1:1. |
| D1-13 | The brief's proof/structure is a suggestion | Delete (duplicate of A1-06). |
| D1-14 | Remove sections that do not help (brand videos…) | → BASE, rewritten (R11: embedded players, not ambient video). |
| D1-15 | Brand section when no clone fits | → MECH (reuse order, R4.3). Duplicate of D2-01; one copy. |
| D1-16 | Five sections, ≤600 words | Delete (R3.1). |
| D1-17…D1-21 | The five-section shape | → BASE (one question per section) + CASE 1:1 (usual shape). |
| D1-22 | Every button says what happens, same link | Split: "says what happens" → COPY; "same link" → BASE primary action. |
| D1-23 | Never imply a customer; never name people | Delete (duplicate of A1-05). |
| D1-24…D1-29 | Final check (word budget, dilution, CTA competition, feature dumping, buried proposition, swap test) | → REVIEW (family 5); "audience dilution" and "swap test" become case-aware. |
| D1-30 | Keep the original wording's length | → COPY, softened to "not overly verbose" (R4.3); the six-words rule goes. |
| D2-01 | Reuse first | Keep (MECH), R4.3 order. |
| D2-02 | The home page's hero usually opens the page | → VISUAL (family 4: the centred-hero question). |
| D2-03 | Leave out clones that do not help | Merge with D1-14 into BASE; MECH keeps only the clone mechanics. |
| D2-04, D4-03 | No two sections making the same point | → BASE (one copy); REVIEW keeps the check. |
| D2-05, D2-10, D6-02 | Every button to the one destination | Rewrite to the primary action (R5.2). |
| D2-06…D2-09 | Header templates, "Prepared for", account logo | Keep the mechanics in MECH; which header for which case → CASE (R6/R7). |
| D2-11 | menuExtra only on group/segment sites | Rewrite by case (R5.3). |
| D2-12 | Plain footer unless asked | Rewrite: options in MECH, choice by case (R7). |
| D2-13 | Header, footer and destination shared by every page | Keep (MECH). |
| D3-01…D3-03 | Account logo in the header only; customer logo row | → IMAGERY (family 3) for the method; placement by case → CASE (R6). |
| D4-01, D4-02 | First screen; mobile header shows the account | → REVIEW (case-aware: only where the account is named). |
| D5-01 | Video → closest brand image | Delete the video half (R11.1). |
| D6-01, D6-03 | Own header: account logo and line; one row | Keep in MECH; account line only for cases that name the account. |
| G1-01…G1-03 | Leg wrapper | Keep (shared with the legacy agent). |
| H1-01 | brief.md | Keep. |
| H1-02 | "There is no written research for this account" | CODE rewrite (R1.3). |

## C. What becomes of today's site skills

- `account-page-copy` — **retired**; split across BASE, CASE 1:1, COPY, EVIDENCE and REVIEW as above.
- `building-with-puck` — stays (MECH); "Reuse first", "Buttons and links", the header/footer section and `menuExtra` rewritten to state options, with the case choices moved to CASE.
- `images-and-logos` — becomes the IMAGERY aspect skill (family 3).
- `page-review` — becomes the REVIEW aspect skill (family 5).
- `rebuilding-a-section` — the video line changes (R11.1).
- `writing-a-section` — the own-header bullets follow R5.2 and R6.
- `making-a-section-interactive` — no family-1 change.

## D. Packaging

Ruled 2026-10-27 (S1.2 = A): six separate case skills, each read on its own under on-demand reading (S2).
