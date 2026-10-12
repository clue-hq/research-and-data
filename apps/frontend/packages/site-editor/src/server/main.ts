// The site editor's process entry. Built by scripts/build.ts into dist/server.mjs, which lives
// next to the built page (dist/index.html), the bundle (dist/assets/) and the shims (dist/shims/).
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { handleEditorRequest } from "./app";
import { readConfig } from "./config";
import { writeEditorResponse } from "./send";

const config = readConfig(process.env, path.dirname(fileURLToPath(import.meta.url)));

const server = http.createServer((request, response) => {
  const method = request.method ?? "GET";
  handleEditorRequest({ host: request.headers.host, method, url: request.url ?? "/" }, { config })
    .then((result) => writeEditorResponse(result, method, response))
    .catch((error: unknown) => {
      console.error("site editor: request failed", error);
      if (!response.headersSent) response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end("Internal error");
    });
});

server.listen(config.port, config.host, () => {
  console.log(`site editor listening on http://${config.host}:${config.port} for *.${config.editorSuffix}`);
});
