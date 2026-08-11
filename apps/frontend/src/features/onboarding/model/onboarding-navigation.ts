import type { OnboardingStep } from "./onboarding";

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  "sign-in",
  "sign-in-email",
  "sign-up",
  "sign-up-email",
  "profile",
  "setting-up",
  "finalizing",
];

export function onboardingStepHref(step: OnboardingStep) {
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

export function submitTarget(step: OnboardingStep): OnboardingStep | null {
  if (step === "sign-in-email" || step === "sign-up-email") return "profile";
  if (step === "profile") return "setting-up";
  if (step === "setting-up") return "finalizing";
  return null;
}
