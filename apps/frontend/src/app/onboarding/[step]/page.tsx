import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { isAuthenticationEnabled } from "@/auth/config";
import { OnboardingScreen } from "@/features/onboarding/components/onboarding-screen";
import { getOnboardingFlow } from "@/features/onboarding/data/onboarding.repository";
import {
  isOnboardingStep,
  type OnboardingStep,
} from "@/features/onboarding/model/onboarding";
import { ONBOARDING_STEPS } from "@/features/onboarding/model/onboarding-navigation";

const screenTitles: Record<OnboardingStep, string> = {
  "sign-in": "Sign in",
  "sign-in-email": "Sign in with email",
  "sign-up": "Create an account",
  "sign-up-email": "Create an account with email",
  "verify-email": "Verify your email",
  profile: "Set up your profile",
  "setting-up": "Setting up your workspace",
  finalizing: "Finalizing your workspace",
};

export function generateStaticParams() {
  return ONBOARDING_STEPS.map((step) => ({ step }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ step: string }>;
}): Promise<Metadata> {
  const { step } = await params;
  return { title: isOnboardingStep(step) ? screenTitles[step] : "Onboarding" };
}

export default async function OnboardingStepPage({
  params,
  searchParams,
}: {
  params: Promise<{ step: string }>;
  searchParams: Promise<{ hold?: string }>;
}) {
  const [{ step }, query, flow] = await Promise.all([
    params,
    searchParams,
    getOnboardingFlow(),
  ]);

  if (!isOnboardingStep(step)) notFound();

  // The setting-up/finalizing steps are presentation-only fixture theatre until FI-4 slice 2
  // replaces them with real recon progress. A real (auth-enabled) deployment never shows fake
  // progress — deep links and back-button visits land on the profile step instead.
  if (isAuthenticationEnabled() && (step === "setting-up" || step === "finalizing")) {
    redirect("/onboarding/profile");
  }

  return (
    <OnboardingScreen
      autoAdvance={query.hold !== "1"}
      flow={flow}
      step={step}
    />
  );
}
