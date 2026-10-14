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

const moved = {
  SYSTEM_SUFFIX: "clue-pages.example",
  LEGACY_SYSTEM_SUFFIXES: "pages.cluehq.ai",
  ORIGIN_HOST: "page-origin.cluehq.ai",
  EDGE_SECRET: "s",
};

test("after the move an old system hostname answers 301 to the same label, path and query", () => {
  assert.deepEqual(decide(req("https://acme.pages.cluehq.ai/annual-report/pricing?x=1"), moved), {
    kind: "redirect",
    status: 301,
    location: "https://acme.clue-pages.example/annual-report/pricing?x=1",
  });
  assert.equal(decide(req("https://acme.pages.cluehq.ai/x", "POST"), moved).kind, "method_not_allowed");
});

test("after the move new system hosts and custom hostnames are forwarded; other cluehq.ai records pass", () => {
  for (const url of ["https://acme.clue-pages.example/annual-report", "https://go.acme.com/annual-report", "https://pages.cluehq.ai/"]) {
    assert.equal(decide(req(url), moved).kind, "forward", url);
  }
  assert.equal(decide(req("https://app.cluehq.ai/login"), moved).kind, "passthrough");
  assert.equal(decide(req("https://cluehq.ai/"), moved).kind, "passthrough");
});

test("with no legacy suffix nothing redirects (today's configuration)", () => {
  assert.equal(decide(req("https://acme.pages.cluehq.ai/annual-report"), env).kind, "forward");
});

// Review finding K3-8: with published pages on the editor's registrable domain, the Worker forwarded
// every workspace's editor host to the page origin. Editor hosts are never ours, whatever the pages
// domain is.
test("editor hosts always pass through, even with the pages on the same registrable domain", () => {
  const shared = { ...env, SYSTEM_SUFFIX: "deeppresence.ai", EDITOR_SUFFIX: "edit.deeppresence.ai" };
  assert.equal(decide(req("https://aac8c47153e8e006ea26797aa03615b6.edit.deeppresence.ai/"), shared).kind, "passthrough");
  assert.equal(decide(req("https://edit.deeppresence.ai/"), shared).kind, "passthrough");
  assert.equal(decide(req("https://acme.deeppresence.ai/report"), shared).kind, "forward", "pages still served");
  assert.equal(decide(req("https://acme.pages.cluehq.ai/"), { ...env, EDITOR_SUFFIX: "" }).kind, "forward", "unset: as before");
});

// Review finding K3-6: runbook §8 step 2 deploys the Worker with ONLY the new zone's route added,
// SYSTEM_SUFFIX still the old one and no legacy list. A host on the new domain is outside every
// apex the Worker knows, so it is forwarded to the page origin like a customer's domain, which
// serves it by its label; nothing redirects yet, and cluehq.ai's other records still pass through.
test("before the redirect is turned on, the new domain's hosts are forwarded under the old config", () => {
  for (const url of ["https://acme.clue-pages.example/annual-report?x=1", "https://acme.pages.cluehq.ai/annual-report?x=1"]) {
    const decision = decide(req(url), env);
    assert.equal(decision.kind, "forward", url);
    assert.equal(decision.headers.get("x-clue-public-host"), new URL(url).hostname);
    assert.equal(decision.target, "https://page-origin.cluehq.ai/annual-report?x=1");
  }
  assert.equal(decide(req("https://app.cluehq.ai/login"), env).kind, "passthrough");
});
