---
schema_version: "1"
kind: skill
name: plan-authoring
version: v1
summary: "Write or update this project's plan at project/plan.md once the strategy is settled."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Write the plan

A project has one plan, `project/plan.md`, and you write it. Write it once — not before — the founding questions from the Stage-0 skill are answered, the ICP is confirmed and pinned (the index card names it) and the product set is confirmed. Never write a plan on the first turn of a project, and never write one the human has not discussed with you.

The plan is the execution plan in the human's terms, as markdown: a title; the outcome; the confirmed profile and the products, by name; the account motion (how many accounts, discovered or imported, what tier gets deep research); the channels and sequence; who owns follow-up; what day ninety looks like; the next three steps. Keep it under two screens. Facts about the company or products come from the files; decisions come from `decisions.md` and the conversation.

Read `project/plan.md` if it exists. Save with `write_file` at `project/plan.md` (or `edit_file` for a small change). If the platform answers `revision_conflict`, the human edited the plan since you read it: read it again, keep their edits, and write again.

When the human changes course later — a new profile, a different channel, a different list size — update the plan the same way and say what changed. Read `project/plan.md` before proposing anything that departs from it.
