import type { Scene } from "./contracts";

/**
 * 2e post-turn suggestion chips — static heuristics v1. Deliberately dumb:
 * a small, scene-aware fixed list, shown after a settled turn. Clicking one
 * only fills the composer (never auto-sends). Smarter, result-aware
 * suggestions are a later increment.
 */
export function postTurnSuggestions(scene: Scene): string[] {
  const suggestions: string[] = [];
  if (Object.keys(scene.pages).length > 1) {
    suggestions.push("Match the style across all pages");
  }
  suggestions.push("Make the headline bolder");
  suggestions.push("Tighten the spacing");
  return suggestions.slice(0, 3);
}
