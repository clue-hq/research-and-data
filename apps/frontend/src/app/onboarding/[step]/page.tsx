import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OnboardingScreen } from "@/features/onboarding/components/onboarding-screen";
import { getOnboardingFlow } from "@/features/onboarding/data/onboarding.repository";
import {
  isOnboardingStep,
  type OnboardingStep,
} from "@/features/onboarding/model/onboarding";
import { ONBOARDING_STEPS } from "@/features/onboarding/model/onboarding-navigation";
import { operatorSetupTarget } from "@/features/onboarding/model/operator-setup";

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
  searchParams: Promise<{
    hold?: string;
    reason?: string;
    workspace?: string | string[];
    website?: string | string[];
  }>;
}) {
  const [{ step }, query, flow] = await Promise.all([
    params,
    searchParams,
    getOnboardingFlow(),
  ]);

  if (!isOnboardingStep(step)) notFound();

  return (
    <OnboardingScreen
      autoAdvance={query.hold !== "1"}
      flow={flow}
      notice={
        query.reason === "session_expired"
          ? "Your session expired. Please sign in again."
          : null
      }
      operatorTarget={step === "setting-up" ? operatorSetupTarget(query) : null}
      step={step}
    />
  );
}
