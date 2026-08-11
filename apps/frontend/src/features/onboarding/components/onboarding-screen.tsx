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
import { VerifyEmailScreen } from "./verify-email-screen";
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
  const isCardScreen = isAuthScreen || step === "verify-email";

  if (step === "setting-up" || step === "finalizing") {
    return (
      <main className={`${styles.page} ${styles.subtlePage}`}>
        <SetupScreen compact={step === "finalizing"} setup={flow.setup} />
      </main>
    );
  }

  return (
    <main
      className={`${styles.page} ${isCardScreen ? styles.authPage : styles.subtlePage}`}
    >
      <OnboardingHeader
        accountEmail={controller.accountEmail ?? flow.account.email}
        onLogOut={controller.logOut}
        showAccount={step === "profile"}
      />

      <div className={styles.centerStage}>
        {isAuthScreen ? (
          <AuthScreen
            busy={controller.busy}
            copy={step.startsWith("sign-in") ? flow.auth.signIn : flow.auth.signUp}
            draft={controller.draft}
            emailMode={step.endsWith("email")}
            error={controller.error}
            onChooseEmail={() => controller.chooseAuthMethod("email")}
            onChooseGoogle={() => controller.chooseAuthMethod("google")}
            onDraftChange={controller.updateDraft}
            onSubmit={controller.submit}
            onSwitchMode={controller.switchAuthMode}
          />
        ) : null}

        {step === "verify-email" ? (
          <VerifyEmailScreen
            busy={controller.busy}
            code={controller.draft.verificationCode}
            copy={flow.auth.verifyEmail}
            email={controller.draft.email || (controller.accountEmail ?? flow.account.email)}
            error={controller.error}
            onCodeChange={(value) => controller.updateDraft("verificationCode", value)}
            onResend={controller.resendVerification}
            onSubmit={controller.submit}
          />
        ) : null}

        {step === "profile" ? (
          <ProfileScreen
            busy={controller.busy}
            draft={controller.draft}
            error={controller.error}
            onDraftChange={controller.updateDraft}
            onSubmit={controller.submit}
            profile={flow.profile}
          />
        ) : null}
      </div>

      {isCardScreen ? <OnboardingFooter /> : null}
    </main>
  );
}
