import type { Metadata } from "next";
import {
  authenticatedBackendContext,
  fetchAuthenticatedDesignBackend,
} from "@/auth/authenticated-backend";
import { BrandContextScreen } from "@/features/brand-context/components/brand-context-screen";
import { getBrandContextWorkspace } from "@/features/brand-context/data/brand-context.repository";
import {
  BrandAssetViewSchema,
  BrandColorModeSchema,
  BrandContextSectionSchema,
  BrandDocumentModeSchema,
} from "@/features/brand-context/model/brand-context";

export const metadata: Metadata = {
  title: "Brand context",
};

interface BrandContextPageProps {
  searchParams: Promise<{
    asset?: string;
    file?: string;
    mode?: string;
    section?: string;
    theme?: string;
    view?: string;
  }>;
}

/**
 * Slice 1: the read seam's server-side transport. A Server Component cannot
 * call its own origin-relative BFF, so it uses the same provider-proof and
 * workspace-stamping primitive the BFF uses (the W2.1 artifact-route pattern).
 * The session is resolved ONCE and shared by every call of this render — a
 * kit's assets are a read apiece, and re-proving the session for each would
 * multiply the platform round trips.
 */
async function designFetch(): Promise<typeof fetch> {
  const context = await authenticatedBackendContext();
  return (input, init) =>
    fetchAuthenticatedDesignBackend(String(input), init, context);
}

export default async function BrandContextPage({ searchParams }: BrandContextPageProps) {
  const [workspace, query] = await Promise.all([
    getBrandContextWorkspace(designFetch),
    searchParams,
  ]);

  const section = BrandContextSectionSchema.safeParse(query.section);
  const assetView = BrandAssetViewSchema.safeParse(query.view);
  const colorMode = BrandColorModeSchema.safeParse(query.theme);
  const documentMode = BrandDocumentModeSchema.safeParse(query.mode);

  return (
    <BrandContextScreen
      initial={{
        assetId: query.asset,
        assetView: assetView.success ? assetView.data : "grid",
        colorMode: colorMode.success ? colorMode.data : "light",
        documentMode: documentMode.success ? documentMode.data : "preview",
        filePath: query.file,
        section: section.success ? section.data : "colors",
      }}
      workspace={workspace}
    />
  );
}
