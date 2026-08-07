# Pre-restyle hygiene increment — the scheduled gate before the Moda restyle

Branch `agents/editing-roundtrip-v0`, commits `7f979f6` → `71c99d0` (+ records).
Closes the three remaining debt-table rows in `docs/frontend-practices.md`
(table updated per the doc's definition-of-done). Discipline: verbatim moves,
one slice per commit, tsc + suite gates after each, browser-verified at the end.

## 1. EditorApp shell split (4 commits)

2,193 lines / 20 `useState` → **1,445 lines / 5 `useState`** (scene, page,
selection set, diagnostics, engine banner — core editing concerns only).

- `7f979f6` — pure helpers + chrome out: `engine/pageDuplication`
  (uniquePageId/duplicatePageOperations), `engine/editorKeyboard`,
  `engine/operationLabels` (deduped — AgentChatPanel carried a byte-identical
  copy), `components/EditorChrome` (mode switch, topbar size label,
  OperationHistoryPanel, EngineDisabledBanner).
- `d2a00ea` — `hooks/useExportPreflight`: Validate/Export flows, in-flight
  flags, export/preflight results + private helpers. activeDocumentId crosses
  via a lazy getter (useDocumentSync is wired later; the getter only runs from
  event handlers — same pattern as the applyOperations lazy wrapper).
- `e588bb4` — `hooks/useBrandChecks`: governance/compatibility flows +
  effectiveBrandKit/compatibilityTarget derivations + latestBrandKitVersion.
- `857e47f` — `hooks/useWorkspaceChrome`: panel mode, workspace mode,
  viewport/tool/fit, sidebar width + drag resizer.

Every workflow/presentation cluster now lives in a hook; EditorApp is
orchestration (guards, apply*, page callbacks, keyboard, layout JSX).

## 2. InspectorPanel split (`9f7e67f`)

1,715 lines → **~145-line orchestrator** + `components/inspector/`:
DocumentPageSection, ObjectSection, SizingSection, RawStyleSection,
DesignTokensSection (with the style summary), AutoLayoutSection, TextSection,
plus shared `fields.tsx` (NumberField/TokenSelect/DimensionModeSelect +
numeric/token helpers) and `diagnostics.tsx` (scope filtering, dedupe, the
compact issue list) and `summaries.tsx`. All JSX and helpers verbatim; the
restyle can rearrange/restyle sections without touching field bindings.
One transcription catch: `roundForEditor` rounds ×1000 (kept exact).

## 3. CSS token layer (`71c99d0`)

`styles.css` now opens with the `:root` design-token block:
`--chrome-*` (dark shell), `--panel-*` (parchment surfaces), `--teal-*`
(agent/status accent), `--action-*` (magenta primary), `--status-*-text`,
`--surface-white`, `--radius-sm/md/pill`, `--shadow-pop`. Rule: values with
≥3 uses tokenized (**302 replacement sites**); true one-offs stay raw.
Rendered values byte-identical — the commit only NAMES them, so the Moda
restyle becomes a token-value edit. frontend-practices rule 3 rewritten to
the token-first rule.

## Gates

- tsc at baseline (known ExportPanel.test error only) and suite **414/415**
  (known EditorCanvas env-split case) after EVERY slice.
- **Browser e2e (claude-opus-4.8 + playwright-mcp, live stack), all 8 shell
  flows PASS:** load (no engine banner, styling intact) → agent turn settled
  as proposal (~2.5 min, 37 ops) → Accept minted `?document=doc_dcc911f6…` →
  select-on-canvas + inspector text edit (live canvas update) → detach + drag
  via native PointerEvents (X/Y 0,0 → 740,1170) → undo/redo exact →
  reload-persist kept BOTH edits → export panel healthy (clean-state export
  produced an artifact in flow 2; the flow-7 "failure" is a legitimate
  LUMV0810 overflow self-inflicted by the drag test). Final-state console:
  **0 errors**. Visual check explicitly confirmed dark chrome + parchment
  cards + teal accents + magenta Accept — no token regression.
  Screenshots in `browser-e2e/`.

## Notes for the restyle (next increment)

- The token block is the restyle's edit surface; component rules already
  consume `var(...)` at every recurring site.
- Konva stays (jsdom test fallback — rule 4 unchanged).
- Pre-existing, not touched: `EDITOR_RENDER_TOKEN_FALLBACK` canvas-vs-export
  tone difference when no Brand Kit is attached (surfaced in Diagnostics);
  the known EditorCanvas env-split unit case; the ExportPanel.test tsc error.
