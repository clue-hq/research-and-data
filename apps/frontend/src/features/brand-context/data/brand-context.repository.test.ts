import assert from "node:assert/strict";
import test from "node:test";
import { brandContextFixture } from "./brand-context.fixture";
import {
  getBrandContextRepository,
  httpBrandContextRepository,
} from "./brand-context.repository";
import { brandKitAssetIds } from "../model/brand-context-mapping";
import { BrandKitDetailSchema } from "../model/brand-kit";
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

  const { kit, workspace } = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.equal(workspace.id, KIT_ID);
  assert.equal(workspace.name, "Stripe");
  assert.ok(workspace.colorGroups.length > 0);
  assert.equal(workspace.assets.length, 15);
  assert.deepEqual(requested.slice(0, 2), ["/brand-kits", `/brand-kits/${KIT_ID}`]);
  // The store's facts about that kit ride along, for the header's actions.
  assert.deepEqual(kit, {
    approvalStatus: "draft",
    id: KIT_ID,
    sourceUrl: "https://stripe.com",
    version: 1,
  });
});

test("a workspace with no kit gets the designed empty states, never fixture data", async () => {
  const requested: string[] = [];
  const { fetchImpl } = stubDesignApi({ "/brand-kits": { body: [] } }, requested);

  const { kit, workspace } = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.deepEqual(workspace.assets, []);
  assert.deepEqual(workspace.knowledgeFolders, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
  assert.equal(kit, null);
  // Nothing beyond the list is fetched when there is nothing to fetch.
  assert.deepEqual(requested, ["/brand-kits"]);
});

test("a design-API refusal renders the empty states rather than failing the page", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { status: 503, body: { detail: "unavailable" } },
  });

  const { kit, workspace } = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
  // No kit meta from a refusal: the actions must not claim a kit we could not read.
  assert.equal(kit, null);
});

test("an unreachable transport renders the empty states too", async () => {
  const { kit, workspace } = await httpBrandContextRepository({
    designFetch: async () => {
      throw new Error("session could not be proven");
    },
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.deepEqual(workspace.typefaces, []);
  assert.equal(kit, null);
});

test("one unreadable asset record degrades its own row, not the page", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id: KIT_ID, version: 1, name: "Stripe" }] },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    // No /assets/* routes at all: every registry read 404s.
  });

  const { kit, workspace } = await httpBrandContextRepository({
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.equal(workspace.assets.length, 15);
  assert.equal(workspace.assets[0].sizeLabel, "—");
  assert.match(workspace.assets[0].visual.kind, /image/);
  assert.equal(kit?.id, KIT_ID);
});

test("without a configured transport the page still gets the dummy fixture", async () => {
  const configured = process.env.CLUE_API_BASE_URL;
  delete process.env.CLUE_API_BASE_URL;
  try {
    const { kit, workspace } = await getBrandContextRepository(async () => {
      throw new Error("the fixture path must not open a transport");
    }).getWorkspace();
    assert.equal(workspace.id, brandContextFixture.id);
    // The dummy is a design, not a stored kit: no identity to approve or re-extract.
    assert.equal(kit, null);
  } finally {
    if (configured !== undefined) process.env.CLUE_API_BASE_URL = configured;
  }
});

test("with a configured transport the page reads the real store", async () => {
  const configured = process.env.CLUE_API_BASE_URL;
  process.env.CLUE_API_BASE_URL = "http://127.0.0.1:8030";
  const { fetchImpl } = stubDesignApi({ "/brand-kits": { body: [] } });
  try {
    const { workspace } = await getBrandContextRepository(
      async () => fetchImpl,
    ).getWorkspace();
    assert.notEqual(workspace.id, brandContextFixture.id);
  } finally {
    if (configured === undefined) delete process.env.CLUE_API_BASE_URL;
    else process.env.CLUE_API_BASE_URL = configured;
  }
});

/**
 * `GET /assets` per image kind — the workspace registry read the Assets section
 * unions with the kit. The stub matches on the EXACT path, so these keys are
 * the exact query strings the repository asks for.
 */
// The harvest is exported as `unknown` on purpose — a raw wire capture is
// parsed, never trusted — so these two tests read it through its own schema.
const HARVESTED_KIT = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);

function registryRoutes(records: unknown[]): Record<string, { body: unknown }> {
  const page = (kind: string) => ({
    body: {
      assets: records.filter((r) => (r as { kind: string }).kind === kind),
      count: 0,
      limit: 200,
      offset: 0,
    },
  });
  return {
    "/assets?kind=raster_image&include_archived=false&limit=200&offset=0": page("raster_image"),
    "/assets?kind=vector&include_archived=false&limit=200&offset=0": page("vector"),
    "/assets?kind=logo&include_archived=false&limit=200&offset=0": page("logo"),
  };
}

test("the Assets section lists the kit's items plus workspace uploads, deduped, categorized", async () => {
  const upload = {
    id: "asset_upl_1",
    kind: "raster_image",
    label: "team.jpg",
    status: "ready",
    source: { kind: "uploaded", filename: "team.jpg", uploaded_by: null },
    media: { mime_type: "image/jpeg", byte_length: 1234, filename: "team.jpg" },
    provenance: { created_at: "2026-09-01T10:00:00Z" },
  };
  const generated = {
    id: "asset_gen_1",
    kind: "raster_image",
    label: "generated hero",
    status: "ready",
    source: { kind: "generated", request_id: null, model: "x" },
  };
  const kitLogoId = brandKitAssetIds(HARVESTED_KIT)[0];
  assert.ok(kitLogoId, "the harvested kit must carry at least one asset");
  const kitDup = {
    id: kitLogoId,
    kind: "logo",
    label: "dup of kit logo",
    status: "ready",
    source: { kind: "uploaded", filename: null, uploaded_by: null },
  };
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [HARVESTED_KIT.brand_kit] },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    ...assetRoutes(),
    ...registryRoutes([upload, generated, kitDup]),
  });

  const { workspace } = await httpBrandContextRepository({
    designFetch: () => fetchImpl,
  }).getWorkspace();

  const byId = new Map(workspace.assets.map((a) => [a.id, a]));
  assert.equal(byId.get("asset_upl_1")?.category, "upload");
  assert.equal(byId.get("asset_upl_1")?.origin, "registry");
  assert.equal(byId.get("asset_upl_1")?.name, "team.jpg");
  assert.equal(byId.get("asset_gen_1")?.category, "ai-generated");
  // The kit wins the dedupe: one row, still badged as the brand's own.
  assert.equal(byId.get(kitLogoId)?.origin, "kit");
  assert.equal(workspace.assets.filter((a) => a.id === kitLogoId).length, 1);
  assert.ok(
    workspace.assets.findIndex((a) => a.origin === "kit") <
      workspace.assets.findIndex((a) => a.id === "asset_upl_1"),
  );
});

test("a failed registry read leaves the kit's assets intact", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [HARVESTED_KIT.brand_kit] },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
    ...assetRoutes(),
  });

  const { workspace } = await httpBrandContextRepository({
    designFetch: () => fetchImpl,
  }).getWorkspace();

  assert.ok(workspace.assets.length > 0);
  assert.ok(workspace.assets.every((a) => a.origin === "kit"));
});
