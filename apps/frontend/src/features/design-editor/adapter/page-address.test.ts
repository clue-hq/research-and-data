import assert from "node:assert/strict";
import test from "node:test";
import type { LoadedWebDocument } from "../engine/webDocuments";
import {
  CUSTOM_COMPONENT_PAGE,
  CUSTOM_COMPONENT_PAGE_ID,
} from "./__fixtures__/web-custom-component";
import { pageIdForNode } from "./page-address";

// W4.7: the node → page resolution shared by every addressed write. It was
// `rich-text-commit.ts`'s private lookup until the custom-component props
// commit needed the identical rule; one addressing rule, one implementation.
// Fixture is the seeded account-bound lane-C document, whose custom-component
// node really does live on the SECOND page below.

function loaded(pages: LoadedWebDocument["webDoc"]): LoadedWebDocument {
  return {
    documentId: "doc_b778a805381c4831844c490e30701719",
    docKind: "web",
    title: "Lane C custom-component test doc",
    webDoc: pages,
    currentVersion: 1,
    undoDepth: 0,
    redoDepth: 0,
    isTemplate: false,
    templateDocumentId: null,
    accountId: "acc_403fa12213464a9cbb2a9a1dab3663db",
    fragmentMeta: {},
  };
}

const document = loaded({
  pages: [
    {
      id: "other",
      name: "Other",
      route: "/other",
      root: "r2",
      nodes: { r2: { id: "r2", kind: "container", classes: "" } },
    },
    {
      id: CUSTOM_COMPONENT_PAGE_ID,
      name: "Home",
      route: "/",
      root: CUSTOM_COMPONENT_PAGE.page_root,
      nodes: CUSTOM_COMPONENT_PAGE.nodes,
    },
  ],
});

test("a node resolves to the page that actually contains it, not the first page", () => {
  assert.equal(pageIdForNode(document, "cclanec1"), CUSTOM_COMPONENT_PAGE_ID);
  assert.equal(pageIdForNode(document, "r2"), "other");
});

test("a node on no loaded page has no address", () => {
  assert.equal(pageIdForNode(document, "nope"), null);
});

test("no document, or a document with no scene, has no address", () => {
  assert.equal(pageIdForNode(null, "cclanec1"), null);
  assert.equal(pageIdForNode(loaded(null), "cclanec1"), null);
  assert.equal(pageIdForNode(loaded({}), "cclanec1"), null);
});
