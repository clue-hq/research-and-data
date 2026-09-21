import type { NextConfig } from "next";
import { localWorkspaceInstance } from "./src/auth/local-workspace";

// canvaskit-wasm's glue requires Node built-ins (`fs`/`path`/`crypto`) and probes for the optional
// `canvas` package on code paths that never run in the browser. Both bundlers must be told to stub
// them, and they use different mechanisms — webpack `resolve.fallback`, Turbopack `resolveAlias`.
const CANVASKIT_STUB = "./src/features/design-editor/engine/scene/empty-module.ts";
const localInstance = localWorkspaceInstance();

const nextConfig: NextConfig = {
  // The script runs in an opaque-origin sandboxed srcdoc. Anonymous CORS is
  // required for its pinned SRI; this public file carries no user credentials.
  async headers() {
    return [{
      source: "/vendor/tailwind-browser.js",
      headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
    }];
  },
  // Parallel local instances must not share Next's compiler cache or dev lock.
  distDir: localInstance?.distDir ?? ".next",
  typescript: {
    tsconfigPath: localInstance ? `tsconfig.local-${localInstance.port}.json` : "tsconfig.json",
  },
  // Railway's runtime image copies only Next's traced production server rather
  // than the full dependency tree. `next start` remains available locally.
  output: "standalone",
  // Keep local visual reviews faithful to the Figma canvas.
  devIndicators: false,
  // This monorepo checkout may live below an unrelated user-level package-lock.json. Without an
  // explicit root, Next 16 can select that ancestor as the Turbopack/tracing workspace and stall
  // while compiling files outside this application. Keep production builds bounded to this npm
  // package; npm runs this config with apps/frontend as its working directory.
  turbopack: {
    root: process.cwd(),
    // `npm run dev` is Turbopack, which ignores the `webpack` key below and has no
    // `resolve.fallback` equivalent. Verified AD1.2: without these, importing canvaskit-wasm fails
    // to compile with `Module not found: Can't resolve 'fs'` at canvaskit.js:157. Only the
    // `browser` condition is supported, which is what we want — server code keeps the real
    // built-ins (and the repo's own Node usage is `node:`-prefixed, so it never matches here).
    resolveAlias: {
      canvas: { browser: CANVASKIT_STUB },
      fs: { browser: CANVASKIT_STUB },
      path: { browser: CANVASKIT_STUB },
      crypto: { browser: CANVASKIT_STUB },
    },
  },
  outputFileTracingRoot: process.cwd(),
  // `npm run build` uses --webpack, so this key governs production builds. Mirrors the design
  // editor's own next.config.mjs.
  webpack: (config) => {
    config.resolve.alias = { ...config.resolve.alias, canvas: false };
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, crypto: false };
    return config;
  },
};

export default nextConfig;
