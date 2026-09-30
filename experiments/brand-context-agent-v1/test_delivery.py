import unittest,tempfile,json
from pathlib import Path
from core import Store
from viewer import build
from retrieval import validate_retrieval
class DeliveryTests(unittest.TestCase):
 def test_public_package_excludes_private_run_files_and_renders_tables(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));s.write('private-response.json',{'api_key':'PRIVATE_CANARY'})
   s.write('documents/company-overview.json',{'key':'company-overview','title':'Company overview','markdown':'| A | B |\n|---|---|\n| one | two |','source_ids':[]})
   build(s)
   payload=json.loads(s.path('public/data.json').read_text())
   self.assertIn('<table>',payload['documents'][0]['html'])
   self.assertFalse(s.path('public/private-response.json').exists())
   self.assertNotIn('PRIVATE_CANARY',s.path('public/data.json').read_text())
 def test_retrieval_rejects_website_as_published_ad(self):
  a={'x':{'origins':[{'collection':'website'}]}}
  r={'cases':[{'id':'published-linkedin','selections':[{'asset_id':'x'}]}]}
  self.assertTrue(validate_retrieval(r,a))
 def test_untrusted_markdown_is_not_executable_html(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));s.write('documents/company-overview.json',{'key':'company-overview','title':'Company','markdown':'<script>alert(1)</script>','source_ids':[]});build(s)
   self.assertNotIn('<script>',json.loads(s.path('public/data.json').read_text())['documents'][0]['html'])
