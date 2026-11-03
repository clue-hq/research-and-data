# Research quality: roadmap and where we stand

Last updated: 2026-11-03.

## Goal

Make ARV2 account research deeper and its pages better: a clear verdict, the facts that matter, no
résumé or "Wikipedia" piles, readable at campaign scale (50–60 accounts, 5+ contacts each).

## Method

- Change one thing per round, run it on the same two accounts, compare with the round before.
- Rules first (prompts, skills, page guides). Code changes only where a rule needs them.
- Each round runs on a fresh copy of the trial seller's workspace, so no round sees another's
  committee or findings.
- Every result goes in [ledger.md](ledger.md).

## Setup

- Worktree `research-trial`, local branch `trial/research-quality` (cut from `dd9a7d74a`, never
  pushed). Own `.venv` and `.env`.
- Own database `clue_research_trial` in container `clue-pg-papeete` (port 55040), cloned from
  `clue_addis-ababa` on 2026-11-03 at migration `802fa1e6c449`, with every earlier round's rows.
  File storage is still addis-ababa's `.artifacts` (the clone's rows point at those files).
- No app stack. Rounds run through `trial/worker.py` and `trial/launch.py`; output is read with
  `trial/dump_run.py` and `trial/render_output.py`.
- Customer data stays out of the repo. Research output lives in the session scratchpad.
- Production is read-only. Nothing is pushed.

## Rulings (founder)

| Date | Ruling |
|---|---|
| 2026-10-30 | Trial as a worktree that imports the platform's modules and changes only rules. |
| 2026-10-30 | Copy the seller's production context into the lane database. |
| 2026-10-30 | Baseline without personas; the ICP covers them. |
| 2026-10-30 | Account research first; person jobs held back. |
| 2026-10-31 | Hypotheses from first principles: does the product sell here, what do they use now, what is wrong with it, how could the seller prove better. Curious, not satisfied with a basic answer. |
| 2026-10-31 | Prompts stay seller- and industry-agnostic; examples use placeholder names and say they are illustrations. |
| 2026-10-31 | The researcher guides the page writer section by section. Be realistic (a competitor may have won, they may build in-house) but always suggest how to still improve the chance of selling. |
| 2026-10-31 | Miscellaneous stays as it is today; to be revisited. |
| 2026-11-03 | The claim store stays for structured facts. Research findings are to move to versioned dossiers with a small derived index — subject to the dossier trial. |
| 2026-11-03 | Round 3 (fewer, richer findings as claims) is dropped. |
| 2026-11-03 | The Exa deep call stays as one early background sweep. |

## Roadmap

| # | Stage | Status |
|---|---|---|
| 1 | Rounds 1, 2, 2b, 6 on rules | Done (see ledger) |
| 2 | Writer fix: repetition and length. Rules only, tested by rewriting pages from round 6 research. | Next |
| 3 | Dossier trial: narrative dossier with fixed headings, anchors and quoted citations; ranked key facts (~10 per account, 5–7 per person) in the page brief. Claims still imported in the background. Compared with round 6 on page quality, length, research time and nothing missing. | Planned |
| 4 | Round 4: committee rules (persona map roles, the IT slot, directory-only people). Independent of the dossier; can run with stage 3. | Planned |
| 5 | Decision point: if the dossier trial wins, write the design note and amend the "typed claim, never a free-text dossier" principle for research narrative. If not, stay on claims and reopen round 3. | Founder |
| 6 | Build, one shippable step at a time: (a) pages cite dossier anchors; (b) typed index, quote check, personal-data index, versions with erasure; (c) move the other readers (Head of ABM read tools, reconciliation, coverage), then stop importing findings as claims. Rough size 4–6 weeks. | After 5 |
| 7 | Person research on the same dossier pattern, with round 5's research rules (public footprint not résumé; LinkedIn facts cite the post; AI Ark email). | After 6 |

## Parked

- High-effort comparison run.
- Miscellaneous ruling.
- A formal seller brief / structured verdict field.
- Persona linkage in the seller's data (`lineage_unresolved`).
- Empty `evidence_span` on research claims.
- Langfuse cuts every field at 8,000 characters; never judge what the agent saw from a trace.
- Remove the leftover "also worth knowing" line from prompt v31 in the next version.
- Frontend additions ("what changed" flag, full-dossier link) need a design ruling.
