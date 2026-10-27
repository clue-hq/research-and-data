# 2026-10-27 — Site agent alignment, family 1 (the page's argument)

Branch `design/site-harness-alignment` (from origin/main 166bafd70), trenton lane. Local commits only, not pushed.
Records: `docs/site-harness-alignment/` — PROGRESS.md (method, families, sources), RULINGS.md (all rulings),
ledger/*.jsonl (203 rows), issues.py → issues.json (P1–P13), rule-ledger.html (published privately:
https://claude.ai/artifact/VizVbyBSSgA3co6W6jbudY), capture.py (offline capture of the real site agent's
first-call system prompt + tools, scripted model, no spend).

Method (founder, mirrors the scene-ad alignment): 1 ledger → 2 rulings one group at a time → 3 one home per
rule → 4 rewrite one topic per commit, wording shown first, skill text uncommitted until trials → 5 trials.
Done family by family: 1 argument (done steps 1–2) · 2 wording+evidence · 3 imagery+media · 4 visual design ·
5 review · 6 mechanics overlaps.

Family 1 rulings in short (full text in RULINGS.md): fixed skill set (R0.1); every page kind — one account,
one-to-few (brief only, no account set tagged), general campaign, event, product campaign, and contact pages
(R1.x, R2.5, R10.x); kind decided by the agent's judgement, first plan line "Who this page is for"; untagged
pages named for their context; base skill `planning-a-page` + case skills built from Shashank's legacy skills
(R2.x); length follows the decision, no 5-section/600-word cap (R3.x); substance before container, prefer clone
slots or rebuilt clone, no over-explaining, ≤20-word paragraphs (R4.x); action from the decision, one primary
action, secondary links by case (R5.x); identity by case (R6.x); shell by case, CSS style copied from the
seller's landing page (R7.x); brief weight unchanged (R8); build by default, one question only when no default
(R9.x); keep ambient video, remove embedded players except a short demo (R11.x); small edits stay small, re-aim
only after confirmation, unclear → edit then ask (R12.x); several directions = separate documents (R13.x).

Correction found mid-session: the site agent DOES receive the person's own message (last, after the brief) via
`render_leg_turn_prompt` (subsystems/design/clue_design/leg_context.py; lumen_api/main.py:11698).

Mechanics follow-ups recorded (not started): untagged-page workspace wording + doc naming; Head of ABM brief
template (manual-siblings new version + re-mint); site clarification tool + chat card; contact-page mechanics
(tag, contact research reads, identity/use gates — architecture decision to bring to founder); header/footer
style check (R7.5); video in clone cards, rebuilt sections, Safari range requests.

Next: family 1 step 3 (one home per rule), then family 2 ledger.
Uncommitted elsewhere in trenton: docs/superpowers/specs/2026-10-27-site-agent-judgement-skills-reconciliation.md
(rough first-pass notes, superseded by the ledger).
