import assert from "node:assert/strict";
import test from "node:test";
import { canonicalJson } from "@clue/site-kit/editor-site";
import { DOC, fakeServer, headingOf, mountSiteSession, withHeading, type MountedSession, type FakeServer } from "./testing/site-session-bridge";

// The sync fix's core promise, end to end: through typing, dock edits, an agent's write, undo, a
// refused save and a reload racing a slow save, the canvas (the REAL FrameController), the app's
// working copy (the REAL session) and the server agree whenever nothing is in flight, and the server
// never receives a save based on an older version than it last reported.

async function agree(mounted: MountedSession, server: FakeServer, step: string): Promise<void> {
  await mounted.settle(12);
  assert.equal(mounted.latest().saves.isIdle(), true, `${step}: the save queue is idle`);
  const canvas = canonicalJson(mounted.frame.getState().site);
  const app = canonicalJson(mounted.latest().site);
  const truth = canonicalJson(server.site);
  assert.equal(canvas, app, `${step}: the canvas shows the app's copy`);
  assert.equal(app, truth, `${step}: the app's copy is the server's`);
  assert.equal(mounted.latest().saves.baseVersion, server.version, `${step}: the next save is based on the server's version`);
  assert.equal(server.staleBaseSaves, 0, `${step}: no save was based on an older version than the server reported`);
}

test("canvas, app copy and server agree through a whole editing session", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  await agree(mounted, server, "1. open");

  mounted.typeOnCanvas("hero", "Typed once");
  await mounted.flushCanvas();
  await agree(mounted, server, "2. type on the canvas");
  assert.equal(headingOf(server.site), "Typed once");

  // A dock edit to the call-to-action while hero typing is still unsent in the frame: the dock's
  // patch keeps it, and the frame's next proposal carries both.
  mounted.frame.componentSelected("cta", "CtaBand", [{ kind: "text", label: "Heading", name: "heading" }], { heading: "Talk to us" });
  await mounted.settle();
  mounted.typeOnCanvas("hero", "Typed twice");
  mounted.latest().inspector.onCommit("heading", "From the dock");
  await mounted.settle(12);
  await mounted.flushCanvas();
  await agree(mounted, server, "3. a dock edit while typing");
  assert.equal(headingOf(server.site), "Typed twice");
  assert.equal(headingOf(server.site, "cta"), "From the dock");

  // The agent writes on the server while the marketer has unsent typing; the reload brings the
  // agent's copy, which wins over the unsent typing (dropped once, never sent later).
  mounted.typeOnCanvas("cta", "Unsent when the agent wrote");
  server.outsideWrite(withHeading(server.site, "hero", "The agent wrote this"));
  mounted.latest().reload();
  await mounted.settle(12);
  await mounted.flushCanvas();
  await agree(mounted, server, "4. an agent write arrives");
  assert.equal(headingOf(server.site), "The agent wrote this");
  assert.equal(headingOf(server.site, "cta"), "From the dock");

  await mounted.pressUndo();
  await agree(mounted, server, "5. undo from the canvas");
  assert.equal(headingOf(server.site), "Typed twice", "the server stepped back past the agent's write");

  server.refuse = (site) => (headingOf(site) === "" ? "page.content.0(hero).heading: Too small" : null);
  mounted.typeOnCanvas("hero", "");
  await mounted.flushCanvas();
  await agree(mounted, server, "6. a refused save");
  assert.equal(mounted.latest().saves.error, "page.content.0(hero).heading: Too small");
  assert.equal(headingOf(mounted.frame.getState().site), "Typed twice", "the canvas went back to the server's copy");
  server.refuse = null;

  server.hold.save = true;
  mounted.typeOnCanvas("hero", "Saved slowly");
  await mounted.flushCanvas();
  server.hold.get = true;
  mounted.latest().stage.url.reload();
  await mounted.settle();
  server.release("get"); // the reload's read (older than the save) answers first: deferred
  await mounted.settle();
  server.release("save"); // then the save lands, and the deferred reload re-reads
  await agree(mounted, server, "7. a reload racing a slow save");
  assert.equal(headingOf(server.site), "Saved slowly");

  mounted.typeOnCanvas("cta", "Last edit");
  await mounted.flushCanvas();
  await agree(mounted, server, "8. editing carries on");
  assert.equal(headingOf(server.site, "cta"), "Last edit");
  await mounted.unmount();
});

// K6-2: Publish pressed while an edit is still on its way — typing the frame has not sent yet, then
// the save carrying it — waits for both, so the version published is the one the marketer sees.
test("getting ready to publish waits for the frame's unsent typing and the save that carries it", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  await agree(mounted, server, "open");

  server.hold.save = true;
  mounted.typeOnCanvas("hero", "Typed just before Publish");
  await mounted.settle();
  let ready: unknown = null;
  void mounted.latest().stage.publish.prepare(DOC).then((value) => (ready = value));
  await mounted.settle();
  assert.equal(ready, null, "not while the frame still holds the typing");
  await mounted.runFrameTimers(); // the pause passes: the frame sends the edit, the save goes out (held)
  await mounted.settle();
  assert.equal(ready, null, "not while the save carrying it is on its way");
  server.release("save");
  await mounted.settle(12);
  assert.deepEqual(ready, { ok: true, version: server.version });
  assert.equal(headingOf(server.site), "Typed just before Publish");
  await mounted.unmount();
});

test("getting ready to publish says why when the save it waited for is refused", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  await agree(mounted, server, "open");

  server.refuse = (site) => (headingOf(site) === "" ? "page.content.0(hero).heading: Too small" : null);
  mounted.typeOnCanvas("hero", "");
  await mounted.settle();
  const ready = mounted.latest().stage.publish.prepare(DOC);
  await mounted.runFrameTimers();
  assert.deepEqual(await ready, { ok: false, message: "page.content.0(hero).heading: Too small" });
  await mounted.unmount();
});
