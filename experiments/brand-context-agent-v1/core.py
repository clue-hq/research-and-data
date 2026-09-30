"""Standalone custody and governance. No Clue imports or database access."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def public_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if p.scheme not in ('http', 'https') or not host or p.username or p.password:
        raise ValueError('Public HTTP(S) URL required without credentials')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Private destinations are outside this experiment')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError('Non-public IP address')
    if p.port not in (None, 80, 443):
        raise ValueError('Non-web ports are outside this experiment')
    return urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))


def check_dns(url):
    url = public_url(url)
    host = urlsplit(url).hostname
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Destination DNS includes a private address')
    return url


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def path(self, name):
        if Path(name).is_absolute():
            raise ValueError('Absolute experiment paths are not allowed')
        p = (self.root / name).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError('Path escapes experiment')
        return p

    def read(self, name, default=None):
        with self.lock:
            p = self.path(name)
            return json.loads(p.read_text()) if p.exists() else default

    def write(self, name, value):
        with self.lock:
            p = self.path(name)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + '.tmp-' + uuid.uuid4().hex)
            tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
            os.replace(tmp, p)

    def event(self, kind, **data):
        with self.lock:
            with self.path('events.jsonl').open('a') as f:
                f.write(json.dumps({'at': now(), 'kind': kind, **data}, ensure_ascii=False) + '\n')

    def source(self, *, url, title, text, method, **meta):
        public_url(url)
        key = 'src_' + digest({'url': url, 'text': text})[:16]
        with self.lock:
            sources = self.read('sources.json', {})
            sources.setdefault(key, {'id': key, 'url': url, 'title': title, 'text': text,
                'method': method, 'retrieved_at': now(), 'sha256': digest(text.encode()), **meta})
            self.write('sources.json', sources)
        return sources[key]

    def asset(self, data, mime, origin):
        key = 'asset_' + digest(data)[:20]
        ext = {'image/svg+xml': '.svg', 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
               'image/gif': '.gif', 'video/mp4': '.mp4', 'application/pdf': '.pdf'}.get(mime.split(';')[0], '.bin')
        with self.lock:
            assets = self.read('assets.json', {})
            if key not in assets:
                path = 'originals/' + key + ext
                self.path(path).parent.mkdir(exist_ok=True)
                self.path(path).write_bytes(data)
                assets[key] = {'id': key, 'sha256': digest(data), 'path': path, 'mime': mime,
                    'byte_length': len(data), 'retrieved_at': now(), 'origins': [], 'analysis_status': 'pending'}
            if origin not in assets[key]['origins']:
                assets[key]['origins'].append(origin)
            self.write('assets.json', assets)
        return assets[key]


def validate_claim(claim, sources):
    if not isinstance(claim, dict):
        return ['Claim must be an object']
    errors = []
    status = claim.get('status')
    if status not in ('observed', 'hypothesis', 'recommendation', 'unknown', 'user_provided'):
        errors.append('Invalid evidence status')
    if not str(claim.get('statement', '')).strip():
        errors.append('Statement is required')
    evidence = claim.get('evidence', [])
    if not isinstance(evidence, list) or any(not isinstance(e, dict) for e in evidence):
        return errors + ['Evidence must be an array of source_id and quote objects']
    if status in ('observed', 'hypothesis') and not evidence:
        errors.append('Observed facts and research hypotheses require evidence')
    for e in evidence:
        source = sources.get(e.get('source_id'))
        quote = ' '.join(str(e.get('quote', '')).split())
        if not source:
            errors.append('Unknown source')
        elif len(quote) < 12 or quote not in ' '.join(source['text'].split()):
            errors.append('Evidence quote is not an exact source span')
    return errors


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, store, ceiling=10.0):
        self.store, self.ceiling = store, ceiling

    def exposure(self):
        return sum(r['actual_usd'] if r.get('actual_usd') is not None else r['reserved_usd']
                   for r in self.store.read('spend.json', []))

    def reserve(self, provider, amount, **meta):
        if amount < 0:
            raise ValueError('Negative reservation')
        with self.store.lock:
            if self.exposure() + amount > self.ceiling:
                raise BudgetExceeded(f'Initial ${self.ceiling:g} research/model ceiling reached')
            rows = self.store.read('spend.json', [])
            key = uuid.uuid4().hex
            rows.append({'id': key, 'provider': provider, 'reserved_usd': amount, 'actual_usd': None,
                'started_at': now(), 'status': 'reserved', **meta})
            self.store.write('spend.json', rows)
            return key

    def settle(self, key, actual, details):
        with self.store.lock:
            rows = self.store.read('spend.json', [])
            row = next(r for r in rows if r['id'] == key)
            row.update(details)
            row['actual_usd'] = actual
            row['finished_at'] = now()
            self.store.write('spend.json', rows)

    def enforce_count(self, provider, maximum):
        count = sum(r['provider'] == provider for r in self.store.read('spend.json', []))
        if count >= maximum:
            raise BudgetExceeded(f'{provider} call limit {maximum} reached')


def require_exclusive_run(store):
    import fcntl
    handle = store.path('run.lock').open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError('This experiment is already running; inspect its existing process')
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle
