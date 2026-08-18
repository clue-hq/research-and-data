import assert from "node:assert/strict";
import test from "node:test";
import { brandContextFixture } from "./brand-context.fixture";
import {
  getBrandContextRepository,
  httpBrandContextRepository,
} from "./brand-context.repository";
import { HARVESTED_ASSET_RECORDS, HARVESTED_BRAND_KIT } from "./__fixtures__/harvest";

const KIT_ID = "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a";

function stubDesignApi(
  routes: Readonly<Record<string, { status?: number; body?: unknown }>>,
  requested: string[] = [],
) {
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const path = String(input);
    requested.push(path);
    const route = routes[path];
    if (!route) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(route.body ?? null), {
      status: route.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { fetchImpl, requested };
}

function assetRoutes(): Record<string, { body: unknown }> {
  return Object.fromEntries(
    Object.entries(HARVESTED_ASSET_RECORDS).map(([id, body]) => [
      `/assets/${id}`,
      { body },
    ]),
  );
}

test("the newest kit version by updated_at is the one the page reads", async () => {
  const requested: string[] = [];
  const { fetchImpl } = stubDesignApi(
    {
      "/brand-kits": {
        body: [
          {
            id: "kit_older",
            version: 3,
            name: "Older",
            updated_at: "2026-08-01T00:00:00+00:00",
          },
          {
            id: KIT_ID,
            version: 1,
            name: "Stripe",
            updated_at: "2026-08-18T12:43:49.842596+00:00",
          },
        ],
      },
      [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
      ...assetRoutes(),
    },
    requested,
  );

  const workspace = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.equal(workspace.id, KIT_ID);
  assert.equal(workspace.name, "Stripe");
  assert.ok(workspace.colorGroups.length > 0);
  assert.equal(workspace.assets.length, 15);
  assert.deepEqual(requested.slice(0, 2), ["/brand-kits", `/brand-kits/${KIT_ID}`]);
});

test("a workspace with no kit gets the designed empty states, never fixture data", async () => {
  const requested: string[] = [];
  const { fetchImpl } = stubDesignApi({ "/brand-kits": { body: [] } }, requested);

  const workspace = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.deepEqual(workspace.assets, []);
  assert.deepEqual(workspace.knowledgeFolders, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
  // Nothing beyond the list is fetched when there is nothing to fetch.
  assert.deepEqual(requested, ["/brand-kits"]);
});

test("a design-API refusal renders the empty states rather than failing the page", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { status: 503, body: { detail: "unavailable" } },
  });

  const workspace = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
});

test("an unreachable transport renders the empty states too", async () => {
  const workspace = await httpBrandContextRepository({
    designFetch: async () => {
      throw new Error("session could not be proven");
    },
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.deepEqual(workspace.typefaces, []);
});

test("one unreadable asset record degrades its own row, not the page", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id: KIT_ID, version: 1, name: "Stripe" }] },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    // No /assets/* routes at all: every registry read 404s.
  });

  const workspace = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.equal(workspace.assets.length, 15);
  assert.equal(workspace.assets[0].sizeLabel, "—");
  assert.match(workspace.assets[0].visual.kind, /image/);
});

test("without a configured transport the page still gets the dummy fixture", async () => {
  const configured = process.env.CLUE_API_BASE_URL;
  delete process.env.CLUE_API_BASE_URL;
  try {
    const workspace = await getBrandContextRepository(async () => {
      throw new Error("the fixture path must not open a transport");
    }).getWorkspace();
    assert.equal(workspace.id, brandContextFixture.id);
  } finally {
    if (configured !== undefined) process.env.CLUE_API_BASE_URL = configured;
  }
});

test("with a configured transport the page reads the real store", async () => {
  const configured = process.env.CLUE_API_BASE_URL;
  process.env.CLUE_API_BASE_URL = "http://127.0.0.1:8030";
  const { fetchImpl } = stubDesignApi({ "/brand-kits": { body: [] } });
  try {
    const workspace = await getBrandContextRepository(
      async () => fetchImpl,
    ).getWorkspace();
    assert.notEqual(workspace.id, brandContextFixture.id);
  } finally {
    if (configured === undefined) delete process.env.CLUE_API_BASE_URL;
    else process.env.CLUE_API_BASE_URL = configured;
  }
});
