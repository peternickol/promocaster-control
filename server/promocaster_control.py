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
REPOS_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_REPOS_DIR", DATA_DIR / "repos")).resolve()
SYNC_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_SYNC_DIR", DATA_DIR / "sync")).resolve()
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
                    "repos_dir": str(REPOS_DIR),
                    "sync_dir": str(SYNC_DIR),
                    "clients_file": str(CLIENTS_FILE),
                    "clients_file_exists": CLIENTS_FILE.exists(),
                }
            )
            return
        sync_client = self.sync_status_client(path)
        if sync_client:
            self.write_json(self.read_sync_status(sync_client))
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

    def sync_status_client(self, path):
        parts = [part for part in path.split("/") if part]
        if len(parts) == 5 and parts[:2] == ["api", "clients"] and parts[3:] == ["sync", "status"]:
            return parts[2]
        return None

    def read_sync_status(self, client):
        status_path = SYNC_DIR / f"{client}.json"
        repo_path = REPOS_DIR / client
        if status_path.exists():
            try:
                return json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"client": client, "state": "error", "message": f"could not read sync status: {exc}"}
        if repo_path.exists():
            return {"client": client, "state": "ready", "message": "repo checkout is present", "repo_path": str(repo_path)}
        return {
            "client": client,
            "state": "not_started",
            "message": "repo has not been cloned yet; UI should start sync and keep polling this endpoint",
            "repo_path": str(repo_path),
        }


def main():
    if not WEB_ROOT.exists():
        raise SystemExit(f"web root does not exist: {WEB_ROOT}")
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), ControlHandler)
    print(f"Promocaster Control listening on http://{BIND}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Promocaster Control stopping", flush=True)


if __name__ == "__main__":
    main()
