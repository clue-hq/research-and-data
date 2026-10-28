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
