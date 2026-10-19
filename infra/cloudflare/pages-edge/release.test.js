// The configuration wrangler.toml ships for the first production launch (founder rulings
// 2026-10-15/16; runbook §9): every published page lives on cluehq.page — workspace addresses and
// customers' own domains, whose CNAMEs point at cluehq.page — and the Worker is routed on that
// zone ALONE, so cluehq.ai (the app) carries no page traffic at all. Read from the file itself, so
// the test checks what `wrangler deploy` will deploy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import worker from "./worker.js";

const toml = readFileSync(new URL("./wrangler.toml", import.meta.url), "utf-8");
const routeZones = [...toml.matchAll(/zone_name\s*=\s*"([^"]+)"/g)].map((match) => match[1]);
const varOf = (name) => toml.match(new RegExp(`^${name}\\s*=\\s*"([^"]*)"`, "m"))?.[1];

const SECRET = "edge-secret";
const shipped = {
  SYSTEM_SUFFIX: varOf("SYSTEM_SUFFIX"),
  LEGACY_SYSTEM_SUFFIXES: varOf("LEGACY_SYSTEM_SUFFIXES"),
  ORIGIN_HOST: varOf("ORIGIN_HOST"),
  EDITOR_SUFFIX: varOf("EDITOR_SUFFIX"),
  EDGE_SECRET: SECRET,
};

const realFetch = globalThis.fetch;
let calls;
beforeEach(() => {
  calls = [];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return new Response("from upstream");
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("the Worker is routed on cluehq.page alone, never on the app's zone", () => {
  assert.deepEqual(routeZones, ["cluehq.page"]);
  assert.equal(shipped.SYSTEM_SUFFIX, "cluehq.page");
  assert.equal(shipped.LEGACY_SYSTEM_SUFFIXES, "", "no cluehq.ai route, so nothing to redirect from");
  assert.equal(shipped.ORIGIN_HOST, "page-origin.cluehq.ai");
  assert.equal(shipped.EDITOR_SUFFIX, "edit.deeppresence.ai");
});

for (const [what, url, host] of [
  ["a workspace address", "https://garnerhealth.cluehq.page/syracuse?q=1", "garnerhealth.cluehq.page"],
  ["a customer's own domain (its CNAME points at cluehq.page)", "https://go.acme.com/syracuse", "go.acme.com"],
  ["the bare cluehq.page (the custom-hostname fallback origin)", "https://cluehq.page/", "cluehq.page"],
]) {
  test(`shipped: ${what} is forwarded to the page origin with the secret`, async () => {
    await worker.fetch(new Request(url, { headers: { "x-clue-edge-auth": "guessed" } }), shipped);
    assert.equal(calls.length, 1);
    const [sent] = calls[0];
    assert.equal(new URL(sent.url).host, shipped.ORIGIN_HOST);
    assert.equal(sent.headers.get("x-clue-public-host"), host);
    assert.equal(sent.headers.get("x-clue-edge-auth"), SECRET);
  });
}

test("shipped: a POST to a page is refused and never reaches the origin", async () => {
  const response = await worker.fetch(new Request("https://garnerhealth.cluehq.page/syracuse", { method: "POST" }), shipped);
  assert.equal(response.status, 405);
  assert.equal(calls.length, 0);
});
