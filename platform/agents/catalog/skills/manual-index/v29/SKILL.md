---
schema_version: "1"
kind: skill
name: manual-index
version: v29
summary: "Manual: the map. One line per chapter, and the rule for which chapter to open."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: docs/superpowers/specs/2026-09-13-head-of-abm-operating-manual-design.md §3 (what each chapter covers) and §4 (the fifteen chapters and how they are disclosed); the summaries of the four generated chapters, read from their own front matter -->
# The manual, and how to read it

This is your operating manual. It is fifteen files. Nothing in it is preloaded except this
index, and nothing in it grants you anything: what you may call is stated once, by your
resolved resource and capability map, and that map is authoritative.

**The reading rule.** Open the chapter whose summary matches what you need, and read only
that chapter. If a word in it is new to you, read the glossary first: `.deepagent/skills/manual-glossary/v29/SKILL.md` gives
every term one line and names the chapter that defines it. Do not read the whole manual to
answer one question; you pay for every byte you open.

| Chapter | What it answers |
| --- | --- |
| `.deepagent/skills/manual-index/v29/SKILL.md` | This page. The map, and the rule for which chapter to open. |
| `.deepagent/skills/manual-turn/v29/SKILL.md` | What one turn is, what ends it, what reaches the human, and what is frozen while you work. |
| `.deepagent/skills/manual-workspace/v29/SKILL.md` | The folders and mounts, every card placed for you, and how the file tools really behave. |
| `.deepagent/skills/manual-tools/v29/SKILL.md` | Every governed tool you hold: address, effect, inputs, outputs, refusal codes, the next move for each, and what the human sees. |
| `.deepagent/skills/manual-fields/v29/SKILL.md` | The registered claim fields by family, with value type, freshness, reuse scope and gate. The families a claims read can be narrowed to. |
| `.deepagent/skills/manual-claims/v29/SKILL.md` | What a claim is: tiers, verification status, use class, outreach safety, and exactly what the account read holds back. |
| `.deepagent/skills/manual-accounts-research/v29/SKILL.md` | How an account joins a project, what its research status means, the stages a job walks, and what "settled" means. |
| `.deepagent/skills/manual-discovery/v29/SKILL.md` | How a discovery run finds companies, what verified, shown, fit and approved mean, and why nothing is ever rejected. |
| `.deepagent/skills/manual-documents-decisions/v29/SKILL.md` | Document kinds, statuses, versions and pins, and how a human's words become a durable recorded decision. |
| `.deepagent/skills/manual-gates-authority/v29/SKILL.md` | What you decide alone, what needs a human gate, what you can never do, and which rules code enforces. |
| `.deepagent/skills/manual-humans-screens/v29/SKILL.md` | What a human does on which screen, and the three channels by which you learn it happened. |
| `.deepagent/skills/manual-siblings/v29/SKILL.md` | The research, discovery, persona and design work you start but never perform, and where to read each outcome. |
| `.deepagent/skills/manual-errors/v29/SKILL.md` | Every error string a governed tool, a file tool or `finalize_turn` can hand back, and the one next move for each. |
| `.deepagent/skills/manual-limits/v29/SKILL.md` | The turn's hard numbers: rounds, supersteps, wall clock, output tokens, the two repair budgets, receipt and read bounds, quotas, retention. |
| `.deepagent/skills/manual-glossary/v29/SKILL.md` | One line per term, alphabetical, each naming the chapter that defines it. |

## Which chapter for which question

- "Can I do this, or does a human have to?" is `.deepagent/skills/manual-gates-authority/v29/SKILL.md`.
- "What does this tool take, and what can it refuse with?" is `.deepagent/skills/manual-tools/v29/SKILL.md`.
- "What does this word in a tool result mean?" is `.deepagent/skills/manual-glossary/v29/SKILL.md` first, then the chapter it names.
- "Where is that file?" is `.deepagent/skills/manual-workspace/v29/SKILL.md`.
- "Is the research done yet, and how do I check?" is `.deepagent/skills/manual-siblings/v29/SKILL.md`, then `.deepagent/skills/manual-accounts-research/v29/SKILL.md`.
- "Why did that call fail?" is `.deepagent/skills/manual-errors/v29/SKILL.md`.
