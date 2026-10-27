import { test } from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceFixture } from "@/features/orchestration/data/workspace.fixture";
import { createV2MailFixture } from "@/features/orchestration/data/mail.fixture";
import { buildMaterials, queryMaterials, materialEntry } from "./materials";

test("materials join two recipients without leaking another account or stale note copies", () => {
 const workspace = createWorkspaceFixture(6), mail = createV2MailFixture();
 const a = mail.mailers[0], b = structuredClone(a);
 b.id = "second-mailer"; b.contactId = "second-contact"; b.recipient.name = "Second recipient";
 a.note = "Current canonical note"; a.revision = 18;
 mail.mailers.push(b);
 const rows = buildMaterials(workspace, mail);
 const scoped = queryMaterials(rows, { accountId:a.accountId, contactId:b.contactId });
 assert.equal(scoped.rows.filter(r => r.kind === "gift").length, 1);
 assert.ok(scoped.rows.every(r => r.accountId === a.accountId && (!r.contactId || r.contactId === b.contactId)));
 const note = rows.find(r => r.id === `note:${a.id}`)!;
 assert.equal(note.mailer?.note, "Current canonical note");
 assert.equal(note.version, 18);
 assert.equal(rows.filter(r => r.kind === "note" && r.mailer?.id === a.id).length, 1);
});

test("shared account assets remain visible for a selected recipient; other recipient pages do not", () => {
 const w=createWorkspaceFixture(6), m=createV2MailFixture();
 const a=m.mailers[0];
 w.artifacts.push({...w.artifacts[0], id:"shared",accountId:a.accountId,mailerId:null,kind:"ad"});
 const result=queryMaterials(buildMaterials(w,m),{accountId:a.accountId,contactId:a.contactId});
 assert.ok(result.rows.some(r=>r.id==="shared"));
 assert.equal(queryMaterials(buildMaterials(w,m),{accountId:"missing"}).total,0);
});

test("a thousand mailers have bounded paging and independent status/type filters", () => {
 const w=createWorkspaceFixture(6), m=createV2MailFixture();
 m.mailers=Array.from({length:1000},(_,i)=>({...structuredClone(m.mailers[0]),id:`m-${i}`,contactId:`c-${i}`,stage:"needs_review" as const}));
 const rows=buildMaterials(w,m);
 const page=queryMaterials(rows,{kind:"gift",page:40});
 assert.equal(page.total,1000); assert.equal(page.rows.length,25); assert.equal(page.page,40);
 assert.equal(queryMaterials(rows,{kind:"gift",status:"approved"}).total,0);
});


test("Snowflake migration preserves existing approvals and has distinct recipient pages", async () => {
 const {withMaterialsWorkspace,withMaterialsMail,materialAccountRows}=await import("../data/materials.fixture");
 const {accountFixtures}=await import("@/features/accounts/data/accounts.fixture");
 const w=createWorkspaceFixture(6),m=createV2MailFixture();
 m.mailers[0].note="Keep my draft";m.mailers[0].revision=42;
 const before=structuredClone(m.mailers);
 const next=withMaterialsMail(m),workspace=withMaterialsWorkspace(w);
 assert.deepEqual(next.mailers.filter(m=>!m.id.startsWith("mailer-snowflake-")),before);
 assert.deepEqual(withMaterialsMail(next),next);
 assert.deepEqual(withMaterialsWorkspace(workspace),workspace);
 const rows=buildMaterials(workspace,next),morgan=queryMaterials(rows,{accountId:"snowflake",contactId:"snowflake-morgan"}).rows;
 assert.equal(morgan.filter(r=>r.kind==="gift").length,1);
 assert.ok(morgan.some(r=>r.id==="page-snowflake-morgan"));
 assert.ok(!morgan.some(r=>r.id==="page-snowflake-taylor"));
 assert.ok(morgan.some(r=>r.id==="ad-snowflake"));
 assert.equal(materialAccountRows(accountFixtures,workspace).filter(a=>a.id==="snowflake").length,1);
});

test("entering from a table row clears a stale material deep link",()=>{
 assert.deepEqual(materialEntry({tableAccount:"account-fieldwork",routeAccount:"snowflake",routeMaterial:"page-snowflake-morgan"}),{accountId:"account-fieldwork",materialId:null});
 assert.deepEqual(materialEntry({routeAccount:"snowflake",routeMaterial:"page-snowflake-morgan"}),{accountId:"snowflake",materialId:"page-snowflake-morgan"});
});

test("Snowflake's seeded approved note describes its selected gift",async()=>{
 const {withMaterialsMail}=await import("../data/materials.fixture");
 const next=withMaterialsMail(createV2MailFixture()),taylor=next.mailers.find(m=>m.id==="mailer-snowflake-taylor")!;
 assert.ok(taylor.approval);
 assert.ok(taylor.approval.note.includes(taylor.approval.gift.name.toLowerCase()));
});
