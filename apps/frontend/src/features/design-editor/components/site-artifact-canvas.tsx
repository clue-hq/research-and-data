"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { SiteCanvasBinding } from "@/features/site-editor/model/site-stage";
import type { VeilRenderKind } from "../adapter/generating-veil";
import { addressKey } from "../engine/webBridge";
import { CanvasEmptyState, CanvasErrorState, CanvasLoadingState } from "./canvas-states";
import { WebAnnotationPopover } from "./web-annotation-popover";
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
  const { annotations, editing, errorMessage, iframeRef, renderKind, src } = binding;
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
      {/* C7: the web lane's comment box, positioned from the iframe's rect plus the geometry the
       * frame reported; portalled to <body> because `.artifactWorkspace` carries a transform. */}
      {renderKind === "ready" && editing && annotations?.pending
        ? createPortal(
            <WebAnnotationPopover
              iframeRef={iframeRef}
              key={addressKey(annotations.pending.address)}
              onAdd={(note) => annotations?.add(note)}
              onDismiss={annotations.dismiss}
              onEditNote={annotations.editNote}
              onSend={annotations.onSend}
              pending={annotations.pending}
            />,
            window.document.body,
          )
        : null}
    </>
  );
}
