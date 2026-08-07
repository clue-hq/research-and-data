import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useTurnNotification } from "../useTurnNotification";

interface Props {
  isAgentRunning: boolean;
  isAgentPanelOpen: boolean;
  hasProposal: boolean;
}

function run(initial: Props) {
  return renderHook((props: Props) => useTurnNotification({ ...props, autoDismissMs: 50 }), {
    initialProps: initial
  });
}

describe("useTurnNotification (2e)", () => {
  it("raises a toast when a turn settles with the agent panel closed", () => {
    const { result, rerender } = run({
      isAgentRunning: true,
      isAgentPanelOpen: false,
      hasProposal: false
    });
    expect(result.current.toast).toBeNull();
    rerender({ isAgentRunning: false, isAgentPanelOpen: false, hasProposal: true });
    expect(result.current.toast).toEqual({
      message: "Agent finished — a proposal is ready to review.",
      tone: "ready"
    });
  });

  it("stays silent when the user is already looking at the agent panel", () => {
    const { result, rerender } = run({
      isAgentRunning: true,
      isAgentPanelOpen: true,
      hasProposal: false
    });
    rerender({ isAgentRunning: false, isAgentPanelOpen: true, hasProposal: true });
    expect(result.current.toast).toBeNull();
  });

  it("dismisses when the panel opens, and on the timer", () => {
    vi.useFakeTimers();
    try {
      const { result, rerender } = run({
        isAgentRunning: true,
        isAgentPanelOpen: false,
        hasProposal: false
      });
      rerender({ isAgentRunning: false, isAgentPanelOpen: false, hasProposal: false });
      expect(result.current.toast?.tone).toBe("issue");

      // Opening the panel clears it immediately.
      rerender({ isAgentRunning: false, isAgentPanelOpen: true, hasProposal: false });
      expect(result.current.toast).toBeNull();

      // Fresh toast → auto-dismiss on the timer.
      rerender({ isAgentRunning: true, isAgentPanelOpen: false, hasProposal: false });
      rerender({ isAgentRunning: false, isAgentPanelOpen: false, hasProposal: false });
      expect(result.current.toast).not.toBeNull();
      act(() => {
        vi.advanceTimersByTime(60);
      });
      expect(result.current.toast).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
