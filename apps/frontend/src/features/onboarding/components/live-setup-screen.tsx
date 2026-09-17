"use client";

import type { OnboardingFlow } from "../model/onboarding";
import { deriveSetupItems } from "../model/setup-items";
import { useSetupProgress } from "../hooks/use-setup-progress";
import { SetupScreen } from "./setup-screen";
import styles from "./onboarding.module.css";

/**
 * The real setting-up screen (clerk mode only): the frozen SetupScreen visuals fed by durable
 * lane truth (useSetupProgress + the pure deriveSetupItems, which derives the four checklist
 * groups from the onboarding lane's steps). This component only threads the company website
 * down and the poll status back up — the derivation and every word of copy live in the model.
 * Terminal failures render inside the same grid cell as the frozen block (no geometry displacement)
 * with two honest recovery controls. "Try again" RELOADS the screen: the seam then re-attaches to
 * whatever run the workspace really has (the start path probes `GET /onboarding/current` first, so
 * a live run is simply observed again) and a run that already spent is never restarted — one
 * onboarding run per workspace is the backend's rule, and minting a second would be real duplicate
 * spend. It is therefore worth pressing after a transport or session failure, and a no-op against a
 * run that genuinely failed. "Continue anyway" releases into the app, which the failure copy
 * promises.
 */
export function LiveSetupScreen({
  companyWebsite,
  compact,
  setup,
}: {
  /** The profile step's own value — the company the onboarding run is started for. */
  companyWebsite: string;
  compact: boolean;
  setup: OnboardingFlow["setup"];
}) {
  const { status, failure, terminal } = useSetupProgress({ companyWebsite });
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
                {terminal === "failed" || terminal === "stalled" ? (
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
