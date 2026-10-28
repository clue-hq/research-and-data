import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pageDraftStore } from '../data/page-draft';
test('page edits survive editor unmount/reload and retain their original version',()=>{
 const data=new Map<string,string>(),storage={getItem:(key:string)=>data.get(key)??null,setItem:(key:string,value:string)=>{data.set(key,value);},removeItem:(key:string)=>{data.delete(key);}};
 const before=pageDraftStore(storage);
 before.write('page-a',{version:1,patch:{headline:'New headline'}});
 const after=pageDraftStore(storage);
 assert.deepEqual(after.read('page-a'),{version:1,patch:{headline:'New headline'}});
 assert.equal(after.read('page-b'),null);
 after.write('page-a',null);assert.equal(after.read('page-a'),null);
});
