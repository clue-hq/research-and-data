# Lane 2 — document flow acceptance

**Status:** the requested frontend verification step is complete, 2026-09-14.
**Checkout:** Semarang, `visual-polish`; live frontend `http://localhost:3040`.

This record consolidates the browser, API/database and frontend-gate evidence collected during
implementation. The close-out audit checked the saved evidence against the unchanged application
at `fb4e006bc`; it did not rerun destructive fixtures or repeat the entire suite for documentation
changes. The lane index's stale "pending" status is corrected.

## Acceptance checklist

| Requested behavior | Result and evidence |
| --- | --- |
| Save and hard refresh | Passed on Knowledge and project documents. Real browser saves created immutable document IDs/revisions; saved content survived full reload. Database/artifact inspection confirmed saved markers for Plan, ICP, persona and Knowledge, with heading and fenced-code metadata retained. |
| Version conflicts without lost edits | Passed. An external revision made the browser's base stale; Save returned a conflict while preserving the draft. Checking for updates kept the draft. Explicit Discard adopted the latest revision, which could then be saved. |
| Switching documents | Passed. Gallery navigation and switching, closing and reopening named file tabs retained each document's separate draft and editor history. Document selection uses stable paths; saves adopt the returned revision ID. |
| Undo, redo and discard | Passed through native editor/browser interactions. Formatting and text changes could be undone/redone; returning to the original content restored a clean state. Discard reset to the current saved version. Opening an untouched document did not enable Save. |
| Unsupported-content recovery | Passed. Unsupported JSX blocked Save and remained recoverable, unchanged, in Source mode. A bounded fixture proved exact source retention; virtualized CodeMirror DOM text was not treated as the full source. |
| Horizontal overflow | Passed in Preview/Edit at 390 and 720 px with long unbroken URLs, inline code and fenced code. Page `scrollWidth` equalled `clientWidth`; table scrolling remained local. Earlier Knowledge checks also covered a 360 px component boundary. |
| Native formatting and read-only state | Passed for headings, nested/task lists, links, tables, inline code and fences. macOS Mod+B/I/K/Z and Mod+Shift+Z worked; Escape closed the link dialog and restored focus. Read-only prototype visual/source/code-block typing was rejected and Save remained disabled; live user permissions were not altered. |
| Gallery and file-write navigation | Passed for all three project document kinds. A controlled live stream opened the exact persona file; duplicate delivery and cold replay did not reopen closed tabs. A historical document card opened the latest revision by path. No permanent Plan/Documents tab remains. |

Only saved revisions are durable across reload. Unsaved drafts and undo history are retained
within the mounted page, with the existing unload warning; this work does not promise recovery
of unsaved drafts after a browser restart.

## Frontend gates

| Gate | Recorded result |
| --- | --- |
| `npm run design-system:build` | Passed. |
| `npm run lint` | Passed: zero errors; two inherited unused-function warnings in `canvasOperations.ts` (`snapPosition`, `snapExtent`). |
| Full frontend test set | 2,270 passed, zero failed/skipped/cancelled. The `tsx` CLI hit sandbox IPC `EPERM`; the same test set ran with `rg --files src -g '*.test.ts' -0 \| xargs -0 node --import tsx --test`. |
| `npm run build` | Passed: Next 16.2.12 production compilation, TypeScript check and page generation. |
| Prototype typecheck | Passed. |
| Whitespace/diff check | Passed at the implementation checkpoint; repeated for this documentation close-out. |

The build and test results are from the completed implementation run, not a newly repeated run.
Local raw evidence remains in `.context/gallery-{tests,lint,tokens,build}.log` and
`.context/gallery-live-proof.json`; `.context` files are untracked. Durable narrative evidence
is recorded in:

- [Shared editor and Knowledge acceptance](../../../_memory/2026-09-14-lane2-shared-markdown-knowledge.md)
- [Plan acceptance, including resumed browser verification](../../../_memory/2026-09-14-lane2-plan-live-integration.md)
- [Gallery and toolbar acceptance](../../../_memory/2026-09-14-lane2-gallery-toolbar-acceptance.md)
- [Toolbar implementation and native-library limits](2026-09-13-markdown-editor-toolbar.md#acceptance--2026-09-14)

## Scope and checkpoints

- `b934ff7b8`: corrected cold-history replay after the Plan browser check exposed it.
- `248ced412`: Gallery document cards and named file tabs, including exact document references.
- `fb4e006bc`: shared native Markdown toolbar and final cross-surface verification.
- MDXEditor 4.2.5 retains its native H1–H6 selector. It does not provide the proposed
  Mod+Shift+X/E or modifier-based list chords; toolbar controls and native Markdown shortcuts
  remain available. No second formatting engine was added.
- Stream checks used the real durable stream path with a held, no-model fixture. They do not
  claim the separate Lane 1 agent-generation walk has run. No model or fleet task was dispatched.
- Disposable projects/threads were archived and test Knowledge paths removed. Append-only audit
  rows and protective queue holds were retained; cleanup did not bypass database guards.
- The compact document-reference chat-card preview at `http://localhost:3047/file-card` is a
  separate visual review item. Its styling has not been applied to the main chat.
- No environment changes, sibling process stops or remote publication were part of this close-out.
