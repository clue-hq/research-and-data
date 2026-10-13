import assert from "node:assert/strict";
import test from "node:test";
import {
  createFixtureWebPublishRepository,
  createHttpWebPublishRepository,
  WebPublishError,
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
  assert.equal(state.customUrl, null);
  assert.deepEqual(state.customPageUrls, {});
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
  assert.equal(result.customUrl, null);
  assert.deepEqual(result.customPageUrls, {});

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

test("the http repository publishes to the server's own page urls when it sends them", async () => {
  // F5 task 14: with a workspace handle and a configured host suffix, a site is
  // served from `https://{handle}.pages…/{slug}` — an origin the client cannot
  // derive from anything it holds. So `page_urls` from the server WINS over the
  // local site-root join, which would have answered the interim path.
  const fetchImpl: typeof fetch = async () =>
    jsonResponse(200, {
      doc_version: 1,
      page_urls: {
        "/": "https://acme.pages.cluehq.ai/launch",
        "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
      },
      previous_available: false,
      routes: ["/", "/pricing"],
      schema_version: 1,
      slug: "launch",
      url: "https://acme.pages.cluehq.ai/launch",
    });
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });

  const result = await repository.publish("doc_1", {
    slug: "launch",
    noindex: false,
  });
  assert.deepEqual(result.pageUrls, {
    "/": "https://acme.pages.cluehq.ai/launch",
    "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
  });
});

test("the http repository carries the custom hostname's addresses through a publish", async () => {
  const fetchImpl: typeof fetch = async () =>
    jsonResponse(200, {
      custom_origin: "https://go.acme.com",
      custom_page_urls: {
        "/": "https://go.acme.com/launch",
        "/pricing": "https://go.acme.com/launch/pricing",
      },
      custom_url: "https://go.acme.com/launch",
      page_urls: {
        "/": "https://acme.pages.cluehq.ai/launch",
        "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
      },
      public_origin: "https://acme.pages.cluehq.ai",
      routes: ["/", "/pricing"],
      slug: "launch",
      url: "https://acme.pages.cluehq.ai/launch",
    });
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });

  const result = await repository.publish("doc_1", {
    slug: "launch",
    noindex: false,
  });
  assert.equal(result.url, "https://acme.pages.cluehq.ai/launch");
  assert.equal(result.customUrl, "https://go.acme.com/launch");
  assert.deepEqual(result.customPageUrls, {
    "/": "https://go.acme.com/launch",
    "/pricing": "https://go.acme.com/launch/pricing",
  });
});

test("the http repository reports no custom addresses when the server sends none", async () => {
  const fetchImpl: typeof fetch = async () =>
    jsonResponse(200, {
      custom_page_urls: {},
      custom_url: null,
      routes: ["/"],
      slug: "launch",
      url: "https://acme.pages.cluehq.ai/launch",
    });
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl,
  });

  const result = await repository.publish("doc_1", {
    slug: "launch",
    noindex: false,
  });
  assert.equal(result.customUrl, null);
  assert.deepEqual(result.customPageUrls, {});
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

test("a refusal carries the server's status and code, so a caller need not parse prose", async () => {
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl: async () =>
      jsonResponse(409, { detail: { code: "document.agent_run_active", run_id: "run_42" } }),
  });
  await assert.rejects(
    repository.publish("doc_1", { slug: "acme", noindex: false }),
    (error: unknown) =>
      error instanceof WebPublishError &&
      error.status === 409 &&
      error.code === "document.agent_run_active",
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
