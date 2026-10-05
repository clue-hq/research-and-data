import assert from "node:assert/strict";
import test, { mock } from "node:test";
import type { ProjectEntity } from "./project-workspace";
import { createDebouncedMentionSearch, mergeMentionResults } from "./mention-remote-search";

const entity = (id: string): ProjectEntity => ({ id, label: id, secondaryLabel: "x", type: "account" });

test("typing waits for a pause, cancels the stale request, and reports only the latest", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const asked: string[] = [];
    const aborted: string[] = [];
    const results: string[][] = [];
    const search = createDebouncedMentionSearch({
      delayMs: 120,
      search: async (query, signal) => {
        asked.push(query);
        signal.addEventListener("abort", () => aborted.push(query));
        return [entity(`hit-${query}`)];
      },
      onResults: (found) => results.push(found.map((item) => item.id)),
    });
    search.request("at");
    mock.timers.tick(60);
    search.request("atr");
    mock.timers.tick(60);
    search.request("atri");
    assert.deepEqual(asked, [], "nothing is asked while the user is still typing");
    mock.timers.tick(120);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(asked, ["atri"]);
    assert.deepEqual(results, [["hit-atri"]]);
    search.request("atriu");
    mock.timers.tick(120);
    search.request("x");
    assert.deepEqual(aborted, ["atriu"], "a new keystroke cancels the request in flight");
    search.dispose();
  } finally {
    mock.timers.reset();
  }
});

test("a query under two characters asks nothing and clears the results", () => {
  const results: string[][] = [];
  const search = createDebouncedMentionSearch({
    delayMs: 120,
    search: async () => [entity("never")],
    onResults: (found) => results.push(found.map((item) => item.id)),
  });
  search.request("a");
  assert.deepEqual(results, [[]]);
  search.dispose();
});

test("server matches follow the local ones, without duplicates", () => {
  assert.deepEqual(
    mergeMentionResults([entity("a"), entity("b")], [entity("b"), entity("c")]).map((item) => item.id),
    ["a", "b", "c"],
  );
});
