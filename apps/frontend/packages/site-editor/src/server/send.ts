import type http from "node:http";
import { pipeline, Readable } from "node:stream";
import type { EditorResponse } from "./app";

/**
 * Writes a handled response to the socket. A body stream (the asset-store proxy's upstream body)
 * goes through pipeline, so a stream that fails partway is logged and the response destroyed —
 * the client sees an aborted body, and the error never reaches the process as an unhandled
 * 'error' event that would take the editor down for every workspace.
 */
export function writeEditorResponse(result: EditorResponse, method: string, response: http.ServerResponse): void {
  response.writeHead(result.status, result.headers);
  if (method === "HEAD" || result.body === null) {
    response.end();
    return;
  }
  if (result.body instanceof ReadableStream) {
    pipeline(Readable.fromWeb(result.body as Parameters<typeof Readable.fromWeb>[0]), response, (error) => {
      if (error) console.error("site editor: response stream failed", error);
    });
    return;
  }
  response.end(result.body);
}
