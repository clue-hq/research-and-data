import type { Metadata } from "next";
import {
  authenticatedBackendContext,
  type AuthenticatedBackendContext,
  fetchAuthenticatedClueBackend,
  fetchAuthenticatedDesignBackend,
} from "@/auth/authenticated-backend";
import { BrandContextScreen } from "@/features/brand-context/components/brand-context-screen";
import { getBrandContextWorkspace } from "@/features/brand-context/data/brand-context.repository";
import {
  BrandAssetViewSchema,
  BrandColorModeSchema,
  BrandContextSectionSchema,
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
    section?: string;
    theme?: string;
    view?: string;
  }>;
}

/**
 * The read seam's server-side transports — one per backend, over ONE session.
 *
 * A Server Component cannot call its own origin-relative BFF, so it uses the same
 * provider-proof and workspace-stamping primitives the BFF uses (the W2.1
 * artifact-route pattern). This page reads both stores: the brand kit from the
 * design backend, the onboarding documents from the platform. The session is
 * proven at most ONCE per render and shared by both — a kit's assets and the
 * documents are a read apiece, and re-proving for each would multiply the round
 * trips. It is proven lazily, so the unconfigured fixture path (which calls
 * neither) never opens a transport at all.
 */
function backendFetches(): {
  clueFetch: () => Promise<typeof fetch>;
  designFetch: () => Promise<typeof fetch>;
} {
  let pending: Promise<AuthenticatedBackendContext> | null = null;
  const sharedContext = () => (pending ??= authenticatedBackendContext());
  return {
    async clueFetch() {
      const context = await sharedContext();
      return (input, init) =>
        fetchAuthenticatedClueBackend(String(input), init, context);
    },
    async designFetch() {
      const context = await sharedContext();
      return (input, init) =>
        fetchAuthenticatedDesignBackend(String(input), init, context);
    },
  };
}

export default async function BrandContextPage({ searchParams }: BrandContextPageProps) {
  const { clueFetch, designFetch } = backendFetches();
  const [view, query] = await Promise.all([
    getBrandContextWorkspace(designFetch, clueFetch),
    searchParams,
  ]);

  const section = BrandContextSectionSchema.safeParse(query.section);
  const assetView = BrandAssetViewSchema.safeParse(query.view);
  const colorMode = BrandColorModeSchema.safeParse(query.theme);

  return (
    <BrandContextScreen
      initial={{
        assetId: query.asset,
        assetView: assetView.success ? assetView.data : "grid",
        colorMode: colorMode.success ? colorMode.data : "light",
        filePath: query.file,
        section: section.success ? section.data : "colors",
      }}
      kit={view.kit}
      workspace={view.workspace}
    />
  );
}
