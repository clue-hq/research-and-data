import { describe, expect, it } from "vitest";
import type { Scene } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { postTurnSuggestions } from "../agentSuggestions";

describe("post-turn suggestions (2e, static v1)", () => {
  it("offers the static pair on a single-page scene", () => {
    expect(postTurnSuggestions(minimalScene)).toEqual([
      "Make the headline bolder",
      "Tighten the spacing"
    ]);
  });

  it("adds the cross-page suggestion on multi-page scenes, capped at 3", () => {
    const multiPage = {
      ...minimalScene,
      pages: {
        ...minimalScene.pages,
        page_extra: { ...Object.values(minimalScene.pages)[0], id: "page_extra" }
      }
    } as Scene;
    const suggestions = postTurnSuggestions(multiPage);
    expect(suggestions[0]).toBe("Match the style across all pages");
    expect(suggestions).toHaveLength(3);
  });
});
