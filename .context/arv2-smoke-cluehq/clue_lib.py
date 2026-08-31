"""Wire helpers for the ARV2 cluehq.ai smoke test — Agent A (python3 stdlib only).

Adapted from .context/arv2-clue-sample-v3/clue_lib.py. Never prints or persists API keys.
Every raw response is written to raw/ before parsing. Every call is timed and ledgered.
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

LEDGER_PATH = os.path.join(HERE, "cost_ledger.json")
TIMING_PATH = os.path.join(HERE, "timing.json")


def ledger_append(entry):
    rows = []
    if os.path.exists(LEDGER_PATH):
        rows = json.load(open(LEDGER_PATH))
    entry.setdefault("agent", "A")
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    rows.append(entry)
    json.dump(rows, open(LEDGER_PATH, "w"), indent=2)
    return rows


def timing_record(phase, seconds, note=""):
    obj = {}
    if os.path.exists(TIMING_PATH):
        obj = json.load(open(TIMING_PATH))
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


def _request(url, *, method="GET", headers=None, body=None, timeout=120, retries=4):
    """One HTTP call with 429/5xx backoff. Returns (status, headers_dict, text, elapsed)."""
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
                wait = float(e.headers.get("retry-after") or 0) or 3 * (attempt + 1)
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


def live_fetch(url, *, label, timeout=30, ua=BROWSER_UA, retries=1):
    """Direct HTTP GET with a browser UA. A block is a DATA POINT — recorded, never hidden."""
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    status, hdrs, text, elapsed = _request(
        url, method="GET", headers=headers, timeout=timeout, retries=retries
    )
    save_raw_text(f"live_{label}.html", text)
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


def exa(payload, *, label, timeout=460, retries=4):
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
            "query": payload.get("query"),
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
            "n_results": len(out.get("results") or []),
        }
    )
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost}", flush=True)
    return out


def total_spend():
    if not os.path.exists(LEDGER_PATH):
        return 0.0
    rows = json.load(open(LEDGER_PATH))
    return round(sum(float(r.get("cost_usd") or 0) for r in rows), 4)
