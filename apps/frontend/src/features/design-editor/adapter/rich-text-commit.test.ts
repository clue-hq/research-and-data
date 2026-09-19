import assert from "node:assert/strict";
import test from "node:test";
import type { LoadedWebDocument } from "../engine/webDocuments";
import {
  BODY_COMMIT_CONTENT,
  RICH_TEXT_PAGE,
  RICH_TEXT_PAGE_ID,
} from "./__fixtures__/web-rich-text";
import { richTextCommitToOperation } from "./rich-text-commit";

// W4.8a: the in-iframe session's `rich-text-commit` payload becomes exactly ONE
// canonical `set_rich_text` op, addressed to the page that actually contains the
// node — the same node-membership resolution `use-inspector-writes.ts` performs
// before every inspector write. The op below is wire-true: the identical batch
// (intent `rich_text_commit` + base_version) was accepted by the lane design API
// against the harvested document (200, version 1 → 2).

function loaded(pages: LoadedWebDocument["webDoc"]): LoadedWebDocument {
  return {
    documentId: "doc_c582718f5ceb4fb28cc5de7c5f8d44fb",
    docKind: "web",
    title: "Lane C rich-text test doc",
    webDoc: pages,
    currentVersion: 2,
    undoDepth: 0,
    redoDepth: 0,
    isTemplate: false,
    templateDocumentId: null,
    accountId: null,
    fragmentMeta: {},
  };
}

const document = loaded({
  pages: [
    { id: "other", name: "Other", route: "/other", root: "r2", nodes: { r2: { id: "r2", kind: "container", classes: "" } } },
    {
      id: RICH_TEXT_PAGE_ID,
      name: "Home",
      route: "/",
      root: RICH_TEXT_PAGE.page_root,
      nodes: RICH_TEXT_PAGE.nodes,
    },
  ],
});

test("a committed body node becomes one set_rich_text op on its own page", () => {
  const operation = richTextCommitToOperation(document, "txtbody", BODY_COMMIT_CONTENT);
  assert.deepEqual(operation, {
    kind: "set_rich_text",
    page_id: "home",
    id: "txtbody",
    content: BODY_COMMIT_CONTENT,
  });
});

test("the page is resolved by node membership, not by taking the first page", () => {
  // `txtbody` lives on the SECOND page here; a first-page shortcut would
  // address the op to "other" and the server would reject it.
  const operation = richTextCommitToOperation(document, "txthead", BODY_COMMIT_CONTENT);
  assert.equal(operation?.kind === "set_rich_text" ? operation.page_id : null, "home");
});

test("a node on no page yields no operation (never a guessed page id)", () => {
  assert.equal(richTextCommitToOperation(document, "nosuchnode", BODY_COMMIT_CONTENT), null);
});

test("no loaded document and no pages both yield no operation", () => {
  assert.equal(richTextCommitToOperation(null, "txtbody", BODY_COMMIT_CONTENT), null);
  assert.equal(
    richTextCommitToOperation(loaded(null), "txtbody", BODY_COMMIT_CONTENT),
    null,
  );
  assert.equal(
    richTextCommitToOperation(loaded({ pages: [] }), "txtbody", BODY_COMMIT_CONTENT),
    null,
  );
});
