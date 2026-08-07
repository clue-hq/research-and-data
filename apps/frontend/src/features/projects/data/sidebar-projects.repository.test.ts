import assert from "node:assert/strict";
import test from "node:test";
import { getSidebarProjects } from "./sidebar-projects.repository";

test("sidebar project fixtures preserve the project and thread hierarchy", async () => {
  const response = await getSidebarProjects();

  assert.equal(response.meta.total, response.data.length);
  assert.ok(response.data.length >= 3);
  assert.ok(response.data.some((project) => project.expanded));
  assert.ok(
    response.data.every((project) =>
      project.conversations.every((conversation) =>
        conversation.href.startsWith(project.href),
      ),
    ),
  );
});
