"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { OnboardingStep } from "../model/onboarding";
import {
  authChoiceTarget,
  authSwitchTarget,
  onboardingStepHref,
  submitTarget,
} from "../model/onboarding-navigation";
import { useOnboardingAuth } from "../data/onboarding-auth";
import { useOnboardingDraft } from "../data/onboarding-draft";
import {
  OnboardingProvisionError,
  provisionWorkspace,
  provisionWorkspaceFixture,
} from "../data/onboarding.repository";

export type { OnboardingDraft } from "../model/onboarding";

const SESSION_ESTABLISH_PATH = "/session/establish";

/**
 * Orchestrates the frozen screens over the headless auth adapter (FI-4 D-1) and the D-2
 * provisioning call. In fixture mode (auth off) it preserves the original design-review
 * navigation exactly; in clerk mode every transition is the result of a real credential or
 * provisioning outcome — nothing advances on a timer except the untouched setup theatre,
 * which slice 2 replaces with real recon progress.
 */
export function useOnboardingController({
  step,
  autoAdvance,
}: {
  step: OnboardingStep;
  autoAdvance: boolean;
}) {
  const router = useRouter();
  const auth = useOnboardingAuth();
  const { draft, updateDraft } = useOnboardingDraft();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The presentation-only setup timer survives slice 1 untouched: with auth off it keeps the
  // approved review flow alive, and with auth on the profile step exits to the app before
  // these steps are reached. Slice 2 (real recon progress) deletes it.
  useEffect(() => {
    if (!autoAdvance || step !== "setting-up") return;

    const timeout = window.setTimeout(
      () => router.push(onboardingStepHref("finalizing")),
      3200,
    );

    return () => window.clearTimeout(timeout);
  }, [autoAdvance, router, step]);

  // Leaving a step clears its error/busy state (render-time reset, per React guidance);
  // the draft itself survives via the provider.
  const [lastStep, setLastStep] = useState(step);
  if (lastStep !== step) {
    setLastStep(step);
    setError(null);
    setBusy(false);
  }

  function navigate(nextStep: OnboardingStep) {
    router.push(onboardingStepHref(nextStep));
  }

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  async function submitSignIn() {
    const result = await auth.signInWithPassword(draft.email, draft.password);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    if (auth.mode === "clerk") {
      router.push(SESSION_ESTABLISH_PATH);
      return;
    }
    navigate("profile");
  }

  async function submitSignUp() {
    const result = await auth.signUpWithPassword(draft.email, draft.password);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    if (result.status === "complete") {
      // Verification is normally required; a Clerk instance with it off completes here.
      navigate("profile");
      return;
    }
    navigate("verify-email");
  }

  async function submitVerification() {
    const result = await auth.verifyEmailCode(draft.verificationCode.trim());
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    navigate("profile");
  }

  function validateProfile(): string | null {
    if (!draft.firstName.trim() || !draft.lastName.trim()) {
      return "Please enter your first and last name.";
    }
    if (!draft.role.trim()) return "Please select your role.";
    if (!draft.companyName.trim()) return "Please enter your company name.";
    if (!draft.companyWebsite.trim()) return "Please enter your company website.";
    return null;
  }

  async function submitProfile() {
    const invalid = validateProfile();
    if (invalid) {
      setError(invalid);
      return;
    }
    const input = {
      first_name: draft.firstName.trim(),
      last_name: draft.lastName.trim(),
      job_role: draft.role.trim(),
      company_name: draft.companyName.trim(),
      company_website: draft.companyWebsite.trim() || null,
    };
    try {
      if (auth.mode === "clerk") {
        await provisionWorkspace(input);
        router.push(SESSION_ESTABLISH_PATH);
        return;
      }
      await provisionWorkspaceFixture(input);
      navigate("setting-up");
    } catch (caught) {
      setError(
        caught instanceof OnboardingProvisionError
          ? caught.message
          : "We couldn't set up your workspace. Please try again.",
      );
    }
  }

  return {
    draft,
    updateDraft,
    busy,
    error,
    accountEmail: auth.email,
    chooseAuthMethod: (method: "google" | "email") => {
      if (step !== "sign-in" && step !== "sign-up") return;
      if (method === "email") {
        navigate(authChoiceTarget(step, "email"));
        return;
      }
      void run(async () => {
        const result = await auth.signInWithGoogle();
        if (result.status === "error") {
          setError(result.message);
          return;
        }
        if (auth.mode === "fixture") navigate(authChoiceTarget(step, "google"));
        // In clerk mode the OAuth redirect is already in flight.
      });
    },
    switchAuthMode: () => navigate(authSwitchTarget(step)),
    resendVerification: () => {
      void run(async () => {
        const result = await auth.resendEmailCode();
        if (result.status === "error") setError(result.message);
      });
    },
    logOut: () => {
      void run(async () => {
        await auth.signOut();
        if (auth.mode === "fixture") navigate("sign-in");
      });
    },
    submit: () => {
      if (step === "sign-in-email") return void run(submitSignIn);
      if (step === "sign-up-email") return void run(submitSignUp);
      if (step === "verify-email") return void run(submitVerification);
      if (step === "profile") return void run(submitProfile);
      const nextStep = submitTarget(step);
      if (nextStep) navigate(nextStep);
    },
  };
}
