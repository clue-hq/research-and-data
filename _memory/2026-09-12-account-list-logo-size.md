# Account-list logo sizing — 2026-09-12

Founder requested larger logos in Accounts and the project's Target accounts tab.
Both use AccountsTable / AccountTableRow. Increased its company image from 12px to
24px (CSS and intrinsic dimensions), keeping contain and shrink-0. Fallback glyphs
share the sizing. Existing compact/comfortable/spacious rows are 44/56/64px.

Live Semarang Accounts browser check: image loaded, computed size 24x24, object-fit
contain, flex-shrink 0; screenshot confirmed alignment. The current project's Target
accounts list is empty; its shared AccountsTable renderer was verified in code. No
accounts were added or changed for the visual check. Temporary browser tab closed.

Frontend design-system build, lint and production build passed; only the existing
canvasOperations unused-function warnings remain. No backend/runtime changes or new
unit tests for this three-line presentation change. Founder also sent a truncated
additional request; asked for the missing text asynchronously, with no answer yet.
