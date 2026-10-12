// The site editor's dev loop (scripts/dev_stack.sh runs it): build everything once, serve from this
// process, and rebuild the browser bundle when the client or site-kit sources change. A change to
// the server itself needs `./scripts/dev_stack.sh restart-editor`.
import { watch } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DIST, ROOT, buildAll, buildClient } from "./build";

await buildAll();
await import(pathToFileURL(path.join(DIST, "server.mjs")).href);

let timer: ReturnType<typeof setTimeout> | null = null;
const rebuild = () => {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    buildClient()
      .then(() => console.log("site editor: client rebuilt"))
      .catch((error: unknown) => console.error("site editor: rebuild failed", error));
  }, 150);
};
for (const directory of [path.join(ROOT, "src/client"), path.join(ROOT, "../site-kit/src")]) {
  watch(directory, { recursive: true }, rebuild);
}
