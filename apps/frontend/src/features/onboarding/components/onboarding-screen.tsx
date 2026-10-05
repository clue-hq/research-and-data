"use client";

import type { OnboardingFlow, OnboardingStep } from "../model/onboarding";
import { useOnboardingController } from "../hooks/use-onboarding-controller";
import { AuthScreen } from "./auth-screen";
import {
  OnboardingFooter,
  OnboardingHeader,
} from "./onboarding-brand";
import { LiveSetupScreen } from "./live-setup-screen";
import { ProfileScreen } from "./profile-screen";
import { SetupScreen } from "./setup-screen";
import { VerifyEmailScreen } from "./verify-email-screen";
import styles from "./onboarding.module.css";

export function OnboardingScreen({
  flow,
  step,
  autoAdvance,
  notice = null,
}: {
  flow: OnboardingFlow;
  step: OnboardingStep;
  autoAdvance: boolean;
  /** One line above a sign-in card, e.g. why the user was sent back to sign in. */
  notice?: string | null;
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
        {controller.authMode === "clerk" ? (
          // Real lane truth; the presentation timer never runs here. The website is the
          // profile draft's — the same value provisioning posted — not the fixture account's.
          <LiveSetupScreen
            companyWebsite={controller.draft.companyWebsite}
            compact={step === "finalizing"}
            setup={flow.setup}
          />
        ) : (
          <SetupScreen compact={step === "finalizing"} setup={flow.setup} />
        )}
      </main>
    );
  }

  return (
    <main
      className={`${styles.page} ${isCardScreen ? styles.authPage : styles.subtlePage}`}
    >
      <OnboardingHeader
        // The fixture designer's address is theatre-only; a real session shows the real
        // email or nothing while it loads — never "hello@aakash.design" (review finding FE6).
        accountEmail={
          controller.authMode === "clerk"
            ? (controller.accountEmail ?? "")
            : flow.account.email
        }
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
            notice={step.startsWith("sign-in") ? notice : null}
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
            // After a refresh the draft is gone but Clerk rehydrates the sign-up attempt —
            // its address is the truthful source; the fixture address is fixture-only.
            email={
              controller.draft.email ||
              controller.pendingEmail ||
              (controller.authMode === "clerk" ? "your email" : flow.account.email)
            }
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
