import asyncio, json
from types import SimpleNamespace
from clue_api.arv2 import footprint_operations as ops
from clue_api.arv2.quality_provider_tools import receipt_preview
from clue_api.footprint.social_types import SocialHistory

async def cp(provider, fn):
    return [], ["youtube_data HTTP 503"]
rt = SimpleNamespace(call_provider=cp, clients=SimpleNamespace())
v = asyncio.run(ops._find_videos(rt, ops.FindVideosArgs(queries=['"Ada"'])))
print("find_videos outage:", v["state"], receipt_preview(v)[1:], [h["snippet"][:60] for h in receipt_preview(v)[0]])
print("saved key order:", list(json.loads(json.dumps(v, sort_keys=True)).keys()))
# not_found social history through _history
h = SocialHistory.of([], pages=1, cost_usd=0, state="not_found")
v = ops._history(h)
refused = v["state"] in {"unavailable","empty","ambiguous","not_found","refused","failed"}
print("x not_found -> refused", refused, "code", str(v.get("code") or v.get("gap") or "provider_refusal"))
h = SocialHistory.of([], pages=1, cost_usd=0, state="private")
v = ops._history(h); print("private -> preview", receipt_preview(v)[1:])
