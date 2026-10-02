import assert from "node:assert/strict";
import test from "node:test";
import {
  createFixtureWebPublishRepository,
  downloadFilenameFrom,
} from "../../design-editor/data/web-publish.repository";
import {
  pageLinkRows,
  publishWithRepository,
  shareAddresses,
} from "./use-artifact-sharing-controller";

test("publishWithRepository publishes the slug and returns the server url", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(repo, "doc_1", {
    slug: "openai-cfo",
    noindex: false,
  });
  assert.equal(outcome.status, "published");
  assert.match(outcome.url, /\/openai-cfo$/);

  const state = await repo.state("doc_1");
  assert.equal(state.published, true);
  assert.equal(state.slug, "openai-cfo");
  assert.equal(state.url, outcome.url);
});

test("a failing publish reports draft with the message", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async () => {
        throw new Error("slug taken");
      },
    },
    "doc_1",
    { slug: "x", noindex: false },
  );
  assert.equal(outcome.status, "draft");
  assert.equal(outcome.message, "slug taken");
  assert.equal(outcome.url, "");
});

test("publishWithRepository forwards the noindex the caller asked for", async () => {
  const repo = createFixtureWebPublishRepository();
  const asked: Array<{ slug: string; noindex: boolean }> = [];
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async (documentId, input) => {
        asked.push(input);
        return repo.publish(documentId, input);
      },
    },
    "doc_1",
    { slug: "acme", noindex: true },
  );
  assert.equal(outcome.status, "published");
  assert.deepEqual(asked, [{ slug: "acme", noindex: true }]);
  assert.deepEqual(Object.keys(outcome.pageUrls), ["/"]);
});

test("a publish on a custom hostname shares the custom address and its pages", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async () => ({
        customPageUrls: {
          "/": "https://go.acme.com/launch",
          "/pricing": "https://go.acme.com/launch/pricing",
        },
        customUrl: "https://go.acme.com/launch",
        pageUrls: {
          "/": "https://acme.pages.cluehq.ai/launch",
          "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
        },
        slug: "launch",
        url: "https://acme.pages.cluehq.ai/launch",
      }),
    },
    "doc_1",
    { slug: "launch", noindex: false },
  );
  assert.equal(outcome.status, "published");
  assert.equal(outcome.url, "https://go.acme.com/launch");
  assert.deepEqual(outcome.pageUrls, {
    "/": "https://go.acme.com/launch",
    "/pricing": "https://go.acme.com/launch/pricing",
  });
});

test("shareAddresses keeps the Clue address when there is no custom hostname", () => {
  assert.deepEqual(
    shareAddresses({
      customPageUrls: {},
      customUrl: null,
      pageUrls: { "/": "https://acme.pages.cluehq.ai/launch" },
      url: "https://acme.pages.cluehq.ai/launch",
    }),
    {
      pageUrls: { "/": "https://acme.pages.cluehq.ai/launch" },
      url: "https://acme.pages.cluehq.ai/launch",
    },
  );
});

test("shareAddresses reads an unpublished state as no address at all", () => {
  assert.deepEqual(
    shareAddresses({ customPageUrls: {}, customUrl: null, pageUrls: {}, url: null }),
    { pageUrls: {}, url: "" },
  );
});

test("pageLinkRows puts Home first and then the routes alphabetically", () => {
  const rows = pageLinkRows({
    "/pricing": "https://acme.clue.site/launch/pricing",
    "/": "https://acme.clue.site/launch",
    "/about": "https://acme.clue.site/launch/about",
  });
  assert.deepEqual(rows, [
    { label: "Home", route: "/", url: "https://acme.clue.site/launch" },
    {
      label: "/about",
      route: "/about",
      url: "https://acme.clue.site/launch/about",
    },
    {
      label: "/pricing",
      route: "/pricing",
      url: "https://acme.clue.site/launch/pricing",
    },
  ]);
});

test("pageLinkRows yields the one row a single-page site has", () => {
  const rows = pageLinkRows({ "/": "https://acme.clue.site/launch" });
  assert.deepEqual(rows, [
    { label: "Home", route: "/", url: "https://acme.clue.site/launch" },
  ]);
});

test("downloadFilenameFrom reads the quoted filename the server sent", () => {
  assert.equal(
    downloadFilenameFrom(
      'attachment; filename="acme-launch-1a2b3c4d.zip"',
      "site.zip",
    ),
    "acme-launch-1a2b3c4d.zip",
  );
});

test("downloadFilenameFrom reads an unquoted filename too", () => {
  assert.equal(
    downloadFilenameFrom("attachment; filename=acme.zip", "site.zip"),
    "acme.zip",
  );
});

test("downloadFilenameFrom falls back when there is no usable name", () => {
  assert.equal(downloadFilenameFrom(null, "site.zip"), "site.zip");
  assert.equal(downloadFilenameFrom("attachment", "site.zip"), "site.zip");
  assert.equal(downloadFilenameFrom('attachment; filename=""', "site.zip"), "site.zip");
});

test("downloadFilenameFrom keeps only the file's own name", () => {
  assert.equal(
    downloadFilenameFrom('attachment; filename="../../etc/acme.zip"', "site.zip"),
    "acme.zip",
  );
});
