import json
from datetime import UTC, datetime
from pydantic import SecretStr
from clue_api.footprint import short_links
from clue_api.footprint.social import (
    company_linkedin_posts, facebook_posts, instagram_posts, linkedin_activity, x_posts,
)
from clue_api.arv2.footprint_operations import _history as preview
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport

short_links.WORKERS = 1
T = SecretStr("t")

def wire(*r):
    tr = ScriptedTransport(list(r))
    return ProviderCaller(transport=tr, raw_sink=MemoryRawSink(), ledger=MemoryLedger(),
                          now=lambda: datetime.now(UTC), sleep=lambda _: None), tr

def body(v, status=200, micro="1000", raw=None):
    return HttpResponse(status, {"content-type": "application/json", "X-Treg-Cost-Micro": micro},
                        raw if raw is not None else json.dumps(v).encode())

def tweet(tid, text, screen="ada", **kw):
    return {"tweet_id": tid, "created_at": "Fri Nov 06 18:16:33 +0000 2026", "text": text,
            "author": {"screen_name": screen, "name": "N"}, **kw}

def li(pid, author="Ada Example", content=None):
    return {"id": f"urn:li:activity:{pid}", "content": content or f"post {pid}", "date": "2026-10-01T10:00:00Z",
            "shareUrl": f"https://www.linkedin.com/posts/x_{pid}", "author": {"name": author, "url": "https://www.linkedin.com/in/x"}}

print("== A1: X page 2 rate-limited (429 x4) -> state?")
c, tr = wire(body({"data": {"timeline": [tweet("1", "a")], "next_cursor": "c2"}}),
             *[body({"detail": "Too Many Requests"}, 429, "0")] * 4)
h = x_posts(c, T, "ada"); print(h.state, h.gap, len(h.posts), "requests", len(tr.requests))

print("== A2: X first page 402 (treg out of credit) -> state?")
c, _ = wire(body({"error": "insufficient balance"}, 402, "0"))
h = x_posts(c, T, "ada"); print(h.state, h.gap)

print("== A3: X first page 200 with TikHub error envelope (data null) -> state?")
c, _ = wire(body({"code": 400, "message": "Request failed, please retry", "data": None}))
h = x_posts(c, T, "ada"); print(h.state, h.gap)

print("== A4: LinkedIn page 2 404 'Pagination token not found' -> state?")
c, _ = wire(body({"posts": [li(1)], "paginationToken": "p2", "hasMore": True}),
            body({"message": "Pagination token not found"}, 404, "0"))
h = linkedin_activity(c, T, "ada", "posts"); print(h.state, h.gap, len(h.posts))

print("== A5: LinkedIn 200 non-JSON body (e.g. HTML/gateway text) -> state?")
c, _ = wire(body(None, raw=b"<html>upstream error</html>"))
h = linkedin_activity(c, T, "ada", "posts"); print(h.state, h.gap, len(h.posts))

print("== A6: LinkedIn 200 error envelope -> state?")
c, _ = wire(body({"success": False, "message": "Upstream timeout"}))
h = linkedin_activity(c, T, "ada", "posts"); print(h.state, h.gap, len(h.posts))

print("== A7: Instagram page 2 404 'cursor not found' -> state?")
item = {"code": "ABC", "id": "1", "taken_at": 1753361074, "caption": {"text": "c"}, "user": {"username": "ada"}}
c, _ = wire(body({"items": [item], "more_available": True, "next_max_id": "m2"}),
            body({"message": "Cursor not found"}, 404, "0"))
h = instagram_posts(c, T, "ada"); print(h.state, h.gap, len(h.posts))

print("== B1: someone else's post in a person's LinkedIn feed -> kind? preview title?")
c, _ = wire(body({"posts": [li(1, author="Meera Mani", content="Meera's own words")], "hasMore": False}))
h = linkedin_activity(c, T, "https://www.linkedin.com/in/dilip", "posts")
p = h.posts[0]; print(p.kind, p.author_name, repr(p.text)); print(preview(h)["results"])

print("== B2: reaction preview title")
c, _ = wire(body({"reactions": [{"createdAt": "2026-10-29T13:29:56Z", "post": li(9, author="Other Person", content="Other person's opinion")}], "hasMore": False}))
h = linkedin_activity(c, T, "ada", "reactions"); print(preview(h)["results"], h.posts[0].published_at)

print("== B3: renamed handle: query old handle, timeline has new screen_name; long quote")
q = tweet("3", "my take", screen="ana_new", quoted=tweet("30", "x" * 270, screen="bob"))
c, tr = wire(body({"data": {"timeline": [q, tweet("4", "my own words", screen="ana_new")], "next_cursor": None}}))
h = x_posts(c, T, "ana_old")
for p in h.posts: print(p.kind, repr(p.text[:20]), p.shared and (len(p.shared.text), p.shared.text_may_be_cut))
print("requests", len(tr.requests))

print("== B4: retweet with no retweeted_tweet: clipped RT text in Post.text, no cut flag")
c, _ = wire(body({"data": {"timeline": [tweet("2", "RT @bob: " + "y" * 120 + "…")], "next_cursor": None}}))
p = x_posts(c, T, "ada").posts[0]; print(p.kind, p.author_name, p.text[:30], "...", p.shared)

print("== C1: partial t.co link in a cut quoted preview is opened and mapped")
cut = "w" * 240 + " https://t.co/Ab"  # preview cut mid-link; full read fails
q = tweet("3", "so true", quoted=tweet("30", cut, screen="bob"))
from tests.footprint._pages import tco_page
c, tr = wire(body({"data": {"timeline": [q], "next_cursor": None}}),
             body({"detail": "gone"}, 404, "0"),
             tco_page("https://unrelated.example/some-other-page"))
p = x_posts(c, T, "ada").posts[0]; print(p.shared.text_may_be_cut, p.shared.links, [r.url for r in tr.requests][-1])

print("== D1: company page: oldest date equals end_date but page had new posts -> stops")
def co(urn, posted): return {"urn": urn, "posted": posted, "text": "t", "url": "u", "poster": {"name": "Acme"}}
c, tr = wire(body({"data": {"data": [co("3", "2026-11-09 10:00:00"), co("2", "2026-10-08 19:00:00")]}}),
             body({"data": {"data": [co("2", "2026-10-08 19:00:00"), co("1b", "2026-10-08 08:00:00")]}}),
             body({"data": {"data": [co("0", "2026-01-01 08:00:00")]}}))
h = company_linkedin_posts(c, T, "acme"); print(h.state, [p.post_id for p in h.posts], "requests", len(tr.requests))

print("== E1: non-dict item in list -> crash?")
for name, fn, b in [
    ("linkedin", lambda c: linkedin_activity(c, T, "ada", "posts"), {"posts": ["oops"], "hasMore": False}),
    ("x", lambda c: x_posts(c, T, "ada"), {"data": {"timeline": [None], "next_cursor": None}}),
    ("li author str", lambda c: linkedin_activity(c, T, "ada", "posts"), {"posts": [{**li(1), "author": "Ada"}], "hasMore": False}),
]:
    c, _ = wire(body(b))
    try: print(name, fn(c).state)
    except Exception as e: print(name, "CRASH", type(e).__name__, e)
