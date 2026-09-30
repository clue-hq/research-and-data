import tempfile
import unittest
from pathlib import Path
from core import Store
import agent


class AgentTests(unittest.TestCase):
    def test_claim_tool_schema_defines_evidence_contract(self):
        t = next(t for t in agent.TOOLS if t['function']['name'] == 'record_claims')
        item = t['function']['parameters']['properties']['claims']['items']
        self.assertIn('evidence', item.get('required', []))
        self.assertIn('source_id', item['properties']['evidence']['items']['required'])

    def test_claim_tool_rejects_unsupported_quote_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d))
            a = agent.ResearchAgent(s, None)
            result = a.run_tool('record_claims', {'claims': [{'statement': 'Conduit makes payments', 'status': 'observed', 'evidence': [{'source_id': 'invented', 'quote': 'Guaranteed payments'}]}]})
            self.assertTrue(result['rejected'])
            self.assertEqual(s.read('claims.json', {}), {})

    def test_exact_quote_is_retained_for_later_independent_review(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d))
            source = s.source(url='https://conduit.ai/', title='Conduit', text='Automate guest communication with AI agents.', method='test')
            a = agent.ResearchAgent(s, None)
            c = {'statement': 'Conduit offers guest communication automation.', 'status': 'observed', 'topic': 'product', 'evidence': [{'source_id': source['id'], 'quote': 'Automate guest communication with AI agents.'}]}
            r = a.run_tool('record_claims', {'claims': [c]})
            self.assertEqual(len(r['accepted']), 1)
            stored = s.read('claims.json')[r['accepted'][0]]
            self.assertEqual(stored['evidence'], c['evidence'])

    def test_agent_does_not_accept_fake_user_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d))
            r = agent.ResearchAgent(s, None).run_tool('record_claims', {'claims': [{'statement': 'User approved pricing', 'status': 'user_provided', 'evidence': []}]})
            self.assertTrue(r['rejected'])

if __name__ == '__main__': unittest.main()
