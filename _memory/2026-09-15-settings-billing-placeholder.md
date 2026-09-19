# Billing placeholder and Pages scope — 2026-09-15

- Founder clarified that Pages is part of V1 but still needs development; its temporary overlay may remain. Then explicitly requested removing the Billing overlay and keeping its dummy frontend visible.
- Billing now renders directly in the standard Settings body. Its existing plan/credit fixtures and presentation-only buttons are unchanged. Pages and the other unavailable sections retain their overlays.
- Updated the Settings spec's A1 and affected sections plus the frontend API contract to record the founder's ruling rather than the earlier overlay assumption.
- ChatGPT in-app browser verified the real Billing component with its existing static data through a temporary route: plan/credits cards visible, no Coming soon text/blur, buttons outside inert or aria-hidden ancestors. The temporary route was removed after verification. The protected live route could not be rechecked because the existing browser session remains expired; no auth changes were made.
- Final gate passed: design-system build, lint (only the two pre-existing design-editor unused-helper warnings), production build, changed-TSX Prettier check, and `git diff --check`. React review found no new hooks, data fetching, or interaction behavior. No backend or fleet changes.
