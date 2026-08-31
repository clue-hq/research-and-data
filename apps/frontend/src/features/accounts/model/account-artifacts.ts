/**
 * Honest Account Artifact states.
 *
 * Slice 7 has no live Account-artifact read contract, so the route uses
 * `capability_unavailable`. `empty` and `service_unavailable` stay distinct for
 * the future live adapter: an authoritative zero result must never look like
 * an outage, and an outage must never masquerade as an empty Account.
 */
export type AccountArtifactState =
  | "capability_unavailable"
  | "empty"
  | "service_unavailable";

type AccountArtifactStateCopy = {
  description: string;
  title: string;
};

const stateCopy: Record<AccountArtifactState, AccountArtifactStateCopy> = {
  capability_unavailable: {
    title: "Account artifacts are not connected yet",
    description:
      "This workspace does not currently provide a live Account artifact library.",
  },
  empty: {
    title: "No artifacts yet",
    description: "No artifacts have been created for this account yet.",
  },
  service_unavailable: {
    title: "Artifacts are temporarily unavailable",
    description:
      "The Account artifact service could not be reached. Try again later.",
  },
};

export function accountArtifactStateCopy(
  state: AccountArtifactState,
): AccountArtifactStateCopy {
  return stateCopy[state];
}
