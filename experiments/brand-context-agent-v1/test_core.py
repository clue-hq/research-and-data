import tempfile
import unittest
from pathlib import Path

import core


class GovernanceTests(unittest.TestCase):
    def test_malformed_evidence_is_rejected_without_crashing(self):
        self.assertTrue(core.validate_claim({'statement': 'Example statement', 'status': 'observed', 'evidence': 'source'}, {}))
        self.assertTrue(core.validate_claim({'statement': 'Example statement', 'status': 'observed', 'evidence': ['source']}, {}))

    def test_reject_private_and_credential_urls(self):
        for url in ['http://localhost/a', 'http://127.0.0.1', 'http://169.254.169.254/', 'file:///etc/passwd', 'https://user:secret@conduit.ai', 'http://[::1]/', 'https://foo.local/']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                core.public_url(url)
        self.assertEqual(core.public_url('https://conduit.ai/product/inbox#x'), 'https://conduit.ai/product/inbox')

    def test_store_cannot_escape_experiment(self):
        with tempfile.TemporaryDirectory() as d:
            s = core.Store(Path(d))
            with self.assertRaises(ValueError): s.write('../outside.json', {})
            with self.assertRaises(ValueError): s.write('/tmp/outside.json', {})

    def test_evidence_quote_must_exist_in_source(self):
        sources = {'s1': {'text': 'Conduit connects guest messages in one inbox.', 'url': 'https://conduit.ai/product/inbox'}}
        valid = {'statement': 'Conduit offers a shared inbox.', 'status': 'observed', 'evidence': [{'source_id': 's1', 'quote': 'guest messages in one inbox'}]}
        self.assertEqual(core.validate_claim(valid, sources), [])
        invalid = {**valid, 'evidence': [{'source_id': 's1', 'quote': 'guarantees 92% revenue growth'}]}
        self.assertTrue(core.validate_claim(invalid, sources))

    def test_fact_without_evidence_is_rejected(self):
        self.assertTrue(core.validate_claim({'statement': 'Costs $50', 'status': 'observed', 'evidence': []}, {}))
        self.assertTrue(core.validate_claim({'statement': 'Costs $50', 'status': 'verified', 'evidence': []}, {}))

    def test_unknown_is_not_published_as_an_observed_fact(self):
        claim = {'statement': 'Pricing requires confirmation.', 'status': 'unknown', 'evidence': []}
        self.assertEqual(core.validate_claim(claim, {}), [])

    def test_budget_blocks_overrun_and_counts_uncertain_calls(self):
        with tempfile.TemporaryDirectory() as d:
            b = core.Budget(core.Store(Path(d)), ceiling=1.0)
            key = b.reserve('model', .7)
            with self.assertRaises(core.BudgetExceeded): b.reserve('model', .4)
            b.settle(key, actual=None, details={'status': 'uncertain'})
            self.assertAlmostEqual(b.exposure(), .7)
            with self.assertRaises(core.BudgetExceeded): b.reserve('model', .4)
            b.settle(key, actual=.2, details={'status': 'completed'})
            self.assertAlmostEqual(b.exposure(), .2)

    def test_cache_key_changes_with_evidence_or_prompt(self):
        self.assertEqual(core.digest({'a': 1, 'b': 2}), core.digest({'b': 2, 'a': 1}))
        self.assertNotEqual(core.digest({'a': 1}), core.digest({'a': 2}))

    def test_asset_dedup_preserves_multiple_origins(self):
        with tempfile.TemporaryDirectory() as d:
            s = core.Store(Path(d))
            a = s.asset(b'original-svg', 'image/svg+xml', {'url': 'https://conduit.ai/logo.svg', 'collection': 'website'})
            b = s.asset(b'original-svg', 'image/svg+xml', {'url': 'https://example.org/same.svg', 'collection': 'brand-provider'})
            self.assertEqual(a['id'], b['id'])
            self.assertEqual(len(s.read('assets.json')[a['id']]['origins']), 2)


if __name__ == '__main__': unittest.main()
