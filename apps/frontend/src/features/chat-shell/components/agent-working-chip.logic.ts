/**
 * The agent-working chip's two facts (founder request 2026-09-03).
 *
 * Kept apart from the component so the visibility rule is testable without a DOM:
 * the chip is the VISIBLE form of the scene editor's agent-run lock (rung A of the
 * live-streaming plan), so it shows exactly when that lock is engaged — and only
 * over a real scene, never over the empty-state card.
 */

/** The founder's words, verbatim (ruling R1 in the plan). The Edit pill's tooltip
 * keeps rung A's ratified lock sentence; this is the chip's own line. */
export const AGENT_WORKING_CHIP_LABEL = "Designing. Please wait to edit.";

export function shouldShowAgentWorkingChip({
  editDisabled,
  hasScene,
}: {
  /** `ArtifactStage`'s `editDisabled` — `agentRunLock.locked` upstream. */
  editDisabled: boolean | undefined;
  /** Whether a scene is on the stage (the same condition that mounts the canvas). */
  hasScene: boolean;
}): boolean {
  return editDisabled === true && hasScene;
}
