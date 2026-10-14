import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { appToFrame, type FrameToAppType } from "@clue/site-kit/editor-protocol";
import { pageFor } from "@clue/site-kit/editor-site";
import { SiteDocumentSchema, type SiteDocument, type SitePage } from "@clue/site-kit/site-document";
import { FrameController, type PuckHandle } from "../src/client/frame-controller";
import type { LoadedSection } from "../src/client/sections";

const NONCE = "nonce-0123456789abcdef";
const brand = { slug: "x", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } as unknown as BrandData;
const page = (heading: string): SitePage => ({
  root: { props: { title: "Home" } },
  content: [{ type: "CtaBand", props: { id: "cta", heading } }],
});
const site = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "S",
  theme: {},
  pages: { "/": page("Hello"), "/analysis": { root: { props: { title: "Analysis" } }, content: [] } },
  shell: { header: { id: "header", preparedFor: "SCSD" }, footer: { id: "footer", legal: "©" } },
  agent_sections: {},
});
const init = (overrides: Record<string, unknown> = {}) =>
  appToFrame(
    "init",
    { brand, device: "Desktop", mode: "edit", route: "/", rev: 1, sections: [], site, ...overrides } as never,
    { documentId: "doc_1", nonce: NONCE },
  );

function harness(loadSections: () => Promise<LoadedSection[]> = async () => []) {
  const posts: { type: FrameToAppType; payload: unknown; documentId: string }[] = [];
  const timers: (() => void)[] = [];
  const puckCalls: string[] = [];
  const controller = new FrameController({
    cancel: () => undefined,
    loadSections,
    post: (type, payload, documentId) => posts.push({ documentId, payload, type }),
    schedule: (run) => {
      timers.push(run);
      return timers.length;
    },
  });
  const puck: PuckHandle = {
    select: (id) => puckCalls.push(`select:${id}`),
    setMode: (mode) => puckCalls.push(`mode:${mode}`),
    showPage: (shown) => puckCalls.push(`show:${String(shown.content[0]?.props.heading ?? "")}`),
  };
  controller.attachPuck(puck);
  controller.setShellFields({ footer: [{ kind: "text", label: "Legal", name: "legal" }], header: [{ kind: "text", label: "Prepared for", name: "preparedFor" }] });
  const types = () => posts.map((post) => post.type);
  return { controller, posts, puckCalls, timers, types };
}

test("boot says ready with no document; init loads, renders and says navigated for that document", async () => {
  const h = harness();
  h.controller.announceReady();
  await h.controller.receive(init());
  assert.deepEqual(h.types(), ["ready", "navigated"]);
  assert.equal(h.posts[0].documentId, "");
  assert.equal(h.posts[1].documentId, "doc_1");
  assert.equal(h.controller.getState().status, "ready");
  assert.equal(h.controller.getState().route, "/");
});

test("an init whose route is not a page falls back to the home page", async () => {
  const h = harness();
  await h.controller.receive(init({ route: "/gone" }));
  assert.deepEqual(h.posts.at(-1), { documentId: "doc_1", payload: { route: "/" }, type: "navigated" });
});

test("a section that does not load fails the init with a typed error", async () => {
  const h = harness(async () => {
    throw new Error("AnalysisSteps did not load");
  });
  await h.controller.receive(init());
  assert.equal(h.controller.getState().status, "failed");
  assert.deepEqual(h.posts.at(-1)?.payload, { code: "section_load_failed", message: "AnalysisSteps did not load" });
});

test("a user edit is posted once, after the debounce, with the whole site", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Edited once"));
  h.controller.pageEdited("/", page("Edited twice"));
  assert.equal(h.types().includes("changed"), false);
  h.timers.at(-1)?.();
  const changed = h.posts.filter((post) => post.type === "changed");
  assert.equal(changed.length, 1);
  const sent = (changed[0].payload as { site: typeof site }).site;
  assert.equal(sent.pages["/"].content[0].props.heading, "Edited twice");
  assert.equal(sent.pages["/analysis"].root.props.title, "Analysis", "the other pages ride along unchanged");
});

test("an echo of the page as it already is posts nothing; preview mode never posts edits", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Hello"));
  assert.equal(h.timers.length, 0);
  await h.controller.receive(appToFrame("set_mode", { mode: "preview" }, { documentId: "doc_1", nonce: NONCE }));
  h.controller.pageEdited("/", page("Typed in preview"));
  assert.equal(h.timers.length, 0);
});

test("leaving edit mode, switching page or a shortcut flushes a pending edit first", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Pending"));
  h.controller.shortcut("undo");
  assert.deepEqual(h.types().filter((type) => type !== "pending").slice(-2), ["changed", "shortcut"]);
});

test("the app's own edits re-render the page without echoing a change back", async () => {
  const h = harness();
  await h.controller.receive(init());
  await h.controller.receive(
    appToFrame("set_props", { componentId: "cta", props: { heading: "From the dock" }, route: "/", rev: 2 }, { documentId: "doc_1", nonce: NONCE }),
  );
  assert.deepEqual(h.puckCalls.at(-1), "show:From the dock");
  h.controller.pageEdited("/", h.controller.getState().site!.pages["/"]);
  assert.equal(h.types().includes("changed"), false);
});

test("an agent reload replaces the site, drops an unsent edit, and keeps the page", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Unsent"));
  const agent = { ...site, pages: { ...site.pages, "/": page("Agent wrote this") } };
  await h.controller.receive(appToFrame("replace_site", { site: agent, rev: 9 }, { documentId: "doc_1", nonce: NONCE }));
  h.timers.forEach((run) => run());
  assert.equal(h.types().includes("changed"), false, "the server's version wins over an unsent edit");
  assert.equal(h.puckCalls.at(-1), "show:Agent wrote this");
});

test("the header is selected through the shell target with its own fields", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.shellSelected("header");
  assert.deepEqual(h.posts.at(-1)?.payload, {
    componentId: "header",
    componentType: "SiteHeader",
    fields: [{ kind: "text", label: "Prepared for", name: "preparedFor" }],
    props: { id: "header", preparedFor: "SCSD" },
    route: "shell",
  });
  h.controller.componentDeselected();
  assert.equal(h.types().at(-1), "selected", "Puck clearing its own selection does not clear the shell's");
});

test("a site link in preview switches page; an outside link does nothing", async () => {
  const h = harness();
  await h.controller.receive(init({ mode: "preview" }));
  h.controller.linkClicked("https://garnerhealth.com");
  assert.equal(h.types().at(-1), "navigated");
  assert.equal(h.posts.filter((post) => post.type === "navigated").length, 1);
  h.controller.linkClicked("/analysis");
  assert.deepEqual(h.posts.at(-1)?.payload, { route: "/analysis" });
  assert.equal(h.controller.getState().route, "/analysis");
});

// The sync fix (2026-10-14). The frame shows the app's working copy and proposes edits stamped with
// the revision they started from.
const ctx = { documentId: "doc_1", nonce: NONCE };
const headingOf = (value: SiteDocument | null) => String(pageFor(value!, "/")!.content[0].props.heading);
const withHeading = (heading: string) => SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": page(heading) } });

test("review K3-5: an update that arrives while sections load is applied after the load, not dropped", async () => {
  let release!: () => void;
  const h = harness(() => new Promise<LoadedSection[]>((resolve) => { release = () => resolve([]); }));
  const loading = h.controller.receive(init({ rev: 4 }));
  await h.controller.receive(appToFrame("replace_site", { site: withHeading("v5 heading"), rev: 5 }, ctx));
  // set_props carries a section's whole props (the dock commits over the app's copy).
  await h.controller.receive(appToFrame("set_props", { componentId: "cta", props: { eyebrow: "from the dock", heading: "v5 heading", id: "cta" }, route: "/", rev: 6 }, ctx));
  await h.controller.receive(appToFrame("navigate", { route: "/analysis" }, ctx));
  release();
  await loading;
  const state = h.controller.getState();
  assert.equal(state.rev, 6);
  assert.equal(headingOf(state.site), "v5 heading");
  assert.equal(pageFor(state.site!, "/")!.content[0].props.eyebrow, "from the dock");
  assert.equal(state.route, "/analysis");
  assert.deepEqual(h.posts.at(-1), { documentId: "doc_1", payload: { route: "/analysis" }, type: "navigated" });
});

test("a proposal names the revision it started from; consecutive proposals share it", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 7 }));
  h.controller.pageEdited("/", page("first"));
  h.timers.at(-1)!();
  h.controller.pageEdited("/", page("first and second"));
  h.timers.at(-1)!();
  const changed = h.posts.filter((post) => post.type === "changed").map((post) => post.payload as { site: SiteDocument; baseRev: number });
  assert.deepEqual(changed.map((proposal) => [headingOf(proposal.site), proposal.baseRev]), [["first", 7], ["first and second", 7]]);
});

test("a dock patch to another part keeps the marketer's unsent typing, and the next proposal starts from its revision", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 7 }));
  h.controller.pageEdited("/", page("typed"));
  await h.controller.receive(appToFrame("set_props", { componentId: "header", props: { preparedFor: "From the dock" }, route: "shell", rev: 8 }, ctx));
  h.timers.at(-1)!();
  const proposal = h.posts.find((post) => post.type === "changed")!.payload as { site: SiteDocument; baseRev: number };
  assert.equal(proposal.baseRev, 8);
  assert.equal(headingOf(proposal.site), "typed");
  assert.equal(proposal.site.shell!.header.preparedFor, "From the dock");
});

test("a different whole copy wins over unsent typing; the copy the frame already shows only moves the revision", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 1 }));
  h.controller.pageEdited("/", page("typed"));
  const shown = h.controller.getState().site!;
  await h.controller.receive(appToFrame("replace_site", { site: shown, rev: 2 }, ctx));
  assert.equal(h.controller.getState().rev, 2);
  h.timers.at(-1)!();
  const first = h.posts.filter((post) => post.type === "changed");
  assert.equal(first.length, 1, "the typing is still sent");
  assert.equal((first[0].payload as { baseRev: number }).baseRev, 2);
  h.controller.pageEdited("/", page("typed again"));
  await h.controller.receive(appToFrame("replace_site", { site: withHeading("from the server"), rev: 3 }, ctx));
  h.timers.forEach((run) => run());
  assert.equal(h.posts.filter((post) => post.type === "changed").length, 1, "the dropped typing is never sent");
  assert.equal(headingOf(h.controller.getState().site), "from the server");
  assert.equal(h.controller.getState().rev, 3);
});

test("review S2a-4: an outside copy keeps the selection on the same section id and tells Puck which one", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 1 }));
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const shown: (string | null)[] = [];
  h.controller.attachPuck({ select: () => undefined, setMode: () => undefined, showPage: (_page, selectedId) => shown.push(selectedId) });
  await h.controller.receive(appToFrame("replace_site", { site: withHeading("World"), rev: 2 }, ctx));
  await h.controller.receive(appToFrame("set_props", { componentId: "cta", props: { heading: "Dock", id: "cta" }, route: "/", rev: 3 }, ctx));
  assert.deepEqual(shown, ["cta", "cta"]);
  assert.deepEqual(h.controller.getState().selection, { componentId: "cta", target: "/" });
});

test("an outside copy without the selected section clears the selection and tells Puck nothing is selected", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 1 }));
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const shown: (string | null)[] = [];
  h.controller.attachPuck({ select: () => undefined, setMode: () => undefined, showPage: (_page, selectedId) => shown.push(selectedId) });
  const without = SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": { root: { props: { title: "Home" } }, content: [] } } });
  await h.controller.receive(appToFrame("replace_site", { site: without, rev: 2 }, ctx));
  assert.deepEqual(shown, [null]);
  assert.equal(h.controller.getState().selection, null);
  assert.equal(h.types().at(-1), "deselected");
});

test("re-describing the selected section after an outside copy posts selected even for the same id", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 1 }));
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const before = h.types().filter((type) => type === "selected").length;
  h.controller.reselected("cta", "StatsBand", [{ kind: "text", label: "Heading", name: "heading" }], { heading: "World" });
  const selected = h.posts.filter((post) => post.type === "selected");
  assert.equal(selected.length, before + 1);
  assert.equal((selected.at(-1)!.payload as { componentType: string }).componentType, "StatsBand");
});

// Sync-fix review F2: a proposal the app refused because its own patch (a dock edit, an image placed)
// overtook it must not be lost while the canvas keeps showing the typing: a patch at a newer revision
// than the last proposal's base makes the frame propose again, from the patch's revision.
test("review F2: a patch that overtakes a sent proposal makes the frame propose again from the patch's revision", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 7 }));
  h.controller.pageEdited("/", page("typed and flushed"));
  h.timers.at(-1)!();
  await h.controller.receive(appToFrame("set_props", { componentId: "header", props: { preparedFor: "From the dock" }, route: "shell", rev: 8 }, ctx));
  assert.ok(h.timers.length >= 2, "a re-proposal is scheduled");
  h.timers.at(-1)!();
  const proposals = h.posts.filter((post) => post.type === "changed").map((post) => post.payload as { site: SiteDocument; baseRev: number });
  assert.deepEqual(proposals.map((proposal) => proposal.baseRev), [7, 8]);
  assert.equal(headingOf(proposals[1].site), "typed and flushed");
  assert.equal(proposals[1].site.shell!.header.preparedFor, "From the dock");
});

test("a patch with no proposal outstanding, or one already re-based, proposes nothing", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 7 }));
  await h.controller.receive(appToFrame("set_props", { componentId: "header", props: { preparedFor: "Dock" }, route: "shell", rev: 8 }, ctx));
  assert.equal(h.timers.length, 0);
  h.controller.pageEdited("/", page("typed"));
  h.timers.at(-1)!();
  await h.controller.receive(appToFrame("replace_site", { site: withHeading("from the server"), rev: 9 }, ctx));
  await h.controller.receive(appToFrame("set_props", { componentId: "header", props: { preparedFor: "Dock again" }, route: "shell", rev: 10 }, ctx));
  h.timers.forEach((run) => run());
  assert.equal(h.posts.filter((post) => post.type === "changed").length, 1, "a replaced copy ended the outstanding proposal");
});

// Unsaved work (2026-10-14, founder's live walk): a reload while the marketer was still in a text
// box lost what they typed, with no warning. The frame tells the app whenever it holds work it has
// not sent yet — typing not yet written, or an edit waiting out its pause — so the app can ask before
// the page goes.
const pendingPosts = (h: ReturnType<typeof harness>) =>
  h.posts.filter((post) => post.type === "pending").map((post) => (post.payload as { pending: boolean }).pending);

test("typing is pending at once, stays pending through the send, and clears once the typing has settled", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.noteTyping();
  h.controller.noteTyping();
  assert.deepEqual(pendingPosts(h), [true], "said once, on the first keystroke");
  const settled = h.timers.length - 1;
  h.controller.pageEdited("/", page("Hello there"));
  h.controller.flushChange();
  assert.equal(h.types().filter((type) => type === "changed").length, 1);
  assert.deepEqual(pendingPosts(h), [true], "typing may still be on its way into the page");
  h.timers[settled - 1]!();
  assert.deepEqual(pendingPosts(h), [true], "an earlier keystroke's timer changes nothing");
  h.timers[settled]!();
  assert.deepEqual(pendingPosts(h), [true, false]);
});

test("a page edit without typing (a drag, a field) is pending until it is sent", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Moved"));
  assert.deepEqual(pendingPosts(h), [true]);
  h.controller.flushChange();
  assert.deepEqual(pendingPosts(h), [true, false]);
});

test("typing that has settled while its edit waits out the pause stays pending until the send", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.noteTyping();
  const settled = h.timers.length - 1;
  h.controller.pageEdited("/", page("Typed"));
  h.timers[settled]!();
  assert.deepEqual(pendingPosts(h), [true]);
  h.controller.flushChange();
  assert.deepEqual(pendingPosts(h), [true, false]);
});

test("a different copy from the app drops the unsent typing, so nothing is pending any more", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.noteTyping();
  h.controller.pageEdited("/", page("Unsent"));
  const other = SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": page("The agent wrote this") } });
  await h.controller.receive(appToFrame("replace_site", { site: other, rev: 2 }, { documentId: "doc_1", nonce: NONCE }));
  assert.deepEqual(pendingPosts(h), [true, false]);
});

test("in preview nothing is typed, so nothing is pending; leaving edit sends what was pending", async () => {
  const h = harness();
  await h.controller.receive(init({ mode: "preview" }));
  h.controller.noteTyping();
  assert.deepEqual(pendingPosts(h), []);
  await h.controller.receive(appToFrame("set_mode", { mode: "edit" }, { documentId: "doc_1", nonce: NONCE }));
  h.controller.pageEdited("/", page("Edited"));
  await h.controller.receive(appToFrame("set_mode", { mode: "preview" }, { documentId: "doc_1", nonce: NONCE }));
  assert.equal(h.types().includes("changed"), true);
  assert.deepEqual(pendingPosts(h), [true, false]);
});

test("a new document starts with nothing pending, and its first keystroke says so again", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.noteTyping();
  await h.controller.receive(init());
  assert.deepEqual(pendingPosts(h), [true], "the app forgets the old document's state when it inits");
  h.controller.noteTyping();
  assert.deepEqual(pendingPosts(h), [true, true]);
});
