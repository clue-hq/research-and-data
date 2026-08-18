import {
  BrandContextWorkspaceSchema,
  type BrandContextWorkspace,
} from "../model/brand-context";
import { brandContextFixture } from "./brand-context.fixture";

export interface BrandContextRepository {
  getWorkspace(): Promise<BrandContextWorkspace>;
}

const fixtureBrandContextRepository: BrandContextRepository = {
  async getWorkspace() {
    return BrandContextWorkspaceSchema.parse(brandContextFixture);
  },
};

function createHttpBrandContextRepository(baseUrl: string): BrandContextRepository {
  return {
    async getWorkspace() {
      const response = await fetch(`${baseUrl}/api/v1/brand-context`, {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(`Brand Context request failed with ${response.status}`);
      }

      return BrandContextWorkspaceSchema.parse(await response.json());
    },
  };
}

export function getBrandContextRepository(): BrandContextRepository {
  const baseUrl = process.env.CLUE_API_BASE_URL?.replace(/\/$/, "");
  return baseUrl
    ? createHttpBrandContextRepository(baseUrl)
    : fixtureBrandContextRepository;
}

export async function getBrandContextWorkspace() {
  return getBrandContextRepository().getWorkspace();
}
