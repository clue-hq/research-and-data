"""Wire helpers for the ARV2 cluehq.ai smoke test — Agent B (python3 stdlib only).

Extends Agent A's clue_lib with AI Ark + OpenRouter. Agent B keeps its OWN ledger/timing
files (cost_ledger_b.json / timing_b.json) so Agent A's artifacts are never overwritten;
the report merges both. Never prints or persists API keys. Every raw response hits raw/
before parsing. Every call is timed and ledgered.
"""

import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(HERE, "raw")
os.makedirs(RAW, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def env_key(name):
    with open(os.path.join(REPO, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


EXA_KEY = env_key("CLUE_EXA_API_KEY")
ARK_KEY = env_key("CLUE_AI_ARK_API_KEY")
OPENROUTER_KEY = env_key("CLUE_OPENROUTER_API_KEY")

ARK_BASE = "https://api.ai-ark.com/api/developer-portal"

LEDGER_PATH = os.path.join(HERE, "cost_ledger_b.json")
TIMING_PATH = os.path.join(HERE, "timing_b.json")

# ---- hard ceilings (brief) -------------------------------------------------
CASH_CEILING = 2.60
CREDIT_CEILING = 50.0

_LAST_ARK_CALL = [0.0]
ARK_MIN_GAP_S = 10.5  # free tier 429s well under the documented 5rps


def _load(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            return default
    return default


def ledger_append(entry):
    rows = _load(LEDGER_PATH, [])
    entry.setdefault("agent", "B")
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    rows.append(entry)
    json.dump(rows, open(LEDGER_PATH, "w"), indent=2)
    return rows


def timing_record(phase, seconds, note=""):
    obj = _load(TIMING_PATH, {})
    obj.setdefault("phases", [])
    obj["phases"].append(
        {
            "phase": phase,
            "seconds": round(seconds, 2),
            "note": note,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    json.dump(obj, open(TIMING_PATH, "w"), indent=2)
    return obj


def save_raw(name, obj):
    path = os.path.join(RAW, name + ".json")
    json.dump(obj, open(path, "w"), indent=2)
    return path


def save_raw_text(name, text):
    path = os.path.join(RAW, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def total_spend():
    rows = _load(LEDGER_PATH, [])
    return round(sum(float(r.get("cost_usd") or 0) for r in rows), 4)


def total_credits():
    rows = _load(LEDGER_PATH, [])
    return round(sum(float(r.get("credits") or 0) for r in rows), 2)


def budget_guard(extra_usd=0.0, extra_credits=0.0):
    """Raise before a call that would break a ceiling. Degradations are recorded, never silent."""
    if total_spend() + extra_usd > CASH_CEILING:
        raise RuntimeError(
            f"CASH CEILING: spent {total_spend()} + {extra_usd} > {CASH_CEILING}"
        )
    if total_credits() + extra_credits > CREDIT_CEILING:
        raise RuntimeError(
            f"CREDIT CEILING: used {total_credits()} + {extra_credits} > {CREDIT_CEILING}"
        )


def _request(url, *, method="GET", headers=None, body=None, timeout=120, retries=4):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (
                    r.status,
                    dict(r.headers),
                    r.read().decode("utf-8", "replace"),
                    round(time.time() - t0, 2),
                )
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            elapsed = round(time.time() - t0, 2)
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = float(e.headers.get("retry-after") or 0) or 12 * (attempt + 1)
                print(f"    retry {e.code} in {wait}s ({text[:140]})", flush=True)
                time.sleep(wait)
                continue
            return (e.code, dict(e.headers), text, elapsed)
        except Exception as e:  # noqa: BLE001
            elapsed = round(time.time() - t0, 2)
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return (0, {}, f"__TRANSPORT_ERROR__ {type(e).__name__}: {e}", elapsed)
    return (0, {}, "__EXHAUSTED__", 0.0)


def live_fetch(url, *, label, timeout=30, retries=1, accept="text/html"):
    """Direct HTTP GET, browser UA. A block is a DATA POINT — recorded, never hidden."""
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": accept + ",application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    status, hdrs, text, elapsed = _request(
        url, method="GET", headers=headers, timeout=timeout, retries=retries
    )
    save_raw_text(f"b_live_{label}.txt", text[:400000])
    ledger_append(
        {
            "provider": "live_http",
            "label": label,
            "op": f"GET {url}",
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": 0.0,
            "bytes": len(text),
            "server": hdrs.get("Server") or hdrs.get("server"),
        }
    )
    print(f"  live[{label}] http={status} {elapsed}s bytes={len(text)}", flush=True)
    return {"status": status, "headers": hdrs, "text": text, "elapsed_s": elapsed, "url": url}


def exa(payload, *, label, timeout=900, retries=4, est_usd=0.03):
    budget_guard(extra_usd=est_usd)
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/search",
        method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body=payload,
        timeout=timeout,
        retries=retries,
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = payload
    save_raw(label, out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append(
        {
            "provider": "exa",
            "label": label,
            "op": payload.get("type", "search"),
            "query": (payload.get("query") or "")[:300],
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": cost,
            "cost_breakdown": out.get("costDollars"),
            "n_results": len(out.get("results") or []),
        }
    )
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost}", flush=True)
    return out


def exa_contents(urls, *, label, text_chars=8000, timeout=240, livecrawl=None):
    budget_guard(extra_usd=0.002 * len(urls))
    body = {"urls": urls, "text": {"maxCharacters": text_chars}}
    if livecrawl:
        body["livecrawl"] = livecrawl
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/contents",
        method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body=body,
        timeout=timeout,
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = body
    save_raw(label, out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append(
        {
            "provider": "exa",
            "label": label,
            "op": "contents" + (f"/{livecrawl}" if livecrawl else ""),
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": cost,
            "cost_breakdown": out.get("costDollars"),
            "n_requested": len(urls),
            "n_results": len(out.get("results") or []),
            "statuses": out.get("statuses"),
        }
    )
    print(
        f"  exa[{label}] http={status} {elapsed}s cost={cost} "
        f"got={len(out.get('results') or [])}/{len(urls)}",
        flush=True,
    )
    return out


def ark(path, body, *, label, est_credits=0.0, timeout=120):
    """AI Ark POST. Browser UA (Cloudflare 403s default clients) + >=10s pacing (free-tier 429s)."""
    budget_guard(extra_credits=est_credits)
    gap = time.time() - _LAST_ARK_CALL[0]
    if _LAST_ARK_CALL[0] and gap < ARK_MIN_GAP_S:
        wait = round(ARK_MIN_GAP_S - gap, 1)
        print(f"    [ark pacing] sleeping {wait}s", flush=True)
        time.sleep(wait)
    status, hdrs, text, elapsed = _request(
        ARK_BASE + path,
        method="POST",
        headers={
            "X-TOKEN": ARK_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": BROWSER_UA,
        },
        body=body,
        timeout=timeout,
        retries=3,
    )
    _LAST_ARK_CALL[0] = time.time()
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out = out if isinstance(out, dict) else {"_list": out}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = body
    save_raw(label, out)
    return out, status, elapsed


def ark_ledger(label, op, status, elapsed, credits, note=""):
    ledger_append(
        {
            "provider": "ai_ark",
            "label": label,
            "op": op,
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": 0.0,
            "credits": credits,
            "note": note,
        }
    )
    print(f"  ark[{label}] http={status} {elapsed}s credits={credits} {note}", flush=True)


def openrouter(
    model, messages, *, label, response_format=None, timeout=900, max_tokens=None, reasoning=None
):
    budget_guard(extra_usd=0.10)
    body = {"model": model, "messages": messages, "usage": {"include": True}}
    if response_format:
        body["response_format"] = response_format
    if max_tokens:
        body["max_tokens"] = max_tokens
    if reasoning is not None:
        body["reasoning"] = reasoning
    status, hdrs, text, elapsed = _request(
        "https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        headers={
            "Authorization": "Bearer " + OPENROUTER_KEY,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cluehq.ai/arv2-smoke",
            "X-Title": "Clue ARV2 smoke (agent B)",
        },
        body=body,
        timeout=timeout,
        retries=3,
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request_shape"] = {
        "model": model,
        "n_messages": len(messages),
        "prompt_chars": sum(len(m.get("content") or "") for m in messages),
        "response_format": response_format,
        "reasoning": reasoning,
    }
    save_raw(label, out)
    usage = out.get("usage") or {}
    # v2 wire finding: BYOK reports usage.cost = 0; the REAL figure is
    # usage.cost_details.upstream_inference_cost.
    real = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    ledger_append(
        {
            "provider": "openrouter",
            "label": label,
            "op": model,
            "http": status,
            "elapsed_s": elapsed,
            "usage": usage,
            "cost_usd": real if real is not None else usage.get("cost"),
        }
    )
    print(f"  openrouter[{label}] http={status} {elapsed}s usage={json.dumps(usage)[:220]}",
          flush=True)
    return out


def exa_output_text(resp):
    """Exa output.content is a markdown STRING with no outputSchema, a dict with one."""
    out = resp.get("output")
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        content = out.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, (dict, list)):
            return json.dumps(content, indent=2)
        return json.dumps(out, indent=2)
    return ""


def deep_report_text(resp):
    """Unwrap the single-string {report:...} outputSchema; tolerate {"value": ...}."""
    text = exa_output_text(resp)
    s = text.strip()
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            r = obj.get("report")
            if isinstance(r, dict):
                return r.get("value") or text
            if isinstance(r, str):
                return r
        except Exception:
            pass
    return text
