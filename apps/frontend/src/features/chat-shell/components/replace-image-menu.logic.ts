/** Option A (founder ruling R-C): the two sources behind "Replace image". Labels carry NO format
 * list — the file dialog's `accept` and the server's sniff own that. */
export const REPLACE_IMAGE_MENU_ROWS = [
  { id: "upload", label: "Upload from computer" },
  { id: "library", label: "Choose from asset library" },
] as const;

export type ReplaceImageMenuRow = (typeof REPLACE_IMAGE_MENU_ROWS)[number]["id"];

export function replaceImageMenuAction(
  row: ReplaceImageMenuRow,
): { kind: "open-file-dialog" } | { kind: "open-library" } {
  return row === "upload" ? { kind: "open-file-dialog" } : { kind: "open-library" };
}
