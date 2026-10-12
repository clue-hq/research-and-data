import assert from "node:assert/strict";
import { test } from "node:test";
import { ClueAuthenticationError } from "@/auth/errors";
import { handleSiteEditorSession } from "./site-editor-session-handler";

test("an authenticated workspace gets its own editor origin, never cached", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "editor.localhost:3129",
    workspaceId: async () => "ws_123",
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), {
    data: { editorOrigin: "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129" },
  });
});

test("no editor domain configured, or authentication off, means no origin", async () => {
  for (const deps of [
    { authenticationEnabled: true, editorSuffix: "" },
    { authenticationEnabled: false, editorSuffix: "edit.example.com" },
  ]) {
    const response = await handleSiteEditorSession({ ...deps, workspaceId: async () => "ws_123" });
    assert.deepEqual(await response.json(), { data: { editorOrigin: null } });
  }
});

test("an unauthenticated request is refused with the authentication error's own status", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "edit.example.com",
    workspaceId: async () => {
      throw new ClueAuthenticationError("Sign in to continue", { code: "AUTHENTICATION_REQUIRED", status: 401 });
    },
  });
  assert.equal(response.status, 401);
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, "AUTHENTICATION_REQUIRED");
});

test("a malformed suffix fails loudly instead of producing a wrong origin", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "https://edit.example.com",
    workspaceId: async () => "ws_123",
  });
  assert.equal(response.status, 500);
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, "SITE_EDITOR_MISCONFIGURED");
});
