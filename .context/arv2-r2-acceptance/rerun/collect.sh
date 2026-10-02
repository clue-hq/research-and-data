#!/bin/zsh
# Evidence for one ARV2 run: claims by field, schema-invalid counts, link audit by verdict and reason, spend.
set -a; source .env; set +a
RUN="$1"; OUT="$2"; mkdir -p "$OUT"
PSQL_URL=$(echo "$CLUE_DATABASE_URL" | sed 's/postgresql+asyncpg/postgresql/')
J="(select job_id from arv2_research_job where run_id='$RUN')"
psql "$PSQL_URL" -c "select job_id, account_entity_id, status, failure_code, started_at, finished_at, finished_at-started_at as wall from arv2_research_job where run_id='$RUN' order by started_at;" > "$OUT/jobs.txt"
psql "$PSQL_URL" -c "select c.entity_id, c.field_key, count(*), count(*) filter (where c.evidence_span is not null) quoted, count(*) filter (where (c.write_markers->>'schema_valid')='false') schema_false, count(*) filter (where c.write_markers ? 'coerced_from') coerced from claim c where c.run_id = '$RUN' group by 1,2 order by 1,3 desc;" > "$OUT/claims-by-field.txt"
psql "$PSQL_URL" -c "select c.entity_id, count(*) claims, count(*) filter (where (c.write_markers->>'schema_valid')='false') schema_false, count(*) filter (where c.write_markers ? 'coerced_from') coerced, count(*) filter (where c.source_url is null) no_url from claim c where c.run_id = '$RUN' group by 1;" > "$OUT/claims-summary.txt"
psql "$PSQL_URL" -c "select c.field_key, left(c.value_json::text,120) value, c.write_markers->>'coerced_from' coerced_from from claim c where c.run_id = '$RUN' and (c.write_markers->>'schema_valid')='false' order by 1;" > "$OUT/schema-invalid.txt"
psql "$PSQL_URL" -c "select a.job_id, a.verdict, count(*) from arv2_claim_annotation a where a.job_id in $J group by 1,2 order by 1,2;" > "$OUT/link-audit.txt"
psql "$PSQL_URL" -c "select a.job_id, a.verdict, coalesce(a.detail_json->>'reason','-') reason, count(*) from arv2_claim_annotation a where a.job_id in $J group by 1,2,3 order by 1,2,4 desc;" > "$OUT/link-audit-by-reason.txt"
psql "$PSQL_URL" -c "select entity_research_job_id job, provider, operation, count(*), round(sum(coalesce(cost_usd,0))::numeric,4) usd, sum(coalesce(credits,0)) credits, sum(coalesce(media_seconds,0)) media_s, string_agg(distinct coalesce(extras_json->>'cost_source','-'), ',') cost_source from provider_call_ledger where entity_research_job_id in $J and phase='result' group by 1,2,3 order by 1,2,3;" > "$OUT/ledger-by-provider.txt"
psql "$PSQL_URL" -c "select entity_research_job_id job, round(sum(coalesce(cost_usd,0))::numeric,4) usd, sum(coalesce(credits,0)) credits, round(sum(coalesce(cost_usd,0)) filter (where provider='openrouter')::numeric,4) model_usd from provider_call_ledger where entity_research_job_id in $J and phase='result' group by 1;" > "$OUT/ledger-totals.txt"
psql "$PSQL_URL" -c "select job_id, status, failure_code, failure_message, model_rounds, finalization_json from arv2_research_job where run_id='$RUN';" -A > "$OUT/receipts.txt"
