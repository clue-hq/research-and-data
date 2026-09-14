import type { NextConfig } from "next";

const config: NextConfig = {
  devIndicators: false,
  reactStrictMode: true,
  turbopack: { root: process.cwd() },
  outputFileTracingRoot: process.cwd(),
};

export default config;
