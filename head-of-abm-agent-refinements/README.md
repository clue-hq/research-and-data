# Head of ABM Agent Refinements

**Created 2026-08-31.** The complete program for turning the platform's Head of ABM deepagent from a well-governed shell into a genuinely expert ABM strategist: the audit of what exists, six deep-research briefs produced by parallel Opus agents (hundreds of live fetches, everything cited), the soft-pull feasibility verdict on every data source the founder named, the training-data acquisition plan, the proposed skill architecture, and ready-to-review draft skills.

**Start here → `09-skill-architecture-proposal.md`** (the synthesis + rollout plan + the 10 founder decisions), then dip into the research files as needed.

| File | What it is | Size |
|---|---|---|
| `01-current-agent-audit.md` | Ground truth on today's agent (prompt v4, profile v38, six skills, the 8 gaps G1–G8), audited from the live branch's catalog | audit |
| `02-what-good-abm-looks-like.md` | The practitioner canon: ITSMA's five types, tier economics, the 417-touchpoint reality, ~100 numbered case studies, failure modes, how great ABM leads think | 2,512 lines |
| `03-agency-playbooks-coldiq.md` | ColdIQ teardown (incl. their pivot to a product with Clue's thesis) + Fullfunnel, Scrappy ABM, Growth Engine X and the cross-agency client-conversation patterns | 1,541 lines |
| `04-creator-landscape-and-source-map.md` | 46 verified creators/orgs, the top-25 canon, per-platform acquisition routes with observed HTTP results, 43-domain fetchability register | 1,257 lines |
| `05-soft-pull-feasibility.md` | The consolidated "what can we actually grab" verdict: wave-1 probes + wave-2 corrections (Reddit out, YouTube off, Substack/podcast-RSS in, origin-fetch rule) | register |
| `06-agent-craft-and-benchmarks.md` | Anthropic/Cursor/Devin/Karpathy-grounded design principles, the two-track eval architecture, pass^k, 13 concrete eval tasks extending M9.6 | 2,743 lines |
| `07-voice-and-anti-slop.md` | The evidence base for the voice constitution: all 35 humanizer patterns, all 30 StoryScope features, 48 banned patterns + 16 habits, linter-validated GOOD/BAD examples per artifact | 2,527 lines |
| `08-training-data-acquisition-plan.md` | The fetch-fleet design: Phase 1 = one day, 6 agents, ~4,000 records, $45–75; corpus format; distillation pipeline; fine-tune rejected with reasons; legal register | 1,113 lines |
| `09-skill-architecture-proposal.md` | **The synthesis**: target architecture, the three new skills, eval gate, rollout R1–R8, founder decisions D1–D10 | proposal |
| `10-draft-skills/` | Ready-to-review drafts: `abm-craft`, `campaign-ideation`, `copy-voice` (all verified zero em dashes) + the prompt v5 delta + wiring caveats | drafts |

## The five headlines

1. **The gap is content, not machinery.** The catalog, memory substrate, delegation, gates, and eval harness all exist; the agent has simply never been given ABM knowledge, ideation craft, or a voice. Three skills + two knowledge packs + a 20-line prompt delta close it (file 09).
2. **The training data is fetchable for pocket change, on open surfaces.** LinkedIn and X are walled but the same practitioners publish everything on newsletters, blogs, and podcast feeds with transcripts; Phase 1 harvests ~4,000 records in a day for under $75. Reddit is out on legal grounds, YouTube defaults off, and the Exa origin-fetch rule keeps everything clean (files 04, 05, 08).
3. **ColdIQ pivoted from agency to product, onto Clue's thesis** ("Build your Revenue Engine Inside Claude Code"). Their published playbooks are simultaneously our best training data and a competitive siren (file 03, decision D9).
4. **Fine-tuning is rejected.** Weights can't cite, and citation is the product. Versioned skills + exemplar libraries + prompt caching win on cost, maintainability, and model-upgrade resilience (file 08).
5. **The eval bar is defined before the skills ship:** deterministic release gates (0 authority violations, 0 injections honored, 0 em dashes), pass^k reliability, and an originality test where the skilled agent must beat the unskilled baseline in ≥70% of blind pairings or the catalog is decorative (file 06).

## What happens next (short version of file 09 §5)

R1 corpus harvest (1 day, needs decisions D1–D5) → R2 distill packs → R3 land copy-voice + lint → R4 land the two strategy skills + prompt v5 + profile v39 → R5 eval suite with a real exit code → R6 stage0 question-canon delta → R7 account-deep-steering v9 (waits for ARV2) → R8 standing freshness.
