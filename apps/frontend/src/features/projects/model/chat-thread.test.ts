import assert from "node:assert/strict";
import test from "node:test";
import { threadRouteHref } from "./chat-thread";

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
