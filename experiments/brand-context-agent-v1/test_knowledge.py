import unittest
from knowledge import validate_document
class KnowledgeTests(unittest.TestCase):
 def test_unresolved_evidence_cannot_enter_reader(self):
  d={'key':'ideal-customers','title':'Ideal customers','markdown':'A factual claim [source](https://evil.example/a)', 'source_ids':['invented']}
  self.assertTrue(validate_document(d,{}))
 def test_filenames_are_not_reader_titles(self):
  self.assertTrue(validate_document({'key':'company','title':'company.md','markdown':'Text','source_ids':[]},{}))
 def test_evidence_drawer_requires_every_body_and_criterion_source(self):
  sources={'a':{'url':'https://conduit.ai/a'},'b':{'url':'https://conduit.ai/b'}}
  d={'key':'x','title':'X','markdown':'[Source](https://conduit.ai/a)','source_ids':[],'icp_criteria':[{'source_ids':['b']}]}
  self.assertTrue(validate_document(d,sources))
