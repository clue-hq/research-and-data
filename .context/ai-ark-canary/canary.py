import json, os, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
def env(n):
    for line in open(os.path.join(HERE, "..", "..", ".env")):
        if line.startswith(n + "="): return line.strip().split("=", 1)[1]
KEY = env("CLUE_AI_ARK_API_KEY")
BASE = "https://api.ai-ark.com/api/developer-portal"
def call(method, path, body=None):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-TOKEN": KEY, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "application/json"}, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.loads(r.read().decode())
        return {"http": 200, "elapsed": round(time.time()-t0,1), "body": out}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "elapsed": round(time.time()-t0,1), "body": e.read().decode()[:600]}
def save(name, obj):
    json.dump(obj, open(os.path.join(HERE, name), "w"), indent=1)
    print(f"--- saved {name}")

print("== credit balance before ==")
r = call("GET", "/v1/credit"); print(r["http"], str(r["body"])[:200]); save("credit_before.json", r)

print("\n== CHECK (a)+(e): people search, domain probook.ai ==")
r = call("POST", "/v1/people", {"account": {"domain": {"any": {"include": ["probook.ai"]}}}, "page": 0, "size": 25})
save("search_probook.json", r)
if r["http"] == 200:
    b = r["body"]
    print("totalElements:", b.get("totalElements"))
    for p in b.get("content", [])[:25]:
        pr = p.get("profile", {}); li = (p.get("link") or {}).get("linkedin", "")
        pos = (p.get("position_groups") or [{}])
        start = ((pos[0].get("date") or {}).get("start") if pos else None)
        print(f"  {pr.get('full_name','?')} | {pr.get('title','?')} | {li} | start={start}")
else:
    print(r["http"], r["body"])
time.sleep(0.5)

print("\n== CHECK (d): same-name — fullName 'Mark Hoffman' unscoped count ==")
r = call("POST", "/v1/people", {"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": ["Mark Hoffman"]}}}}, "page": 0, "size": 10})
save("hoffman_unscoped.json", r)
if r["http"] == 200: print("totalElements:", r["body"].get("totalElements"))
else: print(r["http"], r["body"])
time.sleep(0.5)

print("\n== CHECK (d2): 'Mark Hoffman' scoped to probook.ai ==")
r = call("POST", "/v1/people", {"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": ["Mark Hoffman"]}}}, "company": None} if False else {"fullName": {"any": {"include": {"mode": "STRICT", "content": ["Mark Hoffman"]}}}}, "account": {"domain": {"any": {"include": ["probook.ai"]}}}, "page": 0, "size": 5})
save("hoffman_scoped.json", r)
if r["http"] == 200:
    b = r["body"]; print("totalElements:", b.get("totalElements"))
    for p in b.get("content", []):
        print("  ", p.get("profile", {}).get("full_name"), "|", p.get("profile", {}).get("title"), "|", (p.get("link") or {}).get("linkedin"))
else: print(r["http"], r["body"])
time.sleep(0.5)

print("\n== CHECK (c): export single w/ email — Kate by LinkedIn URL ==")
r = call("POST", "/v1/people/export/single", {"url": "https://www.linkedin.com/in/kibrady12"})
save("export_kate.json", r)
if r["http"] == 200:
    b = r["body"]; em = b.get("email") or {}
    print("email block:", json.dumps(em)[:500])
    pos = (b.get("position_groups") or [{}])[0]
    print("current position:", json.dumps({"company": (pos.get("company") or {}).get("name"), "date": pos.get("date")})[:200])
else: print(r["http"], r["body"])
time.sleep(0.5)

print("\n== CHECK (c2): export George (ground truth george@probook.ai) ==")
r = call("POST", "/v1/people/export/single", {"url": "https://www.linkedin.com/in/george-eliadis"})
save("export_george.json", r)
if r["http"] == 200:
    em = (r["body"].get("email") or {})
    print("email block:", json.dumps(em)[:400])
else: print(r["http"], r["body"])
time.sleep(0.5)

print("\n== phone finder: Mark Hoffman by LinkedIn URL (5cr if found) ==")
r = call("POST", "/v1/people/mobile-phone-finder", {"url": "https://www.linkedin.com/in/mark-hoffman-582a5741"})
save("phone_mark.json", r)
print(r["http"], str(r["body"])[:300])
time.sleep(0.5)

print("\n== personality analysis: Kate (4cr) ==")
r = call("POST", "/v1/people/analysis", {"url": "https://www.linkedin.com/in/kibrady12"})
save("personality_kate.json", r)
if r["http"] == 200:
    print(json.dumps(r["body"], indent=1)[:900])
else: print(r["http"], r["body"])

print("\n== credit balance after ==")
r = call("GET", "/v1/credit"); print(r["http"], str(r["body"])[:200]); save("credit_after.json", r)
