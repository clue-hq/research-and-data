# Asset Details panel height

- User requested the Details column span the full floating asset window.
- Removed the late duplicate `.assetDialogDetails` rule that imposed `max-height: 80vh`. The original grid item already stretches and has `min-height: 0` plus `overflow-y: auto`; existing mobile split rows remain unchanged.
- Live browser verification: modal height 924px, preview and Details both 922px inside the borders, identical top/bottom bounds, computed max-height none. Details scrolled independently to its bottom while the preview stayed fixed. Returned Details to the top; no asset fields changed.
- Browser locator evaluation timed out twice despite the modal being present; direct read-only DOM geometry evaluation worked. No UI reload or service restart needed.
- Token generation, lint and production build passed, with the two existing unused-helper lint warnings in canvasOperations.ts. Production build ran in an isolated temporary frontend copy to preserve the live dev server.
- Closing state: fix is live, browser verified, and complete. Local commit only; no push. No ingestion data or running services changed.
