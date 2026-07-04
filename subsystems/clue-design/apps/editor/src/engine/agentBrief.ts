/**
 * 2e Design-Plan pre-brief (Moda §1.3): four optional questions folded into
 * the prompt as a structured brief block. Pure composition — the chat panel
 * holds the form values, this decides the text. An empty brief leaves the
 * prompt untouched (the form is skippable by design).
 *
 * Variants-as-pages rides here: variations > 1 becomes an explicit
 * instruction to produce each concept as its own NAMED page.
 */

export interface DesignBrief {
  /** How many distinct concepts to produce (1 = a single design). */
  variations: number;
  /** How strictly to follow the attached Brand Kit. */
  brandAdherence: "strict" | "flexible" | "";
  /** What to emphasize (e.g. "the discount", "the venue photo"). */
  focus: string;
  /** Call-to-action copy, verbatim. */
  cta: string;
}

export const EMPTY_BRIEF: DesignBrief = {
  variations: 1,
  brandAdherence: "",
  focus: "",
  cta: ""
};

export function briefIsEmpty(brief: DesignBrief): boolean {
  return (
    brief.variations <= 1 &&
    brief.brandAdherence === "" &&
    brief.focus.trim() === "" &&
    brief.cta.trim() === ""
  );
}

/** Prepend the brief block to the user's prompt (or return the prompt
 * unchanged when the brief is empty). */
export function composeBriefPrompt(brief: DesignBrief, prompt: string): string {
  if (briefIsEmpty(brief)) {
    return prompt;
  }
  const lines: string[] = ["Design brief:"];
  if (brief.variations > 1) {
    lines.push(
      `- Produce ${brief.variations} distinct variant concepts, EACH as its own page ` +
        `named "Variant A", "Variant B", … — one page per concept, no shared pages.`
    );
  }
  if (brief.brandAdherence === "strict") {
    lines.push("- Brand adherence: strict — stay inside the Brand Kit tokens exactly.");
  } else if (brief.brandAdherence === "flexible") {
    lines.push(
      "- Brand adherence: flexible — the Brand Kit is a starting point; tasteful deviation is allowed."
    );
  }
  if (brief.focus.trim()) {
    lines.push(`- Visual focus: ${brief.focus.trim()}.`);
  }
  if (brief.cta.trim()) {
    lines.push(`- Call to action (verbatim): "${brief.cta.trim()}".`);
  }
  return `${lines.join("\n")}\n\nRequest: ${prompt}`;
}
