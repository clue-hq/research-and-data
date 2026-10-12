import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import {
  SITE_FIXTURE_DOCUMENT_ID,
  SiteRepositoryError,
  fixtureSiteRepository,
  httpSiteRepository,
} from "./site.repository";

const SITE = {
  id: "doc-1",
  title: "Syracuse",
  theme: {},
  pages: { "/": { root: { props: { title: "Home" } }, content: [] } },
  shell: null,
  agent_sections: {},
} as SiteDocument;

function recorder(responses: Response[]) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request");
    return next;
  }) as typeof fetch;
  return { calls, fetchImpl };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("get reads GET /documents/{id} through the design BFF and requires a site", async () => {
  const { calls, fetchImpl } = recorder([
    json({ id: "doc-1", doc_kind: "site", title: "Syracuse", scene: SITE, current_version: 7, undo_stack: [{}, {}], redo_stack: [] }),
  ]);
  const loaded = await httpSiteRepository({ fetchImpl }).get("doc-1");
  assert.equal(calls[0].url, "/api/clue/design/documents/doc-1");
  assert.deepEqual(
    { title: loaded.title, version: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth },
    { title: "Syracuse", version: 7, undoDepth: 2, redoDepth: 0 },
  );
});

test("get refuses a document that is not a site", async () => {
  const { fetchImpl } = recorder([json({ id: "doc-1", doc_kind: "web", title: "W", scene: {}, current_version: 1 })]);
  await assert.rejects(httpSiteRepository({ fetchImpl }).get("doc-1"));
});

test("save PUTs the whole site with base_version and returns the new version", async () => {
  const { calls, fetchImpl } = recorder([json({ document: { id: "doc-1", current_version: 8, doc_kind: "site" } })]);
  const result = await httpSiteRepository({ fetchImpl }).save("doc-1", {
    site: SITE,
    baseVersion: 7,
    intent: "inspector: edit heading",
  });
  assert.equal(calls[0].url, "/api/clue/design/documents/doc-1/site");
  assert.equal(calls[0].init?.method, "PUT");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    site: SITE,
    base_version: 7,
    intent: "inspector: edit heading",
  });
  assert.equal(result.version, 8);
});

test("a 409 base-version refusal surfaces its code and the server's version", async () => {
  const { fetchImpl } = recorder([
    json({ detail: { code: "edits.base_version_mismatch", message: "moved on", current_version: 9 } }, 409),
  ]);
  await assert.rejects(
    httpSiteRepository({ fetchImpl }).save("doc-1", { site: SITE, baseVersion: 7 }),
    (error: unknown) =>
      error instanceof SiteRepositoryError &&
      error.code === "edits.base_version_mismatch" &&
      error.status === 409 &&
      error.currentVersion === 9,
  );
});

test("a 422 refusal carries the validator's errors", async () => {
  const { fetchImpl } = recorder([
    json({ detail: { code: "site.invalid", message: "invalid", errors: ["page.content.0(cta).heading: Too small"] } }, 422),
  ]);
  await assert.rejects(
    httpSiteRepository({ fetchImpl }).save("doc-1", { site: SITE, baseVersion: 7 }),
    (error: unknown) =>
      error instanceof SiteRepositoryError && error.errors[0] === "page.content.0(cta).heading: Too small",
  );
});

test("undo, redo, versions, restore, section links and brand use their routes", async () => {
  const { calls, fetchImpl } = recorder([
    json({ document: { id: "doc-1", current_version: 8 }, undone_batch_id: "b1" }),
    json({ document: { id: "doc-1", current_version: 9 }, redone_batch_id: "b1" }),
    json({ versions: [{ batch_id: "b2", version: 9, actor_kind: "human", intent: null, created_at: "2026-10-11T10:00:00Z" }] }),
    json({ document: { id: "doc-1", current_version: 10 } }),
    json({
      links: [
        {
          name: "AnalysisSteps",
          digest: "c".repeat(64),
          token: "tok_0123456789abcdef",
          expires_at: "2026-10-11T10:10:00Z",
          props_schema: { type: "object" },
        },
      ],
    }),
    json({ brand: { slug: "garner", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } }),
  ]);
  const repository = httpSiteRepository({ fetchImpl });
  assert.equal((await repository.undo("doc-1", 7)).version, 8);
  assert.equal((await repository.redo("doc-1", 8)).version, 9);
  assert.deepEqual(await repository.versions("doc-1", 20), [
    { batchId: "b2", version: 9, actorKind: "human", intent: null, createdAt: "2026-10-11T10:00:00Z" },
  ]);
  assert.equal((await repository.restore("doc-1", "b2", 9)).version, 10);
  assert.deepEqual((await repository.sectionLinks("doc-1"))[0].propsSchema, { type: "object" });
  assert.equal((await repository.getBrand("doc-1")).slug, "garner");
  const base = "/api/clue/design/documents/doc-1";
  assert.deepEqual(
    calls.map((call) => [call.init?.method ?? "GET", call.url]),
    [
      ["POST", `${base}/site/undo`],
      ["POST", `${base}/site/redo`],
      ["GET", `${base}/site/versions?limit=20`],
      ["POST", `${base}/site/versions/b2/restore`],
      ["POST", `${base}/site/section-links`],
      ["GET", `${base}/site/brand`],
    ],
  );
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { base_version: 7 });
});

test("the fixture enforces compare-and-swap and keeps an undo stack", async () => {
  const repository = fixtureSiteRepository();
  const loaded = await repository.get(SITE_FIXTURE_DOCUMENT_ID);
  const saved = await repository.save(SITE_FIXTURE_DOCUMENT_ID, { site: loaded.site, baseVersion: loaded.version });
  assert.equal(saved.version, loaded.version + 1);
  await assert.rejects(
    repository.save(SITE_FIXTURE_DOCUMENT_ID, { site: loaded.site, baseVersion: loaded.version }),
    (error: unknown) => error instanceof SiteRepositoryError && error.code === "edits.base_version_mismatch",
  );
  const undone = await repository.undo(SITE_FIXTURE_DOCUMENT_ID, saved.version);
  assert.equal(undone.version, saved.version + 1);
  await assert.rejects(
    repository.undo(SITE_FIXTURE_DOCUMENT_ID, undone.version),
    (error: unknown) => error instanceof SiteRepositoryError && error.code === "undo.empty",
  );
});
