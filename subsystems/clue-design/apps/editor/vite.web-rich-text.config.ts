import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  publicDir: false,
  build: {
    emptyOutDir: false,
    lib: {
      entry: resolve(__dirname, "src/iframe/webRichTextRuntime.ts"),
      formats: ["iife"],
      name: "LumenWebRichTextBundle",
      fileName: () => "web-rich-text-runtime.js"
    },
    outDir: resolve(__dirname, "public/vendor"),
    sourcemap: false
  }
});
