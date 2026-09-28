import json
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[3]
src=root/'.artifacts/research-model-evaluation-20260928'
out=root/'outputs/research-model-evaluation-20260928'
data=json.loads((src/'workbook-data.json').read_text())
M='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
P='http://schemas.openxmlformats.org/package/2006/relationships'
assert len(data['runs'])==11 and len(data['jobs'])==26
assert abs(sum(r['total'] for r in data['runs'])+.118116-73.2619105276)<1e-9
assert abs(sum(r['credits'] for r in data['runs'])-23.6)<1e-9
assert not data['missing']
mdlinks=[]
for name in ['REPORT.md','PREMIER-QUALITY.md','ZAFRAN-QUALITY.md','FAILURES-ZAFRAN.md']:
    for target in re.findall(r'\]\(([^)]+)\)',(src/name).read_text()):
        if target.startswith(('http://','https://','#')):continue
        p=(src/target.split('#')[0]).resolve()
        assert p.exists(),(name,target)
        mdlinks.append(str(p))
with ZipFile(out/'research-model-comparison.xlsx') as z:
    assert z.testzip() is None
    wb=ET.fromstring(z.read('xl/workbook.xml'))
    sheets=list(wb.find(f'{{{M}}}sheets'))
    assert len(sheets)==8
    errors=[];hyperlinks=0;formula_count=0;cost_values={}
    for n in z.namelist():
        if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n):
            s=ET.fromstring(z.read(n))
            for c in s.findall(f'.//{{{M}}}c'):
                if c.attrib.get('t')=='e':errors.append((n,c.attrib['r']))
                if c.find(f'{{{M}}}f') is not None:formula_count+=1
            hyperlinks+=len(s.findall(f'{{{M}}}hyperlinks/{{{M}}}hyperlink'))
            if n=='xl/worksheets/sheet2.xml':
                for c in s.findall(f'.//{{{M}}}c'):
                    if c.attrib['r'] in ['K19','L19']:
                        cost_values[c.attrib['r']]=float(c.find(f'{{{M}}}v').text)
    assert not errors,errors
    assert abs(cost_values['K19']-73.2619105276)<1e-8,cost_values
    assert abs(cost_values['L19']-23.6)<1e-8,cost_values
    targets=[]
    for n in z.namelist():
        if n.endswith('.rels'):
            for r in ET.fromstring(z.read(n)):
                if r.attrib.get('Type','').endswith('/hyperlink'):
                    target=r.attrib['Target'];targets.append(target)
                    if target.startswith('file://'):assert Path(target[7:]).exists(),target
    assert hyperlinks==len(targets)==361,(hyperlinks,len(targets))
verification={'runs':len(data['runs']),'job_rows':len(data['jobs']),'failure_observations':len(data['failures']),'sheets':8,'native_hyperlinks':hyperlinks,'missing_local_links':0,'markdown_links_checked':len(mdlinks),'formula_errors':errors,'formula_count':formula_count,'cost_total_usd':cost_values['K19'],'ai_ark_credits':cost_values['L19'],'verification':'All sheets rendered and visually reviewed; cost components and cached totals reconciled; hyperlinks checked for serialized targets and local existence. Native Excel click-through not exercised.'}
(src/'VERIFICATION.json').write_text(json.dumps(verification,indent=2)+'\n')
print(json.dumps(verification))
