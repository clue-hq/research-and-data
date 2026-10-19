"""Ordered stylesheet acquisition and bounded, in-place import expansion.

Output chunks retain their own URL base. Conditional wrappers live in effective
CSS so every existing consumer sees the same cascade; raw source text and order
remain available as capture evidence. Network requests are deduplicated, source
occurrences are not.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urljoin, urlsplit

import tinycss2

from .net import BoundedFetcher, FetchRequest
from .snapshot import Stylesheet

MAX_IMPORT_DEPTH = 4
MAX_IMPORT_REQUESTS = 64
MAX_CSS_CHUNKS = 4096
MAX_EFFECTIVE_CSS_BYTES = 32 * 1024 * 1024


def _diag(message: str) -> dict:
    return {"code": "LUMI0542", "severity": "warning", "message": message}


def _tokens(values):
    return [v for v in values if v.type not in ("whitespace", "comment")]


def _import(rule, path):
    """Read CSS tokens, including quoted/escaped URLs and import conditions."""
    if rule.content is not None:
        return None
    values = _tokens(rule.prelude)
    if not values:
        return None
    first, *rest = values
    if first.type in ("string", "url"):
        href = first.value
    elif first.type == "function" and first.lower_name == "url":
        args = _tokens(first.arguments)
        if len(args) != 1 or args[0].type != "string":
            return None
        href = args[0].value
    else:
        return None
    if not href.strip():
        return None
    wrappers = []
    if rest and rest[0].type == "ident" and rest[0].value.lower() == "layer":
        rest.pop(0)
        name = "lumen-capture-import-" + hashlib.sha256(str(path).encode()).hexdigest()[:20]
        wrappers.append("@layer " + name)
    elif rest and rest[0].type == "function" and rest[0].lower_name == "layer":
        layer = rest.pop(0)
        name = tinycss2.serialize(layer.arguments).strip()
        parts = _tokens(layer.arguments)
        if not parts or any(v.type not in ("ident", "literal") for v in parts):
            return None
        if any(v.type == "literal" and v.value != "." for v in parts):
            return None
        wrappers.append("@layer " + name)
    if rest and rest[0].type == "function" and rest[0].lower_name == "supports":
        condition = tinycss2.serialize(rest.pop(0).arguments).strip()
        if not condition:
            return None
        wrappers.append("@supports (" + condition + ")")
    if rest:
        # Serialize original whitespace between media tokens; token objects retain
        # their values but filtering whitespace would join 'screen and'.
        positions = {id(v): i for i, v in enumerate(rule.prelude)}
        media = tinycss2.serialize(rule.prelude[positions[id(rest[0])] :]).strip()
        if any(v.type in ("error", "{} block", ";") for v in rest):
            return None
        wrappers.append("@media " + media)
    # An inactive import must not establish its layer in the cascade.
    conditions = [w for w in wrappers if not w.startswith("@layer ")]
    layers = [w for w in wrappers if w.startswith("@layer ")]
    return href, conditions + layers


def _rules(text):
    return tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False)


def _imports(text, base, path):
    allowed = True
    for index, rule in enumerate(_rules(text)):
        kind = getattr(rule, "lower_at_keyword", "")
        if rule.type in ("whitespace", "comment"):
            continue
        if kind == "import":
            if allowed:
                try:
                    parsed = _import(rule, (base, *path, index))
                    if parsed:
                        target = urljoin(base, parsed[0])
                        urlsplit(target)  # Validate even when base is empty.
                        yield index, target, parsed[1]
                except ValueError:
                    # Bad URL syntax or malformed tokens must not abort a page.
                    # Assembly diagnoses an unsupported import at this position.
                    continue
        elif kind == "charset" or (kind == "layer" and rule.content is None):
            continue
        else:
            allowed = False


def _wrap(text, wrappers):
    for wrapper in reversed(wrappers):
        text = wrapper + "{" + text + "}"
    return text


async def collect_ordered_stylesheets(records, fetcher: BoundedFetcher, *, base_url=""):
    diagnostics = []

    def diagnose(item):
        if len(diagnostics) < 256:
            diagnostics.append(item)
        else:
            diagnostics[-1] = _diag("Additional CSS diagnostics truncated; coverage is partial.")

    hrefs = list(
        dict.fromkeys(r["href"] for r in records if r.get("href") and r.get("text") is None)
    )
    cache = {}
    if hrefs:
        for result in await fetcher.fetch_many([FetchRequest(url=u, kind="css") for u in hrefs]):
            for diagnostic in result.diagnostics:
                diagnose(diagnostic)
            if result.ok and result.body is not None:
                cache[result.url] = (
                    result.final_url or result.url,
                    result.body.decode("utf-8", errors="replace"),
                )
    roots = []
    for index, record in enumerate(records):
        url = record.get("href") or f"inline:{index}"
        if record.get("text") is not None:
            text = record["text"]
            origin = record.get("href") or base_url
        elif url in cache:
            origin, text = cache[url]
            url = origin
        else:
            continue
        roots.append((index, url, origin, text, record))
    # Fetch in concurrent breadth waves; assembly below follows source order.
    frontier = [
        (origin, text, (index,)) for index, _, origin, text, r in roots if not r.get("disabled")
    ]
    attempted = set(cache) | set(hrefs)
    traversed = {
        origin
        for _, url, origin, _, record in roots
        if not url.startswith("inline:") and not record.get("disabled")
    }
    requested = 0
    for depth in range(MAX_IMPORT_DEPTH):
        targets = list(
            dict.fromkeys(
                url for base, text, path in frontier for _, url, _ in _imports(text, base, path)
            )
        )
        urls = []
        for url in targets:
            if url in attempted:
                continue
            attempted.add(url)
            if urlsplit(url).scheme not in ("http", "https"):
                diagnose(_diag(f"CSS import has no supported source URL: {url}"))
            elif requested >= MAX_IMPORT_REQUESTS:
                diagnose(_diag("CSS import request budget reached; coverage is partial."))
            else:
                urls.append(url)
                requested += 1
        if urls:
            for result in await fetcher.fetch_many([FetchRequest(url=u, kind="css") for u in urls]):
                for diagnostic in result.diagnostics:
                    diagnose(diagnostic)
                if result.ok and result.body is not None:
                    cache[result.url] = (
                        result.final_url or result.url,
                        result.body.decode("utf-8", errors="replace"),
                    )
        frontier = []
        for url in targets:
            if url not in cache:
                continue
            origin, text = cache[url]
            if origin in traversed:
                continue
            traversed.add(origin)
            frontier.append((origin, text, (depth + 1, url)))
        if not frontier:
            break
    output = []
    total = 0
    capped = False

    def emit(url, text, path, raw, wrappers, media, disabled, parent):
        nonlocal total, capped
        effective = "" if disabled else _wrap(text, wrappers)
        size = len(effective.encode())
        if len(output) >= MAX_CSS_CHUNKS or total + size > MAX_EFFECTIVE_CSS_BYTES:
            if not capped:
                diagnose(_diag("CSS expansion byte/chunk budget reached; coverage is partial."))
                capped = True
            return
        total += size
        output.append(
            Stylesheet(
                url=url,
                text=effective,
                raw_text=raw,
                source_order=list(path),
                media=media or None,
                disabled=disabled,
                imported_from=parent,
            )
        )

    def expand(url, base, text, path, wrappers, media, disabled, parent, ancestors, depth):
        if capped:
            return
        if disabled:
            emit(url, "", path, text, [], media, True, parent)
            return
        rules = _rules(text)
        imports = {i: (u, w) for i, u, w in _imports(text, base, path)}
        pending = []
        part = 0
        raw = text
        emitted = False
        for index, rule in enumerate(rules):
            if rule.type == "error":
                diagnose(_diag(f"Invalid CSS rule skipped in {url}: {rule.message}"))
                continue
            if getattr(rule, "lower_at_keyword", "") != "import":
                pending.append(rule)
                continue
            chunk = tinycss2.serialize(pending)
            if chunk.strip():
                emit(url, chunk, (*path, part), raw, wrappers, media, False, parent)
                raw = None
                emitted = True
                part += 1
            pending = []
            if index not in imports:
                diagnose(
                    _diag(
                        f"Ignored late or unsupported CSS import in {url}; "
                        "no unconditional fallback."
                    )
                )
                continue
            target, conditions = imports[index]
            if target in ancestors or target == base:
                diagnose(_diag(f"Cyclic CSS import omitted: {target}"))
                continue
            if depth >= MAX_IMPORT_DEPTH or target not in cache:
                diagnose(_diag(f"CSS import not captured within bounds: {target}"))
                continue
            child_url, child_text = cache[target]
            if child_url in ancestors or child_url == base:
                diagnose(_diag(f"Cyclic CSS import redirect omitted: {target}"))
                continue
            expand(
                child_url,
                child_url,
                child_text,
                (*path, part),
                [*wrappers, *conditions],
                media,
                False,
                url,
                (*ancestors, base),
                depth + 1,
            )
            part += 1
        chunk = tinycss2.serialize(pending)
        if chunk.strip() or not emitted:
            emit(url, chunk, (*path, part) if part else path, raw, wrappers, media, False, parent)

    for index, url, origin, text, record in roots:
        media = str(record.get("media") or "").strip()
        wrappers = ["@media " + media] if media and media != "all" else []
        expand(
            url, origin, text, (index,), wrappers, media, bool(record.get("disabled")), None, (), 0
        )
    return output, diagnostics
