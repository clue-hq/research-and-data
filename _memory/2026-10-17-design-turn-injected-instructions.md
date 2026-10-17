# 2026-10-17 — what the scene agent receives on a follow-up turn (investigation, no code changed)

Branch `feat/scene-delete-key`. Triggered by the Conduit revamp run `run_a250cece3ac756958db08e81899af7b1`
("Make the whole ad feel more premium") keeping the layout and producing an off-brand image.

## Inventory (solo path)
- System prompt, rebuilt every turn: `build_scene_solo_prompt` (~12k chars) + frame payload
  (`lumen_agent/frame.py`: brand card, published-ad styles "advisory", backgrounds "advisory",
  type ramp, LIVE scene digest, asset index, 4 pinned knowledge files ≤24k chars each) +
  deepagents `BASE_AGENT_PROMPT` + middleware (skills list, filesystem docs, todo, `/.deepagent/AGENTS.md`,
  scoped preferences when present).
- User message (`main.py` `_execute_agent_turn_job` → `render_leg_turn_prompt` → `editor_agent_prompt`):
  [empty-page steering note] [DELEGATION BRIEF, first turn of a leg] [SESSION SO FAR, fresh thread]
  [DOCUMENT CHANGED drift note] + the user's text + "Editor context JSON" (ids, targets,
  `scene_summary` with no text/geometry, diagnostics, `editor_instruction`, standing instructions).
- Workspace files rewritten each turn (`workspace.py::scaffold_workspace`): brief.md (message +
  editor context again + "Caller-selected native-copy review" legibility block), state.json
  (`turn_request` = message again), brand_card.json, brand_colors.json, source_assets.json,
  ad-assets.md, references.md.

## Findings
- Four stacked "keep it" rules: `editor_instruction` (main.py:12547, commit 831a8bbb9 2026-07-04,
  written for chipped editor edits), solo prompt step 1 "For a seeded edit … preserve successful
  unrelated content", shared-surface contract #4 "smallest coherent change … unforgivable failure,
  worse than making no change at all" (prompts.py:56-62), and the follow-up routine sending a revamp
  back to the full routine, which still contains the seeded-edit preserve line.
- Contradiction: `editor_instruction` with targets says "do not touch any other node —
  byte-identical"; the shared-surface contract #1 says selected nodes are "the SUBJECT, never a fence".
- Brand: Conduit's brand_card has `imagery_rules: []`, tone clear/professional. The pastel-bokeh look
  is stated ONLY in ad-assets / frame section, labelled "context, not a rule … nothing here overrides
  … what the person actually asked for" → "premium" overrode it.
- Third follow-up had `target_node_ids=["atmosphere"]` (image selected) → strict fence; fine there.

Open: founder to choose fixes; nothing edited.

## Step 1 of the harness alignment — rule ledger (2026-10-17, DONE)
- Working dir `docs/design-harness-alignment/` (untracked; to be committed on the alignment branch): PROGRESS.md
  checklist (57 sources, all ticked), `ledger/*.jsonl` (636 rows), `issues.py` → `issues.json` (11 conflict groups),
  `render_ledger.py` → `rule-ledger.html` (artifact https://claude.ai/artifact/2EagVdjnAmnGkGgzNhU5Ce), `sources/`
  (captured first-call system prompt 68,335 chars + 21 tool schemas). Document tree page:
  https://claude.ai/artifact/Q8KsrqMZfAQT8EYJUDRGhm.
- Headline conflicts: I1 nine keep-it-small rules, no revamp permission/intent; I2 selection fence vs subject;
  I3 brand look advisory + below the request (binding only in account skills); I4 circular self-review;
  I5 follow-up routine vs repair-design/review.md/components (apply_structured_edit missing); I6 five ask policies;
  I7 six reading policies; I8 broken refs (clarify-design-brief, memory edit_file denied, search_assets→use_brand_asset
  refused, print-bleed-marks, foundations/typography-and-composition/images/placement, logo-and-assets, generate_brand_kit);
  I9 trio/test-probe/eval leftovers; I10 specific contradictions (scrim, type ratios, root structure, font floor,
  "Book a Demo", Inter, identity, ending); I11 duplicates (direction ×5, logo prep ×5, new imagery ×6, CTA ×5+,
  message ×3).
- Next: Step 2 founder rulings topic by topic (I1/I3/I4 first). Branch for edits not yet created (proposed
  `design/harness-alignment` off research-streaming).
