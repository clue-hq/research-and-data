"""Offline, review-only r18 routing fixture. No model, network, DB or runtime imports.

The explicit entity/finding mappings below are fixture annotations, NOT a production
classifier. Run from the repo root with python3. All source records remain unchanged.
"""
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / '.artifacts/arv4-clue-zafran-20260926-r18'
OUT = ROOT / '.artifacts/narrative-selection-20260926'
ENTITIES = {
    'Account': '74d83176-f407-4d35-a9c2-25ad0a8bbf91',
    'Nick': 'ecfd137b-d274-4707-8bb2-f23efdea4a52',
    'Vari': 'ab5a988f-ff12-4005-a3d8-bc18a85838c1',
    'Sanaz': 'a6ffb804-3673-4f6f-a7c4-6c853e20420f',
    'Tom': 'b7d6c153-4440-4290-87a5-8af0578ae046',
    'Rotem': '6640b512-18b8-48c0-a3fc-4fc5e0b619d0',
}
NAMES = {v: k for k, v in ENTITIES.items()}

# Auditable proposed categories assigned to the fixture's original finding IDs.
# Evidence text and qualification fields, not these tags, determine factual meaning.
RULES = {}
def tag(person, ids, categories, account_relevant=True):
    for part in ids.split(','):
        ends = [int(n) for n in part.split('-')]
        for number in range(ends[0], ends[-1] + 1):
            RULES[person, f'F{number:03}'] = (categories.split(), account_relevant)

tag('Account','1-9','company_identity offering business_model operating_model')
tag('Account','3,4,9','published_outcomes public_statements market_context')
tag('Account','6,7','company_identity historical_context')
tag('Account','10-19','funding financial_performance scale')
tag('Account','12,18,19','funding public_statements strategic_priorities')
tag('Account','20-30','hiring organization responsibilities leadership_change')
tag('Account','21','hiring operational_needs working_methods public_statements')
tag('Account','22-24','hiring responsibilities public_statements strategic_priorities')
tag('Account','26','hiring technology historical_context')
tag('Account','40-46','workflows working_methods operational_needs')
tag('Account','42,44,45','workflows technology responsibilities')
tag('Account','45,46','workflows technology initiatives public_statements')
tag('Account','50-55','technology workflows')
tag('Account','53','technology career historical_context')
tag('Account','54','technology workflows historical_context')
tag('Account','60-73','organization responsibilities')
tag('Account','71,73','organization public_statements')
tag('Account','72','organization historical_context')
tag('Account','80-86','strategic_priorities initiatives offering market_context')
tag('Account','85','strategic_priorities public_statements')
tag('Account','90-95','public_statements working_methods reputation')
tag('Account','100-104','conflicting_evidence')
tag('Account','100,102','conflicting_evidence financial_performance funding')
tag('Account','101','conflicting_evidence company_identity')
tag('Account','103','conflicting_evidence scale')
tag('Account','104','conflicting_evidence organization historical_context')
tag('Account','110,111','public_statements working_methods organization')
tag('Account','112,113','published_outcomes conflicting_evidence')
tag('Account','114,115','hiring responsibilities')
tag('Account','116','organization conflicting_evidence')

tag('Nick','1-4','responsibilities organization')
tag('Nick','5-12','career historical_context',False)
tag('Nick','13-18','education certifications',False)
tag('Nick','19-22','personal_projects public_interests public_statements',False)
tag('Nick','23-33','public_statements working_methods workflows initiatives')
tag('Nick','25,29-32','public_statements technology workflows working_methods initiatives')
tag('Nick','34-39','public_statements hiring initiatives responsibilities')
tag('Nick','38,39','public_statements initiatives market_context')
tag('Nick','40,41','public_interests public_statements',False)
tag('Nick','43-48','career public_statements historical_context',False)
tag('Nick','49-52','conflicting_evidence',False)

tag('Vari','1-8,61','responsibilities organization')
tag('Vari','9-11','working_methods technology public_statements')
tag('Vari','12-16','public_statements hiring initiatives')
tag('Vari','17-23','workflows responsibilities hiring')
tag('Vari','19','workflows operational_needs hiring')
tag('Vari','20,21','technology workflows hiring')
tag('Vari','24-41','career historical_context',False)
tag('Vari','30-32,37','career historical_context working_methods technology',False)
tag('Vari','42-51','education certifications',False)
tag('Vari','52-56','organization conflicting_evidence',False)
tag('Vari','57-60','conflicting_evidence',False)
tag('Vari','6,8,55','direct_field',False)
tag('Vari','7','career',False)

tag('Sanaz','1-5','responsibilities organization company_identity')
tag('Sanaz','6-12','career historical_context',False)
tag('Sanaz','13','leadership_change organization')
tag('Sanaz','14-21','funding financial_performance scale public_statements')
tag('Sanaz','22-24','education career historical_context',False)
tag('Sanaz','25-33','career historical_context public_interests',False)
tag('Sanaz','34-36','offering strategic_priorities public_statements historical_context')
tag('Sanaz','37-43','public_statements working_methods strategic_priorities')
tag('Sanaz','44-48','public_interests public_statements',False)
tag('Sanaz','49,51,52','public_statements initiatives')
tag('Sanaz','50,53','public_statements historical_context',False)

tag('Tom','1-5','responsibilities organization leadership_change')
tag('Tom','6-20','career historical_context',False)
tag('Tom','21-25','education public_interests',False)
tag('Tom','26-40','public_statements working_methods strategic_priorities initiatives')
tag('Tom','29','public_interests public_statements',False)
tag('Tom','35','public_statements technology historical_context')
tag('Tom','39','funding public_statements')
tag('Tom','41-46','hiring public_statements organization')
tag('Tom','47-50','career public_statements historical_context',False)
tag('Tom','51-53','conflicting_evidence historical_context',False)

tag('Rotem','1-6','responsibilities organization')
tag('Rotem','7-12','career historical_context',False)
tag('Rotem','13-16','leadership_change organization public_statements')
tag('Rotem','17-19','education',False)
tag('Rotem','20-28','public_interests historical_context',False)
tag('Rotem','29','public_statements career',False)
tag('Rotem','31-35','public_statements initiatives working_methods')
tag('Rotem','32,33','public_statements funding')
tag('Rotem','36-40','hiring public_statements organization')
tag('Rotem','41,42','hiring career public_statements historical_context',False)
tag('Rotem','43','career',False)

FIELDS = {
    'core.company_linkedin_url': 'company_identity', 'core.industry': 'company_identity market_context',
    'core.employee_count': 'scale', 'core.revenue_band': 'financial_performance',
    'core.account_name': 'company_identity', 'core.primary_domain': 'company_identity',
    'core.legal_name': 'company_identity', 'core.founded_year': 'company_identity',
    'core.company_type': 'company_identity', 'core.industries_all': 'market_context',
    'core.company_languages': 'company_identity', 'core.company_crunchbase_url': 'company_identity',
    'core.company_twitter_url': 'company_identity', 'core.company_email': 'direct_field',
    'core.hq_location': 'company_identity', 'core.employee_range': 'scale',
    'core.primary_tech_stack': 'technology', 'core.tech_stack_categorised': 'technology',
    'account.total_funding': 'funding', 'account.recent_funding': 'funding',
    'account.open_requisitions': 'hiring responsibilities',
    'account.committee_selection': 'committee_rationale responsibilities',
    'contact.current_title': 'responsibilities', 'contact.current_location': 'direct_field',
    'contact.network_statistics': 'direct_field', 'contact.member_badges': 'direct_field',
    'contact.facet.career_history': 'career historical_context', 'core.work_email': 'direct_field',
}
# Later writes with exact topic matches inherit the ORIGINAL tag proposal, never its
# review status or factual authority. Remaining topics get explicit fixture annotations.
LATER = {}
def later(person, topic, categories, relevant=True):
    LATER[person, topic] = (categories.split(), relevant)

for topic,cats in {
 'Company $130 million total versus CTech more-than-$140 million expectation':'funding conflicting_evidence',
 '90 percent versus 99 percent de-risk product claims':'published_outcomes conflicting_evidence',
 'CTech report of Snir Havdala departure':'organization leadership_change',
 'Nominated GTM leadership titles as reported':'organization responsibilities',
 'Amex Ventures strategic investment amount undisclosed':'funding',
 'CTO labels: Ben Seri, Tomer Admon Field CTO, careers Tomer Field CTO':'organization responsibilities conflicting_evidence',
 'Named customers and demo-led sales motion':'business_model market_context published_outcomes',
 'Nick Fisher AI-First GTM Ops and Head of Growth hire posts':'hiring public_statements strategic_priorities',
}.items():later('Account',topic,cats)
for topic,cats,rel in [
 ('Education, Skilljar certificates, unverified credentials','education certifications',False),
 ('JD HubSpot execution and required platforms','technology workflows hiring',True),
 ('Public posts: AE intros, $60M caption, Ben Seri CNBC','public_statements funding initiatives',True),
 ('Career: Secureworks, ReSource Pro, Axiom, Tangoe','career historical_context',False),
 ('JD verticals, CISO engagement, calendar and budget','workflows hiring responsibilities',True),
 ('Axiom pipeline claim and Salesforce–HubSpot integration','career historical_context technology',False),
 ('Career: Ivanti date overlaps, Grazitti, Milestone','career historical_context conflicting_evidence',False),
 ('Stale directories, The Org, namesakes, and research gaps','conflicting_evidence',False),
 ('Seller relevance for Clue (interpretation)','interpretation_only',True),
]:later('Vari',topic,cats,rel)
for topic,cats,rel in [
 ('Cocktail Chemistry and CocktailGPT','personal_projects public_interests public_statements',False),
 ('Hiring remits versus personal execution','hiring responsibilities public_statements',True),
 ('Why I joined Zafran','career public_statements',True),
 ('Career history','career historical_context',False),
 ('Education and honors','education certifications',False),
 ('Present role at Zafran','responsibilities organization',True),
 ('Okta title variants','career historical_context conflicting_evidence',False),
 ('First-week customer voice','public_statements working_methods',True),
 ('ZafranGPT and in-house outbound research','technology workflows public_statements',True),
 ('Messy middle of AI adoption','technology workflows public_statements working_methods',True),
 ('Claude Cowork BDR intent workflow','technology workflows public_statements',True),
 ('SEO, hackathon, and agentic product launch','public_statements initiatives strategic_priorities',True),
 ('Recommendations and historical media','career public_statements historical_context',False),
 ('Event creative and Black Hat','initiatives public_statements working_methods',True),
 ('Location, family, and contact','public_interests',False),
 ('Namesakes and third-party personality synthesis','conflicting_evidence',False),
]:later('Nick',topic,cats,rel)

RECIPES = {
 'overview/what-they-do':'company_identity offering business_model operating_model published_outcomes scale',
 'overview/why-they-fit':'operational_needs strategic_priorities initiatives responsibilities purchasing_requirements scale technology workflows conflicting_evidence',
 'overview/why-now':'initiatives hiring expansion leadership_change funding explicit_buying_intent',
 'overview/buying-committee':'committee_rationale responsibilities organization',
 'overview/how-to-approach':'operational_needs initiatives working_methods public_statements evaluation_preferences',
 'overview/research-notes':'conflicting_evidence reputation',
 'insights/buying-signals':'operational_needs hiring purchasing_requirements explicit_buying_intent workflows',
 'insights/strategy-and-initiatives':'strategic_priorities initiatives expansion',
 'insights/organization-and-teams':'hiring organization responsibilities leadership_change',
 'insights/tools-they-already-use':'technology workflows integrations',
 'insights/money-and-momentum':'funding financial_performance scale expansion',
 'insights/contact-insights':'public_statements working_methods evaluation_preferences',
 'insights/business-context':'offering business_model operating_model market_context published_outcomes company_identity',
 'nick/why-this-person':'responsibilities committee_rationale career working_methods',
 'nick/problem-right-now':'operational_needs workflows initiatives strategic_priorities hiring',
 'nick/experience-and-perspective':'career education certifications public_statements working_methods personal_projects public_interests',
 'nick/openers':'public_statements personal_projects public_interests initiatives',
 'nick/angles':'working_methods public_statements strategic_priorities workflows operational_needs',
 'nick/research-notes':'conflicting_evidence reputation',
}

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
def digest(data):
    return hashlib.sha256(data).hexdigest()
def value(row):
    return row['value_json'] if isinstance(row['value_json'], dict) else {}
def entry(row):
    return value(row).get('dossier_entry', {})
def origin(row):
    return 'dossier_import' if entry(row) else ('later_finding' if row['field_key'].endswith('.research_finding') else 'other_field')

def main():
    rows = json.loads((SOURCE/'review/all-claim.json').read_text())
    assert len(rows)==481 and len({r['id'] for r in rows})==481
    byid = {r['id']:r for r in rows}
    bytopic = {(NAMES[r['entity_id']],value(r).get('topic')):RULES.get((NAMES[r['entity_id']],entry(r).get('id'))) for r in rows if entry(r)}
    overlay = []
    for row in rows:
        person=NAMES[row['entity_id']];v=value(row);e=entry(row);field=row['field_key']
        rule=None;basis=''
        if e:
            rule=RULES.get((person,e['id']));basis='explicit finding-ID fixture annotation'
        elif field.endswith('.research_finding'):
            rule=LATER.get((person,v.get('topic'))) or bytopic.get((person,v.get('topic')))
            basis='explicit later-topic annotation or exact-topic inheritance (not deduplication)'
        elif field in FIELDS:
            rule=(FIELDS[field].split(),person=='Account' or field=='contact.current_title')
            basis='typed field recipe'
        tags,rel=rule or ([],False)
        if v.get('claim_type')=='reported_statement' and 'public_statements' not in tags:
            tags=tags+['public_statements']
        review=v.get('review') or {}
        overlay.append(dict(claim_id=row['id'],entity=person,entity_id=row['entity_id'],field_key=field,
            finding_id=e.get('id'),dossier_section=e.get('section'),topic=v.get('topic',field),
            origin=origin(row),categories=tags,account_context_candidate=rel,
            review_status=review.get('status','not_recorded'),mapping_basis=basis if rule else 'UNMAPPED: needs semantic review',
            destinations=[],context_destinations=[],disposition=None))
    omap={o['claim_id']:o for o in overlay}
    # Preserve the full historical snapshot once; packets carry exact model-useful
    # values/evidence. Provider blobs in write_markers are retained here, not injected
    # as if every unrelated provider property were a selected claim.
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'claims.snapshot.json').write_bytes((SOURCE/'review/all-claim.json').read_bytes())
    prepared=json.loads((SOURCE/'prepared-context.json').read_text())
    head=(SOURCE/'head-input.md').read_text()
    docs=[]
    pins=[prepared['icp'],*prepared['personas'],*prepared['seller_documents']]
    for m in re.finditer(r'^SELECTED DOCUMENT (\S+) ([\w-]+)\n(.*?)(?=^SELECTED DOCUMENT |\Z)',head,re.M|re.S):
        pin=next(p for p in pins if p['document_id']==m[2]);body=m[3]
        # Export separators add newlines. Locate the exact pinned byte sequence by
        # trimming only trailing newlines and matching the stored content hash.
        variants=[body[:len(body)-n] if n else body for n in range(len(body)-len(body.rstrip('\n'))+1)]
        exact=next((s for s in variants if digest(s.encode())==pin['sha256']),None)
        docs.append(dict(**pin,content=exact if exact is not None else body,
                         extracted_sha256=digest((exact if exact is not None else body).encode()),
                         pinned_hash_matched=exact is not None))
    assert len(docs)==3
    shared=dict(source_run_id=rows[0]['run_id'],prepared_context=prepared,
                selected_documents=docs,delegation_brief=(SOURCE/'head-brief.generated.md').read_text(),
                context_gaps=['No separately pinned seller overview in this export; retain the selected product document.',
                              'Retained seller source is historical; persona prose is sparse.'],
                historical_source='head-input.md retained selected documents; current project not queried')
    dump(OUT/'shared-context.json',shared)
    packet_stats={};unresolved=[]
    for name,rawtags in RECIPES.items():
        wanted=set(rawtags.split());selected={}
        for o in overlay:
            row=byid[o['claim_id']];v=value(row)
            if name.startswith('nick/'):
                in_scope=o['entity']=='Nick' or (o['entity']=='Account' and name.split('/')[1] in ['why-this-person','problem-right-now','angles'])
                if row['field_key']=='account.committee_selection':
                    in_scope=in_scope and v.get('contact_id')==ENTITIES['Nick']
            else:in_scope=o['entity']=='Account' or o['account_context_candidate']
            if not in_scope:continue
            # Notes are a visible destination, not suppression. Wrong entity and
            # interpretation-only records remain available without affirming them.
            notes=name.endswith('/research-notes')
            uncertain=o['review_status'] in ['wrong_entity','insufficient_context','potential_conflict']
            onlynotes=o['review_status']=='wrong_entity' or 'interpretation_only' in o['categories']
            matches=set(o['categories']) & wanted
            if (matches and not onlynotes) or (notes and (uncertain or onlynotes)):
                context_only=name.startswith('nick/') and o['entity']=='Account'
                selected[o['claim_id']]=dict(role='context' if context_only else 'primary',reason=(('account context; ' if context_only else '')+('review qualification' if notes and uncertain else 'category match: '+', '.join(sorted(matches)))))
        # Include exact linked companions transitively. Only references present in
        # the authorized snapshot are resolved; unresolved references stay explicit.
        queue=list(selected)
        while queue:
            cid=queue.pop();r=byid[cid];rev=value(r).get('review') or {}
            refs=list(rev.get('conflicts_with') or [])
            if rev.get('duplicate_of'):refs.append(rev['duplicate_of'])
            if r.get('superseded_by'):refs.append(r['superseded_by'])
            for ref in refs:
                if ref not in byid:
                    unresolved.append(dict(section=name,claim_id=cid,missing_reference=ref));continue
                if ref not in selected:
                    selected[ref]=dict(role='context',reason='linked review/supersession companion of '+cid);queue.append(ref)
        packet=[]
        for cid,why in selected.items():
            r=byid[cid];o=omap[cid]
            o['destinations' if why['role']=='primary' else 'context_destinations'].append(name)
            packet.append(dict(claim_id=cid,**why,entity_id=r['entity_id'],entity=o['entity'],field_key=r['field_key'],
                categories=o['categories'],value_json=r['value_json'],evidence_span=r['evidence_span'],
                source_url=r['source_url'],source_tier=r['source_tier'],observed_at=r['observed_at'],
                collected_at=r['collected_at'],verification_status=r['verification_status'],
                superseded_by=r['superseded_by'],source_key=r['source_key'],artifact_key=r['artifact_key']))
        dump(OUT/'packets'/f'{name.replace("/","--")}.json',dict(section=name,page=('contact' if name.startswith('nick/') else name.split('/')[0]),section_key=name.split('/')[1],shared_context='../shared-context.json',
            status='review-only candidate selection; no narrative generated',recipe_categories=sorted(wanted),claims=packet))
        packet_stats[name]=dict(primary=sum(p['role']=='primary' for p in packet),context=sum(p['role']=='context' for p in packet),bytes=(OUT/'packets'/f'{name.replace("/","--")}.json').stat().st_size)
        lines=[f'# {name}: selected claims','', 'Candidate inputs, not generated prose. Full values, sources, review labels and interpretations are in the adjacent JSON.','', '| Subject / finding | Claim ID | Topic or field | Role / reason |','| --- | --- | --- | --- |']
        for p in packet:
            o=omap[p['claim_id']];topic=o['topic'].replace('|','\\|').replace('\n',' ')
            lines.append(f"| {o['entity']} {o['finding_id'] or '(later/typed)'} | `{o['claim_id']}` | {topic} | {p['role']}: {p['reason']} |")
        (OUT/'packets'/f'{name.replace("/","--")}.md').write_text('\n'.join(lines)+'\n')
    for o in overlay:
        if o['destinations'] or o['context_destinations']:o['disposition']='selected'
        elif not o['categories']:o['disposition']='unmapped_needs_review'
        elif o['categories']==['direct_field']:o['disposition']='direct_field_and_complete_findings'
        else:o['disposition']='complete_findings_only_outside_selected_pages'
    dump(OUT/'routing-overlay.json',overlay)
    with (OUT/'claim-routing.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(overlay[0]));writer.writeheader()
        writer.writerows({k:('; '.join(v) if isinstance(v,list) else v) for k,v in o.items()} for o in overlay)
    dump(OUT/'unresolved-review-references.json',unresolved)
    # Full readable findings, including everything not selected for narrative.
    full=['# Complete retained findings','', 'All 481 saved claims; no new research, rewriting or narrative. JSON values are displayed verbatim below.','']
    for o in overlay:
        r=byid[o['claim_id']]
        full += [f"## {o['entity']} {o['finding_id'] or ''} — {o['topic']}",'',f"Claim `{o['claim_id']}` · `{o['field_key']}` · {o['disposition']}",'','```json',json.dumps(r['value_json'],ensure_ascii=False,indent=2),'```','',f"Source URL: {r['source_url'] or 'See sources within the saved value or provenance in claims.snapshot.json.'}",'']
    (OUT/'complete-findings.md').write_text('\n'.join(full))
    summary=dict(total=len(rows),origins=dict(Counter(origin(r) for r in rows)),
        dispositions=dict(Counter(o['disposition'] for o in overlay)),
        reused_claims=sum(len(set(o['destinations']+o['context_destinations']))>1 for o in overlay),
        packets=packet_stats,unresolved_reference_occurrences=len(unresolved),
        pinned_context_hash_matches=sum(d['pinned_hash_matched'] for d in docs))
    dump(OUT/'summary.json',summary)
    report=['# r18 narrative input selection — review draft','',
      'Prepared offline from the retained r18 snapshot. No models, paid providers, database changes, workers or publication. This is proposed manual fixture routing; it does not validate claim truth or automatic production routing.','',
      '## Inventory','',f"All **{len(rows)} claims** are accounted for: 341 dossier imports, 56 later findings and 84 typed/other records. Exact raw rows are in [claims.snapshot.json](claims.snapshot.json).",'',
      f"**{summary['reused_claims']} claims are reused across multiple section packets.** Distinct records are not collapsed, including later writes which revisit imported findings.",'',
      '| Disposition | Count |','| --- | --- |']
    report += [f'| {k} | {v} |' for k,v in summary['dispositions'].items()]
    report += ['', '## Section inputs','', '| Section | Primary | Linked context | Packet bytes |','| --- | ---: | ---: | ---: |']
    for name,s in packet_stats.items():report.append(f"| [{name}](packets/{name.replace('/','--')}.md) · [JSON](packets/{name.replace('/','--')}.json) | {s['primary']} | {s['context']} | {s['bytes']:,} |")
    report += ['', '## Review cautions','',
      '- These are broad candidate inputs, not a promise every record belongs in the final prose. Categories are multi-valued and section reuse is intentional. Review the input breadth before any calls.',
      '- Personal history from the other four people remains in complete findings; only Nick has contact-page packets in this trial. Their relevant professional findings can still enter account sections.',
      '- Work emails, network counts and other direct metadata are retained in complete findings/direct-field inventory, without spending narrative calls to restate them.',
      '- Typed enrichment source payloads remain in the full snapshot. A selected typed value does not authorize copying unrelated AI Ark descriptive prose from its provenance blob.',
      '- Qualifications and interpretations remain exactly as stored. A selected statement is not independently verified. There is no automatic elevation of missing review labels to supported.',
      '- Historical tooling and earlier-employer evidence can be selected as context; the writer must preserve employer/date and must not declare it current target deployment.',
      '- The later Vari seller-relevance interpretation is routed as a review note, not an observed account fact.',
      f"- Pinned document byte hashes matched: {summary['pinned_context_hash_matches']}/3. See [shared-context.json](shared-context.json) for full documents and any mismatch flags.",
      f"- Unresolved linked-review reference occurrences: {len(unresolved)}. See [reference report](unresolved-review-references.json); missing links are not invented.",
      '- Raw packet byte sizes include original entry/provenance duplication. They are not measured model token sizes or latency. A lossless model view can omit repeated structural copies, but never shorten findings or evidence to hit the 60-second target.',
      '', '## Review every claim and reuse','',
      '[Claim-by-claim CSV](claim-routing.csv) · [Explicit routing overlay](routing-overlay.json) · [Complete findings](complete-findings.md) · [Summary](summary.json)','',
      '## Unmapped and non-narrative records','', '| Subject / finding | Claim | Topic/field | Disposition |','| --- | --- | --- | --- |']
    for o in overlay:
        if o['disposition']!='selected':report.append(f"| {o['entity']} {o['finding_id'] or ''} | `{o['claim_id']}` | {o['topic'].replace('|','/')} | {o['disposition']} |")
    (OUT/'REVIEW.md').write_text('\n'.join(report)+'\n')
    hashes={str(p.relative_to(OUT)):digest(p.read_bytes()) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ['manifest.json']}
    dump(OUT/'manifest.json',dict(source_claims_sha256=digest((SOURCE/'review/all-claim.json').read_bytes()),
        generator_sha256=digest(Path(__file__).read_bytes()),files=hashes))
    # Verify exact finding preservation, claim-ID membership and reverse coverage.
    for name in RECIPES:
        p=json.loads((OUT/'packets'/f'{name.replace("/","--")}.json').read_text())
        for c in p['claims']:
            assert c['value_json']==byid[c['claim_id']]['value_json']
            assert c['evidence_span']==byid[c['claim_id']]['evidence_span']
            assert name in omap[c['claim_id']]['destinations']+omap[c['claim_id']]['context_destinations']
    assert sum(summary['dispositions'].values())==481
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
