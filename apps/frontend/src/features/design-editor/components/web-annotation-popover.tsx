"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Trash2Icon, XIcon } from "lucide-react";

import type { PendingAnnotation } from "../adapter/annotations";
import type { WebElementAddress } from "../engine/webBridge";
import { computePopoverPosition } from "./web-annotation-popover.logic";
import styles from "./web-annotation-popover.module.css";

/**
 * Slice 3 (rulings R-A1 / R-A2): the comment box a single click in Edit mode
 * opens on the element under the cursor.
 *
 * Canvas UI, like the rich-text toolbar beside it: `position: fixed`, anchored
 * against the iframe's bounding rect plus the element geometry the bridge
 * reported, and portalled to <body> by the canvas (the artifact workspace
 * carries a transform, which would otherwise become the containing block and
 * clip it — see the portal note in `web-artifact-canvas.tsx`).
 *
 * The two buttons are R-A2's: **Add** stores the note as a numbered chip, and
 * **Send to chat** stores it and submits the turn immediately. `onSend` and
 * `onEditText` are OPTIONAL and their controls are absent when they are not
 * provided — the composer chips (task 7) and the clone text editor (task 16)
 * own those halves, and a button that cannot do anything is worse than no
 * button.
 */
export function WebAnnotationPopover({
  iframeRef,
  onAdd,
  onDismiss,
  onEditText,
  onSend,
  pending,
}: {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  onAdd: (note: string) => void;
  onDismiss: () => void;
  /** Task 16: open the constrained inline editor on this element. */
  onEditText?: (address: WebElementAddress) => void;
  /** Task 7: store the annotation and submit the turn in one action. */
  onSend?: (note: string) => void;
  pending: PendingAnnotation;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [note, setNote] = useState("");
  const [position, setPosition] = useState<{ left: number; top: number } | null>(
    null,
  );

  const elementRect = pending.geometry.viewport;
  const recompute = useCallback(() => {
    const iframe = iframeRef.current;
    const card = cardRef.current;
    if (!iframe || !card) {
      setPosition(null);
      return;
    }
    const frame = iframe.getBoundingClientRect();
    const box = card.getBoundingClientRect();
    setPosition(
      computePopoverPosition(
        {
          left: frame.left,
          top: frame.top,
          width: frame.width,
          height: frame.height,
        },
        {
          x: elementRect.x,
          y: elementRect.y,
          width: elementRect.width,
          height: elementRect.height,
        },
        { width: box.width, height: box.height },
        { width: window.innerWidth, height: window.innerHeight },
      ),
    );
  }, [
    elementRect.height,
    elementRect.width,
    elementRect.x,
    elementRect.y,
    iframeRef,
  ]);

  useLayoutEffect(() => {
    recompute();
  }, [recompute]);

  useEffect(() => {
    const onViewportChange = () => recompute();
    window.addEventListener("resize", onViewportChange, { passive: true });
    window.addEventListener("scroll", onViewportChange, {
      capture: true,
      passive: true,
    });
    return () => {
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [recompute]);

  // Escape anywhere, and a press outside both the card and the canvas, close
  // the box. A press INSIDE the canvas is left alone deliberately: the bridge
  // answers it with a new `annotate`, which replaces this box with one on the
  // element just clicked — closing here first would only make it flicker.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onDismiss();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (cardRef.current?.contains(target)) return;
      if (iframeRef.current && iframeRef.current === target) return;
      onDismiss();
    };
    window.addEventListener("keydown", onKeyDown, true);
    window.document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [iframeRef, onDismiss]);

  const blank = note.trim().length === 0;

  return (
    <div
      ref={cardRef}
      className={`${styles.card}${position ? ` ${styles.positioned}` : ""}`}
      style={position ? { left: `${position.left}px`, top: `${position.top}px` } : undefined}
      role="dialog"
      aria-label={`Comment on ${pending.name}`}
      onClick={(event) => event.stopPropagation()}
    >
      <div className={styles.head}>
        <span className={styles.chip} title={pending.name}>
          {pending.name}
        </span>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Close"
          title="Close"
          onClick={onDismiss}
        >
          <XIcon aria-hidden="true" size={14} />
        </button>
      </div>
      <textarea
        // The box exists because the user just clicked the element to write
        // about it; landing anywhere but the field would make every annotation
        // a two-click affair. One box is mounted at a time (the canvas keys it
        // on the address), so this never steals focus from another.
        autoFocus
        className={styles.field}
        placeholder="Edit or ask a question"
        aria-label="Annotation"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className={styles.foot}>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Discard"
          title="Discard"
          onClick={onDismiss}
        >
          <Trash2Icon aria-hidden="true" size={14} />
        </button>
        {pending.textLike && onEditText ? (
          <button
            type="button"
            className={styles.link}
            onClick={() => onEditText(pending.address)}
          >
            Edit text
          </button>
        ) : null}
        <span className={styles.spacer} />
        {onSend ? (
          <button
            type="button"
            className={styles.button}
            disabled={blank}
            onClick={() => onSend(note)}
          >
            Send to chat
          </button>
        ) : null}
        <button
          type="button"
          className={`${styles.button} ${styles.primary}`}
          disabled={blank}
          onClick={() => onAdd(note)}
        >
          Add
        </button>
      </div>
    </div>
  );
}
