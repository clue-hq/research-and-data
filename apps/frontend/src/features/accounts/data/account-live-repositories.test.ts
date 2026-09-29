import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  createHttpAccountContactsRepository,
  getAccountContact,
  getAccountContacts,
} from "./account-contacts.repository";
import {
  createHttpAccountDetailsRepository,
  getAccountDetails,
} from "./account-details.repository";
import {
  createHttpAccountWorkspaceRepository,
  getAccountWorkspace,
} from "./account-workspace.repository";
import {
  ACCOUNTS_PAGE_CAP,
  ACCOUNTS_PAGE_LIMIT,
  createHttpAccountsRepository,
  getAccounts,
} from "./accounts.repository";
import { ClueApiError, type fetchRead } from "./frontend-api";
import { accountsFixtureMode } from "./repository-mode";

// --- the doubles ------------------------------------------------------------------------------

type ReadCall = {
  path: string;
  searchParams: Record<string, string | number | undefined>;
  recordNotFoundAllowed: boolean;
};

/**
 * A `fetchRead` double that records every request and answers from a queue.
 *
 * The repositories are tested through their own factories, so nothing here
 * touches the network, the authenticated request seam, or `process.env`.
 */
function recordingRead(
  answers: ReadonlyArray<unknown | (() => unknown)>,
): { read: typeof fetchRead; calls: ReadCall[] } {
  const calls: ReadCall[] = [];
  let index = 0;
  const read = (async (path, options = {}) => {
    calls.push({
      path,
      searchParams: options.searchParams ?? {},
      recordNotFoundAllowed: options.recordNotFoundAllowed ?? false,
    });
    const answer = answers[Math.min(index, answers.length - 1)];
    index += 1;
    return typeof answer === "function" ? (answer as () => unknown)() : answer;
  }) as typeof fetchRead;
  return { read, calls };
}

function refusingRead(error: unknown): typeof fetchRead {
  return (async () => {
    throw error;
  }) as typeof fetchRead;
}

const UPSTREAM_FAILURE = new ClueApiError("upstream unavailable", {
  code: "SERVICE_UNAVAILABLE",
  requestId: "req-live",
  status: 503,
});

// --- minimal contract-v1 payloads -------------------------------------------------------------

function accountRow(id: string, name: string) {
  return {
    id,
    name,
    logoPath: null,
    websiteUrl: "https://zafran.io",
    researchStatus: "completed",
    overallFit: "High",
    fitScore: 88,
    revenueBand: "$10M–$50M",
    employeeBand: "51–200",
    locationCount: 2,
  };
}

const ACCOUNT_DETAIL = {
  id: "account-1",
  name: "Zafran Security",
  previewTitle: "Zafran Security",
  logoPath: null,
  websiteUrl: "https://zafran.io",
  websiteLabel: "zafran.io",
  researchStatus: "completed",
  headcountLabel: "51–200",
  locationsLabel: "Tel Aviv",
  revenueLabel: "$10M–$50M",
  fitScore: 88,
  createdAt: "2026-01-01T00:00:00Z",
  lastModifiedAt: "2026-01-02T00:00:00Z",
  overallFit: "High",
  fitCriteria: [],
  contacts: [],
  insights: [],
  activity: [],
};

const ACCOUNT_WORKSPACE = {
  accountId: "account-1",
  insights: [],
  artifacts: [],
  activity: [],
};

const CONTACT_SUMMARY = {
  id: "contact-1",
  name: "Nick Fisher",
  title: "Chief Technology Officer",
  persona: "Technical evaluator",
  personaTone: "blue",
  influence: "High",
  emailStatus: "lookup",
  socials: [],
};

const CONTACT_DETAIL = {
  ...CONTACT_SUMMARY,
  accountId: "account-1",
  accountName: "Zafran Security",
  accountLogoPath: null,
  recentSignalsLabel: "Last 90 days",
  linkedinLabel: "in/nickfisher",
  linkedinUrl: "https://www.linkedin.com/in/nickfisher",
  evidence: [],
  lastModifiedAt: "2026-01-02T00:00:00Z",
};

/**
 * What a repository actually receives for a permitted record 404.
 *
 * `fetchRead` classifies the `ACCOUNT_NOT_FOUND` / `CONTACT_NOT_FOUND` envelope
 * itself (`frontend-api.test.ts` owns that rule) and resolves to `null`; the
 * repositories only ever see this value, so the double answers with it.
 */
const RECORD_NOT_FOUND = null;

// --- E1: the accounts list --------------------------------------------------------------------

test("E1 pages through nextCursor at limit=200 and concatenates in server order", async () => {
  const { read, calls } = recordingRead([
    {
      data: [accountRow("a1", "Alpha"), accountRow("a2", "Beta")],
      meta: { total: 3, nextCursor: "cursor-2" },
    },
    { data: [accountRow("a3", "Gamma")], meta: { total: 3, nextCursor: null } },
  ]);

  const response = await createHttpAccountsRepository(read).list();

  assert.deepEqual(
    response.data.map((account) => account.name),
    ["Alpha", "Beta", "Gamma"],
  );
  assert.deepEqual(response.meta, { total: 3, nextCursor: null });
  assert.equal(calls.length, 2);
  assert.equal(calls[0]!.path, "/accounts");
  // The surface serves one contract, so no selector is sent (removed 2026-09-09).
  assert.equal(calls[0]!.searchParams.contract, undefined);
  assert.equal(calls[0]!.searchParams.limit, ACCOUNTS_PAGE_LIMIT);
  assert.equal(ACCOUNTS_PAGE_LIMIT, 200);
  assert.equal(calls[0]!.searchParams.cursor, undefined);
  assert.equal(calls[1]!.searchParams.cursor, "cursor-2");
});

test("E1 stops at the page cap and returns what it has", async () => {
  const { read, calls } = recordingRead([
    () => ({
      data: [accountRow("a", "Endless")],
      meta: { total: 100_000, nextCursor: "always-more" },
    }),
  ]);

  const response = await createHttpAccountsRepository(read).list();

  assert.equal(ACCOUNTS_PAGE_CAP, 25);
  assert.equal(calls.length, ACCOUNTS_PAGE_CAP);
  assert.equal(response.data.length, ACCOUNTS_PAGE_CAP);
  // The truncated read still reports the server's own total; the cursor is
  // dropped because the browser table pages over the returned rows, not the API.
  assert.deepEqual(response.meta, { total: 100_000, nextCursor: null });
});

test("E1 forwards the one server-side filter and never the browser-side knobs", async () => {
  const { read, calls } = recordingRead([
    { data: [], meta: { total: 0, nextCursor: null } },
  ]);

  await createHttpAccountsRepository(read).list({
    projectId: "custom-reports",
    search: "zafran",
    sort: "name_asc",
  });

  assert.equal(calls[0]!.searchParams.projectId, "custom-reports");
  assert.equal(calls[0]!.searchParams.search, undefined);
  assert.equal(calls[0]!.searchParams.sort, undefined);
});

test("E1 propagates a transport failure instead of degrading to an empty list", async () => {
  await assert.rejects(
    createHttpAccountsRepository(refusingRead(UPSTREAM_FAILURE)).list(),
    (error: unknown) => error === UPSTREAM_FAILURE,
  );
});

// --- E2 / E3: account detail and workspace ----------------------------------------------------

test("E2 parses .data", async () => {
  const { read, calls } = recordingRead([{ data: ACCOUNT_DETAIL }]);

  const account = await createHttpAccountDetailsRepository(read).get(
    "account 1",
  );

  assert.equal(account?.name, "Zafran Security");
  assert.equal(calls[0]!.path, "/accounts/account%201");
  assert.equal(calls[0]!.recordNotFoundAllowed, true);
});

test("E3 parses .data and 404s to null like E2", async () => {
  const { read, calls } = recordingRead([{ data: ACCOUNT_WORKSPACE }]);

  const workspace = await createHttpAccountWorkspaceRepository(read).get(
    "account-1",
  );

  assert.equal(workspace?.accountId, "account-1");
  assert.equal(calls[0]!.path, "/accounts/account-1/workspace");
  assert.equal(calls[0]!.recordNotFoundAllowed, true);

  const missingRead = recordingRead([RECORD_NOT_FOUND]);
  assert.equal(
    await createHttpAccountWorkspaceRepository(missingRead.read).get("nope"),
    null,
  );
});

test("a missing account is null on E2, never an invented empty account", async () => {
  const { read } = recordingRead([RECORD_NOT_FOUND]);

  assert.equal(await createHttpAccountDetailsRepository(read).get("nope"), null);
});

test("E2 and E3 rethrow every other failure", async () => {
  for (const repository of [
    createHttpAccountDetailsRepository(refusingRead(UPSTREAM_FAILURE)),
    createHttpAccountWorkspaceRepository(refusingRead(UPSTREAM_FAILURE)),
  ]) {
    await assert.rejects(
      repository.get("account-1"),
      (error: unknown) => error === UPSTREAM_FAILURE,
    );
  }
});

// --- E4 / E5: contacts ------------------------------------------------------------------------

test("E4 parses data and ignores the envelope's meta.total", async () => {
  const { read, calls } = recordingRead([
    { data: [CONTACT_SUMMARY], meta: { total: 1 } },
  ]);

  const contacts = await createHttpAccountContactsRepository(read).list(
    "account-1",
  );

  assert.deepEqual(contacts?.map((contact) => contact.name), ["Nick Fisher"]);
  assert.equal(calls[0]!.path, "/accounts/account-1/contacts");
});

test("E5 parses .data", async () => {
  const { read, calls } = recordingRead([{ data: CONTACT_DETAIL }]);

  const contact = await createHttpAccountContactsRepository(read).get(
    "account-1",
    "contact 1",
  );

  assert.equal(contact?.name, "Nick Fisher");
  assert.equal(calls[0]!.path, "/accounts/account-1/contacts/contact%201");
  assert.equal(calls[0]!.recordNotFoundAllowed, true);
});

test("a missing account or contact is null on E4 and E5", async () => {
  const listRead = recordingRead([RECORD_NOT_FOUND]);
  const getRead = recordingRead([RECORD_NOT_FOUND]);

  assert.equal(
    await createHttpAccountContactsRepository(listRead.read).list("nope"),
    null,
  );
  assert.equal(
    await createHttpAccountContactsRepository(getRead.read).get(
      "account-1",
      "nope",
    ),
    null,
  );
});

test("E4 and E5 rethrow every other failure", async () => {
  const repository = createHttpAccountContactsRepository(
    refusingRead(UPSTREAM_FAILURE),
  );

  await assert.rejects(
    repository.list("account-1"),
    (error: unknown) => error === UPSTREAM_FAILURE,
  );
  await assert.rejects(
    repository.get("account-1", "contact-1"),
    (error: unknown) => error === UPSTREAM_FAILURE,
  );
});

// --- the flag and the no-fallback rule --------------------------------------------------------

function withFixtureMode<T>(value: string | undefined, body: () => T): T {
  const previous = process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  if (value === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
  else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = value;
  try {
    return body();
  } finally {
    if (previous === undefined) delete process.env.CLUE_ACCOUNTS_FIXTURE_MODE;
    else process.env.CLUE_ACCOUNTS_FIXTURE_MODE = previous;
  }
}

test("fixture mode is the exact string 'true' and nothing else", () => {
  assert.equal(withFixtureMode("true", accountsFixtureMode), true);
  for (const value of [undefined, "", "false", "TRUE", "1", "yes", " true"]) {
    assert.equal(withFixtureMode(value, accountsFixtureMode), false);
  }
});

test("with the flag off an empty backend stays empty — no fixture ever stands in", async () => {
  const empty = recordingRead([{ data: [], meta: { total: 0, nextCursor: null } }]);
  const missing = recordingRead([RECORD_NOT_FOUND]);
  const emptyContacts = recordingRead([{ data: [], meta: { total: 0 } }]);

  const [accounts, detail, workspace, contacts] = await withFixtureMode(
    undefined,
    () =>
      Promise.all([
        getAccounts(undefined, empty.read),
        getAccountDetails("zafran-security", missing.read),
        getAccountWorkspace("zafran-security", missing.read),
        getAccountContacts("zafran-security", emptyContacts.read),
      ]),
  );

  assert.deepEqual(accounts, { data: [], meta: { total: 0, nextCursor: null } });
  assert.equal(detail, null);
  assert.equal(workspace, null);
  assert.deepEqual(contacts, []);
});

test("with the flag off every read surfaces the transport failure, never a fixture", async () => {
  const reads: ReadonlyArray<readonly [string, () => Promise<unknown>]> = [
    ["accounts", () => getAccounts(undefined, refusingRead(UPSTREAM_FAILURE))],
    [
      "account details",
      () => getAccountDetails("zafran-security", refusingRead(UPSTREAM_FAILURE)),
    ],
    [
      "account workspace",
      () =>
        getAccountWorkspace("zafran-security", refusingRead(UPSTREAM_FAILURE)),
    ],
    [
      "account contacts",
      () =>
        getAccountContacts("zafran-security", refusingRead(UPSTREAM_FAILURE)),
    ],
    [
      "contact detail",
      () =>
        getAccountContact(
          "zafran-security",
          "nick-fisher",
          refusingRead(UPSTREAM_FAILURE),
        ),
    ],
  ];

  for (const [label, read] of reads) {
    await withFixtureMode(undefined, () =>
      assert.rejects(
        read,
        (error: unknown) => error === UPSTREAM_FAILURE,
        `the live ${label} read must fail loudly`,
      ),
    );
  }
});

test("with the flag on the fixtures answer the same entry points", async () => {
  const [accounts, detail] = await withFixtureMode("true", () =>
    Promise.all([getAccounts(), getAccountDetails("zafran-security")]),
  );

  assert.ok(accounts.data.length > 0);
  assert.equal(detail?.id, "zafran-security");
});

// --- static guards ----------------------------------------------------------------------------

function featureSources(): ReadonlyArray<readonly [string, string]> {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const files: Array<readonly [string, string]> = [];
  const walk = (directory: string, prefix: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = `${directory}/${entry.name}`;
      const label = `${prefix}${entry.name}`;
      if (entry.isDirectory()) walk(path, `${label}/`);
      else if (/\.(ts|tsx)$/.test(entry.name))
        files.push([label, readFileSync(path, "utf8")]);
    }
  };
  walk(root, "");
  return files;
}

test("the accounts feature never reads the base-URL environment variable", () => {
  // Assembled rather than written out so this guard does not report itself.
  const baseUrlEnv = ["CLUE", "API", "BASE", "URL"].join("_");
  const offenders = featureSources()
    .filter(([, source]) => source.includes(baseUrlEnv))
    .map(([label]) => label);

  // The feature talks to the backend through the same-origin BFF and the
  // authenticated server request; a base-URL read would be a second transport.
  assert.deepEqual(offenders, []);
});

test("the fixture flag is read in exactly one module", () => {
  const offenders = featureSources()
    .filter(
      ([label, source]) =>
        source.includes("CLUE_ACCOUNTS_FIXTURE_MODE") &&
        label !== "data/repository-mode.ts" &&
        !label.endsWith(".test.ts"),
    )
    .map(([label]) => label);

  assert.deepEqual(offenders, []);
});

test("research reads preserve exact project context and provisional membership", async () => {
  const context = { projectId: "project / clinical", contextId: "e22896f9-85b9-46b1-8001-3243f18c1c1e" };
  const quality = { projectId: context.projectId, contextId: context.contextId,
    qualityState: "provisional", refreshPending: true, gaps: ["Employment remains unresolved"],
    contexts: [{ ...context, projectName: "Clinical intake", accountId: "account-1" }] };
  const { read, calls } = recordingRead([
    { data: { ...ACCOUNT_DETAIL, overviewDisplay: { page: "overview", sections: [], researchQuality: quality } } },
    { data: { ...ACCOUNT_WORKSPACE, insightsDisplay: { page: "insights", sections: [], researchQuality: quality } } },
    { data: [{ ...CONTACT_SUMMARY, influence: null, membershipState: "needs_verification", outreachEligible: false, membershipGaps: quality.gaps }] },
    { data: { ...CONTACT_DETAIL, influence: null, membershipState: "needs_verification", outreachEligible: false,
      contactDisplay: { page: "contact", sections: [], researchQuality: quality } } },
  ]);
  const account = await createHttpAccountDetailsRepository(read).get("account-1", context);
  const workspace = await createHttpAccountWorkspaceRepository(read).get("account-1", context);
  const contacts = await createHttpAccountContactsRepository(read).list("account-1", context);
  const contact = await createHttpAccountContactsRepository(read).get("account-1", "contact-1", context);
  for (const call of calls) {
    const url = new URL(call.path, "http://test");
    assert.equal(url.searchParams.get("projectId"), context.projectId);
    assert.equal(url.searchParams.get("contextId"), context.contextId);
  }
  assert.equal(account?.overviewDisplay?.researchQuality?.qualityState, "provisional");
  assert.equal(workspace?.insightsDisplay?.researchQuality?.contexts[0]?.projectName, "Clinical intake");
  assert.equal(contacts?.[0]?.outreachEligible, false);
  assert.equal(contact?.membershipState, "needs_verification");
  assert.equal(contact?.influence, null);
  assert.equal(contacts?.[0]?.influence, null);
});
