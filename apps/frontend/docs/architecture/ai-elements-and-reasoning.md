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
3. `ChainOfThought`;
4. `Tool`;
5. `Task`;
6. `Plan`;
7. `Confirmation`;
8. `Sources`.

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
| Runtime message schemas | `src/features/projects/model/project-workspace.ts` |
| Fixture-to-message adapter | `src/features/projects/data/build-project-messages.ts` |
| Message timeline | `src/features/projects/components/project-message-timeline.tsx` |
| Part renderer | `src/features/projects/components/project-message-part.tsx` |
| Reasoning adapter | `src/features/projects/components/reasoning.tsx` |
| Activity-trace adapter | `src/features/projects/components/chain-of-thought.tsx` |
| Tool adapter | `src/features/projects/components/project-tool-activity.tsx` |
| Task adapter | `src/features/projects/components/generation-progress.tsx` |
| Plan adapter | `src/features/projects/components/project-plan-summary.tsx` |
| Confirmation adapter | `src/features/projects/components/plan-approval.tsx` |
| Sources adapter | `src/features/projects/components/project-sources.tsx` |
| Reading-position behavior | `src/features/projects/hooks/use-transcript-auto-scroll.ts` |

Visual TSX files receive typed props and callbacks. Phase-to-message assembly
lives in the data adapter, not inside the page component. Fixtures and HTTP
repositories remain outside presentation code.

## Ordered message-part contract

`ProjectMessageSchema` validates the transcript structure. Every message has a
stable ID, role, optional assistant label, and ordered parts. The current union
contains:

```ts
type ProjectMessagePart =
  | TextPart
  | ReasoningPart
  | ActionPart
  | ToolPart
  | PlanPart
  | TaskPart
  | SourcesPart;
```

The frontend fixture adapter produces the current Figma preview sequence. The
backend can later return the same ordered structure or stream compatible part
events without changing the visual adapters.

Every tool and source record is fixture/repository data. Components do not
manufacture parameters, results, URLs, titles, or lifecycle states.

## Lifecycle ownership

The preview phases remain:

```text
conversation
  -> questionnaire
  -> agent-running
  -> planning
  -> generating
  -> complete
```

Preview timers demonstrate Figma states only. In production, the backend owns
message IDs, run IDs, ordering, tool states, approval state, progress, source
records, failure recovery, and timestamps.

Recommended streaming event envelope:

```ts
interface ProjectMessagePartEvent {
  messageId: string;
  part: ProjectMessagePart;
  partId: string;
  runId?: string;
  sequence: number;
  threadId: string;
  type: "part.created" | "part.updated" | "part.completed" | "part.failed";
}
```

The UI exposes user-visible activity summaries. It does not require or display
private raw model chain-of-thought. The product label may say “Thought” while
the backend contract uses `ReasoningTrace` or `AgentActivity`.

## Disclosure and scroll behavior

Each reasoning block owns independent disclosure state. Expanding a completed
step must not expand earlier reasoning blocks.

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

Active reasoning and task labels use the shared `Shimmer` primitive. Its
background position loops continuously; task and tool loader SVGs rotate while
running. Completed states use the compact Clue status check rather than a large
bare tick.

Every streaming reasoning status, including the initial `Thinking` state and
`landing agent is running...`, places the same rotating loader immediately
before the shimmer label. A disclosure chevron is rendered only when the status
has detail or an activity trace to expand.

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
