import { cn } from "@/lib/utils";
import { ClueMark } from "./clue-mark";

export type AdDesigningLockProps = {
  /** True while a design turn is running against this document (chat.threadBusy && designLegOpen). */
  active: boolean;
  /** Pill copy. Default: "Currently designing. Please wait to edit." */
  label?: string;
  placement?: "top-left" | "top-center";
  className?: string;
};

/**
 * For the ad / scene canvas: the artwork stays fully visible and keeps
 * updating live, but a transparent shield swallows pointer input and a frosted
 * pill tells the marketer the agent is mid-edit. Pair with the existing
 * `sceneGestureDisabled` / `inspectorDisabled` props so keyboard and inspector
 * edits are blocked too; this component only covers the canvas surface.
 */
export function AdDesigningLock({
  active,
  label = "Currently designing. Please wait to edit.",
  placement = "top-left",
  className,
}: AdDesigningLockProps) {
  return (
    <div
      className={cn("clue-gen-lock", className)}
      data-active={active}
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
