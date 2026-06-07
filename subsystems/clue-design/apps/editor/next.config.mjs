const outputFileTracingRoot = new URL(".", import.meta.url).pathname;

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot,
  eslint: {
    ignoreDuringBuilds: true
  },
  transpilePackages: ["konva", "react-konva"],
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  }
};

export default nextConfig;
