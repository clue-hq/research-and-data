import assert from "node:assert/strict";
import test from "node:test";
import { activeChatProjectId, mergeExpandedState, openProject } from "./use-sidebar-projects-controller";

const wire = (id: string, expanded = false) => ({
  id, expanded, pinned: false, title: id.toUpperCase(), href: `/projects/${id}`, conversations: [],
});

test("a reload keeps the local expanded flags and takes the server's pinned flag", () => {
  const current = [{ id: "a", expanded: true, pinned: false }];
  const next = mergeExpandedState(current as never, [{ id: "a", expanded: false, pinned: true, title: "A", href: "/projects/a", conversations: [] }] as never);
  assert.equal(next[0].expanded, true);
  assert.equal(next[0].pinned, true);
});

test("the project of the open chat is the one a chat route names", () => {
  assert.equal(activeChatProjectId("/projects/prj_1/chats/thr_9"), "prj_1");
  assert.equal(activeChatProjectId("/projects/prj_1/chats/thr_9/"), "prj_1");
  assert.equal(activeChatProjectId("/projects/prj_1"), null, "a project page is not a chat");
  assert.equal(activeChatProjectId("/projects/prj_1/artifacts/doc_1"), null);
  assert.equal(activeChatProjectId("/projects"), null);
  assert.equal(activeChatProjectId("/"), null);
});

test("the first read opens the open chat's project and leaves the others closed", () => {
  const next = mergeExpandedState([], [wire("a"), wire("b")] as never, "b");
  assert.deepEqual(next.map((project) => [project.id, project.expanded]), [["a", false], ["b", true]]);
});

test("a later read keeps a project the person closed closed, even the open chat's", () => {
  const current = mergeExpandedState([], [wire("a"), wire("b")] as never, "b");
  const closed = current.map((project) => ({ ...project, expanded: false }));
  const next = mergeExpandedState(closed, [wire("a"), wire("b")] as never, "b");
  assert.equal(next[1].expanded, false);
});

test("going to a chat opens its project without touching the others", () => {
  const current = [{ ...wire("a"), expanded: true }, wire("b"), wire("c")];
  const next = openProject(current as never, "b");
  assert.deepEqual(next.map((project) => [project.id, project.expanded]), [["a", true], ["b", true], ["c", false]]);
  assert.equal(openProject(next, "b"), next, "an already open project changes nothing");
  assert.equal(openProject(next, null), next);
});
