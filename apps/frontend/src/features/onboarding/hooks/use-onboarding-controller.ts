"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { OnboardingStep } from "../model/onboarding";
import { validateProfileDraft } from "../model/onboarding";
import {
  authChoiceTarget,
  authSwitchTarget,
  onboardingStepHref,
} from "../model/onboarding-navigation";
import { useOnboardingAuth } from "../data/onboarding-auth";
import { useOnboardingDraft } from "../data/onboarding-draft";
import {
  OnboardingProvisionError,
  provisionWorkspace,
} from "../data/onboarding.repository";
import {
  clearWorkspaceSelection,
  selectWorkspace,
} from "@/features/session/data/session-actions";

export type { OnboardingDraft } from "../model/onboarding";

const SESSION_ESTABLISH_PATH = "/session/establish";

/**
 * Orchestrates the frozen screens over the headless auth adapter (FI-4 D-1) and the D-2
 * provisioning call. In fixture mode (auth off) it preserves the original design-review
 * navigation exactly — including the unvalidated profile walkthrough; in clerk mode every
 * transition is the result of a real credential or provisioning outcome.
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
  // Ref latch, not render-state: two clicks inside one React batch must not both pass.
  const inFlight = useRef(false);

  // The presentation-only setup timer exists ONLY for fixture mode's design-review theatre;
  // in clerk mode the setting-up screen renders LiveSetupScreen, driven by durable recon
  // lanes (slice 2) — nothing advances because time passed.
  const timerEligible = auth.mode === "fixture";
  useEffect(() => {
    if (!timerEligible || !autoAdvance || step !== "setting-up") return;

    const timeout = window.setTimeout(
      () => router.push(onboardingStepHref("finalizing")),
      3200,
    );

    return () => window.clearTimeout(timeout);
  }, [autoAdvance, router, step, timerEligible]);

  // Leaving a step clears its error/busy state (render-time reset, per React guidance);
  // the draft itself survives via the provider.
  // (inFlight is not reset here: refs must not be written during render, and run()'s
  // finally block always releases the latch when its action settles.)
  const [lastStep, setLastStep] = useState(step);
  if (lastStep !== step) {
    setLastStep(step);
    setError(null);
    setBusy(false);
  }

  function navigate(nextStep: OnboardingStep) {
    router.push(onboardingStepHref(nextStep));
  }

  function establishSession() {
    // A Route Handler target: use an explicit document navigation, not an RSC push.
    window.location.assign(SESSION_ESTABLISH_PATH);
  }

  async function run(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch {
      // Adapter operations should return typed errors, but this is the final containment seam for
      // provider/runtime exceptions. A rejected promise must never become a silent stuck screen.
      setError("We couldn't complete that request. Please try again.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function submitSignIn() {
    const result = await auth.signInWithPassword(draft.email, draft.password);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    if (auth.mode !== "clerk") {
      navigate("profile");
      return;
    }
    if (result.status === "complete") {
      establishSession();
      return;
    }
    // needs-verification: email MFA / device trust routes through the same
    // in-house verification screen as sign-up. Establishing the session here
    // with an incomplete sign-in used to bounce the user straight back to
    // /sign-in?reason=session_expired (founder-reported, 2026-08-17).
    navigate("verify-email");
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
    if (result.status === "complete" && result.flow === "sign-in") {
      // A verified sign-IN is an existing identity: establish the session.
      // Only a sign-UP continues into profile/provisioning.
      establishSession();
      return;
    }
    navigate("profile");
  }

  async function submitProfile() {
    if (auth.mode === "clerk") {
      // Fixture mode deliberately skips validation: the design-review walkthrough must
      // click through empty screens exactly as it did pre-integration.
      const invalid = validateProfileDraft(draft);
      if (invalid) {
        setError(invalid);
        return;
      }
    }
    const input = {
      first_name: draft.firstName.trim(),
      last_name: draft.lastName.trim(),
      job_role: draft.role.trim(),
      company_name: draft.companyName.trim() || null,
      company_website: draft.companyWebsite.trim() || null,
    };
    try {
      if (auth.mode === "clerk") {
        const provisioned = await provisionWorkspace(input);
        const selection = new FormData();
        selection.set("workspaceId", provisioned.workspace_id);
        await selectWorkspace(selection);
        // Slice 2: continue to the real setting-up screen; LiveSetupScreen owns starting
        // the (replay-safe) setup and releases into the app when the fast lane completes.
        // Selecting the exact provisioned workspace preserves FI-2's explicit-cookie rule;
        // onboarding never falls back to whichever membership happens to be first.
        navigate("setting-up");
        return;
      }
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
    pendingEmail: auth.pendingEmail,
    authMode: auth.mode,
    chooseAuthMethod: (method: "google" | "email") => {
      if (method === "email") {
        if (step === "sign-in" || step === "sign-up") {
          navigate(authChoiceTarget(step, "email"));
        }
        return;
      }
      // Google is live on all four auth screens (review finding FE2) — the email screens
      // render the same button and it must work there too.
      void run(async () => {
        const result = await auth.signInWithGoogle();
        if (result.status === "error") {
          setError(result.message);
          return;
        }
        if (auth.mode === "fixture") navigate("profile");
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
        // Same discipline as the app's sign-out: erase the workspace selection first, then
        // end the provider session even if the cookie clear failed.
        try {
          await clearWorkspaceSelection();
        } finally {
          await auth.signOut();
        }
        if (auth.mode === "fixture") navigate("sign-in");
      });
    },
    submit: () => {
      if (step === "sign-in-email") return void run(submitSignIn);
      if (step === "sign-up-email") return void run(submitSignUp);
      if (step === "verify-email") return void run(submitVerification);
      if (step === "profile") return void run(submitProfile);
      // setting-up/finalizing have no submit control; their transitions are the fixture
      // timer (fixture mode) or durable lane truth (clerk mode) — never a submit.
    },
  };
}
