import assert from 'node:assert/strict';
import { test } from 'node:test';
import { withMaterialsWorkspace } from '@/features/account-materials/data/materials.fixture';
import { createWorkspaceFixture } from '../data/workspace.fixture';
import { approveArtifactContent } from './workspace';

test('content approval saves the exact version without changing recipient sends or other assets',()=>{
 const before=withMaterialsWorkspace(createWorkspaceFixture());
 const asset=before.artifacts.find(a=>a.id==='ad-snowflake')!;
 const after=approveArtifactContent(before,asset.id,asset.version,'2026-10-28T00:00:00Z');
 const approved=after.artifacts.find(a=>a.id===asset.id)!;
 assert.equal(approved.status,'approved');
 assert.equal(approved.contentApproval?.headline,asset.headline);
 assert.equal(approved.contentApproval?.version,asset.version);
 assert.equal(asset.status,'draft');
 assert.deepEqual(after.accounts,before.accounts);
 assert.deepEqual(after.artifacts.filter(a=>a.id!==asset.id),before.artifacts.filter(a=>a.id!==asset.id));
 assert.throws(()=>approveArtifactContent(before,asset.id,asset.version+1),/latest version/);
 assert.throws(()=>approveArtifactContent(before,'missing',1),/no longer available/);
});

test('confirmation keeps the originally previewed material identity even after selection changes',async()=>{
 const {contentApprovalRequest}=await import('./workspace');
 const before=withMaterialsWorkspace(createWorkspaceFixture());
 let selected=before.artifacts.find(a=>a.id==='ad-snowflake')!;
 const request=contentApprovalRequest(selected);
 selected=before.artifacts.find(a=>a.id!==request.id&&a.kind==='ad')!;
 assert.equal(selected.version,request.version);
 const after=approveArtifactContent(before,request.id,request.version);
 assert.equal(after.artifacts.find(a=>a.id===request.id)?.status,'approved');
 assert.equal(after.artifacts.find(a=>a.id===selected.id)?.status,selected.status);
 assert.equal(request.title,'Snowflake · Account campaign');
});
