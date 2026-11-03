# Research quality: ledger

Everything tried, what it showed, and where it stands today. Newest at the bottom.
Accounts are called A and B (the same two in every round); job ids are in the lane database.

Last updated: 2026-11-03.

## Rounds

| Recipe | Round | Date | What changed | What it showed | Stands today |
|---|---|---|---|---|---|
| Production | Baseline | 2026-10-30 | Production rules, no personas, person jobs held back. Jobs A `8cb7b02e`, B `ee666438`. | About 8–12 searches, all in the first 5 minutes; the agent rationed against an imagined budget; hypotheses were qualification checks; its verdict (A: deprioritise) never reached the page, which showed high fit. | Reference point |
| r28 | 1 | 2026-10-30 | Prompt v28: start from four questions (pursue now, what changed, who first and what opener, what could stop a deal); background only if it explains; hypotheses in `/work/hypotheses.md`; budget paragraph; hand-over in `/outputs/account-assessment.md`. Jobs A `dc4c4c25`, B `db16e269`. | Sharper verdicts; research still narrow. | Kept |
| r29 | 2 | 2026-10-31 | Skill account-dossier v11 + prompt v29: research as a loop, follow the threads, the Exa deep call as one broad early sweep in the background, nominate the committee only after the questions are settled. Jobs A `9ccd45cd` (failed), B `a75e017a`. | About twice the searches. A failed `missing_finalize`: the model broke down into whitespace in its final write-up at ~208k tokens of context. Round 2 also saw round 1's committee. | Kept; led to a fresh workspace per round |
| r30 | 2b | 2026-10-31 | Prompt v30 + skill v12: first-principles hypotheses, settled only with specifics or after three tries; no budget counter; a learning note per batch; follow leads two steps deeper; depth-based stop rule; agnostic examples; check directory-only people. Jobs A `bf8ca1de`, B `9415cb33`. | 19–29 searches and 15–20 pages read; hypotheses settled with specifics; about a third of findings are dated, attributed quotes. Wider, not longer (~5 min of research). The page writer drifted from the research (two lines in its v2 rules). | Kept |
| r31 | 6 | 2026-10-31 | Prompt v31 + page guide v3: the researcher writes `/outputs/page-brief.md` (verdict; per section the message, why, evidence ids, do-not-say); realistic with a path to sell; the writer follows the brief; ICP check shows only unmet/unknown rows; Miscellaneous as today. Jobs A `01ad7be5`, B `4ac9152e`. | Continuity fixed: verdict leads, warnings and conditions survive, proof design carried. Repetition and length unchanged (~3,100 words; the incumbent named in ~8 of 11 sections). | Kept; writer fix next |
| — | 3 | — | Fewer, richer findings as claims. | Not run. | Dropped 2026-11-03 (replaced by the dossier trial) |
| — | 4 | — | Committee rules. | Not run. | Planned |
| — | 5 | — | Person research. | Not run. | Research rules planned; format deferred to dossiers |

## Checks and decisions

| Date | What | Result | Stands today |
|---|---|---|---|
| 2026-10-31 | Did the agents read their whole skills? | Yes. An earlier "only ~25% read" was Langfuse cutting fields at 8,000 characters. | Closed |
| 2026-11-03 | Does the Exa deep call earn its place? Counted, over rounds 2b and 6, the cited findings whose source only the deep call found. | 17 of 199 (8.5%) only from the deep call — including leadership changes, workflow-revealing job posts and a broker-authority record; 77 (39%) first surfaced by it and fetched later by the agent. It takes 43–55 s in the background and costs $0.02–0.04 of ~$0.20–0.25 Exa spend per job. | Keep, as one early background sweep |
| 2026-11-03 | Claim store vs versioned dossiers. | Claim store stays for structured facts (firmographics, contacts, scoring, Client KB, media). Research findings move to a versioned dossier with a small typed index, quote checks against source snapshots, and a personal-data index for erasure. | Pending the dossier trial |
