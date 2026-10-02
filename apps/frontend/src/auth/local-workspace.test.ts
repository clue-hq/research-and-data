import assert from "node:assert/strict";
import test from "node:test";
import { assertLocalWorkspaceSelection, localProvisioningRefusal, localWorkspaceInstance, workspaceCookieName } from "./local-workspace";
import { ClueAuthenticationError } from "./errors";

const configured = {
  NODE_ENV: "development", CLUE_AUTH_ENABLED: "true",
  CLUE_APP_ORIGIN: "http://localhost:3022",
  CLUE_LOCAL_WORKSPACE_ID: "ws_aws", CLUE_LOCAL_WORKSPACE_NAME: "AWS",
};

test("ordinary deployments keep their normal workspace selection", () => {
  assert.equal(localWorkspaceInstance({ NODE_ENV: "production" }), null);
  assert.equal(localWorkspaceInstance({ NODE_ENV: "development" }), null);
});

test("local ports use separate cookies and compiler outputs", () => {
  const aws = localWorkspaceInstance(configured)!;
  const google = localWorkspaceInstance({ ...configured, CLUE_APP_ORIGIN: "http://localhost:3023", CLUE_LOCAL_WORKSPACE_ID: "ws_google", CLUE_LOCAL_WORKSPACE_NAME: "Google Cloud" })!;
  assert.notEqual(aws.cookieName, google.cookieName);
  assert.notEqual(aws.distDir, google.distDir);
  assert.equal(aws.cookieName, "clue_workspace_id_3022");
  assert.equal(google.cookieName, "clue_workspace_id_3023");
});

test("a local selector cannot enable unauthenticated or production access", () => {
  for (const override of [{ NODE_ENV: "production" }, { CLUE_AUTH_ENABLED: "false" }, { NODE_ENV: undefined }]) {
    assert.throws(() => localWorkspaceInstance({ ...configured, ...override }));
  }
});

test("partial configuration and nonlocal or ambiguous origins fail closed", () => {
  for (const origin of ["https://cluehq.ai:3022", "http://localhost", "http://localhost:3022/path", "http://localhost:3022?workspace=x", "http://user@localhost:3022", "garbage"]) {
    assert.throws(() => localWorkspaceInstance({ ...configured, CLUE_APP_ORIGIN: origin }));
  }
  assert.throws(() => localWorkspaceInstance({ ...configured, CLUE_LOCAL_WORKSPACE_NAME: "" }));
  assert.throws(() => localWorkspaceInstance({ ...configured, CLUE_LOCAL_WORKSPACE_ID: "../../wrong" }));
});

test("explicit switching and provisioning cannot escape a pinned instance", async () => {
  const previous = Object.fromEntries(Object.keys(configured).map((key) => [key, process.env[key]]));
  Object.assign(process.env, configured);
  try {
    assert.doesNotThrow(() => assertLocalWorkspaceSelection("ws_aws"));
    assert.throws(() => assertLocalWorkspaceSelection("ws_conduit"), (error: unknown) => error instanceof ClueAuthenticationError && error.status === 403);
    assert.equal(workspaceCookieName(), "clue_workspace_id_3022");
    const refusal = localProvisioningRefusal()!;
    assert.equal(refusal.status, 403);
    assert.equal((await refusal.json()).error.code, "LOCAL_WORKSPACE_PINNED");
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
