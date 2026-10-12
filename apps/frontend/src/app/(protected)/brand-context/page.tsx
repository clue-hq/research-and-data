import type { Metadata } from "next";
import { getProtectedSession } from "@/features/session/data/session-dal";
import {
  authenticatedBackendContext,
  type AuthenticatedBackendContext,
  fetchAuthenticatedClueBackend,
  fetchAuthenticatedDesignBackend,
} from "@/auth/authenticated-backend";
import { BrandContextScreen } from "@/features/brand-context/components/brand-context-screen";
import { getBrandContextWorkspace } from "@/features/brand-context/data/brand-context.repository";
import { readOnboardingStatus } from "@/features/brand-context/data/brand-knowledge.repository";
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
  // The unconfigured (fixture) path serves the dummy's brand and has no run to poll, so it
  // issues no status request at all — the same `CLUE_API_BASE_URL` switch
  // `getBrandContextRepository` reads to choose the fixture adapter.
  const platformConfigured = Boolean(process.env.CLUE_API_BASE_URL?.trim());
  const readStatus = async () => {
    if (!platformConfigured) return null;
    try {
      return await readOnboardingStatus(await clueFetch());
    } catch {
      // Proving the session is the workspace read's job to report; an unpollable status just
      // means no progressive fill, never a failed page.
      return null;
    }
  };
  const [view, onboarding, query, session] = await Promise.all([
    getBrandContextWorkspace(designFetch, clueFetch),
    readStatus(),
    searchParams,
    getProtectedSession(),
  ]);

  const section = BrandContextSectionSchema.safeParse(query.section);
  const assetView = BrandAssetViewSchema.safeParse(query.view);
  const colorMode = BrandColorModeSchema.safeParse(query.theme);

  return (
    <BrandContextScreen
      key={session?.principal.workspace_id ?? "fixture"}
      scopeKey={session?.principal.workspace_id ?? "fixture"}
      canWriteKnowledge={session?.principal.permissions.includes("project.write") ?? false}
      initial={{
        assetId: query.asset,
        assetView: assetView.success ? assetView.data : "grid",
        colorMode: colorMode.success ? colorMode.data : "light",
        filePath: query.file,
        section: section.success ? section.data : "colors",
      }}
      kit={view.kit}
      measured={view.measured}
      onboarding={onboarding}
      workspace={view.workspace}
    />
  );
}
