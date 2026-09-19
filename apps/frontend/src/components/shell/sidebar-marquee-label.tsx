"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import styles from "./sidebar-marquee-label.module.css";

const COPY_GAP_PX = 24;
const SCROLL_SPEED_PX_PER_SECOND = 48;

export function SidebarMarqueeLabel({ text }: { text: string }) {
  const viewportRef = useRef<HTMLSpanElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const viewport = viewportRef.current;
    const label = textRef.current;
    if (!viewport || !label) return;

    // Observe both the available space and text, including renames and font loads.
    const observer = new ResizeObserver(() => {
      const textWidth = label.getBoundingClientRect().width;
      const viewportWidth = viewport.getBoundingClientRect().width;
      setDistance(textWidth > viewportWidth + 1 ? textWidth + COPY_GAP_PX : 0);
    });
    observer.observe(viewport);
    observer.observe(label);
    return () => observer.disconnect();
  }, []);

  return (
    <span
      className={styles.viewport}
      data-overflow={distance > 0 ? "true" : undefined}
      ref={viewportRef}
      style={{
        "--marquee-distance": `${distance}px`,
        "--marquee-duration": `${distance / SCROLL_SPEED_PX_PER_SECOND}s`,
        "--marquee-gap": `${COPY_GAP_PX}px`,
      } as CSSProperties}
      title={text}
    >
      <span className={styles.track}>
        <span ref={textRef}>{text}</span>
        {distance > 0 ? <span aria-hidden="true">{text}</span> : null}
      </span>
    </span>
  );
}
