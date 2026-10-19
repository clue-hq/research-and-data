import assert from "node:assert/strict";
import { test } from "node:test";
import type { WebAnnotation } from "@/features/design-editor/adapter/annotations";
import { addressKey, addressObjectId } from "@/features/design-editor/engine/webBridge";
import { annotationContextRefs } from "@/features/chat-shell/model/edit-targets";
import { siteAnnotationAddress, siteObjectId } from "./site-annotations";

test("the object id is exactly what Lane A3 validates", () => {
  assert.equal(siteObjectId("/analysis", "Hero-1a2b"), "site:/analysis#Hero-1a2b");
  assert.equal(siteObjectId("/analysis", "Hero-1a2b", "title"), "site:/analysis#Hero-1a2b.title");
  assert.equal(siteObjectId("/", "cta"), "site:/#cta");
  assert.equal(siteObjectId("shell", "header"), "site:shell#header");
});

test("a site address rides the web lane's annotation machinery unchanged", () => {
  const address = siteAnnotationAddress("/analysis", "Hero-1a2b", "FeatureSplit");
  assert.equal(addressObjectId(address), "site:/analysis#Hero-1a2b");
  assert.notEqual(addressKey(address), addressKey(siteAnnotationAddress("/", "Hero-1a2b", "FeatureSplit")));
});

test("a site turn carries one document ref and one noted design_node ref per annotation, in badge order", () => {
  const item = (n: number, target: string, componentId: string, note: string): WebAnnotation => ({
    address: siteAnnotationAddress(target, componentId, "StatsBand"),
    n,
    name: "Stats band",
    note,
    pageId: target === "shell" ? "/" : target,
    textLike: false,
  });
  assert.deepEqual(
    annotationContextRefs({
      documentId: "doc-site",
      documentVersion: 7,
      items: [item(2, "shell", "header", "Use the full district name"), item(1, "/", "proof", "Lead with 7.4%")],
    }),
    [
      { objectId: "doc-site", objectType: "design_document", version: 7 },
      { note: "1. Lead with 7.4%", objectId: "site:/#proof", objectType: "design_node", version: 7 },
      { note: "2. Use the full district name", objectId: "site:shell#header", objectType: "design_node", version: 7 },
    ],
  );
});
