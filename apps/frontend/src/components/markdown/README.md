# Shared Markdown surface

Lane 2 Task 5: `MarkdownArticle` uses react-markdown + remark-gfm; `MarkdownEditor`
lazy-loads MDXEditor and all native plugins on the client. The approved prototype's
controls and Clue token theme live here. Code/source uses self-hosted DM Mono.

The feature owns persistence, raw saved body, draft, base revision and errors. Supply
`documentKey` from workspace/project + stable path. `value` initializes the session;
it is not a keystroke-controlled replacement. Advance `resetKey` only on Discard or
an accepted external replacement. A save's new immutable document ID is not a reset.
Keep the editor mounted (hidden) through Preview/Edit to preserve undo history.

Initial library normalization is tracked separately; undo to that normalized value
returns the original raw bytes. Disable auto-linking during import to avoid an extra
normalization edit. Native source recovery preserves unimportable text. Subscribe to
`onStatusChange` and use `markdownCanSave` to block Save until source returns to valid
Rich text. The editor never performs transport calls or silently retries a conflict.

Use `readOnly` for permission changes. Such changes remount from the retained draft
because the library otherwise rebuilds Source from its last visual serialization.
Knowledge uses an inert wrapper for in-flight saves, keeping editor history intact.

MDXEditor 4.2.5 supports Lexical 0.48.0. The main app's direct Lexical packages are
aligned to that version; the design text runtime and MDX plugins resolve one Lexical
constructor. Keep the dependency identity test when changing either editor's version.
Do not edit vendor files or target generated vendor class names.

Verified on Semarang 3040: no-op import; real v2/v3 saves and reload; stale-tab conflict
with retained draft; undo after Save; Preview/Edit; per-path drafts; source recovery;
Discard; long code/URLs/tables at a temporarily constrained 360 px boundary. Temporary
width styles and disposable document rows were removed after testing.
