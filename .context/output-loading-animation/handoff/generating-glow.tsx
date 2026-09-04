import { cn } from "@/lib/utils";

export type GeneratingGlowProps = {
  /** True while the agent is working on the artifact in this pane. */
  active: boolean;
  className?: string;
};

/**
 * Soft brand-coloured haze that hugs the edges of the output pane while an
 * agent is generating (the Comet-style "whole surface is alive" cue, in Clue's
 * sage / cream / slate-teal instead of blue). Purely decorative: no pointer
 * events, no text. Mount inside a `position: relative` host (add `.clue-gen-host`).
 * Styles live in ./generating.css — import it once where the pane is composed.
 */
export function GeneratingGlow({ active, className }: GeneratingGlowProps) {
  return <div className={cn("clue-gen-glow", className)} data-active={active} aria-hidden="true" />;
}
