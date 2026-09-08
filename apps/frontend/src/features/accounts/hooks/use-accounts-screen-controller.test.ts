import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";
import { AccountSchema, type Account } from "../model/account";
import {
  addToProjectNotice,
  reflectAddToProject,
  type BulkActionResponse,
  type BulkProjectOption,
} from "../model/bulk-actions";
import {
  applyEmailLookupToContact,
  isEmailLookupPending,
  presentEmailLookup,
  resolvedEmailAddress,
  type ContactEmailLookup,
} from "../model/contact-email-lookup";
import { createLocalAccount, isLocalDraftAccount } from "../model/create-account";
import { addSelectedAccountsToProject } from "../data/bulk-actions.repository";
import { ClueApiError } from "../data/clue-api-error";

// The frontend test runner is `node:test` under tsx: there is no DOM and no
// React renderer, so a hook cannot be mounted here. The controller's behaviour
// is therefore tested where it actually lives — in the injectable action and the
// pure model functions the hook composes — and the wiring itself is asserted by
// reading the source, the pattern `account-ui-contract.test.ts` already uses.

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

const controller = source("./use-accounts-screen-controller.ts");
const screen = source("../components/accounts-screen.tsx");
const table = source("../components/accounts-table.tsx");
const layout = source("../../../app/(protected)/accounts/layout.tsx");
const shell = source("../components/accounts-layout-shell.tsx");
const lookupController = source(
  "../contacts/hooks/use-email-lookup-controller.ts",
);
const contactRow = source("../contacts/components/contact-row.tsx");

const project: BulkProjectOption = {
  id: "project-1",
  name: "ABM Q4",
  status: "active",
};

const servedAccount: Account = AccountSchema.parse({
  id: "account-1",
  name: "Zafran Security",
  logoPath: null,
  websiteUrl: "https://zafran.io",
  researchStatus: "completed",
  overallFit: "High",
  fitScore: 88,
  revenueBand: "$10m_50m",
  employeeBand: "51-200",
  locationCount: 1,
  industryLabels: ["Security"],
  socials: [],
  projects: [],
  customFields: [],
});

function response(
  counts: Partial<BulkActionResponse["counts"]>,
  items: BulkActionResponse["items"],
): BulkActionResponse {
  return {
    operationId: "operation-1",
    state: "completed",
    counts: {
      requested: items.length,
      completed: 0,
      unchanged: 0,
      ineligible: 0,
      failed: 0,
      ...counts,
    },
    items,
  };
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

test("row selection is the controller's own state and a local draft is never in it", () => {
  assert.match(controller, /selectedAccountIds/);
  assert.match(controller, /function toggleAccount/);
  assert.match(controller, /function toggleAllVisibleAccounts/);
  // A local draft has no durable id, so it can never be the subject of a
  // server-side bulk action; the controller refuses to select it.
  assert.match(controller, /selectableAccountIds/);
  assert.match(controller, /isLocalDraftAccount/);

  const draft = createLocalAccount("Acme", "https://acme.example", {
    id: "person-1",
    name: "Sam Lee",
  });
  assert.equal(isLocalDraftAccount(draft), true);
  assert.equal(isLocalDraftAccount(servedAccount), false);
});

// ---------------------------------------------------------------------------
// Add to project
// ---------------------------------------------------------------------------

test("Add to project posts the selected ids and the chosen project", async () => {
  const calls: unknown[] = [];
  const outcome = await addSelectedAccountsToProject(
    {
      accountIds: ["account-1", "account-2"],
      idempotencyKey: "attempt-1",
      project,
      rows: [servedAccount],
    },
    async (input) => {
      calls.push(input);
      return response({ completed: 1, unchanged: 1 }, [
        { subjectId: "account-1", outcome: "completed", reasonCode: null },
        { subjectId: "account-2", outcome: "unchanged", reasonCode: null },
      ]);
    },
  );

  assert.deepEqual(calls, [
    {
      accountIds: ["account-1", "account-2"],
      idempotencyKey: "attempt-1",
      projectId: "project-1",
    },
  ]);
  assert.equal(outcome.status, "added");
  assert.equal(
    outcome.status === "added" ? outcome.notice : null,
    "1 added · 1 already in project",
  );
  // The controller clears the selection on exactly this outcome.
  assert.match(controller, /=== "added"/);
  assert.match(controller, /clearSelection\(\)/);
});

test("the notice is the server's own counts, never a guessed success", () => {
  assert.equal(
    addToProjectNotice({
      requested: 4,
      completed: 1,
      unchanged: 1,
      ineligible: 1,
      failed: 1,
    }),
    "1 added · 1 already in project · 1 ineligible · 1 failed",
  );
  assert.equal(
    addToProjectNotice({
      requested: 1,
      completed: 0,
      unchanged: 0,
      ineligible: 0,
      failed: 1,
    }),
    "1 failed",
  );
});

test("only completed and unchanged rows gain the project membership", () => {
  const rows = reflectAddToProject(
    [
      servedAccount,
      { ...servedAccount, id: "account-2" },
      { ...servedAccount, id: "account-3" },
      {
        ...servedAccount,
        id: "account-4",
        primaryProjectId: "project-9",
        projects: [{ id: "project-1", name: "ABM Q4" }],
      },
    ],
    project,
    response({ completed: 2, unchanged: 1, failed: 1 }, [
      { subjectId: "account-1", outcome: "completed", reasonCode: null },
      { subjectId: "account-2", outcome: "failed_terminal", reasonCode: null },
      { subjectId: "account-3", outcome: "unchanged", reasonCode: null },
      { subjectId: "account-4", outcome: "completed", reasonCode: null },
    ]),
  );

  assert.deepEqual(rows[0]?.projects, [{ id: "project-1", name: "ABM Q4" }]);
  assert.equal(rows[0]?.primaryProjectId, "project-1");
  assert.deepEqual(rows[1]?.projects, []);
  assert.deepEqual(rows[2]?.projects, [{ id: "project-1", name: "ABM Q4" }]);
  // Already a member: no duplicate, and an existing primary project stands.
  assert.deepEqual(rows[3]?.projects, [{ id: "project-1", name: "ABM Q4" }]);
  assert.equal(rows[3]?.primaryProjectId, "project-9");
});

test("an expired session is reported, not swallowed into a notice", async () => {
  const outcome = await addSelectedAccountsToProject(
    {
      accountIds: ["account-1"],
      idempotencyKey: "attempt-1",
      project,
      rows: [servedAccount],
    },
    async () => {
      throw new ClueApiError("private upstream message", {
        code: "AUTHENTICATION_REQUIRED",
        requestId: "request-1",
        status: 401,
      });
    },
  );

  assert.deepEqual(outcome, { status: "session_expired" });
  assert.match(controller, /session_expired/);
});

test("a refused or failed action surfaces a safe notice and keeps the selection", async () => {
  const refused = await addSelectedAccountsToProject(
    {
      accountIds: ["account-1"],
      idempotencyKey: "attempt-1",
      project,
      rows: [servedAccount],
    },
    async () => {
      throw new ClueApiError("private upstream message", {
        code: "PERMISSION_DENIED",
        requestId: "request-2",
        status: 403,
      });
    },
  );
  assert.deepEqual(refused, {
    status: "refused",
    notice: "You no longer have permission to add Accounts to this project.",
  });

  const failed = await addSelectedAccountsToProject(
    {
      accountIds: ["account-1"],
      idempotencyKey: "attempt-1",
      project,
      rows: [servedAccount],
    },
    async () => {
      throw new ClueApiError("private upstream message", {
        code: "SERVICE_UNAVAILABLE",
        requestId: "request-3",
        status: 503,
      });
    },
  );
  assert.equal(failed.status, "refused");
  assert.equal(
    failed.status === "refused" ? failed.notice : null,
    "The Account action could not finish. Try again to safely resume it.",
  );
});

test("the bulk bar is the design build's screen, its capabilities read in the layout", () => {
  assert.match(layout, /readAccountBulkCapabilities\(\)/);
  assert.match(shell, /bulkCapabilities=\{bulkCapabilities\}/);
  assert.match(screen, /selectedCount > 0/);
  assert.match(screen, /Add to project/);
  assert.match(screen, /addToProject\.maxItems/);
  // The design build's own CSS module and Button, not a new component file.
  assert.match(screen, /tableStyles\.selectionBar/);
  assert.doesNotMatch(screen, /from "\.\/accounts-bulk/);
});

// ---------------------------------------------------------------------------
// Send to chat
// ---------------------------------------------------------------------------

test("Send to chat hands the projects transport the same context refs as before", () => {
  assert.match(controller, /useChatTransport\(\)\.mode === "http"/);
  assert.match(screen, /useAddToChatController/);
  assert.match(screen, /objectType: "account" as const/);
  assert.match(screen, /objectId: accountId/);
  assert.match(screen, /version: null/);
  assert.match(screen, /source: "accounts"/);
  assert.match(screen, /onTransferred: controller\.clearSelection/);
  assert.match(
    screen,
    /controller\.chatHandoffAvailable &&\s*controller\.bulkCapabilities\.addToChat\.allowed/,
  );
});

// ---------------------------------------------------------------------------
// The removed bulk email action (founder ruling b)
// ---------------------------------------------------------------------------

test("no bulk email-lookup action survives anywhere in the accounts feature", () => {
  // Assembled from parts so this guard cannot report itself.
  const needles = [
    "lookup" + "ContactEmails",
    "Contact" + "BulkCapabilities",
    "read" + "ContactBulkCapabilities",
    "lookup" + "WorkEmails",
  ];
  const featureRoot = new URL("../", import.meta.url);
  const offenders: string[] = [];

  function walk(directory: URL, prefix: string) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const child = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
      if (entry.isDirectory()) {
        walk(child, `${prefix}${entry.name}/`);
        continue;
      }
      if (!entry.name.endsWith(".ts") && !entry.name.endsWith(".tsx")) continue;
      const text = readFileSync(child, "utf8");
      if (needles.some((needle) => text.includes(needle))) {
        offenders.push(`${prefix}${entry.name}`);
      }
    }
  }

  walk(featureRoot, "");
  assert.deepEqual(
    offenders.filter((path) => !path.endsWith("use-accounts-screen-controller.test.ts")),
    [],
  );
});

// ---------------------------------------------------------------------------
// The single-contact email lookup (founder ruling b keeps this one)
// ---------------------------------------------------------------------------

const pending: ContactEmailLookup = {
  lookupId: "lookup-1",
  state: "pending",
  resolution: "pending",
  emails: [],
  retryable: false,
};

const available: ContactEmailLookup = {
  lookupId: "lookup-1",
  state: "available",
  resolution: "single_source",
  emails: [{ value: "dana@zafran.io", sources: [{ key: "exa", label: "Exa" }] }],
  retryable: false,
};

test("the lookup controller starts, then polls until the lookup is terminal", () => {
  assert.match(lookupController, /startContactEmailLookup/);
  assert.match(lookupController, /pollContactEmailLookup/);
  assert.match(lookupController, /isEmailLookupPending/);
  assert.doesNotMatch(lookupController, /setTimeout\(\(\) => setState\("complete"\)/);

  assert.equal(isEmailLookupPending(pending), true);
  for (const state of ["available", "not_found", "withheld", "unavailable", "failed"] as const) {
    assert.equal(isEmailLookupPending({ ...pending, state }), false);
  }
  assert.equal(isEmailLookupPending(null), false);
});

test("a resolved lookup puts the address on the row as an available email", () => {
  assert.equal(resolvedEmailAddress(available), "dana@zafran.io");
  assert.equal(resolvedEmailAddress(pending), null);

  const contact: { emailLabel?: string; emailStatus: "available" | "lookup"; name: string } = {
    emailStatus: "lookup",
    name: "Dana",
  };
  const row = applyEmailLookupToContact(contact, available);
  assert.equal(row.emailLabel, "dana@zafran.io");
  assert.equal(row.emailStatus, "available");
  assert.match(contactRow, /applyEmailLookupToContact/);

  // Nothing is written onto the row while the lookup is still running.
  assert.deepEqual(applyEmailLookupToContact(contact, pending), {
    emailStatus: "lookup",
    name: "Dana",
  });
});

test("every lookup outcome has an honest label; a conflict is never silently narrowed", () => {
  assert.deepEqual(presentEmailLookup({ kind: "ready", lookup: null }), {
    actionable: true,
    label: "Look up",
    state: "idle",
  });
  assert.equal(
    presentEmailLookup({ kind: "requesting", lookup: null }).state,
    "loading",
  );
  assert.equal(
    presentEmailLookup({ kind: "ready", lookup: pending }).state,
    "loading",
  );
  assert.deepEqual(
    presentEmailLookup({
      kind: "error",
      lookup: null,
      message: "Email enrichment unavailable",
    }),
    { actionable: false, label: "Email enrichment unavailable", state: "error" },
  );
  assert.equal(
    presentEmailLookup({ kind: "ready", lookup: { ...pending, state: "not_found" } }).label,
    "No email found",
  );
  assert.equal(
    presentEmailLookup({ kind: "ready", lookup: { ...pending, state: "withheld" } }).label,
    "Unavailable",
  );
  assert.deepEqual(
    presentEmailLookup({
      kind: "ready",
      lookup: { ...pending, state: "failed", retryable: true },
    }),
    { actionable: true, label: "Try again", state: "error" },
  );
  // Two addresses: the row cannot show both, so neither is picked for it.
  const conflicting: ContactEmailLookup = {
    ...available,
    resolution: "conflict",
    emails: [
      ...available.emails,
      { value: "d.cohen@zafran.io", sources: [{ key: "pdl", label: "PDL" }] },
    ],
  };
  assert.equal(resolvedEmailAddress(conflicting), null);
  assert.equal(
    presentEmailLookup({ kind: "ready", lookup: conflicting }).label,
    "Multiple emails found",
  );
});

// ---------------------------------------------------------------------------
// The non-optimistic local create (founder ruling f)
// ---------------------------------------------------------------------------

test("a created account invents nothing and is marked a local draft", () => {
  const draft = createLocalAccount("Acme Robotics", "https://acme.example", {
    id: "person-1",
    name: "Sam Lee",
  });

  assert.deepEqual(
    { ...draft, id: "<generated>" },
    {
      createdBy: { id: "person-1", name: "Sam Lee" },
      employeeBand: "Unknown",
      customFields: [],
      fitScore: null,
      id: "<generated>",
      industryLabels: [],
      isLocalDraft: true,
      locationCount: 0,
      logoPath: null,
      name: "Acme Robotics",
      overallFit: null,
      owner: { id: "person-1", name: "Sam Lee" },
      primaryProjectId: null,
      projects: [],
      researchIsRefreshing: false,
      researchStatus: "not_started",
      researchStatusLabel: "Not started",
      revenueBand: "Unknown",
      socials: [],
      websiteUrl: "https://acme.example",
    },
  );

  // The draft flag is UI-only: it is not part of the wire model.
  assert.equal("isLocalDraft" in AccountSchema.parse(draft), false);
  // The row says so in text; no new component, no invented badge.
  assert.match(table, /Not saved yet/);
});
