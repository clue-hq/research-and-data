import assert from "node:assert/strict";
import test from "node:test";

import type { WebDocumentOptions } from "./webDocuments";
import {
  applyWebOperations,
  fetchWebRenderHtml,
  removePageOp,
  setFragmentTextOverrideOp,
  setPageMetaOp,
  WebOperationsError,
} from "./webDocuments";

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

/** F5 task 19: the design API flattens every checked-apply rejection to one
 * envelope code (`web_operations.invalid`) and keeps the ENGINE's own refusal
 * code beside it (`detail.engine_code` — `op.route_exists`, `op.route_invalid`,
 * …). The inspector's route field branches on that code to say which refusal
 * this was in its own words, so the error must carry it, not only the prose. */
test("a 422 carries the engine's own refusal code", async () => {
  const fetchImpl = (async () =>
    new Response(
      JSON.stringify({
        detail: {
          code: "web_operations.invalid",
          engine_code: "op.route_exists",
          message: "route `/pricing` is already taken",
          diagnostics: [],
        },
      }),
      { status: 422, headers: { "content-type": "application/json" } },
    )) as unknown as typeof fetch;

  const error = await applyWebOperations(
    { apiBaseUrl: "http://api.test", fetchImpl },
    "doc_1",
    [setPageMetaOp("pricing", { route: "/pricing" })],
  ).then(
    () => null,
    (cause: unknown) => cause,
  );

  assert.ok(error instanceof WebOperationsError);
  assert.equal(error.kind, "invalid");
  assert.equal(error.code, "web_operations.invalid");
  assert.equal(error.engineCode, "op.route_exists");
  assert.equal(error.message, "route `/pricing` is already taken");
});

/** No `engine_code` (a 409, or an older server) reads as absent, never as a
 * code the field could branch on. */
test("an error without an engine code reads as null", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ detail: { code: "web_operations.stale" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;

  const error = await applyWebOperations(
    { apiBaseUrl: "http://api.test", fetchImpl },
    "doc_1",
    [removePageOp("pricing")],
  ).then(
    () => null,
    (cause: unknown) => cause,
  );

  assert.ok(error instanceof WebOperationsError);
  assert.equal(error.engineCode, null);
});

/** Slice 3 (R-A6): the ONE interior edit a human may make to a clone — the text
 * of one element inside it, addressed by the same structural path an annotation
 * uses. The builder is pinned because the engine's op is a serde struct where
 * `override` is an OPTION: absent (or null) means CLEAR, and a `{override:
 * undefined}` key would serialize to `"override": null` in some encoders and to
 * nothing in others. Spelling the clear as an OMITTED key is what makes the two
 * agree. */
test("the override op builder spells the engine's wire shape", () => {
  assert.deepEqual(
    setFragmentTextOverrideOp("home", "frg_a", ":nth-child(1)", {
      text: "New",
      bold: true,
      italic: false,
      underline: false,
      size: 1,
    }),
    {
      kind: "set_fragment_text_override",
      page_id: "home",
      id: "frg_a",
      path: ":nth-child(1)",
      override: { text: "New", bold: true, italic: false, underline: false, size: 1 },
    },
  );
  assert.deepEqual(setFragmentTextOverrideOp("home", "frg_a", ":nth-child(1)", null), {
    kind: "set_fragment_text_override",
    page_id: "home",
    id: "frg_a",
    path: ":nth-child(1)",
  });
});
