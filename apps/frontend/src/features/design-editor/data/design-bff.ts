import {
  defaultDesignFetch,
  type DesignEditorConfig,
} from "../engine/config";

/** The authenticated BFF mount for the design API (W1.2) — never a FastAPI
 * origin; the proxy stamps the workspace header server-side. */
export const DESIGN_API_BFF_PREFIX = "/api/clue/design";

/** The headerless BFF mount for the design API's public, content-addressed
 * `/asset-store/{digest}` bytes (AD1.7, founder ruling D8) — same origin, no
 * workspace header, because that upstream route refuses one. */
export const DESIGN_PUBLIC_BFF_PREFIX = "/api/clue/design-public";

/**
 * W2.1: the engine's config for browser callers, routed through the BFF.
 *
 * The extracted engine builds request URLs with `new URL(path, apiBaseUrl)`
 * where `path` is origin-absolute (`/documents/…`) — so `apiBaseUrl` must be
 * an origin, never a path prefix: a relative base throws ("Invalid base
 * URL"), and even an absolute base with a path would have its prefix dropped
 * by URL resolution. (W1.1's config doc sketched passing the BFF prefix as
 * `apiBaseUrl` directly; this factory is the working form of that contract —
 * the engine stays verbatim.)
 *
 * So: `apiBaseUrl` is the page origin, and `fetchImpl` re-mounts every
 * engine URL under the same-origin BFF prefix, where session cookies ride
 * along automatically and the proxy adds the workspace header server-side.
 */
export function designBffConfig(): DesignEditorConfig {
  const origin = window.location.origin;
  return {
    apiBaseUrl: origin,
    fetchImpl: (input, init) => {
      const url =
        input instanceof URL
          ? input
          : new URL(input instanceof Request ? input.url : input, origin);
      return defaultDesignFetch(
        `${DESIGN_API_BFF_PREFIX}${url.pathname}${url.search}`,
        init,
      );
    },
  };
}
