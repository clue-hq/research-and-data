import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { appToFrame, type FrameToAppType } from "@clue/site-kit/editor-protocol";
import { SiteDocumentSchema, type SitePage } from "@clue/site-kit/site-document";
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
    { brand, device: "Desktop", mode: "edit", route: "/", sections: [], site, ...overrides } as never,
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
  assert.deepEqual(h.types().slice(-2), ["changed", "shortcut"]);
});

test("the app's own edits re-render the page without echoing a change back", async () => {
  const h = harness();
  await h.controller.receive(init());
  await h.controller.receive(
    appToFrame("set_props", { componentId: "cta", props: { heading: "From the dock" }, route: "/" }, { documentId: "doc_1", nonce: NONCE }),
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
  await h.controller.receive(appToFrame("replace_site", { site: agent, version: 9 }, { documentId: "doc_1", nonce: NONCE }));
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
