"""Serve only a frozen snapshot's public viewer; never its research records or receipts."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if self.path.startswith("/originals/"):
            self.send_header("Content-Disposition", "attachment")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["v2"], default="v2")
    parser.add_argument("--port", type=int, default=3056)
    args = parser.parse_args()
    public = Path(__file__).resolve().parents[1] / args.version / "public"
    print(f"Frozen {args.version} preview: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(public))).serve_forever()
