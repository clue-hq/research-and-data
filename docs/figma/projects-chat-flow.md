# Projects / chat flow fidelity map

Source file: `NcLl2r0dzVDN28xAQCwvM1`
Source page: `Projects/chat flow` (`1326:37155`)
Reference viewport: `1680 × 945`

This map separates the visual source from data and interaction state. Components
render values passed from the project repositories; Figma copy is represented by
fixtures only when no API base URL is configured.

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
