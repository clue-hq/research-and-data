"use client";

// Editor-only view of a cloned section: text slots become editable in place on the canvas.
// The new wording is written back into this component's `slots` prop after a short pause in typing
// and when the marketer leaves the slot, so the field panel, undo history and saved page all see the
// same change. Published pages never load this.
import { useEffect, useRef, useState } from "react";
import { useGetPuck } from "@puckeditor/core";
import type { Clone } from "../clone";
import { CloneMarkup } from "../clone-markup";
import { normalizeRich, richText } from "../rich";
import { richFromDom } from "./rich-text";

/** The pause after the last keystroke in a cloned text slot before its wording is written. Without
 * it, typing reached the page only when the slot lost focus, and a reload while still typing lost it
 * (the founder's live walk, 2026-10-14). */
export const CLONE_TEXT_PAUSE_MS = 500;

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
  // Latest-value refs, written in a passive effect (this repo's react-hooks rule): `htmlFor` is a new
  // function on every render, and re-running the marking effect for it would forget what a focused
  // slot held when the marketer clicked in.
  const htmlForRef = useRef(htmlFor);
  const htmlRef = useRef(html);
  useEffect(() => {
    htmlForRef.current = htmlFor;
    htmlRef.current = html;
  });
  // While the marketer is in one of this clone's text slots, the markup is held as it was when they
  // clicked in. Each write changes `html`, and redrawing the markup would take the caret out of the
  // slot mid-word (or out of a sibling slot just clicked: sync-fix review F7). Leaving the clone lets
  // the markup catch up with what will publish.
  const [held, setHeld] = useState<string | null>(null);
  const shown = held ?? html;
  // Whether a slot was written while the markup was held (the markup must then be brought up to date
  // when the marketer leaves, even if its HTML string did not change: review finding S1-4).
  const wroteWhileHeld = useRef(false);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const view = root.ownerDocument.defaultView;
    const cleanups: (() => void)[] = [];
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
        // The text as it stood when the marketer clicked in, then as last written: leaving or pausing
        // without a change writes nothing (review finding S1-2 — a click-away used to flatten and save
        // it). The slot is rich text (plan 2): what is written is the slot's words with their bold,
        // italic, underline, links and styled spans, in the grammar's form (the browser's own ⌘B makes
        // <b>, which is read as bold).
        let unchangedText: string | null = null;
        let pause: number | null = null;
        const cancelPause = () => {
          if (pause !== null) view?.clearTimeout(pause);
          pause = null;
        };
        /** Write the slot's wording if it changed. Returns the value written, or null. */
        const write = (): string | null => {
          cancelPause();
          const text = normalizeRich(richFromDom(element));
          if (unchangedText !== null && text === unchangedText) return null;
          unchangedText = text;
          // No words left (the browser leaves a <br> in an emptied slot) is an empty slot.
          const value = richText(text).trim() === "" ? "" : text.replace(/\s+/g, " ").trim();
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
          wroteWhileHeld.current = true;
          return value;
        };
        const onFocus = () => {
          unchangedText = normalizeRich(richFromDom(element));
          setHeld((previous) => previous ?? shown);
        };
        const onInput = () => {
          cancelPause();
          pause = view?.setTimeout(write, CLONE_TEXT_PAUSE_MS) ?? null;
        };
        const onBlur = (event: FocusEvent) => {
          const value = write();
          // (No `instanceof`: the canvas may live in another frame's realm.)
          const next = event.relatedTarget as Element | null;
          if (next && root.contains(next)) return; // a sibling slot of this clone: keep holding
          // Leaving the clone: show the markup that will publish. When its HTML string is the one
          // held, React will not redraw it (an emptied slot shows the clone's own wording; a
          // normalised one is the same text), so it is put back here — after the focus has moved, and
          // only if React has not rebuilt the clone first (the effect's cleanup cancels it).
          const publishes = value !== null ? htmlForRef.current(key, value) : htmlRef.current;
          const redraw = wroteWhileHeld.current && publishes === shown;
          wroteWhileHeld.current = false;
          setHeld(null);
          if (!redraw) return;
          const handle = view?.setTimeout(() => {
            // React rebuilt the clone meanwhile (its markup changed after all): nothing to put back.
            if (!element.isConnected) return;
            root.innerHTML = publishes;
            markSlots();
          }, 0);
          cleanups.push(() => view?.clearTimeout(handle));
        };
        const stop = (event: Event) => event.stopPropagation();
        element.addEventListener("focus", onFocus);
        element.addEventListener("input", onInput);
        element.addEventListener("blur", onBlur);
        element.addEventListener("click", stop);
        element.addEventListener("pointerdown", stop);
        cleanups.push(() => {
          // A pause still running is dropped, not written: the slot is being torn down (another page,
          // a rebuilt clone), and a late write could land on whatever now has this item's id.
          cancelPause();
          element.removeEventListener("focus", onFocus);
          element.removeEventListener("input", onInput);
          element.removeEventListener("blur", onBlur);
          element.removeEventListener("click", stop);
          element.removeEventListener("pointerdown", stop);
        });
      }
    };
    markSlots();
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [shown, clone, itemId, getPuck]);

  // The effect re-marks the slots whenever the markup shown changes, which is exactly when
  // CloneMarkup rebuilds it; an unchanged clone keeps its DOM and its marks.
  return <CloneMarkup clone={clone} html={shown} ref={ref} />;
}
