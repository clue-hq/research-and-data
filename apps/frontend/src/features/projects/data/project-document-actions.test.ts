import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

test("document saves can be bundled for an editor without server authentication code", async () => {
  const result = await build({
    stdin: {
      contents: 'export { saveProjectDocument } from "./project-document-actions";',
      resolveDir: fileURLToPath(new URL(".", import.meta.url)),
    },
    bundle: true,
    platform: "browser",
    write: false,
    metafile: true,
    logLevel: "silent",
  });
  assert.ok(result.outputFiles[0].text.includes("saveProjectDocument"));
  assert.equal(Object.keys(result.metafile.inputs).some((path) => /authenticated-backend|next\/headers|server-only/.test(path)), false);
});
