"use client";

import { useRef, useState, type CSSProperties } from "react";
import { TITLE_MARQUEE_GAP_PX, titleMarqueePlan, type TitleMarqueePlan } from "../model/title-marquee";
import styles from "./chat-shell.module.css";

/** The artifact header's title: one line, cut with an ellipsis when it does not fit. Hovering a cut
 * title scrolls it left through one whole loop — the name, a gap, the name again — and it stops when
 * its first letter is back where it began (it never scrolls back). With reduced motion it does not
 * scroll; the browser's tooltip shows the whole name instead. Keyed on the title by its caller, so a
 * renamed artifact starts fresh. */
export function ArtifactTitle({ title }: { title: string }) {
  const boxRef = useRef<HTMLSpanElement>(null);
  const [plan, setPlan] = useState<TitleMarqueePlan | null>(null);
  const [tooltip, setTooltip] = useState(false);

  const start = () => {
    const box = boxRef.current;
    if (plan || !box) return;
    const next = titleMarqueePlan({ textWidth: box.scrollWidth, boxWidth: box.clientWidth });
    if (next && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setTooltip(true);
      return;
    }
    setPlan(next);
  };

  const trackStyle = plan
    ? ({
        "--title-marquee-shift": `-${plan.shiftPx}px`,
        "--title-marquee-duration": `${plan.durationMs}ms`,
        "--title-marquee-gap": `${TITLE_MARQUEE_GAP_PX}px`,
      } as CSSProperties)
    : undefined;

  return (
    <span
      className={styles.artifactTitle}
      onMouseEnter={start}
      ref={boxRef}
      title={tooltip ? title : undefined}
    >
      {plan ? (
        <>
          {/* The name stays in place, unseen, so the box keeps exactly its size and the header does
              not move; the scrolling copies are laid over it. */}
          <span aria-hidden="true" className={styles.artifactTitleSizer}>
            {title}
          </span>
          <span className={styles.artifactTitleTrack} onAnimationEnd={() => setPlan(null)} style={trackStyle}>
            <span>{title}</span>
            <span aria-hidden="true" className={styles.artifactTitleRepeat}>
              {title}
            </span>
          </span>
        </>
      ) : (
        title
      )}
    </span>
  );
}
