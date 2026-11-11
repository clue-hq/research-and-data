from pydantic import SecretStr
from clue_api.footprint import social
from clue_api.footprint.treg_client import TregReply

def run(replies, fn, *a):
    it = iter(replies)
    social.treg_call = lambda *args, **kw: next(it)
    social._with_links = lambda caller, h, known=None: h
    social._x_full_quotes = lambda caller, token, h, known, base: h
    return fn(None, SecretStr("t"), *a)

page1 = TregReply(body={"data": {"timeline": [{"tweet_id": 1, "text": "hi", "author": {"screen_name": "dave"}}], "next_cursor": "c2"}}, cost_usd=0.01, call_id=None, status=200)
rate = TregReply(body={"message": "Too Many Requests"}, cost_usd=0.0, call_id=None, status=429)
pay = TregReply(body={"error": "payment_required"}, cost_usd=0.0, call_id=None, status=402)
h = run([pay], social.x_posts, "dave"); print("X page1 402 ->", h.state, h.gap)
h = run([page1, rate], social.x_posts, "dave"); print("X page2 429 ->", h.state, h.gap, len(h.posts))
h = run([pay], social.company_linkedin_posts, "https://www.linkedin.com/company/x/"); print("company page1 402 ->", h.state, h.gap)
h = run([pay], social.linkedin_activity, "https://www.linkedin.com/in/x", "posts"); print("linkedin page1 402 ->", h.state, h.gap)
