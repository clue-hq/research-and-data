import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createWorkspaceFixture } from '../../orchestration/data/workspace.fixture';
import { createV2MailFixture } from '../../orchestration/data/mail.fixture';
import { withMaterialsMail, withMaterialsWorkspace } from '../data/materials.fixture';
import { withWalkthroughMail, withWalkthroughWorkspace } from '../data/walkthrough.fixture';
import { buildAccountLibrary, queryAccountLibrary } from './account-library';

function setup() {
 return { workspace:withWalkthroughWorkspace(withMaterialsWorkspace(createWorkspaceFixture(6))), mail:withWalkthroughMail(withMaterialsMail(createV2MailFixture())) };
}
test('account library includes both campaigns and canonical pages without leaking other accounts',()=>{
 const {workspace,mail}=setup();
 const rows=buildAccountLibrary('snowflake',workspace,mail,[]);
 assert.equal(rows.length,13);
 assert.ok(rows.every(r=>r.accountId==='snowflake'));
 assert.equal(rows.filter(r=>r.kind==='page').length,4);
 assert.equal(rows.filter(r=>r.contactId==='snowflake-morgan').length,6);
 assert.equal(rows.filter(r=>r.campaignId==='campaign-field-conversations').length,6);
 assert.equal(rows.find(r=>r.kind==='ad')?.contactId,null);
 const page=rows.find(r=>r.id==='page-walkthrough-snowflake-morgan');
 assert.equal(page?.page?.mailerId,'walkthrough-snowflake-morgan');
});
test('approval remains approved after shipment and page review is version-bound',()=>{
 const {workspace,mail}=setup();
 const rows=buildAccountLibrary('snowflake',workspace,mail,[]);
 assert.equal(rows.find(r=>r.id==='gift:walkthrough-snowflake-taylor')?.status,'approved');
 assert.equal(rows.find(r=>r.id==='gift:walkthrough-snowflake-taylor')?.execution,'In transit');
 assert.equal(rows.find(r=>r.id==='page-walkthrough-snowflake-morgan')?.status,'review');
 assert.equal(rows.find(r=>r.id==='page-walkthrough-snowflake-taylor')?.execution,'Published · sample');
});
test('campaign and recipient filters keep shared ads but never pull in another campaign',()=>{
 const {workspace,mail}=setup(); const rows=buildAccountLibrary('snowflake',workspace,mail,[]);
 const found=queryAccountLibrary(rows,{campaignId:'campaign-field-conversations',contactId:'snowflake-morgan'});
 assert.equal(found.total,3);
 assert.ok(found.rows.every(r=>r.mailer?.id==='walkthrough-snowflake-morgan'));
 assert.equal(queryAccountLibrary(rows,{campaignId:'campaign-awareness',contactId:'snowflake-morgan'}).total,1);
 assert.equal(queryAccountLibrary(rows,{search:'workshop follow-up',kind:'page'}).total,2);
});
test('native account files survive missing campaign metadata and foreign file rows are excluded',()=>{
 const {workspace,mail}=setup();
 const files=[{id:'doc-one',title:'Account brief',type:'document' as const,thumbnailPath:'/preview.svg',lastEditedLabel:'Last edited Oct 24',projectName:'Another project'}, {id:'foreign',title:'Wrong account',accountId:'atlas',type:'ad' as const,thumbnailPath:'/preview.svg',lastEditedLabel:'Oct 24'}];
 const rows=buildAccountLibrary('snowflake',workspace,mail,files);
 assert.equal(rows.find(r=>r.id==='native:doc-one')?.campaignId,null);
 assert.equal(rows.find(r=>r.id==='native:doc-one')?.projectName,'Another project');
 assert.ok(!rows.some(r=>r.id==='native:foreign'));
 assert.equal(queryAccountLibrary(rows,{campaignId:'unassigned'}).total,1);
});
test('library pagination is bounded and stale links clamp to valid pages',()=>{
 const {workspace,mail}=setup(); const row=buildAccountLibrary('snowflake',workspace,mail,[])[0];
 const rows=Array.from({length:500},(_,i)=>({...row,id:String(i)}));
 const found=queryAccountLibrary(rows,{page:NaN});
 assert.equal(found.rows.length,24);assert.equal(found.page,1);
 assert.equal(queryAccountLibrary(rows,{page:999}).page,21);
});

test('legacy campaign metadata migration preserves edited drafts and exact approval snapshots',()=>{
 const {workspace,mail}=setup();
 const m=mail.mailers.find(m=>m.id==='mailer-snowflake-morgan')!;
 delete m.campaignId;m.note='My saved note';m.revision=45;
 const before=structuredClone(mail);
 const next=withMaterialsMail(mail);
 assert.equal(next.mailers.find(m=>m.id==='mailer-snowflake-morgan')?.campaignId,'campaign-gifts');
 assert.equal(next.mailers.find(m=>m.id==='mailer-snowflake-morgan')?.note,'My saved note');
 assert.equal(next.mailers.find(m=>m.id==='mailer-snowflake-morgan')?.revision,45);
 assert.deepEqual(next.mailers.map(m=>m.approval),before.mailers.map(m=>m.approval));
 assert.deepEqual(mail,before);
 assert.deepEqual(withMaterialsMail(next),next);
 assert.deepEqual(withMaterialsWorkspace(workspace),workspace);
});

test('a foreign page link cannot expose another recipient or project content',()=>{
 const {workspace,mail}=setup();
 const page=mail.pages!.find(p=>p.id==='page-walkthrough-snowflake-morgan')!;
 page.projectId='other-project';
 assert.ok(!buildAccountLibrary('snowflake',workspace,mail,[]).some(r=>r.id===page.id));
});
