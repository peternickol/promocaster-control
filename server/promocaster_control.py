#!/usr/bin/env python3
import json
import os
import posixpath
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


WEB_ROOT = Path(os.environ.get("PROMOCASTER_CONTROL_WEB_ROOT", "web")).resolve()
DATA_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_DATA_DIR", ".")).resolve()
CLIENTS_FILE = Path(os.environ.get("PROMOCASTER_CONTROL_CLIENTS_FILE", "clients.yml")).resolve()
BIND = os.environ.get("PROMOCASTER_CONTROL_BIND", "127.0.0.1")
PORT = int(os.environ.get("PROMOCASTER_CONTROL_PORT", "8080"))


class ControlHandler(SimpleHTTPRequestHandler):
    server_version = "PromocasterControl/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args), flush=True)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self.write_json(
                {
                    "ok": True,
                    "data_dir": str(DATA_DIR),
                    "clients_file": str(CLIENTS_FILE),
                    "clients_file_exists": CLIENTS_FILE.exists(),
                }
            )
            return
        if path == "/":
            self.path = "/editor.html"
        elif path.startswith("/api/"):
            self.send_error(404, "API endpoint is not implemented yet")
            return
        super().do_GET()

    def translate_path(self, path):
        parsed_path = unquote(urlparse(path).path)
        if parsed_path == "/":
            parsed_path = "/editor.html"
        clean_path = posixpath.normpath(parsed_path).lstrip("/")
        target = (WEB_ROOT / clean_path).resolve()
        if WEB_ROOT not in target.parents and target != WEB_ROOT:
            return str(WEB_ROOT / "__forbidden__")
        return str(target)

    def write_json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    if not WEB_ROOT.exists():
        raise SystemExit(f"web root does not exist: {WEB_ROOT}")
    server = ThreadingHTTPServer((BIND, PORT), ControlHandler)
    print(f"Promocaster Control listening on http://{BIND}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Promocaster Control stopping", flush=True)


if __name__ == "__main__":
    main()
