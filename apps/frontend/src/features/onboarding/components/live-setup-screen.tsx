"use client";

import type { OnboardingFlow } from "../model/onboarding";
import { deriveSetupItems } from "../model/setup-items";
import { useSetupProgress } from "../hooks/use-setup-progress";
import { SetupScreen } from "./setup-screen";
import styles from "./onboarding.module.css";

/**
 * The slice-2 real setting-up screen (clerk mode only): the frozen SetupScreen visuals fed
 * by durable recon-lane truth (useSetupProgress + the pure deriveSetupItems). Terminal
 * failures render inside the same grid cell as the frozen block (no geometry displacement)
 * with real recovery controls: "Try again" re-runs setup (meaningful — a failed lane
 * releases its dedupe slot and a retry mints a fresh attempt) and "Continue anyway"
 * releases into the app, which the failure copy promises.
 */
export function LiveSetupScreen({
  compact,
  setup,
}: {
  compact: boolean;
  setup: OnboardingFlow["setup"];
}) {
  const { status, failure, terminal } = useSetupProgress();
  const items = deriveSetupItems(setup, status);

  return (
    <div className={styles.setupStack}>
      <SetupScreen compact={compact} setup={{ ...setup, items }} />
      {failure ? (
        <div className={styles.authHeading}>
          <p className={styles.authError} role="alert">
            {failure}
          </p>
          <p>
            {terminal === "session" ? (
              <button onClick={() => window.location.replace("/sign-in")} type="button">
                Sign in
              </button>
            ) : (
              <>
                {terminal === "failed" ? (
                  <button onClick={() => window.location.reload()} type="button">
                    Try again
                  </button>
                ) : null}{" "}
                <button
                  onClick={() => window.location.replace("/session/establish")}
                  type="button"
                >
                  Continue anyway
                </button>
              </>
            )}
          </p>
        </div>
      ) : null}
    </div>
  );
}
