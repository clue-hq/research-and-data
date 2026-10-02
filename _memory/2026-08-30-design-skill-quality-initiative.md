# 2026-08-30 — Design skill-quality initiative: four sessions, COMPLETE

## What and why
Founder session (all day, chat-driven): the design deepagent had the mechanical
power to customize cloned landing pages (verified: RemoveNode/MoveNode/
SetNodeProps-with-slots all exist — zero new mechanisms needed) but none of the
JUDGMENT — its whole landing-page strategy was a 43-line knowledge doc. The
founder shared four Ploy skills (ploy-inspiration/: copywrite,
campaign-landing-page, build-site-page, redactor-and-code) plus a CRO operating
model and a component-derivation transcript as thought-process references, and
ran four review-gated authoring sessions. Protocol per session (followed
exactly): read Ploy's file + web research + our substrate → present substance
in chat → founder approves → write → wire prompts → focused tests → commit.

## Shipped (all in knowledge_docs/skills/, wired in prompts_web.py)
1. `campaign-landing-page` (86cf4ff5b) — strategy: argument-first, the brief
   (user material trusted as-is, assume-and-state), awareness stages, THE SHELL
   JUDGMENT (three questions + trust question; per-page reasoning, explicitly
   never a mechanical gate; ABM pages decided fresh each time — founder ruling),
   nine argument patterns w/ failure modes, never-invent-evidence, sections
   derived from the argument in our real verbs.
2. `conversion-copywriting` (285bcacca) — language: reader test, claim ladder +
   modal verbs, proof attribution, receipt CTAs (+first-person finding),
   copy-through-slots (match captured geometry; escalate, never cram), tone
   hierarchy: brand VOICE GUIDE when kit carries one (founder's planned
   ingestion feature — forward-compatible line) > brand card+anchor > clone's
   own copy.
3. `edit-website` upgraded 91→~240 lines (e75c1a5e7) — invested-state/
   blast-radius spine; clone-editing ladder (slot rebind via set_node_props
   FULL kind payload → repair → replace; never retype); reuse ladder;
   narrative integration; compose-new-section sequence from the founder's Ploy
   transcript (grammar extraction → ONE structural ancestor → surface
   hierarchy → density match → logo-off acid test); blast-radius reporting.
4. `repair-cloned-sections` NEW (48fd94f9f) — returning-visitor bar,
   read-before-repairing (lineage: pin existing released repair, don't mint
   duplicates), BEHAVIOR INVENTORY with rung ladder per behavior,
   ugly-is-not-wrong, repair-scope contract, release honesty + blast radius.

All four: judgment only, zero gates (founder law), zero seller names, zero new
mechanisms. Stack restarted on the new code (all five processes UP via
scripts/dev_stack.sh status).

## Founder rulings captured today
- Shell stripping is CONDITIONAL (three-gate + trust question), agent-decided
  via skills, NEVER mechanical/deterministic; F4's stripped-shell ABM
  capability stays as-is; nothing hard-fixed either way.
- Analytics/conversion events: explicitly deferred ("we will come to that
  later") — no tracking machinery in any skill.
- Future: brand-voice style-guide .md ingested with brand kits (a file, not a
  claim) — conversion-copywriting already points at it as top tone authority.

## Open threads
- FORM substrate: campaign pages need a working form (visual = solved via
  kit-derived composition; submission capture + where leads land = undecided;
  my suggestion on the table: into our own accounts/contacts spine).
- The natural next test: a real campaign-customization run on the Stripe clone
  (add/delete/rewrite/derive) exercising all four skills.
- Draft campaign shells + draft repair frag_9885a5184cb17e52 still awaiting
  release decisions; born-released autonomy change approved-in-principle but
  unimplemented.
- Prior session's context: _memory/2026-08-29-session-close-clone-run-success.md.
