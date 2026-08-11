import assert from "node:assert/strict";
import test from "node:test";
import { createHttpAccountContactsRepository } from "./account-contacts.repository";
import { createHttpAccountDetailsRepository } from "./account-details.repository";
import { getAccountWorkspace } from "./account-workspace.repository";

test("account detail is fetched by encoded live id", async () => {
  let requestedPath = "";
  const repository = createHttpAccountDetailsRepository(async (path) => {
    requestedPath = path;
    return { id: "account/one", name: "Account One" };
  });

  const detail = await repository.get("account/one");

  assert.equal(requestedPath, "/accounts/account%2Fone");
  assert.equal(detail?.name, "Account One");
});

test("domain account and contact misses stay honest", async () => {
  const detailRepository = createHttpAccountDetailsRepository(async () => null);
  const contactRepository = createHttpAccountContactsRepository(async () => null);

  assert.equal(await detailRepository.get("missing"), null);
  assert.deepEqual(await contactRepository.list("missing"), []);
  assert.equal(await contactRepository.get("missing", "contact"), null);
});

test("every linked Contact shape parses through its independent detail endpoint", async () => {
  const paths: string[] = [];
  const rows = [
    {
      id: "named-contact",
      name: "Dana Buyer",
      title: "VP Finance",
      titleRestricted: false,
      persona: "economic_buyer",
      roleOnCommittee: { value: "economic_buyer", confidence: 0.87 },
      linkedinUrl: "https://linkedin.example.test/in/dana",
      projectIds: ["project-1"],
      signals: { typeCount: 1 },
    },
    {
      id: "withheld-contact",
      name: "Chris Blocker",
      title: null,
      titleRestricted: true,
      persona: "blocker",
      roleOnCommittee: { value: "blocker", confidence: 0.62 },
      linkedinUrl: null,
      projectIds: ["project-1"],
      signals: { typeCount: 0 },
    },
    {
      id: "unnamed-contact",
      name: null,
      title: null,
      titleRestricted: false,
      persona: "technical_evaluator",
      roleOnCommittee: { value: "technical_evaluator", confidence: 0.71 },
      linkedinUrl: null,
      projectIds: ["project-1"],
      signals: { typeCount: 0 },
    },
  ] as const;
  const repository = createHttpAccountContactsRepository(async (path) => {
    paths.push(path);
    if (path.endsWith("/contacts")) {
      return { data: rows, meta: { total: rows.length } };
    }
    const requestedId = path.split("/").at(-1);
    const row = rows.find((candidate) => candidate.id === requestedId);
    if (!row) return null;
    return {
      ...row,
      accountId: "account-1",
      accountName: "Account One",
      professionalFacts: [],
      evidence: [],
      redirectedFrom: null,
    };
  });

  const contacts = await repository.list("account-1");
  const details = await Promise.all(
    contacts.map((contact) => repository.get("account-1", contact.id)),
  );

  assert.deepEqual(paths, [
    "/accounts/account-1/contacts",
    "/accounts/account-1/contacts/named-contact",
    "/accounts/account-1/contacts/withheld-contact",
    "/accounts/account-1/contacts/unnamed-contact",
  ]);
  assert.equal(contacts.length, 3);
  assert.equal(contacts[1]?.titleRestricted, true);
  assert.equal(contacts[2]?.name, null);
  assert.deepEqual(
    details.map((detail) => detail?.id),
    contacts.map((contact) => contact.id),
  );
  assert.ok(details.every((detail) => detail?.accountId === "account-1"));
});

test("a stale merged Contact URL resolves visibly to its survivor", async () => {
  const repository = createHttpAccountContactsRepository(async () => ({
    id: "surviving-contact",
    name: "Dana Buyer",
    title: null,
    titleRestricted: false,
    persona: "economic_buyer",
    roleOnCommittee: { value: "economic_buyer", confidence: null },
    linkedinUrl: null,
    projectIds: ["project-1"],
    signals: { typeCount: 0 },
    accountId: "account-1",
    accountName: "Account One",
    professionalFacts: [],
    evidence: [],
    redirectedFrom: "merged-contact",
  }));

  const detail = await repository.get("account-1", "merged-contact");

  assert.equal(detail?.id, "surviving-contact");
  assert.equal(detail?.redirectedFrom, "merged-contact");
});

test("unserved workspace tabs contain no runtime demo data", async () => {
  const workspace = await getAccountWorkspace("account-1");

  assert.deepEqual(workspace, {
    accountId: "account-1",
    insights: [],
    artifacts: [],
    activity: [],
  });
});
