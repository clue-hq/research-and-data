"""Add only native hyperlink relationships; verify original workbook preservation.

All cell content, formulas, tables and styles are authored with artifact-tool.
This uses the existing workbook's native-link fallback, not a spreadsheet writer.
"""
import json,re
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3]
SRC=ROOT/'.artifacts/research-model-evaluation-20260928'
OUT=ROOT/'outputs/research-model-evaluation-20260928'
BOOK=OUT/'research-model-comparison.xlsx'
M='http://schemas.openxmlformats.org/spreadsheetml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';P='http://schemas.openxmlformats.org/package/2006/relationships'
E.register_namespace('',M);E.register_namespace('r',R)
def load(p):
 with ZipFile(p) as z:return {n:z.read(n) for n in z.namelist()}
def sheets(files):
 rel={x.get('Id'):x.get('Target') for x in E.fromstring(files['xl/_rels/workbook.xml.rels'])};ans={}
 for x in E.fromstring(files['xl/workbook.xml']).find(f'{{{M}}}sheets'):
  p=rel[x.get(f'{{{R}}}id')];ans[x.get('name')]=p.lstrip('/') if p.startswith('/') else 'xl/'+p
 return ans
def native(files):
 ans={}
 for name,p in sheets(files).items():
  rp=str(Path(p).parent/'_rels'/(Path(p).name+'.rels')); rel={x.get('Id'):x.get('Target') for x in E.fromstring(files[rp])} if rp in files else {}
  for h in E.fromstring(files[p]).findall(f'{{{M}}}hyperlinks/{{{M}}}hyperlink'):ans[(name,h.get('ref'))]=rel.get(h.get(f'{{{R}}}id'),h.get('location'))
 return ans
old=load(SRC/'research-model-comparison.before-retries.xlsx');current=load(BOOK);oldlinks=native(old)
assert len(oldlinks)==361
combined=oldlinks|{(x['sheet'],x['cell']):x['target'] for x in json.loads((SRC/'new-native-links.json').read_text())}
for name,p in sheets(current).items():
 xml=E.fromstring(current[p]);rp=str(Path(p).parent/'_rels'/(Path(p).name+'.rels'));rel=E.fromstring(current[rp]) if rp in current else E.Element(f'{{{P}}}Relationships')
 for x in list(rel):
  if x.get('Type')==R+'/hyperlink':rel.remove(x)
 for h in xml.findall(f'{{{M}}}hyperlinks'):xml.remove(h)
 hs=E.Element(f'{{{M}}}hyperlinks')
 for n,((sn,cell),target) in enumerate(combined.items()):
  if sn!=name:continue
  rid='VerifiedLink'+str(n);E.SubElement(rel,f'{{{P}}}Relationship',{'Id':rid,'Type':R+'/hyperlink','Target':target,'TargetMode':'External'});E.SubElement(hs,f'{{{M}}}hyperlink',{'ref':cell,f'{{{R}}}id':rid})
 if len(hs):
  later={'printOptions','pageMargins','pageSetup','headerFooter','rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
  ix=next((i for i,x in enumerate(xml) if x.tag.split('}')[-1] in later),len(xml));xml.insert(ix,hs)
 current[p]=E.tostring(xml,encoding='utf-8',xml_declaration=True);current[rp]=E.tostring(rel,encoding='utf-8',xml_declaration=True)
tmp=BOOK.with_suffix('.tmp')
with ZipFile(tmp,'w',ZIP_DEFLATED) as z:
 for n,b in current.items():z.writestr(n,b)
tmp.replace(BOOK)
new=load(BOOK);assert sheets(old)==sheets(new);assert native(new)==combined
def cells(files,p):
 strings=[]
 if 'xl/sharedStrings.xml' in files:
  strings=[''.join(si.itertext()) for si in E.fromstring(files['xl/sharedStrings.xml'])]
 ans={}
 for c in E.fromstring(files[p]).findall(f'.//{{{M}}}sheetData/{{{M}}}row/{{{M}}}c'):
  v=c.find(f'{{{M}}}v');f=c.find(f'{{{M}}}f');inline=c.find(f'{{{M}}}is');value=v.text if v is not None else None
  if c.get('t')=='s':value=strings[int(value)]
  elif inline is not None:value=''.join(inline.itertext())
  ans[c.get('r')]=(f.text if f is not None else None,value)
 return ans
checked=0;differences=[]
for name,p in sheets(old).items():
 a,b=cells(old,p),cells(new,p)
 for cell,v in a.items():
  if name=='Costs' and re.fullmatch('[A-M]19',cell):continue
  if (name,cell) in {('Runs','A2'),('Method','B6'),('Method','B7')}:continue
  now=b.get(cell,(None,None))
  if v!=now:
   try:equal=v[0]==now[0] and abs(float(v[1])-float(now[1]))<1e-10
   except (ValueError,TypeError):equal=False
   if not equal:differences.append((name,cell,v,now))
  checked+=1
assert not differences,differences[:20]
for name,p in sheets(old).items():
 for tag in ['mergeCells','cols']:
  a=E.fromstring(old[p]).find(f'{{{M}}}{tag}');b=E.fromstring(new[p]).find(f'{{{M}}}{tag}');assert E.tostring(a)==E.tostring(b),(name,tag)
 # Freeze panes are stable even if sheet view serialization changes.
 a=E.fromstring(old[p]).find(f'.//{{{M}}}pane');b=E.fromstring(new[p]).find(f'.//{{{M}}}pane');assert a.attrib==b.attrib,(name,'pane')
for target in combined.values():
 if target.startswith('file://'):assert Path(target[7:]).exists(),target
tot=cells(new,sheets(new)['Costs']);assert abs(float(tot['K21'][1])-86.9842821676)<1e-8;assert abs(float(tot['L21'][1])-32.3)<1e-8
errors=[]
for name,p in sheets(new).items():
 errors.extend((name,c.get('r')) for c in E.fromstring(new[p]).findall(f'.//{{{M}}}c') if c.get('t')=='e')
assert not errors,errors
result={'original_cells_preserved':checked,'original_native_links_preserved':len(oldlinks),'native_links':len(combined),'sheets':list(sheets(new)),'known_total_usd':float(tot['K21'][1]),'ai_ark_credits':float(tot['L21'][1]),'formula_errors':errors,'column_widths_merges_and_freeze_panes':'preserved','local_links':'all targets exist'}
(OUT/'update-verification.json').write_text(json.dumps(result,indent=2));(OUT/'native-hyperlinks.json').write_text(json.dumps([{'sheet':s,'cell':c,'target':t} for (s,c),t in combined.items()],indent=2));print(json.dumps(result,indent=2))
