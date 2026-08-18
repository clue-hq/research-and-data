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

// This page proves the current session and reads workspace-scoped design state on every render.
// Without an explicit dynamic boundary, the repository's intentional fail-soft catch can swallow
// Next's build-time dynamic-usage signal and pre-render an empty workspace. It also makes
// `router.refresh()` after approval/re-extraction a real store read rather than a cached shell.
export const dynamic = "force-dynamic";

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
  const [view, query] = await Promise.all([
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
      kit={view.kit}
      workspace={view.workspace}
    />
  );
}
