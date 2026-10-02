---
schema_version: "1"
kind: skill
name: plan-authoring
version: v2
summary: "Write this project's plan as a document under project/, and ask the human once before pinning it as the plan."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Write the plan

Write the plan as a document under `project/`. `project/plan.md` is the usual place. Any markdown
path under `project/` is a versioned document the human can read and edit, so where you put it is
your judgement, not a rule.

Write it once — not before — the founding questions from the Stage-0 skill are answered, the ICP is
confirmed and pinned (the index card names it) and the product set is confirmed. Never write a plan
on the first turn of a project, and never one the human has not discussed with you.

The plan is the execution plan in the human's terms, as markdown: a title; the outcome; the
confirmed profile and the products, by name; the account motion (how many accounts, discovered or
imported, what tier gets deep research); the channels and sequence; who owns follow-up; what day
ninety looks like; the next three steps. Keep it under two screens. Facts about the company or
products come from the files; decisions come from `decisions.md` and the conversation.

If what you are writing is this project's plan, ask the human once whether to pin it as the plan.
On yes, put `role: plan` in its front matter and write it again. That role is what the project's
status file and the Plan tab read; nothing else marks a document as the plan.

Do not add a domain_ref for it. The card the human sees comes from the document itself.

Read the file before you rewrite it. Save with `write_file` (or `edit_file` for a small change). If
the platform answers `revision_conflict`, the human edited it since you read it: read it again,
keep their edits, and write again.

When the human changes course later — a new profile, a different channel, a different list size —
update the plan the same way and say what changed. Read the plan before proposing anything that
departs from it.
