# 2026-09-19 — Head of ABM deep behavioral audit (read-only; one doc written)

Founder complaint: the live agent only asks questions (always "last three closed-won deals"),
never acts or plans proactively; my earlier draft skills "not good enough to carry forward".
Deliverable: `head-of-abm-agent-refinements/11-deep-behavioral-audit.md` (306 lines), indexed
in that folder's README. No platform code, catalog bytes, or pins touched.

## Audited state (origin/research-streaming @ 21e3ef1e9, 2026-09-19)
- Live pin head-of-abm@v57: prompt v10, stage0-interview v33 (229 lines), icp/persona/plan
  authoring v2, FIFTEEN manual-* chapters v4 (~3,100 lines; manual-tools 1,210), recipe 28,
  model x-ai/grok-4.6, caps 1800 s / 100 rounds (raised after a plan turn died at 300 s reading
  skills), L1 budget 40 KB (resolved prompt ~23.7 KB). Memory OFF (CLUE_MEMORY_ENABLED=false).
  Delegation and any web tool withheld. 15 governed tools (3 spend launches, 2 live gates + 1 dead,
  6 reads, record/propose, design leg); submit_ingestion granted but always IncompatibleRecipe
  (lane-1 walk F1). Langfuse tracing landed 09-15 (head-of-abm.turn traces).
- Aryan adopted my prompt-v5 delta + the six-question canon + qualification floor into v22..v33;
  NOT adopted: abm-craft worldview, campaign-ideation, copy-voice (scheduled), knowledge packs,
  corpus (backlog), evals (founder ruling 4, 2026-09-10: no mechanical eval gates or lint).

## Root causes (string-traced, all quoted in the doc)
1. Script literalism: v33 §2 "Ask one question at a time, in this order, skip only when already
   answered" + six fixed questions = the entire repertoire; route keys mirror the six.
2. Planning prohibited until after interview + both gates: plan-authoring "Write it once, not
   before ... Never write a plan on the first turn"; icp-authoring same; §10 "cannot start anything
   the human has not asked for on the current turn".
3. No proposal substrate: zero ABM knowledge mounted (3,100 lines platform manual vs ~12 lines ABM);
   no estimate/preview/signal-scan/cost tools; agent may not estimate spend.
4. Turn contract gravity: awaiting_input is the cheapest honest close; next_actions = "what you are
   waiting for"; every turn carries the exact-quote capture chore.
5. Identity = authority list (seven cannots + capability map's unavailable block).
6. Success defined as receipts, not client progress.
Expected path for the Home suggestion "Find and research new accounts": ~11 turns before discovery.

## Framing delivered
Six spectrums (interrogate↔propose, wait↔initiate, platform-literate↔domain-expert, script↔
repertoire, receipts↔outcomes, hard-gated↔soft-resonant); success redefined as proximity to a
running, agreed, evidence-backed program: M1 turns-to-first-credible-plan (bar: 1 turn when
onboarding files exist) … M10 trust floor (0 fabrications / 0 unauthorized spend / 0 em dashes);
14 levers ranked (L1 invert the opening into a briefing; L2 question repertoire; L3 mount an ABM
library; L4 skill families on Aryan's design pattern; L5 zero-spend proposal tools; L6 reframe
next_actions; L8 rewrite authority text as craft; L11 ungrant dead tools; L12 20-session Langfuse
review as the allowed eval).

## Gaps / owed
- No open-ended transcript corpus exists; grok reasoning invisible in UI (gateway adapter). Pull
  20 sessions from Langfuse for the baseline before setting M-targets.
- Next step is the founder's call: which levers first; skill families are to be designed against
  the spectrums, not shipped from the 08-31 drafts as-is.
