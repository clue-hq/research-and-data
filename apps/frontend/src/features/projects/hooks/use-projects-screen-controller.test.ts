import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  paginate,
  startChat,
  visibleProjects,
} from "./use-projects-screen-controller";
import {
  MAX_PREFILLED_PROMPT_LENGTH,
  prefilledPrompt,
  urlWithoutPrompt,
} from "../model/prefilled-prompt";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

const p = (id: string, extra = {}) => ({
  id,
  title: id,
  description: "",
  href: `/projects/${id}`,
  status: "active",
  pinned: false,
  brandId: "b",
  productId: null,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
  archivedAt: null,
  activity: { chats: 0, running: 0, needsInput: 0 },
  ...extra,
});

test("visibleProjects applies filter, query and sort exactly as the dummy did", () => {
  const all = [p("a"), p("b", { status: "archived" }), p("c", { pinned: true })];
  assert.deepEqual(
    visibleProjects(all as never, { filter: "active", query: "", sort: "name" }).map(
      (x) => x.id,
    ),
    ["c", "a"],
  );
  assert.deepEqual(
    visibleProjects(all as never, {
      filter: "archived",
      query: "",
      sort: "name",
    }).map((x) => x.id),
    ["b"],
  );
  assert.deepEqual(
    visibleProjects(all as never, { filter: "active", query: "C", sort: "name" }).map(
      (x) => x.id,
    ),
    ["c"],
  );
});

test("paginate slices 12 per page", () => {
  const many = Array.from({ length: 25 }, (_, i) => p(`p${i}`));
  assert.equal(paginate(many as never, 1).length, 12);
  assert.equal(paginate(many as never, 3).length, 1);
});

test("startChat creates the thread, submits the first turn on it, and returns the thread href", async () => {
  const calls: string[] = [];
  const thread = { id: "thr_new", href: "/projects/prj/chats/thr_new" };
  const deps = {
    threads: {
      create: async (input: { projectId: string }) => {
        calls.push(`create:${input.projectId}`);
        return thread;
      },
    },
    turns: {
      submit: async (input: {
        threadId: string;
        submission: { kind: string; message?: string };
      }) => {
        calls.push(`submit:${input.threadId}:${input.submission.message}`);
        return { turnId: "t1" };
      },
    },
  };
  const result = await startChat(deps as never, {
    projectId: "prj",
    message: "Plan Q4",
    contextRefs: [],
    attachmentRefs: [],
    agentProfileId: null,
  });
  assert.deepEqual(calls, ["create:prj", "submit:thr_new:Plan Q4"]);
  assert.equal(result.href, thread.href);
});

test("startChat refuses an empty message without creating a thread", async () => {
  const deps = {
    threads: {
      create: async () => {
        throw new Error("must not be called");
      },
    },
    turns: { submit: async () => ({}) },
  };
  await assert.rejects(
    startChat(deps as never, {
      projectId: "prj",
      message: "   ",
      contextRefs: [],
      attachmentRefs: [],
      agentProfileId: null,
    }),
  );
});

test("a chat is never started while an attachment is still uploading, and it is refused in the Home's words", () => {
  // `newChat` is hook-internal — this repo runs `node:test` with no React
  // renderer, so the wiring is asserted at its source the way the in-chat add
  // is (`use-add-to-open-chat-controller.test.ts`). The rule underneath is
  // already pinned by `chat-attachments.test.ts`: the snapshot is `null` until
  // every attachment is ready.
  const controller = source("./use-projects-screen-controller.ts");
  const home = source("./use-project-home-controller.ts");
  const refusal = 'setError("Wait for attachments to finish uploading.");';
  // The same sentence in both controllers, so the two cannot drift apart.
  assert.ok(home.includes(refusal));
  assert.ok(controller.includes(refusal));
  // The guard comes before the writes: the refusal, and its `return`, are
  // above the only `startChat` call.
  assert.ok(
    controller.indexOf(refusal) < controller.indexOf("startChat(repositories"),
  );
  // And nothing silently substitutes an empty list for a withheld snapshot.
  assert.doesNotMatch(controller, /snapshot\(\) \?\? \[\]/);
});

test("a ?prompt= link fills the Home composer with its text, cut to a sane length", () => {
  assert.equal(
    prefilledPrompt("Ask Clue to analyse my HubSpot deals"),
    "Ask Clue to analyse my HubSpot deals",
  );
  // A repeated parameter takes the first value, the way a browser reads it.
  assert.equal(prefilledPrompt(["first", "second"]), "first");
  // Missing, empty or blank changes nothing: the composer starts empty.
  assert.equal(prefilledPrompt(undefined), "");
  assert.equal(prefilledPrompt(""), "");
  assert.equal(prefilledPrompt("   \n "), "");
  // A long message is cut, never refused.
  const long = "x".repeat(MAX_PREFILLED_PROMPT_LENGTH + 500);
  assert.equal(prefilledPrompt(long).length, MAX_PREFILLED_PROMPT_LENGTH);
  assert.equal(MAX_PREFILLED_PROMPT_LENGTH, 2000);
});

test("the prompt parameter is dropped from the address, everything else kept", () => {
  assert.equal(
    urlWithoutPrompt("https://app.test/projects/prj?prompt=Hello%20there"),
    "/projects/prj",
  );
  assert.equal(
    urlWithoutPrompt("https://app.test/projects/prj?prompt=Hi&x=1#top"),
    "/projects/prj?x=1#top",
  );
  assert.equal(urlWithoutPrompt("https://app.test/projects/prj"), null);
});

test("the Home composer starts with the linked prompt and sends nothing until the person submits", () => {
  // Hook wiring, asserted at its source (no React renderer under node:test).
  const controller = source("./use-projects-screen-controller.ts");
  const page = source("../../../app/(protected)/projects/[projectId]/page.tsx");
  const screen = source("../components/projects-screen.tsx");
  // The route reads `prompt` once and hands the cleaned text to the Home.
  assert.match(page, /prompt\?: string \| string\[\]/);
  assert.match(page, /initialPrompt=\{prefilledPrompt\(query\.prompt\)\}/);
  assert.match(screen, /useProjectsScreenController\(projectId, initialPrompt\)/);
  // The composer's state is born with it — the initial value, not an effect.
  assert.match(controller, /useState\(initialPrompt\)/);
  // The only `startChat` call stays inside the submit handler: nothing in an
  // effect sends the prefilled text.
  assert.equal(controller.split("startChat(repositories").length, 2);
  const effects = controller.match(/useEffect\(\(\) => \{[\s\S]*?\}, \[[^\]]*\]\);/g) ?? [];
  for (const effect of effects) assert.doesNotMatch(effect, /newChat|startChat|submit/);
  // And the parameter leaves the address once read, so a reload starts clean.
  assert.match(controller, /window\.history\.replaceState\(null, "", withoutPrompt\)/);
});
