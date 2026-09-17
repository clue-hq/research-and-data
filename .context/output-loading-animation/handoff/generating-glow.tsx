import { cn } from "@/lib/utils";

export type GeneratingGlowProps = {
  /** True while the agent is working on the artifact in this pane. */
  active: boolean;
  /**
   * "aurora" — two soft light-bands drift around the frame (calm, premium).
   * "beam"   — one bright beam with a long tail races the frame (energetic).
   */
  variant?: "aurora" | "beam";
  className?: string;
};

/**
 * Light at the edges of the output pane while an agent is generating. Four
 * stacked layers give it depth the way Comet's frame does: a wide faint haze,
 * a tight bloom, a 1.5px bright line on the edge itself, and a faint recess
 * under the line so the light reads as spilling in from behind the frame.
 * The centre of the pane stays clean. Decorative only: no pointer events.
 * Mount inside a `position: relative` host (add `.clue-gen-host`).
 * Styles live in ./generating.css — import it once where the pane is composed.
 */
export function GeneratingGlow({ active, variant = "aurora", className }: GeneratingGlowProps) {
  return (
    <div className={cn("clue-gen-glow", className)} data-active={active} data-variant={variant} aria-hidden="true">
      <i className="clue-gen-glow__haze" />
      <i className="clue-gen-glow__bloom" />
      <i className="clue-gen-glow__line" />
      <i className="clue-gen-glow__rim" />
    </div>
  );
}
