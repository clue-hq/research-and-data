import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep local visual reviews faithful to the Figma canvas.
  devIndicators: false,
  // This monorepo checkout may live below an unrelated user-level package-lock.json. Without an
  // explicit root, Next 16 can select that ancestor as the Turbopack/tracing workspace and stall
  // while compiling files outside this application. Keep production builds bounded to this npm
  // package; npm runs this config with apps/frontend as its working directory.
  turbopack: { root: process.cwd() },
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
