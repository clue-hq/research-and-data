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
