import http.server, threading, json
from datetime import UTC, datetime
from pydantic import SecretStr
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpxTransport, HttpResponse, HttpRequest
from clue_api.footprint import short_links
from clue_api.footprint.social import linkedin_activity

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(301); self.send_header("Location", self.path + "x"); self.end_headers()
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/a"
try:
    HttpxTransport().send(HttpRequest("GET", url, headers={}, timeout_s=5))
except Exception as e:
    print("HttpxTransport raised:", type(e).__module__, type(e).__name__)

# Now: a transport that answers treg normally and sends the short link through the real httpx
# transport, but with the short link's URL rewritten to the looping local server (stands in for
# lnkd.in issuing an HTTP redirect into a redirect loop).
class Mixed:
    def __init__(self): self.n = 0
    def send(self, req):
        if "treg.to" in req.url:
            body = {"posts": [{"id": "urn:li:activity:1", "content": "see https://lnkd.in/gLoop",
                               "date": "2026-10-01T10:00:00Z", "author": {"name": "Ada"}}], "hasMore": False}
            return HttpResponse(200, {"X-Treg-Cost-Micro": "1500"}, json.dumps(body).encode())
        return HttpxTransport().send(HttpRequest("GET", url, headers={}, timeout_s=5))
c = ProviderCaller(transport=Mixed(), raw_sink=MemoryRawSink(), ledger=MemoryLedger(),
                   now=lambda: datetime.now(UTC), sleep=lambda _: None)
try:
    h = linkedin_activity(c, SecretStr("t"), "ada", "posts")
    print("state", h.state)
except Exception as e:
    print("linkedin_activity CRASHED after paying for its pages:", type(e).__name__)
