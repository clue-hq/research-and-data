# Remove Inspect from the chat interface

- Founder requested removing the Inspect control beside assistant responses for release.
- Removed the transcript button, callback prop and trigger styles; disconnected the
  inspector controller and drawer from ConversationContent, including its unused projectId prop.
- Chat no longer probes inspector availability. Backend diagnostic routes and records are
  unchanged. Updated the canonical projects contract to describe the UI removal.
- Verification: `npm run design-system:build`, `npm run lint`, and `npm run build` passed.
  Lint reports two existing unused-function warnings in untouched canvasOperations.ts.
- Browser smoke on the founder's existing Damascus chat: both Inspect buttons disappeared
  after hot reload; assistant attribution, reasoning controls, transcript and composer still
  render. Confirmed by accessibility state and screenshot. No new chat turn submitted.
- Reviewed the three changed TSX components for hook, prop and accessibility regressions;
  `git diff --check` passed. No new tests needed for this UI-only removal.
- Closing state: ready for local commit; no services restarted, no remote publication.
