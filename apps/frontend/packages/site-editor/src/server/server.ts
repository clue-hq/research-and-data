// The site editor's HTTP server, apart from its process entry (main.ts) so it can be tested.
import http from "node:http";
import { handleEditorRequest } from "./app";
import type { EditorServerConfig } from "./config";
import { writeEditorResponse } from "./send";

/** Review K3-7: every workspace's editor shares one registrable domain (until it is on the Public Suffix
 * List), so one workspace's agent code can set cookies that every other workspace's editor then receives.
 * The editor reads no cookies (only host, method and path reach the handler), and must not answer 431
 * for them: room for a browser's whole cookie jar for a domain (about 180 cookies of 4 KB). */
export const EDITOR_MAX_HEADER_BYTES = 1024 * 1024;

export function createEditorServer(config: EditorServerConfig): http.Server {
  return http.createServer({ maxHeaderSize: EDITOR_MAX_HEADER_BYTES }, (request, response) => {
    const method = request.method ?? "GET";
    handleEditorRequest({ host: request.headers.host, method, url: request.url ?? "/" }, { config })
      .then((result) => writeEditorResponse(result, method, response))
      .catch((error: unknown) => {
        console.error("site editor: request failed", error);
        if (!response.headersSent) response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
        response.end("Internal error");
      });
  });
}
