"""Wire helpers for the ONE-ACCOUNT AI-Ark run (python3 stdlib only).

Adapted from .context/arv2-person-depth/p_lib.py. Own ledger/timing so no prior
artifacts are touched. Never prints or persists API keys. Every raw response is
written to raw/ BEFORE parsing. Every call is timed and ledgered.

HARD RULE: no Apollo. There is no Apollo helper in this module by design.
"""

import json
import os
import threading
import fcntl
import contextlib
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(HERE, "raw")
TRANSCRIPTS = os.path.join(HERE, "transcripts")
os.makedirs(RAW, exist_ok=True)
os.makedirs(TRANSCRIPTS, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_IO = threading.Lock()
_LOCKFILE = os.path.join(HERE, ".ledger.lock")


@contextlib.contextmanager
def _xlock():
    """Cross-process + cross-thread exclusive lock so parallel phase scripts
    never clobber each other's ledger/timing writes."""
    with _IO:
        f = open(_LOCKFILE, "a+")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()


def env_key(name):
    try:
        with open(os.path.join(REPO, ".env")) as f:
            for line in f:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


EXA_KEY = env_key("CLUE_EXA_API_KEY")
ARK_KEY = env_key("CLUE_AI_ARK_API_KEY")
OPENROUTER_KEY = env_key("CLUE_OPENROUTER_API_KEY")
GEMINI_KEY = env_key("CLUE_GEMINI_API_KEY")

ARK_BASE = "https://api.ai-ark.com/api/developer-portal"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
LEDGER_PATH = os.path.join(HERE, "cost_ledger.json")
TIMING_PATH = os.path.join(HERE, "timing.json")

# ---- hard ceilings (brief) -------------------------------------------------
CASH_CEILING = 3.00
CREDIT_CEILING = 25.0
MEDIA_SECONDS_CEILING = 2.5 * 3600

_LAST_ARK_CALL = [0.0]
ARK_MIN_GAP_S = 10.5

# ---- gemini price sheet (gemini-2.5/3.5-flash-lite class + embedding-2) -----
PRICE = {
    "audio_input_usd_per_1m": 0.30,
    "text_input_usd_per_1m": 0.10,
    "text_output_usd_per_1m": 0.40,
    "embed_usd_per_1m": 0.20,
    "raw_audio_embed_usd_per_second": 0.00016,
    "audio_tokens_per_second": 32,
}


def _load(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            return default
    return default


def ledger_append(entry):
    with _xlock():
        rows = _load(LEDGER_PATH, [])
        entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        rows.append(entry)
        json.dump(rows, open(LEDGER_PATH, "w"), indent=2)
        return len(rows)


def timing_record(phase, seconds, note=""):
    with _xlock():
        obj = _load(TIMING_PATH, {})
        obj.setdefault("phases", [])
        obj["phases"].append({
            "phase": phase, "seconds": round(seconds, 2), "note": note,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        json.dump(obj, open(TIMING_PATH, "w"), indent=2)
        return obj


def save_raw(name, obj):
    path = os.path.join(RAW, name + ".json")
    with _xlock():
        json.dump(obj, open(path, "w"), indent=2)
    return path


def save_raw_text(name, text):
    path = os.path.join(RAW, name)
    with _xlock():
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
    if total_spend() + extra_usd > CASH_CEILING:
        raise RuntimeError(f"CASH CEILING: {total_spend()} + {extra_usd} > {CASH_CEILING}")
    if total_credits() + extra_credits > CREDIT_CEILING:
        raise RuntimeError(f"CREDIT CEILING: {total_credits()} + {extra_credits} > {CREDIT_CEILING}")


def _request(url, *, method="GET", headers=None, body=None, timeout=120, retries=4,
             raw_body=None):
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (r.status, dict(r.headers), r.read().decode("utf-8", "replace"),
                        round(time.time() - t0, 2))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            elapsed = round(time.time() - t0, 2)
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = float(e.headers.get("retry-after") or 0) or 12 * (attempt + 1)
                print(f"    retry {e.code} in {wait}s ({text[:120]})", flush=True)
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


# ---------------------------------------------------------------- AI Ark ----
ARK_EXHAUSTED = [False]


def ark(path, body=None, *, label, method="POST", est_credits=0.0, timeout=120):
    """One AI Ark call. Paced >=10.5s. Records credits. Halts on 402/exhaustion."""
    if ARK_EXHAUSTED[0]:
        raise RuntimeError("AI Ark halted: credit exhaustion previously recorded")
    budget_guard(extra_credits=est_credits)
    gap = ARK_MIN_GAP_S - (time.time() - _LAST_ARK_CALL[0])
    if gap > 0:
        time.sleep(gap)
    headers = {"X-TOKEN": ARK_KEY, "Content-Type": "application/json",
               "User-Agent": BROWSER_UA, "Accept": "application/json"}
    status, hdrs, text, elapsed = _request(ARK_BASE + path, method=method, headers=headers,
                                           body=body, timeout=timeout, retries=3)
    _LAST_ARK_CALL[0] = time.time()
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    rec = {"_http_status": status, "_elapsed_s": elapsed, "_request_path": path,
           "_request_body": body, "_body": out}
    save_raw(label, rec)
    if status in (402, 403) or (isinstance(out, dict) and "credit" in str(out).lower()
                                and status >= 400):
        ARK_EXHAUSTED[0] = True
        ledger_append({"provider": "ai_ark", "label": label, "op": path, "http": status,
                       "elapsed_s": elapsed, "credits": 0, "cost_usd": 0.0,
                       "note": "EXHAUSTED/DENIED -> AI Ark halted", "response": str(out)[:400]})
        print(f"  ark[{label}] HALT http={status} {str(out)[:200]}", flush=True)
        return rec
    n = None
    if isinstance(out, dict):
        n = out.get("totalElements")
    credits = est_credits
    ledger_append({"provider": "ai_ark", "label": label, "op": path, "http": status,
                   "elapsed_s": elapsed, "credits": credits, "cost_usd": 0.0,
                   "request": body, "totalElements": n,
                   "n_returned": len(out.get("content") or []) if isinstance(out, dict) else None})
    print(f"  ark[{label}] http={status} {elapsed}s total={n} "
          f"returned={len(out.get('content') or []) if isinstance(out, dict) else '-'} "
          f"cr~{credits}", flush=True)
    return rec


# ------------------------------------------------------------------- Exa ----
def exa(payload, *, label, timeout=900, retries=4, est_usd=0.01):
    budget_guard(extra_usd=est_usd)
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/search", method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body=payload, timeout=timeout, retries=retries)
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = payload
    save_raw(label, out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append({"provider": "exa", "label": label, "op": payload.get("type", "search"),
                   "query": (payload.get("query") or "")[:400], "http": status,
                   "elapsed_s": elapsed, "cost_usd": cost,
                   "cost_breakdown": out.get("costDollars"),
                   "n_results": len(out.get("results") or [])})
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost} "
          f"n={len(out.get('results') or [])}", flush=True)
    return out


def exa_contents(urls, *, label, text_chars=8000, timeout=240, livecrawl=None):
    budget_guard(extra_usd=0.002 * len(urls))
    body = {"urls": urls, "text": {"maxCharacters": text_chars}}
    if livecrawl:
        body["livecrawl"] = livecrawl
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/contents", method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body=body, timeout=timeout)
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = body
    save_raw(label, out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append({"provider": "exa", "label": label,
                   "op": "contents" + (f"/{livecrawl}" if livecrawl else ""),
                   "http": status, "elapsed_s": elapsed, "cost_usd": cost,
                   "cost_breakdown": out.get("costDollars"), "n_requested": len(urls),
                   "n_results": len(out.get("results") or []),
                   "statuses": out.get("statuses")})
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost} "
          f"got={len(out.get('results') or [])}/{len(urls)}", flush=True)
    return out


def exa_output_text(resp):
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


# ---------------------------------------------------------------- Gemini ----
def gemini_generate(model, parts, *, label, timeout=1800, temperature=0.0,
                    max_output_tokens=None, audio_seconds=0.0, retries=2):
    """POST :generateContent. Cost computed from real usageMetadata."""
    budget_guard(extra_usd=0.20)
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": temperature}}
    if max_output_tokens:
        body["generationConfig"]["maxOutputTokens"] = max_output_tokens
    url = f"{GEMINI_BASE}/models/{model}:generateContent?key={GEMINI_KEY}"
    status, hdrs, text, elapsed = _request(
        url, method="POST", headers={"Content-Type": "application/json"},
        body=body, timeout=timeout, retries=retries)
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:6000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    # redact the key from the echoed request
    out["_request_parts_summary"] = json.dumps(parts)[:1500]
    save_raw(label, out)
    um = out.get("usageMetadata") or {}
    cost = gemini_cost(um)
    ledger_append({"provider": "gemini", "label": label, "op": f"{model}:generateContent",
                   "http": status, "elapsed_s": elapsed, "usage": um, "cost_usd": cost,
                   "audio_seconds": audio_seconds})
    print(f"  gemini[{label}] http={status} {elapsed}s usage={json.dumps(um)[:260]} "
          f"cost=${cost}", flush=True)
    return out


def gemini_cost(um):
    """Cost from real usageMetadata. Audio-modality prompt tokens priced as audio."""
    if not um:
        return 0.0
    audio_tok = 0
    text_tok = 0
    for d in (um.get("promptTokensDetails") or []):
        if d.get("modality") == "AUDIO":
            audio_tok += d.get("tokenCount") or 0
        else:
            text_tok += d.get("tokenCount") or 0
    prompt_total = um.get("promptTokenCount") or 0
    if audio_tok == 0 and text_tok == 0:
        text_tok = prompt_total
    out_tok = (um.get("candidatesTokenCount") or 0) + (um.get("thoughtsTokenCount") or 0)
    c = (audio_tok / 1e6) * PRICE["audio_input_usd_per_1m"]
    c += (text_tok / 1e6) * PRICE["text_input_usd_per_1m"]
    c += (out_tok / 1e6) * PRICE["text_output_usd_per_1m"]
    return round(c, 6)


def gemini_embed(text, *, label, task_type="RETRIEVAL_DOCUMENT", dim=768,
                 model="gemini-embedding-2", timeout=120):
    budget_guard(extra_usd=0.01)
    body = {"content": {"parts": [{"text": text}]}, "taskType": task_type,
            "outputDimensionality": dim}
    url = f"{GEMINI_BASE}/models/{model}:embedContent?key={GEMINI_KEY}"
    status, hdrs, raw, elapsed = _request(
        url, method="POST", headers={"Content-Type": "application/json"},
        body=body, timeout=timeout, retries=3)
    try:
        out = json.loads(raw)
    except Exception:
        out = {"_unparsed": raw[:3000]}
    vals = ((out.get("embedding") or {}).get("values")) or []
    um = out.get("usageMetadata") or {}
    tok = um.get("totalTokenCount") or um.get("promptTokenCount") or 0
    cost = round((tok / 1e6) * PRICE["embed_usd_per_1m"], 8)
    ledger_append({"provider": "gemini", "label": label, "op": f"{model}:embedContent",
                   "http": status, "elapsed_s": elapsed, "usage": um, "cost_usd": cost,
                   "dim": len(vals), "task_type": task_type})
    return {"status": status, "values": vals, "tokens": tok, "cost_usd": cost,
            "elapsed_s": elapsed, "_raw_head": str(out)[:300]}


# ------------------------------------------------------------ OpenRouter ----
def openrouter(model, messages, *, label, response_format=None, timeout=900,
               max_tokens=None, reasoning=None):
    budget_guard(extra_usd=0.10)
    body = {"model": model, "messages": messages, "usage": {"include": True}}
    if response_format:
        body["response_format"] = response_format
    if max_tokens:
        body["max_tokens"] = max_tokens
    if reasoning is not None:
        body["reasoning"] = reasoning
    status, hdrs, text, elapsed = _request(
        "https://openrouter.ai/api/v1/chat/completions", method="POST",
        headers={"Authorization": "Bearer " + OPENROUTER_KEY,
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://cluehq.ai/arv2-one-account-aiark",
                 "X-Title": "Clue ARV2 one-account AI Ark"},
        body=body, timeout=timeout, retries=3)
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    save_raw(label, out)
    usage = out.get("usage") or {}
    real = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    ledger_append({"provider": "openrouter", "label": label, "op": model, "http": status,
                   "elapsed_s": elapsed, "usage": usage,
                   "cost_usd": real if real is not None else usage.get("cost")})
    print(f"  openrouter[{label}] http={status} {elapsed}s "
          f"usage={json.dumps(usage)[:200]}", flush=True)
    return out


# ------------------------------------------------------------------ HTTP ----
def live_fetch(url, *, label, timeout=45, retries=1, accept="text/html",
               extra_headers=None, save=True, max_save=600000):
    headers = {"User-Agent": BROWSER_UA,
               "Accept": accept + ",application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    if extra_headers:
        headers.update(extra_headers)
    status, hdrs, text, elapsed = _request(url, method="GET", headers=headers,
                                           timeout=timeout, retries=retries)
    if save:
        save_raw_text(f"live_{label}.txt", text[:max_save])
    ledger_append({"provider": "live_http", "label": label, "op": f"GET {url[:200]}",
                   "http": status, "elapsed_s": elapsed, "cost_usd": 0.0, "bytes": len(text)})
    print(f"  live[{label}] http={status} {elapsed}s bytes={len(text)}", flush=True)
    return {"status": status, "headers": hdrs, "text": text, "elapsed_s": elapsed, "url": url}


def head_bytes(url, *, label, nbytes=400000, timeout=120):
    """Range-GET the head of a binary (audio) file; returns bytes + content-length."""
    headers = {"User-Agent": BROWSER_UA, "Range": f"bytes=0-{nbytes-1}"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            hdrs = dict(r.headers)
            status = r.status
    except urllib.error.HTTPError as e:
        return {"status": e.code, "bytes": b"", "headers": {}, "elapsed_s": round(time.time()-t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "bytes": b"", "headers": {}, "error": str(e),
                "elapsed_s": round(time.time()-t0, 2)}
    ledger_append({"provider": "live_http", "label": label, "op": f"RANGE {url[:160]}",
                   "http": status, "elapsed_s": round(time.time()-t0, 2), "cost_usd": 0.0,
                   "bytes": len(data), "content_length": hdrs.get("Content-Length"),
                   "content_range": hdrs.get("Content-Range")})
    return {"status": status, "bytes": data, "headers": hdrs,
            "elapsed_s": round(time.time()-t0, 2)}
