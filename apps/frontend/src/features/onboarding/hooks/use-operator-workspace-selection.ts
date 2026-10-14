"use client";

import { useEffect, useState } from "react";
import { selectWorkspace } from "@/features/session/data/session-actions";

export type OperatorWorkspaceSelection = "selecting" | "ready" | "refused";

/**
 * Selects an operator link's workspace through the membership-checked `selectWorkspace` server
 * action — the same call the signup controller makes after provisioning — and reports when it
 * is safe to start onboarding. `refused` means the signed-in user does not belong to it.
 */
export function useOperatorWorkspaceSelection(workspaceId: string): OperatorWorkspaceSelection {
  const [state, setState] = useState<OperatorWorkspaceSelection>("selecting");

  useEffect(() => {
    let live = true;
    const selection = new FormData();
    selection.set("workspaceId", workspaceId);
    selectWorkspace(selection).then(
      () => {
        if (live) setState("ready");
      },
      () => {
        if (live) setState("refused");
      },
    );
    return () => {
      live = false;
    };
  }, [workspaceId]);

  return state;
}
