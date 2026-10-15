import assert from "node:assert/strict";
import test from "node:test";
import { projectRouteActiveHref } from "./active-navigation";

test("inside a project no top-level item is highlighted; the projects list highlights Projects", () => {
  assert.equal(projectRouteActiveHref("/"), "/");
  assert.equal(projectRouteActiveHref("/projects"), "/projects");
  assert.equal(projectRouteActiveHref("/projects/"), "/projects");
  // The open chat's own row is the highlight on a chat page, never the Projects item.
  assert.equal(projectRouteActiveHref("/projects/prj_1/chats/thr_1"), null);
  assert.equal(projectRouteActiveHref("/projects/prj_1"), null);
  assert.equal(projectRouteActiveHref("/projects/prj_1/artifacts/doc_1"), null);
});
