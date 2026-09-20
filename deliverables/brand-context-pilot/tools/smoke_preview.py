"""Brief loopback-only check; uses an OS-selected port and always stops its server."""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("frozen_preview", root / "tools/serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    public = root / "v2/public"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), partial(module.Handler, directory=str(public)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port)
    try:
        for route in ["/", "/data.json", "/manifest.json", "/spend.json", "/.env", "/../sources.json"]:
            try:
                with urllib.request.urlopen(url + route) as response:
                    code = response.status
                    if route == "/data.json":
                        data = json.load(response)
                        assert (len(data["documents"]), len(data["assets"])) == (25, 56)
            except urllib.error.HTTPError as error:
                code = error.code
            assert code == (200 if route in ["/", "/data.json", "/manifest.json"] else 404), (route, code)
            print(route, code)
        asset = json.loads((public / "data.json").read_text())["assets"][0]["path"]
        with urllib.request.urlopen(url + "/" + asset) as response:
            assert response.read() == (public / asset).read_bytes()
        print("Original asset download matches saved bytes.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("Ephemeral V2 preview smoke passed; server stopped.")


if __name__ == "__main__":
    main()
