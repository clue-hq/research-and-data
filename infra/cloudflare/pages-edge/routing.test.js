import assert from "node:assert/strict";
import { test } from "node:test";

import { decide } from "./routing.js";

const env = { SYSTEM_SUFFIX: "pages.cluehq.ai", ORIGIN_HOST: "page-origin.cluehq.ai", EDGE_SECRET: "s" };
const req = (url, method = "GET", headers = {}) => new Request(url, { method, headers });

test("system and customer hostnames are forwarded with the public host and the secret", () => {
  for (const url of ["https://acme.pages.cluehq.ai/annual-report?x=1", "https://go.acme.com/annual-report?x=1"]) {
    const decision = decide(req(url, "GET", { "x-clue-public-host": "spoofed", "x-clue-edge-auth": "spoofed" }), env);
    assert.equal(decision.kind, "forward");
    assert.equal(decision.target, "https://page-origin.cluehq.ai/annual-report?x=1");
    assert.equal(decision.headers.get("x-clue-public-host"), new URL(url).hostname);
    assert.equal(decision.headers.get("x-clue-edge-auth"), "s");
  }
});

test("the bare system suffix is ours; other cluehq.ai records pass through untouched", () => {
  assert.equal(decide(req("https://pages.cluehq.ai/"), env).kind, "forward");
  assert.equal(decide(req("https://app.cluehq.ai/login"), env).kind, "passthrough");
  assert.equal(decide(req("https://cluehq.ai/"), env).kind, "passthrough");
});

test("only GET and HEAD reach the origin", () => {
  assert.equal(decide(req("https://go.acme.com/x", "POST"), env).kind, "method_not_allowed");
  assert.equal(decide(req("https://go.acme.com/x", "HEAD"), env).kind, "forward");
});
