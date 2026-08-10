import assert from "node:assert/strict";
import test from "node:test";
import { normalizeClerkProxyResponse } from "./clerk-proxy-response";

test("preserves Clerk's undefined pass-through result", () => {
  assert.equal(
    normalizeClerkProxyResponse("http://localhost:3000/projects/prj_1", undefined),
    undefined,
  );
  assert.equal(
    normalizeClerkProxyResponse("http://localhost:3000/projects/prj_1", null),
    null,
  );
});

test("turns Clerk's exact self-rewrite into a pass-through without losing auth headers", () => {
  const url = "http://localhost:3000/projects/prj_1";
  const response = new Response(null, {
    headers: {
      "x-clerk-auth-status": "signed-in",
      "x-middleware-request-x-clerk-auth-status": "signed-in",
      "x-middleware-rewrite": url,
    },
  });

  assert.equal(normalizeClerkProxyResponse(url, response), response);
  assert.equal(response.headers.get("x-middleware-rewrite"), null);
  assert.equal(response.headers.get("x-middleware-next"), "1");
  assert.equal(response.headers.get("x-clerk-auth-status"), "signed-in");
  assert.equal(
    response.headers.get("x-middleware-request-x-clerk-auth-status"),
    "signed-in",
  );
});

test("leaves a real Clerk rewrite untouched", () => {
  const requestUrl = "http://localhost:3000/projects/prj_1";
  const rewriteUrl = "http://localhost:3000/sign-in";
  const response = new Response(null, {
    headers: { "x-middleware-rewrite": rewriteUrl },
  });

  assert.equal(normalizeClerkProxyResponse(requestUrl, response), response);
  assert.equal(response.headers.get("x-middleware-rewrite"), rewriteUrl);
  assert.equal(response.headers.get("x-middleware-next"), null);
});
