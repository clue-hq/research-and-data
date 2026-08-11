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

test("contacts list and detail use their independent live endpoints", async () => {
  const paths: string[] = [];
  const repository = createHttpAccountContactsRepository(async (path) => {
    paths.push(path);
    if (path.endsWith("/contacts")) {
      return {
        data: [
          {
            id: "contact-1",
            name: null,
            title: null,
            titleRestricted: true,
            persona: "blocker",
            roleOnCommittee: { value: "blocker", confidence: null },
            linkedinUrl: null,
            projectIds: [],
            signals: { typeCount: 0 },
          },
        ],
        meta: { total: 1 },
      };
    }
    return {
      id: "contact-1",
      name: null,
      title: null,
      titleRestricted: true,
      persona: "blocker",
      roleOnCommittee: { value: "blocker", confidence: null },
      linkedinUrl: null,
      projectIds: [],
      signals: { typeCount: 0 },
      accountId: "account-1",
      accountName: "Account One",
      professionalFacts: [],
      evidence: [],
      redirectedFrom: null,
    };
  });

  const contacts = await repository.list("account-1");
  const detail = await repository.get("account-1", "contact-1");

  assert.deepEqual(paths, [
    "/accounts/account-1/contacts",
    "/accounts/account-1/contacts/contact-1",
  ]);
  assert.equal(contacts.length, 1);
  assert.equal(contacts[0]?.titleRestricted, true);
  assert.equal(detail?.accountId, "account-1");
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
