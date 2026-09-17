import json, os, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
def env(n):
    for line in open(os.path.join(HERE, "..", "..", ".env")):
        if line.startswith(n + "="): return line.strip().split("=", 1)[1]
KEY = env("CLUE_AI_ARK_API_KEY"); BASE = "https://api.ai-ark.com/api/developer-portal"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-TOKEN": KEY, "Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r: return {"http": 200, "body": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e: return {"http": e.code, "body": e.read().decode()[:400]}
def save(n,o): json.dump(o, open(os.path.join(HERE,n),"w"), indent=1); print("--- saved", n)

print("== Churba scoped search (committee member #5) ==")
r = call("POST", "/v1/people", {"contact": {"fullName": {"any": {"include": {"mode": "SMART", "content": ["Aaron Churba"]}}}}, "account": {"domain": {"any": {"include": ["probook.ai"]}}}, "page": 0, "size": 3})
save("churba_scoped.json", r)
if r["http"]==200:
    for p in r["body"].get("content", []):
        pos=(p.get("position_groups") or [{}])[0]
        print("  ", p["profile"].get("full_name"), "|", p["profile"].get("title"), "|", (p.get("link") or {}).get("linkedin"), "| start=", (pos.get("date") or {}).get("start"))
else: print(r)
time.sleep(15)

print("== phone finder: Mark Hoffman ==")
r = call("POST", "/v1/people/mobile-phone-finder", {"url": "https://www.linkedin.com/in/mark-hoffman-582a5741"})
save("phone_mark2.json", r); print(r["http"], str(r["body"])[:250])
time.sleep(15)

print("== personality: Kate ==")
r = call("POST", "/v1/people/analysis", {"url": "https://www.linkedin.com/in/kibrady12"})
save("personality_kate2.json", r)
if r["http"]==200:
    b=r["body"]; s=json.dumps(b)
    print("keys:", list(b.keys())[:12]); print(s[:1200])
else: print(r["http"], r["body"])
time.sleep(10)

for p in ["/v1/credits", "/v1/credit/fetch", "/v1/user/credit"]:
    r = call("GET", p)
    print("credit try", p, "->", r["http"], str(r["body"])[:150])
    if r["http"]==200: save("credit.json", r); break
