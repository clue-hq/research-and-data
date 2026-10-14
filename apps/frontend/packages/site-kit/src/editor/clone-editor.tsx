"use client";

// Editor-only view of a cloned section: text slots become editable in place on the canvas.
// On blur the new wording is written back into this component's `slots` prop, so the field
// panel, undo history and saved page all see the same change. Published pages never load this.
import { useEffect, useRef } from "react";
import { useGetPuck } from "@puckeditor/core";
import type { Clone } from "../clone";
import { CloneMarkup } from "../clone-markup";

export function CloneEditor({
  itemId,
  clone,
  html,
  htmlFor,
}: {
  itemId: string;
  clone: Clone;
  html: string;
  htmlFor: (key: string, value: string) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const getPuck = useGetPuck();
  // Latest-value ref, written in a passive effect (this repo's react-hooks rule): `htmlFor` is a new
  // function on every render, and re-running the marking effect for it would forget what a focused
  // slot held when the marketer clicked in.
  const htmlForRef = useRef(htmlFor);
  useEffect(() => {
    htmlForRef.current = htmlFor;
  });
  // The slot the marketer clicked into, from another slot of this clone, while that slot's write was
  // about to rebuild the clone's markup (sync-fix review F7). Exactly one rebuild follows a write —
  // React's (the markup changed) or the redraw below (it did not) — and it detaches the clicked slot,
  // leaving the caret nowhere; after it, the slot with the same key takes the focus back.
  const resumeKey = useRef<string | null>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const cleanups: (() => void)[] = [];
    const resumeFocus = () => {
      const key = resumeKey.current;
      resumeKey.current = null;
      const document = root.ownerDocument;
      if (key === null || root.contains(document.activeElement)) return;
      const slot = root.querySelector<HTMLElement>(`[data-lumen-slot="${CSS.escape(key)}"]`);
      if (!slot) return;
      slot.focus();
      const range = document.createRange();
      range.selectNodeContents(slot);
      range.collapse(false);
      const selection = document.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    };
    const markSlots = () => {
      for (const element of root.querySelectorAll<HTMLElement>("[data-lumen-slot]")) {
        const key = element.getAttribute("data-lumen-slot") ?? "";
        if (clone.slots[key]?.kind !== "text") continue;
        element.contentEditable = "true";
        element.style.outline = "none";
        element.style.cursor = "text";
        // Puck disables pointer events inside components and re-enables them only for elements
        // marked as overlay portals (how its own inline fields work), so slots opt in the same way.
        element.setAttribute("data-puck-overlay-portal", "true");
        // The text as it stood when the marketer clicked in: leaving without typing writes nothing
        // (review finding S1-2 — the browser's innerText never equals the captured wording when the
        // markup has a <br> or a non-breaking space, so a click-away used to flatten and save it).
        let atFocus: string | null = null;
        const onFocus = () => {
          atFocus = element.innerText;
        };
        const onBlur = (event: FocusEvent) => {
          if (atFocus !== null && element.innerText === atFocus) return;
          const value = element.innerText.replace(/\s+/g, " ").trim();
          // (No `instanceof`: the canvas may live in another frame's realm.)
          const next = event.relatedTarget as Element | null;
          resumeKey.current = next && root.contains(next) ? next.getAttribute("data-lumen-slot") : null;
          const { dispatch } = getPuck();
          dispatch({
            type: "setData",
            recordHistory: true,
            data: (previous) => ({
              ...previous,
              content: previous.content.map((item) =>
                item.props.id === itemId
                  ? { ...item, props: { ...item.props, slots: { ...item.props.slots, [key]: value } } }
                  : item,
              ),
            }),
          });
          // A write that leaves the markup as it is (an emptied slot shows the clone's own wording;
          // a normalised one is the same text) gets no re-render from React, so the canvas would keep
          // what the marketer typed while the saved page shows something else (review finding S1-4).
          // Put back exactly the markup that will publish — once the focus has moved (a redraw inside
          // the blur would detach the slot being clicked), and only if the markup is still this one
          // (the effect's cleanup cancels it when React rebuilds first).
          if (htmlForRef.current(key, value) === html) {
            const redraw = root.ownerDocument.defaultView?.setTimeout(() => {
              root.innerHTML = html;
              markSlots();
              resumeFocus();
            }, 0);
            cleanups.push(() => root.ownerDocument.defaultView?.clearTimeout(redraw));
          }
        };
        const stop = (event: Event) => event.stopPropagation();
        element.addEventListener("focus", onFocus);
        element.addEventListener("blur", onBlur);
        element.addEventListener("click", stop);
        element.addEventListener("pointerdown", stop);
        cleanups.push(() => {
          element.removeEventListener("focus", onFocus);
          element.removeEventListener("blur", onBlur);
          element.removeEventListener("click", stop);
          element.removeEventListener("pointerdown", stop);
        });
      }
    };
    markSlots();
    // This run follows React rebuilding the markup (a changed `html`): resume a slot clicked meanwhile.
    resumeFocus();
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [html, clone, itemId, getPuck]);

  // The effect re-marks the slots whenever `html` changes, which is exactly when CloneMarkup
  // rebuilds the markup; an unchanged clone keeps its DOM and its marks.
  return <CloneMarkup clone={clone} html={html} ref={ref} />;
}
