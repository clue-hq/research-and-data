import { AccountContactSummarySchema } from '@/features/accounts/model/account-contact';
import { walkthroughAccounts } from './walkthrough.fixture';
export function walkthroughContacts(accountId:string) {
 const account=walkthroughAccounts().find(a=>a.id===accountId);
 if(!account)return null;
 return account.committee.map((person,index)=>AccountContactSummarySchema.parse({id:accountId==='snowflake'?`snowflake-${index===0?'morgan':'taylor'}`:`${accountId}-${index===0?'marketing':'operations'}`,name:person.name,title:index===0?'Field Marketing Lead':'Revenue Operations Lead',persona:index===0?'Champion':'Technical evaluator',personaTone:index===0?'olive':'blue',influence:index===0?'High':'Medium',emailStatus:'lookup',socials:[],profileAction:'none',membershipState:'supported',outreachEligible:true}));
}
