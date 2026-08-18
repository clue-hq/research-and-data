import { fetchAuthenticatedClueBackend } from "@/auth/authenticated-backend";
import {
  httpDesignArtifactRepository,
  type DesignArtifactRepository,
} from "./artifact.repository";

/**
 * W2.1, shared for the chat-flow mount: the design-artifact read seam over
 * the authenticated backend primitive, for Server Components (a Server
 * Component cannot call the origin-relative BFF; both paths share the same
 * provider-proof and workspace-header seam). Any refusal — not-found, auth
 * unavailable (fixture dev), backend unreachable — surfaces as the
 * repository's typed error; callers decide the fallback (the pages resolve
 * to null / an empty feed).
 */
export function backendDesignArtifactRepository(): DesignArtifactRepository {
  return httpDesignArtifactRepository({
    baseUrl: "",
    fetchImpl: (input, init) =>
      fetchAuthenticatedClueBackend(String(input), init),
  });
}
