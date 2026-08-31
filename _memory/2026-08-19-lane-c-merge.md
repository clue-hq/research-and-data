# 2026-08-19 — Lane C merged into the trunk (`integration/frontend-design-part-iv-v2`)

Founder-ordered pull of `feature/w4-lane-c-richtext-components` (tip `7741de75`,
"lane feature-complete") into the trunk.

## What happened

- **Zero-conflict merge** — lane C had already merged the post-lane-B trunk into itself
  (`84d8a79e`), so the trunk HEAD (`2c037baf`) was the merge base; content-wise this was a
  fast-forward, recorded as an explicit `--no-ff` merge commit to match the lane-B
  convention (`8dde2199`).
- **What came in (25 commits, +6,749 lines):** W4.8a rich-text session (vendored Lexical
  runtime `webRichTextRuntime.ts`, canvas-owned toolbar rethemed to the inspector design
  language, one `set_rich_text` commit per session), W4.8b range-bound Link-to,
  W4.7 custom-component props form (contract item 34, incl. Escape-abandons-draft fix),
  the founder-directed view-mode addendum (Edit off = clean bridge-free render;
  view-mode links Figma-like per ruling (a): absolute → new tab, #fragment → in-preview
  scroll, relative → inert), and the lane's whole-branch-review fixes (`6178d609`
  Edit-off unlatches the bridge; `6d051ec4` untouched optional prop no longer overwrites
  its default).
- **Union gates re-run here by the trunk session:** `npm install` (lane C added Lexical
  deps) → design-system:build → **test 752/752** → lint clean → production build green.
- Lane C's prescribed close-out cleanup checked: no `lane-c-8050-watchdog` process was
  running (nothing to kill).

## Carried items from lane C's ledger (not bugs to fix now)

- Per-node rich-text link error outlives its range; toolbar panel-open pointerdown
  commits the session on inspector URL-field click; vendor cache-key `?v=` owned
  upstream (all ledgered-accepted in the lane's whole-branch review).
- Source-semantics caveat: a rich-text commit landing while another write is in flight is
  silently dropped after the Lexical session destroys itself — same as upstream.

## State / next (the ratified queue)

All three W4 lanes are now on the trunk (A on-branch, B `8dde2199`, C this merge).
Next per the committed plan: **chat-flow editor integration**
(`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md` — its hard
start-gate "after lane C merges" is now satisfied) → W4.10 keyboard node-op audit →
W4 exit gate (§1 live / §3 inert / §2 absent) → W5 acceptance audit + founder sign-off.
No push — the user pushes/decides.
