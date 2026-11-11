import json, sys
sys.path.insert(0, "tests/footprint")
from test_video_search import wire, ok, search, details, KEYS, VID1, VID2, QUOTA
from clue_spend.transport import HttpResponse
from clue_api.footprint.video_search import find_videos

# 1) second search hits a 500 (twice, max_attempts=2) -> first search's paid results dropped
err = HttpResponse(500, {"content-type": "application/json"}, b'{}')
caller, t = wire(search(VID1, VID2), err, err, err)
leads, gaps = find_videos(caller, KEYS, ["a", "b"], exa_fallback=None)
print("500 on 2nd search:", len(leads), gaps)

# 2) YouTube rate limit (403 rateLimitExceeded, not quotaExceeded)
rl = HttpResponse(403, {"content-type": "application/json"}, json.dumps({"error": {"errors": [{"reason": "rateLimitExceeded"}]}}).encode())
caller, t = wire(search(VID1), rl, rl, rl)
leads, gaps = find_videos(caller, KEYS, ["a", "b"], exa_fallback=lambda q: ["https://www.youtube.com/watch?v=" + VID2])
print("rateLimit on 2nd search:", len(leads), gaps)

# 3) quota on 2nd search -> first search re-run on exa (asked again)
asked = []
caller, t = wire(search(VID1), QUOTA, details(VID1))
leads, gaps = find_videos(caller, KEYS, ["a", "b"], exa_fallback=lambda q: asked.append(q) or [])
print("quota on 2nd:", [l.video_id for l in leads], gaps, "exa asked:", asked)

# 4) details fails -> all search results dropped
caller, t = wire(search(VID1, VID2), err, err, err)
leads, gaps = find_videos(caller, KEYS, ["a"], exa_fallback=None)
print("details 500:", len(leads), gaps)
