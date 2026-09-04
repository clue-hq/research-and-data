import { cn } from "@/lib/utils";
import { ClueMark } from "./clue-mark";

export type WebsiteGeneratingVeilProps = {
  /** True from `leg.opened` / `turn.started` until the canvas revision that carries the page. */
  active: boolean;
  /** Short present-tense line. Default: "Building your landing page". */
  title?: string;
  /**
   * Optional second line. Founder rule (design-leg.ts): no percentage, no ETA,
   * no countdown. Pass DESIGN_GENERATION_WAIT_NOTICE or nothing.
   */
  hint?: string;
  /** "paper" — light frosted veil (default). "ink" — deep-olive cinematic veil, cream mark. */
  tone?: "paper" | "ink";
  className?: string;
};

/**
 * Website generation cannot stream, so the whole pane blurs until the page
 * exists. The Clue mark assembles, breathes, and re-assembles in the centre.
 * Covers whatever is underneath (previous page, empty state, loading frame)
 * via backdrop-filter, and shields input while active.
 */
export function WebsiteGeneratingVeil({
  active,
  title = "Building your landing page",
  hint,
  tone = "paper",
  className,
}: WebsiteGeneratingVeilProps) {
  return (
    <div
      className={cn("clue-gen-veil", className)}
      data-active={active}
      data-tone={tone}
      role="status"
      aria-live="polite"
      aria-hidden={!active}
    >
      <div className="clue-gen-veil__stage">
        <ClueMark className="clue-gen-mark" />
        <div className="clue-gen-title">{title}</div>
        {hint ? <div className="clue-gen-hint">{hint}</div> : null}
      </div>
    </div>
  );
}
