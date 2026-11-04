# Research quality: roadmap and where we stand

Last updated: 2026-11-04.

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
| 2026-11-03 | Writer fix parked; round 6 stays as it is. The page writer is revisited after the dossier settles, and then only with words-per-point guidance — no item counts, no code limits. |
| 2026-11-03 | Dossier versions: the agent commits at milestones with a one-line message; the last commit of a run is published. Saves are not versions. |
| 2026-11-03 | No code check of quoted words. Quote fidelity is the agent's job, set by prompt and skill. Code checks only the dossier's contract (headings, anchors, cited sources exist, index anchors exist). |
| 2026-11-03 | Every run researches all eleven coverage areas in the account-dossier skill, whether or not the hypotheses and four questions are already answered. The questions say where to dig deepest; they never make an area skippable. |
| 2026-11-04 | The dossier stays organised by the seller's questions, not by the display pages. From recipe 36 it has ten headings: "What changed recently" becomes "Buying signals and timing" (signals for and against buying now, dated, with what each suggests), and "How they sell and whom they serve" is added. |
| 2026-11-04 | Next work, in order: the page writer's guides, person research, and the r31 agent with the new research rules (recipe 37). The dossier platform build is not started; the evidence so far (ledger, 2026-11-04) is that the writer and the claim-path input are not what make the pages poor. |
| 2026-11-04 | Writer-guide rules are guidance in the prompt, never enforced by code. No item counts: the guides' "up to 3" per-section limits go, and a Personal angle is asked for "when the research supports one", with no number. A length per point is allowed (for example, why-they-fit about 80–90 words). |
| 2026-11-03 | No Exa Agent Ultra for now: up to $20 and ~30 min per run, about ten times a whole research job and longer than the investigation. The gain is in the agent's own digging. |

## Roadmap

| # | Stage | Status |
|---|---|---|
| 1 | Rounds 1, 2, 2b, 6 on rules | Done (see ledger) |
| 2 | Dossier trial (markdown dossier, recipes 32–36): research rules and format tested on NTG and Nav. | Done 2026-11-04. Research rules kept; the format is not taken to production for now (ledger, 2026-11-04 entries) |
| 3 | **r31 agent with the new research rules (recipe 37):** r31's JSON dossier, claim import, page brief and page writer unchanged; prompt v36 and skill v17 add only the research rules from r34–r36 (order, all eleven areas, stop when nothing new turns up, deep-call sources as evidence and dig deeper, open results about people and problems, lasting record, one caveat where it matters, research date). Run on NTG and Nav, then MODE Global. | Running since 2026-11-04 21:09 UTC |
| 4 | **Page writer guides** (contact-page, account-pages, research-page-writing), from the founder's feedback on the hand-done Illumio pages. Each point opens with the person's own words, then one line "Why it signals [seller]"; never put own wording in quotation marks (wrong/right example); translations marked "(our translation: …)"; sell honestly where the account already has part of the offer; "Why this person" without title, start date, tenure or reporting line; openers mix work and personal hooks; angles labelled Professional or Personal, each with Insight and Proof and move, a Personal angle when the research supports one; why-they-fit about 80–90 words, ICP checklist moved out of it; why-now and how-to-approach with dated events and the person's words. Guidance only, no code limits, no item counts. Tested first on the three Illumio dossiers (harness copied to `trial/pwexp/`, untracked), then on recipe 37's NTG and Nav dossiers. | Next: draft wording for founder review |
| 5 | **Committee (round 4) and person research (round 5), as one stage, committee first**, because who is chosen decides whose research is run. Committee rules live in the account agent's prompt: pick from what the seller sells, not fixed clusters (the forced systems seat is how a junior IT admin gets chosen); consider finance when the seller sells back-office work; find the main operating owner deliberately (Brian Miller appeared in one run and not the next); prefer people with a public voice and record why another was dropped. Person research: LinkedIn activity, not the profile (own posts, comments, About; exact quotes with dates); cite the post URL, the profile only for identity; no résumé findings (career is context); check what the account already has in place and whether it is already the seller's customer; confirm the current employer for anyone who moved in the past year; record what could not be found and why. | After 4 |
| 6 | Decisions outside prompts: a LinkedIn-activity tool for the research agent (without one the LinkedIn rule mostly finds nothing); automatic work-email lookup when someone joins the committee; a way for the agent to ask the workspace owner for help. | Founder, when stage 5 starts |
| 7 | Storage decision: claim store as today, claims plus a synthesis document, or the dossier platform build. Decided on the writer's results with the new guides (stage 4) across inputs. | After 4 |
| — | Separate lane: discovery picks weaker accounts (Pallet's came from discovery; Illumio's were hand-picked for strong signals). Judge new pages on Pallet's strongest account, MODE Global, as well as NTG and Nav. | Noted |

## How we find out which part is at fault (cheap, in order)

1. **Good research, the platform's writer.** Run the unchanged page writer on the hand-made Illumio
   research, on a copy, never production (it would overwrite the demo pages). If its pages are
   poor, the writer is at fault, because the research is known to be good. **Done 2026-11-04** (by
   another session, $2.90, harness in `trial/pwexp/`): all 18 pages passed the checks with no
   invented facts; short of the approved style only where its guides lack the rules. The writer and
   the claim-path input are not what make the pages poor.
2. **Agent research, pages hand-written with the founder's rules.** Write the pages by hand from an
   agent dossier (r36's or recipe 37's NTG or Nav). If the account pages come out strong, account
   research is good enough and the fix is the writer; the contact pages show how much person
   research holds them back. **Open.**
3. **Then the storage question** (stage 7). With the Illumio rules in the writer's guides, run it on
   (a) claims as today, (b) claims plus a short synthesis document (verdict, signals, obstacles),
   and (c) the dossier. If (c) clearly wins, build the dossier platform. If (b) comes close, the
   cheaper path is the claim store plus a synthesis document. **After stage 4.**

## Parked

- High-effort comparison run.
- Miscellaneous ruling.
- A formal seller brief / structured verdict field.
- Persona linkage in the seller's data (`lineage_unresolved`).
- Empty `evidence_span` on research claims.
- Langfuse cuts every field at 8,000 characters; never judge what the agent saw from a trace.
- Remove the leftover "also worth knowing" line from prompt v31 (still in v36, which is a pure port).
- Frontend additions ("what changed" flag, full-dossier link) need a design ruling.
