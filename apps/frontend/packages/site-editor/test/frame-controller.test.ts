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
    select: (id, options) => puckCalls.push(options?.scroll === false ? `select-quiet:${id}` : `select:${id}`),
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

test("a page reported back with the same rich text spelled differently (& for &amp;, the editor's <p>) posts nothing", async () => {
  const h = harness();
  await h.controller.receive(init({ site: { ...site, pages: { ...site.pages, "/": page("Tom & Jerry") } } }));
  h.controller.pageEdited("/", page("<p>Tom &amp; Jerry</p>"));
  assert.equal(h.timers.length, 0, "no save of the same words");
});

test("rich text the editor or a paste wrote is saved in the grammar's form; its echo posts nothing", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page('<p style="text-align: center;">Hello <b>there</b></p><p>again</p>'));
  h.timers.at(-1)?.();
  const sent = (h.posts.filter((post) => post.type === "changed")[0].payload as { site: typeof site }).site;
  assert.equal(sent.pages["/"].content[0].props.heading, "Hello <strong>there</strong><br>again");
  const before = h.timers.length;
  h.controller.pageEdited("/", page("<p>Hello <strong>there</strong><br>again</p>"));
  assert.equal(h.timers.length, before, "the editor's own wrapper around the saved text is the same text");
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
    element: null,
    elements: [],
    fields: [{ kind: "text", label: "Prepared for", name: "preparedFor" }],
    props: { id: "header", preparedFor: "SCSD" },
    route: "shell",
  });
  h.controller.componentDeselected();
  assert.equal(h.types().at(-1), "selected", "Puck clearing its own selection does not clear the shell's");
});

test("a site link in preview switches page; an outside link never navigates the frame", async () => {
  const h = harness();
  await h.controller.receive(init({ mode: "preview" }));
  h.controller.linkClicked("https://garnerhealth.com");
  assert.equal(h.types().at(-1), "open_link", "it asks the app for a new tab (founder, 2026-10-14)");
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
  assert.deepEqual(h.controller.getState().selection, { componentId: "cta", elementKey: null, target: "/" });
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

// External links (founder, 2026-10-14): a link to another website clicked in the preview is handed
// to the app, which opens it in a new tab; the frame never navigates itself.
test("a link to another website asks the app to open it; a page of this site still switches page", async () => {
  const h = harness();
  await h.controller.receive(init({ mode: "preview" }));
  h.controller.linkClicked("https://example.com/pricing");
  assert.deepEqual(h.posts.at(-1), { documentId: "doc_1", payload: { href: "https://example.com/pricing" }, type: "open_link" });
  h.controller.linkClicked("/analysis");
  assert.deepEqual(h.posts.at(-1)?.type, "navigated");
  const before = h.posts.length;
  for (const href of ["javascript:alert(1)", "mailto:sales@example.com", "#top", "/not-a-page"]) h.controller.linkClicked(href);
  assert.equal(h.posts.length, before, "nothing else is opened");
});



// Site element inspector (plan 1): a selection may name one text element of the section.
const TYPO = { color: "#014036", fontFamily: "Garner Serif", fontSize: 48, fontWeight: 600, italic: false, underline: false, textAlign: "left" as const };
function elementHarness(known: string[] = ["heading", "body"]) {
  const h = harness();
  const asked: string[] = [];
  h.controller.attachDescriber((target, componentId, key) => {
    asked.push(`${target}#${componentId}:${key}`);
    const elements = known.map((k) => ({ key: k, kind: "text" as const, label: k }));
    const element = key && known.includes(key) ? { key, kind: "text" as const, label: key, computed: TYPO } : null;
    return { element, elements };
  });
  const selectedPayloads = () =>
    h.posts.filter((post) => post.type === "selected").map((post) => post.payload as { componentId: string; element: { key: string } | null; elements: unknown[] });
  return { ...h, asked, selectedPayloads };
}

test("a click on a text element of a new section selects the section with that element", async () => {
  const h = elementHarness();
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  assert.equal(h.selectedPayloads().length, 0, "nothing is posted until Puck selects the section");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "heading");
  assert.equal(h.selectedPayloads().at(-1)?.elements.length, 2);
  assert.deepEqual(h.controller.getState().selection, { componentId: "cta", elementKey: "heading", target: "/" });
});

test("another text element of the selected section is posted at once; the same one again posts nothing", async () => {
  const h = elementHarness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  h.controller.elementClicked("/", "cta", "heading");
  h.controller.elementClicked("/", "cta", "body");
  h.controller.elementClicked("/", "cta", "body");
  assert.deepEqual(h.selectedPayloads().map((p) => p.element?.key ?? null), [null, "heading", "body"]);
  h.controller.elementClicked("/", "cta", null);
  assert.equal(h.selectedPayloads().at(-1)?.element, null, "a click on no text selects the whole section again");
});

test("an element the section no longer has selects the whole section", async () => {
  const h = elementHarness(["body"]);
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  assert.equal(h.selectedPayloads().at(-1)?.element, null);
  assert.equal(h.controller.getState().selection?.elementKey, null);
});

test("the app's select may name an element: in the selected section at once, in another after Puck selects it", async () => {
  const h = elementHarness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  await h.controller.receive(appToFrame("select", { componentId: "cta", elementKey: "body", route: "/" }, ctx));
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "body");
  h.controller.componentDeselected();
  await h.controller.receive(appToFrame("select", { componentId: "cta", elementKey: "heading", route: "/" }, ctx));
  assert.ok(h.puckCalls.includes("select:cta"));
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "heading");
});

test("a header element is selected through the shell target", async () => {
  const h = elementHarness(["preparedFor"]);
  await h.controller.receive(init());
  h.controller.elementClicked("shell", "header", "preparedFor");
  h.controller.shellSelected("header");
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "preparedFor");
  assert.deepEqual(h.controller.getState().selection, { componentId: "header", elementKey: "preparedFor", target: "shell" });
  const count = h.selectedPayloads().length;
  h.controller.elementClicked("shell", "header", "preparedFor");
  h.controller.shellSelected("header");
  assert.equal(h.selectedPayloads().length, count, "the same element again posts nothing");
});

test("re-describing after an outside copy keeps the selected element when the section still has it", async () => {
  const h = elementHarness();
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "body");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  h.controller.reselected("cta", "CtaBand", [], { heading: "World" });
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "body");
});

test("a selection described while the canvas was still redrawing is re-described once it has settled", async () => {
  const h = harness();
  let settled = false;
  h.controller.attachDescriber((_target, _componentId, key) =>
    settled
      ? { element: key === "heading" ? { key, kind: "text", label: key, computed: TYPO } : null, elements: [{ key: "heading", kind: "text", label: "heading" }] }
      : { element: null, elements: [] },
  );
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const selected = () => h.posts.filter((post) => post.type === "selected").map((post) => post.payload as { element: { key: string } | null });
  assert.equal(selected().at(-1)?.element, null);
  settled = true;
  h.controller.refreshSelection();
  assert.equal(selected().at(-1)?.element?.key, "heading", "the element asked for is found once the canvas settles");
  assert.equal(h.controller.getState().selection?.elementKey, "heading");
  const count = selected().length;
  h.controller.refreshSelection();
  assert.equal(selected().length, count, "nothing changed: nothing is posted again");
});

test("a click on text in a section Puck did not select (a clone's editable text) selects the section, without scrolling", async () => {
  const h = elementHarness();
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  assert.ok(h.puckCalls.includes("select-quiet:cta"), h.puckCalls.join(","));
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  assert.equal(h.selectedPayloads().at(-1)?.element?.key, "heading");
});

test("an element whose look keeps changing (an animated colour) is not posted again on every frame", async () => {
  const h = harness();
  let shade = 0;
  h.controller.attachDescriber((_target, _componentId, key) => ({
    element: key ? { key, kind: "text", label: key, computed: { ...TYPO, color: `#0000${(shade++ % 100).toString().padStart(2, "0")}` } } : null,
    elements: [{ key: "heading", kind: "text", label: "heading" }],
  }));
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const count = h.posts.filter((post) => post.type === "selected").length;
  for (let i = 0; i < 5; i += 1) h.controller.refreshSelection();
  assert.equal(h.posts.filter((post) => post.type === "selected").length, count);
});

test("leaving a piece of text sends what was typed once the rich text editor has reported it", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("F"));
  h.controller.leftText();
  assert.equal(h.types().includes("changed"), false, "nothing is sent at the moment of leaving");
  h.controller.pageEdited("/", page("Fewer surprises."));
  const leave = h.timers.find((_, i) => i === h.timers.length - 2);
  leave?.();
  const changed = h.posts.filter((post) => post.type === "changed");
  assert.equal(changed.length, 1);
  assert.equal((changed[0].payload as { site: typeof site }).site.pages["/"].content[0].props.heading, "Fewer surprises.");
});

// Plan 2: highlighted words. The describer reads the canvas's text selection; the controller decides
// when a change of it is worth a `selected`, and keeps the words through a redraw.
function wordsHarness() {
  const h = harness();
  let words: { start: number; end: number; count: number; text: string; computed: typeof TYPO } | null = null;
  h.controller.attachDescriber((_target, _componentId, key) => ({
    element: key ? { key, kind: "text" as const, label: key, computed: TYPO, words } : null,
    elements: [{ key: "heading", kind: "text" as const, label: "heading" }, { key: "body", kind: "text" as const, label: "body" }],
  }));
  const setWords = (start: number | null, end = 0) => {
    words = start === null ? null : { start, end, count: 1, text: "x".repeat(end - start), computed: TYPO };
  };
  const lastWords = () => {
    const last = h.posts.filter((post) => post.type === "selected").at(-1)?.payload as { element: { words?: { start: number } | null } | null } | undefined;
    return last?.element?.words ?? null;
  };
  const selectedCount = () => h.posts.filter((post) => post.type === "selected").length;
  return { ...h, lastWords, selectedCount, setWords };
}

test("highlighting words in the selected element posts them; the same range again posts nothing", async () => {
  const h = wordsHarness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], {});
  h.controller.elementClicked("/", "cta", "heading");
  h.setWords(4, 9);
  h.controller.selectionChanged({ target: "/", componentId: "cta", key: "heading" });
  assert.equal(h.lastWords()?.start, 4);
  const count = h.selectedCount();
  h.controller.selectionChanged({ target: "/", componentId: "cta", key: "heading" });
  assert.equal(h.selectedCount(), count);
});

test("highlighting words in another element of the section selects that element with its words", async () => {
  const h = wordsHarness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], {});
  h.controller.elementClicked("/", "cta", "heading");
  h.setWords(0, 3);
  h.controller.selectionChanged({ target: "/", componentId: "cta", key: "body" });
  assert.deepEqual(h.controller.getState().selection, { componentId: "cta", elementKey: "body", target: "/" });
  assert.equal(h.lastWords()?.start, 0);
});

test("a redraw that drops the highlight keeps the words; the marketer's own click or key clears them", async () => {
  const h = wordsHarness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], {});
  h.controller.elementClicked("/", "cta", "heading");
  h.setWords(4, 9);
  h.controller.selectionChanged({ target: "/", componentId: "cta", key: "heading" });
  h.setWords(null);
  const count = h.selectedCount();
  h.controller.selectionChanged(null);
  assert.equal(h.selectedCount(), count, "a collapse nobody asked for posts nothing");
  h.controller.reselected("cta", "CtaBand", [], {});
  assert.equal(h.lastWords()?.start, 4, "a re-description after a redraw keeps the words");
  assert.deepEqual(h.controller.keptWords(), { componentId: "cta", key: "heading", target: "/", words: { start: 4, end: 9, count: 1, text: "xxxxx", computed: TYPO } });
  h.controller.userActed();
  h.controller.selectionChanged(null);
  assert.equal(h.lastWords(), null, "after a click or a key, a collapse clears the words");
  assert.equal(h.controller.keptWords(), null);
});

// Plan 4: a selected section carries its own box (ruling R1, R2); a change in Layers' tree re-posts.
test("selected for a section carries its section box; for an element none", async () => {
  const h = harness();
  const BOX = { fill: "#FFFFFF", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 1000 };
  const sectionBox = { outer: { key: "root", box: BOX }, inner: { key: "root.inner", container: { ...BOX, gap: 0, layout: "text" as const, contentAlign: "start" as const, name: "Box" } } };
  h.controller.attachDescriber((_target, _componentId, key) => ({
    element: key === "heading" ? { key, kind: "text" as const, label: key, computed: TYPO } : null,
    elements: [{ key: "heading", kind: "text" as const, label: "heading", parent: null }],
    sectionBox: key ? null : sectionBox,
  }));
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const selected = () => h.posts.filter((post) => post.type === "selected").map((post) => post.payload as { element: unknown; sectionBox?: unknown });
  assert.deepEqual(selected().at(-1)?.sectionBox, sectionBox);
  // A click on an element of the selected section re-posts with the element, and no section box.
  h.controller.elementClicked("/", "cta", "heading");
  assert.equal(selected().at(-1)?.sectionBox ?? null, null);
});

test("a change in which parent an element sits under re-posts the selection", async () => {
  const h = harness();
  let parent: string | null = null;
  h.controller.attachDescriber(() => ({ element: null, elements: [{ key: "heading", kind: "text" as const, label: "heading", parent }] }));
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const count = () => h.posts.filter((post) => post.type === "selected").length;
  const before = count();
  h.controller.refreshSelection();
  assert.equal(count(), before, "nothing changed");
  parent = "column";
  h.controller.refreshSelection();
  assert.equal(count(), before + 1);
});

// Plan 4 live check: after an undo (the app's new copy of the site), the panel showed the old drawn
// value. A look that changes after a copy arrives is posted; a look that changes on its own is not.
test("a drawn look changed by a new copy of the site is posted again; one that changes on its own is not", async () => {
  const h = harness();
  let size = 48;
  h.controller.attachDescriber((_target, _componentId, key) => ({
    element: key === "heading" ? { key, kind: "text" as const, label: key, computed: { ...TYPO, fontSize: size } } : null,
    elements: [{ key: "heading", kind: "text" as const, label: "heading", parent: null }],
  }));
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "heading");
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const sizes = () => h.posts.filter((post) => post.type === "selected").map((post) => (post.payload as { element: { computed: { fontSize: number } } | null }).element?.computed.fontSize);
  const before = sizes().length;
  size = 60; // an animation, say: nothing the app sent
  h.controller.refreshSelection();
  assert.equal(sizes().length, before, "no post for a look that changes on its own");
  await h.controller.receive(appToFrame("set_props", { componentId: "cta", props: { heading: "Hello", id: "cta" }, route: "/", rev: 2 }, { documentId: "doc_1", nonce: NONCE }));
  size = 32; // the undone style: the canvas redrew from the app's copy
  h.controller.refreshSelection();
  assert.equal(sizes().at(-1), 32, "the new drawn look reaches the panel");
});

test("review I1/I2: an image's drawn look (fit, corners) is posted after a new copy of the site, and when its file loads", async () => {
  const h = harness();
  const BOX = { fill: "", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 400 };
  let image = { media: "img" as const, box: BOX, fit: "fill" as const, fitMatters: true, alt: "", src: "/brands/x.png" };
  h.controller.attachDescriber((_target, _componentId, key) => ({
    element: key === "image" ? { key, kind: "image" as const, label: "Image", computed: TYPO, image } : null,
    elements: [{ key: "image", kind: "image" as const, label: "Image", parent: null }],
  }));
  await h.controller.receive(init());
  h.controller.elementClicked("/", "cta", "image");
  h.controller.componentSelected("cta", "CtaBand", [], {});
  const fits = () => h.posts.filter((post) => post.type === "selected").map((post) => (post.payload as { element: { image: { fit: string; fitMatters: boolean } } | null }).element?.image);
  await h.controller.receive(appToFrame("set_props", { componentId: "cta", props: { id: "cta" }, route: "/", rev: 2 }, { documentId: "doc_1", nonce: NONCE }));
  image = { ...image, fit: "fit" as never };
  h.controller.refreshSelection();
  assert.equal(fits().at(-1)?.fit, "fit", "the undone fit reaches the panel");
  image = { ...image, fitMatters: false };
  h.controller.imageLoaded();
  assert.equal(fits().at(-1)?.fitMatters, false, "a file that loaded after the selection is described again");
});
