# Onboarding flow implementation

Status: implemented from the seven designer-authored frames marked Ready for
dev on the production `onboarding-flow` page. The separate `Onboarding flow ·
Production V2` exploration is explicitly out of scope and is not represented in
the frontend.

## Source of truth

- File: Clue (`NcLl2r0dzVDN28xAQCwvM1`)
- Page: `onboarding-flow` (`1634:16661`)
- Approved frame size: 1680 × 945
- Typography: Satoshi through the local Clue design system

## Approved node and route mapping

| Approved screen | Figma node | Frontend route |
| --- | --- | --- |
| Sign in · provider choice | `1764:71523` | `/onboarding/sign-in` |
| Sign in · email | `1762:70819` | `/onboarding/sign-in-email` |
| Sign up · provider choice | `1764:71668` | `/onboarding/sign-up` |
| Sign up · email | `1764:71604` | `/onboarding/sign-up-email` |
| Profile | `1764:71391` | `/onboarding/profile` |
| Setting up · checklist | `1775:78768` | `/onboarding/setting-up` |
| Setting up · finalizing | `1775:78734` | `/onboarding/finalizing` |

Append `?hold=1` to `/onboarding/setting-up` for deterministic visual QA
without the presentation-only automatic transition.

## Component boundary

- Route and repository: validated server-side flow payload.
- `useOnboardingController`: draft state, route transitions, and the mock setup
  timer.
- `OnboardingScreen`: approved-screen selection and visual composition.
- `AuthScreen`, `ProfileScreen`, `SetupScreen`: independent visual components.
- `OnboardingHeader` and `OnboardingFooter`: exact shared framing used by the
  approved authentication and profile screens.

## Fidelity notes

- The round portrait visible beside the setup frame in Figma is a comment pin,
  not product artwork, and is intentionally excluded.
- The Clue logo is the production SVG at `public/logos/clue-sidebar.svg`.
- The old generated brand landscape and workflow panel assets were removed;
  neither exists in the approved frames.
- Screen copy and mock values live in `onboarding.fixture.ts`, outside the
  visual components.

## Verification checklist

- [x] Tests pass.
- [x] Lint passes.
- [x] Production build passes.
- [x] All seven routes render against the approved 1680 × 945 geometry.
- [x] Sign-in, sign-up, profile, and setup transitions work.
- [ ] Mobile layout has no horizontal overflow.
