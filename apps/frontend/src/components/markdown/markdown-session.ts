/** Library-normalized output is a comparison baseline, never a replacement for saved raw bytes. */
export function bodyAfterMarkdownChange(raw: string, normalized: string | null, next: string): string {
  return next === normalized || next === raw ? raw : next;
}

export type MarkdownEditorStatus = { error: string | null; viewMode: "rich-text" | "source" | "diff" };

export function markdownCanSave(status: MarkdownEditorStatus): boolean {
  return status.error === null && status.viewMode === "rich-text";
}
