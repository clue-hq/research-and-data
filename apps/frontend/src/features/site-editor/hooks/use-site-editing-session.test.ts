import assert from "node:assert/strict";
import test from "node:test";
import { DOC, fakeServer, headingOf, mountSiteSession, startSite, withHeading } from "./testing/site-session-bridge";

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

// Unsaved work (2026-10-14, the founder's live walk): typing, then reloading without leaving the text
// box, lost the typing with no warning. While the frame holds work it has not sent, or a save is
// still on its way (for any site this tab edited), leaving the page asks first.
test("leaving the page asks first while the frame holds unsent typing, and not once it is saved", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  assert.equal(mounted.leaveAsks(), false, "nothing to lose");
  mounted.frame.noteTyping();
  await mounted.settle();
  assert.equal(mounted.leaveAsks(), true, "typing not yet written into the page");
  mounted.typeOnCanvas("hero", "Typed, not left");
  await mounted.runFrameTimers();
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Typed, not left", "the pause sent it without leaving the box");
  assert.equal(mounted.leaveAsks(), false);
  await mounted.unmount();
});

test("leaving the page asks first while a save is on its way, even for a site no longer open", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  server.hold.save = true;
  mounted.typeOnCanvas("hero", "Saving slowly");
  await mounted.flushCanvas();
  assert.equal(mounted.leaveAsks(), true, "the save has not landed");
  await mounted.open(null);
  assert.equal(mounted.leaveAsks(), true, "it is still on its way after the site is closed");
  server.release("save");
  await mounted.settle(12);
  assert.equal(mounted.leaveAsks(), false);
  assert.equal(headingOf(server.site), "Saving slowly");
  await mounted.unmount();
});

test("a frame that reboots or is given another document has nothing pending", async () => {
  const server = fakeServer();
  const other = fakeServer(startSite({ hero: "Doc two" }), 9);
  const mounted = await mountSiteSession(server, { otherDocument: other });
  mounted.frame.noteTyping();
  await mounted.settle();
  assert.equal(mounted.leaveAsks(), true);
  await mounted.open("doc-2");
  assert.equal(mounted.leaveAsks(), false, "the new document's init dropped the old typing");
  await mounted.unmount();
});


// Review finding K3-1 (founder, 2026-10-14: fixes 1 and 2). Agent-written section code runs in the
// editor frame and can send the frame's messages. (1) The frame may ask for undo or redo only while
// the marketer is editing; the app's own ⌘Z and menu, and the agent's own tools, are unaffected.
// (2) A different site gets a fresh frame, so one site's code cannot act on the next.
test("K3-1 fix 1: while the marketer previews, the canvas cannot undo; the app's own ⌘Z still can", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "Edited");
  await mounted.flushCanvas();
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Edited");
  await mounted.setEditing(false);
  mounted.frame.shortcut("undo");
  mounted.frame.shortcut("redo");
  await mounted.settle(12);
  assert.equal(server.log.some((line) => line.startsWith("UNDO") || line.startsWith("REDO")), false, "the canvas changed nothing");
  assert.equal(headingOf(server.site), "Edited");
  globalThis.window.dispatchEvent(new globalThis.window.KeyboardEvent("keydown", { key: "z", metaKey: true }));
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Old headline", "the marketer's own ⌘Z in the app still undoes");
  await mounted.unmount();
});

test("K3-1 fix 2: a different site gets a fresh frame, and the old frame's messages are ignored", async () => {
  const server = fakeServer();
  const other = fakeServer(startSite({ hero: "Doc two" }), 9);
  const mounted = await mountSiteSession(server, { otherDocument: other });
  const firstFrame = mounted.frame;
  const firstSrc = mounted.latest().stage.canvas.src;
  await mounted.open("doc-2");
  assert.notEqual(mounted.latest().stage.canvas.src, firstSrc, "a new frame address (and secret)");
  assert.notEqual(mounted.frame, firstFrame);
  assert.equal(headingOf(mounted.frame.getState().site), "Doc two");
  // Code left behind in the first frame tries to act: an undo and a save.
  firstFrame.shortcut("undo");
  firstFrame.pageEdited("/", withHeading(firstFrame.getState().site!, "hero", "Forged").pages["/"]);
  firstFrame.flushChange();
  await mounted.settle(12);
  assert.deepEqual(other.log, [], "nothing reached the open site");
  assert.deepEqual(server.log, [], "nor the one it came from");
  // The new frame works as usual.
  mounted.typeOnCanvas("hero", "Typed on doc two");
  await mounted.flushCanvas();
  await mounted.settle(12);
  assert.equal(headingOf(other.site), "Typed on doc two");
  await mounted.unmount();
});

test("K3-1 fix 2: leaving a site and coming back to the same one keeps its frame", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  const frame = mounted.frame;
  const src = mounted.latest().stage.canvas.src;
  await mounted.open(null);
  await mounted.open(DOC);
  assert.equal(mounted.latest().stage.canvas.src, src);
  assert.equal(mounted.frame, frame);
  await mounted.unmount();
});

// External links (founder, 2026-10-14): a link to another website, clicked in the preview, opens in
// a new browser tab. The frame cannot open tabs (its sandbox allows no popups), so it asks the app,
// which opens only http(s) addresses, cut off from the app (noopener), and only right after a real
// click by the person — so section code cannot open tabs on its own.
test("an external link clicked in the preview opens in a new tab, only after a real click", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  const opened: unknown[][] = [];
  const view = globalThis.window as unknown as { open: (...args: unknown[]) => null };
  view.open = (...args: unknown[]) => {
    opened.push(args);
    return null;
  };
  const activation = (isActive: boolean) =>
    Object.defineProperty(globalThis.window.navigator, "userActivation", { configurable: true, value: { isActive } });
  await mounted.setEditing(false);
  activation(true);
  mounted.frame.linkClicked("https://example.com/pricing");
  await mounted.settle();
  assert.deepEqual(opened, [["https://example.com/pricing", "_blank", "noopener,noreferrer"]]);
  activation(false);
  mounted.frame.linkClicked("https://example.com/again");
  await mounted.settle();
  assert.equal(opened.length, 1, "no real click just now: nothing opens");
  await mounted.unmount();
});

// Review finding S2b-1: an image upload that finished after a tab switch was placed into whichever
// site was open by then — another account's site, saved as its next version. Every image target now
// names its site, and the session places an image only on the site it was meant for; the picture is
// still in the library, and the marketer is told.
test("S2b-1: an upload that finishes after switching sites is never placed on the other site", async () => {
  const server = fakeServer();
  const other = fakeServer(startSite({ hero: "Doc two" }), 9);
  const mounted = await mountSiteSession(server, { otherDocument: other });
  mounted.frame.componentSelected("hero", "FeatureSplit", [{ kind: "image", label: "Image", name: "image" }], { image: "" });
  await mounted.settle();
  const field = mounted.latest().imageField("image", "");
  assert.ok(field, "the hero's image field");
  const release = mounted.holdNextUpload();
  const uploading = field.onFileSelect(new File(["x"], "photo.png", { type: "image/png" })).catch(() => "refused");
  await mounted.settle();
  await mounted.open("doc-2");
  release();
  assert.equal(await uploading, "refused");
  await mounted.settle(12);
  assert.equal(other.log.filter((line) => line.startsWith("PUT")).length, 0, "Umbrella's site is untouched");
  assert.equal(server.log.filter((line) => line.startsWith("PUT")).length, 0);
  assert.match(mounted.latest().saves.error ?? "", /library/, "the marketer is told where the picture went");
  await mounted.unmount();
});

test("S2b-1: an upload that finishes on the same site is placed and saved", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.frame.componentSelected("hero", "FeatureSplit", [{ kind: "image", label: "Image", name: "image" }], { image: "" });
  await mounted.settle();
  await mounted.latest().imageField("image", "")!.onFileSelect(new File(["x"], "photo.png", { type: "image/png" }));
  await mounted.settle(12);
  const hero = server.site.pages["/"].content.find((entry) => entry.props.id === "hero")!;
  assert.equal(hero.props.image, `/asset-store/${"c".repeat(64)}`);
  await mounted.unmount();
});

// Review finding S2b-6: ⌘Z anywhere on the chat page undid the open site on the server, even with the
// site hidden behind another surface or the panel closed (one step can be a whole agent turn).
test("S2b-6: ⌘Z undoes the site only while it is on screen", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  mounted.typeOnCanvas("hero", "Edited");
  await mounted.flushCanvas();
  await mounted.settle(12);
  const pressUndo = () => globalThis.window.dispatchEvent(new globalThis.window.KeyboardEvent("keydown", { key: "z", metaKey: true }));
  await mounted.setOnScreen(false);
  pressUndo();
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Edited", "hidden: nothing undone");
  await mounted.setOnScreen(true);
  pressUndo();
  await mounted.settle(12);
  assert.equal(headingOf(server.site), "Old headline", "on screen: undone");
  await mounted.unmount();
});


// Review finding S2b-8: the brand carries the cloned sections a site can show, and the server builds
// it from the site it holds (only the clones the site places). An undo that brings back a
// clone the current site had replaced must show that clone, not "Choose a cloned section": the
// editor reads the brand again, and the frame is given the new one.
test("review S2b-8: undo bringing back a cloned section gives the frame a brand that has it", async () => {
  const clone = { id: "frag_0123456789abcdef", label: "Closing band", page_url: "https://seller.example/", html: "<section></section>", css: "", slots: {}, wrapper_class: "w" };
  const withClone = startSite();
  withClone.pages["/"].content.push({ type: "ClonedSection", props: { id: "close", fragmentId: clone.id, slots: {}, replacements: [], links: [] } });
  const server = fakeServer(startSite());
  server.undo = [withClone];
  server.brandFor = (site) => {
    const uses = site.pages["/"].content.some((item) => item.type === "ClonedSection");
    return { slug: "x", kit: { tokens: {} }, fonts: [], assets: {}, clones: uses ? { [clone.id]: clone } : {} } as never;
  };
  const mounted = await mountSiteSession(server);
  await mounted.settle();
  assert.equal(mounted.frame.getState().brand?.clones[clone.id], undefined, "the current site uses no clone");
  await mounted.pressUndo();
  await mounted.settle(12);
  assert.ok(mounted.frame.getState().site?.pages["/"].content.some((item) => item.type === "ClonedSection"), "the undone site is shown");
  assert.ok(mounted.frame.getState().brand?.clones[clone.id], "the frame's brand has the clone the undone site shows");
  await mounted.unmount();
});

test("review S2b-8: a reload that brings no new clone does not read the brand again", async () => {
  const server = fakeServer(startSite());
  const mounted = await mountSiteSession(server);
  await mounted.settle();
  const reads = server.brandReads;
  server.outsideWrite(withHeading(server.site, "hero", "An agent's heading"));
  await mounted.pressUndo();
  await mounted.settle(12);
  assert.equal(server.brandReads, reads);
  await mounted.unmount();
});

// Site element inspector (plan 1): selecting a text element and styling it.
const TYPO = { color: "#014036", fontFamily: "Inter", fontSize: 32, fontWeight: 400, italic: false, underline: false, textAlign: "left" as const };
function describeHeading(mounted: Awaited<ReturnType<typeof mountSiteSession>>) {
  mounted.frame.attachDescriber((_target, _componentId, key) => ({
    element: key === "heading" ? { key, kind: "text", label: "Talk to us", computed: TYPO } : null,
    elements: [{ key: "heading", kind: "text", label: "Talk to us" }],
  }));
}

test("a selected text element reaches the inspector, and a style commit is one save with the section's _edits", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server);
  describeHeading(mounted);
  mounted.frame.elementClicked("/", "cta", "heading");
  await selectCta(mounted);
  const inspector = mounted.latest().inspector;
  assert.equal(inspector.element?.key, "heading");
  assert.equal(inspector.elementOverride, null);
  assert.ok(inspector.layers.some((row) => row.elementKey === "heading" && row.active));
  const accepted = () => server.log.filter((entry) => entry.startsWith("PUT") && entry.includes("->")).length;
  const saves = accepted();
  inspector.onStyleCommit("heading", { italic: true, fontSize: 48 });
  await mounted.settle(12);
  const cta = server.site.pages["/"].content.find((item) => item.props.id === "cta")!;
  assert.deepEqual(cta.props._edits, { heading: { italic: true, fontSize: 48 } });
  assert.equal(accepted(), saves + 1, server.log.join("\n"));
  assert.deepEqual(mounted.latest().inspector.elementOverride, { italic: true, fontSize: 48 });
  await mounted.unmount();
});

test("while the agent-run lock holds, a style commit sends and saves nothing", async () => {
  const server = fakeServer();
  const mounted = await mountSiteSession(server, { locked: true });
  describeHeading(mounted);
  mounted.frame.elementClicked("/", "cta", "heading");
  await selectCta(mounted);
  const before = structuredClone(server.site);
  mounted.latest().inspector.onStyleCommit("heading", { italic: true });
  await mounted.settle(12);
  assert.deepEqual(server.site, before);
  assert.equal(mounted.latest().inspector.disabled, true);
  await mounted.unmount();
});

// Plan 4: a move among neighbours is one save and one undo step, and the selection follows the moved
// element to its new key; Hide on a header part is one save too.
test("moving a stat is one save and one undo step, and the selection follows it", async () => {
  const start = startSite();
  const cta = start.pages["/"].content.find((item) => item.props.id === "cta")!;
  cta.props = { ...cta.props, stats: [{ value: "7%", label: "less" }, { value: "2x", label: "more" }] };
  const server = fakeServer(start);
  const mounted = await mountSiteSession(server);
  const arrangeOf = (key: string) => ({ item: key, parent: "stats", siblings: ["stats.0", "stats.1"] });
  const BOX = { fill: "", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 400 };
  mounted.frame.attachDescriber((_target, _componentId, key) => ({
    element: key?.startsWith("stats.")
      ? { key, kind: "container", label: "Card", computed: TYPO, container: { ...BOX, gap: 0, layout: "text", contentAlign: "start", name: "Card" }, arrange: arrangeOf(key) }
      : null,
    elements: [{ key: "stats.0", kind: "container", label: "Card", parent: null }, { key: "stats.1", kind: "container", label: "Card", parent: null }],
  }));
  mounted.frame.elementClicked("/", "cta", "stats.1");
  await selectCta(mounted);
  const inspector = mounted.latest().inspector;
  assert.deepEqual(inspector.arrange, { canUp: true, canDown: false, note: null });
  const undo = server.undo.length;
  inspector.onMove("up");
  await mounted.settle(12);
  const stored = server.site.pages["/"].content.find((item) => item.props.id === "cta")!;
  assert.deepEqual(stored.props.stats, [{ value: "2x", label: "more" }, { value: "7%", label: "less" }]);
  assert.equal(server.undo.length, undo + 1, "one save, one undo step");
  assert.equal(mounted.latest().inspector.element?.key, "stats.0", "the selection follows the moved stat");
  await mounted.unmount();
});

test("review I6: two quick presses of Move up take the third stat to the top", async () => {
  const start = startSite();
  const cta = start.pages["/"].content.find((item) => item.props.id === "cta")!;
  cta.props = { ...cta.props, stats: [{ value: "a" }, { value: "b" }, { value: "c" }] };
  const server = fakeServer(start);
  const mounted = await mountSiteSession(server);
  const BOX = { fill: "", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 400 };
  mounted.frame.attachDescriber((_target, _componentId, key) => ({
    element: key?.startsWith("stats.")
      ? { key, kind: "container", label: "Card", computed: TYPO, container: { ...BOX, gap: 0, layout: "text", contentAlign: "start", name: "Card" }, arrange: { item: key, parent: "stats", siblings: ["stats.0", "stats.1", "stats.2"] } }
      : null,
    elements: ["stats.0", "stats.1", "stats.2"].map((k) => ({ key: k, kind: "container" as const, label: "Card", parent: null })),
  }));
  mounted.frame.elementClicked("/", "cta", "stats.2");
  await selectCta(mounted);
  const inspector = mounted.latest().inspector;
  inspector.onMove("up");
  inspector.onMove("up"); // before the canvas reports the first move back
  await mounted.settle(12);
  const stored = server.site.pages["/"].content.find((item) => item.props.id === "cta")!;
  assert.deepEqual(stored.props.stats, [{ value: "c" }, { value: "a" }, { value: "b" }]);
  assert.equal(mounted.latest().inspector.element?.key, "stats.0");
  await mounted.unmount();
});

// Plan 5: an image's alt text typed in the panel is one save and one undo step.
test("an image's alt text is one save and one undo step", async () => {
  const start = startSite();
  const hero = start.pages["/"].content.find((item) => item.props.id === "hero")!;
  hero.props = { ...hero.props, image: "/brands/x.png" };
  const server = fakeServer(start);
  const mounted = await mountSiteSession(server);
  const BOX = { fill: "", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 400 };
  mounted.frame.attachDescriber((_target, _componentId, key) => ({
    element: key === "image"
      ? { key, kind: "image", label: "Image", computed: TYPO, image: { media: "img", box: BOX, fit: null, fitMatters: false, alt: "", src: "/brands/x.png" }, imageSource: { kind: "prop", prop: "image", uses: 1 }, altSource: { kind: "prop", prop: "imageAlt" } }
      : null,
    elements: [{ key: "image", kind: "image", label: "Image", parent: null }],
  }));
  mounted.frame.elementClicked("/", "hero", "image");
  mounted.frame.componentSelected("hero", "FeatureSplit", [], { heading: "Old headline" });
  await mounted.settle();
  const inspector = mounted.latest().inspector;
  assert.equal(inspector.imageAlt, "");
  assert.deepEqual(inspector.imageReplace, { prop: "image", uses: 1 });
  const undo = server.undo.length;
  assert.equal(inspector.onImageAltCommit("A quiet clinic"), null);
  await mounted.settle(12);
  assert.equal(server.site.pages["/"].content.find((item) => item.props.id === "hero")!.props.imageAlt, "A quiet clinic");
  assert.equal(server.undo.length, undo + 1);
  assert.equal(mounted.latest().inspector.onImageAltCommit("x".repeat(301)), "Alt text is plain text of at most 300 characters, with no line breaks.");
  await mounted.unmount();
});
