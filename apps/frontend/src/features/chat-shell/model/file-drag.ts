/**
 * A drag only concerns the composer when the pointer is carrying FILES. A
 * text-selection drag inside the chat (or a dragged link) reports its own MIME
 * types and must leave the drop target alone, so every drag handler asks this
 * first.
 */
export function dragCarriesFiles(
  types: readonly string[] | DOMStringList | undefined,
): boolean {
  if (!types) return false;
  return Array.from(types as ArrayLike<string>).includes("Files");
}

/**
 * The drop target's nesting counter. Dragging across a pane's children fires
 * `dragleave` on the one you left BEFORE `dragenter` on the one you entered, so
 * the target is "still under the pointer" while the depth is above zero; a
 * plain boolean would flicker off and on at every child boundary. Clamped at
 * zero because a drag that began outside the pane can deliver a stray leave.
 */
export function nextDragDepth(depth: number, event: "enter" | "leave"): number {
  if (event === "enter") return depth + 1;
  return Math.max(0, depth - 1);
}

/**
 * The files a drop is carrying, as a real array. `DataTransfer.files` is a live
 * `FileList` that the browser may empty once the event handler returns, so the
 * copy is taken eagerly and is what the intake receives.
 */
export function filesFromDrop(
  dataTransfer: { files: ArrayLike<File> } | null | undefined,
): File[] {
  if (!dataTransfer) return [];
  return Array.from(dataTransfer.files);
}
