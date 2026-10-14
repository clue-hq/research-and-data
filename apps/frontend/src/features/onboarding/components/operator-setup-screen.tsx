"use client";

import { useOperatorWorkspaceSelection } from "../hooks/use-operator-workspace-selection";
import type { OnboardingFlow } from "../model/onboarding";
import type { OperatorSetupTarget } from "../model/operator-setup";
import { LiveSetupScreen } from "./live-setup-screen";
import styles from "./onboarding.module.css";

/**
 * The setting-up screen for an operator link. The linked workspace is selected FIRST, and the
 * live screen mounts only once that succeeded, so onboarding can never start for whichever
 * workspace happened to be selected before the link was opened.
 */
export function OperatorSetupScreen({
  target,
  compact,
  setup,
}: {
  target: OperatorSetupTarget;
  compact: boolean;
  setup: OnboardingFlow["setup"];
}) {
  const state = useOperatorWorkspaceSelection(target.workspaceId);

  if (state === "ready") {
    return (
      <LiveSetupScreen companyWebsite={target.companyWebsite} compact={compact} setup={setup} />
    );
  }
  if (state === "refused") {
    return (
      <p className={styles.authError} role="alert">
        You don&apos;t have access to this workspace.
      </p>
    );
  }
  return null;
}
