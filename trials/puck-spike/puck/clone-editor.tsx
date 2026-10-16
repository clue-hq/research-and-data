"use client";

// Editor-only view of a cloned section: text slots become editable in place on the canvas.
// On blur the new wording is written back into this component's `slots` prop, so the field
// panel, undo history and saved page all see the same change. Published pages never load this.
import { useEffect, useRef } from "react";
import { useGetPuck } from "@puckeditor/core";
import type { Clone } from "@/lib/clone";

export function CloneEditor({ itemId, clone, html }: { itemId: string; clone: Clone; html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const getPuck = useGetPuck();

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const cleanups: (() => void)[] = [];
    for (const element of root.querySelectorAll<HTMLElement>("[data-lumen-slot]")) {
      const key = element.getAttribute("data-lumen-slot") ?? "";
      if (clone.slots[key]?.kind !== "text") continue;
      element.contentEditable = "true";
      element.style.outline = "none";
      element.style.cursor = "text";
      // Puck disables pointer events inside components and re-enables them only for elements
      // marked as overlay portals (how its own inline fields work), so slots opt in the same way.
      element.setAttribute("data-puck-overlay-portal", "true");
      const onBlur = () => {
        const value = element.innerText.replace(/\s+/g, " ").trim();
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
      };
      const stop = (event: Event) => event.stopPropagation();
      element.addEventListener("blur", onBlur);
      element.addEventListener("click", stop);
      element.addEventListener("pointerdown", stop);
      cleanups.push(() => {
        element.removeEventListener("blur", onBlur);
        element.removeEventListener("click", stop);
        element.removeEventListener("pointerdown", stop);
      });
    }
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [html, clone, itemId, getPuck]);

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: clone.css }} />
      <div
        ref={ref}
        className={`lumen-fragment ${clone.wrapper_class}`}
        data-lumen-fragment="true"
        data-fragment-id={clone.id}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </>
  );
}
