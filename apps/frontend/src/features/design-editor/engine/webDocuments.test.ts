import assert from "node:assert/strict";
import test from "node:test";

import type { WebDocumentOptions } from "./webDocuments";
import { fetchWebRenderHtml } from "./webDocuments";

/** F5 task 5: the render endpoint is page-aware (`?page_id=`; omitted = the
 * document's first page). The shell must send the id when it has one and send
 * NOTHING when it does not — an empty/absent `page_id` is the first-page
 * default, never a literal empty param. */
test("fetchWebRenderHtml appends page_id when a page is named", async () => {
  const seen: string[] = [];
  const fetchImpl = (async (url: URL | string) => {
    seen.push(String(url));
    return new Response(JSON.stringify({ html: "<html></html>", diagnostics: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  const options: WebDocumentOptions = { apiBaseUrl: "http://api.test", fetchImpl };

  await fetchWebRenderHtml(options, "doc_1", "/rt.js", undefined, "pricing");
  assert.match(seen[0], /page_id=pricing/);

  await fetchWebRenderHtml(options, "doc_1", "/rt.js");
  assert.doesNotMatch(seen[1], /page_id/);
});
