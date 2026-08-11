"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { OnboardingFlow, OnboardingStep } from "../model/onboarding";
import {
  authChoiceTarget,
  authSwitchTarget,
  onboardingStepHref,
  submitTarget,
} from "../model/onboarding-navigation";

export type OnboardingDraft = OnboardingFlow["account"] & {
  password: string;
};

export function useOnboardingController({
  step,
  autoAdvance,
}: {
  step: OnboardingStep;
  autoAdvance: boolean;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<OnboardingDraft>({
    email: "",
    password: "",
    firstName: "",
    lastName: "",
    role: "",
    companyName: "",
    companyWebsite: "",
  });

  useEffect(() => {
    if (!autoAdvance || step !== "setting-up") return;

    const timeout = window.setTimeout(
      () => router.push(onboardingStepHref("finalizing")),
      3200,
    );

    return () => window.clearTimeout(timeout);
  }, [autoAdvance, router, step]);

  function updateDraft<Key extends keyof OnboardingDraft>(
    key: Key,
    value: OnboardingDraft[Key],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function navigate(nextStep: OnboardingStep) {
    router.push(onboardingStepHref(nextStep));
  }

  return {
    draft,
    updateDraft,
    chooseAuthMethod: (method: "google" | "email") => {
      if (step === "sign-in" || step === "sign-up") {
        navigate(authChoiceTarget(step, method));
      }
    },
    switchAuthMode: () => navigate(authSwitchTarget(step)),
    submit: () => {
      const nextStep = submitTarget(step);
      if (nextStep) navigate(nextStep);
    },
  };
}
