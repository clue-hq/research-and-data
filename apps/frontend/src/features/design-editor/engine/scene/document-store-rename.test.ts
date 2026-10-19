import assert from "node:assert/strict";
import { test } from "node:test";
import { DocumentRenameError, renameDocument } from "./documentStore";

// K1-5 (founder ruling 2026-10-16): the design API refuses a rename while a design run drives the
// document. The refusal must reach the caller with its status and code, not as prose, so the
// header can tell an agent-run refusal from any other failure.
test("a rename refused because a design run drives the document carries its status and code", async () => {
  const fetchImpl = (async () =>
    new Response(
      JSON.stringify({ detail: { code: "document.agent_run_active", run_id: "run_1" } }),
      { status: 409, headers: { "content-type": "application/json" } },
    )) as typeof fetch;
  await assert.rejects(
    renameDocument({ apiBaseUrl: "http://design.test", fetchImpl }, "doc-1", "New title"),
    (error: unknown) =>
      error instanceof DocumentRenameError &&
      error.status === 409 &&
      error.code === "document.agent_run_active",
  );
});

test("a rename refused without a JSON body still reports its status, with no code", async () => {
  const fetchImpl = (async () => new Response("boom", { status: 500 })) as typeof fetch;
  await assert.rejects(
    renameDocument({ apiBaseUrl: "http://design.test", fetchImpl }, "doc-1", "New title"),
    (error: unknown) => error instanceof DocumentRenameError && error.status === 500 && error.code === null,
  );
});

test("a rename that lands returns the title the server stored", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ schema_version: 1, document_id: "doc-1", title: "Stored" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  assert.equal(
    await renameDocument({ apiBaseUrl: "http://design.test", fetchImpl }, "doc-1", " Stored "),
    "Stored",
  );
});
