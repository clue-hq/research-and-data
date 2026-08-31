# 2026-08-19 — Chat-flow editor integration, Slice 5: URL write-back (deep-link OUT)

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Brief:
`.superpowers/sdd/2026-08-19-chat-flow-editor-integration/task-5-brief.md`.
Follows slices 1–4 (`f7540b63`, `f6d63cdc`, `3957166a`, `3ba169be`). Commit `95922696`.

## What shipped

- **`model/chat-surface-params.ts`** gained the pure serializer
  `chatSurfacePaneParams(state) → {surface, edit, selection}` (the inverse of the existing
  `chatSurfaceUrlState` parse), plus an explicit `?surface=chat` parse branch (the ratified
  alias of the conversation-only resting state — same state as an absent param). Rules:
  rail closed → NO pane params (clean URL); gallery → `surface=gallery` only; artifact →
  `surface=<artifact kind>` with the kind-unknown tiebreak (preserve incoming `web`/`ad`,
  else `web`); `edit=1` only on the artifact surface while editing; `selection=<token>`
  only while editing and only when ≠ `canvas`. `?artifact=` is never emitted.
- **`components/chat-surface.tsx`** gained the write-back effect: `useRouter` +
  `usePathname` + `useSearchParams`, composed over the LIVE query minus the three pane keys
  (so `handoff` and any future param survive), `router.replace(..., {scroll:false})` ONLY
  when the composed query differs from the current one (loop guard + convergence with the
  workspace controller's handoff cleanup). No sync setState; read side stays read-at-mount.
- **10 new tests** (TDD, red first): round-trip identity over `ChatSurfaceUrlState` for
  closed / gallery / artifact(web,ad) / editing / every non-`canvas` token in
  `CHAT_SHELL_INSPECTOR_SELECTIONS` / `canvas`-omitted / selection-without-editing /
  kind-unknown tiebreak / no-`artifact`-key. Suite 772/772 (762 + 10), lint, build green.

## Controller decision made during implementation (please confirm)

The brief named `shell.inspectorSelection` as the URL's selection source, but on a REAL
document that value never changes: `WebInspector`'s `onSelectionChange` fires only from the
dummy FALLBACK layer trees, and a real layer-row/canvas click flows through
`session.webSelection` instead. Serializing `shell.inspectorSelection` alone would have made
`?selection=` inert on every real artifact (and the brief's own browser step 4 unreachable).
Shipped instead: the **effective schema the inspector is rendering** — the same
`session.webSelection.selection?.schema.selection ?? shell.inspectorSelection` value passed
to `WebInspector`. Still an inspector SCHEMA token (never a node id), which is exactly what
`?selection=` hydrates. Cost: one `router.replace` (→ one RSC re-render) per canvas
selection change.

## Known limitation surfaced (needs a founder/controller ruling)

**Deep-link OUT restores pane STATE, not the open ARTIFACT.** The ratified vocabulary has no
artifact identity (`?artifact=` is superseded), and the chats route never fabricates tabs, so
a shared `?surface=web&edit=1&selection=text` URL lands rail-open on the artifact surface with
NO tab → the slice-4 dock guard collapses to the conversation (`data-artifact-kind="none"`,
inspector absent). Browser-proven in a fresh tab. The URL is preserved verbatim (no rewrite),
so the state is honest, not lost. Restoring the docked editing state from a link needs an
artifact-identity param — a new ruling, not slice-5 work.

## Verification (live 3030/8030/8010 stack, Playwright)

URL assertions via `page.url()`/`location.search`:
resting `""` → open rail `?surface=gallery` → card `?surface=web` → Edit `?surface=web&edit=1`
→ Subheadline `?surface=web&edit=1&selection=text` (inspector shows real hydrated Text values,
node `sub`) → real accepted send → dock dismissed AND URL back to `?surface=web` (edit +
selection dropped) → rail closed → bare URL. `?x=1` survived every replace (`?x=1&surface=gallery`
↔ `?x=1`). `?surface=chat` inbound → plain conversation, canonicalized to the bare URL, no
history entry, and a following toggle proved NO remount (same `main` DOM node + marker, 10
transcript articles unchanged). Artifact route regression: URL stays bare across Edit toggles,
Edit still docks. Console: only the known `example.com/widget` 404s.
Screenshots `.playwright-mcp/slice5-{04,05,07,10}-*.png`.

**history.length finding:** `router.replace` is history-neutral — 4 URL-changing pane toggles
with no canvas mounted left `history.length` flat. The +1 per Edit toggle seen WITH a canvas is
the srcdoc iframe navigation, and it reproduces identically on the artifact route (untouched by
this slice, URL never changes) — pre-existing canvas behavior, not the write-back.

**Ops:** the platform API on 8030 died mid-run (fourth dead-server incident on this branch) —
restarted with `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` extended for `http://localhost:3030`; the
symptom is the "workspace is temporarily unavailable" screen, not a frontend bug. One real chat
message ("slice5 url check") was posted to the seeded dev thread to prove dismiss-on-send (same
plan-sanctioned pattern as slice 4). No document writes.

## Next

Slice 6 close-out (contract notes, `.gitignore` for `.artifacts/`, full gates + make check,
walkthrough script) — and the artifact-identity ruling above if the founder wants true
editing-state deep links.
