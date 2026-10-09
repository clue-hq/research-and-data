# Skill and prompt changes, with the failing case behind each

Not loaded into the agent. One line per rule change (the lean rule: a rule enters only when a run
fails without it).

- 2026-10-08 · system prompt, edits: "If the request names something that is not on the page, say
  so and ask before adding anything." Failing case: a3 edit 7 (added a four-card section for cards
  that did not exist). Fixed in E2b edit 7.
- 2026-10-08 · account-page-copy, part 3: "The brief may suggest a proof or a structure. Treat it
  as a suggestion…" Failing cases: a1, a2, a3 builds (followed the brief's Nightingale suggestion;
  never searched Garner's site; the skill's fit check was skipped).
- 2026-10-08 · account-page-copy, part 5: "Say whose result it is in the kicker or the source
  line; keep the heading about the result." Failing cases: a3 edit 2, E2b ("Another employer's
  result — not SCSD's" as the proof heading).
- 2026-10-08 · page-review and system prompt step 5: render again until the review passes, up to
  3 renders in all (was: once more at most). Failing case: b1 (a known orphan in the hero headline
  shipped after the one allowed re-render).
- 2026-10-08 · new skill rebuilding-a-section (skills-e5, founder-approved), for the seller
  component library spike. Written before a run: the task (rebuild a clone as a component) had no
  skill at all.
- 2026-10-08 · writing-a-section, kit list: `kit.Image` with `fit="fill"` for a background photo;
  rules: surfaces may also come from `bg-surface-<role>` + `text-on-surface-<role>` for panels
  edge to edge. Failing cases (seen before the run, in the originals): Garner's hero (text over a
  full-bleed video) and closing panels (two panels edge to edge) could not be expressed with
  `kit.Shell` and the fixed `kit.Image`.
- 2026-10-08 · writing-a-section, kit list: each piece shown with its exact props (`label` for the
  button's words, `src` for an image). Failing cases: run cl3 turns 1, 2, 3 and 5, each with a write
  refused for a guessed prop (`file` for `src`; the button's words as children).
- 2026-10-09 · system prompt, R1 (founder-approved wording, founder ruling D3): the brief is
  direction (goal, reader and offer fixed; suggested facts, proof and structure are suggestions,
  say why in plan.md when choosing differently); `research/` names the claim labels, the claims file
  and the background-only sections; new rule: check a research number or quote in
  `research/claims.md`. No failing case yet: the R1 runs test it. Code side: research files now keep
  every statement type, its notes, and the Watch-outs / Context only sections (marked background);
  the claims file comes from the claims the research cites (the source drawer's read), gated by the
  platform rule.
