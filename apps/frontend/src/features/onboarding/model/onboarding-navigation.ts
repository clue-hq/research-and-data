import type { OnboardingStep } from "./onboarding";

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  "sign-in",
  "sign-in-email",
  "sign-up",
  "sign-up-email",
  "verify-email",
  "profile",
  "setting-up",
  "finalizing",
];

export function onboardingStepHref(step: OnboardingStep): string {
  return `/onboarding/${step}`;
}

export function authChoiceTarget(
  step: "sign-in" | "sign-up",
  method: "google" | "email",
): OnboardingStep {
  if (method === "google") return "profile";
  return step === "sign-in" ? "sign-in-email" : "sign-up-email";
}

export function authSwitchTarget(step: OnboardingStep): OnboardingStep {
  return step === "sign-in" || step === "sign-in-email" ? "sign-up" : "sign-in";
}

// Note: there is no submitTarget map anymore — every submit transition is an explicit
// outcome-driven decision in useOnboardingController (a credential result, a verification
// result, or a provisioning result), and the only timer-driven hop (setting-up → finalizing)
// lives with the fixture theatre it belongs to.
