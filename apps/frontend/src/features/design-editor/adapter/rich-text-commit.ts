import {
  setRichTextOp,
  type LoadedWebDocument,
  type RichTextDocument,
  type WebOperation,
} from "../engine/webDocuments";
import { pageIdForNode } from "./page-address";

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
 * The page id is resolved by NODE MEMBERSHIP — never by taking the first page.
 * A node that belongs to no loaded page yields `null` (no operation) rather
 * than a guessed address: an op carrying the wrong `page_id` is a server
 * rejection at best and a cross-page write at worst. That rule now lives in
 * `page-address.ts` (extracted at W4.7, when the custom-component props commit
 * needed the identical resolution).
 */
export function richTextCommitToOperation(
  document: LoadedWebDocument | null,
  nodeId: string,
  content: RichTextDocument,
): WebOperation | null {
  const pageId = pageIdForNode(document, nodeId);
  if (!pageId) return null;
  return setRichTextOp(pageId, nodeId, content);
}
