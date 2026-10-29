import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createV2MailFixture } from '@/features/orchestration/data/mail.fixture';
import { withWalkthroughMail } from '../data/walkthrough.fixture';
import { accountOutreach, queryOutreach, outreachSelection } from './outreach';
test('one and 500 accounts use the same records and bounded account pages',()=>{
 const state=withWalkthroughMail(createV2MailFixture());
 const rows=accountOutreach(state.mailers);
 assert.equal(rows.length,500);assert.equal(rows[0].id,'snowflake');assert.equal(rows[0].recipients.length,2);
 assert.equal(queryOutreach(rows,{search:'',status:'all',page:1}).rows.length,25);
 assert.equal(queryOutreach(rows,{search:'',status:'all',page:99}).page,20);
 assert.equal(queryOutreach(rows,{search:'Snowflake',status:'all',page:20}).rows[0].recipients[0].id,'walkthrough-snowflake-morgan');
 assert.equal(queryOutreach(rows,{search:'Taylor Reed',status:'all',page:1}).total,1);
});
test('selection never shows a recipient from another account',()=>{
 const state=withWalkthroughMail(createV2MailFixture()),rows=accountOutreach(state.mailers);
 assert.equal(outreachSelection(rows,'snowflake','walkthrough-scale-account-7-taylor')?.id,'walkthrough-snowflake-morgan');
 assert.equal(outreachSelection(rows,'missing',null),undefined);
});

test('table handoff overrides old context and persists the selected account in the URL',async()=>{
 const { accountReviewQuery }=await import('./outreach');
 const old='surface=target-accounts&materialsAccount=snowflake&recipient=old-person&review=tracking&catalog=earlier&libraryReview=1&libraryPage=8&type=ad&campaign=old&librarySearch=Northstar&libraryRecipient=old-person';
 const result=new URLSearchParams(accountReviewQuery(old,'scale-account-9'));
 assert.equal(result.get('materialsAccount'),'scale-account-9');assert.equal(result.get('surface'),'gallery');
 for(const key of ['libraryReview','libraryPage','type','campaign','librarySearch','libraryRecipient'])assert.equal(result.has(key),false);
 assert.equal(result.has('recipient'),false);assert.equal(result.has('review'),false);assert.equal(result.has('catalog'),false);
});
test('legacy catalog excludes current walkthrough sends',async()=>{
 const { earlierMailers }=await import('./outreach');
 const state=withWalkthroughMail(createV2MailFixture());
 assert.ok(earlierMailers(state.mailers).length>0);
 assert.equal(earlierMailers(state.mailers).some(m=>m.campaignId==='campaign-field-conversations'),false);
});
