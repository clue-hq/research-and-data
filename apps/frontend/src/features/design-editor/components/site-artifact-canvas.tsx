"use client";

import { useEffect, useRef } from "react";
import type { SiteCanvasBinding } from "@/features/site-editor/model/site-stage";
import type { VeilRenderKind } from "../adapter/generating-veil";
import { CanvasEmptyState, CanvasErrorState, CanvasLoadingState } from "./canvas-states";
import styles from "./web-artifact-canvas.module.css";

/**
 * The site lane's canvas (D2): ONE iframe onto the workspace's editor domain, where agent code runs
 * away from the marketer's session. It stays mounted while hidden (display: none keeps the frame and
 * its state; moving an iframe in the DOM would reload it), so the frame is warm. The states are the
 * web canvas's own three. No top navigation, no popups, no referrer.
 */
export function SiteArtifactCanvas({
  binding,
  onRenderKindChange,
}: {
  binding: SiteCanvasBinding;
  /** Present only while this canvas is the one on screen (the stage's generating veil reads it). */
  onRenderKindChange?: (kind: VeilRenderKind) => void;
}) {
  // Destructured first: `binding` carries the iframe ref, so react-hooks/refs flags every
  // `binding.*` read during render as a ref read ("Cannot access refs during render").
  const { errorMessage, iframeRef, renderKind, src } = binding;
  const reporting = onRenderKindChange !== undefined;
  const onRenderKindChangeRef = useRef(onRenderKindChange);
  useEffect(() => {
    onRenderKindChangeRef.current = onRenderKindChange;
  });
  useEffect(() => {
    if (reporting) onRenderKindChangeRef.current?.(renderKind);
  }, [renderKind, reporting]);

  return (
    <>
      {src ? (
        <iframe
          className={styles.frame}
          ref={iframeRef}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin"
          src={src}
          style={renderKind === "ready" ? undefined : { display: "none" }}
          title="Website editor"
        />
      ) : null}
      {renderKind === "loading" ? <CanvasLoadingState /> : null}
      {renderKind === "error" ? <CanvasErrorState message={errorMessage ?? ""} /> : null}
      {renderKind === "empty" ? <CanvasEmptyState /> : null}
    </>
  );
}
