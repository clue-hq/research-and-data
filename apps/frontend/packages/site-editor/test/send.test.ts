import assert from "node:assert/strict";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { test } from "node:test";
import { writeEditorResponse } from "../src/server/send";

test("a body stream that fails partway aborts that response and the server keeps serving", { timeout: 5000 }, async () => {
  const server = http.createServer((request, response) => {
    if (request.url === "/broken") {
      // A design-API asset response that aborts mid-body: one chunk, then an error.
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode("first chunk"));
          setTimeout(() => controller.error(new Error("upstream aborted")), 10);
        },
      });
      writeEditorResponse({ body, headers: { "content-type": "image/png" }, status: 200 }, "GET", response);
      return;
    }
    writeEditorResponse({ body: "ok", headers: { "content-type": "text/plain" }, status: 200 }, "GET", response);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  try {
    const broken = await fetch(`http://127.0.0.1:${port}/broken`, { signal: AbortSignal.timeout(2000) });
    assert.equal(broken.status, 200);
    // The client sees the truncated body abort: never a clean end (which would read as complete)
    // and never a hang (our own 2 s timeout firing).
    const outcome = await broken.text().then(
      () => "ended",
      (error: unknown) => (error instanceof Error && error.name === "TimeoutError" ? "hung" : "aborted"),
    );
    assert.equal(outcome, "aborted");
    // The process is still alive and serving.
    const next = await fetch(`http://127.0.0.1:${port}/next`);
    assert.equal(await next.text(), "ok");
  } finally {
    server.closeAllConnections();
    server.close();
  }
});
