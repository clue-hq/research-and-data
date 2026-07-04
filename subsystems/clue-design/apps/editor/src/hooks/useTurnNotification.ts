import { useEffect, useRef, useState } from "react";

/**
 * 2e notify-when-done: when an agent turn settles while the user is NOT
 * looking at the agent panel, surface a small in-app toast (click opens the
 * panel). Deliberately no browser Notification API — no permission prompts,
 * no dialogs. Rides the same isAgentRunning transition 2b's checklist uses.
 */
export interface TurnToast {
  message: string;
  tone: "ready" | "issue";
}

export interface UseTurnNotificationDeps {
  isAgentRunning: boolean;
  /** True when the agent panel is the visible right-panel mode. */
  isAgentPanelOpen: boolean;
  /** The settled turn's outcome: was a reviewable proposal produced? */
  hasProposal: boolean;
  autoDismissMs?: number;
}

export function useTurnNotification(deps: UseTurnNotificationDeps) {
  const { isAgentRunning, isAgentPanelOpen, hasProposal, autoDismissMs = 8000 } = deps;
  const [toast, setToast] = useState<TurnToast | null>(null);

  const wasRunningRef = useRef(isAgentRunning);
  const depsRef = useRef({ isAgentPanelOpen, hasProposal });
  depsRef.current = { isAgentPanelOpen, hasProposal };

  useEffect(() => {
    const settled = wasRunningRef.current && !isAgentRunning;
    wasRunningRef.current = isAgentRunning;
    if (!settled || depsRef.current.isAgentPanelOpen) {
      return;
    }
    setToast(
      depsRef.current.hasProposal
        ? { message: "Agent finished — a proposal is ready to review.", tone: "ready" }
        : { message: "Agent finished — check the chat for details.", tone: "issue" }
    );
  }, [isAgentRunning]);

  // Auto-dismiss; opening the panel dismisses immediately.
  useEffect(() => {
    if (!toast) {
      return;
    }
    if (isAgentPanelOpen) {
      setToast(null);
      return;
    }
    const timer = setTimeout(() => setToast(null), autoDismissMs);
    return () => clearTimeout(timer);
  }, [toast, isAgentPanelOpen, autoDismissMs]);

  return { toast, dismiss: () => setToast(null) };
}
