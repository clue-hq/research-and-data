"""Shared wire helpers for the ARV2 Clue-simulated sample run (python3 stdlib only).

Never prints or persists API keys. Every raw response is written to disk before parsing.
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


def env_key(name):
    with open(os.path.join(REPO, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


EXA_KEY = env_key("CLUE_EXA_API_KEY")
APOLLO_KEY = env_key("CLUE_APOLLO_API_KEY")
OPENROUTER_KEY = env_key("CLUE_OPENROUTER_API_KEY")

LEDGER_PATH = os.path.join(HERE, "cost_ledger.json")


def ledger_append(entry):
    rows = []
    if os.path.exists(LEDGER_PATH):
        rows = json.load(open(LEDGER_PATH))
    rows.append(entry)
    json.dump(rows, open(LEDGER_PATH, "w"), indent=2)
    return rows


def save_raw(name, obj):
    path = os.path.join(RAW, name + ".json")
    json.dump(obj, open(path, "w"), indent=2)
    return path


def _request(url, *, method="GET", headers=None, body=None, timeout=120, retries=4):
    """One HTTP call with 429/5xx backoff. Returns (status, headers_dict, text)."""
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
                    round(time.time() - t0, 1),
                )
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            elapsed = round(time.time() - t0, 1)
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = float(e.headers.get("retry-after") or 0) or 3 * (attempt + 1)
                print(f"    retry {e.code} in {wait}s ({text[:120]})", flush=True)
                time.sleep(wait)
                continue
            return (e.code, dict(e.headers), text, elapsed)
        except Exception as e:  # noqa: BLE001 - urllib timeouts / socket errors
            elapsed = round(time.time() - t0, 1)
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            return (0, {}, f"__TRANSPORT_ERROR__ {type(e).__name__}: {e}", elapsed)
    return (0, {}, "__EXHAUSTED__", 0.0)


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
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": cost,
            "cost_breakdown": out.get("costDollars"),
        }
    )
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost}", flush=True)
    return out


def apollo(path, *, label, method="GET", body=None, credits=0, timeout=120):
    url = "https://api.apollo.io/api/v1" + path
    headers = {"x-api-key": APOLLO_KEY, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    status, hdrs, text, elapsed = _request(
        url, method=method, headers=headers, body=body, timeout=timeout
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    rate = {k: v for k, v in hdrs.items() if "rate" in k.lower() or "requests-left" in k.lower()}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_rate_headers"] = rate
    out["_request"] = {"method": method, "path": path, "body": body}
    save_raw(label, out)
    ledger_append(
        {
            "provider": "apollo",
            "label": label,
            "op": f"{method} {path.split('?')[0]}",
            "http": status,
            "elapsed_s": elapsed,
            "credits": credits,
            "rate_headers": rate,
        }
    )
    print(f"  apollo[{label}] http={status} {elapsed}s credits~{credits}", flush=True)
    return out


def openrouter(
    model, messages, *, label, response_format=None, timeout=600, max_tokens=None, reasoning=None
):
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
            "HTTP-Referer": "https://insighthealth.local/clue-sample",
            "X-Title": "Clue ARV2 sample",
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
    # do not persist the full prompt (large); persist a digest of the request shape
    out["_request_shape"] = {
        "model": model,
        "n_messages": len(messages),
        "prompt_chars": sum(len(m.get("content") or "") for m in messages),
        "response_format": response_format,
    }
    save_raw(label, out)
    usage = out.get("usage") or {}
    ledger_append(
        {
            "provider": "openrouter",
            "label": label,
            "op": model,
            "http": status,
            "elapsed_s": elapsed,
            "usage": usage,
            "cost_usd": usage.get("cost"),
        }
    )
    print(
        f"  openrouter[{label}] model={model} http={status} {elapsed}s usage={usage}",
        flush=True,
    )
    return out


def exa_output_text(resp):
    """Exa `output.content` is a markdown STRING when no outputSchema is supplied, a dict when one
    is. Return the report as text either way; '' when absent."""
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


def total_spend():
    if not os.path.exists(LEDGER_PATH):
        return 0.0
    rows = json.load(open(LEDGER_PATH))
    return round(sum(float(r.get("cost_usd") or 0) for r in rows), 4)
