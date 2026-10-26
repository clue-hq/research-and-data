import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "../data/workspace.fixture";
import { createV2MailFixture } from "../data/mail.fixture";
import { accountRows, queryAccounts, selectedVisibleIds } from "./account-list";
import { assignAccountOwners } from "./workspace";

test("one thousand accounts remain bounded, sorted and searchable across pages", () => {
  const data = createWorkspaceFixture(1000);
  const rows = accountRows(data, createV2MailFixture());
  const first = queryAccounts(rows, { page:1, pageSize:25 });
  const second = queryAccounts(rows, { page:2, pageSize:25 });
  assert.equal(first.total,1000);
  assert.equal(first.items.length,25);
  assert.equal(first.pages,40);
  assert.equal(new Set([...first.items,...second.items].map((r) => r.account.id)).size,50);
  const last = queryAccounts(rows,{ page:999, pageSize:25 });
  assert.equal(last.page,40);
  assert.equal(last.items.length,25);
  assert.equal(queryAccounts(rows,{ search:"Northstar", page:40 }).items[0].account.name,"Northstar Systems");
  assert.equal(queryAccounts(rows,{ search:"no-such-account" }).total,0);
});
test("status filters and explicit page selection do not select hidden accounts", () => {
  const rows = accountRows(createWorkspaceFixture(1000),createV2MailFixture());
  const page = queryAccounts(rows,{ status:"review",pageSize:25 });
  assert.equal(page.total,2);
  assert.ok(page.items.every((r) => ["review","address"].includes(r.status)));
  assert.deepEqual(selectedVisibleIds(["missing",page.items[0].account.id],page.items),[page.items[0].account.id]);
  const sorted = queryAccounts(rows,{ ownerId:"alex",sort:"name",pageSize:50 });
  assert.ok(sorted.items.every((r) => r.account.ownerId === "alex"));
  assert.equal(sorted.items.length,50);
});
test("bulk ownership is atomic, revision guarded and leaves sender identity intact", () => {
  const state = createWorkspaceFixture(1000), picked = state.accounts.slice(0,25).map(({id,revision}) => ({id,revision}));
  const next = assignAccountOwners(state,picked,"jamie");
  assert.ok(next.accounts.slice(0,25).every((a) => a.ownerId === "jamie"));
  assert.equal(next.accounts[0].senderId,state.accounts[0].senderId);
  assert.deepEqual(next.accounts.slice(25),state.accounts.slice(25));
  assert.throws(() => assignAccountOwners(state,[picked[0],{...picked[1],revision:99}],"jamie"),/changed/);
  assert.equal(state.accounts[0].ownerId,"alex");
  assert.throws(() => assignAccountOwners(state,state.accounts.slice(0,101),"jamie"),/100/);
  assert.equal(state.accounts[0].revision,1);
  assert.throws(() => assignAccountOwners(next,picked,"alex"),/changed/);
  assert.equal(next.accounts[0].ownerId,"jamie");
  assert.throws(() => assignAccountOwners(state,picked,"unknown"),/owner/);
});

test("one thousand prepared mailers and their artifacts stay bounded and correctly linked", () => {
  const data = createWorkspaceFixture(1000);
  const mail = createV2MailFixture();
  const original = mail.mailers.find((mailer) => mailer.id === "mailer-avery")!;
  const asset = data.artifacts.find((item) => item.kind === "page")!;
  mail.mailers = data.accounts.map((account, index) => {
    account.mailerId = `scale-mailer-${index}`;
    return { ...structuredClone(original), id: account.mailerId, addressConfirmed: true };
  });
  data.artifacts = data.accounts.map((account) => ({ ...asset, id: `page-${account.id}`, accountId: account.id }));
  const page = queryAccounts(accountRows(data, mail), { status: "review", page: 40, pageSize: 25 });
  assert.equal(page.total, 1000);
  assert.equal(page.items.length, 25);
  assert.ok(page.items.every((row) => row.mailer?.id === row.account.mailerId));
  assert.ok(page.items.every((row) => row.artifacts.length === 1 && row.artifacts[0].accountId === row.account.id));
});
