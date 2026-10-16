# Site editor (Puck sites, Wave 2 Lane C)

Status: implementation in progress (plan `docs/superpowers/plans/2026-10-11-lane-c-site-editor.md`).

## Two origins
- **The app** (`app.cluehq.ai`, `apps/frontend`) holds the session, the chat, the stage chrome,
  the dock (fields + Layers), the asset library, versions and publish. It holds the site JSON
  and is the only side that saves (design API site routes through `/api/clue/design/*`).
- **The editor domain** (`https://<label>.<CLUE_SITE_EDITOR_SUFFIX>`, `apps/frontend/packages/site-editor`)
  renders the Puck canvas (`Puck.Preview` only) and runs agent-written sections. It has no
  login, a strict CSP (no unsafe-eval, nonced import map only, frame-ancestors = the app), and
  serves `/sections/<digest>.mjs?t=` (token verified with the design API) and `/asset-store/<sha>`
  (proxied) from its own origin. `<label>` = first 32 hex of sha256("clue-site-editor-label:v1:" + workspace id).

## The protocol
`@clue/site-kit/editor-protocol` (Contract 6). Envelope `{channel: "clue-site-editor", v: 1,
documentId, nonce, type, payload}`. The app accepts only from its iframe's window, the exact
editor origin, the frame's nonce and the initialised document; the frame only from its parent
and the app origin. No `"*"` target origins.

## Where the code is
- Kind switch: `src/features/chat-shell/model/artifact-kind.ts` (`isWebsiteKind`, `chatShellKindForCard`).
- Data + save policy: `src/features/site-editor/{model,data,hooks}`.
- Frame host: `src/features/design-editor/components/site-artifact-canvas.tsx`, persistent in `artifact-stage.tsx`.
- Dock: `src/features/chat-shell/components/site-inspector.tsx`; pages: `site-pages-panel.tsx`, `site-url-bar.tsx`.
- Shared edits: `@clue/site-kit/editor-site`; origin helpers: `@clue/site-kit/editor-origin`.
