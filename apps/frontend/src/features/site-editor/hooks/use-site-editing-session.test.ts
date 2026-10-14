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

test("review S2b-3, GET answers first: a reload read before our save landed waits for the save, then re-reads", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "New headline");
  await mounted.flushCanvas();
  server.hold.get = true;
  mounted.latest().stage.url.reload();
  await mounted.settle();
  server.release("get"); // the GET (read v5, while the save is still with the validator) answers first
  await mounted.settle();
  assert.equal(headingOf(mounted.latest().site), "New headline", "the load is deferred, never adopted mid-save");
  server.release("save"); // then the save lands as v6, and the deferred reload re-reads
  await mounted.settle(12);
  assert.equal(server.log.filter((line) => line.startsWith("GET")).length, 1, "the first read was held; the re-read was not");
  assert.equal(mounted.latest().saves.baseVersion, 6);
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
  server.release("save"); // the save lands first (v6)…
  await mounted.settle();
  server.release("get"); // …then the GET that read v5 answers
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
  server.release("get");
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

// Sync-fix review F1: between a landed undo (or a refusal) and its reload, the canvas still shows the
// old copy. Typing made there must neither re-apply what was undone nor resend what was refused.
test("review F1: canvas typing during an undo's reload never re-applies what was undone", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "Edit to undo");
  await mounted.flushCanvas();
  server.hold.get = true;
  await mounted.pressUndo(); // the undo lands as v7; its reload is slow
  mounted.typeOnCanvas("cta", "Typed during the reload");
  await mounted.flushCanvas();
  assert.equal(server.version, 7, "nothing was saved over the undo");
  server.release("get");
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Old headline", "the undo stands");
  assert.equal(server.redo.length, 1, "redo is still available");
  assert.equal(headingOf(mounted.frame.getState().site), "Old headline", "the canvas shows the undone copy");
  assert.equal(headingOf(mounted.frame.getState().site, "cta"), "Talk to us", "the typing in the window is dropped, once");
  mounted.typeOnCanvas("cta", "After the undo");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site, "cta"), "After the undo");
  assert.equal(headingOf(server.site), "Old headline");
  await mounted.unmount();
});

test("review F1: a refused edit is never sent again by typing made before its reload lands", async () => {
  const server = fakeServer();
  const asked: string[] = [];
  server.refuse = (site) => {
    asked.push(`hero=${JSON.stringify(headingOf(site))} cta=${headingOf(site, "cta")}`);
    return headingOf(site) === "" ? "page.content.0(hero).heading: Too small" : null;
  };
  const mounted = await mountSiteSession(server);
  server.hold.get = true;
  mounted.typeOnCanvas("hero", "");
  await mounted.flushCanvas(); // refused 422; the reload is slow
  mounted.typeOnCanvas("cta", "Typed before the reload landed");
  await mounted.flushCanvas();
  assert.deepEqual(asked, ['hero="" cta=Talk to us'], "the refused edit was not resent");
  server.release("get");
  await mounted.settle(12);
  assert.equal(headingOf(mounted.frame.getState().site), "Old headline");
  mounted.typeOnCanvas("cta", "Book a call");
  await mounted.flushCanvas();
  assert.equal(headingOf(server.site, "cta"), "Book a call");
  assert.equal(headingOf(server.site), "Old headline");
  await mounted.unmount();
});

test("review F2: flushed canvas typing overtaken by a dock edit is proposed again and saved, never shown-but-lost", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  await selectCta(mounted);
  mounted.typeOnCanvas("hero", "Typed on canvas");
  mounted.frame.flushChange(); // posted, not yet handled by the app…
  mounted.latest().inspector.onCommit("heading", "From the dock"); // …when the app's own edit moves the copy
  await mounted.settle(12);
  await mounted.flushCanvas(); // the frame's re-proposal (debounced) goes out
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Typed on canvas");
  assert.equal(headingOf(server.site, "cta"), "From the dock");
  assert.equal(headingOf(mounted.latest().site), "Typed on canvas");
  assert.equal(headingOf(mounted.frame.getState().site), "Typed on canvas");
  await mounted.unmount();
});

test("review F4: coming back while the last visit's save is still in flight waits for it; the next edit is never refused", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "Saved while leaving");
  await mounted.flushCanvas(); // the save is with the validator…
  await mounted.open(null); // …while the marketer looks at another tab…
  await mounted.open(DOC); // …and comes back before it lands
  server.release("save");
  await mounted.settle(16);
  assert.equal(headingOf(mounted.frame.getState().site), "Saved while leaving", "the canvas shows the saved edit");
  assert.equal(mounted.latest().saves.baseVersion, 6);
  mounted.typeOnCanvas("cta", "Book a call");
  await mounted.flushCanvas();
  assert.equal(mounted.latest().saves.note, null, "not refused as 'moved on'");
  assert.equal(headingOf(server.site), "Saved while leaving");
  assert.equal(headingOf(server.site, "cta"), "Book a call");
  await mounted.unmount();
});

// Follow-up to F4: a controller kept for a document you left must not act on the working copy, which
// by then holds the document you are looking at. Its queued save is refused while you are away; the
// refusal used to supersede (and reload) the OTHER document, dropping what you were typing there.
test("a save refused for the site you left never disturbs the site you are editing", async () => {
  const server = fakeServer();
  const other = fakeServer(startSite({ hero: "Doc two" }), 9);
  const mounted = await mountSiteSession(server, { otherDocument: other });
  server.refuse = (site) => (headingOf(site) === "Refused later" ? "page.content.0(hero).heading: Refused" : null);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "First");
  await mounted.flushCanvas();
  mounted.typeOnCanvas("hero", "Refused later");
  await mounted.flushCanvas(); // queued behind the held save
  await mounted.open("doc-2");
  assert.equal(headingOf(mounted.frame.getState().site), "Doc two");
  mounted.typeOnCanvas("hero", "Typing on doc two");
  server.release("save"); // the first save lands; the queued one is refused, on the site you left
  await mounted.settle(16);
  await mounted.flushCanvas();
  await mounted.settle(12);
  assert.equal(headingOf(other.site), "Typing on doc two", "the typing on the open site was saved");
  assert.equal(mounted.latest().saves.error, null, "the other site's refusal is not shown here");
  assert.equal(headingOf(server.site), "First");
  await mounted.unmount();
});
