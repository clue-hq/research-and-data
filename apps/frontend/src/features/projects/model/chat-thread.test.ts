import assert from "node:assert/strict";
import test from "node:test";
import { ChatThreadListResponseSchema, threadRouteHref } from "./chat-thread";

/* --------------------------------------------------------------------------
 * The speaker projection (task 4 fix round 1, finding I1)
 *
 * `ThreadWire.speaker` is the platform's DURABLE answer to "does this thread
 * hold a design leg, and is it running right now" — the fact the editor lock
 * needs on a cold load, where the replayed frame backlog reaches back only a
 * few turns. It was on the wire and unparsed.
 * ----------------------------------------------------------------------- */

function threadWire(speaker?: unknown) {
  return {
    id: "thread-1",
    title: null,
    href: "/projects/p1/chats/thread-1",
    status: "running",
    pinned: false,
    project_id: "p1",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...(speaker === undefined ? {} : { speaker }),
  };
}

function parseOne(speaker?: unknown) {
  return ChatThreadListResponseSchema.parse({ data: [threadWire(speaker)] })
    .threads[0];
}

test("a running design leg is read off the thread wire", () => {
  assert.deepEqual(
    parseOne({
      role: "design",
      design_leg_id: "leg-9",
      design_leg_state: "running",
    })?.designLeg,
    { legId: "leg-9", state: "running" },
  );
});

test("a leg awaiting the user is read as open but not running", () => {
  assert.deepEqual(
    parseOne({
      role: "design",
      design_leg_id: "leg-9",
      design_leg_state: "open_awaiting_user",
    })?.designLeg,
    { legId: "leg-9", state: "open_awaiting_user" },
  );
});

test("a head-of-ABM speaker states positively that there is no leg", () => {
  assert.deepEqual(
    parseOne({
      role: "head_of_abm",
      design_leg_id: null,
      design_leg_state: null,
    })?.designLeg,
    { legId: null, state: null },
  );
});

test("a read that derived no speaker leaves the leg UNKNOWN, never 'no leg'", () => {
  // The platform sends `speaker: null` on reads that did not derive it (the
  // tool-reference projections after a create/rename). Absent knowledge is
  // never a guess — and for the editor lock, guessing "no leg" here is the
  // dangerous direction.
  assert.equal(parseOne()?.designLeg, null);
  assert.equal(parseOne(null)?.designLeg, null);
});

test("a leg state this build does not know reads as RUNNING, not as absent", () => {
  // Fail-safe: a state we cannot interpret still proves a leg EXISTS, and the
  // lock's direction of error is to hold rather than to open the editor.
  assert.deepEqual(
    parseOne({
      role: "design",
      design_leg_id: "leg-9",
      design_leg_state: "some_future_state",
    })?.designLeg,
    { legId: "leg-9", state: "running" },
  );
});

test("an unreadable speaker never takes the whole thread list down", () => {
  assert.equal(parseOne("nonsense")?.designLeg, null);
  assert.equal(parseOne({ role: 42 })?.designLeg, null);
});

test("thread hrefs are path-based chats routes", () => {
  assert.equal(threadRouteHref("p1", "t2", ""), "/projects/p1/chats/t2");
  assert.equal(
    threadRouteHref("campaign one", "thread/x", ""),
    "/projects/campaign%20one/chats/thread%2Fx",
  );
});

test("the legacy thread query param is never resurrected", () => {
  assert.equal(
    threadRouteHref("p1", "t2", "thread=t1&handoff=h1"),
    "/projects/p1/chats/t2?handoff=h1",
  );
});

test("pane-state and handoff query keys ride along", () => {
  assert.equal(
    threadRouteHref("p1", "t2", "surface=gallery"),
    "/projects/p1/chats/t2?surface=gallery",
  );
  assert.equal(
    threadRouteHref("p1", "t2", "surface=web&edit=1&selection=text"),
    "/projects/p1/chats/t2?surface=web&edit=1&selection=text",
  );
});

/* --------------------------------------------------------------------------
 * The discovery a thread is holding (agent-authored discovery, task 10)
 *
 * While an account discovery runs, the thread that launched it is busy. The
 * thread LIST read names the run so the composer can show Stop for it.
 * ----------------------------------------------------------------------- */

function parseDiscovery(discovery?: unknown) {
  return ChatThreadListResponseSchema.parse({
    data: [
      { ...threadWire(), ...(discovery === undefined ? {} : { discovery }) },
    ],
  }).threads[0];
}

test("a thread holding a discovery names the run and whether it can stop", () => {
  assert.deepEqual(
    parseDiscovery({ run_id: "run-7", stoppable: true })?.discovery,
    { runId: "run-7", stoppable: true },
  );
  assert.deepEqual(
    parseDiscovery({ run_id: "run-7", stoppable: false })?.discovery,
    { runId: "run-7", stoppable: false },
  );
});

test("a thread holding no discovery reads null, whether null or absent", () => {
  assert.equal(parseDiscovery(null)?.discovery, null);
  assert.equal(parseDiscovery()?.discovery, null);
});
