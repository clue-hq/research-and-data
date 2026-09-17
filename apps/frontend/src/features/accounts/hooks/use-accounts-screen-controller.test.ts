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
import { accountsForProject } from "../model/project-accounts";
import { addSelectedAccountsToProject } from "../data/bulk-actions.repository";
import {
  EMAIL_LOOKUP_POLL_LIMIT,
  EMAIL_LOOKUP_TIMEOUT_MESSAGE,
  followContactEmailLookup,
} from "../data/contact-email-lookup.repository";
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

test("searching, filtering and sorting never clear the selection (design build)", () => {
  // The pre-lift apps controller cleared the selection on every view change.
  // The design build does not: a filter is not a deselection.
  assert.doesNotMatch(controller, /function setSearch\(/);
  assert.doesNotMatch(controller, /function setFilters\(/);
  assert.doesNotMatch(controller, /function setSort\(/);
  assert.match(controller, /const \[search, setSearch\] = useState/);
  assert.match(controller, /const \[filters, setFilters\] = useState/);
  assert.match(controller, /const \[sort, setSort\] = useState/);

  // Selection is cleared in exactly two places: the explicit control, and a
  // successful add-to-project. The declaration plus that one call site is the
  // whole of `clearSelection` in the controller — creating an account, paging,
  // searching and filtering all leave it alone.
  assert.equal(controller.match(/clearSelection\(\)/g)?.length, 2);
  assert.match(controller, /function clearSelection\(\)/);
  assert.match(
    controller,
    /setAccountRows\(outcome\.rows\);\s*\n\s*setBulkNotice\(outcome\.notice\);\s*\n\s*clearSelection\(\);/,
  );
  assert.match(screen, /onClick=\{controller\.clearSelection\}/);

  // A row the current view hides keeps its checkbox but is not acted on.
  assert.match(controller, /visibleSelectedAccountIds/);
  assert.match(
    controller,
    /accountIds: \[\.\.\.visibleSelectedAccountIds\]/,
  );
  assert.match(screen, /controller\.visibleSelectedAccountIds\.size/);
  assert.match(
    screen,
    /selectedAccountIds=\{controller\.selectedAccountIds\}/,
  );
});

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
    "ABM Q4: 1 added · 1 already in project",
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
  assert.match(lookupController, /followContactEmailLookup/);
  assert.match(lookupController, /isEmailLookupPending/);
  assert.doesNotMatch(lookupController, /setTimeout\(\(\) => setState\("complete"\)/);

  assert.equal(isEmailLookupPending(pending), true);
  for (const state of ["available", "not_found", "withheld", "unavailable", "failed"] as const) {
    assert.equal(isEmailLookupPending({ ...pending, state }), false);
  }
  assert.equal(isEmailLookupPending(null), false);
});

test("a lookup that never settles stops at the ceiling and says so", async () => {
  const polls: string[] = [];
  const phases: string[] = [];
  const outcome = await followContactEmailLookup(
    { accountId: "account-1", contactId: "contact-1", lookupId: "lookup-1" },
    (phase) => phases.push(phase.kind === "error" ? phase.message : phase.kind),
    {
      // A poll that stays pending forever, and no real waiting.
      poll: async (_accountId, _contactId, lookupId) => {
        polls.push(lookupId);
        return pending;
      },
      wait: async () => {},
    },
  );

  assert.equal(EMAIL_LOOKUP_POLL_LIMIT, 40);
  assert.equal(polls.length, EMAIL_LOOKUP_POLL_LIMIT);
  assert.ok(polls.every((lookupId) => lookupId === "lookup-1"));
  assert.equal(outcome, "exhausted");
  assert.equal(phases.at(-1), EMAIL_LOOKUP_TIMEOUT_MESSAGE);
  assert.equal(
    EMAIL_LOOKUP_TIMEOUT_MESSAGE,
    "Email lookup is taking longer than expected — try again later",
  );
  // The design build's control keeps showing its error state for it.
  assert.equal(
    presentEmailLookup({
      kind: "error",
      lookup: pending,
      message: EMAIL_LOOKUP_TIMEOUT_MESSAGE,
    }).state,
    "error",
  );
});

test("a lookup that settles stops polling immediately", async () => {
  let calls = 0;
  const outcome = await followContactEmailLookup(
    { accountId: "account-1", contactId: "contact-1", lookupId: "lookup-1" },
    () => {},
    {
      poll: async () => {
        calls += 1;
        return available;
      },
      wait: async () => {},
    },
  );

  assert.equal(calls, 1);
  assert.equal(outcome, "settled");
});

test("an unmounted row stops polling and a 401 is reported, not rendered", async () => {
  let calls = 0;
  let live = true;
  const cancelledOutcome = await followContactEmailLookup(
    { accountId: "account-1", contactId: "contact-1", lookupId: "lookup-1" },
    () => {},
    {
      cancelled: () => !live,
      poll: async () => {
        calls += 1;
        live = false;
        return pending;
      },
      wait: async () => {},
    },
  );
  assert.equal(calls, 1);
  assert.equal(cancelledOutcome, "cancelled");

  const expired = await followContactEmailLookup(
    { accountId: "account-1", contactId: "contact-1", lookupId: "lookup-1" },
    () => assert.fail("an expired session is not a lookup phase"),
    {
      poll: async () => {
        throw new ClueApiError("private upstream message", {
          code: "AUTHENTICATION_REQUIRED",
          requestId: "request-4",
          status: 401,
        });
      },
      wait: async () => {},
    },
  );
  assert.equal(expired, "session_expired");
  assert.match(lookupController, /session_expired/);
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

// ---------------------------------------------------------------------------
// Project scoping and the real membership write (founder ruling 2)
// ---------------------------------------------------------------------------

const projectScreen = source("../components/project-target-accounts.tsx");

test("a project-scoped controller reads only that project's rows", () => {
  // The hook cannot be mounted here (no DOM, no React renderer), so the wiring
  // is read from source — the convention this file already uses. What the
  // scoping actually computes is `accountsForProject`'s predicate, asserted
  // against real rows in `model/project-accounts.test.ts`.
  assert.match(controller, /options\?: \{ project\?: AccountProject \}/);
  assert.match(controller, /const project = options\?\.project;/);
  assert.match(
    controller,
    /const scopedAccounts = useMemo\(\(\) => project\s*\n\s*\? accountRows\.filter\(\(account\) => account\.projects\.some\(\(\{ id \}\) => id === project\.id\)\)\s*\n\s*: accountRows/,
  );
  // Search, filters, sort and the columns all read the scoped rows.
  assert.match(controller, /const searched = scopedAccounts\.filter\(/);
  assert.match(
    controller,
    /createAccountColumnDefinitions\(scopedAccounts\),\s*\n\s*\[scopedAccounts\],/,
  );
  assert.match(controller, /accounts: scopedAccounts,/);
  // Omitted, the workspace-wide screen is unscoped as before.
  assert.match(
    projectScreen,
    /useAccountsScreenController\(accounts, data\.bulkCapabilities, undefined, \{ project \}\)/,
  );
  assert.match(screen, /useAccountsScreenController\(accounts, bulkCapabilities\)/);
});

test("addAccounts appends the rows the screen does not have, stamping nothing itself", () => {
  // The rows arrive already reflecting what the backend accepted, so nothing
  // here invents a membership.
  assert.match(controller, /function addAccounts\(added: AccountRow\[\]\) \{/);
  assert.doesNotMatch(controller, /projects: \[\.\.\.account\.projects, project\]/);
  // Only rows the screen does not already hold are appended…
  assert.match(
    controller,
    /setAccountRows\(\(current\) => \[\.\.\.current, \.\.\.added\.filter\(\(account\) => !current\.some\(\(\{ id \}\) => id === account\.id\)\)\]\);/,
  );
  // …and the columns widen to whatever custom variables they carry.
  assert.match(controller, /const definitions = createAccountColumnDefinitions\(added\);/);
  assert.match(controller, /setColumnOrder\(\(current\) => \[\.\.\.current, \.\.\.definitions\.map/);
  assert.match(controller, /setColumnWidths\(\(current\) => \(\{ \.\.\.createAccountColumnWidths\(definitions\), \.\.\.current \}\)\);/);
  assert.match(controller, /setVisibleColumns\(\(current\) => \(\{ \.\.\.createAccountColumnVisibility\(definitions\), \.\.\.current \}\)\);/);

  // A stamped row is exactly what `accountsForProject` then keeps — the same
  // predicate the scoped read uses, so the row appears in the project table.
  const stamped: Account = {
    ...servedAccount,
    projects: [...servedAccount.projects, { id: project.id, name: project.name }],
  };
  assert.deepEqual(accountsForProject([servedAccount, stamped], project.id), [stamped]);
});

test("Add accounts reflects only the picks the server accepted", async () => {
  // The dialog's local-only add is not lifted: the picks go through the same
  // action the Accounts screen submits (`addSelectedAccountsToProject`), and
  // the rows the controller then appends are that action's own reflection — a
  // partially applied write shows exactly the part that applied.
  const picked = [
    servedAccount,
    { ...servedAccount, id: "account-2" },
    { ...servedAccount, id: "account-3" },
  ];
  const result = response({ completed: 1, unchanged: 1, failed: 1 }, [
    { subjectId: "account-1", outcome: "completed", reasonCode: null },
    { subjectId: "account-2", outcome: "failed_terminal", reasonCode: null },
    { subjectId: "account-3", outcome: "unchanged", reasonCode: null },
  ]);
  const outcome = await addSelectedAccountsToProject(
    {
      accountIds: picked.map(({ id }) => id),
      idempotencyKey: "attempt-1",
      // The tab knows its own project; it is not a picker option.
      project: { id: project.id, name: project.name },
      rows: picked,
    },
    async () => result,
  );

  assert.equal(outcome.status, "added");
  const rows = outcome.status === "added" ? outcome.rows : [];
  assert.deepEqual(rows, reflectAddToProject(picked, project, result));
  // The refused pick gains nothing, so the project's scoped view never shows it.
  assert.deepEqual(
    accountsForProject(rows, project.id).map(({ id }) => id),
    ["account-1", "account-3"],
  );
  assert.equal(outcome.status === "added" ? outcome.notice : null, "ABM Q4: 1 added · 1 already in project · 1 failed");
  // The controller appends that reflection and surfaces that notice.
  assert.match(controller, /setBulkNotice\(outcome\.notice\);\s*\n\s*if \(outcome\.status === "refused"\) return false;\s*\n\s*addAccounts\(outcome\.rows\);/);
  assert.doesNotMatch(projectScreen, /data\/bulk-actions\.repository/);
});

test("an expired session on Add accounts stamps nothing and sends the operator to sign-in", async () => {
  const picked = [servedAccount];
  const outcome = await addSelectedAccountsToProject(
    {
      accountIds: ["account-1"],
      idempotencyKey: "attempt-1",
      project: { id: project.id, name: project.name },
      rows: picked,
    },
    async () => {
      throw new ClueApiError("private upstream message", {
        code: "AUTHENTICATION_REQUIRED",
        requestId: "request-4",
        status: 401,
      });
    },
  );

  // No rows come back at all, so there is nothing to stamp — the 401 is not a
  // "try again", and the picked row keeps exactly the memberships it had.
  assert.deepEqual(outcome, { status: "session_expired" });
  assert.deepEqual(picked[0]?.projects, servedAccount.projects);
  assert.match(
    controller,
    /if \(outcome\.status === "session_expired"\) \{\s*\n\s*window\.location\.assign\("\/sign-in\?reason=session_expired"\);\s*\n\s*return false;\s*\n\s*\}/,
  );
});

test("the Add accounts screen reacts to the write, and nothing else", () => {
  // A refusal changes no row, and the screen says so with the same alert block
  // its load failure uses.
  assert.match(
    projectScreen,
    /if \(await controller\.submitAddAccounts\(accounts\)\) \{\s*\n\s*setAddFailed\(false\);\s*\n\s*onReread\(\);\s*\n\s*return;\s*\n\s*\}\s*\n\s*setAddFailed\(true\);/,
  );
  assert.match(projectScreen, /role="alert"[\s\S]*?Unable to add accounts/);
  // Success re-reads the served pool so it stops offering a row now in the project.
  assert.match(projectScreen, /setData\(ProjectAccountsResponseSchema\.parse\(await response\.json\(\)\)\);/);
});
