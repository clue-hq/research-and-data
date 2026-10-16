import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  createFixtureWebPublishRepository,
  createHttpWebPublishRepository,
  type WebPublishRepository,
} from "../../design-editor/data/web-publish.repository";
import { AGENT_RUN_PUBLISH_NOTE } from "../model/agent-run-lock";
import type { ChatShellArtifactKind } from "../model/chat-shell";
import {
  pageLinkRows,
  publishWithRepository,
  shareAddresses,
  useArtifactSharingController,
} from "./use-artifact-sharing-controller";

test("publishWithRepository publishes the slug and returns the server url", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(repo, "doc_1", {
    slug: "openai-cfo",
    noindex: false,
  });
  assert.equal(outcome.status, "published");
  assert.match(outcome.url, /\/openai-cfo$/);

  const state = await repo.state("doc_1");
  assert.equal(state.published, true);
  assert.equal(state.slug, "openai-cfo");
  assert.equal(state.url, outcome.url);
});

test("a failing publish reports draft with the message", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async () => {
        throw new Error("slug taken");
      },
    },
    "doc_1",
    { slug: "x", noindex: false },
  );
  assert.equal(outcome.status, "draft");
  assert.equal(outcome.message, "slug taken");
  assert.equal(outcome.url, "");
});

test("publishWithRepository forwards the noindex the caller asked for", async () => {
  const repo = createFixtureWebPublishRepository();
  const asked: Array<{ slug: string; noindex: boolean }> = [];
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async (documentId, input) => {
        asked.push(input);
        return repo.publish(documentId, input);
      },
    },
    "doc_1",
    { slug: "acme", noindex: true },
  );
  assert.equal(outcome.status, "published");
  assert.deepEqual(asked, [{ slug: "acme", noindex: true }]);
  assert.deepEqual(Object.keys(outcome.pageUrls), ["/"]);
});

test("a publish on a custom hostname shares the custom address and its pages", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(
    {
      ...repo,
      publish: async () => ({
        customPageUrls: {
          "/": "https://go.acme.com/launch",
          "/pricing": "https://go.acme.com/launch/pricing",
        },
        customUrl: "https://go.acme.com/launch",
        docVersion: 1,
        pageUrls: {
          "/": "https://acme.pages.cluehq.ai/launch",
          "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
        },
        slug: "launch",
        url: "https://acme.pages.cluehq.ai/launch",
      }),
    },
    "doc_1",
    { slug: "launch", noindex: false },
  );
  assert.equal(outcome.status, "published");
  assert.equal(outcome.url, "https://go.acme.com/launch");
  assert.deepEqual(outcome.pageUrls, {
    "/": "https://go.acme.com/launch",
    "/pricing": "https://go.acme.com/launch/pricing",
  });
});

test("shareAddresses keeps the Clue address when there is no custom hostname", () => {
  assert.deepEqual(
    shareAddresses({
      customPageUrls: {},
      customUrl: null,
      pageUrls: { "/": "https://acme.pages.cluehq.ai/launch" },
      url: "https://acme.pages.cluehq.ai/launch",
    }),
    {
      pageUrls: { "/": "https://acme.pages.cluehq.ai/launch" },
      url: "https://acme.pages.cluehq.ai/launch",
    },
  );
});

test("shareAddresses reads an unpublished state as no address at all", () => {
  assert.deepEqual(
    shareAddresses({ customPageUrls: {}, customUrl: null, pageUrls: {}, url: null }),
    { pageUrls: {}, url: "" },
  );
});

test("pageLinkRows puts Home first and then the routes alphabetically", () => {
  const rows = pageLinkRows({
    "/pricing": "https://acme.clue.site/launch/pricing",
    "/": "https://acme.clue.site/launch",
    "/about": "https://acme.clue.site/launch/about",
  });
  assert.deepEqual(rows, [
    { label: "Home", route: "/", url: "https://acme.clue.site/launch" },
    {
      label: "/about",
      route: "/about",
      url: "https://acme.clue.site/launch/about",
    },
    {
      label: "/pricing",
      route: "/pricing",
      url: "https://acme.clue.site/launch/pricing",
    },
  ]);
});

test("pageLinkRows yields the one row a single-page site has", () => {
  const rows = pageLinkRows({ "/": "https://acme.clue.site/launch" });
  assert.deepEqual(rows, [
    { label: "Home", route: "/", url: "https://acme.clue.site/launch" },
  ]);
});

// --- Task 28 (founder 2026-10-13): a person's publish waits while the design agent works --------

/** The design API's refusal while a design run drives the document (main.py,
 * `_refuse_if_agent_running`): a 409 with a code and the run's id — no message. */
function agentRunActiveFetch(calls: string[]): typeof fetch {
  return async (input) => {
    calls.push(String(input));
    return new Response(
      JSON.stringify({ detail: { code: "document.agent_run_active", run_id: "run_42" } }),
      { headers: { "content-type": "application/json" }, status: 409 },
    );
  };
}

test("a publish refused because the agent is working reports the note, never the code", async () => {
  const calls: string[] = [];
  const outcome = await publishWithRepository(
    createHttpWebPublishRepository({
      apiBaseUrl: "http://localhost:8002",
      fetchImpl: agentRunActiveFetch(calls),
    }),
    "doc_1",
    { slug: "acme", noindex: false },
  );
  assert.equal(calls.length, 1);
  assert.equal(outcome.status, "draft");
  assert.equal(outcome.agentWorking, true);
  assert.equal(outcome.message, AGENT_RUN_PUBLISH_NOTE);
  assert.doesNotMatch(outcome.message, /agent_run_active|run_42/);
});

test("any other refusal is not the agent's lock", async () => {
  const outcome = await publishWithRepository(
    createHttpWebPublishRepository({
      apiBaseUrl: "http://localhost:8002",
      fetchImpl: async () =>
        new Response(JSON.stringify({ detail: { code: "web_publish.slug_taken", message: "Slug already in use." } }), {
          headers: { "content-type": "application/json" },
          status: 409,
        }),
    }),
    "doc_1",
    { slug: "acme", noindex: false },
  );
  assert.equal(outcome.agentWorking, false);
  assert.equal(outcome.message, "Slug already in use.");
});

type SharingController = ReturnType<typeof useArtifactSharingController>["controller"];

/** Mount the real hook in a DOM (the menu's controller, exactly as the header
 * builds it) and hand back every render's controller. */
type SharingProps = {
  /** K6-2: the site editor's wait for edits on their way. */
  beforePublish?: (documentId: string) => Promise<{ ok: true; version: number | null } | { ok: false; message: string }>;
  /** The document on screen (default doc_1, "Spring launch"); a tab switch changes both. */
  documentId?: string;
  /** K6-2: the version the open editor last saved. */
  documentVersion?: number | null;
  kind?: ChatShellArtifactKind;
  publishLocked: boolean;
  /** Absent: the hook builds its own HTTP seam over the BFF, as the header does. */
  repository?: WebPublishRepository;
  title?: string;
};

async function withSharingController(
  initial: SharingProps,
  run: (
    latest: () => SharingController,
    rerender: (next: SharingProps) => Promise<void>,
  ) => Promise<void>,
): Promise<void> {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost/" });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    CustomEvent: dom.window.CustomEvent,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const seen: SharingController[] = [];
  function Probe(props: SharingProps): ReactNode {
    seen.push(
      useArtifactSharingController({
        beforePublish: props.beforePublish,
        documentId: props.documentId ?? "doc_1",
        documentVersion: props.documentVersion,
        kind: props.kind ?? "web",
        publishLocked: props.publishLocked,
        repository: props.repository,
        title: props.title ?? "Spring launch",
      }).controller,
    );
    return null;
  }
  const root = createRoot(dom.window.document.getElementById("root")!);
  const render = async (props: SharingProps) => {
    await act(async () => root.render(createElement(Probe, props)));
  };
  try {
    await render(initial);
    await run(() => seen.at(-1)!, render);
  } finally {
    act(() => root.unmount());
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete (globalThis as Record<string, unknown>)[key];
    }
  }
}

/** A seam that counts publishes, so "sends nothing" is a count, not a hope. */
function countingRepository(): WebPublishRepository & { publishes: number } {
  const fixture = createFixtureWebPublishRepository();
  const counted = {
    ...fixture,
    publishes: 0,
    async publish(documentId: string, input: { slug: string; noindex: boolean }) {
      counted.publishes += 1;
      return fixture.publish(documentId, input);
    },
  };
  return counted;
}

test("while the agent works the Publish action is inert, says why, and sends nothing", async () => {
  const repository = countingRepository();
  await withSharingController({ publishLocked: true, repository }, async (latest) => {
    assert.equal(latest().publishLocked, true);
    assert.equal(latest().publishLockNote, AGENT_RUN_PUBLISH_NOTE);
    await act(async () => latest().publishAsset());
    assert.equal(repository.publishes, 0);
    assert.equal(latest().publishStatus, "draft");
    assert.equal(latest().publishLockNote, AGENT_RUN_PUBLISH_NOTE);
  });
});

test("a run that started after the menu opened: the 409 shows the same note, not the code", async () => {
  const calls: string[] = [];
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl: agentRunActiveFetch(calls),
  });
  await withSharingController({ publishLocked: false, repository }, async (latest) => {
    assert.equal(latest().publishLockNote, null);
    await act(async () => latest().publishAsset());
    assert.equal(calls.length, 1);
    assert.equal(latest().publishStatus, "draft");
    assert.equal(latest().publishLockNote, AGENT_RUN_PUBLISH_NOTE);
    assert.equal(latest().statusMessage, AGENT_RUN_PUBLISH_NOTE);
    // The button is not held shut by a refusal: once the run is over, pressing it again publishes.
    assert.equal(latest().publishLocked, false);
  });
});

test("a refusal's note gives way to the lock, and leaves with it when the run is over", async () => {
  const calls: string[] = [];
  const repository = createHttpWebPublishRepository({
    apiBaseUrl: "http://localhost:8002",
    fetchImpl: agentRunActiveFetch(calls),
  });
  await withSharingController({ publishLocked: false, repository }, async (latest, rerender) => {
    await act(async () => latest().publishAsset());
    assert.equal(latest().publishLockNote, AGENT_RUN_PUBLISH_NOTE);
    // The surface now sees the run: the lock holds the button and says the same sentence.
    await rerender({ publishLocked: true, repository });
    assert.equal(latest().publishLocked, true);
    assert.equal(latest().publishLockNote, AGENT_RUN_PUBLISH_NOTE);
    // The run is over: no stale "wait" line is left behind.
    await rerender({ publishLocked: false, repository });
    assert.equal(latest().publishLocked, false);
    assert.equal(latest().publishLockNote, null);
  });
});

test("with no run in the way, publishing is unchanged", async () => {
  const repository = countingRepository();
  await withSharingController({ publishLocked: false, repository }, async (latest) => {
    assert.equal(latest().publishLocked, false);
    assert.equal(latest().publishLockNote, null);
    await act(async () => latest().publishAsset());
    assert.equal(repository.publishes, 1);
    assert.equal(latest().publishStatus, "published");
    assert.equal(latest().statusMessage, "Published");
    assert.equal(latest().publishLockNote, null);
  });
});

test("the Share menu reads and publishes a site through the site routes, and a web page through the web ones", async () => {
  for (const kind of ["site", "web"] as const) {
    const calls: string[] = [];
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push(`${method} ${String(input instanceof Request ? input.url : input)}`);
      const body =
        method === "POST"
          ? {
              custom_page_urls: {},
              page_urls: { "/": "http://pages.localhost/spring-launch" },
              routes: ["/"],
              schema_version: 1,
              slug: "spring-launch",
              url: "http://pages.localhost/spring-launch",
            }
          : { custom_origin: null, public_origin: "http://pages.localhost", published: false, schema_version: 1 };
      return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" }, status: 200 });
    }) as typeof fetch;
    try {
      await withSharingController({ kind, publishLocked: false }, async (latest) => {
        await act(async () => latest().toggleMenu());
        await act(async () => latest().publishAsset());
        assert.equal(latest().publishStatus, "published", kind);
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
    const route = `/api/clue/design/documents/doc_1/${kind}/publish`;
    assert.ok(calls.length >= 2, `${kind}: ${calls.join(" | ")}`);
    assert.ok(calls.every((call) => call.endsWith(` ${route}`)), `${kind}: ${calls.join(" | ")}`);
    assert.equal(calls.filter((call) => call.startsWith("POST ")).length, 1, kind);
  }
});

// Review finding K6-1: one Share menu serves every artifact tab, so switching tabs carried one site's
// Share settings into the next: a never-published site showed the other's address and was refused as
// "already published by another document", or went live at an address with another account's name;
// and a publish finishing after the switch landed on the new tab. The controller now resets its
// per-site state when the document changes, and a publish result lands only on its own site.
function slugOwnerRepository(published: Map<string, string>, gate?: Promise<void>): WebPublishRepository & { sent: { documentId: string; slug: string }[] } {
  const sent: { documentId: string; slug: string }[] = [];
  return {
    sent,
    async state(documentId) {
      const slug = published.get(documentId) ?? null;
      const url = slug ? `http://acme.pages.localhost:8049/${slug}` : null;
      return {
        currentVersion: 3, customOrigin: null, customPageUrls: {}, customUrl: null, docVersion: slug ? 3 : null,
        noindex: false, htmlDigest: null, manifestDigest: null, packageDigest: null,
        pageUrls: url ? { "/": url } : {}, pages: [], previousAvailable: false, publishId: null,
        publicOrigin: "http://acme.pages.localhost:8049", published: Boolean(slug), slug,
        status: slug ? "active" : null, updatedAt: null, url,
      };
    },
    async publish(documentId, input) {
      if (gate) await gate;
      sent.push({ documentId, slug: input.slug });
      for (const [owner, slug] of published) {
        if (slug === input.slug && owner !== documentId) throw new Error(`slug '${input.slug}' is already published by another document`);
      }
      published.set(documentId, input.slug);
      const url = `http://acme.pages.localhost:8049/${input.slug}`;
      return { customPageUrls: {}, customUrl: null, docVersion: 3, pageUrls: { "/": url }, slug: input.slug, url };
    },
    async setNoindex(_documentId, noindex) {
      return noindex;
    },
    async unpublish() {},
  } as WebPublishRepository & { sent: { documentId: string; slug: string }[] };
}

test("K6-1: switching to a never-published site never carries the other site's address", async () => {
  const repository = slugOwnerRepository(new Map([["doc_A", "acme-q4"]]));
  const a = { documentId: "doc_A", kind: "site" as const, publishLocked: false, repository, title: "Acme Q4 account page" };
  await withSharingController(a, async (latest, rerender) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().slug, "acme-q4");
    await act(async () => latest().toggleMenu());
    await rerender({ ...a, documentId: "doc_B", title: "Globex account page" });
    assert.equal(latest().slug, "globex-account-page", "its own address, from its own title");
    assert.equal(latest().shareUrl, "");
    assert.equal(latest().publishStatus, "draft");
    await act(async () => latest().publishAsset());
    assert.deepEqual(repository.sent, [{ documentId: "doc_B", slug: "globex-account-page" }]);
    assert.equal(latest().publishStatus, "published");
  });
});

test("K6-1: a site published straight after a switch goes live under its own name", async () => {
  const repository = slugOwnerRepository(new Map());
  const c = { documentId: "doc_C", kind: "site" as const, publishLocked: false, repository, title: "Initech account page" };
  await withSharingController(c, async (latest, rerender) => {
    await rerender({ ...c, documentId: "doc_D", title: "Umbrella account page" });
    await act(async () => latest().toggleMenu());
    await act(async () => latest().publishAsset());
    assert.deepEqual(repository.sent, [{ documentId: "doc_D", slug: "umbrella-account-page" }]);
  });
});

test("K6-1: a publish that finishes after switching sites never shows on the new site", async () => {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const published = new Map<string, string>();
  const repository = slugOwnerRepository(published, gate);
  const e = { documentId: "doc_E", kind: "site" as const, publishLocked: false, repository, title: "Hooli account page" };
  await withSharingController(e, async (latest, rerender) => {
    await act(async () => latest().toggleMenu());
    let pending: Promise<void> = Promise.resolve();
    await act(async () => {
      pending = latest().publishAsset();
    });
    await rerender({ ...e, documentId: "doc_F", title: "Pied Piper account page" });
    await act(async () => {
      release();
      await pending;
    });
    assert.equal(published.get("doc_E"), "hooli-account-page", "E's publish still happened");
    assert.equal(latest().publishStatus, "draft", "F was never published");
    assert.equal(latest().shareUrl, "", "Copy link has nothing of E's");
    assert.equal(latest().slug, "pied-piper-account-page");
  });
});


// --- K6-2: Share offers Republish once the site has changed since it was published ---------------
// --- K6-3: "Allow indexing" starts from the document's durable noindex and the choice is kept -----

/** A publish seam with a server's memory: the document's version, its durable noindex, and the
 * version its live site was published from. Every call is logged in order. */
function serverRepository(start: { version: number; noindex?: boolean; publishedVersion?: number | null }) {
  const server = {
    version: start.version,
    noindex: start.noindex ?? false,
    publishedVersion: start.publishedVersion ?? null,
    calls: [] as string[],
  };
  const url = "http://acme.pages.localhost:8049/spring-launch";
  const repository: WebPublishRepository = {
    async state() {
      server.calls.push("state");
      const live = server.publishedVersion !== null;
      const pageUrls: Record<string, string> = live ? { "/": url } : {};
      return {
        customOrigin: null, customPageUrls: {}, customUrl: null, docVersion: server.publishedVersion,
        currentVersion: server.version, noindex: server.noindex,
        htmlDigest: null, manifestDigest: null, packageDigest: null,
        pageUrls, pages: [], previousAvailable: false, publishId: null,
        publicOrigin: "http://acme.pages.localhost:8049", published: live, slug: live ? "spring-launch" : null,
        status: live ? "active" : null, updatedAt: null, url: live ? url : null,
      };
    },
    async publish(_documentId, input) {
      server.calls.push(`publish noindex=${input.noindex}`);
      server.publishedVersion = server.version;
      return { customPageUrls: {}, customUrl: null, docVersion: server.version, pageUrls: { "/": url }, slug: input.slug, url };
    },
    async setNoindex(_documentId, noindex) {
      server.calls.push(`setNoindex ${noindex}`);
      server.noindex = noindex;
      return noindex;
    },
    async unpublish() {},
  };
  return { repository, server };
}

test("K6-2: a site changed since its publish says so and offers Republish; equal versions do not", async () => {
  const { repository, server } = serverRepository({ version: 4, publishedVersion: 3 });
  await withSharingController({ kind: "site", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().publishStatus, "published");
    assert.equal(latest().changesSincePublish, true);
    await act(async () => latest().toggleMenu());
    server.publishedVersion = 4;
    await act(async () => latest().toggleMenu());
    assert.equal(latest().changesSincePublish, false);
  });
});

test("K6-2: after a republish the menu shows the new published version without a reload", async () => {
  const { repository, server } = serverRepository({ version: 4, publishedVersion: 3 });
  await withSharingController({ kind: "site", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().changesSincePublish, true);
    await act(async () => latest().publishAsset());
    assert.equal(latest().publishStatus, "published");
    assert.equal(latest().changesSincePublish, false);
    assert.deepEqual(server.calls, ["state", "publish noindex=false"], "no state re-read was needed");
  });
});

test("K6-2: an edit saved while the menu is open counts as a change since publishing", async () => {
  const { repository } = serverRepository({ version: 3, publishedVersion: 3 });
  const props = { documentVersion: 3, kind: "site" as const, publishLocked: false, repository };
  await withSharingController(props, async (latest, rerender) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().changesSincePublish, false);
    await rerender({ ...props, documentVersion: 4 });
    assert.equal(latest().changesSincePublish, true);
  });
});

test("K6-2: Publish waits for the edits on their way before it publishes", async () => {
  const { repository, server } = serverRepository({ version: 3, publishedVersion: 3 });
  let release: (value: { ok: true; version: number }) => void = () => undefined;
  const saved = new Promise<{ ok: true; version: number }>((resolve) => (release = resolve));
  const asked: string[] = [];
  const beforePublish = (documentId: string) => {
    asked.push(documentId);
    return saved;
  };
  await withSharingController({ beforePublish, kind: "site", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    let pending: Promise<void> = Promise.resolve();
    await act(async () => {
      pending = latest().publishAsset();
    });
    assert.deepEqual(asked, ["doc_1"]);
    assert.equal(latest().publishStatus, "publishing");
    assert.deepEqual(server.calls, ["state"], "nothing is published while a save is on its way");
    server.version = 4; // the save lands
    await act(async () => {
      release({ ok: true, version: 4 });
      await pending;
    });
    assert.deepEqual(server.calls, ["state", "publish noindex=false"]);
    assert.equal(server.publishedVersion, 4, "the version published is the one the marketer saw");
    assert.equal(latest().changesSincePublish, false);
  });
});

test("K6-2: a save that fails stops the publish and the menu says why", async () => {
  const { repository, server } = serverRepository({ version: 3, publishedVersion: null });
  const beforePublish = async () => ({ ok: false as const, message: "page.content.0(hero).heading: Too small" });
  await withSharingController({ beforePublish, kind: "site", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    await act(async () => latest().publishAsset());
    assert.deepEqual(server.calls, ["state"], "nothing was published");
    assert.equal(latest().publishStatus, "draft");
    assert.equal(
      latest().publishFailureNote,
      "Not published: your latest edit was not saved (page.content.0(hero).heading: Too small).",
    );
  });
});

test("K6-3: Allow indexing starts from the document's durable noindex, and a publish keeps it", async () => {
  const { repository, server } = serverRepository({ version: 2, noindex: true });
  await withSharingController({ kind: "site", publishLocked: false, repository }, async (latest) => {
    assert.equal(latest().allowIndexing, true, "before the state is read");
    await act(async () => latest().toggleMenu());
    assert.equal(latest().allowIndexing, false);
    await act(async () => latest().publishAsset());
    assert.deepEqual(server.calls, ["state", "publish noindex=true"], "nothing to store: the document already says noindex");
  });
});

test("K6-3: changing Allow indexing is stored on the document before the publish, so a reload shows it", async () => {
  const { repository, server } = serverRepository({ version: 2, noindex: false });
  await withSharingController({ kind: "web", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().allowIndexing, true);
    await act(async () => latest().setAllowIndexing(false));
    await act(async () => latest().publishAsset());
    assert.deepEqual(server.calls, ["state", "setNoindex true", "publish noindex=true"]);
  });
  // A reload: a fresh menu over the same document reads the stored choice.
  await withSharingController({ kind: "web", publishLocked: false, repository }, async (latest) => {
    await act(async () => latest().toggleMenu());
    assert.equal(latest().allowIndexing, false);
    // Ticking it again is the explicit act that makes the page indexable.
    await act(async () => latest().setAllowIndexing(true));
    await act(async () => latest().publishAsset());
    assert.deepEqual(server.calls.slice(-2), ["setNoindex false", "publish noindex=false"]);
    assert.equal(server.noindex, false);
  });
});
