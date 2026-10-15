import assert from "node:assert/strict";
import test from "node:test";
import { brandContextFixture } from "./brand-context.fixture";
import {
  getBrandContextRepository,
  httpBrandContextRepository,
} from "./brand-context.repository";
import { brandKitAssetIds } from "../model/brand-context-mapping";
import { BrandKitDetailSchema } from "../model/brand-kit";
import { HARVESTED_ASSET_RECORDS, HARVESTED_BRAND_KIT, MEASURED_BRAND_KIT } from "./__fixtures__/harvest";

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

/** A platform transport that serves nothing: the four folders are then honestly absent. */
const noPlatformRead = (async () => {
  throw new Error("the platform read is not part of this test");
}) as unknown as typeof fetch;

/** A minimal, valid `BrandBrief@1` — the kit's Design.md comes from this. */
const BRIEF_FIXTURE = {
  background_rhythm: { bands: [], confidence: "high" },
  characterization: {
    confidence: "high",
    support: "Violet CTAs on a white canvas.",
    words: ["expansive", "polished"],
  },
  chromatic_moment: {
    confidence: "high",
    element: "the primary CTA",
    quiet: false,
    token: "surface.brand",
  },
  component_recipes: [],
  constraints: [],
  diagnostics: [],
  imagery_posture: { absences: [], confidence: "low", slots: [] },
  palette_application: [],
  schema_version: 1,
  signature_compositions: [],
  typographic_posture: { confidence: "low", signature_moves: [], tokens: [] },
};

function briefedKit() {
  const kit = HARVESTED_BRAND_KIT as {
    brand_kit: Record<string, unknown>;
    brand_kit_json: Record<string, unknown>;
  };
  return {
    ...HARVESTED_BRAND_KIT,
    brand_kit_json: { ...kit.brand_kit_json, brief: BRIEF_FIXTURE },
  };
}

const KNOWLEDGE_DOCUMENT_FIELDS = {
  icpKey: null,
  kind: "company-overview",
  productId: null,
  status: "ready",
  updatedAt: "2026-09-08T00:00:00Z",
  version: 1,
};

const KNOWLEDGE_TREE = {
  brandId: "brd_1",
  folders: [
    {
      documents: [
        { ...KNOWLEDGE_DOCUMENT_FIELDS, id: "doc-1", path: "company/overview.md", title: "Overview" },
      ],
      key: "company",
      label: "Company",
    },
    {
      documents: [
        { ...KNOWLEDGE_DOCUMENT_FIELDS, id: "doc-2", path: "product/aura.md", title: "Aura" },
      ],
      key: "product",
      label: "Product",
    },
    { documents: [], key: "audience", label: "Audience" },
    { documents: [], key: "proof", label: "Proof" },
  ],
};

function knowledgeRoutes(): Record<string, { body: unknown }> {
  const detail = (id: string, markdown: string) => ({
    ...KNOWLEDGE_DOCUMENT_FIELDS,
    frontMatter: {},
    id,
    markdown,
    path: id === "doc-1" ? "company/overview.md" : "product/aura.md",
    sources: [],
    title: id === "doc-1" ? "Overview" : "Aura",
  });
  return {
    "/frontend/v1/brand-context/knowledge": { body: KNOWLEDGE_TREE },
    "/frontend/v1/brand-context/knowledge/documents/doc-1": {
      body: detail("doc-1", "# Overview\n"),
    },
    "/frontend/v1/brand-context/knowledge/documents/doc-2": {
      body: detail("doc-2", "# Aura\n"),
    },
  };
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
    clueFetch: () => noPlatformRead,
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
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.deepEqual(workspace.assets, []);
  assert.deepEqual(workspace.knowledgeFolders, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
  assert.equal(kit, null);
  // The workspace library is independent of kit existence.
  assert.equal(requested.filter(path => path.startsWith("/assets?")).length, 3);
});

test("a no-kit library reads past page one and batches metadata for older assets", async () => {
  const records = Array.from({length: 251}, (_, index) => ({id: `asset_${index}`,
    kind: "raster_image", status: "ready", source: {kind: "uploaded"}, label: `Image ${index}`}));
  const pages: number[] = [], batches: number[] = [];
  const fetchImpl: typeof fetch = async input => {
    const url = new URL(String(input), "https://design.example");
    if (url.pathname === "/brand-kits") return Response.json([]);
    if (url.pathname === "/assets") {
      if (url.searchParams.get("kind") !== "raster_image") return Response.json({assets: []});
      const offset = Number(url.searchParams.get("offset")); pages.push(offset);
      return Response.json({assets: records.slice(offset, offset + 200)});
    }
    if (url.pathname === "/assets/descriptions") {
      const ids = url.searchParams.get("asset_ids")!.split(","); batches.push(ids.length);
      return Response.json({descriptions: Object.fromEntries(ids.map(id => [id, {asset_id: id,
        title: "Historical image", creative_type: "photo", usage_roles: ["card_image"], status: "ready"}]))});
    }
    throw new Error(`Unexpected per-asset read: ${url.pathname}`);
  };
  const view = await httpBrandContextRepository({designFetch: () => fetchImpl, clueFetch: () => noPlatformRead}).getWorkspace();
  assert.equal(view.kit, null);
  assert.deepEqual(pages, [0, 200]); assert.deepEqual(batches, [100, 100, 51]);
  assert.equal(view.workspace.assets.length, 251);
  const older = view.workspace.assets.find(asset => asset.id === "asset_250")!;
  assert.equal(older.name, "Historical image");
  assert.deepEqual(older.context?.usage_roles, ["card_image"]);
  assert.deepEqual(older.sources, ["user_upload"]);
});

test("a design-API refusal renders the empty states rather than failing the page", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { status: 503, body: { detail: "unavailable" } },
  });

  const { kit, workspace } = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();

  assert.deepEqual(workspace.colorGroups, []);
  assert.notEqual(workspace.id, brandContextFixture.id);
  // No kit meta from a refusal: the actions must not claim a kit we could not read.
  assert.equal(kit, null);
});

test("an unreachable transport renders the empty states too", async () => {
  const { kit, workspace } = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
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
    clueFetch: () => noPlatformRead,
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
    const { kit, workspace } = await getBrandContextRepository(
      async () => {
        throw new Error("the fixture path must not open a transport");
      },
      () => noPlatformRead,
    ).getWorkspace();
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
      () => noPlatformRead,
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

test("the platform's Knowledge folders list before the kit's Design folder", async () => {
  const { fetchImpl: designImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id: KIT_ID, name: "Stripe", version: 1 }] },
    [`/brand-kits/${KIT_ID}`]: { body: briefedKit() },
    ...assetRoutes(),
  });
  const { fetchImpl: clueImpl } = stubDesignApi(knowledgeRoutes());

  const { workspace } = await httpBrandContextRepository({
    clueFetch: () => clueImpl,
    designFetch: async () => designImpl,
  }).getWorkspace();

  assert.deepEqual(
    workspace.knowledgeFolders.map((folder) => folder.id),
    ["company", "product", "audience", "proof", "design"],
  );
  // Each platform document carries the body its own detail read served.
  assert.equal(workspace.knowledgeFolders[0].documents[0].name, "Overview");
  assert.equal(workspace.knowledgeFolders[0].documents[0].body, "# Overview\n");
  assert.equal(workspace.knowledgeFolders[1].documents[0].body, "# Aura\n");
  // The kit's Design.md is unchanged: still the brief render, still last.
  const design = workspace.knowledgeFolders[4];
  assert.equal(design.label, "Design");
  assert.equal(design.documents[0].path, "design/Design.md");
  assert.match(design.documents[0].body, /## Characterization/);
});

test("a refused platform read leaves the four folders out; the kit's Design stays", async () => {
  const { fetchImpl: designImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id: KIT_ID, name: "Stripe", version: 1 }] },
    [`/brand-kits/${KIT_ID}`]: { body: briefedKit() },
    ...assetRoutes(),
  });

  const { workspace } = await httpBrandContextRepository({
    clueFetch: () => {
      throw new Error("the platform session could not be proven");
    },
    designFetch: async () => designImpl,
  }).getWorkspace();

  assert.deepEqual(
    workspace.knowledgeFolders.map((folder) => folder.id),
    ["design"],
  );
});

test("the onboarding documents list before any kit is ingested", async () => {
  // The platform writes them during onboarding; a workspace with no brand kit at
  // all must still show them, not the section's empty state.
  const { fetchImpl: designImpl } = stubDesignApi({ "/brand-kits": { body: [] } });
  const { fetchImpl: clueImpl } = stubDesignApi(knowledgeRoutes());

  const { kit, workspace } = await httpBrandContextRepository({
    clueFetch: () => clueImpl,
    designFetch: async () => designImpl,
  }).getWorkspace();

  assert.deepEqual(
    workspace.knowledgeFolders.map((folder) => folder.id),
    ["company", "product", "audience", "proof"],
  );
  assert.deepEqual(workspace.colorGroups, []);
  assert.equal(kit, null);
});

test("a design-store outage still lists the onboarding documents", async () => {
  // The two stores are independent: losing the kit must not also hide the
  // documents onboarding already wrote.
  const { fetchImpl: clueImpl } = stubDesignApi(knowledgeRoutes());

  const { kit, workspace } = await httpBrandContextRepository({
    clueFetch: () => clueImpl,
    designFetch: async () => {
      throw new Error("the design session could not be proven");
    },
  }).getWorkspace();

  assert.deepEqual(
    workspace.knowledgeFolders.map((folder) => folder.id),
    ["company", "product", "audience", "proof"],
  );
  assert.deepEqual(workspace.colorGroups, []);
  assert.equal(kit, null);
});

function batchRecordsRoute(): Record<string, { body: unknown }> {
  const ids = [...new Set(brandKitAssetIds(BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT)))];
  const assets = Object.fromEntries(
    ids.filter(id => id in HARVESTED_ASSET_RECORDS).map(id => [id, HARVESTED_ASSET_RECORDS[id]]),
  );
  return {
    [`/assets/records?asset_ids=${ids.map(encodeURIComponent).join(",")}`]: {
      body: { schema_version: 1, assets },
    },
  };
}

test("kit asset records arrive in ONE batch read, not one request per asset", async () => {
  const requested: string[] = [];
  const { fetchImpl } = stubDesignApi(
    {
      "/brand-kits": { body: [{ id: KIT_ID, version: 1, name: "Stripe" }] },
      [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
      ...batchRecordsRoute(),
    },
    requested,
  );
  const { workspace } = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();
  assert.equal(requested.filter(path => path.startsWith("/assets/records?")).length, 1);
  assert.equal(requested.filter(path => /^\/assets\/[^/?]+$/.test(path)).length, 0);
  assert.ok(workspace.assets.some(asset => asset.sizeLabel !== "—"));
});

test("a design API without the batch route still gets each record read", async () => {
  const requested: string[] = [];
  const { fetchImpl } = stubDesignApi(
    {
      "/brand-kits": { body: [{ id: KIT_ID, version: 1, name: "Stripe" }] },
      [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
      ...assetRoutes(),
    },
    requested,
  );
  const { workspace } = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();
  assert.ok(requested.some(path => /^\/assets\/[^/?]+$/.test(path)));
  assert.ok(workspace.assets.some(asset => asset.sizeLabel !== "—"));
});

test("the three registry asset kinds are listed concurrently", async () => {
  let inFlight = 0;
  let peak = 0;
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/brand-kits") return Response.json([]);
    if (path.startsWith("/assets?")) {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise(resolve => setTimeout(resolve, 20));
      inFlight -= 1;
      return Response.json({ assets: [] });
    }
    return Response.json({ descriptions: {} });
  }) as typeof fetch;
  await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();
  assert.equal(peak, 3);
});

test("a measured kit brings its measured view, and its minted colours leave Semantic roles", async () => {
  const detail = MEASURED_BRAND_KIT as { brand_kit: { id: string; version: number; name: string } };
  const { id, version, name } = detail.brand_kit;
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id, version, name, approval_status: "draft", created_at: null, updated_at: null }] },
    [`/brand-kits/${id}`]: { body: MEASURED_BRAND_KIT },
  });
  const view = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getWorkspace();
  assert.ok(view.measured);
  assert.equal(view.measured.colorGroups[0].label, "Section backgrounds");
  const semantic = view.workspace.colorGroups.find((group) => group.id === "semantic")!;
  assert.ok(!semantic.swatches.some((swatch) => swatch.id === "surface.band.014036"));
  assert.ok(semantic.swatches.some((swatch) => swatch.id === "surface.brand"));
  // The page streams the kit through getKitView (2026-10-15); it carries the measured view too.
  const streamed = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => fetchImpl,
  }).getKitView();
  assert.equal(streamed.measured?.colorGroups[0].label, "Section backgrounds");
});

test("a kit made before measurement, and a failed read, bring no measured view", async () => {
  const { fetchImpl } = stubDesignApi({
    "/brand-kits": { body: [{ id: KIT_ID, version: 1, name: "Stripe", approval_status: "draft" }] },
    [`/brand-kits/${KIT_ID}`]: { body: HARVESTED_BRAND_KIT },
  });
  const old = await httpBrandContextRepository({ clueFetch: () => noPlatformRead, designFetch: async () => fetchImpl }).getWorkspace();
  assert.equal(old.measured, null);
  const refused = await httpBrandContextRepository({
    clueFetch: () => noPlatformRead,
    designFetch: async () => stubDesignApi({ "/brand-kits": { status: 500 } }).fetchImpl,
  }).getWorkspace();
  assert.equal(refused.measured, null);
});

test("the documents and the kit are read separately, and neither refusal costs the other", async () => {
  // 2026-10-15: the page shows the documents first and streams the slower kit in after.
  const knowledge: typeof fetch = async (input) => {
    const path = String(input);
    if (path.endsWith("/knowledge")) {
      return Response.json({ brandId: "brd", folders: [{ key: "company", label: "Company", documents: [
        { id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", status: "ready", updatedAt: "2026-10-15T00:00:00Z", version: 1, productId: null, icpKey: null },
      ] }] });
    }
    return Response.json({ id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", status: "ready", updatedAt: "2026-10-15T00:00:00Z", version: 1, productId: null, icpKey: null, markdown: "# Overview", frontMatter: {}, sources: [] });
  };
  const designDown: typeof fetch = async () => new Response(null, { status: 503 });
  const repository = httpBrandContextRepository({ clueFetch: () => knowledge, designFetch: () => designDown });

  const folders = await repository.getKnowledgeFolders();
  assert.deepEqual(folders.map((folder) => folder.documents.map((document) => document.path)), [["company/overview.md"]]);
  const kitView = await repository.getKitView();
  assert.equal(kitView.kit, null);
  assert.deepEqual(kitView.workspace.knowledgeFolders, []);

  const platformDown = httpBrandContextRepository({ clueFetch: () => noPlatformRead, designFetch: () => designDown });
  assert.deepEqual(await platformDown.getKnowledgeFolders(), []);
});
