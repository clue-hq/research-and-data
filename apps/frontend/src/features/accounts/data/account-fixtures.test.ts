import assert from "node:assert/strict";
import test from "node:test";
import {
  getAccountContact,
  getAccountContacts,
} from "./account-contacts.repository";
import { getAccountDetails } from "./account-details.repository";

/**
 * The fixtures are the contract's stand-in until a live backend is wired, so
 * they are parsed through the same Zod schemas the HTTP adapters use. A fixture
 * that drifts from the wire shape fails here rather than in a screen.
 */

test("the account detail fixture parses, sections included", async () => {
  const account = await getAccountDetails("openai");

  assert.ok(account);
  assert.equal(account.redirectedFrom, null);
  // Neutral facts are project-neutral and appear once, not per project.
  assert.equal(
    account.neutralFacts.filter(
      (fact) => fact.fieldKey === "core.employee_count",
    ).length,
    1,
  );
  // A pack field rides the same registry-driven list as the core fields.
  assert.ok(
    account.neutralFacts.some((fact) =>
      fact.fieldKey.startsWith("saas_platform."),
    ),
  );
  // Value narratives are plural, one per persona.
  const revenueSection = account.projectSections.find(
    (section) => section.projectId === "10m-landing-page-campaign",
  );
  assert.equal(revenueSection?.narratives.length, 2);
  // The unattributed bucket is served last and is labelled by a null project.
  assert.equal(
    account.projectSections[account.projectSections.length - 1]?.projectId,
    null,
  );
});

test("an unknown account id resolves to null rather than throwing", async () => {
  assert.equal(await getAccountDetails("not-an-account"), null);
});

test("the contact fixtures distinguish withheld values from absent ones", async () => {
  const contacts = await getAccountContacts("openai");

  const restricted = contacts.find((contact) => contact.titleRestricted);
  assert.ok(restricted);
  assert.equal(restricted.title, null);

  const unnamed = contacts.find((contact) => contact.name === null);
  assert.ok(unnamed);
  assert.equal(unnamed.titleRestricted, false);
});

test("the contact profile carries governed facts and URL-free evidence", async () => {
  const contact = await getAccountContact("openai", "denise-dresser");

  assert.ok(contact);
  assert.equal(contact.accountId, "openai");
  const withheld = contact.professionalFacts.find((fact) => fact.restricted);
  assert.ok(withheld);
  // A withheld fact carries no value and no provenance — only the marker.
  assert.equal(withheld.value, null);
  assert.equal(withheld.provider, null);
  for (const evidence of contact.evidence) {
    assert.equal("url" in evidence, false);
  }
});

test("an account with no committee returns an empty list, not null", async () => {
  assert.deepEqual(await getAccountContacts("anthropic"), []);
});
