"""Reconcile original logo candidates with observed website usage, never invent marks."""
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from core import digest, now
from assets import AssetPipeline, original_url
from rework import asset_context

def collect(store,p):
 sources=store.read('sources.json',{})
 home=p.fetch_page('https://www.conduit.ai/',refresh=True)
 # Content IDs may be reused when text is unchanged but deployment asset URLs change.
 # Inspect the just-refreshed HTML, not an older requested_url in its source record.
 html=store.path('raw/page-'+digest('https://www.conduit.ai/')+'.html').read_text()
 soup=BeautifulSoup(html,'html.parser');pipeline=AssetPipeline(store,p)
 found=[]
 for x in home.get('images',[]):
  if not any(part in original_url(x['url']) for part in ['/icon.png','/apple-icon','/conduit-icon.png']):continue
  a=pipeline.ingest(original_url(x['url']),{'collection':'website','source_id':home['id'],'source_page':home['url'],'alt':x.get('alt'),'role':'official_website_icon'})
  found.append(a['id'])
 observed=[{'src':img.get('src'),'classes':img.get('class',[]),'alt':img.get('alt')} for img in soup.select('img') if 'conduit-wordmark' in str(img)]
 css_records=[]
 for link in soup.select('link[rel="stylesheet"]'):
  url=urljoin(home['url'],link['href'])
  try:body,mime,resolved=p.download(url,limit=4*1024*1024)
  except Exception as e:
   store.event('stylesheet_gap',url=url,error_type=type(e).__name__)
   continue
  text=body.decode(errors='replace')
  fragments=re.findall(r'@font-face\{[^}]+\}|[^{}]*\.(?:invert|brightness-0)[^{}]*\{[^}]+\}',text)
  relevant='\n'.join(fragments)
  if relevant:
   src=store.source(url=resolved,title='Official website font and logo appearance CSS',text=relevant,method='official_stylesheet_excerpts',full_response_sha256=digest(body))
   css_records.append(src['id'])
 store.write('identity-inspection.json',{'at':now(),'website_source_id':home['id'],'wordmark_elements':observed,'official_icon_ids':list(dict.fromkeys(found)),'stylesheet_source_ids':css_records,'note':'Website icons were wrongly excluded by the original generic image filter. Wordmark reverse appearance is CSS on the same original SVG, not a separate downloaded white master.'})
 print('Official icon candidates:',list(dict.fromkeys(found)),flush=True)

def attach_context(store):
 assets=store.read('assets.json',{})
 for a in assets.values():a['agent_context']=asset_context(a)
 store.write('assets.json',assets)

def attach_display_treatments(store):
 """Keep source-observed display instructions available in the agent handoff."""
 pack=store.read('brand-pack.json',{});assets=store.read('assets.json',{})
 for slot in pack.get('slots',[]):
  if not slot.get('css_filter'):continue
  a=assets[slot['asset_id']]
  a['observed_display_treatments']=[{'background':slot['background'],
   'css_filter':slot['css_filter'],'basis':'Observed on the official website; original bytes unchanged.',
   'source_ids':pack.get('source_ids',[]),'separate_original_file':False,
   'use_boundary':'Available for review when the renderer preserves this treatment. Otherwise request a reverse master; never ask an image model to redraw the mark.'}]
  guidance=a.get('analysis',{}).get('guidance',{})
  guidance.update(how_to_use='Preserve original geometry and aspect ratio. Use the dark SVG directly on light; on dark, the recorded official footer treatment is available for review.',
   avoid_when='Avoid low contrast, cropping, stretching or unrecorded color changes. Never recreate the wordmark with an image model.',
   crop_and_placement='Preserve the full original. Only the explicitly recorded website display treatment is supported; it is not a separate white master.',
   background_suitability='Dark original on light. Recorded white display treatment on dark if the renderer preserves it; otherwise request a reverse master.')
  a['agent_context']=asset_context(a)
  a['agent_context']['related_document_keys']=['visual-identity']
  a['agent_context']['relationship_basis']='Observed website identity asset and documented display treatment.'
 store.write('assets.json',assets)

def finalize(store):
 """Record inspected originals and website treatments without synthesizing logo files."""
 import shutil
 from PIL import Image
 from library_guide import save_document
 inspection=store.read('identity-inspection.json')
 observations=store.source(url='https://www.conduit.ai/',title='Website identity: inspected DOM and computed styles',method='browser_dom_computed_style_observation',text='Homepage body background rgb(255, 255, 255); text rgb(41, 37, 30). Buttons background rgb(40, 36, 30), text white. Body uses bodyFont; heading uses seasonFont. Header Conduit wordmark has filter none. Footer uses the same conduit-wordmark.svg with brightness(0) invert(1). A Conduit image points to /conduit-icon.png through the website image optimizer.')
 assets=store.read('assets.json',{})
 descriptions={
  'asset_b8d066fe19fbc0e24e47':('Official transparent Conduit icon','Pale cream right-facing chevron on a transparent canvas. Downloaded from the live website’s conduit-icon.png.','Use on a dark contrasting background; preserve the original geometry and padding.','official_website_original'),
  'asset_1889762a5971823cd61e':('Official Conduit site icon','Pale cream chevron on a dark brown square. This 512px website icon has an opaque background.','Use as a complete app/favicon tile. Do not treat the dark square as transparency.','official_website_original'),
  'asset_27c64ef3b5f723e09124':('Official Conduit touch icon','Pale cream chevron on a dark brown 180px square. Original Apple touch icon from the website.','Use as an app/touch-icon reference at appropriate resolution. Do not enlarge into a primary wordmark.','official_website_original'),
  'asset_4da0c092f8267c5adb40':('Brandfetch Conduit icon · pale transparent','Pale cream chevron in a palette PNG with transparency. Its silhouette matches the higher-resolution website icon. The preview background is not part of the logo.','Prefer the official 512px transparent icon for new draft layouts. Retain this original for provider provenance.','provider_original_visually_concordant'),
  'asset_d4f65f4ffb224f420066':('Brandfetch Conduit icon · dark tile','Dark chevron on a pale rounded tile in a 100px JPEG. This file is opaque, not a transparent dark icon.','Small light-background reference only. Request an official transparent dark master before preparing a high-resolution light-background icon placement.','provider_original_only'),
 }
 for aid,(name,description,usage,authority) in descriptions.items():
  a=assets[aid]
  if a.get('analysis'):store.write('history/assets/'+aid+'/'+str(a.get('analysis_revision',1))+'.json',a)
  im=Image.open(store.path(a['path']));transparent=im.convert('RGBA').getextrema()[-1][0]<255
  a['dimensions']={'width':im.width,'height':im.height,'frames':getattr(im,'n_frames',1),'has_transparency':transparent,'has_alpha_channel':im.mode in ('RGBA','LA')}
  a['analysis']={'name':name,'category':'logo','description':description,'observed':{'composition':'Single right-facing chevron, no wordmark text','transparency':transparent,'original_dimensions':f'{im.width} × {im.height}'},'guidance':{'use_when':usage,'how_to_use':'Use the original asset file, not an image-model recreation.','avoid_when':'Do not stretch, crop into the mark, or imply a customer partnership.','background_suitability':'Dark background for pale icon; light background for dark tile.'},'product_or_use_case':'Conduit company identity','inferred_audience':None,'uncertainties':['Campaign approval and official clear-space specification are not provided.'],'tags':['logo','icon','chevron']}
  a.update(analysis_status='completed',analysis_method='visual_inspection_and_original_file_metadata',analysis_revision=a.get('analysis_revision',1)+1,analysis_at=now(),brand_authority=authority,human_approved=False)
  a.pop('analysis_model',None)
  if a['mime']=='image/png':
   dest=store.path('previews/'+aid+'.png');dest.parent.mkdir(exist_ok=True);shutil.copy2(store.path(a['path']),dest)
  a['agent_context']=asset_context(a)
  a['agent_context']['related_document_keys']=['visual-identity']
  a['agent_context']['relationship_basis']='Inspected company identity asset, mapped directly to the identity guide.'
 store.write('assets.json',assets)
 pack={'slots':[
  {'title':'Wordmark on light','background':'light','asset_id':'asset_761b0b47f1b7c604d186','status':'Official transparent SVG','note':'Original dark wordmark from the company website.'},
  {'title':'Wordmark on dark','background':'dark','asset_id':'asset_761b0b47f1b7c604d186','css_filter':'brightness(0) invert(1)','status':'Observed website treatment','note':'Same original SVG; the website’s footer applies this filter. A separate white master was not found.'},
  {'title':'Icon on dark','background':'dark','asset_id':'asset_b8d066fe19fbc0e24e47','status':'Official transparent PNG · 512px','note':'Original icon discovered in the live website DOM, with transparency verified from the file.'},
  {'title':'Icon on light','background':'light','asset_id':'asset_d4f65f4ffb224f420066','status':'Incomplete · opaque provider tile','note':'The available dark icon is a 100px JPEG. An official transparent dark master remains missing.'}],
  'colors':[{'hex':'#29251E','use':'Observed website text / identity ink'},{'hex':'#FFFFFF','use':'Observed website canvas'},{'hex':'#28241E','use':'Observed primary button background'},{'hex':'#F3F1EC','use':'Brandfetch palette candidate; not a complete semantic token system'},{'hex':'#77D4FF','use':'Brandfetch accent candidate; placement requires brand review'}],
  'color_note':'Website observations and provider palette candidates are distinguished. These are not inferred platform success/error/focus tokens.',
  'typography_note':'Official CSS maps bodyFont to Neue Montreal and seasonFont to Season Mix. Arial and Inter appear as fallbacks/other faces, not substitutes for the primary brand typography. Font binaries are not copied into this review package.',
  'gaps':['Official transparent dark icon master','Separate reverse wordmark master if the export pipeline cannot preserve the observed website treatment','Brand-owner confirmation of logo spacing, palette roles and font-use permissions'],
  'source_ids':[inspection['website_source_id'],observations['id'],*inspection['stylesheet_source_ids']]}
 store.write('brand-pack.json',pack)
 attach_display_treatments(store)
 css_url=store.read('sources.json')[inspection['stylesheet_source_ids'][0]]['url']
 body='''This identity guide separates original company files, observed website presentation and provider candidates. It gives a designer usable source assets while keeping incomplete parts of the logo family visible.

## Logo family and background fit

| Placement | Available asset | Status and use |
| --- | --- | --- |
| Wordmark on light | Dark, transparent website SVG | Official original. Preserve aspect ratio and original lettering. |
| Wordmark on dark | Same website SVG with the footer’s white display treatment | Observed website usage. This is a rendering treatment, not a separately downloaded white master. |
| Icon on dark | Pale, transparent 512px website PNG | Official original; prefer this over the smaller provider version. |
| Icon on light | Dark icon in a 100px provider JPEG tile | Incomplete for transparent high-resolution placement. Request an official dark master. |

The website’s Apple touch icon and site icon are opaque square tiles. They are useful app identity references, but they must not replace the transparent assets in an ad lockup. The Brandfetch pale PNG uses palette transparency; the earlier analysis incorrectly described the viewer background as part of the image. File inspection corrected that error. [Website](https://www.conduit.ai/)

## Color and typography

The live website uses white as the main canvas, #29251E for body text, and #28241E for its dark primary buttons. Brandfetch also supplied #F3F1EC and #77D4FF; retain those as provider palette candidates rather than inventing a complete set of semantic UI tokens. A color being present does not establish its correct use for errors, focus rings or every campaign background.

The website CSS identifies Neue Montreal for body typography and Season Mix for the display face. It also declares fallbacks and other fonts. A fallback declaration is not evidence that Arial is Conduit’s primary brand font. Font files and licensing need to be handled by the existing platform ingestion pipeline before export. [Official stylesheet](CSS_URL)

## How an agent should use this pack

Choose a slot by background contrast and use the original asset identity. For one-to-one ads, compose the seller and target-company marks as separate image layers; do not ask an image model to draw either logo. Preserve proportions, align optical height and allow deliberate space around the separator. The exact clear-space rule is not published in these captured sources and needs brand confirmation.

Website treatments may be reproduced only as explicitly recorded presentation instructions. Do not silently produce new logo files or declare missing variants approved. The standalone preview shows the observed reverse-wordmark treatment so a human can inspect it; the original SVG remains unchanged.

## Remaining gaps and next action

The four intended slots are now visible, but the pack is not four approved transparent masters. The light-background icon still needs an official transparent dark file. If server export cannot preserve the footer treatment, request a reverse wordmark master as well. Confirm spacing, palette roles and font permissions before campaign approval. Brand ingestion should keep these availability states separate from a successful provider HTTP response.
'''.replace('CSS_URL',css_url)
 save_document(store,'visual-identity','Visual identity & logo pack','design',body,pack['source_ids'],{'use_when':['Selecting logo variants, colors and typography for Conduit drafts'],'decisions_supported':['Original asset choice by surface contrast'],'do_not_infer':['All four slots are approved transparent originals','A favicon tile is a wordmark','Provider theme means background color']})
