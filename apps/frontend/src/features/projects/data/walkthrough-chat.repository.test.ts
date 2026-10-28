import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createChatRepositories } from './chat-repositories';
import { withWalkthroughChat } from './walkthrough-chat.repository';
import { FIXTURE_PROJECT_ID, FIXTURE_THREAD_ID } from './chat.fixture';
test('walkthrough has no old research turns to replay over its prepared outreach',async()=>{
 const repo=withWalkthroughChat(createChatRepositories());const input={projectId:FIXTURE_PROJECT_ID,threadId:FIXTURE_THREAD_ID};
 assert.equal((await repo.turns.list(input)).turns.length,0);
 assert.equal((await repo.gates.list(input)).gates.length,0);
 assert.match((await repo.messages.list(input)).messages[1].body??'',/500 accounts/);
});
