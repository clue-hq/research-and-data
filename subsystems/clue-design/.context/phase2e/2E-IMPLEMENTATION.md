# Phase 2e — The experience extras (closes Phase 2 / Milestone M2)

Five small, cherry-pickable features around the agent chat, one commit
each. The only backend change is the instructions column + endpoint;
everything else is editor-side and rides existing machinery (2b's run
status, 2c's composer, the agent panel).

## Commits

- `0fa47c2` — **per-document standing agent instructions (backend).**
  `documents.agent_instructions` via the existing `ensure_column` add-only
  pattern; `PUT /documents/{id}/agent-instructions` (blank clears);
  returned by GET. `AgentTurnPreviewRequest.agent_instructions` →
  `editor_agent_prompt` folds it into the context as
  `standing_instructions` with an explicit "the current request wins on
  conflict" rider.
- `e45bf0d` — **instructions UI + per-turn payload (frontend).**
  `useAgentInstructions`: the trimmed draft rides with EVERY turn
  immediately (both runners send `agent_instructions`); Save persists via
  PUT; instructions typed before the document exists auto-persist once the
  first Accept mints the id. "Standing instructions" disclosure with an
  honest status line (unsaved-but-sent / saved / saves-when-doc-exists /
  error). Loader round-trip via `fetchDocument`.
- `631c5bb` — **Design-Plan pre-brief + variants-as-pages.** Moda §1.3's
  four skippable questions (variations / brand adherence / focus / CTA) as
  a disclosure; composition is the pure `composeBriefPrompt` (empty brief
  = untouched prompt). Variations > 1 → "N distinct concepts, EACH as its
  own named page (Variant A/B/…)". Direct sends only — queued messages
  stay verbatim so their chips read as typed.
- `cfb3277` — **post-turn suggestion chips (static v1).** Deliberately
  dumb heuristics (`postTurnSuggestions`): fixed pair + "Match the style
  across all pages" on multi-page scenes, cap 3. Shown once a turn has
  settled; clicking fills the composer draft, never auto-sends. EditorApp
  computes from the scene so the panel stays scene-free.
- `21e8cf9` — **notify-when-done toast.** `useTurnNotification` rides the
  same `isAgentRunning` transition as 2b's checklist: settle while the
  agent panel is closed → floating click-to-open toast; opening the panel
  dismisses; auto-dismiss otherwise. No browser Notification API (no
  permission prompts, no dialogs).

## Gates

- API suite: +2 tests (instructions round-trip incl. clear; prompt
  injection present/absent); agent/document/instructions subset 19 green.
- Editor suite **414/415** cold-cache (+11 across the increment: 3
  instructions hook, 3 brief composition, 2 suggestions, 3 toast hook; the
  1 is the known EditorCanvas env-split case). tsc at baseline.
- Browser e2e (M2 completion gate): below.

## Browser e2e evidence (PASS — all five hard gates)

Real stack (both sides at `21e8cf9`), Playwright MCP driven by a
claude-opus-4.8 agent. Document `doc_876e8b6f…` ("Phase 2e E2E Poster",
final v4). Zero live console errors at every checkpoint. Screenshots
`2e-e2e-0…6` in `browser-e2e/`.

- **Payload gate:** the POST to `/agent/turns` carried BOTH
  `"agent_instructions":"Always use dark navy backgrounds with white
  text."` and a prompt beginning `Design brief:` with "2 distinct variant
  concepts, EACH as its own page named \"Variant A\", \"Variant B\"…",
  flexible adherence, focus, and the verbatim CTA — exactly the composed
  block (`2e-e2e-2`).
- **Toast gate:** with the agent panel closed, every settling turn raised
  `agent-done-toast` (three observations, both message variants); click
  opens the panel; auto-dismisses (`2e-e2e-3`).
- **Persistence gate:** instructions typed BEFORE the document existed
  auto-saved once the first persisting action minted the id — curl showed
  the exact text, still intact after a later Accept at v4 (`2e-e2e-4`).
- **Reload gate:** `?document=` reload pre-filled the Standing
  instructions textarea ("· active", "Saved with the document.")
  (`2e-e2e-5`).
- **Chips gate:** the settled multi-page scene showed the context-aware
  row (incl. "Match the style across all pages" — absent on single-page);
  clicking filled the composer verbatim with NO `/agent/turns` POST
  (`2e-e2e-6`).
- **Variants-as-pages (best-effort, as specced):** the brief turn's draft
  produced two pages `variant_a` / `variant_b` — both on dark navy
  `#0B1533` with white text, i.e. the STANDING INSTRUCTIONS shaped the
  design. Naming came back lowercase (`variant_a`) rather than
  "Variant A" — cosmetic, prompt-adherence quality.
- **Bonus:** a later edit turn produced a clean proposal → Accept →
  version 4 with instructions intact.

Honest notes: 3 of 4 turns hit the known agent-quality flakiness
(LUMD0401 duplicate-node-id repair loops → failed-with-draft) — feature-
independent; already on the agent-improvement backlog. The gate used the
documented fallback (mint the doc via a scene mutation) where needed.

**This closes Phase 2 (2a → 2e) and Milestone M2.**
