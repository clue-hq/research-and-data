const outputFileTracingRoot = new URL(".", import.meta.url).pathname;

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The script runs in an opaque-origin sandboxed srcdoc. Anonymous CORS is
  // required for its pinned SRI; this public file carries no user credentials.
  async headers() {
    return [{
      source: "/vendor/tailwind-browser.js",
      headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
    }];
  },
  outputFileTracingRoot,
  eslint: {
    ignoreDuringBuilds: true
  },
  transpilePackages: ["konva", "react-konva"],
  webpack: (config, { isServer }) => {
    config.resolve.alias.canvas = false;
    if (!isServer) {
      // canvaskit-wasm's glue references Node built-ins on its Node code path
      // (unused in the browser); stub them so the client bundle resolves.
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        crypto: false
      };
    }
    return config;
  }
};

export default nextConfig;
