import type { OnboardingFlow, SetupItem } from "./onboarding";

/** The fixture id of the founder-ratified explicit-dummy brand-kit row (fails loudly in
 * tests if the fixture renames it — review FE-N9). */
export const BRAND_KIT_ITEM_ID = "brand-kit";

/**
 * Map one durable recon-lane status onto the frozen three-state checklist vocabulary.
 * `failed`/`paused` deliberately do NOT map to `queued` (that would assert "this will
 * happen"); callers drop or annotate those rows instead (review FE-M3).
 */
export function laneItemStatus(lane: string | null): SetupItem["status"] | "stopped" {
  if (lane === "completed") return "complete";
  if (lane === "running") return "running";
  if (lane === "failed" || lane === "paused") return "stopped";
  return "queued";
}

/**
 * Derive the honest checklist rows from lane truth (pure; unit-tested).
 *
 * - `starting` renders the fast-lane row as running: the submission is durably captured and
 *   the drive is in flight — this is also what restores visible motion while the fast lane's
 *   single enclosing transaction hides its RUNNING row (review FE-M1/BE-M6).
 * - A stopped (failed/paused) background lane keeps its row with an honest detail line
 *   rather than an eternal `queued` claim.
 * - The brand-kit row stays the ratified explicit dummy (forced `queued`), and is dropped
 *   cleanly if the fixture no longer carries it.
 */
export function deriveSetupItems(
  fixtureSetup: OnboardingFlow["setup"],
  progress: {
    status: string;
    fast_status: string | null;
    background_status: string | null;
  } | null,
): SetupItem[] {
  const starting = progress?.status === "starting";
  const fastLane = laneItemStatus(progress?.fast_status ?? null);
  const backgroundLane = laneItemStatus(progress?.background_status ?? null);

  const items: SetupItem[] = [
    {
      id: "company-research",
      label: "Looking up company, & products",
      detail: "Positioning, category, and differentiated value",
      status:
        fastLane === "stopped"
          ? "queued" // the surfaced failure paragraph carries the truth for the fast lane
          : starting && fastLane === "queued"
            ? "running"
            : fastLane,
    },
  ];

  if (backgroundLane === "stopped") {
    items.push({
      id: "deep-research",
      label: "Deep research on your company",
      detail: "Didn't finish — we'll pick this up again later",
      status: "queued",
    });
  } else {
    items.push({
      id: "deep-research",
      label: "Deep research on your company",
      detail: "Broader sources, proof points, and market reputation",
      status: backgroundLane,
    });
  }

  const brandKit = fixtureSetup.items.find((item) => item.id === BRAND_KIT_ITEM_ID);
  if (brandKit) {
    // Founder ruling (FI-4 §9): explicit dummy until the design branch merges.
    items.push({ ...brandKit, status: "queued" });
  }
  return items;
}
