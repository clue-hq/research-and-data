import json, pathlib, collections, datetime, statistics
BASE=pathlib.Path.cwd(); OUT=BASE/'.artifacts/research-model-evaluation-20260928'
configs=[
 ('premier-grok46-medium','arv4-insight-premier-20260928-r24','x-ai/grok-4.6','medium','Todd Greer',None,dict(head=0.104850,continuations=4.125880,exa=.208,reconciliation=0,preflight=0,total=12.513690,credits=3.1)),
 ('premier-muse-medium','arv4-insight-premier-muse-20260928-run04','meta/muse-spark-1.3','medium','Beth Smith',None,dict(head=0,continuations=0,exa=.186,reconciliation=0,preflight=0,total=2.544894,credits=2.1)),
 ('premier-muse-high','arv4-insight-premier-muse-high-20260928-run05','meta/muse-spark-1.3','high','Beth Smith','muse-high',dict(head=0,continuations=0,exa=.180,reconciliation=.100531,preflight=.00084375,total=4.18700375,credits=2.1)),
 ('premier-grok47-high','arv4-insight-premier-grok47-high-20260928-run06','x-ai/grok-4.7','high','Todd Greer','grok-high',dict(head=0,continuations=0,exa=.206,reconciliation=.15531075,preflight=.0017984,total=10.74761515,credits=.1)),
 ('premier-muse-xhigh','arv4-insight-premier-muse-xhigh-20260928-run07','meta/muse-spark-1.3','xhigh','Todd Greer','muse-xhigh',dict(head=0,continuations=0,exa=.194,reconciliation=0,preflight=.00052925,total=2.79781145,credits=1.6)),
]
def read(p,default=None):return json.loads(p.read_text()) if p.exists() else default

def dt(s):return datetime.datetime.fromisoformat(s)
def exists(p):return str(p) if p.exists() else None
runs=[]; jobs=[]
for key,folder,model,effort,person,compare,c in configs:
 root=BASE/'.artifacts'/folder; timing=read(root/'timing.json',[])
 metrics=read(BASE/'.artifacts/research-model-comparison-20260928'/compare/'metrics.json',[]) if compare else []
 indexed={x['job_id']:x for x in metrics}
 executions=read(root/'review/arv2_quality_execution.json',[]); models=read(root/'review/agent_model_call.json',[])
 runjobs=[]
 for t in sorted(timing,key=lambda x:x['subject']):
  jid=t['job_id']; subject=t['subject']; m=indexed.get(jid,t)
  execs=sorted([e for e in executions if e['job_id']==jid],key=lambda e:e['created_at'])
  first=execs[0]['execution_id'] if execs else None
  calls=[x for x in models if x['execution_id']==first]
  dossier=root/'review'/jid/'dossier.json'; d=read(dossier,{'sections':[]})
  finalfindings=[f for s in d['sections'] for f in s.get('findings',[])]
  initial=root/'account-initial/dossier.json' if subject=='account' else dossier
  initial = initial if initial.exists() else dossier
  di=read(initial,d); findings=[f for s in di['sections'] for f in s.get('findings',[])]
  out={
    'run_key':key,'scenario':'Insight Health -> Premier Gastroenterology','job_id':jid,'subject_type':subject,
    'subject_name':'Premier Gastroenterology' if subject=='account' else person,'model':model,'reasoning_effort_requested':effort,
    'status_recorded':t['status'],'started_at_utc':t['start'],'finished_at_utc':t['finish'],'elapsed_seconds':t['total_seconds'],
    'elapsed_definition':'job start to terminal timestamp; includes drafting, import, narrative and completion recovery',
    'model_calls_persisted':t['model_calls'],'model_calls_remote_only':2 if key.endswith('xhigh') and subject=='person' else 0,
    'model_usd_persisted':t['model_usd'],'model_usd_remote_only':.1167012 if key.endswith('xhigh') and subject=='person' else 0,
    'model_usd_total_recorded':t['model_usd']+(.1167012 if key.endswith('xhigh') and subject=='person' else 0),
    'model_seconds_sum':t['model_seconds_sum'],'formation_model_started_at_utc':t['formation_model_start'],
    'import_completed_at_utc':t['import_completed'],'narrative_stored_at_utc':t['narrative_stored'],
    'formation_to_import_seconds':t.get('formation_to_import_seconds'),'import_to_narrative_seconds':t.get('import_to_narrative_seconds'),
    'findings_initial':len(findings),'findings_latest':len(finalfindings),'sections_initial':len(di['sections']),
    'review_statuses_initial':dict(collections.Counter(f.get('review',{}).get('status','unspecified') for f in findings)),
    'claim_types_initial':dict(collections.Counter(f.get('claim_type') for f in findings)),
    'initial_dossier_json':exists(initial),'latest_dossier_json':exists(dossier),'latest_dossier_markdown':exists(dossier.with_suffix('.md')),
    'researcher_narrative_markdown':exists(root/('account-initial/page.md' if subject=='account' else 'person/page.md')) if t['narrative_stored'] else None,
    'final_narrative_markdown':exists(root/('account/page.md' if subject=='account' else 'person/page.md')),
    'unpublished_narrative_markdown':exists(root/'person/unpublished-narrative-draft.md') if subject=='person' else None,
    'execution_id_initial':first,'trace_ids_initial':sorted(set(x.get('langfuse_trace_id') for x in calls if x.get('langfuse_trace_id'))),
    'raw_model_receipts_path':str(root/'review/agent_model_call.json'),'timing_path':str(root/'timing.json'),
  }
  for k in ['input_tokens','output_tokens','cache_read_tokens','model_median_seconds','model_max_seconds','calls_over_60s','activity_call_counts','tool_batches','multi_tool_batches','max_batch_size','distinct_read_paths','exact_repeat_read_requests','source_records','unique_source_urls','findings_using_report','requested_acquisitions']:
   if k in m:out[k]=m[k]
  if 'input_tokens' not in out:
   out.update(input_tokens=sum(x.get('input_tokens') or 0 for x in calls),output_tokens=sum(x.get('output_tokens') or 0 for x in calls),cache_read_tokens=sum(x.get('cache_read_input_tokens') or 0 for x in calls))
  if key=='premier-muse-medium' and subject=='person':
   out.update(status_effective='cancelled_by_user',cancelled_at_utc='2026-09-28T04:56:53.960989+00:00',elapsed_until_cancel_seconds=1237.631950,elapsed_definition='No terminal timestamp; pending Exa was cancelled by user. Stale in_progress is not current activity.')
  elif key=='premier-muse-xhigh' and subject=='person':out.update(status_effective='infrastructure_interrupted',failure='Postgres volume exhausted; no authored person dossier or narrative, despite retained Exa report.')
  elif subject=='person' and key in ['premier-grok46-medium','premier-grok47-high']:
   out.update(status_effective='needs_review',failure='Durable dossier/import/narrative survived; finalization referenced account-owned committee claim from person context (missing_finalize).')
  elif key=='premier-muse-high' and subject=='person':out.update(status_effective='needs_review',failure='Contact narrative repeatedly omitted required parent dossier version; misleading old feedback; no published narrative.')
  elif key=='premier-grok47-high' and subject=='account':out.update(status_effective='needs_review',failure='No researcher narrative saved; finalization missing /outputs/research.json. Later account page written by Muse reconciliation.')
  else:out['status_effective']=t['status']
  jobs.append(out);runjobs.append(out)
 account=next(x for x in runjobs if x['subject_type']=='account');pjob=next(x for x in runjobs if x['subject_type']=='person')
 end=max(dt(x['finished_at_utc']) for x in runjobs if x['finished_at_utc'])
 overall=(end-dt(account['started_at_utc'])).total_seconds()
 if key=='premier-muse-medium':overall=1548.535502
 costs={'account_researcher_usd':account['model_usd_total_recorded'],'person_researcher_usd':pjob['model_usd_total_recorded'],'head_brief_usd':c['head'],'legacy_account_continuations_usd':c['continuations'],'exa_usd':c['exa'],'focused_reconciliation_usd':c['reconciliation'],'model_setting_preflight_usd':c['preflight'],'deepgram_usd':0,'recorded_total_usd':c['total'],'ai_ark_credits':c['credits']}
 comps=sum(v for k,v in costs.items() if k.endswith('_usd') and k!='recorded_total_usd')
 assert abs(comps-c['total'])<.000001,(key,comps,c['total'])
 caveats=['Live search results vary; this is not a fixed-corpus model evaluation.','One account and one selected person; Beth and Todd are different research subjects.','AI Ark credits are separate non-USD units, not included in dollar totals.','No transcription call was exercised.','Recorded costs are usage-ledger/provider-reported amounts, not invoice reconciliation.']
 if key=='premier-grok46-medium':caveats+=['Run started Sept 27 UTC / Sept 28 Asia/Kolkata.','Old reconciliation repeatedly continued the account; initial 52 findings versus latest 60.','Overall elapsed below ends at person terminal; worker stopped about 31m22s after initial start during a third continuation. In-flight charge may be absent.','Fresh Head briefing differs from retained Head brief used by subsequent Muse/Grok4.7 tests.']
 else:caveats+=['Reuses Head brief created by setup run01; its $0.118116 is reported once under setup_attempts, not charged again here.','Pinned persona lineage is advisory; unresolved lineage affects certainty of persona comparisons.']
 if key=='premier-muse-medium':caveats+=['Person test user-cancelled during approximately 17-minute pending Exa deep call; eventual provider charge/cancellation is unknown.','Original/default label was misleading: actual outgoing request explicitly used medium reasoning.','Total is a known recorded subtotal, not final all-in cost.']
 if key=='premier-muse-high':caveats+=['Predates narrative-version error improvement 93d87fe35; failure feedback differs from later Grok/xhigh.']
 if key=='premier-muse-xhigh':caveats+=['Person interrupted by full Postgres Docker volume, not model-quality failure.','Two model calls recovered only from Langfuse after DB recording failed; included once in total.','No complete person comparison or reconciliation result.']
 if key=='premier-grok47-high':caveats+=['Final account narrative comes from common Muse focused reconciliation, not Grok.','AI Ark person lookup subject-lock-refused; low credits do not prove cheaper successful enrichment.']
 traces=sorted(set(x.get('langfuse_trace_id') for x in models if x.get('langfuse_trace_id')))
 runs.append({'run_key':key,'root_path':str(root),'scenario':'Insight Health -> Premier Gastroenterology','model':model,'reasoning_effort_requested':effort,'revision':24,'account_job_id':account['job_id'],'person_job_id':pjob['job_id'],'person_name':person,'overall_elapsed_seconds_to_research_terminal_or_cancel':overall,'costs':costs,'caveats':caveats,'trace_ids_research_and_legacy_continuations':traces,'report_path':exists(root/'REPORT.md') or exists(root/'REVIEW-IN-PROGRESS.md') or str(BASE/'.artifacts/research-model-comparison-20260928/XHIGH.md'),'account_initial_narrative_path':account['researcher_narrative_markdown'],'person_narrative_path':pjob['researcher_narrative_markdown'],'account_final_narrative_path':account['final_narrative_markdown'],'all_jobs_completed':all(x['status_effective']=='completed' for x in runjobs),'jobs':runjobs})
for r in runs:
 trace_map={'premier-muse-high':'1dad2e49b76d56685760a078906793b7','premier-grok47-high':'67b24c401be993adce8c82581a7d4189'}
 r['focused_reconciliation_trace_ids']=[trace_map[r['run_key']]] if r['run_key'] in trace_map else []
 r['final_account_narrative_author']='meta/muse-spark-1.3 focused reconciliation' if r['run_key']=='premier-grok47-high' else ('researcher with subsequent reconciliation' if r['run_key'] in ['premier-grok46-medium','premier-muse-high'] else r['model'])
 r['research_terminal_elapsed_definition']='Initial account start to last research job terminal; excludes later reconciliation/worker shutdown. For cancelled Muse-medium, initial start to recorded cancellation.'
notes={
 'purpose':'Workbook-ready retained Premier comparison; no new research or model calls made by this audit.',
 'elapsed':'Job elapsed includes research, JSON drafting/import, narrative and completion recovery. Overlapping account/person durations must not be summed to wall time.',
 'formation':'Formation marker is model call preceding first durable section-save, not proven exact start of all claim-related thought/work.',
 'model_seconds_sum':'Not an exclusive wall-time partition; may overlap tools and include latency/retries.',
 'cost':'Only components ending _usd sum to recorded_total_usd except total itself. AI Ark credits separate; provider missing/pending billing remains unknown.',
 'traces':'Trace IDs and observable calls can be reviewed. No raw private chain-of-thought included.',
 'output_tokens':'Provider-billed output tokens may include reasoning; not a measure of narrative length.',
 'evidence_counts':'Source records include envelopes/normalized copies; unique URLs are not independent corroborating sources.',
 'findings':'Counts describe authored records, not quality. Initial snapshots preserve model-owned work before reconciliation.',
 'reasoning':'Requested effort verified from outgoing requests; does not establish amount of hidden reasoning.',
 'missing':'Null means unavailable or not produced, never a fabricated zero.',
}
setup=[{'run_key':'premier-muse-setup01','root_path':str(BASE/'.artifacts/arv4-insight-premier-muse-20260928-run01'),'status':'failed_before_research','failure':'Muse provider 403 age attestation prerequisite','head_brief_usd':.118116,'head_elapsed_seconds':64.0,'research_model_recorded_usd':None,'no_research_tools_executed':True}, {'run_key':'premier-muse-setup02','root_path':str(BASE/'.artifacts/arv4-insight-premier-muse-20260928-run02'),'status':'failed_before_research','failure':'Provider accepts only auto tool_choice','research_model_recorded_usd':None,'no_research_tools_executed':True}, {'run_key':'premier-muse-setup03','root_path':str(BASE/'.artifacts/arv4-insight-premier-muse-20260928-run03'),'status':'failed_before_research','failure':'Nested narrative tool schema exceeds provider depth limit','research_model_recorded_usd':None,'no_research_tools_executed':True}]
payload={'schema_version':1,'title':'Premier Gastroenterology / Insight Health retained model evaluation','field_notes':notes,'runs':runs,'setup_attempts':setup,'quality_review_path':str(OUT/'PREMIER-QUALITY.md')}
(OUT/'premier-model-evaluation.json').write_text(json.dumps(payload,indent=2)+'\n')
(OUT/'premier-jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')
(OUT/'premier-runs.json').write_text(json.dumps(runs,indent=2)+'\n')
print(json.dumps({'runs':len(runs),'jobs':len(jobs),'costs':{r['run_key']:r['costs']['recorded_total_usd'] for r in runs},'paths_missing_dossier':[(j['run_key'],j['subject_type']) for j in jobs if not j['initial_dossier_json']]},indent=2))
