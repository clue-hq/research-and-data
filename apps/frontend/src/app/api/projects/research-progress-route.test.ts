import assert from "node:assert/strict";
import test from "node:test";
import { GET } from "./[projectId]/research-progress/route";

// One segment above the bracketed route on purpose (the `[segment]` glob pitfall).
test("a failed read is retryable, uncached, and carries no upstream detail", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("private upstream connection details");
  });
  const response = await GET(new Request("http://localhost/api/projects/prj_1/research-progress"), {
    params: Promise.resolve({ projectId: "prj_1" }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { error: "Unable to read research progress. Please try again." });
});
