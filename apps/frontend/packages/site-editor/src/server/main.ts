// The site editor's process entry. Built by scripts/build.ts into dist/server.mjs, which lives
// next to the built page (dist/index.html), the bundle (dist/assets/) and the shims (dist/shims/).
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readConfig } from "./config";
import { createEditorServer } from "./server";

const config = readConfig(process.env, path.dirname(fileURLToPath(import.meta.url)));

createEditorServer(config).listen(config.port, config.host, () => {
  console.log(`site editor listening on http://${config.host}:${config.port} for *.${config.editorSuffix}`);
});
