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
  // Nothing beyond the list is fetched when there is nothing to fetch.
  assert.deepEqual(requested, ["/brand-kits"]);
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
