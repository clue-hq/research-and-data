import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createWorkspaceFixture } from '../../orchestration/data/workspace.fixture';
import { createV2MailFixture } from '../../orchestration/data/mail.fixture';
import { withMaterialsMail, withMaterialsWorkspace } from '../data/materials.fixture';
import { withWalkthroughMail, withWalkthroughWorkspace } from '../data/walkthrough.fixture';
import { buildProjectLibrary, queryReviewQueue, summarizeAccountMaterials } from './project-library';
import { queryAccountLibrary } from './account-library';

function setup(){return {workspace:withWalkthroughWorkspace(withMaterialsWorkspace(createWorkspaceFixture(6))),mail:withWalkthroughMail(withMaterialsMail(createV2MailFixture()))};}
test('project library combines campaigns but excludes another project even for the same account',()=>{
 const {workspace,mail}=setup(); const m=structuredClone(mail.mailers[0]);
 m.id='foreign';m.projectId='other';mail.mailers.push(m);
 const rows=buildProjectLibrary(workspace.project.id,workspace,mail,[]);
 assert.ok(!rows.some(r=>r.mailer?.id==='foreign'));
 assert.equal(queryAccountLibrary(rows,{accountId:'snowflake'}).total,13);
 assert.equal(queryAccountLibrary(rows,{accountId:'snowflake',campaignId:'campaign-field-conversations'}).total,6);
 assert.equal(queryAccountLibrary(rows,{search:'Snowflake'}).total,13);
});
test('native documents and unattributed designs stay visible without invented account or campaign',()=>{
 const {workspace,mail}=setup();
 const native=[{id:'document:project/plan.md',title:'Campaign brief',createdAt:'',updatedAt:'',editedLabel:'',lastViewedAt:'',collateralType:'documents' as const,collateralTypeLabel:'Documents'}];
 const rows=buildProjectLibrary(workspace.project.id,workspace,mail,native);
 const document=rows.find(r=>r.gallery===native[0]);
 assert.ok(document);assert.equal(document.accountId,'');assert.equal(document.campaignId,null);
 assert.equal(document.kind,'file');
 assert.ok(!queryAccountLibrary(rows,{accountId:'snowflake'}).rows.includes(document));
});
test('review queue groups only a single send, keeps campaigns separate and pages recipients',()=>{
 const {workspace,mail}=setup();
 const rows=buildProjectLibrary(workspace.project.id,workspace,mail,[]);
 const result=queryReviewQueue(rows,{accountId:'snowflake'});
 assert.equal(result.total,2);
 assert.equal(new Set(result.rows.map(r=>r.mailer.campaignId)).size,2);
 assert.equal(result.rows.find(r=>r.mailer.id==='walkthrough-snowflake-morgan')?.materials.length,3);
 const all=queryReviewQueue(rows,{});
 assert.ok(all.total>100);assert.equal(all.rows.length,24);
 assert.equal(new Set(all.rows.map(r=>r.mailer.id)).size,24);
 assert.equal(queryReviewQueue(rows,{accountId:'missing'}).total,0);
});
test('account summaries count material types across campaigns, not just recipient sets',()=>{
 const {workspace,mail}=setup();const rows=buildProjectLibrary(workspace.project.id,workspace,mail,[]);
 const summary=summarizeAccountMaterials(rows).get('snowflake')!;
 assert.equal(summary.total,13);assert.equal(summary.kinds.page,4);assert.equal(summary.kinds.ad,1);
 assert.equal(summary.sendsToReview,2);
});

test('all-materials overview keeps rare types discoverable at scale with bounded previews',async()=>{
 const {libraryOverview}=await import('./project-library');
 const {workspace,mail}=setup();
 const native=[{id:'brief',title:'Project brief',createdAt:'',updatedAt:'',editedLabel:'',lastViewedAt:'',collateralType:'documents' as const,collateralTypeLabel:'Documents'}];
 const rows=buildProjectLibrary(workspace.project.id,workspace,mail,native);
 const groups=libraryOverview(rows,{});
 assert.deepEqual(groups.map(g=>g.kind),['page','ad','gift','note','file']);
 assert.ok(groups.every(g=>g.rows.length<=4));
 assert.ok(groups.find(g=>g.kind==='page')!.total>500);
 assert.equal(groups.find(g=>g.kind==='file')!.rows[0].title,'Project brief');
 assert.ok(libraryOverview(rows,{accountId:'snowflake'}).flatMap(g=>g.rows).every(r=>r.accountId==='snowflake'));
});

test('review pagination reaches different recipients and filtering resets to the first page',async()=>{
 const {libraryFilterPatch}=await import('./project-library');
 const {workspace,mail}=setup(),rows=buildProjectLibrary(workspace.project.id,workspace,mail,[]);
 const params=new URLSearchParams('libraryPage=1');
 for(const [key,value] of Object.entries(libraryFilterPatch('libraryPage','2')))if(value===null)params.delete(key);else params.set(key,value);
 const page2=queryReviewQueue(rows,{page:Number(params.get('libraryPage'))});
 assert.equal(page2.page,2);
 assert.notEqual(page2.rows[0].mailer.id,queryReviewQueue(rows,{page:1}).rows[0].mailer.id);
 assert.equal(libraryFilterPatch('materialsAccount','snowflake').libraryPage,null);
});

test('the same normalized native design feed contributes to account counts and project results',async()=>{
 const {projectGalleryItems}=await import('@/features/gallery/model/project-gallery');
 const {workspace,mail}=setup();
 const native=projectGalleryItems([{id:'native-only-design',title:'Account ad',type:'canvas',collateralType:'linkedin-ad',editedLabel:'Today',originThreadId:'thread-primary',createdAt:'2026-10-28T00:00:00Z',updatedAt:'2026-10-28T00:00:00Z',accountId:'native-only',accountName:'Native-only account'}],[]);
 const rows=buildProjectLibrary(workspace.project.id,workspace,mail,native);
 const nativeRows=rows.filter(r=>r.gallery);
 assert.equal(nativeRows.length,1);
 const summary=summarizeAccountMaterials(rows).get('native-only');
 assert.equal(summary?.total,1);
 assert.equal(queryAccountLibrary(rows,{accountId:'native-only'}).total,summary?.total);
});
