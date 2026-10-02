/**
 * The cofounder's approved "agent is generating" motion (handoff `ad4f30bb`),
 * copied VERBATIM: `generating.css` and the components are presentation truth
 * and are not restyled, renamed, or "improved" here.
 *
 * Two consumers share the sheet:
 *   - the WEBSITE pane: `WebsiteGeneratingVeil` + `GeneratingGlow` (design/website);
 *   - the SCENE-AD pane: `AdDesigningLock` + `GeneratingGlow`, gated by
 *     `sceneAgentMotionActive` (design/scene-ad, founder ruling 2026-09-04).
 * The lock is scene-only (founder ruling 2026-09-07: no ad lock on websites).
 */
export { ClueMark, CLUE_MARK_PATHS, CLUE_MARK_VIEWBOX } from "./clue-mark";
export { GeneratingGlow, type GeneratingGlowProps } from "./generating-glow";
export { WebsiteGeneratingVeil, type WebsiteGeneratingVeilProps } from "./website-generating-veil";
export { AdDesigningLock, type AdDesigningLockProps } from "./ad-designing-lock";
export { sceneAgentMotionActive } from "./scene-agent-motion";
