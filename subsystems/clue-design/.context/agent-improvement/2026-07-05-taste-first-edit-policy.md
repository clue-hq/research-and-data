# Taste-first edit policy (v1 SHIPPED fd807be, 2026-07-05; boundary decided with user)

User direction (verbatim intent, from the accommodation-integration
discussion): no editor-side crowding hints for humans; human placement is
NOT sacred to the agent — "the agent has taste and its output has quality
when i ask the agent to make an edit on an existing design… it can happen
that the agent may move a human dragged or positioned element, its fine,
if that change results in a really good composition… let's not
overcomplicate this."

## The v1 boundary (user: "yes this is exactly what i meant")

**Slight adjustments freely; big rearrangements only with a heads-up in
the proposal.** Accept/Reject preview + undo carry the trust load, not
scope strictness. Announcement stays MANDATORY for every collateral
change (the failure mode of taste-first is silent changes, not bad taste).

## What this supersedes / keeps

- SOFTENS: the "byte-identical outside the ask" rule and "pinned geometry
  is human-owned, move ONLY when asked" (prompts.py seeded-edit rules +
  FREEHAND/PINNED block) → "the ask defines the goal; you own the
  composition. Prefer minimal changes; slight collateral adjustments
  (incl. human-placed elements) are fine when they clearly improve the
  affected composition — announce each one. Big rearrangements need a
  prominent heads-up in the proposal summary."
- KEEPS: the accommodation machinery unchanged — it is the mechanical
  FLOOR under taste (catches sub-visual facts judgment can't see:
  −0.31pt overlap accepted at 0.9). Keeps edit-scoped acceptance
  (pre-existing complaints still can't hostage a turn).
- CRITIC emphasis shift: judge whether the affected REGION is now well
  composed, not merely "ask landed without collateral damage".
- ARCHITECTURE resolved: no engine/preflight promotion — with no
  human-facing crowding hints, the loop-side channel loses nothing and
  stays the permanent home ("living spec"; revisit only if semantics
  freeze AND cleanliness alone justifies engine work).

## Change-set (SHIPPED as decided — prompt-level only; runtime suite 152→153)

1. prompts.py: reword the two policy blocks per above (prose only).
2. prompts.py critic rubric: region-composition emphasis line.
3. Tests: prompt-text assertions + one loop test that a collateral edit
   outside the named scope is not zero-applied by the gates it hits.
4. NO new machinery. NO engine. NO editor.

## Separate roadmap item (new capability, NOT part of the reword)

"Agent may ask if the need be" — a mid-turn clarifying question
("this means rearranging the header you hand-placed — go ahead?") is a
new interaction primitive (editor chat UI + runtime pause/resume).
Park until user prioritizes it. Skills/knowledge docs remain the lever
for richer taste instruction later.

## Implementation notes (fd807be)

- Announcement carrier v1: `// collateral:` / `// heads-up:` comment lines
  in the authored block — all three gate parsers ignore `//` lines, and
  run artifacts (iterations/*/dsl.lumen) preserve them. The author has NO
  separate summary channel (write_block returns only the DSL source), so
  a USER-FACING collateral summary needs the parked mid-turn-communication
  item; until then the Accept/Reject preview + accommodation payload are
  the user-visible surfaces.
- Critic limits respected: attempt_history carries one-liners, not DSL
  source, so the critic CANNOT see comment lines or diff against baseline
  — its rubric judges region composition only (worse-than-before, or
  rearrangement beyond the ask); unannounced-change enforcement stays
  author-side prose. No browser e2e run per user instruction ("take a
  pause") — behavior evidence will come from the user's own use.
