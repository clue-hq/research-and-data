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
type SharingProps = { publishLocked: boolean; repository: WebPublishRepository };

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
        documentId: "doc_1",
        kind: "web",
        title: "Spring launch",
        ...props,
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
