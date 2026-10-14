import assert from "node:assert/strict";
import test from "node:test";
import { DOC, fakeServer, headingOf, mountSiteSession, startSite } from "./testing/site-session-bridge";

// The sync fix (2026-10-14): the app's working copy is the only copy in the browser that decides
// what is saved. These run the REAL session against a REAL FrameController over an in-memory bridge.

async function selectCta(mounted: Awaited<ReturnType<typeof mountSiteSession>>) {
  mounted.frame.componentSelected("cta", "CtaBand", [{ kind: "text", label: "Heading", name: "heading" }], { heading: "Talk to us" });
  await mounted.settle();
}

test("opening a site: the frame shows the server's copy and nothing is saved", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  assert.equal(headingOf(mounted.frame.getState().site), "Old headline");
  assert.equal(mounted.latest().saves.baseVersion, 5);
  assert.equal(server.version, 5);
  await mounted.unmount();
});

test("review S2b-3, GET answers first: a reload read before our save landed is never adopted", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "New headline");
  await mounted.flushCanvas();
  server.hold.get = true;
  mounted.latest().stage.url.reload();
  await mounted.settle();
  server.release(); // the GET (read v5, before the save) answers first
  await mounted.settle();
  server.release(); // then the save lands as v6
  await mounted.settle();
  assert.equal(headingOf(mounted.latest().site), "New headline", "the app copy keeps the saved edit");
  await selectCta(mounted);
  mounted.latest().inspector.onCommit("heading", "Book a call");
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "New headline", "the later dock edit did not erase the canvas edit");
  assert.equal(headingOf(server.site, "cta"), "Book a call");
  assert.equal(mounted.latest().saves.note, null);
  assert.equal(mounted.latest().saves.error, null);
  assert.equal(server.staleBaseSaves, 0);
  await mounted.unmount();
});

test("review S2b-3, PUT answers first: the next edit is based on the newest version, never refused", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "New headline");
  await mounted.flushCanvas();
  server.hold.get = true;
  mounted.latest().stage.url.reload();
  await mounted.settle();
  server.release(); // the save lands first (v6)…
  await mounted.settle();
  server.release(); // …then the GET that read v5 answers
  await mounted.settle(12);
  await selectCta(mounted);
  mounted.latest().inspector.onCommit("heading", "Book a call");
  await mounted.settle(12);
  assert.equal(mounted.latest().saves.note, null, "not refused as 'moved on'");
  assert.equal(headingOf(server.site), "New headline");
  assert.equal(headingOf(server.site, "cta"), "Book a call");
  assert.equal(server.staleBaseSaves, 0);
  await mounted.unmount();
});

test("review S2b-3, tab return: nothing from the earlier visit is adopted or saved; the first edit uses the newest base", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "Before leaving");
  await mounted.flushCanvas();
  await mounted.open(null); // a web or ad tab
  server.outsideWrite(startSite({ hero: "Written while away", cta: "Talk to us" }));
  server.hold.get = true; // the fresh read is slow
  await mounted.open(DOC);
  // The marketer types straight away, on the canvas that still shows the earlier visit.
  mounted.typeOnCanvas("cta", "Too early");
  await mounted.flushCanvas();
  assert.equal(mounted.latest().saves.note, null, "never refused as 'moved on'");
  assert.equal(headingOf(server.site), "Written while away", "nothing from the earlier visit was saved");
  assert.equal(server.staleBaseSaves, 0);
  server.release();
  await mounted.settle(12);
  assert.equal(headingOf(mounted.frame.getState().site), "Written while away", "the fresh read is what the canvas shows");
  mounted.typeOnCanvas("cta", "Book a call");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site, "cta"), "Book a call");
  assert.equal(headingOf(server.site), "Written while away");
  assert.equal(server.staleBaseSaves, 0);
  await mounted.unmount();
});

test("review K1-4: a refused save puts the canvas back to the server's copy, and nothing refused is sent again", async () => {
  const server = fakeServer();
  server.refuse = (site) => (headingOf(site) === "" ? "page.content.0(hero).heading: Too small" : null);
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "");
  await mounted.flushCanvas();
  await mounted.settle(12);
  assert.equal(mounted.latest().saves.error, "page.content.0(hero).heading: Too small");
  assert.equal(headingOf(mounted.frame.getState().site), "Old headline", "the canvas went back too");
  mounted.typeOnCanvas("cta", "Book a call");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site), "Old headline");
  assert.equal(headingOf(server.site, "cta"), "Book a call", "the next edit is saved, without the refused one");
  await mounted.unmount();
});

test("review K3-3: a reload after the session's own save does not wipe what the marketer is still typing", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "Hello wor");
  await mounted.flushCanvas();
  mounted.typeOnCanvas("hero", "Hello world, this is");
  mounted.latest().reload(); // the standalone route's poll saw the version move (our own save)
  await mounted.settle(12);
  assert.equal(headingOf(mounted.frame.getState().site), "Hello world, this is", "the pending typing is still on the canvas");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site), "Hello world, this is");
  await mounted.unmount();
});

test("a dock edit made right after a canvas edit is built on the canvas edit (never on a stale render)", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  await selectCta(mounted);
  mounted.typeOnCanvas("hero", "Typed on the canvas");
  mounted.frame.flushChange();
  // No settle between: the dock commits in the same moment the canvas edit arrives.
  await mounted.settle(1);
  mounted.latest().inspector.onCommit("heading", "From the dock");
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Typed on the canvas");
  assert.equal(headingOf(server.site, "cta"), "From the dock");
  assert.equal(headingOf(mounted.frame.getState().site, "cta"), "From the dock");
  await mounted.unmount();
});

test("StrictMode: the whole session still saves", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server, { strict: true });
  mounted.typeOnCanvas("hero", "Under StrictMode");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site), "Under StrictMode");
  await mounted.unmount();
});
