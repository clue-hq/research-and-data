"use client";

// Editor-only (plan 6, ruling R8): the fallback header's menu labels typed in place. The header draws
// its menu itself; this wraps it in edit mode and writes a changed label into the header's props.
import { useEffect, useRef, type ReactNode } from "react";
import { useGetPuck } from "@puckeditor/core";
import { markMenuLabels, writeMenuLabel } from "./menu-labels";

type GetPuck = ReturnType<typeof useGetPuck>;

/** One menu label written into the props of the Puck item `itemId`, as one undo step. */
export function writeItemMenuLabel(getPuck: GetPuck, itemId: string, source: string, label: string): void {
  const { dispatch } = getPuck();
  dispatch({
    type: "setData",
    recordHistory: true,
    data: (previous) => ({
      ...previous,
      content: previous.content.map((item) => {
        if (item.props.id !== itemId) return item;
        const props = writeMenuLabel(item.props as Record<string, unknown>, source, label);
        return props ? { ...item, props: props as typeof item.props } : item;
      }),
    }),
  });
}

export function MenuLabels({ itemId, children }: { itemId: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const getPuck = useGetPuck();
  // Re-marked after every draw: React may replace the labels' elements.
  useEffect(() => {
    const root = ref.current;
    return root ? markMenuLabels(root, (source, label) => writeItemMenuLabel(getPuck, itemId, source, label)) : undefined;
  });
  return (
    <div ref={ref} style={{ display: "contents" }}>
      {children}
    </div>
  );
}
