"""Explicit, cached public-research adapters; private responses stay in the run directory."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from core import Budget, check_dns, digest, now, public_url


class Providers:
    def __init__(self, store, env, transport=None):
        self.store, self.env = store, env
        self.budget = Budget(store)
        self.client = httpx.Client(timeout=90, transport=transport, follow_redirects=False)
        self.model = env.get('ONBOARDING_SYNTHESIS_AGENT_MODEL') or 'x-ai/grok-4.6'

    def download(self, url, limit=20 * 1024 * 1024):
        for _ in range(5):
            url = check_dns(public_url(url))
            with self.client.stream('GET', url, headers={'User-Agent': 'ConduitBrandResearchPilot/1.0'}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = public_url(urljoin(url, r.headers['location']))
                    continue
                r.raise_for_status()
                data = bytearray()
                for chunk in r.iter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError('Remote content exceeds bounded download size')
                return bytes(data), r.headers.get('content-type', '').split(';')[0], str(r.url)
        raise RuntimeError('Too many redirects')

    def fetch_page(self, url):
        url = public_url(url)
        cached = self.store.read('cache/page-' + digest(url) + '.json')
        if cached:
            return cached
        with self.store.lock:
            self.budget.enforce_count('page', 50)
            receipt = self.budget.reserve('page', 0, url=url)
        try:
            data, mime, final_url = self.download(url, limit=8 * 1024 * 1024)
            if mime not in ('text/html', 'application/xhtml+xml', 'text/plain', 'application/xml', 'text/xml'):
                raise ValueError('Page tool accepts HTML or text; use asset acquisition for binaries')
            soup = BeautifulSoup(data, 'html.parser')
            title = soup.title.get_text(' ', strip=True) if soup.title else final_url
            images = []
            for tag in soup.select('img, source'):
                src = tag.get('src') or tag.get('data-src')
                if not src and tag.get('srcset'):
                    src = tag['srcset'].split(',')[-1].strip().split(' ')[0]
                if src and not src.startswith('data:'):
                    images.append({'url': urljoin(final_url, src), 'alt': tag.get('alt', ''),
                        'width': tag.get('width'), 'height': tag.get('height')})
            for tag in soup.select('meta[property="og:image"], link[rel*="icon"]'):
                src = tag.get('content') or tag.get('href')
                if src: images.append({'url': urljoin(final_url, src), 'alt': tag.get('property') or 'Website icon'})
            links = list(dict.fromkeys(urljoin(final_url, a['href']) for a in soup.select('a[href]')
                        if not a['href'].startswith(('mailto:', 'tel:', 'javascript:', '#'))))
            for tag in soup.select('script, style, noscript'):
                tag.decompose()
            text = re.sub(r'\n{3,}', '\n\n', soup.get_text('\n', strip=True))[:100000]
            source = self.store.source(url=final_url, title=title, text=text, method='direct_html',
                images=images, links=links, content_type=mime, requested_url=url)
            raw = self.store.path('raw/page-' + digest(url) + '.html')
            raw.parent.mkdir(exist_ok=True)
            raw.write_bytes(data)
            self.store.write('cache/page-' + digest(url) + '.json', source)
            self.budget.settle(receipt, 0, {'status': 'completed', 'source_id': source['id']})
            return source
        except Exception as e:
            self.budget.settle(receipt, 0, {'status': 'failed', 'error_type': type(e).__name__})
            raise

    def paid(self, provider, operation, url, payload, *, headers, reserve, maximum, cache=True, timeout=180, method='POST', retry_uncertain=False):
        # Payload identity excludes credentials. They never enter cache keys, traces or files.
        safe_payload = {k: v for k, v in payload.items() if k not in ('api_key', 'email')}
        key = digest({'provider': provider, 'operation': operation, 'payload': safe_payload})
        path = 'cache/' + provider + '-' + key + '.json'
        with self.store.lock:
            prior = self.store.read(path)
            if prior and prior.get('status') == 'completed' and cache:
                return prior['response']
            if prior and prior.get('status') != 'completed' and not retry_uncertain:
                raise RuntimeError(f'{provider} request previously failed or is uncertain; no automatic paid retry ({key[:12]})')
            self.budget.enforce_count(provider, maximum)
            receipt = self.budget.reserve(provider, reserve, operation=operation, request_hash=key,
                retry_of=prior.get('receipt') if prior else None)
            self.store.write(path, {'status': 'pending', 'receipt': receipt, 'started_at': now()})
        started = time.monotonic()
        r = None
        try:
            r = self.client.request(method, url, json=payload if method == 'POST' else None, headers=headers, timeout=timeout)
            if r.status_code >= 400 or r.status_code == 204:
                raise RuntimeError(f'{provider} HTTP {r.status_code}')
            response = r.json()
            if not isinstance(response, dict) or response.get('error'):
                raise RuntimeError(f'{provider} returned an error envelope')
            actual = None
            if provider == 'exa': actual = (response.get('costDollars') or {}).get('total')
            if provider == 'model': actual = (response.get('usage') or {}).get('cost')
            self.budget.settle(receipt, float(actual) if actual is not None else None,
                {'status': 'completed', 'duration_s': round(time.monotonic()-started, 2),
                 'credits': 1 if provider == 'adyntel' else None,
                 'usage': response.get('usage'), 'provider_request_id': response.get('id') or response.get('requestId'),
                 'dollar_accounting': 'reported' if actual is not None else 'unreported'})
            self.store.write(path, {'status': 'completed', 'receipt': receipt, 'response': response})
            return response
        except Exception as e:
            failure = {'http_status': r.status_code if r is not None else None}
            self.budget.settle(receipt, None, {'status': 'uncertain', 'error_type': type(e).__name__,
                'duration_s': round(time.monotonic()-started, 2), **failure})
            self.store.write(path, {'status': 'uncertain', 'receipt': receipt, 'error_type': type(e).__name__, **failure})
            raise RuntimeError(f'{provider} request failed ({type(e).__name__}, HTTP {failure["http_status"]}); reservation retained') from None

    def search(self, query, domains=None):
        key = self.env.get('CLUE_EXA_API_KEY')
        if not key: raise RuntimeError('Exa credential missing')
        payload = {'query': query, 'type': 'auto', 'numResults': 6,
                   'contents': {'text': {'maxCharacters': 12000}}}
        if domains: payload['includeDomains'] = domains
        data = self.paid('exa', 'search', 'https://api.exa.ai/search', payload,
            headers={'x-api-key': key}, reserve=.10, maximum=24)
        results = []
        for item in data.get('results', []):
            if not item.get('url'): continue
            source = self.store.source(url=item['url'], title=item.get('title', item['url']),
                text=item.get('text') or '\n'.join(item.get('highlights') or []), method='exa_search',
                published_date=item.get('publishedDate'), query=query)
            results.append({'id': source['id'], 'url': source['url'], 'title': source['title'], 'text': source['text'][:6500]})
        return results

    def model_info(self, model=None):
        model = model or self.model
        data = self.store.read('model-catalog.json')
        if data is None:
            r = self.client.get('https://openrouter.ai/api/v1/models')
            r.raise_for_status()
            data = r.json()
            self.store.write('model-catalog.json', data)
        match = next((m for m in data['data'] if m['id'] == model), None)
        if not match: raise RuntimeError('Configured model unavailable in current OpenRouter catalog: ' + model)
        return match

    def chat(self, messages, *, tools=None, max_tokens=7000, json_mode=False, model=None):
        model = model or self.model
        info = self.model_info(model)
        prices = info['pricing']
        metering_messages = json.loads(json.dumps(messages))
        image_upper = 0
        for message in metering_messages:
            if isinstance(message.get('content'), list):
                for part in message['content']:
                    if part.get('type') == 'image_url':
                        part['image_url'] = {'url': '[bounded 512px preview]'}
                        image_upper += 4096
        prompt_tokens_upper = len(json.dumps(metering_messages)) + len(json.dumps(tools or [])) + image_upper
        active_prices = prices
        for override in prices.get('overrides', []):
            if prompt_tokens_upper >= override.get('min_prompt_tokens', float('inf')):
                active_prices = {**prices, **override}
        reserve = prompt_tokens_upper * float(active_prices['prompt']) + max_tokens * float(active_prices['completion']) + float(prices.get('request', 0) or 0)
        payload = {'model': model, 'messages': messages, 'max_tokens': max_tokens}
        if tools: payload.update(tools=tools, tool_choice='auto', parallel_tool_calls=True)
        if json_mode: payload['response_format'] = {'type': 'json_object'}
        key = self.env.get('CLUE_OPENROUTER_API_KEY') or self.env.get('OPENROUTER_API_KEY')
        if not key: raise RuntimeError('OpenRouter credential missing')
        return self.paid('model', 'chat', 'https://openrouter.ai/api/v1/chat/completions', payload,
            headers={'Authorization': 'Bearer ' + key}, reserve=reserve, maximum=50, timeout=240)
