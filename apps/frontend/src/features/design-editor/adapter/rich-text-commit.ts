import {
  setRichTextOp,
  type LoadedWebDocument,
  type RichTextDocument,
  type WebOperation,
} from "../engine/webDocuments";

/**
 * W4.8a: the rich-text commit adapter — the in-iframe Lexical session's
 * `rich-text-commit` payload → exactly ONE canonical `set_rich_text`
 * operation, which the shell persists through the SAME manual-edits
 * controller every inspector write uses (one in-flight mutation,
 * `base_version` on every apply, 409 → quiet reload, 422 → inline
 * diagnostic). There is deliberately no second write path.
 *
 * Source semantics: `WebEditorApp.tsx:331-340` →
 * `applyOps([setRichTextOp(pageId, nodeId, content)], "rich_text_commit")`.
 *
 * The page id is resolved by NODE MEMBERSHIP — the same lookup
 * `use-inspector-writes.ts` performs before every inspector write — never by
 * taking the first page. A node that belongs to no loaded page yields `null`
 * (no operation) rather than a guessed address: an op carrying the wrong
 * `page_id` is a server rejection at best and a cross-page write at worst.
 */
export function richTextCommitToOperation(
  document: LoadedWebDocument | null,
  nodeId: string,
  content: RichTextDocument,
): WebOperation | null {
  const page = document?.webDoc?.pages?.find((candidate) =>
    Boolean(candidate.nodes?.[nodeId]),
  );
  if (!page) return null;
  return setRichTextOp(page.id, nodeId, content);
}
