import assert from "node:assert/strict";
import test from "node:test";
import {
  contactDisplayName,
  contactProfileLinkAccessibleName,
  contactRowAccessibleName,
} from "./contact-accessibility";

test("named Contact row and profile-link names are concise and distinct", () => {
  assert.equal(contactDisplayName("Dana Buyer"), "Dana Buyer");
  assert.equal(contactRowAccessibleName("Dana Buyer"), "Contact Dana Buyer");
  assert.equal(
    contactProfileLinkAccessibleName("Dana Buyer"),
    "Open Dana Buyer profile",
  );
});

test("unnamed Contact rows and links use the same honest fallback", () => {
  assert.equal(contactDisplayName(null), "Unnamed contact");
  assert.equal(contactRowAccessibleName(null), "Contact Unnamed contact");
  assert.equal(
    contactProfileLinkAccessibleName(null),
    "Open Unnamed contact profile",
  );
});
