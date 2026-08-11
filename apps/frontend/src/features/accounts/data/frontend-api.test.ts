import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError, fetchRead } from "./frontend-api";

test("authenticated reads use the mounted path without legacy tenancy headers", async () => {
  let requestedPath = "";
  let requestedHeaders = new Headers();
  const body = await fetchRead(
    "/accounts",
    { searchParams: { cursor: "next", limit: 50, projectId: undefined } },
    async (path, init) => {
      requestedPath = path;
      requestedHeaders = new Headers(init?.headers);
      return Response.json({ data: [], meta: { total: 0, nextCursor: null } });
    },
  );

  assert.equal(requestedPath, "/frontend/v1/accounts?cursor=next&limit=50");
  assert.equal(requestedHeaders.get("accept"), "application/json");
  assert.equal(requestedHeaders.get("authorization"), null);
  assert.equal(requestedHeaders.get("x-workspace-id"), null);
  assert.equal(requestedHeaders.get("x-clue-workspace-id"), null);
  assert.deepEqual(body, { data: [], meta: { total: 0, nextCursor: null } });
});

test("only domain record 404s resolve to null", async () => {
  const missing = await fetchRead(
    "/accounts/acme",
    { recordNotFoundAllowed: true },
    async () =>
      Response.json(
        {
          error: {
            code: "ACCOUNT_NOT_FOUND",
            message: "Account was not found",
            requestId: "request-1",
          },
        },
        { status: 404 },
      ),
  );
  assert.equal(missing, null);

  await assert.rejects(
    fetchRead(
      "/accounts",
      {},
      async () =>
        Response.json(
          {
            error: {
              code: "NOT_FOUND",
              message: "Route was not found",
              requestId: "request-2",
            },
          },
          { status: 404 },
        ),
    ),
    (error: unknown) =>
      error instanceof ClueApiError &&
      error.code === "NOT_FOUND" &&
      error.requestId === "request-2",
  );
});
