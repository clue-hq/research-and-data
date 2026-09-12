# AI Elements and Clue agent-state architecture

Status: approved component set implemented and validated locally.

Owners: frontend implementation and Aaryan for backend integration.

This is the source of truth for how Clue uses Vercel AI Elements inside project
conversations. It records the product boundary, installed source, message-part
contract, Lightfield-inspired presentation rules, and backend handoff.

## Product boundary

The project conversation remains a Clue-owned interface. AI Elements does not
replace, wrap, or restyle the full chat.

Clue continues to own:

- the Home and workspace composer;
- message bubbles and assistant document text;
- project and thread headers;
- the split conversation, Gallery, artifact, and Inspector layout;
- account, contact, model, attachment, `@`, skill, and canvas-selection input;
- responsive behavior and Figma-approved motion;
- every visible product icon.

The approved AI Elements state primitives are limited to:

1. `Reasoning`;
2. `Shimmer`;
3. `Tool`;
4. `Task`;
5. `Plan`;
6. `Confirmation`;
7. `Sources`.

`Conversation`, `Message`, `PromptInput`, `Agent`, `Artifact`, `CodeBlock`, and
other catalog components are not part of the current implementation.

The inline attachment adapter was approved and implemented before this agent-
state decision. It remains an internal primitive inside the Clue composer; it
does not replace the composer or expand the state-component scope.

## Source ownership and theming

AI Elements installs component source into the repository. It is not a backend
service and no Vercel-hosted UI is embedded at runtime.

```text
src/components/ai-elements/
  attachments.tsx
  chain-of-thought.tsx
  confirmation.tsx
  plan.tsx
  reasoning.tsx
  shimmer.tsx
  sources.tsx
  task.tsx
  tool.tsx
```

The source primitives provide disclosure behavior, lifecycle semantics, and
accessibility. Feature adapters under `src/features/projects/components/`
provide Clue typography, spacing, tokens, copy, Figma SVGs, and data mapping.

```text
AI Elements primitive
  -> Clue project adapter
    -> ordered ProjectMessagePart data
      -> fixture or future backend event
```

Theme aliases in `src/app/globals.css` resolve all shared primitives through
Clue semantic tokens. Adapters additionally use the project CSS module where
the approved Figma component has more specific measurements. Default Vercel
colors, card prominence, prompt UI, and Lucide icons are not exposed in the
rendered project flow.

## Lightfield presentation rules

The Lightfield review established an interaction hierarchy, not a source-code
dependency. Clue applies these rules:

| Message part | Clue presentation |
| --- | --- |
| Normal assistant text | Unboxed document text |
| Reasoning | Quiet disclosure line; shimmer only while active |
| Chain of thought | Expandable, structured activity summary |
| Tool | Muted inline status; parameters/results appear on demand |
| Task | Compact progress list; active work is emphasized |
| Plan | Compact durable object; expandable summary |
| Confirmation | Bordered decision surface with explicit actions |
| Sources | Compact disclosure containing external evidence links |
| Artifact | Clue-owned Gallery or artifact pane, never an AI Elements card |

A card represents a durable object, material state change, or decision. A card
does not merely mean the agent is thinking.

## Current implementation map

| Responsibility | File |
| --- | --- |
| Runtime part schemas | `src/features/projects/model/chat-parts.ts` |
| Turn-event schema + SSE reader | `src/features/projects/model/chat-events.ts` |
| Event-to-transcript reducer | `src/features/projects/model/chat-transcript.ts` |
| Stream transport | `src/features/projects/data/chat-stream.repository.ts` |
| Message timeline | `src/features/projects/components/chat-transcript.tsx` |
| Part renderer | `src/features/projects/components/chat-message-part.tsx` |
| Consolidated reasoning disclosure | `src/features/projects/components/chat-reasoning.tsx` |
| Tool adapter | `src/features/projects/components/chat-tool-call.tsx` |
| Task adapter | `src/features/projects/components/chat-research-task.tsx` |
| Confirmation (gate) adapter | `src/features/projects/components/chat-gate-card.tsx` |
| Markdown renderer | `src/components/ai-elements/message-response.tsx` |
| Reading-position behavior | `src/features/projects/hooks/use-transcript-auto-scroll.ts` |

Visual TSX files receive typed props and callbacks. Fixtures and HTTP
repositories remain outside presentation code.

**As-built, Lane D slice D5 (2026-08-09).** The fixture-to-message adapter
(`build-project-messages.ts`) that assembled a transcript from a six-value phase
enum is deleted, along with the components that consumed its shape. The
transcript is now the durable message read plus the turn stream, reduced by
`chat-transcript.ts`.

## Ordered message-part contract

`chat-parts.ts` validates each part snapshot; every part carries a stable
`partId` and a `revision` that increases per emission, so a consumer replaces by
part id and never merges two half-cards. The union is:

```ts
type ChatPart =
  | ChatTextPart        // accumulated from text.start / text.delta / text.end
  | ChatReasoningPart   // model-round state, plus optional backend-supplied trace
  | ChatActivityPart    // ordered, durably-recorded observed steps
  | ChatToolPart        // toolName, toolCallId, structured input/output/error
  | ChatTaskPart        // one detached run as one visible task
  | ChatPlanPart        // a plan/directive snapshot plus its ref and revision
  | ChatGatePart        // the durable confirmation snapshot
  | ChatSourcesPart;    // real message-scoped source items
```

`PartKind.ACTION` exists in the backend enum with no payload model and no
emitter, so no `action` part is accepted here — a schema for it would be
invented rather than mirrored.

Every tool, task, gate and source record is repository data. Components do not
manufacture parameters, results, URLs, titles, or lifecycle states.

## Lifecycle ownership

The backend owns message IDs, turn IDs, ordering, tool states, gate state, run
progress, source records, failure recovery, and timestamps. The frontend owns
words, icons, and motion.

The six-value phase enum survives only as the `?phase=` **artifact-side preview
parameter** documented in `docs/api-contracts/projects.md`; no message, part, or
status is derived from it, and the timers that used to advance it are deleted.

The streaming envelope is no longer a recommendation: it is the shipped §3.2
turn-event contract, read by `chat-events.ts`.

```text
schema_version, event_id, sequence, occurred_at,
project_id, thread_id, turn_id, generation_attempt_id,
message_id?, part_id?, run_id?, delta_index?,
type, part?, delta?, error?

turn.accepted | turn.started | turn.awaiting_input | turn.completed |
turn.failed | turn.cancelled | turn.retrying |
part.created | part.updated | part.completed | part.failed | part.reset |
text.start | text.delta | text.end | stream.hello | stream.reset
```

`event_id` is the `Last-Event-ID` cursor and the deduplication key; `sequence`
is monotone within one turn. Part lifecycle events carry a full snapshot;
`text.delta` is append-only and index-ordered.

**Presentation ruling, 2026-09-12:** one inline `Reasoning` disclosure per
assistant response replaces the per-round completion labels and `ChainOfThought`
activity list. Round text is joined in stream order, without interpreting Markdown.
Backticks, fences and other syntax remain ordinary text in the Clue body font.
The disclosure is present only when the backend supplied non-empty trace text;
otherwise an active model round shows one shimmering Thinking label and a
completed round adds no status receipt. Tool results, tasks, gates, failures and
sources retain their own components.

Trace availability and retention are unchanged: the backend's development-only
`CLUE_CHAT_REASONING_TRACE_MODE=raw` may supply ephemeral provider text. It is not
saved in the durable conversation, and reload or stream reset can remove it.
This presentation change does not enable raw traces in production or persist them.

## Disclosure and scroll behavior

Each assistant response owns one disclosure. It opens when trace text first
arrives during a running turn. Manual collapse remains respected as more text
and model rounds arrive. It closes after the turn finishes, and can be reopened
while the text remains available. Historical disclosures start collapsed.

Trace text uses `white-space: pre-wrap` and `overflow-wrap: anywhere`, with a
256px vertical scroll limit. Final-answer Markdown remains formatted, but inline
code, fenced blocks and long strings wrap inside the available message width.
No code block or trace should create horizontal scrolling in the chat panel.

The transcript follows the reader:

- new content stays pinned only when the reader is already near the bottom;
- scrolling upward disables forced auto-scroll;
- the transcript never overlays a floating jump control on message content;
- expanding reasoning or tools does not steal the reading position;
- reduced-motion preferences disable smooth scrolling and animated emphasis.

## Composer boundary

The Clue composer is proprietary product UI and remains feature-owned.
`PromptInput` is not installed or evaluated as a replacement.

The structured reference model is now active for account and contact context:

```ts
type ComposerReference =
  | AccountReference
  | ContactReference
  | FileReference
  | SkillReference
  | CanvasSelectionReference;
```

Typing `@` or using the composer’s `@` control opens one grouped account/contact
picker at the caret. The prompt uses a local Slate editor with account and
contact references represented as inline void elements. This keeps a reference
inside the sentence and allows it to wrap with normal text without turning the
composer into a row of badges.

The visible reference is deliberately quiet: the Figma-approved logo or avatar,
the record label, and a subtle text treatment. It has no chip border, filled
background, or close icon. Clicking a reference selects that one atomic element;
`Backspace` or `Delete` removes only the selected reference and preserves the
surrounding draft. The picker supports keyboard navigation, `Enter`/`Tab`
selection, `Escape`, typed filtering, and pointer selection.

Prompt text and reference identity remain separate. The editor serializes plain
prompt text through `getPrompt()` and ordered stable CRM IDs through
`getEntityIds()`. Home carries those IDs into project creation; the project
composer sends them as `contextEntityIds`. Picker query, caret target, and active
option are local editor interaction state—not page or backend business state.

`/` should open Skills and actions, and editor selection should create a
removable reference containing stable artifact and node IDs. That editor work
remains separate from this AI Elements state integration.

Active reasoning uses `Shimmer` with no rotating loader or completion checkmark.
The chevron appears only when there is trace text to expand. Reduced motion
disables shimmer emphasis and disclosure animation. Task/tool presentation is
independent of reasoning and keeps its existing lifecycle indicators.

## Lightfield evidence limit

The Lightfield interface was inspected and read through its rendered product
and public documentation. Its private components, chain-of-thought source,
internal React architecture, and assets were not exported and are not present
in this repository.

Clue reproduces only the verified interaction modality: document-style
assistant text, quiet execution lines, progressive disclosure, selective
cards, explicit approval, sources, and reader-controlled scrolling. The actual
implementation uses Clue data contracts, Figma assets, and locally owned AI
Elements primitives.

## Validation record

Validated on 2026-09-12: consolidated disclosure lifecycle and transcript tests,
real-component browser checks at a 320px panel width with long backticks, URLs,
Markdown and fenced JSON (no horizontal overflow), plus the design-system build,
lint and production build. Test samples are isolated at the local preview; no
provider calls or backend trace-retention changes were made.

Validated on 2026-08-01:

- fixture messages pass Zod parsing and ordered-part tests;
- TypeScript passes with no emitted output;
- ESLint passes with zero warnings;
- the repository test suite passes;
- planning, reasoning, tool, task, plan, confirmation, and sources states were
  exercised in localhost;
- reasoning disclosures were verified as independent;
- the split workspace was checked at the normal viewport, 1024px, and 800px
  with no horizontal document overflow;
- browser console errors were checked during rendered QA;
- the optimized Next.js production build passes.
- shimmer background position was sampled at two live points and changed;
- loader rotation, grouped `@` search, account/contact selection, direct typed
  mention filtering, inline wrapping, atomic Backspace removal, and
  Home-to-project ID handoff were exercised in localhost.

Official component references:

- <https://elements.ai-sdk.dev/components/reasoning>
- <https://elements.ai-sdk.dev/components/chain-of-thought>
- <https://elements.ai-sdk.dev/components/tool>
- <https://elements.ai-sdk.dev/components/task>
- <https://elements.ai-sdk.dev/components/plan>
- <https://elements.ai-sdk.dev/components/confirmation>
- <https://elements.ai-sdk.dev/components/sources>
- <https://elements.ai-sdk.dev/components/shimmer>
