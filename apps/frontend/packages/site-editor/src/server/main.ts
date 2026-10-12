// The site editor's process entry. Built by scripts/build.ts into dist/server.mjs, which lives
// next to the built page (dist/index.html), the bundle (dist/assets/) and the shims (dist/shims/).
import http from "node:http";
import path from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import { handleEditorRequest } from "./app";
import { readConfig } from "./config";

const config = readConfig(process.env, path.dirname(fileURLToPath(import.meta.url)));

const server = http.createServer((request, response) => {
  handleEditorRequest({ host: request.headers.host, method: request.method ?? "GET", url: request.url ?? "/" }, { config })
    .then((result) => {
      response.writeHead(result.status, result.headers);
      if (request.method === "HEAD" || result.body === null) {
        response.end();
        return;
      }
      if (result.body instanceof ReadableStream) {
        Readable.fromWeb(result.body as Parameters<typeof Readable.fromWeb>[0]).pipe(response);
        return;
      }
      response.end(result.body);
    })
    .catch((error: unknown) => {
      console.error("site editor: request failed", error);
      if (!response.headersSent) response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end("Internal error");
    });
});

server.listen(config.port, config.host, () => {
  console.log(`site editor listening on http://${config.host}:${config.port} for *.${config.editorSuffix}`);
});
