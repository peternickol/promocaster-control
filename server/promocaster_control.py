#!/usr/bin/env python3
import json
import mimetypes
import os
import posixpath
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


WEB_ROOT = Path(os.environ.get("PROMOCASTER_CONTROL_WEB_ROOT", "web")).resolve()
DATA_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_DATA_DIR", ".")).resolve()
CLIENTS_FILE = Path(os.environ.get("PROMOCASTER_CONTROL_CLIENTS_FILE", "clients.yml")).resolve()
REPOS_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_REPOS_DIR", DATA_DIR / "repos")).resolve()
SYNC_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_SYNC_DIR", DATA_DIR / "sync")).resolve()
BIND = os.environ.get("PROMOCASTER_CONTROL_BIND", "127.0.0.1")
PORT = int(os.environ.get("PROMOCASTER_CONTROL_PORT", "8080"))


def load_clients():
    clients = {}
    if not CLIENTS_FILE.exists():
        return clients

    current = ""
    for raw_line in CLIENTS_FILE.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("  ") and not raw_line.startswith("    ") and raw_line.strip().endswith(":"):
            current = raw_line.strip()[:-1]
            clients[current] = {}
            continue
        if current and raw_line.startswith("    ") and ":" in raw_line:
            key, value = raw_line.strip().split(":", 1)
            clients[current][key] = clean_yaml_scalar(value.strip())
    return clients


def repo_checkout_name(repo_url):
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repo"


def client_repo_name(client):
    repo = load_clients().get(client, {}).get("repo", "")
    if repo:
        return repo_checkout_name(repo)
    return client


def clean_yaml_scalar(value):
    value = value.split(" #", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value


def media_type_for_name(name):
    return "video" if name.lower().endswith(".mp4") else "image"


def slide_from_entry(client, entry):
    name = entry.get("name") or entry.get("file") or ""
    slide_type = media_type_for_name(name)
    duration = int(entry.get("time") or entry.get("duration") or entry.get("durationMs") or 10000)
    return {
        "name": name,
        "src": f"/api/clients/{quote(client, safe='')}/media/{quote(name, safe='')}",
        "type": slide_type,
        "durationMs": None if slide_type == "video" else duration,
        "maxDurationMs": duration if slide_type == "video" and duration else None,
        "startsOn": entry.get("starts") or entry.get("startsOn") or "",
        "expiresOn": entry.get("expires") or entry.get("expiresOn") or "",
    }


def parse_media_yml(client, media_yml):
    locations = []
    current = None
    current_slide = None
    key_pattern = re.compile(r"^[A-Za-z0-9_-]+:\s*$")

    for raw_line in media_yml.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not raw_line.startswith((" ", "\t", "-")) and key_pattern.match(stripped):
            current = {"name": stripped[:-1], "slides": []}
            locations.append(current)
            current_slide = None
            continue

        if not current:
            continue

        if stripped.startswith("- "):
            current_slide = {}
            current["slides"].append(current_slide)
            rest = stripped[2:].strip()
            if ":" in rest:
                key, value = rest.split(":", 1)
                current_slide[key.strip()] = clean_yaml_scalar(value.strip())
            continue

        if current_slide is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_slide[key.strip()] = clean_yaml_scalar(value.strip())

    normalized_locations = []
    for location in locations:
        normalized_locations.append(
            {
                "name": location["name"],
                "slides": [
                    slide_from_entry(client, slide)
                    for slide in location["slides"]
                    if slide.get("name") or slide.get("file")
                ],
            }
        )

    return {"activeLocation": normalized_locations[0]["name"] if normalized_locations else "", "locations": normalized_locations}


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
        decks_client = self.decks_client(path)
        if decks_client:
            self.write_decks(decks_client)
            return
        media_request = self.media_request(path)
        if media_request:
            self.write_media(*media_request)
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

    def do_HEAD(self):
        media_request = self.media_request(urlparse(self.path).path)
        if media_request:
            self.write_media(*media_request, head_only=True)
            return
        super().do_HEAD()

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

    def decks_client(self, path):
        parts = [part for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "clients"] and parts[3] == "decks":
            return parts[2]
        return None

    def media_request(self, path):
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 5 and parts[:2] == ["api", "clients"] and parts[3] == "media":
            return parts[2], unquote("/".join(parts[4:]))
        return None

    def read_sync_status(self, client):
        status_path = SYNC_DIR / f"{client}.json"
        repo_path = REPOS_DIR / client_repo_name(client)
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

    def repo_path(self, client):
        return REPOS_DIR / client_repo_name(client)

    def write_decks(self, client):
        repo_path = self.repo_path(client)
        media_yml = repo_path / "_data" / "media.yml"
        if not repo_path.exists():
            self.write_json(
                {"error": "repo_not_synced", "message": f"run promocaster-control client-repo sync {client}"},
                status=409,
            )
            return
        if not media_yml.exists():
            self.write_json({"error": "missing_media_yml", "message": f"{media_yml} was not found"}, status=404)
            return
        try:
            self.write_json(parse_media_yml(client, media_yml))
        except (OSError, ValueError) as exc:
            self.write_json({"error": "media_yml_parse_failed", "message": str(exc)}, status=500)

    def write_media(self, client, requested_name, head_only=False):
        safe_name = posixpath.normpath("/" + requested_name).lstrip("/")
        if safe_name.startswith("../") or safe_name == "..":
            self.send_error(403)
            return

        media_path = (self.repo_path(client) / "media" / safe_name).resolve()
        media_root = (self.repo_path(client) / "media").resolve()
        if media_root not in media_path.parents and media_path != media_root:
            self.send_error(403)
            return
        if not media_path.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        file_size = media_path.stat().st_size
        start = 0
        end = file_size - 1
        status = 200
        range_header = self.headers.get("Range")

        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
                end = min(end, file_size - 1)
                if start <= end:
                    status = 206

        length = max(end - start + 1, 0)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if head_only:
            return
        with media_path.open("rb") as media_file:
            media_file.seek(start)
            remaining = length
            while remaining > 0:
                chunk = media_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


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
