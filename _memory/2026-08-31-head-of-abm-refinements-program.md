# 2026-08-31 — Head of ABM Agent Refinements program (research + architecture, no platform code)

Founder directive: sharpen the Head of ABM agent with real ABM domain intelligence ("we don't have
the training data"), via soft-pull feasibility + multiple Opus research agents + a plan for
skills/training data/benchmarks. Hard rules pinned: agent copy may NEVER contain em dashes and must
never read AI-generated; soft guardrails only; natural tendency to ask questions and learn from the
user. All deliverables in **`head-of-abm-agent-refinements/`** (12 docs + 3 draft skills +
prompt-v5 delta, ~13k lines). Entry point: `09-skill-architecture-proposal.md` (rollout R1–R8,
founder decisions D1–D10). Nothing outside that folder changed except this note.

## What was established (verified, do not re-derive)

- **Live agent audited** from `origin/platform/comprehensive-account-contact-research`: prompt
  head-of-abm v4 (57 lines, governance only), profile v38 (27 tools, model openai/gpt-5.6-terra,
  8192 out-tokens/24 rounds/300s), skills = stage0-interview v20 + account-deep-steering v8 (which
  still speaks Sumble vocabulary → needs v9 after ARV2 lands). Gaps G1–G8 in file 01: zero ABM
  domain model, zero ideation, zero voice rules, memory substrate wired but no elicitation skill,
  no strategist evals, no corpus.
- **Six Opus agents** produced files 02/03/04/06/07/08 (each has a fetchability register).
  Standouts: ITSMA now five types (definitions book-gated → D8 buy Burgess 2025 handbook);
  417-touchpoint HockeyStack stat; tier economics + 70/25/5; Fullfunnel three dynamic lists;
  **ColdIQ pivoted agency→product "Build your Revenue Engine Inside Claude Code", thesis ≈ Clue's
  (D9 competitive session wanted)**; 46-creator source map; two-track eval design (deterministic
  gate vs judge trend, pass^k per τ-bench, 13 tasks E1–E13 extending M9.6); voice constitution
  (35 humanizer patterns + 30 StoryScope features → 48 bans + 16 habits, working linter, key
  finding: phrase-banning alone barely moves detection 95.5→93.9%).
- **Acquisition ground truth (overrides earlier assumptions):** Reddit OUT (contractual: robots
  Disallow /, .json 403 everywhere, active litigation) — human-reading only; YouTube default OFF
  (ToS) — substitute = podcast RSS transcripts (Exit Five 259 eps, GTMnow 257, Full-Funnel 223,
  The Prompt 218, verified); Substack full-text RSS + `/api/v1/archive` backfill verified; X drop
  (XCancel C&D'd 2026-08-24); LinkedIn mirror-first; **Exa origin-fetch rule R3** (Exa ToS bars
  derivative works from Exa-obtained text; Exa honors robots; real price ~$0.001/page contents —
  ARV2-sources doc line ~111 says $0.004, stale). Exa permission ask = founder decision D3.
- **Phase 1 harvest:** 6 agents, 2 waves, one day, ~3.5–4.5k records, $45–75. **Fine-tune
  rejected** (weights can't cite; skills+exemplars+caching ~$400–700/yr).
- ColdIQ blog fully open (378 posts, sitemap 6,306 URLs); clay.com sitemap 16,796 URLs;
  momentumabm.com 504 (retry); gtmnow/6sense/thecmo 403.

## Open / follow-ups

- Founder decisions D1–D10 (file 09 §6) gate corpus Phase 1; D5 seed-list pruning is the
  taste-critical one.
- Draft skills (abm-craft, campaign-ideation, copy-voice; all zero-em-dash-verified) are NOT in
  the catalog; wiring caveats in `10-draft-skills/README.md` (tools pins via build_toolbelt,
  v1-draft→v1, knowledge packs don't exist until distillation R2).
- **`.context/attachments/lxH0CD/` transcript left UNTRACKED deliberately: it contains two live
  API keys pasted in chat (Apollo line ~507, AI Ark line ~1061).** Recommend key rotation and/or
  redaction before any commit of that folder.
- Session hygiene: committed head-of-abm-agent-refinements/ + this note locally only; nothing
  pushed; no platform code touched.
