# 01 — Current Head of ABM agent: full audit

**Date:** 2026-08-31 · **Audited against:** `origin/platform/comprehensive-account-contact-research` (the live branch, 411+ commits ahead of main) · **Author:** platform session (Fable), from the actual catalog files, not from memory.

This is the ground-truth inventory of what the Head of ABM agent *is* today, and the precise gap between that and "the most intelligent Head of ABM agent in the world." Every other file in this folder exists to close the gaps named at the end of this one.

---

## 1. What the agent is today

The Head of ABM is the platform's main deepagent. It runs on project chat threads and is the only agent with authority to bring other agents into existence. Its identity is a sha-pinned catalog bundle:

| Piece | Live version | Size / note |
|---|---|---|
| Prompt | `prompts/head-of-abm/v4/SYSTEM.md` | **57 lines.** Pure governance. |
| Profile | `profiles/head-of-abm/v38/profile.yaml` | 27 governed tools, 2 active skills, delegation grants |
| Model | `openai/gpt-5.6-terra` | temp 0.1, 8192 max output tokens, 24 max model rounds, 300s turn timeout |
| Memory | `scoped-advisory-v1` | the Doc-M scoped-memory substrate is wired in |
| Workspace | virtual, 10MB cap, `.md/.json/.txt/.yaml` only | readable: `.deepagent, inputs, context, work, outputs`; writable: `work, outputs` |

### 1.1 The three spawn mechanisms (verified earlier on the live branch, re-confirmed in the catalog)

1. **Fleet launch (human-gated, durable):** `draft_account_research_directive` → human confirms → `launch_account_research` / `launch_selected_account_research` / `launch_contact_research`. One real research agent per account/contact on the fleet. This is the slot ARV2 is rebuilding the inside of.
2. **Delegation (agent's own discretion):** `delegation_roles: [research, content_drafter, reviewer]`, depth 1, max 6 per turn, via the framework's delegate tool. The copy agent is the `content_drafter` role (active v5 prompt), reviewer critiques, research-specialist inspects durable research views.
3. **Design leg (thread takeover):** `open_design_leg` freezes a delegation bundle and reroutes the thread to the design deepagent (role=design, v1) until `finish_design_leg`.

### 1.2 The tool surface (all 27, grouped by what they let the agent do)

- **Know:** `list_client_knowledge`, `inspect_client_claim`, `list_product_knowledge`, `inspect_product_claim`, `get_research_view`, `inspect_readiness_history`, `inspect_statement_history`, `read_account_research_run`, `read_contact_research_run`
- **Stage 0:** `start_recon`, `record_interview_answer`, `submit_onboarding_input`, `submit_ingestion`, `evaluate_stage0_readiness`, `synthesize_icps`
- **Gate-opening (human authority):** `open_product_selection_gate`, `open_icp_confirmation_gate`, `open_discovery_configuration_gate`, `open_directive_confirmation_gate`
- **Act (spend/launch):** `start_confirmed_project_run`, `draft_account_research_directive`, `launch_account_research`, `launch_selected_account_research`, `launch_contact_research`
- **Extend the platform:** `propose_field`, `propose_source`
- **Hand off:** `open_design_leg`

Note what is *absent* from this surface: no direct web access tool at profile v38 (the founder said Aryan "just gave the web access" to the deepagents — that grant is newer than v38 or rides the entity-research side; the refinement work must check the live grant at build time), no discovery search tool of its own (discovery rides runs and directives), no copy-lint tool, no exemplar-library reader.

### 1.3 The skill inventory (the whole "brain" today)

| Skill | Live | Lines | What it actually teaches |
|---|---|---|---|
| `stage0-interview` | v20 | 369 | *Procedure:* establish product/ICP truth, ask-from-gaps, route statements through governed paths, readiness, gates. Well-built, battle-hardened (20 versions). |
| `account-deep-steering` | v8 | 207 | *Procedure:* scope/confirm/launch/read research fleets; co-define the buying committee (personas → functions/levels with provider-vocabulary synonyms); non-linear conversation rules. |
| `research-task` | v4 | 40 | Delegated research-specialist charter (bounded review/verification). |
| `account-gap-research` | v3 | 57 | Old-lane gap-research procedure (speaks the retired waterfall's vocabulary; effectively quarantined-adjacent). |
| `artifact-review` | v1 | 36 | Reviewer charter: classify findings, never edit, never approve. |
| `content-exemplar` | v1 | 36 | Content-drafter charter: one exemplar, input ledger, schema/slot contract. |

Only the first two are in the Head of ABM's own profile; the rest are delegated-role charters.

### 1.4 The system prompt (v4), characterized honestly

All 57 lines are *behavioral governance*: which skill to open, preserve-exact-statements, route through governed paths, what the agent cannot confirm (product, ICP, directives, readiness, promotion, budgets), no fake agency, finalize-turn discipline. It is good governance, and it should survive. It contains **zero** lines about ABM.

---

## 2. What surrounds it (the platform context any refinement must respect)

1. **ARV2 is replacing the research lane under it.** Ratified stack: Exa (discovery + all deep research) · AI Ark (committee/identity/emails/phones, 5/5 live canary) · Apollo fallback-only · free ATS APIs (Ashby/Greenhouse/Lever) promoted to first-class source · Melissa deferred to direct-mail export · Scrapling built-but-benched (0 uses in 40 fetches in the cluehq.ai smoke test). The $0.51 smoke test (two Opus agents, 124 calls, 203 claims, 5 verified emails) is the acceptance evidence for wiring this into the Head of ABM. **Consequence:** `account-deep-steering` v8 still speaks Sumble vocabulary (`sumble_people`, "structured Sumble organization fields") and will need a v9 rewrite when ARV2's toolbelt lands. Skill refinements in this program should be written against the ARV2 vocabulary, not the retiring one.
2. **The claim discipline is the house religion.** Every fact = typed claim + verbatim quote + source URL, or an honest empty. The agent's domain skills must lean on this (evidence-anchored personalization is Clue's differentiator vs. every "AI SDR" tool) rather than fight it.
3. **Human gates are kept by founder ruling.** Approve accounts, confirm ICP/directives, launch spend. Soft guardrails elsewhere: judgment annotates, never vetoes; refusals are actionable tool messages; no raw exception kills a job.
4. **Scoped memory (Doc M) exists and is wired** (`memory_policy: scoped-advisory-v1`): five-scope preferences/behavioral learnings assembled deterministically into context. The "always learn from the user" requirement has a substrate already; what is missing is *skill-level instruction* to actively elicit, record, and apply preferences.
5. **Catalog discipline:** skills/prompts/profiles are versioned, sha-pinned markdown/yaml folders. Adding intelligence = new skill versions + a profile bump. This is exactly the "filesystem-first" pattern Anthropic's skills feature and Eve.dev use; we already live in it.
6. **Budget realities in the profile:** 8192 output tokens, 24 model rounds, 300s per turn. Domain knowledge cannot be dumped into the prompt; it must be **load-on-demand skills + workspace knowledge files**, with the prompt carrying only the always-true identity/behavior layer.
7. **The design leg is where artifacts render.** Voice/copy rules must bind the content-drafter role AND travel into the design leg's delegation bundle, or ads/mailers will regress to slop even while chat stays clean.

---

## 3. The gap analysis (what "sharpen the skill" actually means)

| # | Gap | Evidence | What closes it |
|---|---|---|---|
| G1 | **No ABM domain model.** The agent has no representation of 1:1/1:few/1:many, tiering economics, play selection, program sequencing, measurement, or maturity. | Prompt v4 + both skills contain no ABM strategy content at all. | A `head-of-abm-craft` knowledge skill + distilled knowledge packs (files 02, 03, 04 in this folder feed it). |
| G2 | **No ideation capability.** Nothing teaches campaign creativity: direct-mail concepts, LinkedIn ad angles, gifting plays, event plays, or how to propose "really cool and unique ideas" grounded in researched signals. | No skill mentions plays, channels, or creative. | A `campaign-ideation` skill with a play library keyed to signal types (the researched P1 signals are the raw material; the smoke test proved signal quality). |
| G3 | **No voice constitution.** Nothing bans AI-sounding copy or em dashes; nothing defines good cold-email/ad/letter craft. The content-drafter charter is process-only ("input ledger, one exemplar"), silent on quality. | `content-exemplar` v1, `artifact-review` v1. | A `copy-voice` skill (hard bans + positive craft + per-artifact rules) bound to head-of-abm, content_drafter, reviewer, and the design-leg bundle; plus a lint/judge in review. |
| G4 | **Question-asking exists as one line, not as craft.** Prompt v4: "Ask only the next material question… prefer one useful question over enumerating a form." Right instinct, no domain content: *which* questions a great ABM lead asks, in what order, and when to push back. | Prompt v4 §Stage 0. | The discovery-question canon (agency intake patterns from file 03) folded into stage0-interview v21 and the craft skill. |
| G5 | **Learning-from-user is substrate-only.** Memory policy is wired; no skill tells the agent to elicit preferences, confirm learnings, or adapt its ABM posture per client. | Profile v38 `memory_policy`; no skill references it. | Preference-elicitation moves in the craft skill; memory-write discipline notes. |
| G6 | **No benchmark/eval for "is this agent a good ABM strategist".** M9.6 evals cover research verification; smoke tests cover the pipeline. Nothing scores plan quality, question quality, idea quality, or copy quality. | M9.6 harness scope; `_memory` eval notes. | The eval plan in file 06 + fixtures derived from files 02/03/07. |
| G7 | **Steering skill speaks a retired stack.** `sumble_people` etc. | account-deep-steering v8 text. | v9 rewrite against ARV2 toolbelt (blocked on ARV2 build landing; write against its ratified vocabulary now). |
| G8 | **No training-data corpus.** The founder's core complaint: "we don't have the training data." Nothing in the repo holds practitioner ABM knowledge, agency playbooks, exemplar copy, or anti-slop patterns. | Repo search. | The acquisition program (files 04, 05, 08) feeding versioned knowledge packs + exemplar libraries. |

## 4. Where refinements physically land (so nothing here is hand-waving)

1. **New skills** → `platform/agents/catalog/skills/<name>/v1/SKILL.md` (frontmatter schema per `docs/agents/skill-and-profile-authoring.md`), granted in a `head-of-abm` profile v39+.
2. **Knowledge packs** → materialized read-only workspace resources (the profile's `readable_prefixes` already include `context/`); big corpus stays out of the prompt.
3. **Exemplar libraries** → same mechanism, consumed by content_drafter grants.
4. **Voice constitution** → its own skill, granted to every role that writes user-facing words + injected into the design-leg delegation bundle.
5. **Evals** → M9.6-style golden fixtures + LLM-judge rubrics; smoke-test harness already proves the run pattern.
6. **Prompt v5** → a *small* diff: keep all governance, add the identity layer ("you are a senior ABM strategist; opinionated counsel, not validation; diagnose before prescribing; no em dashes ever in user-facing copy") and the skill-routing lines for the new skills.

The proposal that assembles all of this is `09-skill-architecture-proposal.md`; the draft skill texts live in `10-draft-skills/`.
