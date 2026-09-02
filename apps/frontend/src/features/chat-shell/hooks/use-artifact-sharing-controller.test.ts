import assert from "node:assert/strict";
import test from "node:test";
import { createFixtureWebPublishRepository } from "../../design-editor/data/web-publish.repository";
import { publishWithRepository } from "./use-artifact-sharing-controller";

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
