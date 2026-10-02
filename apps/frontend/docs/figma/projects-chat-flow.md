# Projects / chat flow fidelity map

Source file: `NcLl2r0dzVDN28xAQCwvM1`
Source page: `Projects/chat flow` (`1326:37155`)
Reference viewport: `1680 × 945`

This map separates the visual source from data and interaction state. Components
render values passed from the project repositories; Figma copy is represented by
fixtures only when no API base URL is configured.

## Chat appearance inconsistency register (2026-09-20)

**Current typography:** the founder selected **14px font size with 22px line height**
for the composer, sent-user text, assistant responses and inline mentions. These
surfaces share the product chat body tokens. This supersedes the 15px body size
recorded in the original review and verification below; attachment labels remain 14px.
The subsequent 14px/20px request was clarified as applying to the accounts table;
chat remains 14px/22px.

**Reference polish after the bubble colour change:** shared attachment chips use
the existing `bg-page` surface (`#f8f9fb`), a quiet Gray Alpha 100 border and regular
label weight. File glyphs are 14px on a transparent preview background, removing
the separate square behind the icon; image thumbnails remain 20px. Hover uses
`bg-subtle` and Gray Alpha 200. Mentions retain their transparent, underlined
presentation with a softer Gray Alpha 200 underline. Draft and sent references
share these rules; 32px attachment height, truncation and removal behaviour remain.
This supersedes the medium-weight attachment measurement in the earlier review.

**User message background:** sent-user message boxes use the founder-selected
`#eff0f3`, provided by the product chat `user-message-background` token. The shared
user-role rule applies across conversations and to optimistic/persisted messages.
Project and design conversations, including artifact split views, all mount the
same `ChatSurface` → `ConversationContent` → `ChatTranscript` renderer. The older
`.userMessage` style also references this token rather than retaining a white fill.

**Subsequent release cleanup:** per-tool activity rows (for example, “Complete a
project step” and “Save your answer”) are omitted by the shared chat part renderer
for all conversations and tool states. The typography measurements below describe
the preceding parity review; the activity rows are no longer shown. Reasoning and
response text remain separate from this removal.

**Status: CHAT-VIS-01 through CHAT-VIS-03 implemented and browser-verified
on 2026-09-20.** This section is the living record for
the main platform's composer/transcript appearance review. Update these entries
when implementing and verifying the fixes rather than creating a competing audit.

### Reference and original review evidence

The founder identified the current dummy frontend as the visual reference and
explicitly preferred the composer's text size and `@` mention treatment. Equivalent
content should retain its appearance after sending; supporting labels may retain
a deliberate secondary hierarchy.

| Surface | Reviewed baseline |
| --- | --- |
| Main platform | `/Users/aryankeshri/conductor/workspaces/research-and-data/damascus`, branch `rebase-and-expand-attachment-types`, commit `074f038e3`; `http://localhost:3027` |
| Live chat | `/projects/prj_579c550441cf5c48a69d783390ac93a7/chats/thr_0c8e9a8e0f7a54e380cf806f4392ba0b` |
| Dummy frontend | `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`, branch `codex/projects-home`, commit `9fc902a`; `http://localhost:3000` |
| Dummy chat inspected | `/projects/10m-landing-page-campaign/chats/thread-primary` |

Evidence came from live browser accessibility state, screenshots, computed CSS,
and the corresponding source files. The main chat viewport was 1056 × 988 CSS
pixels; the dummy tab was 1280 × 720. Computed typography was compared directly;
this was not a screenshot overlay comparison at matching viewport sizes.

- Both copies of `packages/design-system/generated/tokens.css` were byte-identical
  (SHA-256 `612f2c76114fc376729bc34bc12b78479dc3b95469c23d5eb93c6a7630b6554c`).
  The observed mismatch is in component styling and composition, not an older
  generated token package.
- The composer measured **15px / 22px, Satoshi, weight 400** in both live apps.
- The main chat's user and assistant body text measured **14px / 20px**.
- A temporary account mention was selected in the main composer's draft, measured,
  and removed. No message was submitted. Its post-send appearance was traced in
  source, not verified by sending it.
- Existing sent-file chips were measured live. Pre-send upload-chip dimensions
  were traced in the shared attachment component; no file was uploaded for review.
- The current dummy chat had no populated agent transcript. Its active shell
  renders saved user strings, and its older `project-flow.module.css` timeline
  still declares 14px / 20px. Thus the review does **not** establish a newer dummy
  agent transcript using 15px / 22px. That proposed target comes from the founder's
  preferred composer appearance.

### Findings addressed

| ID | Inconsistency and evidence | Implemented correction |
| --- | --- | --- |
| **CHAT-VIS-01** | **Body text shrinks after sending.** Composer: 15px font / 22px line height. Both sent user prose and agent responses: 14px / 20px, inherited from `.transcript`. The values are declared independently. | Share the preferred 15px / 22px chat-body definition across the composer and transcript, including rendered paragraphs and lists. Keep secondary labels intentionally separate. |
| **CHAT-VIS-02** | **`@` mentions change appearance and lose identity cues.** Composer: 15px text, transparent background, no surrounding border, underlined name, 16px account logo/contact avatar (14px typed file/design glyph), 5px icon gap. Transcript source: generic 11px / 18px boxed `@label`, 0.5px border, page-colour fill, 4px radius and 7px horizontal padding. Account/contact/type icons are not rendered by that branch. | Reuse the composer's mention presentation for sent references, retaining identity icons, typography, colour and underline treatment. Preserve read-only transcript behaviour and appropriate missing-image fallbacks. |
| **CHAT-VIS-03** | **Uploaded-file chips shrink and use different geometry.** Composer source: AI Elements inline attachment, 32px height, 14px medium text, 6px gap and 20px preview container. Existing transcript chips: 19px measured height, 11px regular text, 5px gap, 0.5px border and 4px radius; image thumbnails are 18px. Their padding and border/radius definitions also differ. | Share the file-attachment presentation before and after sending. Retain the established composer dimensions; omit draft-only removal/upload controls from sent chips without changing the chip's visual identity. |

Implementation references (relative to `apps/frontend`):

- [Composer and transcript CSS](../../src/features/projects/components/project-flow.module.css):
  `.composerEditor`, `.messageText`, `.chatMention*`, `.messageContextRefs`.
- [Composer mention renderer](../../src/features/projects/components/project-composer-editor.tsx):
  `ComposerMention` retains Slate editing and selection; the shared
  [mention visual](../../src/features/projects/components/chat-mention.tsx) owns identity cues.
- [Transcript reference renderer](../../src/features/projects/components/chat-transcript.tsx):
  delegates to [message references](../../src/features/projects/components/chat-message-reference.tsx),
  preserving reference order and identity while reusing the draft presentation.
- [Chat attachments](../../src/features/projects/components/chat-attachment.tsx)
  and [shared attachment component](../../src/components/ai-elements/attachments.tsx):
  one inline presentation for drafts and sent files, with removal and upload status
  supplied only by drafts.
- [Generated tokens](../../packages/design-system/generated/tokens.css) and
  [frontend styling rules](../architecture/frontend.md#design-system-rule).

In the dummy checkout, the comparison sources are
`src/components/chat/chat-composer.module.css`,
`src/components/ai-elements/attachments.tsx`,
`src/features/projects/components/project-flow.module.css`, and
`src/features/chat-shell/components/chat-shell-view.tsx`.

### Properties already aligned and review limits

- Satoshi, regular body weight and the primary content colour matched. The main
  chat's composer and transcript use the same neutral content colour
  (`rgb(28, 32, 40)`). This review found no evidence requiring a font replacement
  or a global palette change.
- On the inspected main-chat viewport, the transcript was 672px wide and the
  composer editable box 671px wide, with their left edges within 0.5px before
  internal text padding. No horizontal overflow was found in the inspected
  transcript. There is no demonstrated column-width defect in this snapshot.
- The author label measured 13px / 18px, the reasoning trigger 13px / 20px and
  tool activity 14px / 20px. These are supporting roles, not automatically defects;
  consistency means a deliberate hierarchy rather than making every label 15px.
- Entity mentions and uploaded files are different kinds of reference. Each
  should remain consistent across draft/sent states; they need not be forced
  into one identical appearance.
- The original review did not exercise narrow layouts, long labels or state
  transitions. The implementation pass below adds responsive and component-state
  checks; fresh server uploads and provider execution remain outside this visual pass.
- The preceding Inspect removal is complete in `074f038e3`; it is not one of the
  appearance findings above.

### Implementation boundary and acceptance

Work belongs to the frontend presentation layer. Share chat typography and the
mention/attachment presentation primitives instead of introducing another set
of transcript-only overrides. If a product-specific chat token is needed, add
it through the design-system source/generator; do not hand-edit generated CSS
or change the global 14px body token for unrelated screens. Preserve the
repository/model seam, reference identities, attachment retrieval, message
ordering and existing chat behaviours. No backend contract or migration change
has been identified as necessary by this review.

The dedicated [chat token source](../../packages/design-system/source/production/components/chat.json)
provides 14px body size and 22px line height through the generator. The published global
14px text token remains intact. `.messageText` covers durable and streaming prose;
the transcript container keeps its metadata default. Mentions share `ChatMentionVisual`;
file chips share `ChatAttachment` and the AI Elements inline variant. Long labels truncate
within the available width and retain the full label in their title/preview. The composer
keeps its horizontal attachment strip, while sent references wrap. Missing account logos
fall back to the building icon; contacts keep the existing initials fallback. A historical
design ref with `kind=web` retains the microsite glyph even without a current catalog entry.

### Implementation verification (2026-09-20)

| Check | Observed result |
| --- | --- |
| CHAT-VIS-01: live user/agent paragraphs and lists | 15px / 22px, weight 400, matching the composer. Author stays 13px / 18px; activity stays 14px / 20px. |
| CHAT-VIS-02: draft and sent mentions | Same 15px label, 5px gap, 1px underline, transparent background and no outer border. Account/contact icon box 16px; document/ad/microsite glyph 14px. |
| CHAT-VIS-03: draft and sent attachments | Same 32px height, 14px / 20px medium text, 6px gap, 6px horizontal padding, 1px border, 6.4px radius and 20px image preview. |
| Real main chat at 1056 × 988 | Existing PDF/XLSX/PNG references render correctly; Inspect absent. Empty draft restored and send disabled. |
| Real main chat with artifact panel open | Transcript width 312px; editable box 311px. Transcript, context rows and composer have no horizontal overflow. Long filenames truncate and sent chips wrap. |
| Isolated component fixture at 390px and 720px widths | Long account/file labels fit without page or transcript overflow. Shared components render draft, optimistic, persisted and streaming examples consistently; reload preserves presentation. |
| Reference fallbacks | Deliberately failed account logo uses building icon; missing contact image uses initials; `kind=web` without a catalog entity uses the microsite icon. |
| Interaction preservation | Live account mention insertion and draft clearing; fixture keyboard mention search/Enter selection; draft attachment removal; no remove buttons on sent refs. Uploading/failed draft states retain their busy/invalid and error styling. |
| Checks | 81 existing focused tests passed across composer editing, catalog, transcript transitions, attachment validation and message presentation. Token generation, ESLint and production build passed. ESLint reports only the two existing unused-function warnings in `canvasOperations.ts`. |

The temporary fixture used the real composer and transcript components with local data and
no transport. It was removed after verification. No new chat turn, paid provider call, or
server upload was submitted. Upload-network failure/retry and a fresh server persistence
round-trip were not exercised; existing state-machine tests passed. The current dummy has
no equivalent populated agent transcript, so closure follows the founder-approved composer
appearance plus the measured before/after evidence above, not a claim of pixel parity with
an unavailable dummy state.

- [x] Shared body typography, including paragraph/list rendering, with deliberate metadata sizes.
- [x] Shared account/contact/file/design mention visuals, icons and fallbacks.
- [x] Shared document/image attachment geometry; sent references are read-only.
- [x] Long-label truncation and narrow/split layout checks.
- [x] Draft editing/removal and keyboard selection; upload-state presentation checked with fixtures.
- [x] Optimistic, streaming and persisted rendering checked with fixtures and existing regression tests.
- [x] Token generation, lint, production build and focused tests.

## Isolated sidebar IA exploration (2026-08-05)

The sidebar project/chat information architecture is being refined in a separate
editable file so the production Clue source is not mutated during exploration.

- Exploration file: `sI7rg7g1cYec9gAdc7slZo`
- Source-components page: `1:2`
- Sidebar-explorations page: `1:3`
- Six-state interaction board: `13:268`
- Project row component set: `65:115`
- Conversation row component set: `69:52`
- Status badge component set: `68:27`
- Project actions menu: `87:64`
- Edit-project dialog: `87:85`
- Reusable 1px icon shelf: `79:38`

Project folders are persistent leading icons. New chat and the three-dot project
menu are transient trailing actions shown at hover/focus. Chat rows remain
indented under their project and may show a trailing Running, Review, Approval,
or Needs input state. The project menu is web-only: New chat, Pin project, Edit
project, and Archive chats. Rename and Remove project live in the edit dialog;
desktop-only Finder and worktree actions are intentionally excluded.

Product copy uses the Clue Satoshi tokens (`sm/text-sm`, `sm/text-sm-medium`,
and `caption`). Every locally normalized icon uses a 1px stroke. The production
Clue Figma file remains the visual reference and was not modified by this
exploration pass.

## Research execution component library (2026-08-06)

Research execution is documented on page `136:2` in the isolated exploration
file `sI7rg7g1cYec9gAdc7slZo`. The page is organized as one top-level wrapper
(`136:3`) with five numbered sections: overview, component workbench, complete
flow, scale behavior, and motion/interaction. The production Clue Figma file was
not modified.

The user sees a compact activity summary that helps them monitor work and verify
results. It is not a transcript of private chain-of-thought. A run remains one
visible research task whether it covers one account or 500 accounts; worker and
account-level jobs are aggregated behind that task.

### Reusable research components

| Component set | Figma node | Variants |
| --- | --- | --- |
| `Clue/Research step row` | `137:417` | Queued, Running, Complete, Needs input |
| `Clue/Research activity` | `142:86` | Scoping, Light research, Checkpoint, Deep research, Synthesizing, Complete, Partial, Needs input |
| `Clue/Research result surface` | `146:152` | Waiting, Building, Ready |
| `Clue/Agent disclosure` | `148:517` | Reasoning/Tool × Running/Complete |

The disclosure set is the Clue adapter for the approved Vercel AI Elements
patterns. Clue continues to own the composer, message layout, split workspace,
artifact surface, and account/contact context. Only compact Reasoning and Tool
lifecycle disclosure is used here; normal assistant copy remains unboxed.

### Complete flow and recovery states

| Stage | Figma node |
| --- | --- |
| Scoping | `149:121` |
| Light research | `151:413` |
| Checkpoint | `151:980` |
| Deep research | `151:992` |
| Synthesizing | `151:1004` |
| Complete | `151:1016` |
| Partial results preserved | `152:692` |
| Needs account/source input | `152:704` |

The six happy-path screens and two recovery screens are presented in a centered
two-column sequence at native size. The right rendering surface remains stable
while it advances from Waiting to Building to Ready. Partial runs preserve the
available table and isolate exceptions; blocked runs request the smallest
required user action.

Scale behavior is shown at `153:871` (one account) and `153:872` (500 accounts).
Both display one visible task and the same meaningful phases. Scale changes
counts, aggregate worker detail, and rendered rows—not the visible task
hierarchy.

### Motion contract

- Loader: 900ms linear rotation, continuous only while a state is running.
- Shimmer: 1.4s clipped sweep with opacity `12% → 48% → 12%`.
- Lifecycle changes: 240ms Smart Animate with ease-out.
- Activity prototype: Scoping → Light research → Checkpoint → Deep research →
  Synthesizing → Complete.
- Result prototype: Waiting → Building → Ready.
- Production progression is event-driven. Prototype timeouts communicate the
  intended feel but must not become the backend lifecycle model.

The motion specification is stored in section `136:34`. Loader rotation and
shimmer keyframes are attached to the running component masters so all instances
inherit the behavior.

## Approved flow states

| State | Figma node | Frontend surface |
| --- | --- | --- |
| Home with account/contact picker | `1410:55724` | `/` + `@` autocomplete |
| Home with model picker | `1410:55801` | `/` + model menu |
| Home with recommendation selected | `1410:55846` | `/` + prompt draft |
| Home with attachments | `1410:55691` | `/` + file drafts |
| Chat full screen | `1326:37844` | project conversation expanded |
| Project start | `1339:40793` | `/projects/:projectId?phase=conversation` |
| Questionnaire | `1339:40689` | `/projects/:projectId?phase=questionnaire` |
| Agent running | `1339:41299` | reasoning / research running state |
| Plan | `1339:41222` | `/projects/:projectId?phase=planning` |
| Building | `1339:41346` | `/projects/:projectId?phase=generating` |
| Gallery grid | `1339:40217` | `/projects/:projectId/gallery` |
| Gallery alternate | `1339:40571` | gallery grouped / alternate layout |
| Website chat | `1339:41492` | website artifact conversation |
| Web edit mode | `1339:41713` | website artifact + Canvas Inspector |
| Artifact detail | `1339:41743` | `/projects/:projectId/artifacts/:artifactId` |
| Website export | `1339:41595` | artifact export state |
| Ad editor initial | `1339:40837` | canvas artifact |
| Ad editor selected | `1339:40959` | canvas selection + inspector |
| Ad editor alternate | `1339:41159` | canvas alternate selection |
| Ad editor final | `1339:41191` | canvas final selection |
| Ad export | `1339:41053` | canvas export state |
| Chat full screen (latest) | `1339:40822` | expanded conversation |
| Gallery full screen | `1339:40934` | expanded gallery |
| Project home | `1339:39903` | project overview |
| Group by account | `1339:40326` | gallery grouping enabled |
| Group by account alternate | `1339:40453` | grouped gallery alternate |
| Project start alternate | `1339:41810` | new project state |

## Reusable Figma components

| Component | Figma node |
| --- | --- |
| Chat input | `1339:48094` |
| Chat message | `1339:49296` |
| Chat header | `1339:49309` |
| Page header | `1339:49327` |
| Gallery tab | `1339:48842` |
| Gallery card | `1339:48861` |
| Chain of Thought | `1339:49094` |
| Reasoning | `1339:49178` |
| Canvas Inspector | `1339:48195` |

## Exported icon source

Project icons in `public/icons/projects` are SVG exports of the actual instances
used by the approved screens. `config/project-icon-sources.ts` is the single
asset registry consumed by the visual `ProjectIcon` component, so screens do
not recreate paths or import icon libraries. An automated test verifies every
registry entry resolves to a committed SVG and rejects the removed teal table
fallback.

`status-check.svg` is the deliberate exception: it is a compact Clue-token
status derivative used for tool, task, and picker completion states after the
raw Figma check proved too heavy at 12–14px. The original exported `check.svg`
remains untouched for provenance. The loader keeps its approved radial shape
but is normalized to the runtime 16px grid and rotated while work is active.

Artifact canvases that specify Inter load the self-hosted Inter variable family
from Fontsource. The surrounding Clue shell continues to use the bundled
Satoshi family from the design system.

Core Figma masters used for export:

- menu `1159:46007`
- link `1159:75467`
- pencil-ruler `1159:75463`
- maximize `1159:31569`
- chevron-down `1159:36067`
- plus `1159:32734`
- arrow-up `1159:75420`
- layout-grid `1159:31350`
- list `1164:100822`
- search `1159:30608`
- sparkles `1159:24856`
- ellipsis `1164:100537`
- check `1159:22924`
- x `1159:35667`
- image `1159:33146`
- telescope `1159:32093`
- brush `1164:101486`
- type `1159:30224`
- sheet-layout `1017:20112`
- web `904:86510`
- clipboard-list `1164:100828`
- target-accounts table layout `1164:100839`
- file-text `1164:101245`
- globe `1159:33480`
- laptop `1159:22896`
- chevrons-up-down `1159:32737`
- vertical-align start `1164:101196`
- vertical-align around `1159:35132`
- vertical-align end `1164:100765`

Target Accounts cards, tabs, and viewer headers all use the neutral table-layout
master inside the peach artifact container. The previous teal table glyph was
removed because it is not present in the approved project-flow screens.

## Working interaction shell

- Home and in-project account/contact autocomplete, model selection,
  recommendation prompts, file attachments, and project submission are
  controller-backed. `@` can be typed or opened explicitly; selections render
  as removable inline chips while stable IDs stay outside prompt text. Attachments
  use the locally installed AI Elements inline variant while resolving color,
  type, border, and radius aliases through Clue tokens. The Home surface
  intentionally contains no project gallery.
- The desktop shell sidebar collapses to a 56px icon rail and restores the
  approved expanded width with a 200ms transition; mobile navigation remains a
  separate drawer interaction.
- New chat creates and selects an in-project thread without remounting the shell.
- Gallery search, sort, type filtering, grouping, grid, and list controls update
  the local repository-backed artifact collection.
- Target accounts opens the table artifact; Gallery restores the gallery route.
- Conversation and artifact expand controls switch between split and focused
  workspace modes.
- The website viewer cycles desktop, tablet, and mobile widths and supports
  50%, 75%, and 100% zoom states.
- Export exposes the selected artifact file through a download link.
- The edit control opens Canvas Inspector; canvas, text, image, and button
  selection states remain separate from artifact and thread state. Typography,
  CTA copy, image fit, radius, and local image replacement update the preview.
- Questionnaire and plan transcript cards reopen their corresponding workspace
  surfaces, and generation details can be expanded or collapsed.
- Mock build progress stays visible for the designed 30-second interval and
  auto-scrolls the transcript while respecting reduced-motion preferences.

## Backend boundary

- UI components remain visual and receive typed props.
- `data/project-workspace.repository.ts` is the replaceable data boundary.
- `data/project-workspace.fixture.ts` contains local preview data only.
- Project, thread, run, artifact, selection, and inspector state remain distinct
  in `model/project-workspace.ts` so backend IDs can replace fixture IDs without
  changing the visual component tree.
