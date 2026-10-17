import json, html
from pathlib import Path
from collections import Counter
HERE = Path(__file__).parent
rows = [json.loads(l) for f in sorted((HERE/"ledger").glob("*.jsonl")) for l in open(f)]
issues = json.loads((HERE/"issues.json").read_text())
LABEL = {
 "A1":"System prompt · scene instructions","A2":"System prompt · logo + surface rules","A3":"System prompt · conditional lines",
 "A4":"System prompt · context block","A5":"System prompt · framework base","A6":"System prompt · memory wrapper",
 "A7":"System prompt · saved preferences","A8":"Read notices",
 "B1":"Tools · file tools","B2":"Tools · view/inspect","B3":"Tools · direction/clarify/finalize","B4":"Tools · compile/asset/logo/edit",
 "C1":"Operating note (AGENT.md)",
 "D1":"Skill · scene-brief-copy","D2":"Skill · plan-design","D3":"Skill · create-design","D4":"Skill · visual-review",
 "D5":"Skill · repair-design","D6":"Skill · tools","D7":"Skill · reference-image-direction","D8":"Skill · reference-conditioned-ads",
 "D9":"Skill · brand-imagery","D10":"Skill · generative-imagery","D11":"Skill · effects","D12":"Skill · brand-and-tokens",
 "D13":"Skill · account-adaptation","D14":"Skill · account-identity-composition","D15":"Playbooks · product-led",
 "D16":"Playbooks · proof-led","D17":"Playbooks · argument-led","D18":"Playbooks · action-led",
 "E1":"Guide · direction-contract","E2":"Guide · components (pinned)","E3":"Guide · references","E4":"Guide · review",
 "E5":"Guide · placement","E6":"Guide · image-grammar","E7":"Guide · catalog (generated)",
 "F1":"Engine · grammar (pinned)","F2":"Engine · directives (pinned)","F3":"Engine · text","F4":"Engine · colors","F5":"Engine · layout",
 "F6":"Engine · diagnostics","F7":"Engine · artboard frame (pinned)","F8":"Engine · font library","F9":"Engine · brand-kit guides",
 "F10":"Engine · export","F11":"Engine · layout-cluster repair",
 "G1":"Message · editor context","G2":"Message · leg wrappers","G3":"Message · drift + steering notes",
 "H1":"Data · brief.md","H2":"Data · references.md","H3":"Data · ad-assets.md","H4":"Data · seller index","H5":"Data · state/sources/brand card",
 "Z1":"Audit additions",
}
GROUPS = [("A","System prompt"),("B","Tool descriptions"),("C","Operating note"),("D","Skills"),("E","Scene guides"),
          ("F","Engine reference"),("G","Message wrappers"),("H","Data files"),("Z","Audit additions")]
TOPIC_DESC = {
 "SCOPE":"How much a turn may change","ROUTINE":"Turn flow and steps","PRECEDENCE":"What wins over what","BRAND":"Brand kit and brand look",
 "IMAGERY":"Images, references, generation","COPY":"Headline, CTA, voice","EVIDENCE":"Claims and honesty","ACCOUNT":"Target account (ABM)",
 "LOGOS":"Logo handling","LAYOUT":"Composition and type","REVIEW":"Self-check and acceptance","TOOLS":"Tool mechanics",
 "READING":"What and how to read","BUDGET":"Time and call targets","ASK":"When to ask the user","OUTPUT":"Finishing and reporting",
 "MULTIAGENT":"Helper-agent leftovers","SYNTAX":"DSL facts"}
for r in rows:
    r["sid"] = r["id"].rsplit("-",1)[0]
    r["label"] = LABEL[r["sid"]]
topics = Counter(r["topic"] for r in rows)
data = {"rows": rows, "issues": issues, "labels": LABEL, "groups": GROUPS, "topics": TOPIC_DESC}
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
n_sources = len({r["sid"] for r in rows if r["sid"]!="Z1"})
page = r'''<title>Scene Agent Rule Ledger</title>
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
<header><h1>Scene agent rule ledger</h1>
<p class="lede">Every instruction the solo scene ad agent receives on a turn, one row per rule, tagged by topic. Conflicts are grouped first; the full ledger is below. Nothing has been changed yet: this is the map for the founder review.</p>
<div class="stats"><span><b>''' + str(len(rows)) + r'''</b> rules</span><span><b>''' + str(n_sources) + r'''</b> sources</span><span><b>''' + str(len(issues)) + r'''</b> conflict groups</span><span>captured on <b>feat/scene-delete-key</b> @ 403442e24</span></div></header>
<h2>Conflicts to rule on</h2>
<p class="lede">Ordered by impact. Each group shows the competing rules side by side with their source.</p>
<div id="issues"></div>
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
<li>The system prompt and the 21 tool descriptions were captured by building the real solo agent offline (scripted model, fake engine) and recording the first model call: 68,335 characters of system prompt, 21,529 characters of tool descriptions.</li>
<li>Every file the agent can open (operating note, 32 skills, 7 scene guides, 15 engine guides) and every per-turn wrapper and data file was read in full and split into rules. Conditional blocks the capture did not trigger were taken from source code.</li>
<li>A completeness check matched every sentence containing must / never / do not / cannot / only when / requires against the ledger; the 53 sentences only paraphrased are in “Audit additions”.</li>
<li>Working files: <code>docs/design-harness-alignment/</code> (PROGRESS.md checklist, ledger/*.jsonl, issues.py, sources/).</li>
</ul>
</div>
</main>
<script id="data" type="application/json">''' + blob + r'''</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const byId=Object.fromEntries(D.rows.map(r=>[r.id,r]));
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rowHtml(r,cls){return `<div class="${cls}"><div class="rmeta"><b>${esc(r.id)}</b><span>${esc(r.label)}</span><span>${esc(r.loc)}</span><span class="tag">${esc(r.topic)}</span><span class="tag">${esc(r.strength)}</span><span class="tag">${esc(r.applies)}</span></div><div class="rtext">${esc(r.text)}</div>${r.note?`<div class="rnote">${esc(r.note)}</div>`:''}</div>`}
const iEl=document.getElementById('issues');
iEl.innerHTML=D.issues.map((i,n)=>`<details class="issue"${n<2?' open':''}><summary><span class="sev ${i.severity}">${i.severity}</span><span class="itl">${esc(i.id)} · ${esc(i.title)}</span><span class="isub">${esc(i.topic)} · ${i.groups.reduce((a,g)=>a+g.rows.length,0)} rules</span></summary><div class="ibody"><p>${esc(i.what)}</p><p class="why">${esc(i.why)}</p>${i.groups.map(g=>`<div class="grp"><h4>${esc(g.label)}</h4>${g.rows.map(id=>rowHtml(byId[id],'row')).join('')}</div>`).join('')}</div></details>`).join('');
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
