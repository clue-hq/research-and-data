import { cn } from "@/lib/utils";

export type GeneratingGlowProps = {
  /** True while the agent is working on the artifact in this pane. */
  active: boolean;
  className?: string;
};

/**
 * Thin light frame at the edges of the output pane while an agent is
 * generating. Four stacked layers (haze, bloom, 2px line, hairline rim), all
 * masked to the edges so the centre stays clean; two soft bands of sage, cream,
 * and slate-teal drift around the perimeter. Decorative only: no pointer events.
 * Mount inside a `position: relative` host (add `.clue-gen-host`).
 * Styles live in ./generating.css — import it once where the pane is composed.
 */
export function GeneratingGlow({ active, className }: GeneratingGlowProps) {
  return (
    <div className={cn("clue-gen-glow", className)} data-active={active} aria-hidden="true">
      <i className="clue-gen-glow__haze" />
      <i className="clue-gen-glow__bloom" />
      <i className="clue-gen-glow__line" />
      <i className="clue-gen-glow__rim" />
    </div>
  );
}
