#!/bin/zsh
# R3 acceptance evidence for one run: jobs, receipts, ledger, claims per contact, compliance, lock failures, fan-out seam.
set -a; source .env; set +a
RUN="$1"; OUT="$2"; mkdir -p "$OUT"
PSQL_URL=$(echo "$CLUE_DATABASE_URL" | sed 's/postgresql+asyncpg/postgresql/')
J="(select job_id from arv2_research_job where run_id='$RUN')"
psql "$PSQL_URL" -c "select substr(job_id::text,1,8) job, subject_type, coalesce((select full_name from contact_entity c where c.id=j.subject_entity_id),'-') person, status, failure_code, model_rounds, tool_calls, finished_at-started_at wall, cost_usd, credits, media_seconds from arv2_research_job j where run_id='$RUN' order by subject_type, started_at;" > "$OUT/jobs.txt"
psql "$PSQL_URL" -c "select substr(job_id::text,1,8) job, finalization_json->>'reason' reason, finalization_json->>'insight_found' insight, finalization_json->>'openers_written' openers, finalization_json->>'hooks_written' hooks, jsonb_array_length(coalesce(finalization_json->'compliance_log','[]')) compliance_rows, jsonb_array_length(coalesce(finalization_json->'not_found','[]')) not_found, jsonb_array_length(coalesce(finalization_json->'same_name_log','[]')) lookalikes, finalization_json->'model_spend'->>'usd' model_usd, finalization_json->'model_spend'->>'prompt_tokens' prompt_tokens from arv2_research_job where run_id='$RUN' and subject_type='person' order by job_id;" > "$OUT/person-receipts.txt"
psql "$PSQL_URL" -Atc "select job_id, finalization_json from arv2_research_job where run_id='$RUN';" > "$OUT/receipts-raw.txt"
psql "$PSQL_URL" -c "select substr(entity_research_job_id::text,1,8) job, provider, operation, count(*), round(sum(coalesce(cost_usd,0))::numeric,4) usd, sum(coalesce(credits,0)) credits, string_agg(distinct coalesce(extras_json->>'cost_source','-'),',') src from provider_call_ledger where entity_research_job_id in $J and phase='result' group by 1,2,3 order by 1,2,3;" > "$OUT/ledger-by-provider.txt"
psql "$PSQL_URL" -c "select substr(entity_research_job_id::text,1,8) job, round(sum(coalesce(cost_usd,0))::numeric,4) usd, sum(coalesce(credits,0)) credits, round(sum(coalesce(cost_usd,0)) filter (where provider='openrouter' and operation='agent_completion')::numeric,4) model_usd from provider_call_ledger where entity_research_job_id in $J and phase='result' group by 1 order by 1;" > "$OUT/ledger-totals.txt"
psql "$PSQL_URL" -c "select coalesce(ce.full_name, ae.canonical_name) subject, c.field_key, count(*), count(*) filter (where c.evidence_span is not null) quoted, count(*) filter (where c.source_url is not null) with_url, count(*) filter (where (c.write_markers->>'schema_valid')='false') schema_false, count(*) filter (where c.write_markers ? 'unique_insight') insight, count(*) filter (where c.write_markers ? 'unevidenced') unevidenced, count(*) filter (where c.write_markers ? 'redacted') redacted, count(*) filter (where not c.outreach_safe) unsafe from claim c left join contact_entity ce on ce.id=c.entity_id left join account_entity ae on ae.id=c.entity_id where c.run_id='$RUN' group by 1,2 order by 1,3 desc;" > "$OUT/claims-by-subject-field.txt"
psql "$PSQL_URL" -c "select coalesce(ce.full_name, ae.canonical_name) subject, count(*) claims, count(*) filter (where c.entity_type='contact') contact_claims, count(*) filter (where (c.write_markers->>'schema_valid')='false') schema_false, count(*) filter (where c.write_markers ? 'unique_insight') insight, count(*) filter (where c.field_key='contact.facet.public_appearances') media_items, count(*) filter (where c.field_key='core.work_email') emails from claim c left join contact_entity ce on ce.id=c.entity_id left join account_entity ae on ae.id=c.entity_id where c.run_id='$RUN' group by 1 order by 1;" > "$OUT/claims-summary.txt"
psql "$PSQL_URL" -Atc "select a.verdict, coalesce(a.detail_json->>'reason','-'), count(*) from arv2_claim_annotation a where a.job_id in $J group by 1,2 order by 1,3 desc;" > "$OUT/link-audit-by-reason.txt"
python3 - "$OUT" <<'PY'
import json,sys,collections,pathlib
out=pathlib.Path(sys.argv[1]); rows=[l.split('|',1) for l in (out/'receipts-raw.txt').read_text().splitlines() if '|' in l]
by_rule=collections.Counter(); by_action=collections.Counter(); per_job={}
for job,raw in rows:
    try: fin=json.loads(raw)
    except Exception: continue
    log=fin.get('compliance_log') or []
    per_job[job[:8]]=len(log)
    for r in log: by_rule[(r.get('action'),r.get('rule'))]+=1
(out/'compliance-summary.txt').write_text('per job: '+json.dumps(per_job)+'\n'+'\n'.join(f'{a:8} {r:28} {n}' for (a,r),n in sorted(by_rule.items(), key=lambda x:-x[1]))+'\n')
PY
grep -E "subject_lock_failed|media_cap_reached|insight_not_found|email_export_empty|committee_step|committee_jobs|person_model_fallback|profile_pin_mismatch|contact_missing|Traceback" .context/arv2-r3-acceptance/worker.log | cut -c1-300 > "$OUT/worker-events.txt"
psql "$PSQL_URL" -c "select j.subject_type, count(distinct j.job_id) jobs, count(distinct t.task_id) fleet_tasks from arv2_research_job j left join fleet_task t on (t.payload_json->>'job_id')=j.job_id::text where j.run_id='$RUN' group by 1;" > "$OUT/fanout-seam.txt" 2>&1
