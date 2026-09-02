import assert from "node:assert/strict";
import test from "node:test";
import {
  createFixtureWebPublishRepository,
  createHttpWebPublishRepository,
} from "./web-publish.repository";

function jsonResponse(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "content-type": "application/json" },
    status,
  });
}

test("the fixture repository starts unpublished", async () => {
  const repository = createFixtureWebPublishRepository();
  const state = await repository.state("doc_1");
  assert.equal(state.published, false);
  assert.equal(state.slug, null);
  assert.equal(state.url, null);
  assert.deepEqual(state.pageUrls, {});
});

test("the fixture repository records the published slug and serves its url", async () => {
  const repository = createFixtureWebPublishRepository();
  const result = await repository.publish("doc_1", {
    slug: "acme",
    noindex: true,
  });
  assert.equal(result.slug, "acme");
  assert.equal(result.url, "https://fixture.pages.test/acme");
  assert.deepEqual(result.pageUrls, { "/": "https://fixture.pages.test/acme" });

  const state = await repository.state("doc_1");
  assert.equal(state.published, true);
  assert.equal(state.status, "active");
  assert.equal(state.url, "https://fixture.pages.test/acme");

  // A second document has its own publish; the fixture is per-document.
  assert.equal((await repository.state("doc_2")).published, false);
});

test("the fixture repository takes a site offline", async () => {
  const repository = createFixtureWebPublishRepository();
  await repository.publish("doc_1", { slug: "acme", noindex: false });
  await repository.unpublish("acme");
  const state = await repository.state("doc_1");
  assert.equal(state.published, false);
});

test("the http repository posts the slug and the noindex the caller asked for", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ init, url: String(input) });
    return jsonResponse(200, {
      doc_version: 4,
      previous_available: false,
      routes: ["/", "/pricing"],
      schema_version: 1,
      slug: "acme",
      url: "http://localhost:8002/w/ws_1/p/acme",
    });
  };
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });

  const result = await repository.publish("doc_1", {
    slug: "acme",
    noindex: true,
  });

  assert.equal(calls[0].url, "http://localhost:8002/documents/doc_1/web/publish");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    noindex: true,
    slug: "acme",
  });
  assert.equal(result.url, "http://localhost:8002/w/ws_1/p/acme");
  // Every route the publish put on the air, addressed off the server's own
  // site root — never a host or path the client invented.
  assert.deepEqual(result.pageUrls, {
    "/": "http://localhost:8002/w/ws_1/p/acme",
    "/pricing": "http://localhost:8002/w/ws_1/p/acme/pricing",
  });
});

test("the http repository reads the server's absolute page urls", async () => {
  const fetchImpl: typeof fetch = async () =>
    jsonResponse(200, {
      doc_version: 4,
      page_urls: {
        "/": "http://localhost:8002/w/ws_1/p/acme",
        "/pricing": "http://localhost:8002/w/ws_1/p/acme/pricing",
      },
      pages: [
        { html_digest: "aaa", page_id: "page_home", route: "/" },
        { html_digest: "bbb", page_id: "page_pricing", route: "/pricing" },
      ],
      previous_available: false,
      published: true,
      slug: "acme",
      status: "active",
      updated_at: "2026-09-02T00:00:00Z",
      url: "http://localhost:8002/w/ws_1/p/acme",
    });
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });

  const state = await repository.state("doc_1");
  assert.equal(state.published, true);
  assert.equal(state.status, "active");
  assert.equal(state.url, "http://localhost:8002/w/ws_1/p/acme");
  assert.equal(state.pages.length, 2);
  assert.equal(state.pages[1].route, "/pricing");
  assert.equal(
    state.pageUrls["/pricing"],
    "http://localhost:8002/w/ws_1/p/acme/pricing",
  );
});

test("the http repository surfaces the server's refusal message", async () => {
  const fetchImpl: typeof fetch = async () =>
    jsonResponse(409, { detail: { message: "Slug already in use." } });
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });
  await assert.rejects(
    repository.publish("doc_1", { slug: "acme", noindex: false }),
    /Slug already in use\./,
  );
});

test("the http repository deletes the slug on unpublish", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ init, url: String(input) });
    return jsonResponse(200, { slug: "acme", status: "unpublished" });
  };
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });
  await repository.unpublish("acme");
  assert.equal(calls[0].url, "http://localhost:8002/web/publishes/acme");
  assert.equal(calls[0].init?.method, "DELETE");
});
