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
