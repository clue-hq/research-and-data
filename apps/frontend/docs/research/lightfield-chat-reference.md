# Lightfield chat reference for Clue

Status: research complete; approved Clue adaptation implemented.

Research date: 2026-08-01.

This document is the canonical product-reference record for the Lightfield chat
study. It describes what was observed, what is supported by Lightfield's public
documentation, and which interaction principles Clue should adopt. It does not
claim access to Lightfield's private source code or internal component library.

## Research coverage

The review covered:

- the user-provided Lightfield chat screenshot;
- an authenticated Lightfield workspace, account table, and existing chat
  thread;
- the live `@` reference chooser without submitting a message;
- Lightfield's setup and agent-capability documentation;
- Lightfield changelog entries for long-running chat, file attachments,
  streaming, model persistence, code execution, and generated artifacts;
- Lightfield's public guide to Skills and Knowledge.

Primary sources:

- <https://support.lightfield.app/articles/7600587835-lightfield-setup-guide>
- <https://support.lightfield.app/articles/3377945369-section-4a-what-the-agent-can-do>
- <https://lightfield.app/blog/how-to-skills-knowledge>
- <https://lightfield.app/blog/rest-api-agentic-csv-import>
- <https://lightfield.app/blog/up-next-improved-contact-view-more-in-workflows>
- <https://lightfield.app/blog/sending-http-requests-workflow-improvements-files-and-more>
- <https://lightfield.app/blog/code-execution-in-lightfield>
- <https://lightfield.app/blog/improved-chat-data-model-flexibility>

## Principal finding

Lightfield's calm appearance is not the result of a basic agent. Its public
product supports record-scoped context, actions, long-running work, files,
skills, code execution, and structured artifacts. The interface remains simple
because the default presentation is a readable document timeline.

Lightfield uses hierarchy in this order:

1. plain text for normal assistant communication;
2. muted inline text for execution updates;
3. small inline references for CRM objects;
4. bordered objects only for durable results, field changes, or approval;
5. popovers only for temporary selection.

Clue should adopt this hierarchy. It should not render every tool, reasoning
step, or task as an equally prominent card.

## Observed visual system

### Application shell

- A persistent approximately 250px sidebar holds both product navigation and
  recent chat history.
- Sidebar groups are quiet text labels rather than decorated containers.
- The thread header is one compact row with the title and secondary actions.
- The main conversation is a narrow reading column inside a large open canvas.
- The visual system is nearly monochrome. Border, weight, spacing, and position
  establish hierarchy before color.

### Message presentation

- User messages are compact, pale neutral pills aligned to the right.
- Assistant messages are unboxed and read like a document.
- Assistant attribution is small and low contrast.
- Paragraphs, lists, and bold subheadings carry the response structure.
- Execution statements such as code or data retrieval are quiet inline status
  lines rather than full-width progress cards.
- Related CRM records appear as inline, recognizable references.

### Cards and approvals

Cards are used selectively. The authenticated thread showed:

- a proposed CRM field update with a before/after preview;
- `Dismiss` and `Approve` controls;
- an `Ask every time` permission control;
- a durable note result represented as a compact object row.

This is an important product rule: a card represents an object, a material
state change, or a decision. It does not merely represent that the agent is
thinking.

### Composer

- The composer floats at the bottom of the reading column.
- It uses a soft border and restrained shadow to separate it from content.
- Secondary controls stay visually subordinate to the prompt.
- A separate jump-to-bottom control appears above the composer when needed.
- The composer accepts file attachments.

Lightfield states publicly that it disabled forced autoscrolling during
streaming, added a jump-to-bottom control, and remembers the selected model
across sessions. These details materially improve long-response reading.

## Observed `@` reference behavior

Entering `@` in the authenticated composer opened one grouped listbox. The
visible groups were:

- Accounts;
- Contacts;
- Opportunities;
- Team members;
- Notes;
- Lists.

The menu is contextual and compact. It does not first ask the user to choose a
record type in a separate dialog. Each option is a structured object reference,
not plain text. Assistant responses also render referenced records as
interactive inline entities.

The Clue equivalent should use a single `@` surface with grouped results. It
should not maintain separate account and contact buttons that compete with the
prompt. In the inspected composer, selected records behaved as atomic inline
objects rather than detached chips: the record sits in the sentence, clicking
selects that reference, and Backspace removes the selected reference without
removing the surrounding draft.

The implemented Clue treatment mirrors the observed visual grammar: 15px/22px
composer text, a 16px logo or avatar, a 5px icon-to-label gap, a visible 1px
neutral underline beneath the record label, and a pale blue focus surface when
the atomic reference is selected. The underline is applied directly to the
label rather than the outer rich-text wrapper so it remains visible through the
editor's nested inline-void markup.

## Product behavior behind the quiet interface

Public Lightfield material confirms these behaviors:

- global chat and record-scoped chat;
- automatic current-record context when chat is opened from a record;
- workspace data access across accounts, contacts, opportunities, emails,
  meetings, transcripts, and notes;
- record updates, drafted communication, analysis, and multi-step Skills;
- drag-and-drop file attachment in chat;
- long-running tasks with progress, resumption, completion notification, and
  explicit requests for user input;
- preserved partial responses after interruption or failure;
- code execution for analysis and structured artifacts;
- a separation between repeatable Skills and durable Knowledge.

The frontend implication is that simplicity must be achieved through
progressive disclosure, not by removing lifecycle states or backend IDs.

## Recommended Clue adaptation

### Copy the interaction hierarchy

Clue should use the following presentation rules:

| Message part | Default presentation |
| --- | --- |
| User prompt | Compact right-aligned neutral pill |
| Assistant answer | Unboxed document text |
| Thinking | One quiet line with shimmer; collapsible detail |
| Tool execution | Muted inline status; expand only on request or failure |
| Sources | Inline references with an optional compact disclosure |
| Task progress | Compact ordered list; promote only the active or failed step |
| Plan | Short readable plan; card only when approval is required |
| Confirmation | Bordered decision card with explicit consequence and actions |
| Record mutation | Before/after or proposed-value card |
| Artifact | Durable preview row or card that opens the artifact pane |
| Error | Concise inline error plus retry/recovery action |

### Preserve the Clue workspace difference

Lightfield is the reference for conversation density and record context. Clue
still owns a different artifact workspace:

- a conversation pane and Gallery/artifact pane;
- editable website, ad, presentation, and table artifacts;
- Canvas Inspector and manual element controls;
- project/thread/artifact traceability.

When no artifact exists, the Clue conversation can use a centered Lightfield-
like reading column. When an artifact opens, the same timeline moves into the
left pane without changing its message grammar.

### Add editor-selection context

The Clue-specific addition is a structured reference to the selected object in
an artifact editor. Selecting a headline, image, CTA, table, or other editable
node should make a small removable reference available in the composer.

The reference should contain:

```ts
interface CanvasSelectionReference {
  artifactId: string;
  iconKey: string;
  label: string;
  nodeId: string;
  nodeType: "canvas" | "group" | "image" | "shape" | "table" | "text";
  type: "canvas-selection";
}
```

Recommended behavior:

1. selecting an editor object creates or updates one current-selection chip;
2. the chip displays the Figma-approved icon and a short label such as
   `Headline · Hero`;
3. the chip has an accessible remove button;
4. removing it clears only prompt context, not the canvas selection itself;
5. submission stores a snapshot of the reference with the message;
6. the backend receives stable artifact and node IDs, never only the label;
7. opening the historical reference focuses the same node when it still exists;
8. deleted or replaced nodes render a safe unavailable state.

This is the natural extension of Lightfield's record references: Accounts and
Contacts identify business context; `canvas-selection` identifies editing
context.

### Unify the composer reference model

Use one structured contract for all prompt context:

```ts
type ComposerReference =
  | AccountReference
  | ContactReference
  | OpportunityReference
  | NoteReference
  | ListReference
  | SkillReference
  | FileReference
  | CanvasSelectionReference;
```

Suggested triggers:

- `@` for CRM records and project objects;
- `/` for Skills and actions;
- attachment control or drag/drop for files;
- editor selection for the current canvas node;
- a separate compact control for model selection.

The visual chip can be shared, but each reference type keeps its own icon,
payload, validation, and open/focus behavior.

## Recommended component boundary

```text
ProjectConversation
  MessageTimeline
    UserMessage
    AssistantMessage
      MessagePartRenderer
        TextPart
        AgentActivityPart
        ToolPart
        SourcesPart
        ConfirmationPart
        RecordMutationPart
        ArtifactPart
  ProjectComposer
    StructuredPromptEditor
    ReferenceChip
    ReferenceMenu
    AttachmentList
    ModelMenu
```

AI Elements supplies only the approved reasoning, shimmer, structured
activity, tool, task, plan, confirmation, and source primitives. Clue adapters
control their typography, spacing, disclosure rules, icons, and data contracts.
The Clue composer and message UI are explicitly excluded. The current
recommendation to use a structured editor for cursor-level references remains
compatible with the observed Lightfield behavior.

## What not to copy

- Do not copy Lightfield's entire sidebar information architecture. Clue's
  project and Gallery model is different.
- Do not hide approvals for external, publishing, paid, or destructive actions.
- Do not reduce the Gallery to a chat attachment list.
- Do not make selected editor elements plain prompt text.
- Do not infer or claim Lightfield's internal React packages from rendered DOM.
- Do not adopt screenshots or Lightfield assets; reproduce only interaction
  principles with Clue's Figma-approved tokens and icons.

## Implementation state

Implemented now:

1. ordered typed message parts without replacing Clue message presentation;
2. document-style hierarchy and selective-card rules;
3. Clue-themed reasoning, activity trace, tool, task, plan, confirmation,
   sources, and shimmer states;
4. reader-controlled bottom anchoring and jump-to-latest behavior;
5. one grouped account/contact `@` menu inside a structured prompt editor;
6. cursor-level atomic record references with logo/avatar, keyboard navigation,
   inline wrapping, and reference-only Backspace/Delete behavior;
7. prompt text and ordered record IDs serialized separately for handoff;
8. normal, 1024px, and 800px split/stacked layout validation.

Still separate future work:

1. add `canvas-selection` as a Clue-only reference type;
2. add `/` Skills and action references to the same structured-editor model;
3. connect paused, failed, resumed, and completed lifecycle events to backend
   run data;
4. add mutation-preview cards when a backend mutation flow is approved.

## Acceptance criteria

- Normal assistant responses do not render inside cards.
- Only actionable or durable objects receive prominent containers.
- `@` presents one grouped, keyboard-accessible reference menu.
- References submit stable IDs and display readable labels.
- Every reference is removable before submission.
- Canvas-selection context contains artifact and node IDs.
- The conversation does not force-scroll when the user is reading older text.
- A jump-to-bottom control appears when the latest message is off-screen.
- Partial and failed agent output remains visible and recoverable.
- All icons come from the Clue Figma asset registry.
- No visual component owns backend orchestration or fixture imports.

## Evidence limits

The research supports an interaction and visual recommendation. It does not
establish Lightfield's internal file structure, source component boundaries,
framework, or dependency choices. Those details are private and cannot be
reliably inferred from the production UI. Clue's component architecture should
therefore follow its own production boundaries documented in this repository.
