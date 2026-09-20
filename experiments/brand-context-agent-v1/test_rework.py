import unittest
import tempfile
from pathlib import Path
from rework import select_sources, validate_rich_document, asset_context, SPECS
from viewer import reader_markdown
from markdown_it import MarkdownIt

class ReworkTests(unittest.TestCase):
 def test_final_editorial_pass_is_safe_on_already_corrected_documents(self):
  from core import Store
  from curation import final_editorial_pass
  with tempfile.TemporaryDirectory() as root:
   store=Store(Path(root))
   for key in ('company-overview','brand-messaging','alternatives'):
    store.write('documents/'+key+'.json',{'key':key,'markdown':'Already corrected body.','revision':2,'open_questions':[]})
   final_editorial_pass(store)
   self.assertEqual(store.read('documents/alternatives.json')['revision'],2)
 def test_extra_citation_cell_is_not_silently_lost_by_renderer(self):
  body='# Overview\n\n| Customer | Result |\n| --- | --- |\n| Example | Reported result | [Source](https://example.com) |'
  html=MarkdownIt().enable('table').render(reader_markdown(body))
  self.assertIn('href="https://example.com"',html)
  self.assertNotIn('<h1>',html)
 def test_product_packet_excludes_unrelated_competitor_and_private_baseline(self):
  sources={'a':{'url':'https://www.conduit.ai/product/inbox','text':'Inbox'},'b':{'url':'https://other.example/','text':'Other'},'c':{'url':'https://www.conduit.ai/pricing','text':'Pricing'}}
  picked=select_sources(sources,['/product/inbox','/pricing'])
  self.assertEqual({s['id'] for s in picked},{'a','c'})
 def test_unknown_product_and_fabricated_evidence_fail(self):
  spec=next(s for s in SPECS if s['key']=='product-inbox')
  doc={'key':spec['key'],'title':spec['title'],'markdown':'## Overview\nShort', 'source_ids':[],'evidence_notes':[{'source_id':'invented','quote':'fabricated evidence'}]}
  self.assertTrue(validate_rich_document(doc,spec,{}))
 def test_asset_context_keeps_fact_inference_and_identity_separate(self):
  a={'id':'a','sha256':'hash','origins':[{'collection':'website','source_page':'https://www.conduit.ai/'}], 'analysis':{'category':'logo','description':'A wordmark','observed':{'text':'Conduit'},'guidance':{'avoid':'Do not recolor'},'uncertainties':['Approval unknown']}}
  c=asset_context(a)
  self.assertEqual(c['observed'],{'text':'Conduit'})
  self.assertFalse(c['approved_for_campaign'])
  self.assertIn('guidance_interpretation',c)
 def test_document_keys_unique_and_product_granularity_preserved(self):
  self.assertEqual(len(SPECS),len({s['key'] for s in SPECS}))
  self.assertTrue({'product-agents','product-inbox','product-portals','product-workflows'}.issubset({s['key'] for s in SPECS}))
 def test_source_observed_treatment_survives_agent_handoff_without_new_master_claim(self):
  treatment={'css_filter':'brightness(0) invert(1)','separate_original_file':False,'source_ids':['source']}
  context=asset_context({'id':'logo','observed_display_treatments':[treatment]})
  self.assertEqual(context['observed_display_treatments'],[treatment])
  self.assertFalse(context['approved_for_campaign'])
