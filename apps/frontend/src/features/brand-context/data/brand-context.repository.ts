import { httpAssetRepository, fixtureAssetRepository, type AssetRepository } from "./asset.repository";
import {
  BrandContextWorkspaceSchema,
  type BrandContextWorkspace,
  type BrandKnowledgeFolder,
} from "../model/brand-context";
import {
  brandKitAssetIds,
  emptyBrandContextWorkspace,
  toBrandContextWorkspace,
  toRegistryAssets,
} from "../model/brand-context-mapping";
import {
  BrandKitDetailSchema,
  BrandKitSummaryListSchema,
  DesignAssetListRecordSchema,
  DesignAssetRecordSchema,
  type BrandKitSummary,
  type DesignAssetListRecord,
  type DesignAssetRecord,
} from "../model/brand-kit";
import {
  toBrandKitMeta,
  type BrandKitMeta,
} from "../model/brand-kit-actions";
import { brandContextFixture } from "./brand-context.fixture";
import { readBrandKnowledgeFolders } from "./brand-knowledge.repository";

/**
 * What one render of the Brand-context page reads.
 *
 * `workspace` is the DESIGNED page's shape (frozen — `BrandContextWorkspaceSchema`); `kit` is
 * the store's facts about the kit behind it (identity, version, approval state, ingested
 * source), which slice 4's header actions need and the design has no slot for. `kit` is `null`
 * whenever `workspace` is an honest empty — no kit, a refusal, an unprovable session, or the
 * unconfigured fixture path.
 */
export interface BrandContextView {
  workspace: BrandContextWorkspace;
  kit: BrandKitMeta | null;
}

export interface BrandContextRepository extends AssetRepository {
  getWorkspace(): Promise<BrandContextView>;
}

/**
 * Slice 1: the Brand-context read seam over the REAL design-subsystem store.
 *
 * `designFetch` yields an authenticated, origin-relative fetch against the
 * design API. Two arrangements satisfy it and both prove the session on the
 * server: the browser-facing BFF (`/api/clue/design/...`), and — for a Server
 * Component, which cannot call its own origin-relative route — the
 * `fetchAuthenticatedDesignBackend` primitive, which resolves the workspace
 * from the session and stamps `X-Workspace-Id` itself. A browser-supplied
 * workspace is never trusted on either path.
 *
 * `clueFetch` is its platform-backend sibling, over the same proven session. The
 * Knowledge section is served by BOTH stores: the onboarding documents (Company,
 * Product, Audience, Proof) come from the platform read, the Design brief from the
 * brand kit. They are independent — the platform's documents exist before any kit
 * is ingested, and a kit's brief renders whether or not the platform read answers.
 *
 * `getWorkspace` NEVER rejects. A workspace with no kit, a design-API refusal
 * and an unprovable session all render the same designed empty states — the
 * page is a review surface, and a 500 (or worse, the dummy's fixture content)
 * would be a lie about the client's brand.
 */
export function httpBrandContextRepository({
  clueFetch,
  designFetch,
}: {
  clueFetch: () => Promise<typeof fetch> | typeof fetch;
  designFetch: () => Promise<typeof fetch> | typeof fetch;
}): BrandContextRepository {
  return {
    ...httpAssetRepository(designFetch),
    async getWorkspace() {
      // Started first and awaited last, so the two backends are read concurrently.
      // It never rejects, which is what lets the catch below still serve the
      // onboarding documents when it is the DESIGN store that is unavailable.
      const platformFolders = readPlatformKnowledgeFolders(clueFetch);
      try {
        return await readWorkspace(await designFetch(), platformFolders);
      } catch (error) {
        console.warn(
          "[brand-context] serving the empty workspace; the brand-kit read failed:",
          error,
        );
        return {
          kit: null,
          workspace: withPlatformFolders(
            emptyBrandContextWorkspace(),
            await platformFolders,
          ),
        };
      }
    },
  };
}

/** Kit asset records: one batch read, or (older design API) one read per asset. */
async function readAssetRecords(
  read: (path: string) => Promise<unknown>,
  assetIds: readonly string[],
): Promise<Map<string, DesignAssetRecord>> {
  const records = new Map<string, DesignAssetRecord>();
  if (assetIds.length === 0) return records;
  try {
    const batch = (await read(
      `/assets/records?asset_ids=${assetIds.map(encodeURIComponent).join(",")}`,
    )) as { assets?: Record<string, unknown> };
    for (const [assetId, body] of Object.entries(batch.assets ?? {})) {
      const parsed = DesignAssetRecordSchema.safeParse(body);
      if (parsed.success) records.set(assetId, parsed.data);
    }
    return records;
  } catch {
    // No batch route on this design API yet: fall back to one read per asset.
  }
  await Promise.all(
    assetIds.map(async (assetId) => {
      try {
        records.set(
          assetId,
          DesignAssetRecordSchema.parse(await read(`/assets/${encodeURIComponent(assetId)}`)),
        );
      } catch {
        // An asset the registry cannot describe still renders its bytes.
      }
    }),
  );
  return records;
}

async function readWorkspace(
  designFetch: typeof fetch,
  platformFolders: Promise<BrandKnowledgeFolder[]>,
): Promise<BrandContextView> {
  const read = async (path: string): Promise<unknown> => {
    const response = await designFetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`design API ${path} responded ${response.status}`);
    }
    return response.json();
  };

  const kits = BrandKitSummaryListSchema.parse(await read("/brand-kits"));
  const selected = selectBrandKit(kits);
  const kit = selected ? BrandKitDetailSchema.parse(
    await read(`/brand-kits/${encodeURIComponent(selected.id)}`),
  ) : null;

  // The kit names its assets by id only; their filename, media type, byte
  // length and geometry live in the asset registry. ONE batch read (the page
  // used to send one request per asset — 27 per load, each queueing on the
  // design API, production 2026-10-03). A design API without the batch route
  // gets the old one-read-per-asset path, so a deploy-order skew never blanks
  // the page; any refusal leaves that row with honest unknowns.
  const assetIds = kit ? [...new Set(brandKitAssetIds(kit))] : [];
  const assetRecords = await readAssetRecords(read, assetIds);

  // The Assets section is the kit UNION the workspace registry: a picture
  // uploaded in the editor belongs to this brand too. One page per image kind
  // is enough for a review surface (the editor's own library pages further,
  // because a picker must be complete); a refusal costs the uploads, never the
  // kit's own assets, so the page never blanks over a registry hiccup. The
  // three kinds are listed concurrently; each kind keeps its own paging order.
  const byKind = await Promise.all(
    ["raster_image", "vector", "logo"].map(async (kind) => {
      const records: DesignAssetListRecord[] = [];
      try {
        for (let offset = 0; ; offset += 200) {
          const page = (await read(`/assets?kind=${kind}&include_archived=false&limit=200&offset=${offset}`)) as {assets?: unknown[]};
          for (const raw of page.assets ?? []) {
            const parsed = DesignAssetListRecordSchema.safeParse(raw);
            if (parsed.success) records.push(parsed.data);
          }
          if ((page.assets?.length ?? 0) < 200) break;
        }
      } catch (error) {
        console.warn(
          `[brand-context] registry read for ${kind} failed; kit assets only:`,
          error,
        );
      }
      return records;
    }),
  );
  const registryRecords: DesignAssetListRecord[] = byKind.flat();

  const workspace = kit ? toBrandContextWorkspace(kit, {assetRecords, registryRecords})
    : {...emptyBrandContextWorkspace(), assets: toRegistryAssets(registryRecords, new Set())};
  try {
    const metadata = await httpAssetRepository(() => designFetch).readMetadata(workspace.assets.map(asset => asset.id));
    workspace.assets = workspace.assets.map(asset => {
      const context = metadata[asset.id];
      return context ? {...asset, context, name: context.title ?? asset.name,
        description: context.description ?? asset.description,
        sources: context.source_occurrences.length ? [...new Set(context.source_occurrences.map(occurrence => occurrence.source))] : asset.sources} : asset;
    });
  } catch (error) { console.warn("[brand-context] asset metadata unavailable", error); }
  return {kit: kit ? toBrandKitMeta(kit) : null, workspace: withPlatformFolders(workspace, await platformFolders)};

}

/**
 * The platform's Knowledge folders, or none of them. `readBrandKnowledgeFolders`
 * already absorbs every read failure; this also absorbs a transport that cannot
 * be opened at all, so a refused platform session never costs the page its kit.
 */
async function readPlatformKnowledgeFolders(
  clueFetch: () => Promise<typeof fetch> | typeof fetch,
): Promise<BrandKnowledgeFolder[]> {
  try {
    return await readBrandKnowledgeFolders(await clueFetch());
  } catch (error) {
    console.warn(
      "[brand-context] the platform knowledge read is unavailable; serving none:",
      error,
    );
    return [];
  }
}

/** Platform folders first (Company, Product, Audience, Proof), then the kit's Design. */
function withPlatformFolders(
  workspace: BrandContextWorkspace,
  platformFolders: readonly BrandKnowledgeFolder[],
): BrandContextWorkspace {
  return BrandContextWorkspaceSchema.parse({
    ...workspace,
    knowledgeFolders: [...platformFolders, ...workspace.knowledgeFolders],
  });
}

/**
 * The workspace's current kit: its LATEST version, whatever its approval
 * status — this screen is precisely the review surface for a draft. A
 * workspace holding several kits shows the most recently updated one
 * (`GET /brand-kits` already serves one row per kit, at its latest version).
 */
function selectBrandKit(
  kits: readonly BrandKitSummary[],
): BrandKitSummary | null {
  let newest: BrandKitSummary | null = null;
  let newestAt = Number.NEGATIVE_INFINITY;
  for (const kit of kits) {
    const at = Date.parse(kit.updated_at ?? kit.created_at ?? "");
    const rank = Number.isNaN(at) ? Number.NEGATIVE_INFINITY : at;
    if (!newest || rank > newestAt) {
      newest = kit;
      newestAt = rank;
    }
  }
  return newest;
}

const fixtureBrandContextRepository: BrandContextRepository = {
  ...fixtureAssetRepository(),
  async getWorkspace() {
    // No kit meta: the dummy is a DESIGN, not a stored kit — there is nothing to approve or
    // re-extract, and inventing a status chip for it would be the first lie on this page.
    return { kit: null, workspace: BrandContextWorkspaceSchema.parse(brandContextFixture) };
  },
};

/**
 * Fixture until the platform transport is configured, the real brand-kit
 * store after — the same `CLUE_API_BASE_URL` switch the rest of the app uses
 * (the design read still goes through `designFetch`, which needs the platform
 * session this variable configures).
 */
export function getBrandContextRepository(
  designFetch: () => Promise<typeof fetch> | typeof fetch,
  clueFetch: () => Promise<typeof fetch> | typeof fetch,
): BrandContextRepository {
  return process.env.CLUE_API_BASE_URL?.trim()
    ? httpBrandContextRepository({ clueFetch, designFetch })
    : fixtureBrandContextRepository;
}

export async function getBrandContextWorkspace(
  designFetch: () => Promise<typeof fetch> | typeof fetch,
  clueFetch: () => Promise<typeof fetch> | typeof fetch,
) {
  return getBrandContextRepository(designFetch, clueFetch).getWorkspace();
}
