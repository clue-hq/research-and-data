// The Worker's real fetch handler (worker.js), not just the routing decision: what it RETURNS to
// the visitor and what it SENDS upstream. `globalThis.fetch` is the Workers runtime's subrequest
// API; each test swaps in a stub that records its calls, and restores the real one afterwards.
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import worker from "./worker.js";

const ORIGIN_HOST = "page-origin.cluehq.ai";
const SECRET = "edge-secret";

/** wrangler.toml's [vars] as shipped today: no legacy list. */
const today = { SYSTEM_SUFFIX: "pages.cluehq.ai", LEGACY_SYSTEM_SUFFIXES: "", ORIGIN_HOST, EDGE_SECRET: SECRET };
/** The same vars after runbook §8's move: the new domain, the old suffix kept as legacy. */
const moved = {
  SYSTEM_SUFFIX: "clue-pages.example",
  LEGACY_SYSTEM_SUFFIXES: "pages.cluehq.ai",
  ORIGIN_HOST,
  EDGE_SECRET: SECRET,
};

const realFetch = globalThis.fetch;
let calls;
let upstream;

beforeEach(() => {
  calls = [];
  upstream = new Response("from upstream", { status: 200, headers: { "x-upstream": "yes" } });
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return upstream;
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

/** A visitor request carrying the two headers only the Worker may set, spoofed. */
const visitor = (url, method = "GET") =>
  new Request(url, {
    method,
    headers: {
      "x-clue-public-host": "victim.pages.cluehq.ai",
      "x-clue-edge-auth": "guessed-secret",
      "accept-language": "en-GB",
    },
  });

async function assertForwarded(env, url, host) {
  const response = await worker.fetch(visitor(url), env);
  assert.equal(response, upstream, "the visitor gets the origin's own response");
  assert.equal(calls.length, 1, "exactly one subrequest");
  assert.equal(calls[0].length, 1, "the subrequest is one Request, no init object");
  const [sent] = calls[0];
  assert.ok(sent instanceof Request);
  const original = new URL(url);
  assert.equal(sent.url, `https://${ORIGIN_HOST}${original.pathname}${original.search}`);
  assert.equal(sent.method, "GET");
  assert.equal(sent.redirect, "manual", "the origin's fallback 302 must reach the browser");
  assert.equal(sent.headers.get("x-clue-public-host"), host);
  assert.equal(sent.headers.get("x-clue-edge-auth"), SECRET);
  assert.equal(sent.headers.get("accept-language"), "en-GB", "other visitor headers pass through");
}

async function assertMethodNotAllowed(env, url) {
  const response = await worker.fetch(visitor(url, "POST"), env);
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD");
  assert.equal(await response.text(), "");
  assert.equal(calls.length, 0, "a refused method never reaches the origin");
}

async function assertPassthrough(env, url) {
  const request = visitor(url);
  const response = await worker.fetch(request, env);
  assert.equal(response, upstream);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].length, 1);
  assert.equal(calls[0][0], request, "the ORIGINAL request object, untouched");
  assert.equal(calls[0][0].headers.get("x-clue-edge-auth"), "guessed-secret", "nothing stamped on it");
}

// --- after the move -----------------------------------------------------------------------------

test("moved: an old <label>.pages.cluehq.ai URL answers 301 to the same label, path and query", async () => {
  const response = await worker.fetch(visitor("https://acme.pages.cluehq.ai/annual-report/analysis?q=1&r=two"), moved);
  assert.equal(response.status, 301);
  assert.equal(response.headers.get("location"), "https://acme.clue-pages.example/annual-report/analysis?q=1&r=two");
  assert.equal(calls.length, 0, "a redirect is answered at the edge");
  // HEAD is read-only too, so it redirects the same way.
  const head = await worker.fetch(visitor("https://acme.pages.cluehq.ai/annual-report?q=1", "HEAD"), moved);
  assert.equal(head.status, 301);
  assert.equal(head.headers.get("location"), "https://acme.clue-pages.example/annual-report?q=1");
  assert.equal(calls.length, 0);
});

test("moved: a new system host and a custom domain are forwarded to the origin with the secret", async () => {
  await assertForwarded(moved, "https://acme.clue-pages.example/annual-report/analysis?q=1", "acme.clue-pages.example");
  calls = [];
  await assertForwarded(moved, "https://go.acme.com/annual-report?q=1", "go.acme.com");
});

test("moved: app.cluehq.ai passes through untouched", async () => {
  await assertPassthrough(moved, "https://app.cluehq.ai/login?next=%2Fprojects");
});

test("moved: a POST to a system host (old or new) is 405 and never reaches the origin", async () => {
  await assertMethodNotAllowed(moved, "https://acme.clue-pages.example/annual-report");
  await assertMethodNotAllowed(moved, "https://acme.pages.cluehq.ai/annual-report");
});

// --- today (no legacy list): the same four behave as before the move ----------------------------

test("today: <label>.pages.cluehq.ai is the system host itself and is forwarded, not redirected", async () => {
  await assertForwarded(today, "https://acme.pages.cluehq.ai/annual-report/analysis?q=1", "acme.pages.cluehq.ai");
});

test("today: a custom domain is forwarded to the origin with the secret", async () => {
  await assertForwarded(today, "https://go.acme.com/annual-report?q=1", "go.acme.com");
});

test("today: app.cluehq.ai passes through untouched", async () => {
  await assertPassthrough(today, "https://app.cluehq.ai/login?next=%2Fprojects");
});

test("today: a POST to a system host is 405 and never reaches the origin", async () => {
  await assertMethodNotAllowed(today, "https://acme.pages.cluehq.ai/annual-report");
});
