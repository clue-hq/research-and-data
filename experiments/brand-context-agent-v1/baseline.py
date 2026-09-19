"""Read-only comparison. Baseline is deliberately excluded from agent research inputs."""
import hashlib,json
from pathlib import Path
from dotenv import dotenv_values
import psycopg
from core import Store,require_exclusive_run,now

def capture(store,env_path):
 env=dotenv_values(env_path)
 with psycopg.connect(env['CLUE_DATABASE_URL'].replace('postgresql+psycopg://','postgresql://'),options='-c default_transaction_read_only=on') as c:
  rows=c.execute("select path,status,artifact_key from brand_knowledge_document where workspace_id=%s and project_id is null order by path,version desc",('ws_feb0b0156920555c9cd85dc4533ff6ff',)).fetchall()
 base=Path(env['CLUE_STORAGE_FS_ROOT']); docs=[]; seen=set()
 for path,status,key in rows:
  if path in seen:continue
  seen.add(path);p=base/key if key else None
  body=p.read_text() if p and p.exists() else None
  docs.append({'path':path,'status':status,'body':body,'sha256':hashlib.sha256(body.encode()).hexdigest() if body else None})
 store.write('baseline/snapshot.json',{'captured_at':now(),'read_only':True,'excluded_from_research_input':True,'documents':docs})
 store.write('baseline-comparison.json',{
  'summary':f'The cloned onboarding snapshot contains {len(docs)} documents, including one proposed hotel/resort ICP and no separate buyer-persona document. Its ICP contains meaningful jobs and some uncertainty handling, but cites internal document names rather than traceable public passages. It hard-excludes STR managers into a separate profile that is absent in this snapshot. The standalone draft instead starts with guest-operations buying situations, retains STR evidence, links public sources and separates fit, readiness and urgency. This is a qualitative comparison of saved outputs, not a controlled same-model benchmark.',
  'snapshot_document_count':len(docs),'baseline_not_used_as_evidence':True,
  'remaining_risk':'The standalone draft still needs human confirmation of necessary criteria; publicly named customer jobs do not establish commercial fit or willingness to buy.'})
 print('Captured isolated baseline:',len(docs),'documents')
if __name__=='__main__':
 s=Store(Path('runs/conduit-20260919'));lock=require_exclusive_run(s);capture(s,Path('../../.env'));lock.close()
