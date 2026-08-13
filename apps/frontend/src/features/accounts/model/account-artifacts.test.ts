import assert from "node:assert/strict";
import test from "node:test";
import { accountArtifactStateCopy } from "./account-artifacts";

test("the unavailable capability is not presented as an empty Account", () => {
  const capability = accountArtifactStateCopy("capability_unavailable");
  const empty = accountArtifactStateCopy("empty");

  assert.equal(capability.title, "Account artifacts are not connected yet");
  assert.equal(empty.title, "No artifacts yet");
  assert.notDeepEqual(capability, empty);
});

test("an authoritative empty result stays distinct from a service failure", () => {
  const empty = accountArtifactStateCopy("empty");
  const unavailable = accountArtifactStateCopy("service_unavailable");

  assert.equal(empty.description, "No artifacts have been created for this account yet.");
  assert.equal(unavailable.title, "Artifacts are temporarily unavailable");
  assert.match(unavailable.description, /could not be reached/);
  assert.notDeepEqual(empty, unavailable);
});
