import { describe, expect, it } from "vitest";
import { briefIsEmpty, composeBriefPrompt, EMPTY_BRIEF } from "../agentBrief";

describe("agent pre-brief composition (2e)", () => {
  it("leaves the prompt untouched when the brief is empty (skippable)", () => {
    expect(composeBriefPrompt(EMPTY_BRIEF, "Make a poster")).toBe("Make a poster");
    expect(briefIsEmpty(EMPTY_BRIEF)).toBe(true);
    // Whitespace-only fields count as empty.
    expect(
      composeBriefPrompt(
        { variations: 1, brandAdherence: "", focus: "   ", cta: " " },
        "Make a poster"
      )
    ).toBe("Make a poster");
  });

  it("folds all four answers into a brief block ahead of the request", () => {
    const prompt = composeBriefPrompt(
      {
        variations: 3,
        brandAdherence: "strict",
        focus: "the discount",
        cta: "Book your seat"
      },
      "Spring sale flyer"
    );
    expect(prompt).toContain("Design brief:");
    // Variants-as-pages: N concepts, each its own NAMED page.
    expect(prompt).toContain("3 distinct variant concepts");
    expect(prompt).toContain('named "Variant A", "Variant B"');
    expect(prompt).toContain("strict — stay inside the Brand Kit tokens");
    expect(prompt).toContain("Visual focus: the discount.");
    expect(prompt).toContain('Call to action (verbatim): "Book your seat".');
    expect(prompt).toContain("Request: Spring sale flyer");
  });

  it("emits only the answered questions", () => {
    const prompt = composeBriefPrompt(
      { variations: 1, brandAdherence: "flexible", focus: "", cta: "" },
      "Refresh the header"
    );
    expect(prompt).toContain("flexible — the Brand Kit is a starting point");
    expect(prompt).not.toContain("variant concepts");
    expect(prompt).not.toContain("Visual focus");
    expect(prompt).not.toContain("Call to action");
  });
});
