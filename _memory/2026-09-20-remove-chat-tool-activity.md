# Remove tool activity rows from chat

- Founder requested removing the component behind the marked “Complete a project
  step” / “Save your answer” rows throughout the chat UI, not just one conversation.
- Shared `ChatMessagePartView` now returns null for every tool part/state. Removed
  its ChatToolCall import; history and live streams use this same renderer.
- Presentation-only change: tool execution/events/wire data remain intact. Reasoning,
  response text, task/plan cards and approval UI remain independently rendered.
- Updated the chat presentation contract and visual register. Browser and frontend
  gate verification in progress; no provider call or message submission needed.

## Verification

- Live browser and full reload: zero tool-activity elements, four messages and two
  reasoning disclosures still present. No blank activity wrappers or message submission.
- 64 existing transcript/reasoning tests passed. Token generation and lint passed
  (only the two existing canvasOperations unused-function warnings).
- Production build and git diff whitespace checks passed. Change complete and saved
  as a local commit; no remote publication and no backend edits.
