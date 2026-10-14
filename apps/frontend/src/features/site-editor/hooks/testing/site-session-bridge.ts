// Test support (not a test file): the REAL site editing session mounted in jsdom, wired to a REAL
// FrameController (the editor frame's logic, minus Puck) through an in-memory bridge that keeps the
// browser's rules — app → frame messages go to the iframe's window, frame → app messages are
// MessageEvents from that window, at the editor's exact origin, with the frame's nonce — and to an
// in-memory server with compare-and-swap, undo/redo stacks and gates for slow requests.
import { JSDOM } from "jsdom";
import { act, createElement, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { BrandData } from "@clue/site-kit";
import { frameToApp, parseAppToFrame } from "@clue/site-kit/editor-protocol";
import { pageFor } from "@clue/site-kit/editor-site";
import type { SiteDocument, SitePage } from "@clue/site-kit/site-document";
import { FrameController, type PuckHandle } from "../../../../../packages/site-editor/src/client/frame-controller";
import { SiteRepositoryError, type SiteRepository } from "../../data/site.repository";
import { useSiteEditingSession, type SiteEditingSession } from "../use-site-editing-session";

export const EDITOR_ORIGIN = "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129";
export const DOC = "doc-1";
const BRAND = { slug: "x", kit: { tokens: {} }, fonts: [], assets: {}, clones: {} } as unknown as BrandData;

export function startSite(headings: Record<string, string> = {}): SiteDocument {
  const heading = (id: string, fallback: string) => headings[id] ?? fallback;
  return {
    id: DOC,
    title: "Acme",
    theme: {},
    shell: null,
    agent_sections: {},
    pages: {
      "/": {
        root: { props: { title: "Home" } },
        content: [
          { type: "FeatureSplit", props: { id: "hero", heading: heading("hero", "Old headline"), surface: "page" } },
          { type: "CtaBand", props: { id: "cta", heading: heading("cta", "Talk to us"), surface: "brand" } },
        ],
      },
    },
  } as unknown as SiteDocument;
}

export function headingOf(site: SiteDocument | null | undefined, id = "hero"): string | undefined {
  const entry = site ? pageFor(site, "/")?.content.find((item) => item.props.id === id) : undefined;
  return entry ? String(entry.props.heading) : undefined;
}

export function withHeading(site: SiteDocument, id: string, heading: string): SiteDocument {
  const copy = structuredClone(site);
  const entry = copy.pages["/"].content.find((item) => item.props.id === id)!;
  entry.props = { ...entry.props, heading };
  return copy;
}

/** The server: the truth, with compare-and-swap like the design API. */
export interface FakeServer {
  site: SiteDocument;
  version: number;
  undo: SiteDocument[];
  redo: SiteDocument[];
  log: string[];
  /** Saves whose base was older than the version the server last REPORTED to the client. */
  staleBaseSaves: number;
  reported: number;
  /** Hold the next request of this kind until `release(kind)` (the validator, a slow network). */
  hold: { save: boolean; get: boolean };
  /** Refuse saves this function names (a 422 from the validator). */
  refuse: ((site: SiteDocument) => string | null) | null;
  /** Let the oldest held request of this kind answer. */
  release(kind: "save" | "get"): void;
  /** Another writer (an agent checkpoint, another tab) changes the site on the server. */
  outsideWrite(site: SiteDocument): void;
}

export function fakeServer(site: SiteDocument = startSite(), version = 5): FakeServer {
  const gates: Record<"save" | "get", (() => void)[]> = { get: [], save: [] };
  const server: FakeServer = {
    site,
    version,
    undo: [],
    redo: [],
    log: [],
    staleBaseSaves: 0,
    reported: version,
    hold: { save: false, get: false },
    refuse: null,
    release(kind) {
      const next = gates[kind].shift();
      if (!next) throw new Error(`no held ${kind} to release`);
      next();
    },
    outsideWrite(next) {
      server.undo.push(server.site);
      server.redo = [];
      server.site = next;
      server.version += 1;
      server.log.push(`outside write -> v${server.version}`);
    },
  };
  (server as FakeServer & { gate: Gate }).gate = (kind) => new Promise<void>((resolve) => gates[kind].push(resolve));
  return server;
}

type Gate = (kind: "save" | "get") => Promise<void>;

function gate(server: FakeServer, kind: "save" | "get"): Promise<void> {
  return (server as FakeServer & { gate: Gate }).gate(kind);
}

function moved(server: FakeServer): SiteRepositoryError {
  return new SiteRepositoryError("The document moved on.", { code: "edits.base_version_mismatch", currentVersion: server.version, status: 409 });
}

export function fakeRepository(server: FakeServer): SiteRepository {
  return {
    async get(documentId) {
      const read = { site: server.site, version: server.version, undo: server.undo.length, redo: server.redo.length };
      if (server.hold.get) {
        server.hold.get = false;
        server.log.push(`GET read v${read.version} (held)`);
        await gate(server, "get");
      }
      server.reported = Math.max(server.reported, read.version);
      return { documentId, title: "Acme", site: read.site, version: read.version, undoDepth: read.undo, redoDepth: read.redo };
    },
    async getBrand() {
      return BRAND;
    },
    async sectionLinks() {
      return [];
    },
    async save(_documentId, request) {
      if (request.baseVersion < server.reported) server.staleBaseSaves += 1;
      if (request.baseVersion !== server.version) {
        server.log.push(`PUT base v${request.baseVersion} refused (server v${server.version})`);
        throw moved(server);
      }
      const refusal = server.refuse?.(request.site) ?? null;
      if (refusal) {
        server.log.push(`PUT base v${request.baseVersion} refused 422`);
        throw new SiteRepositoryError("invalid", { code: "site.invalid", errors: [refusal], status: 422 });
      }
      if (server.hold.save) {
        server.hold.save = false;
        await gate(server, "save");
      }
      server.undo.push(server.site);
      server.redo = [];
      server.site = request.site;
      server.version += 1;
      server.reported = server.version;
      server.log.push(`PUT base v${request.baseVersion} -> v${server.version} hero=${headingOf(request.site)} cta=${headingOf(request.site, "cta")}`);
      return { version: server.version };
    },
    async undo(_documentId, baseVersion) {
      if (baseVersion !== server.version) throw moved(server);
      const previous = server.undo.pop();
      if (!previous) throw new SiteRepositoryError("empty", { code: "undo.empty", status: 409 });
      server.redo.push(server.site);
      server.site = previous;
      server.version += 1;
      server.reported = server.version;
      server.log.push(`UNDO -> v${server.version}`);
      return { version: server.version };
    },
    async redo(_documentId, baseVersion) {
      if (baseVersion !== server.version) throw moved(server);
      const next = server.redo.pop();
      if (!next) throw new SiteRepositoryError("empty", { code: "redo.empty", status: 409 });
      server.undo.push(server.site);
      server.site = next;
      server.version += 1;
      server.reported = server.version;
      server.log.push(`REDO -> v${server.version}`);
      return { version: server.version };
    },
    async versions() {
      return [];
    },
    async restore() {
      throw new Error("restore is not part of these scenarios");
    },
  };
}

export interface MountedSession {
  latest(): SiteEditingSession;
  frame: FrameController;
  shown: SitePage[];
  settle(rounds?: number): Promise<void>;
  /** The marketer types on the canvas: the frame's Puck reports the edited page (then the frame
   * debounces it; `flushCanvas` sends it at once, as a blur or a pause would). */
  typeOnCanvas(id: string, heading: string): void;
  flushCanvas(): Promise<void>;
  /** The frame's ⌘Z outside text. */
  pressUndo(): Promise<void>;
  /** Show another document, or none (a web or ad tab). */
  open(documentId: string | null): Promise<void>;
  unmount(): Promise<void>;
}

/** One repository over several documents, each answered by its own server. */
function repositoryFor(servers: Record<string, FakeServer>): SiteRepository {
  const byDocument = Object.fromEntries(Object.entries(servers).map(([documentId, server]) => [documentId, fakeRepository(server)]));
  const of = (documentId: string): SiteRepository => {
    const repository = byDocument[documentId];
    if (!repository) throw new Error(`no fake server for ${documentId}`);
    return repository;
  };
  return {
    get: (documentId) => of(documentId).get(documentId),
    getBrand: (documentId) => of(documentId).getBrand(documentId),
    sectionLinks: (documentId) => of(documentId).sectionLinks(documentId),
    save: (documentId, request) => of(documentId).save(documentId, request),
    undo: (documentId, baseVersion) => of(documentId).undo(documentId, baseVersion),
    redo: (documentId, baseVersion) => of(documentId).redo(documentId, baseVersion),
    versions: (documentId, limit) => of(documentId).versions(documentId, limit),
    restore: (documentId, batchId, baseVersion) => of(documentId).restore(documentId, batchId, baseVersion),
  };
}

export async function mountSiteSession(
  server: FakeServer,
  { strict = false, otherDocument }: { strict?: boolean; /** The server behind "doc-2", when a test opens it. */ otherDocument?: FakeServer } = {},
): Promise<MountedSession> {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost:3029/" });
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    CustomEvent: dom.window.CustomEvent,
    MessageEvent: dom.window.MessageEvent,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async (input: string) => {
      if (String(input).endsWith("/api/clue/site-editor/session")) {
        return new Response(JSON.stringify({ data: { editorOrigin: EDITOR_ORIGIN } }), { status: 200 });
      }
      if (String(input).includes("/api/clue/design/assets")) return new Response(JSON.stringify({ assets: [] }), { status: 200 });
      throw new Error(`unexpected fetch ${input}`);
    },
  });

  const repository = repositoryFor(otherDocument ? { [DOC]: server, "doc-2": otherDocument } : { [DOC]: server });
  const seen: SiteEditingSession[] = [];
  let artifact: string | null = "art-1";
  const documentIds: Record<string, string> = { "art-1": DOC, "art-2": "doc-2" };
  let iframe: HTMLIFrameElement | null = null;
  function Probe() {
    const session = useSiteEditingSession({
      activeArtifactId: artifact,
      documentIds,
      editing: true,
      enabled: artifact !== null,
      locked: false,
      repository,
      warm: true,
    });
    seen.push(session);
    return createElement("iframe", {
      ref: (element: HTMLIFrameElement | null) => {
        session.stage.canvas.iframeRef.current = element;
        iframe = element;
      },
    });
  }

  const shown: SitePage[] = [];
  const timers: (() => void)[] = [];
  let nonce = "";
  const frame = new FrameController({
    cancel: () => undefined,
    loadSections: async () => [],
    post: (type, payload, documentId) => {
      const data = frameToApp(type, payload, { documentId, nonce });
      setTimeout(() => {
        dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data, origin: EDITOR_ORIGIN, source: iframe!.contentWindow }));
      }, 0);
    },
    schedule: (run) => {
      timers.push(run);
      return timers.length;
    },
  });
  const puck: PuckHandle = { select: () => undefined, setMode: () => undefined, showPage: (page) => shown.push(page) };
  frame.attachPuck(puck);

  const root: Root = createRoot(dom.window.document.getElementById("root")!);
  const render = () => (strict ? createElement(StrictMode, null, createElement(Probe)) : createElement(Probe));
  const settle = async (rounds = 8) => {
    for (let i = 0; i < rounds; i += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 2));
      });
    }
  };
  await act(async () => root.render(render()));
  await settle();
  const latest = () => seen.at(-1)!;
  const src = latest().stage.canvas.src;
  if (!src) throw new Error("the session minted no editor frame address");
  nonce = new URL(src).hash.replace(/^#n=/, "");
  // The app → frame side of the bridge: what the frame's own acceptor would let through.
  Object.defineProperty(iframe!.contentWindow!, "postMessage", {
    configurable: true,
    value: (data: unknown, targetOrigin: string) => {
      if (targetOrigin !== EDITOR_ORIGIN) return;
      const message = parseAppToFrame(data);
      if (!message || message.nonce !== nonce) return;
      setTimeout(() => void frame.receive(message), 0);
    },
  });
  frame.announceReady();
  await settle();

  return {
    frame,
    latest,
    settle,
    shown,
    typeOnCanvas(id, heading) {
      const site = frame.getState().site;
      if (!site) throw new Error("the frame shows no site");
      frame.pageEdited("/", withHeading(site, id, heading).pages["/"]);
    },
    async flushCanvas() {
      frame.flushChange();
      await settle();
    },
    async pressUndo() {
      frame.shortcut("undo");
      await settle();
    },
    async open(documentId) {
      artifact = documentId === null ? null : documentId === DOC ? "art-1" : "art-2";
      await act(async () => root.render(render()));
      await settle();
    },
    async unmount() {
      await act(async () => root.unmount());
    },
  };
}
