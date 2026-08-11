"use client";

import type { OnboardingFlow, SetupItem } from "../model/onboarding";
import { useSetupProgress } from "../hooks/use-setup-progress";
import { SetupScreen } from "./setup-screen";
import styles from "./onboarding.module.css";

function laneItemStatus(lane: string | null): SetupItem["status"] {
  if (lane === "completed") return "complete";
  if (lane === "running") return "running";
  return "queued";
}

/**
 * The slice-2 real setting-up screen (clerk mode only): the frozen SetupScreen visuals fed by
 * durable recon-lane truth (useSetupProgress). Items shown are exactly what is true today:
 * the fast company-research lane, the deeper background lane, and the brand-kit item as the
 * founder-ratified explicit dummy (design subsystem; parallel branch). The per-field checklist
 * groups land in slice 3 with the granular event vocabulary.
 */
export function LiveSetupScreen({ setup }: { setup: OnboardingFlow["setup"] }) {
  const { status, failure } = useSetupProgress();

  const brandKitFixtureItem = setup.items.find((item) => item.id === "brand-kit");
  const items: SetupItem[] = [
    {
      id: "company-research",
      label: "Looking up company, & products",
      detail: "Positioning, category, and differentiated value",
      status: laneItemStatus(status?.fast_status ?? null),
    },
    {
      id: "deep-research",
      label: "Deep research on your company",
      detail: "Broader sources, proof points, and market reputation",
      status: laneItemStatus(status?.background_status ?? null),
    },
    // Founder ruling (FI-4 §9): the brand-kit item stays an explicit dummy until the design
    // branch merges; it never claims progress it does not have.
    ...(brandKitFixtureItem ? [{ ...brandKitFixtureItem, status: "queued" as const }] : []),
  ];

  return (
    <>
      <SetupScreen compact={false} setup={{ ...setup, items }} />
      {failure ? (
        <div className={styles.authHeading}>
          <p className={styles.authError} role="alert">
            {failure}
          </p>
          <p>
            <button onClick={() => window.location.reload()} type="button">
              Retry
            </button>
          </p>
        </div>
      ) : null}
    </>
  );
}
