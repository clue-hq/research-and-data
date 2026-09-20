import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import httpx
from core import Store
import providers


class ProviderTests(unittest.TestCase):
    def test_linked_markdown_documentation_is_researchable(self):
        def serve(request):
            return httpx.Response(200, headers={'content-type':'text/markdown'}, text='# Inbox\n\nGuest conversations stay in one workspace.')
        with tempfile.TemporaryDirectory() as d, patch('providers.check_dns', lambda u: u):
            p=providers.Providers(Store(Path(d)), {}, transport=httpx.MockTransport(serve))
            source=p.fetch_page('https://conduit.ai/product/inbox.md')
            self.assertIn('Guest conversations stay',source['text'])
            self.assertEqual(source['content_type'],'text/markdown')

    def test_page_caches_original_without_repeating_transport(self):
        calls = []
        def serve(request):
            calls.append(request.url)
            return httpx.Response(200, text='<html><title>Conduit</title><h1>Guest communication</h1><p>One shared inbox.</p><img src="/hero.png" alt="Inbox interface"><a href="/product/inbox">Inbox</a></html>')
        with tempfile.TemporaryDirectory() as d, patch('providers.check_dns', lambda u: u):
            p = providers.Providers(Store(Path(d)), {}, transport=httpx.MockTransport(serve))
            a = p.fetch_page('https://conduit.ai/')
            b = p.fetch_page('https://conduit.ai/')
            self.assertEqual(a['id'], b['id'])
            self.assertEqual(len(calls), 1)
            self.assertEqual(a['images'][0]['url'], 'https://conduit.ai/hero.png')
            self.assertIn('One shared inbox', a['text'])

    def test_provider_failure_does_not_auto_retry_paid_call(self):
        calls = []
        def fail(request):
            calls.append(request.url)
            return httpx.Response(503, text='temporary failure')
        with tempfile.TemporaryDirectory() as d:
            p = providers.Providers(Store(Path(d)), {'CLUE_EXA_API_KEY': 'test-only'}, transport=httpx.MockTransport(fail))
            for _ in range(2):
                with self.assertRaises(RuntimeError): p.search('Conduit hospitality')
            self.assertEqual(len(calls), 1)
            self.assertGreater(p.budget.exposure(), 0)

    def test_redirect_to_private_host_is_rejected(self):
        def redirect(request): return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        with tempfile.TemporaryDirectory() as d, patch('providers.check_dns', lambda u: u):
            p = providers.Providers(Store(Path(d)), {}, transport=httpx.MockTransport(redirect))
            with self.assertRaises(ValueError): p.fetch_page('https://conduit.ai/')


if __name__ == '__main__': unittest.main()
