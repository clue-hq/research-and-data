import json, html
from pathlib import Path
from collections import Counter
HERE = Path(__file__).parent
rows = [json.loads(l) for f in sorted((HERE/"ledger").glob("*.jsonl")) for l in open(f)]
issues = json.loads((HERE/"issues.json").read_text())
LABEL = {
 "A1":"Site · system prompt",
 "D1":"Site skill · account-page-copy","D2":"Site skill · building-with-puck","D3":"Site skill · images-and-logos","D4":"Site skill · page-review",
 "D5":"Site skill · rebuilding-a-section","D6":"Site skill · writing-a-section","B1":"Site · tool descriptions","G1":"Site · message wrapper (leg prompt)","H1":"Site data · brief.md, research/","H2":"Site data · research files and claims.md","H3":"Site data · clone cards",
 "L1":"Legacy · campaign-landing-page","L1a":"Legacy · campaign-landing-page / action-selection","L1b":"Legacy · campaign-landing-page / argument-and-shell",
 "L1c":"Legacy · campaign-landing-page / page-directions","L2":"Legacy · campaign-page-workflow","L3":"Legacy · web-account-personalization",
 "L3a":"Legacy · web-account-personalization / account-argument","L3b":"Legacy · web-account-personalization / audience-modes",
 "L3c":"Legacy · web-account-personalization / identity-and-evidence","L4":"Legacy · web-contact-personalization",
 "L5":"Legacy · web-decision-material","L6":"Legacy · plan-design","L7":"Legacy · conversion-copywriting","L7a":"Legacy · conversion-copywriting / copy-craft","L7b":"Legacy · conversion-copywriting / website-copy-brief",
}
GROUPS = [("A","Site · system prompt"),("B","Site · tools"),("D","Site · skills"),("G","Site · message wrapper"),("H","Site · data files"),("L","Legacy candidates (not delivered)")]
TOPIC_DESC = {
 "KIND":"Which kind of page, for whom","ARGUMENT":"What the page argues; the message plan","STRUCTURE":"Sections, order, length",
 "SUBSTANCE":"Decision material and depth","ACTION":"Offer, buttons, destinations","PEOPLE":"People at the account; contact pages",
 "IDENTITY":"The account's name and logo","SHELL":"Header and footer choice","PLAN":"plan.md, the brief, amendments",
 "SCOPE":"How much an edit may change","ASK":"When to ask the person",
 "SOURCING":"Where facts may come from (family 2)","CLAIMS":"Claim strength and numbers (family 2)","PROOF":"Customer proof (family 2)","OFFPAGE":"What never reaches the page (family 2)","VOICE":"Voice and the reader's words (family 2)","HEADLINE":"Headlines (family 2)","EVIDENCE":"Reading evidence (family 2)","COPY":"Wording craft (family 2)","IMAGERY":"Images (family 3)","MOTION":"Video and motion (family 3)",
 "LAYOUT":"Composition (family 4)","BRAND":"Brand look (family 4)","REVIEW":"Self-check (family 5)",
 "TOOLS":"Tool mechanics","READING":"What to read","OUTPUT":"Finishing and reporting","MECHANICS":"Legacy mechanics (not carried over)"}
for r in rows:
    r["sid"] = r["id"].rsplit("-",1)[0]
    r["label"] = LABEL[r["sid"]]
topics = Counter(r["topic"] for r in rows)
data = {"rows": rows, "issues": issues, "labels": LABEL, "groups": GROUPS, "topics": TOPIC_DESC}
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
n_sources = len({r["sid"] for r in rows})
n_site = sum(1 for r in rows if not r["sid"].startswith("L"))
page = r'''<title>Site Agent Rule Ledger</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* layout: one reading column; conflicts as cards with grouped evidence rows, then a filterable ledger */
:root{--bg:#f6f7f5;--panel:#fff;--ink:#1d2321;--mute:#5d6863;--line:#dfe3e0;--acc:#2f6f5e;--hi:#a23b3b;--med:#9a5a12;--low:#5d6863;--chip:#eef1ef;--quote:#f1f4f2;
--sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141816;--panel:#1b201e;--ink:#e3e8e5;--mute:#98a39e;--line:#2c3330;--acc:#7cc2ad;--hi:#e58a8a;--med:#e0a35a;--low:#98a39e;--chip:#232a27;--quote:#202624;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141816;--panel:#1b201e;--ink:#e3e8e5;--mute:#98a39e;--line:#2c3330;--acc:#7cc2ad;--hi:#e58a8a;--med:#e0a35a;--low:#98a39e;--chip:#232a27;--quote:#202624;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:32px 64px}
main{max-width:1000px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
h1{font-size:26px;font-weight:600;margin:0;text-wrap:balance} h2{font-size:19px;font-weight:600;margin:18px 0 0}
.lede{color:var(--mute);margin:4px 0 0;max-width:72ch}
.stats{display:flex;flex-wrap:wrap;gap:6px 22px;font-family:var(--mono);font-size:13px;color:var(--mute);margin-top:8px}
.stats b{color:var(--ink);font-weight:500}
.topics{display:flex;flex-wrap:wrap;gap:6px}
.chip{font:500 12px/1 var(--sans);border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 10px;cursor:pointer;font-variant-numeric:tabular-nums}
.chip span{color:var(--mute);margin-left:4px}
.chip[aria-pressed="true"]{background:var(--acc);border-color:var(--acc);color:var(--bg)} .chip[aria-pressed="true"] span{color:var(--bg)}
.issue{background:var(--panel);border:1px solid var(--line);border-radius:8px}
.issue>summary{list-style:none;cursor:pointer;padding:14px 16px;display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline}
.issue>summary::-webkit-details-marker{display:none}
.sev{font:600 11px/1 var(--sans);text-transform:uppercase;letter-spacing:.05em;border-radius:4px;padding:4px 6px;background:var(--chip)}
.sev.high{color:var(--hi)} .sev.medium{color:var(--med)} .sev.low{color:var(--low)}
.itl{font-weight:600;font-size:16px;min-width:0}
.isub{grid-column:2;color:var(--mute);font-size:13px;font-family:var(--mono)}
.ibody{padding:0 16px 16px;display:flex;flex-direction:column;gap:10px}
.ibody p{margin:0;max-width:75ch} .why{border-left:3px solid var(--acc);padding-left:10px}
.grp h4{margin:8px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--acc);font-weight:600}
.row.legacy,.lrow.legacy{border:1px dashed var(--line);background:transparent}
.status{font:12px/1.4 var(--mono);color:var(--acc)}
.row{display:grid;grid-template-columns:minmax(0,1fr);gap:2px;padding:8px 10px;border-radius:6px;background:var(--quote);margin-bottom:4px}
.rmeta{font:12px/1.4 var(--mono);color:var(--mute);display:flex;flex-wrap:wrap;gap:4px 10px}
.rmeta b{color:var(--ink);font-weight:500}
.rtext{font-size:14px} .rnote{font-size:13px;color:var(--med)}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.controls input,.controls select{font:14px var(--sans);color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:7px 10px;min-width:0}
.controls input{flex:1 1 240px}
.count{font:13px var(--mono);color:var(--mute)}
#ledger{display:flex;flex-direction:column;gap:2px}
.lrow{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.tag{font:500 11px/1 var(--sans);border-radius:4px;padding:3px 6px;background:var(--chip);color:var(--mute)}
.method{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;color:var(--mute);font-size:14px}
.method ul{margin:6px 0 0;padding-left:18px}
button.more{font:14px var(--sans);color:var(--acc);background:none;border:1px solid var(--line);border-radius:6px;padding:8px 12px;cursor:pointer;align-self:flex-start}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
</style>
<main>
<header><h1>Site agent rule ledger</h1>
<p class="lede">Every rule the site agent receives, family by family, beside the legacy web skills we may bring over (dashed, not delivered). Family 2 (wording and evidence) is open for rulings; family 1 (the page's argument) is ruled. Nothing in the agent has been changed yet.</p>
<div class="stats"><span><b>''' + str(len(rows)) + r'''</b> rules</span><span><b>''' + str(n_site) + r'''</b> site rules</span><span><b>''' + str(n_sources) + r'''</b> sources</span><span><b>''' + str(len(issues)) + r'''</b> conflict groups</span><span>captured on <b>origin/main</b> @ 166bafd70</span></div></header>
<h2 id="f2">Family 2 · wording and evidence</h2>
<p class="lede">Ordered by impact. Each group shows the competing rules side by side with their source. Solid rows are what the site agent gets today; dashed rows are legacy candidates.</p>
<div id="issues2"></div>
<h2 id="f1">Family 1 · the page's argument (ruled)</h2>
<div id="issues1"></div>
<h2>Full ledger</h2>
<div class="topics" id="topics"></div>
<div class="controls">
<input id="q" type="search" placeholder="Search rule text or notes" aria-label="Search rules">
<select id="src" aria-label="Source"><option value="">All sources</option></select>
<select id="str" aria-label="Strength"><option value="">Any strength</option><option>must</option><option>must-not</option><option>should</option><option>prefer</option><option>may</option><option>default</option><option>fact</option></select>
<label class="count"><input type="checkbox" id="noted"> with notes only</label>
<span class="count" id="count"></span>
</div>
<div id="ledger"></div>
<button class="more" id="more" hidden>Show more</button>
<h2>How this was built</h2>
<div class="method">
<ul>
<li>The system prompt (45,583 characters, with all 7 skills) and the 19 tool descriptions were captured by building the real site agent offline (scripted model, no spend) for a live-site workspace with account research, and recording its first model call.</li>
<li>For family 1, the site agent's system prompt, its 7 skills and its per-turn data files were read in full and every rule about the page's kind, argument, structure, substance, action, identity and shell became a row. Rules for later families (wording, evidence, imagery, visual design, review) are left for their own pass.</li>
<li>Family 2 adds the site agent's wording and evidence rules (system prompt, account-page-copy parts 2–6, tool descriptions, the research files and clone cards) and the legacy conversion-copywriting skill with its copy-craft and website-copy-brief references, plus the evidence parts of web-account-personalization, campaign-landing-page, web-decision-material and plan-design. Each family-2 group also says what is specific to a page kind.</li>
<li>The family-1 legacy candidates are the web harness's direction skills that Shashank Keshri created or rewrote: campaign-landing-page (with 3 references), campaign-page-workflow, web-account-personalization (with 3 references), web-contact-personalization, web-decision-material and plan-design. Legacy mechanics rows are tagged MECHANICS and will not carry over as written.</li>
<li>Out of scope: the Head of ABM's brief itself (written by another agent each turn) and the exit judge.</li>
<li>Working files: <code>docs/site-harness-alignment/</code> (PROGRESS.md, ledger/*.jsonl, issues.py, sources/).</li>
</ul>
</div>
</main>
<script id="data" type="application/json">''' + blob + r'''</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const byId=Object.fromEntries(D.rows.map(r=>[r.id,r]));
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rowHtml(r,cls){return `<div class="${cls}${r.sid.startsWith('L')?' legacy':''}"><div class="rmeta"><b>${esc(r.id)}</b><span>${esc(r.label)}</span><span>${esc(r.loc)}</span><span class="tag">${esc(r.topic)}</span><span class="tag">${esc(r.strength)}</span><span class="tag">${esc(r.applies)}</span></div><div class="rtext">${esc(r.text)}</div>${r.note?`<div class="rnote">${esc(r.note)}</div>`:''}</div>`}
const issueHtml=(list,openFirst)=>list.map((i,n)=>`<details class="issue"${openFirst&&n<2?' open':''}><summary><span class="sev ${i.severity}">${i.severity}</span><span class="itl">${esc(i.id)} · ${esc(i.title)}</span><span class="isub">${esc(i.topic)} · ${i.groups.reduce((a,g)=>a+g.rows.length,0)} rules · <span class="status">${esc(i.status||"open")}</span></span></summary><div class="ibody"><p>${esc(i.what)}</p><p class="why">${esc(i.why)}</p>${i.cases?`<p class="status">Case-specific: ${esc(i.cases)}</p>`:''}${i.groups.map(g=>`<div class="grp"><h4>${esc(g.label)}</h4>${g.rows.map(id=>rowHtml(byId[id],'row')).join('')}</div>`).join('')}</div></details>`).join('');
document.getElementById('issues2').innerHTML=issueHtml(D.issues.filter(i=>i.family===2),true);
document.getElementById('issues1').innerHTML=issueHtml(D.issues.filter(i=>i.family===1),false);
const counts={};D.rows.forEach(r=>counts[r.topic]=(counts[r.topic]||0)+1);
const tEl=document.getElementById('topics');let topic='';
tEl.innerHTML=`<button class="chip" aria-pressed="true" data-t="">All<span>${D.rows.length}</span></button>`+Object.keys(D.topics).filter(t=>counts[t]).sort((a,b)=>counts[b]-counts[a]).map(t=>`<button class="chip" aria-pressed="false" data-t="${t}" title="${esc(D.topics[t])}">${t}<span>${counts[t]}</span></button>`).join('');
tEl.addEventListener('click',e=>{const b=e.target.closest('.chip');if(!b)return;topic=b.dataset.t;tEl.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed',c===b));limit=60;draw()});
const sEl=document.getElementById('src');
D.groups.forEach(([k,lab])=>{const og=document.createElement('optgroup');og.label=lab;Object.entries(D.labels).filter(([s])=>s.startsWith(k)).forEach(([s,l])=>{const o=document.createElement('option');o.value=s;o.textContent=`${s} · ${l}`;og.appendChild(o)});sEl.appendChild(og)});
let limit=60;const q=document.getElementById('q'),st=document.getElementById('str'),noted=document.getElementById('noted'),lEl=document.getElementById('ledger'),cEl=document.getElementById('count'),more=document.getElementById('more');
function draw(){const qq=q.value.trim().toLowerCase();const list=D.rows.filter(r=>(!topic||r.topic===topic)&&(!sEl.value||r.sid===sEl.value)&&(!st.value||r.strength===st.value)&&(!noted.checked||r.note)&&(!qq||(r.text+' '+r.note+' '+r.loc).toLowerCase().includes(qq)));
cEl.textContent=`${list.length} of ${D.rows.length}`;lEl.innerHTML=list.slice(0,limit).map(r=>rowHtml(r,'lrow')).join('');more.hidden=list.length<=limit}
[q,st,noted,sEl].forEach(el=>el.addEventListener('input',()=>{limit=60;draw()}));
more.addEventListener('click',()=>{limit+=120;draw()});
draw();
})();
</script>'''
(HERE/"rule-ledger.html").write_text(page)
print(len(page))
