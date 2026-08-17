import assert from "node:assert/strict";
import test from "node:test";
import {
  projectArtifactHref,
  projectChatHref,
  projectGalleryHref,
} from "./chat-shell-routes";

test("project-owned routes keep chats and artifacts under their durable project", () => {
  assert.equal(
    projectGalleryHref("campaign one", "t1"),
    "/projects/campaign%20one/chats/t1?surface=gallery",
  );
  assert.equal(
    projectChatHref("campaign one", "thread/primary", {
      edit: "1",
      surface: "web",
    }),
    "/projects/campaign%20one/chats/thread%2Fprimary?edit=1&surface=web",
  );
  assert.equal(
    projectArtifactHref("campaign one", "artifact/hero", {
      kind: "web",
      thread: "thread-primary",
    }),
    "/projects/campaign%20one/artifacts/artifact%2Fhero?kind=web&thread=thread-primary",
  );
});

test("route builders omit empty integration-state parameters", () => {
  assert.equal(
    projectChatHref("project", "chat", { edit: undefined, surface: "" }),
    "/projects/project/chats/chat",
  );
});
