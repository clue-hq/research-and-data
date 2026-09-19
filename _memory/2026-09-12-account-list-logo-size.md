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

## Follow-up: account preview logo

Founder clarified the next change with an account-preview screenshot: enlarge that
logo too and reduce its surrounding space. In shared AccountIdentity, increased
the image from 36px to 56px inside the existing 68px tile, reducing each inset from
16px to 6px. CSS and intrinsic dimensions match; contain preserves proportions and
shrink-0 prevents compression. The shared component also covers account details,
research overview and the project account preview.

Live Semarang browser confirmed loaded 56x56 image, 68x68 tile, 6px insets and contain;
screenshot reviewed. Design-system build, lint and production build passed, with
only the same two existing canvasOperations warnings. git diff --check passed.
An initial file search failed because zsh expanded an unmatched wildcard; reran
the search against the components directory. No backend, data or server changes.
