import assert from "node:assert/strict";
import test from "node:test";
import { GET } from "./[projectId]/discovery/route";

// Sits one segment ABOVE `[projectId]/discovery/` on purpose: `npm test` glob-expands each path,
// and a test inside a bracketed segment is collected as ZERO tests (accounts.md, tab lift).

test("a failed read is retryable, uncached, and carries no upstream detail", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("private upstream connection details");
  });
  const response = await GET(new Request("http://localhost/api/projects/prj_1/discovery"), {
    params: Promise.resolve({ projectId: "prj_1" }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    error: "Unable to read discovery progress. Please try again.",
  });
});
