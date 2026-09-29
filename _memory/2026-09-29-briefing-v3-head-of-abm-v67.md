# 2026-09-29 — briefing v3 / head-of-abm v67: drop the one-person trial scope

Why: the 2026-09-29 dubai run nominated one person per account. The Head of ABM's
`account-research-briefing` v2 example brief said "select one relevant buying-committee person"
and "person-depth research for one selected person" (a trial scope); every real brief copied it,
overriding the account researcher's "aim for four or five". committee_cap stayed 5 throughout.

Change (founder-approved wording): briefing v3 = v2 with those two lines replaced ("select the
relevant buying-committee people … aim for four or five when the research supports them, never
more than the job's committee limit, and do not pad" / "for each selected person"). Prompt v18,
stage0-interview v40 = v17/v39 with only paths repointed; manual re-minted at v13 (build.py
MANUAL_VERSION/PROFILE_VERSION; tool_notes.yaml; launch tool description path). Profile v67,
registry + composer pin, tests (catalog list, registry digest 4a04d337…, pins) updated.

Also 2026-09-29: dubai `.env` LUMEN_INGESTION_DESCRIBE_MODEL back to deepseek/deepseek-v4.1-flash
(example parity). Graph limit: founder ruling 2026-09-29 — keep production at 350 rounds
(recursion fuse 2110); the trial script's 700 supersteps (~115 rounds) was never the intent.
Owed: a live research run to see 4–5 nominations per account.
