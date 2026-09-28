# Onboarding Role select

- User requested the Role dropdown on /onboarding/profile match the brand design system.
- Reused shared SelectField instead of a native select and local chevron. Removed obsolete selectShell CSS. Only the onboarding trigger height/padding is adapted to its 44px form fields; shared typography, radius, focus, popup and keyboard behavior stay centralized.
- Kept the same placeholder, role options and draft update callback. No submission, provisioning or API changes.
- Browser verification used a temporary tab because the user's own tab had already moved to setting-up. Verified branded popup, Founder selection, ArrowDown opening, Escape closing and focus restoration. Computed trigger: 44px high, 4px corners, Satoshi, button type (does not submit the form). Test tab closed; no form submitted.
- Token generation and lint passed (two existing unused-helper warnings in canvasOperations.ts). Production build passed, including TypeScript and page generation, from a temporary frontend copy with shared installed dependencies. Live frontend and ingestion workers were not restarted.
- Closing state: UI change and browser verification complete, diff whitespace clean. Local commit only; no push. User's ongoing ingestion tab preserved.
