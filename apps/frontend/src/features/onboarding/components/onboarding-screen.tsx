"use client";

import type { OnboardingFlow, OnboardingStep } from "../model/onboarding";
import { useOnboardingController } from "../hooks/use-onboarding-controller";
import { AuthScreen } from "./auth-screen";
import {
  OnboardingFooter,
  OnboardingHeader,
} from "./onboarding-brand";
import { ProfileScreen } from "./profile-screen";
import { SetupScreen } from "./setup-screen";
import styles from "./onboarding.module.css";

export function OnboardingScreen({
  flow,
  step,
  autoAdvance,
}: {
  flow: OnboardingFlow;
  step: OnboardingStep;
  autoAdvance: boolean;
}) {
  const controller = useOnboardingController({ step, autoAdvance });
  const isAuthScreen = [
    "sign-in",
    "sign-in-email",
    "sign-up",
    "sign-up-email",
  ].includes(step);

  if (step === "setting-up" || step === "finalizing") {
    return (
      <main className={`${styles.page} ${styles.subtlePage}`}>
        <SetupScreen compact={step === "finalizing"} setup={flow.setup} />
      </main>
    );
  }

  return (
    <main
      className={`${styles.page} ${isAuthScreen ? styles.authPage : styles.subtlePage}`}
    >
      <OnboardingHeader
        accountEmail={flow.account.email}
        showAccount={step === "profile"}
      />

      <div className={styles.centerStage}>
        {isAuthScreen ? (
          <AuthScreen
            copy={step.startsWith("sign-in") ? flow.auth.signIn : flow.auth.signUp}
            draft={controller.draft}
            emailMode={step.endsWith("email")}
            onChooseEmail={() => controller.chooseAuthMethod("email")}
            onChooseGoogle={() => controller.chooseAuthMethod("google")}
            onDraftChange={controller.updateDraft}
            onSubmit={controller.submit}
            onSwitchMode={controller.switchAuthMode}
          />
        ) : null}

        {step === "profile" ? (
          <ProfileScreen
            draft={controller.draft}
            onDraftChange={controller.updateDraft}
            onSubmit={controller.submit}
            profile={flow.profile}
          />
        ) : null}
      </div>

      {isAuthScreen ? <OnboardingFooter /> : null}
    </main>
  );
}
