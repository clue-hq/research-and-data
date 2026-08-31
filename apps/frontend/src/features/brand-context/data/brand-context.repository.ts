import {
  BrandContextWorkspaceSchema,
  type BrandContextWorkspace,
} from "../model/brand-context";
import {
  brandKitAssetIds,
  emptyBrandContextWorkspace,
  toBrandContextWorkspace,
} from "../model/brand-context-mapping";
import {
  BrandKitDetailSchema,
  BrandKitSummaryListSchema,
  DesignAssetRecordSchema,
  type BrandKitSummary,
  type DesignAssetRecord,
} from "../model/brand-kit";
import {
  toBrandKitMeta,
  type BrandKitMeta,
} from "../model/brand-kit-actions";
import { brandContextFixture } from "./brand-context.fixture";

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

export interface BrandContextRepository {
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
 * `getWorkspace` NEVER rejects. A workspace with no kit, a design-API refusal
 * and an unprovable session all render the same designed empty states — the
 * page is a review surface, and a 500 (or worse, the dummy's fixture content)
 * would be a lie about the client's brand.
 */
export function httpBrandContextRepository({
  designFetch,
}: {
  designFetch: () => Promise<typeof fetch> | typeof fetch;
}): BrandContextRepository {
  return {
    async getWorkspace() {
      try {
        return await readWorkspace(await designFetch());
      } catch (error) {
        console.warn(
          "[brand-context] serving the empty workspace; the brand-kit read failed:",
          error,
        );
        return { kit: null, workspace: emptyBrandContextWorkspace() };
      }
    },
  };
}

async function readWorkspace(designFetch: typeof fetch): Promise<BrandContextView> {
  const read = async (path: string): Promise<unknown> => {
    const response = await designFetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`design API ${path} responded ${response.status}`);
    }
    return response.json();
  };

  const kits = BrandKitSummaryListSchema.parse(await read("/brand-kits"));
  const selected = selectBrandKit(kits);
  if (!selected) return { kit: null, workspace: emptyBrandContextWorkspace() };

  const kit = BrandKitDetailSchema.parse(
    await read(`/brand-kits/${encodeURIComponent(selected.id)}`),
  );

  // The kit names its assets by id only; their filename, media type, byte
  // length and geometry live in the asset registry. One read per asset, in
  // parallel, and any refusal leaves that row with honest unknowns.
  const assetRecords = new Map<string, DesignAssetRecord>();
  await Promise.all(
    brandKitAssetIds(kit).map(async (assetId) => {
      try {
        const record = DesignAssetRecordSchema.parse(
          await read(`/assets/${encodeURIComponent(assetId)}`),
        );
        assetRecords.set(assetId, record);
      } catch {
        // An asset the registry cannot describe still renders its bytes.
      }
    }),
  );

  return {
    kit: toBrandKitMeta(kit),
    workspace: BrandContextWorkspaceSchema.parse(
      toBrandContextWorkspace(kit, { assetRecords }),
    ),
  };
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
): BrandContextRepository {
  return process.env.CLUE_API_BASE_URL?.trim()
    ? httpBrandContextRepository({ designFetch })
    : fixtureBrandContextRepository;
}

export async function getBrandContextWorkspace(
  designFetch: () => Promise<typeof fetch> | typeof fetch,
) {
  return getBrandContextRepository(designFetch).getWorkspace();
}
