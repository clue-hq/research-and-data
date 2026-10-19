import assert from "node:assert/strict";
import { it } from "node:test";
import { fetchDocumentAgentRun } from "../data/document-agent-run";
import { INITIAL_AGENT_RUN_POLL, reduceAgentRunPoll, siteReloadWanted } from "./document-agent-run.logic";

const idle = { active: false, runId: null, currentVersion: 3 };
const busy = { active: true, runId: "run_1", currentVersion: 3 };

it("copies the read and starts with no reload", () => {
  const first = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, busy);
  assert.deepEqual(first, { active: true, runId: "run_1", currentVersion: 3, reloadNonce: 0 });
});

it("bumps the reload nonce exactly when current_version moves", () => {
  const a = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, busy);
  const b = reduceAgentRunPoll(a, busy); // same version — no bump
  assert.equal(b.reloadNonce, 0);
  const c = reduceAgentRunPoll(b, { ...busy, currentVersion: 4 }); // a checkpoint landed
  assert.equal(c.reloadNonce, 1);
  const d = reduceAgentRunPoll(c, { ...idle, currentVersion: 5 }); // the run finished and committed
  assert.equal(d.reloadNonce, 2);
  assert.equal(d.active, false);
  assert.equal(d.runId, null);
});

it("does not treat the first observed version as a change", () => {
  const first = reduceAgentRunPoll(INITIAL_AGENT_RUN_POLL, { ...idle, currentVersion: 9 });
  assert.equal(first.reloadNonce, 0);
});

it("fetches and validates the agent-run read through the configured transport", async () => {
  const calls: string[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    calls.push(String(input instanceof URL ? input.pathname : input));
    return new Response(
      JSON.stringify({ schema_version: 1, document_id: "doc_1", active: true, run_id: "run_9", current_version: 12 }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const result = await fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl }, "doc_1");
  assert.deepEqual(result, { active: true, runId: "run_9", currentVersion: 12 });
  assert.deepEqual(calls, ["/documents/doc_1/agent-run"]);
});

it("rejects a non-200 and a malformed body", async () => {
  const notFound: typeof fetch = async () => new Response("{}", { status: 404 });
  await assert.rejects(fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl: notFound }, "doc_x"));
  const malformed: typeof fetch = async () =>
    new Response(JSON.stringify({ active: "yes" }), { status: 200, headers: { "content-type": "application/json" } });
  await assert.rejects(fetchDocumentAgentRun({ apiBaseUrl: "http://design.test", fetchImpl: malformed }, "doc_x"));
});

// Review finding K3-3: the standalone route polls the document's version to notice agent writes. It
// must not reload the site for a version the session wrote itself — that reload pushed a copy into the
// canvas while the marketer was still typing.
it("the standalone site reloads for someone else's write or a finished run, never for its own save", () => {
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: 6, runEnded: false }), false, "our own save");
  assert.equal(siteReloadWanted({ polledVersion: 5, knownVersion: 6, runEnded: false }), false, "a poll older than our save");
  assert.equal(siteReloadWanted({ polledVersion: 7, knownVersion: 6, runEnded: false }), true, "someone else wrote");
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: 6, runEnded: true }), true, "the agent's run finished");
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: null, runEnded: false }), true, "nothing loaded yet");
  assert.equal(siteReloadWanted({ polledVersion: null, knownVersion: 6, runEnded: false }), false);
});
