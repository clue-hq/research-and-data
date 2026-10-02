# Home suggestion labels and draft insertion — 2026-09-12

- Founder reported the second Home suggestion mirroring the draft, and requested suggestion clicks populate the composer.
- Removed the draft-dependent suggestion mapping from `use-project-home-controller.ts`; Home now displays the repository's original suggestions directly. Existing suggestion buttons already call `setPrompt`, which synchronizes into the Slate editor without submitting.
- Live Semarang browser verification: typing arbitrary text left all three labels unchanged; clicking each suggestion replaced the composer with its exact text and stayed on Home. Cleared the test draft afterward. No chat/research/design request was submitted.
- Focused existing Home/repository/composer tests: 13 passed. Design-system build, lint and production build passed; lint retains two existing unused-variable warnings in unchanged design-engine code. This is a frontend-only change; no service restart, backend contract or data change required.
- Closing state: ready and live on Semarang frontend 3040; commit/push to `brand-context-polish` follows the standing founder instruction. No unresolved defect in this slice.
