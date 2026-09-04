import { cn } from "@/lib/utils";
import { ClueMark } from "./clue-mark";

export type AdDesigningLockProps = {
  /** True while a design turn is running against this document (chat.threadBusy && designLegOpen). */
  active: boolean;
  /** Chip copy. Default: "Agent is designing. Please wait." */
  label?: string;
  /** "frost" — white chip on the canvas. "ink" — deep-olive chip, cream text. */
  appearance?: "frost" | "ink";
  placement?: "top-left" | "top-center";
  className?: string;
};

/**
 * For the ad / scene canvas: the artwork stays fully visible and keeps
 * updating live, but a transparent shield swallows pointer input and a small
 * 8px-radius chip (the frontend's --radius) tells the marketer the agent is
 * mid-edit. Pair with the existing `sceneGestureDisabled` / `inspectorDisabled`
 * props so keyboard and inspector edits are blocked too; this component only
 * covers the canvas surface.
 */
export function AdDesigningLock({
  active,
  label = "Agent is designing. Please wait.",
  appearance = "frost",
  placement = "top-left",
  className,
}: AdDesigningLockProps) {
  return (
    <div
      className={cn("clue-gen-lock", className)}
      data-active={active}
      data-appearance={appearance}
      data-placement={placement}
      role="status"
      aria-live="polite"
      aria-hidden={!active}
      // Swallow everything so a stray click cannot select or drag a node mid-generation.
      onPointerDown={(e) => e.preventDefault()}
      onMouseDown={(e) => e.preventDefault()}
    >
      <div className="clue-gen-lock__pill">
        <ClueMark className="clue-gen-spinner" />
        <span className="clue-gen-lock__text">{label}</span>
      </div>
    </div>
  );
}
