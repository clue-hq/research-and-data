import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const root='/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1';
const src=path.join(root,'.artifacts/research-model-evaluation-20260928');
const out=path.join(root,'outputs/research-model-evaluation-20260928');
const read=async n=>JSON.parse(await fs.readFile(path.join(src,n),'utf8'));
const [premier,pjobs,zafran,quality,peval]=await Promise.all(['premier-runs.json','premier-jobs.json','zafran-runs.json','quality-evidence.json','premier-model-evaluation.json'].map(read));
const traceRoot='https://us.cloud.langfuse.com/project/cmu2j8vra0137ad0clp5vylx2/traces/';
const runs=[],jobs=[],links=[],failures=[],missing=[],nativeLinks=[];
const secs=(a,b)=>a&&b?(Date.parse(b)-Date.parse(a))/1000:null;
const excelTime=s=>s==null?null:s/86400;
const flat=s=>String(s??'').replaceAll('_',' ');
async function addLink(run,subject,kind,target,note='') {
  if(!target) {links.push([run,subject,kind,'Not produced / unavailable',null,note]);return;}
  if(!target.startsWith('https://')) {try{await fs.access(target);}catch{missing.push(target);return;}}
  // Keep model-call metadata and public actions inspectable; do not reproduce hidden reasoning text.
  links.push([run,subject,kind,'Open',target,note]);
}
const shortModel=m=>m.replace('x-ai/','').replace('meta/','').replace('deepseek/','').replace('z-ai/','');
const summary={
 'premier-grok46-medium':'Both dossiers and pages saved; person completion failed; old account continuations added cost.',
 'premier-muse-medium':'Account saved. Beth cancelled during prolonged Exa wait; recorded cost is a subtotal.',
 'premier-muse-high':'Both dossiers saved; Beth narrative unpublished after parent-version errors.',
 'premier-grok47-high':'Both dossiers and Todd page saved. Account page produced by separate Muse reconciliation.',
 'premier-muse-xhigh':'Account saved. Todd stopped by database disk exhaustion before dossier.',
 grok46:'All three dossiers and narratives saved; person finalization failed. Reconciliation settled.',
 grok47:'Provider capacity failure during draft. Nick and Vari never started.',
 glm53:'No authored dossier. Wrong nominations and missing final output; operator stop followed failure.',
 'glm53-untouched-02':'Untouched retry truncated at 16,384 output tokens; no authored dossier.',
 'deepseek4pro-high':'Account and Nick imported; Vari incomplete; no narratives; reconciliation failed.',
 'muse-max':'All dossiers imported; account page saved; contact pages unpublished; reconciliation failed.'
};
for(const [i,r] of premier.entries()) {
 const id=`P${i+1}`, c=r.costs, js=pjobs.filter(j=>j.run_key===r.run_key);
 const start=js[0].started_at_utc;
 const parts=[c.account_researcher_usd+c.person_researcher_usd,c.exa_usd,c.deepgram_usd,0,c.focused_reconciliation_usd,c.legacy_account_continuations_usd,c.head_brief_usd,c.model_setting_preflight_usd,0];
 const finalWall=i===0?1882:i===3?3106:r.overall_elapsed_seconds_to_research_terminal_or_cancel;
 runs.push({id,key:r.run_key,scenario:'Insight Health → Premier',model:r.model,effort:r.reasoning_effort_requested,start,wall:r.overall_elapsed_seconds_to_research_terminal_or_cancel,settledWall:finalWall,parts,total:c.recorded_total_usd,credits:c.ai_ark_credits,summary:summary[r.run_key],report:r.report_path,root:r.root_path,notes:r.caveats.join(' ')});
 for(const j of js) {
  jobs.push({id,name:j.subject_name,subject:j.subject_type,status:j.status_effective||j.status_recorded,start:j.started_at_utc,end:j.finished_at_utc||j.cancelled_at_utc,wall:j.elapsed_seconds??j.elapsed_until_cancel_seconds,pre:secs(j.started_at_utc,j.formation_model_started_at_utc),formation:j.formation_to_import_seconds,post:j.import_to_narrative_seconds,findings:j.findings_initial,latest:j.findings_latest,narrative:!!j.researcher_narrative_markdown,modelCost:j.model_usd_total_recorded,calls:j.model_calls_persisted+j.model_calls_remote_only,input:j.input_tokens,cache:j.cache_read_tokens,output:j.output_tokens,modelSeconds:j.model_seconds_sum,reads:j.activity_call_counts?.read_file??null,batches:j.multi_tool_batches??null,maxBatch:j.max_batch_size??null,readRepeats:j.exact_repeat_read_requests??null,jobId:j.job_id});
  for(const [kind,key] of [['Initial claim JSON','initial_dossier_json'],['Latest claim JSON','latest_dossier_json'],['Readable dossier','latest_dossier_markdown'],['Researcher narrative','researcher_narrative_markdown'],['Final narrative','final_narrative_markdown'],['Unpublished draft','unpublished_narrative_markdown'],['Timing audit','timing_path']]) await addLink(id,j.subject_name,kind,j[key],kind==='Final narrative'&&i===3&&j.subject_type==='account'?'Written by common Muse reconciler, not Grok.':'');
  for(const t of j.trace_ids_initial||[]) await addLink(id,j.subject_name,'Langfuse execution',traceRoot+t,'Observable model/tool activity; effort is requested configuration.');
  if(j.failure) failures.push([id,j.subject_name,'Completion / infrastructure',j.failure,'Observed; see run report',r.report_path]);
 }
 await addLink(id,'Run','Run report',r.report_path);
 for(const t of r.trace_ids_research_and_legacy_continuations||[]) await addLink(id,'Run / continuation','Langfuse trace',traceRoot+t);
 for(const t of r.focused_reconciliation_trace_ids||[]) await addLink(id,'Common Muse reconciliation','Langfuse trace',traceRoot+t);
 const comp={2:'muse-high',3:'grok-high',4:'muse-xhigh'}[i];
 for(const name of ['model-calls.csv','tool-activity.md','tool-activity.json','provider-attempts.json']) {
  const candidates=[path.join(r.root_path,name),...(comp?[path.join(root,'.artifacts/research-model-comparison-20260928',comp,name)]:[])];
  for(const p of candidates) {try{await fs.access(p);await addLink(id,'Run',name,p);break;}catch{}}
 }
 for(const name of ['all-raw/manifest.json','trace-verification.json','review/provider_call_ledger.json']) {const p=path.join(r.root_path,name);try{await fs.access(p);await addLink(id,'Run',name,p);}catch{}}
}
for(const [i,r] of zafran.runs.entries()) {
 const id=`Z${i+1}`,c=r.cost_components_usd;
 const parts=[c.researcher_model,c.exa,c.deepgram,c.embeddings,c.common_muse_reconciliation,0,0,c.preflight,c.other_providers];
 runs.push({id,key:r.id,scenario:'Clue → Zafran',model:r.model,effort:r.reasoning_effort,start:r.start,wall:r.research_wall_seconds,settledWall:r.wall_seconds,parts,total:r.known_total_usd,credits:r.ai_ark_credits,summary:summary[r.id],report:r.links.report,root:path.dirname(r.links.report),notes:`Resource revision 24; fixed Nick and Vari. ${r.end_semantics}. ${r.unpriced_researcher_calls||0} unpriced researcher call(s). Runtime may differ despite shared resource pins.`});
 for(const j of r.jobs) {
  jobs.push({id,name:j.name,subject:j.subject,status:j.status,start:j.start,end:j.end,wall:j.wall_seconds,pre:j.pre_formation_seconds,formation:j.formation_to_import_seconds,post:j.import_to_narrative_seconds,findings:j.dossier?.findings??0,latest:j.dossier?.stored??0,narrative:!!j.narrative_stored,modelCost:j.model_usd,calls:j.model_calls,input:j.input_tokens,cache:j.cache_read_input_tokens,output:j.output_tokens,modelSeconds:j.model_seconds_sum,reads:null,batches:null,maxBatch:null,readRepeats:null,jobId:j.job_id,stageCost:j.research_stage_model_plus_provider_usd});
  for(const [key,value] of Object.entries(j.links)) {
   if(key==='langfuse_traces'){for(const t of value) await addLink(id,j.name,'Langfuse execution',t);}
   else await addLink(id,j.name,flat(key),value,key==='narrative_markdown'&&j.subject==='account'?'Current stored page; initial researcher page listed separately.':'');
  }
 }
 for(const [key,value] of Object.entries(r.links)) {
  if(key==='langfuse_traces'){for(const t of value) await addLink(id,'Run / reconciliation','Langfuse trace',t);}
  else if(!['model_call_snapshot','working_tree_diff','original_model_calls_csv'].includes(key)) await addLink(id,'Run',flat(key),value,key==='current_account_narrative'?'May include common Muse reconciliation.':'');
 }
}
for(const f of zafran.failures) failures.push([runs.find(r=>r.key===f.run_id).id,f.subject_stage,f.category,f.explanation,f.confidence,f.evidence_paths[0]]);
const extraFailures=[
 ['P1','Account continuations','Backend lifecycle','Old reconciliation repeatedly continued the account and could not settle on stable inputs; $4.12588 in recorded extra model work. Worker stopped during a third continuation. Initial research and pages survived.','Observed; possible in-flight cost missing.'],
 ['P2','Beth / Exa','Provider wait + user cancellation','Person deep request remained pending roughly 17 minutes; cancelled on user instruction. Eventual provider billing is unknown. No person dossier to grade.','Observed wait; provider-side root cause unproven.'],
 ['P3','Beth narrative','Tool contract + model call arguments','Missing parent dossier version repeatedly rejected narrative writes. Misleading error feedback described a changed parent rather than a missing argument.','Confirmed; corrected in later runtime.'],
 ['P4','Account finalization','Backend recovery + incomplete final output','Grok did not save its own account narrative or required final output file. Final page was generated by separate Muse reconciliation.','Confirmed missing output; not a Grok narrative sample.'],
 ['P4','Todd enrichment','Subject lock','AI Ark lookup refused for the locked subject; low AI Ark credits therefore do not establish cheaper successful enrichment.','Confirmed tool refusal.'],
 ['P5','Todd / storage','Infrastructure','Postgres Docker volume filled. Two model calls were recorded only remotely and recovered for billing; person research stopped before JSON dossier.','Confirmed disk exhaustion; not a model-quality failure.'],
 ['P3 / P4','Research evidence','Shared filtering + model use','AI Ark summary.seo remained exposed in projected enrichment artifacts; Grok F034 used that prose. The boundary leak is shared even when not used.','Confirmed in retained artifacts.'],
 ['P4','Trace export','Observability','Model-name parsing warnings and export timeout occurred. All 171 researcher model IDs and 27 provider attempt IDs were nevertheless found remotely.','Verified IDs do not prove every filesystem callback exported.']
];
for(const f of extraFailures){const r=runs.find(r=>r.id===f[0].split(' / ')[0]);failures.push([...f,r.report]);}
for(const [i,s] of peval.setup_attempts.entries()){
 const id=`S${i+1}`;failures.push([id,'Before research','Provider integration',s.failure,'No research tools executed',s.root_path]);
 await addLink(id,'Setup','Attempt folder',s.root_path,'Setup only; no research output.');
}
const checks=[];
for(const r of runs){const calc=r.parts.reduce((a,b)=>a+(b||0),0);if(Math.abs(calc-r.total)>0.00001)throw Error(`Cost mismatch ${r.id}`); checks.push({run:r.id,costSum:calc,total:r.total});}
if(missing.length)throw Error('Missing links: '+missing.join('\n'));

const wb=Workbook.create();
const sheets={};
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
function make(name,title,note,headers,rows,widths,height=48){
 const s=wb.worksheets.add(name);sheets[name]=s;s.showGridLines=false;
 const last=col(headers.length-1),end=5+rows.length;
 s.getRange(`A1:${last}${end}`).format={font:{name:'Arial',size:10,color:'#24364B'},verticalAlignment:'top',wrapText:true};
 s.mergeCells(`A1:${last}1`);s.getRange('A1').values=[[title]];s.getRange(`A1:${last}1`).format={fill:'#122B44',font:{name:'Arial',size:18,bold:true,color:'#FFFFFF'},rowHeight:38};
 s.mergeCells(`A2:${last}3`);s.getRange('A2').values=[[note]];s.getRange(`A2:${last}3`).format={fill:'#E9F1F7',font:{name:'Arial',size:11,color:'#24364B'},wrapText:true,rowHeight:24};
 s.getRange(`A5:${last}5`).values=[headers];s.getRange(`A5:${last}5`).format={fill:'#234B65',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:34};
 if(rows.length)s.getRange(`A6:${last}${end}`).values=rows.map(row=>row.map(x=>x===undefined?null:x));
 for(let i=0;i<headers.length;i++)s.getRange(`${col(i)}1:${col(i)}${end}`).format.columnWidth=widths[i]||20;
 for(let i=0;i<rows.length;i++){const lines=Math.max(...rows[i].map((x,k)=>String(x??'').split('\n').reduce((a,v)=>a+Math.max(1,Math.ceil(v.length/((widths[k]||20)*0.85))),0)));s.getRange(`A${i+6}:${last}${i+6}`).format.rowHeight=Math.max(32,lines*14+12);if(i%2===1)s.getRange(`A${i+6}:${last}${i+6}`).format.fill='#F2F6FA';}
 s.tables.add(`A5:${last}${end}`,true,name.replaceAll(' ','')+'Table');
 s.freezePanes.freezeRows(5);s.freezePanes.freezeColumns(2);s.tabColor='#234B65';return s;
}
const runRows=runs.map(r=>[r.id,r.scenario,shortModel(r.model),r.effort,excelTime(r.wall),excelTime(r.settledWall),null,r.credits,jobs.filter(j=>j.id===r.id&&j.subject==='account')[0]?.findings??0,jobs.filter(j=>j.id===r.id&&j.subject==='person').map(j=>`${j.name}: ${j.findings}${j.narrative?' + page':''}`).join('\n')||'None started',r.summary,null]);
make('Runs','Research model comparison · 28 September 2026','11 research attempts across two seller/account pairs. Recorded USD and AI Ark credits are separate. Research wall includes research through final job outcome; total observed also includes later reconciliation or cancellation. Overlapping jobs are not added.', ['Run','Seller / account','Research model','Effort','Research wall','Total observed','Known USD','AI Ark credits','Account findings','Person outputs','Outcome','Run report'],runRows,[9,26,29,11,15,16,14,13,14,31,61,15],75);
const costRows=runs.map(r=>[r.id,...r.parts,null,r.credits,r.id==='P2'?'Pending Exa billing unknown':r.id==='P1'?'Includes old continuations; possible in-flight charge missing':r.id==='Z2'?'Failed call and extra availability probe unpriced':'Recorded usage; not invoice reconciled']);
costRows.push(['S1',0,0,0,0,0,0,0.118116,0,0,null,null,'Fresh shared Head brief in setup01. Counted once; no research tools.']);
const cs=make('Costs','Recorded cost breakdown','Researcher = account and person models. Reconciliation is a separate common model. AI Ark credits are not converted to dollars. Setup02/03 have no priced research usage recorded; this does not certify a provider invoice of zero.', ['Run','Researcher USD','Exa USD','Deepgram USD','Embedding USD','Reconciliation USD','Old continuations USD','Head brief USD','Preflight USD','Other USD','Known total USD','AI Ark credits','Billing limits'],costRows,[9,16,14,16,16,19,20,17,17,14,18,16,66],52);
for(let i=0;i<costRows.length;i++)cs.getRange(`K${i+6}`).formulas=[[`=SUM(B${i+6}:J${i+6})`]];
cs.getRange(`B6:K${costRows.length+5}`).setNumberFormat('$0.000000');cs.getRange(`L6:L${costRows.length+5}`).setNumberFormat('0.0');
const totalRow=costRows.length+7;
cs.getRange(`A${totalRow}`).values=[['Total']];
for(let k=1;k<=11;k++)cs.getRange(`${col(k)}${totalRow}`).formulas=[[`=SUM(${col(k)}6:${col(k)}${costRows.length+5})`]];
cs.getRange(`A${totalRow}:M${totalRow}`).format={fill:'#DCE9E2',font:{name:'Arial',size:10,bold:true,color:'#183E2E'},rowHeight:30};
cs.getRange(`B${totalRow}:K${totalRow}`).setNumberFormat('$0.000000');cs.getRange(`L${totalRow}`).setNumberFormat('0.0');
cs.getRange(`M${totalRow}`).values=[['Known recorded charges; unpriced uncertainties excluded.']];
for(let i=0;i<runs.length;i++) {sheets.Runs.getRange(`G${i+6}`).formulas=[[`=Costs!K${i+6}`]];}
sheets.Runs.getRange(`E6:F${runRows.length+5}`).setNumberFormat('[m]:ss');sheets.Runs.getRange(`G6:G${runRows.length+5}`).setNumberFormat('$0.00');sheets.Runs.getRange(`H6:H${runRows.length+5}`).setNumberFormat('0.0');
function hyperlink(sheet,cell,target,label){const u=target.startsWith('https://')?target:'file://'+target;sheet.getRange(cell).values=[[label]];sheet.getRange(cell).format.font={color:'#1767A0',underline:'single'};nativeLinks.push({sheet:Object.entries(sheets).find(([k,v])=>v===sheet)[0],cell,target:u});}
for(let i=0;i<runs.length;i++)hyperlink(sheets.Runs,`L${i+6}`,runs[i].report,'Open report');
const jobRows=jobs.map(j=>[j.id,j.name,j.status,excelTime(j.wall),excelTime(j.pre),excelTime(j.formation),excelTime(j.post),j.findings,j.latest,j.narrative?'Saved':'Not saved',j.calls,j.modelCost,j.start?new Date(j.start):null,j.end?new Date(j.end):null,j.jobId]);
const js=make('Jobs','Per-account and per-person timing','Times are job wall duration and observed phase boundaries. “Before formation” includes preparation, research and source review. Blank phase times mean no completed milestone. Model cost excludes providers. Zero findings on blocked jobs means none authored, not an empty successful investigation.', ['Run','Entity','Status','Job elapsed','Before formation','Formation → import','Import → narrative','Initial / draft findings','Latest stored findings','Researcher narrative','Model calls','Model USD','Start UTC','End UTC','Job ID'],jobRows,[9,28,22,15,18,19,19,17,17,19,14,15,24,24,43],48);
js.getRange(`D6:G${jobRows.length+5}`).setNumberFormat('[m]:ss');js.getRange(`L6:L${jobRows.length+5}`).setNumberFormat('$0.0000');js.getRange(`M6:N${jobRows.length+5}`).setNumberFormat('mmm d hh:mm:ss');
const qr=[];
for(const p of quality.probes)for(const [model,m]of Object.entries(p.models)){const r=runs.find(r=>r.key===model);qr.push([r.id,p.probe,flat(m.assessment),m.note,m.findings.map(f=>`${f.subject} ${f.finding_id}`).join(', '),m.acquired_passage_matches?.length??null,path.join(src,'quality-evidence.json')]);}
const extraQuality=[
 ['P1','Operating voice','Strong baseline','Initial account preserved MedEvolve cash/time/visibility statements; Todd expands collections, physician reporting and reimbursement. Some company and other-person content enters Todd claims.','Initial 52 account; Todd 37'],
 ['P2','Executive public voice','Shallow account selection','Useful intake, referral and Open Access flow; MedEvolve material not developed into strong attributed operating voice. Only 19 account findings; Beth unfinished.','Account only'],
 ['P3','Executive public voice','Returned but omitted','MedEvolve Todd excerpt was retrieved but missing from account dossier and account narrative. Greene historical quote survived, often via Exa-report reference.','Account F031/F071 are research gaps'],
 ['P3','Recent hiring and patient experience','Distinct discovery strength','Three summer-2026 postings and one qualified patient-reminder/portal anecdote survived; not evidence of current vacancies or systemic failure.','Account F030/F062'],
 ['P3','Beth depth and scope','Profile depth; limited own voice','Preserves 18 entities, 100+ providers, 15 physicians/45 FTEs and endoscopy experience. No independent long-form voice or hobbies established. Employer/colleague facts and duplicate summaries remain.','Beth 19 findings'],
 ['P4','Executive public voice','Strong retention','Todd MedEvolve analytics, collection metrics, Medicare and recruiting details retained with direct source links. His person dossier contains six substantial attributed passages.','Account F060–63; Todd F018–23'],
 ['P4','External record abstraction','Useful new lead','Sherill Albert profile describes extracting outside records into new-patient EMR; affiliation/date uncertainty appropriately retained.','Account F064'],
 ['P4','Conflicts and granularity','Overclassification / peripheral detail','21 account potential-conflict tags include compatible property dimensions, plan/completion chronology and different role titles; excessive historical property coverage.','Account F012–20/F013'],
 ['P4','Recent hiring and patient experience','Discovery gap','Equivalent summer scheduling/prior-auth jobs and seven-reminder anecdote not found in acquired account phrase scan.','Not proof absent from public web'],
 ['P5','Executive public voice','Improved account retention','Account preserved MedEvolve operational voice in about 7m31s. Better account evidence than Muse high, but different live sources and runtime mean effort alone is not proven cause.','30 account findings'],
 ['P5','Person completion','Not evaluable','Database storage failure stopped Todd before authored JSON. No complete person narrative to compare.','Not a model-quality failure'],
 ['P1 / P3 / P4 / P5','Narrative versus source fidelity','Shared issues remain','Research gaps become supported observations, some independent facts bundled, ownership leaks and public statements compressed. Valid import does not establish semantic quality.','See detailed Premier review'],
 ['Z2','Grok 4.7 medium partial draft','Promising but incomplete','Strong ABM/BDR, Outreach and named public statements in 30 draft findings; provider capacity ended generation before final review. Cannot compare as finished quality.','4 draft sections; no import'],
 ['Z3 / Z4','GLM finished output','Not evaluable','Sources and Exa report exist; researcher never completed structured dossier. Untouched retry hit output-token truncation and finalizer handling.','No authored dossier / narrative']
];
for(const row of extraQuality)qr.push([...row,null,path.join(src,row[0].startsWith('P')?'PREMIER-QUALITY.md':'FAILURES-ZAFRAN.md')]);
const qs=make('Quality','What the models preserved, missed or distorted','20 Zafran probes plus Premier and incomplete-run assessments. These are targeted source-to-finding checks, not an exhaustive omission rate. A claim count is not a quality score. Exact quoted passages and source paths are in the linked evidence report.', ['Run','Evidence / behavior','Assessment','Observed difference','Finding references','Acquired passage matches','Evidence'],qr,[11,42,29,84,35,16,18],88);
for(let i=0;i<qr.length;i++)hyperlink(qs,`G${i+6}`,qr[i][6],'Open evidence');
for(let i=0;i<qr.length;i++)qs.getRange(`A${i+6}:G${i+6}`).format.rowHeight=Math.max(44,Math.max(...qr[i].slice(0,6).map((v,k)=>Math.ceil(String(v??'').length/([11,42,29,84,35,16][k]*0.85))))*14+12);
const fsheet=make('Failures','Observed failures and attribution','Separate provider outages, backend defects, model behavior and operator actions. Broad needs_review/missing_finalize codes do not establish loss of saved research. Repairs were not made as part of this reporting task.', ['Run','Entity / stage','Category','What happened and consequence','Confidence / limitation','Evidence'],failures,[12,35,26,95,55,18],105);
for(let i=0;i<failures.length;i++)hyperlink(fsheet,`F${i+6}`,failures[i][5],'Open evidence');
for(let i=0;i<failures.length;i++)fsheet.getRange(`A${i+6}:F${i+6}`).format.rowHeight=Math.max(50,Math.max(...failures[i].slice(0,5).map((v,k)=>Math.ceil(String(v??'').length/([12,35,26,95,55][k]*0.85))))*14+12);
const linkRows=links.map(l=>[l[0],l[1],l[2],l[3],l[5],l[4]]);
const ls=make('Outputs','Dossiers, narratives, raw sources and execution traces','Local links open files on this Mac; move/share the linked artifact tree with the workbook to preserve access. Langfuse links require your existing project access. Initial researcher narratives and later reconciled pages are identified separately. Raw private chain-of-thought is not reproduced.', ['Run','Entity / scope','Artifact','Open','Notes','Absolute source location'],linkRows,[10,29,33,27,65,105],40);
for(let i=0;i<links.length;i++)if(links[i][4])hyperlink(ls,`D${i+6}`,links[i][4],'Open '+links[i][2]);
const traceRows=jobs.map(j=>[j.id,j.name,j.calls,j.input,j.cache,j.output,excelTime(j.modelSeconds),j.reads,j.readRepeats,j.batches,j.maxBatch]);
const ts=make('Trace metrics','Observable execution metrics','Input tokens are cumulative conversation replay, often cached, not unique research volume. Output tokens may include billed reasoning. Model latency sums overlap other activity and are not an exclusive wall-time breakdown. Empty tool statistics were not normalized for that run; see chronology links.', ['Run','Entity','Model calls','Input tokens','Cache-read tokens','Output tokens','Model latency sum','read_file calls','Exact repeat reads','Multi-tool batches','Largest batch'],traceRows,[10,29,15,20,20,19,20,18,19,20,18],42);
ts.getRange(`C6:F${traceRows.length+5}`).setNumberFormat('#,##0');ts.getRange(`G6:G${traceRows.length+5}`).setNumberFormat('[m]:ss');
const methods=[
 ['Scope','11 substantive research attempts (5 Premier, 6 Zafran), plus three Muse setup failures. Premier baseline began September 27 UTC but September 28 in Asia/Kolkata. No new paid calls made for this report.'],
 ['Recommendation','Use Grok 4.6 medium as current research-quality baseline; Muse xhigh remains a promising lower-cost account candidate, and Muse max has unique person-depth strengths. No model completed every formal lifecycle stage without issues.'],
 ['Two workloads','Premier: Insight Health seller, one account plus one selected person (Todd or Beth). Zafran: Clue seller, account plus fixed Nick and Vari. Raw total costs across these workloads are not like-for-like.'],
 ['Effort','medium/high/xhigh/max are the actual requested settings where checked. They are provider-specific controls, not equal hidden compute budgets. No private reasoning content is reconstructed.'],
 ['Resources versus runtime','Revision-24 resources and common retained context within each comparison; side-chat runtime fixes changed code between some launches. Muse also uses provider-specific tool/schema adaptations. Not a randomized model-only experiment.'],
 ['Wall time','Runs shows earliest research start to final research completion/failure/cancellation. Jobs overlap. Costs includes reconciliation and other listed paid work even if after research. Extra settlement time is in the report/run sources.'],
 ['Settlement boundaries','P1 worker stop about31m22s including old continuation (approximate); P4 final no-op about51m46s; Z1 30m15.5s; Z5 57m55.2s; Z6 36m03.5s including failed reconciliation. These should not be confused with successful end-to-end duration.'],
 ['Cost','Sum recorded researcher/provider result rows once; exclude estimate duplication. USD and AI Ark credits remain separate. P2 pending Exa, P1 possible in-flight continuation, Z2 failed call/probe leave unpriced uncertainty. No invoice reconciliation.'],
 ['Setup cost','S1 paid Head brief $0.118116; reused by later Premier runs and counted once. S2 tool-choice and S3 schema setup failures have no recorded priced research usage.'],
 ['Findings','Authored dossier records are not all account claims. Typed AI Ark enrichment excluded from authored counts. Z2 has30 drafts but0 imported. P1 initial52 findings became60 through old continuations.'],
 ['Quality method','Read initial and latest dossiers, source payloads, narratives and tool traces. Classify acquired-but-omitted, not-acquired-in-targeted-scan, unsupported inference, wrong ownership, bad conflict or incomplete output separately. No blanket loss percentage.'],
 ['Narrative attribution','Researchers write initial account/contact narratives. Later focused reconciliation uses common Muse; its text is not proof of another researcher model’s writing quality. Draft failed writes are not published narratives.'],
 ['Trace boundary','Model-call CSVs, public assignments, tool chronology and Langfuse links expose observable activity. Reasoning effort and billable output tokens do not reveal internal reasoning quality. ID-match checks do not prove every callback exported.'],
 ['Source reliability','This assesses fidelity to retrieved sources, not independent proof that every public source is true. Dates and unknown affiliation are retained qualifications.'],
 ['Missing data','Blank numeric milestone means unavailable or never reached, not zero time. Not produced / unavailable in Outputs is deliberate. Failed jobs may still have durable dossiers and narratives.'],
 ['Next evaluation','Fix/replay deterministic completion, parent-reference and narrative/reconciliation contract failures against saved artifacts, then compare fixed-evidence authoring for fidelity before buying fresh discovery runs.']
];
make('Method','How to read the comparison','Current snapshot: 28 September 2026. All amounts in USD unless labelled AI Ark credits. This workbook is a decision aid grounded in retained run artifacts; it does not assign unsupported quality scores.', ['Topic','Definition / interpretation'],methods,[28,135],70);

wb.recalculate();
await fs.mkdir(out,{recursive:true});
console.log((await wb.inspect({kind:'table',range:'Runs!A5:K9',include:'values,formulas',tableMaxRows:5,tableMaxCols:11,maxChars:2500})).ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:40},summary:'Formula check'});
await fs.writeFile(path.join(out,'formula-check.ndjson'),errors.ndjson);
console.log(errors.ndjson);
await fs.writeFile(path.join(src,'workbook-data.json'),JSON.stringify({runs,jobs,failures,links,checks,missing},null,2));
await fs.writeFile(path.join(out,'native-hyperlinks.json'),JSON.stringify(nativeLinks,null,2));
for(const [name,s]of Object.entries(sheets)){
 if(process.argv[2]&&!process.argv[2].split(',').includes(name))continue;
 const ranges={Runs:'A1:L16',Costs:'A1:M19',Jobs:'A1:O10',Quality:'A1:G9',Failures:'A1:F9',Outputs:'A1:F11','Trace metrics':'A1:K10',Method:'A1:B9'};
 const preview=await wb.render({sheetName:name,range:ranges[name],scale:1.25,format:'png'});
 await fs.writeFile(path.join(out,'preview-'+name.replaceAll(' ','-')+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'research-model-comparison.xlsx'));
console.log(JSON.stringify({runs:runs.length,jobs:jobs.length,links:links.length,failures:failures.length,knownUSD:runs.reduce((a,r)=>a+r.total,0)+0.118116,output:path.join(out,'research-model-comparison.xlsx')}));
