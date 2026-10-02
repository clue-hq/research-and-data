/**
 * When the scene-ad editor shows the agent-working motion (the co-founder's
 * lock + glow, ported 2026-09-04 from `handoff/output-pane-generating-motion`).
 *
 * The rule the retired chip had, kept apart from the components so it is
 * testable without a DOM: the motion is the VISIBLE form of the scene editor's
 * agent-run lock, so it runs exactly while that lock is engaged — and only
 * over a real scene, never over the empty-state card.
 */
export function sceneAgentMotionActive({
  agentWorking,
  hasScene,
}: {
  /** `chat-surface.tsx`'s `sceneLocked`: the agent-run lock over an ad artifact. */
  agentWorking: boolean | undefined;
  /** Whether a scene is on the stage (the same condition that mounts the canvas). */
  hasScene: boolean;
}): boolean {
  return agentWorking === true && hasScene;
}
