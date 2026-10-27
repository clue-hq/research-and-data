# Family 6 · Step 3 — one home per rule (approved 2026-10-28)

Homes as before (S1): **BASE** · **REVIEW** · **MECH** (`building-with-puck`, `writing-a-section`,
`rebuilding-a-section`, `making-a-section-interactive`) · **SYS** · **CODE** (site-kit, harness, tools) · **TRIALS**.

## A. Each ruling's home

| Ruling | Home | Notes |
|---|---|---|
| X1.1 `rebuilding-a-section` "when to use" | MECH (its description) + SYS (its line in the skill list) | |
| X1.2 `writing-a-section` "when to use" | MECH (its description) + SYS (skill list) | |
| X1.3 R4.3's four steps in "Reuse first" | MECH (`building-with-puck`) | Said once; other mentions point there. |
| X1.4 "leave the point out" as the last resort | MECH (`building-with-puck`) | |
| X2.1 skill list + reading rule | SYS + CODE (`harness.system_prompt_with_skills` stops pasting; `SKILLS_STEP`/`LIVE_SKILLS_STEP` replaced; skills middleware or an equivalent list) | Contract test: every skill path named exists (S2.2). |
| X2.2 drop the new-sections condition | CODE (`harness.py` folders; `skills-e5` always listed) | |
| X2.3 keep the live-site condition | CODE (unchanged) + SYS (the interactive skill listed only on live workspaces) | |
| X2.4 "Read brief.md… open files when you need them" | SYS | Unchanged. |
| X3.1 `kit.Video` | CODE (`site-kit/src/agent-kit.tsx`, `check-section.ts`, render and page origin video serving) + MECH (`writing-a-section` kit list) | With R11.4 and M1.6. |
| X3.2 motion line follows M1.3 | MECH (`writing-a-section`) | |
| X3.3 rebuilding the seller's motion; switcher example; still state | MECH (`making-a-section-interactive`) | |
| X3.4 rebuilt sections keep their video | MECH (`rebuilding-a-section`) | Same line as R11.1/M1.2. |
| X3.5 a rebuild-with-motion trial | TRIALS (step 5) | |

## B. Today's site lines: where each goes

| Row | Line (short) | Fate |
|---|---|---|
| A1-21 | "Your skills are below this prompt… Follow them." | Replace with the S2 list (X2.1). |
| A1-22 | "Read brief.md, the research and catalog/index.md…" | Keep (X2.4). |
| D5-04 | rebuilding-a-section description "when you are asked" | Rewrite (X1.1). |
| D5-05 | What a rebuilt section is | Keep. |
| D6-11 | writing-a-section description "you have been asked" | Rewrite (X1.2). |
| D6-12 | The kit's pieces | Keep; add `kit.Video` (X3.1). |
| D6-13 | A header or footer of your own | Keep (R7). |
| D6-10 (family 4) | "Write no transition or animation of your own" | Rewrite (X3.2). |
| D7-04, D7-05 | Interactive rules; accordion example | Keep; add the seller-motion part and a switcher example (X3.3). |
| H7-01 | Conditional skill folders | CODE: drop the e5 condition, keep the live one (X2.2–X2.3). |
| D2-01 (family 1), D1-15 (family 1) | Old reuse order | Rewrite to R4.3 in `building-with-puck` (X1.3); the account-page-copy line retires. |

## C. What this does

- **MECH**: two skill descriptions rewritten; `building-with-puck` carries R4.3's order once; `writing-a-section`
  gains `kit.Video` and the M1.3 motion line; `making-a-section-interactive` gains rebuilding the seller's motion.
- **CODE**: `kit.Video` (with video serving and Safari playback); the harness lists skills instead of pasting them
  and stops gating `skills-e5`.
- **SYS**: the skill list and reading rule.
