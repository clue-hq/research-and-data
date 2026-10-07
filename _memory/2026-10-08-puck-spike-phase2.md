# Puck spike phase 2 (agent on Puck) — branch spike/puck-phase1, trenton lane

Plan: docs/superpowers/plans/2026-10-07-puck-spike-phase2-agent.md. Code: trials/puck-spike/agent/.

## Done
- T1 (e253b7b73) schemas + catalog; T2 (ee2c8e934) validate/render/fetch/search/restore tools.
- T3 prompt + skills (3c2f3dffd): founder-approved 2026-10-07. Rulings: Syracuse worked example
  dropped from the copy skill (case A is Syracuse); build-skill example made up (Northwind/Lakeside);
  "one dark brand section" exception dropped (founder: drop it).
- T3 runner (2026-10-08): run_agent.py, cases.json, briefs/atrium.md (case C test brief),
  trials_puck_agent/{workspace,harness}.py. 26 Python tests + 12 TS tests green, all offline
  (scripted fake model). One live check (0.2 cents): grok-4.6 through our gateway sees an image
  inside a tool result; gateway cost lands on response_metadata["clue_cost_cents"].
- Harness rulings: create_agent + deepagents middleware (as the platform's scene solo graph), no
  subagent/todo/base prompt/summarization; ordered tool calls (proven needed by a failing test);
  finish guard; 40-call safety stop; builds start with no page.json/shell.json (write_file refuses
  to overwrite). Fixed prompt ~3.4k tokens vs ~52k platform.
- Dry assembly of all three cases from the lane DB (reads only): A 12 research blocks, 4 people,
  15 seller files, 21 clones; B 12 blocks, 3 people, 16 files, 29 clones; C research refused
  (insights_not_written; overview read separately now), 0 people.

## Known limits
- people.json lists only the research's contact references; names that appear only in text
  (e.g. other officials) are caught by the prompt rule, not the validator.
- Screenshots are capped at 2000px on the long side (a 1440 page renders ~480px wide): headlines
  and layout readable, body text not. Revisit if E1 reviews miss wrap problems.

## Next
- T4 E1 builds (A twice, B, C) — waiting on founder go (spend ~$1 per page expected).
