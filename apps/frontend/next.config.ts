import type { NextConfig } from "next";

/**
 * Same-origin proxy for the backend read layer.
 *
 * The ratified CORS posture is: production serves the frontend and the API
 * same-origin, so no cross-origin credentialed request is ever made; a
 * development setup allows the exact localhost origin, listed explicitly;
 * wildcard never. This rewrite is that same-origin seam — with
 * `CLUE_ACCOUNTS_API_BASE_URL` set, `/frontend/v1/*` on this origin forwards to
 * the backend, so a browser-side caller needs no CORS grant at all.
 *
 * It is a transport passthrough, not an auth layer: `X-Workspace-Id` is added
 * by the repositories (which run server-side), never by the rewrite.
 */
const READ_PREFIX = "/frontend/v1";

const configuredBaseUrl = process.env.CLUE_ACCOUNTS_API_BASE_URL?.trim().replace(
  /\/+$/,
  "",
);

// The base may be given as the origin or as the already-mounted surface; the
// transport module accepts both, so the rewrite must too or a base ending in
// /frontend/v1 would proxy to /frontend/v1/frontend/v1.
const destinationBase = configuredBaseUrl?.endsWith(READ_PREFIX)
  ? configuredBaseUrl.slice(0, -READ_PREFIX.length)
  : configuredBaseUrl;

const nextConfig: NextConfig = {
  // Keep local visual reviews faithful to the Figma canvas.
  devIndicators: false,
  async rewrites() {
    if (!destinationBase) return [];
    return [
      {
        source: `${READ_PREFIX}/:path*`,
        destination: `${destinationBase}${READ_PREFIX}/:path*`,
      },
    ];
  },
};

export default nextConfig;
