import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_ASSETS_DIR", BASE_DIR / "assets")).resolve()
TEMPLATE_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_TEMPLATE_DIR", BASE_DIR / "backend" / "templates")).resolve()
DATA_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_DATA_DIR", ".")).resolve()
CONTROL_DB_PATH = Path(
    os.environ.get("SITE_DATABASE_PATH")
    or DATA_DIR / "control.sqlite3"
).resolve()
REPOS_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_REPOS_DIR", DATA_DIR / "client")).resolve()
SYNC_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_SYNC_DIR", DATA_DIR / "sync")).resolve()
SSH_DIR = Path(os.environ.get("PROMOCASTER_CONTROL_SSH_DIR", DATA_DIR / "ssh")).resolve()
CLIENT_GITHUB_KEY = Path(os.environ.get("PROMOCASTER_CONTROL_CLIENT_GITHUB_KEY", SSH_DIR / "client_github_key")).resolve()
CONTROL_GIT_CONFIG = Path(os.environ.get("PROMOCASTER_CONTROL_GIT_CONFIG", DATA_DIR / "gitconfig")).resolve()
MAX_JSON_BODY_BYTES = int(os.environ.get("PROMOCASTER_CONTROL_MAX_JSON_BODY_BYTES", str(2 * 1024 * 1024)))
MAX_MULTIPART_BODY_BYTES = int(os.environ.get("PROMOCASTER_CONTROL_MAX_MULTIPART_BODY_BYTES", str(512 * 1024 * 1024)))
ALLOWED_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4"}
IMAGE_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png"}
IMAGE_MAX_GEOMETRY = os.environ.get("PROMOCASTER_CONTROL_IMAGE_MAX_GEOMETRY", "1920x1080")
IMAGE_QUALITY = os.environ.get("PROMOCASTER_CONTROL_IMAGE_QUALITY", "85")
IMAGE_WARN_MIN_WIDTH = int(os.environ.get("PROMOCASTER_CONTROL_IMAGE_WARN_MIN_WIDTH", "1920"))
IMAGE_WARN_MIN_HEIGHT = int(os.environ.get("PROMOCASTER_CONTROL_IMAGE_WARN_MIN_HEIGHT", "1080"))
VIDEO_MEDIA_EXTENSIONS = {".mp4"}
VIDEO_WARN_WIDTH = int(os.environ.get("PROMOCASTER_CONTROL_VIDEO_WARN_WIDTH", "1920"))
VIDEO_WARN_HEIGHT = int(os.environ.get("PROMOCASTER_CONTROL_VIDEO_WARN_HEIGHT", "1080"))
VIDEO_WARN_DURATION_SECONDS = float(os.environ.get("PROMOCASTER_CONTROL_VIDEO_WARN_DURATION_SECONDS", "120"))
VIDEO_WARN_SIZE_BYTES = int(os.environ.get("PROMOCASTER_CONTROL_VIDEO_WARN_SIZE_MB", "250")) * 1024 * 1024
VIDEO_PREFERRED_CODEC = os.environ.get("PROMOCASTER_CONTROL_VIDEO_PREFERRED_CODEC", "h264")
SUBPROCESS_CWD = Path("/")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_control_db() -> sqlite3.Connection:
    CONTROL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CONTROL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_clients_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            repo TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT 'master',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def init_clients_db() -> None:
    with connect_control_db() as conn:
        ensure_clients_table(conn)


def load_clients():
    try:
        with connect_control_db() as conn:
            ensure_clients_table(conn)
            rows = conn.execute(
                "SELECT id, name, repo, branch FROM clients WHERE active = 1 ORDER BY lower(name), id"
            ).fetchall()
            return {
                row["id"]: {"name": row["name"], "repo": row["repo"], "branch": row["branch"]}
                for row in rows
            }
    except sqlite3.Error:
        return {}


def validate_client_config(client_id: str, name: str, repo: str, branch: str) -> str:
    client_id = client_id.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", client_id):
        return "Client slug must start with a lowercase letter or number and contain only lowercase letters, numbers, hyphens, or underscores."
    if not name.strip():
        return "Client name is required."
    if not repo.strip():
        return "Git repository is required."
    if not branch.strip():
        return "Branch is required."
    return ""


def upsert_client(client_id: str, name: str, repo: str, branch: str, *, create: bool) -> str:
    error = validate_client_config(client_id, name, repo, branch)
    if error:
        return error

    clients = load_clients()
    if create and client_id in clients:
        return "Client slug already exists."
    if not create and client_id not in clients:
        return "Client does not exist."

    now = utc_iso()
    with connect_control_db() as conn:
        ensure_clients_table(conn)
        if create:
            conn.execute(
                """
                INSERT INTO clients (id, name, repo, branch, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (client_id.strip(), name.strip(), repo.strip(), branch.strip(), now, now),
            )
        else:
            conn.execute(
                """
                UPDATE clients
                SET name = ?, repo = ?, branch = ?, updated_at = ?
                WHERE id = ?
                """,
                (name.strip(), repo.strip(), branch.strip(), now, client_id.strip()),
            )
    return ""


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


def client_branch(client):
    return load_clients().get(client, {}).get("branch", "master") or "master"


def client_info(client):
    config = load_clients().get(client, {})
    return {"id": client, "name": config.get("name") or client}


def clean_yaml_scalar(value):
    value = value.split(" #", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value


def media_type_for_name(name):
    return "video" if name.lower().endswith(".mp4") else "image"


def is_safe_media_name(name):
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        return False
    if Path(name).name != name:
        return False
    return Path(name).suffix.lower() in ALLOWED_MEDIA_EXTENSIONS


def imagemagick_command():
    command = shutil.which("magick") or shutil.which("convert")
    if not command:
        raise RuntimeError("ImageMagick is required to process image uploads")
    return command


def image_identify_command(command):
    if Path(command).name == "magick":
        return [command, "identify"]
    identify = shutil.which("identify")
    if identify:
        return [identify]
    raise RuntimeError("ImageMagick identify is required to inspect image uploads")


def image_size(command, image_path):
    proc = subprocess.run(
        [*image_identify_command(command), "-format", "%w %h", str(image_path)],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(SUBPROCESS_CWD),
    )
    width, height = proc.stdout.strip().split()
    return int(width), int(height)


def ffprobe_command():
    command = shutil.which("ffprobe")
    if not command:
        raise RuntimeError("ffprobe is required to inspect video uploads")
    return command


def video_metadata(video_path):
    proc = subprocess.run(
        [
            ffprobe_command(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(SUBPROCESS_CWD),
    )
    data = json.loads(proc.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("MP4 upload does not contain a video stream")
    stream = streams[0]
    format_data = data.get("format") or {}
    duration = float(stream.get("duration") or format_data.get("duration") or 0)
    size = int(format_data.get("size") or video_path.stat().st_size)
    return {
        "codec": stream.get("codec_name") or "",
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": duration,
        "size": size,
    }


def video_warnings(filename, metadata):
    warnings = []
    width = metadata["width"]
    height = metadata["height"]
    if width < VIDEO_WARN_WIDTH or height < VIDEO_WARN_HEIGHT:
        warnings.append(
            {
                "filename": filename,
                "message": f"{filename} is {width}x{height}, below 1080p target {VIDEO_WARN_WIDTH}x{VIDEO_WARN_HEIGHT}",
                "width": width,
                "height": height,
                "targetWidth": VIDEO_WARN_WIDTH,
                "targetHeight": VIDEO_WARN_HEIGHT,
            }
        )
    if width > VIDEO_WARN_WIDTH or height > VIDEO_WARN_HEIGHT:
        warnings.append(
            {
                "filename": filename,
                "message": f"{filename} is {width}x{height}, above 1080p target {VIDEO_WARN_WIDTH}x{VIDEO_WARN_HEIGHT}; consider exporting 1080p for smoother playback",
                "width": width,
                "height": height,
                "targetWidth": VIDEO_WARN_WIDTH,
                "targetHeight": VIDEO_WARN_HEIGHT,
            }
        )
    if metadata["codec"] and metadata["codec"] != VIDEO_PREFERRED_CODEC:
        warnings.append(
            {
                "filename": filename,
                "message": f"{filename} uses {metadata['codec']} video; {VIDEO_PREFERRED_CODEC} MP4 is the preferred device profile",
                "codec": metadata["codec"],
                "targetCodec": VIDEO_PREFERRED_CODEC,
            }
        )
    if metadata["duration"] > VIDEO_WARN_DURATION_SECONDS:
        warnings.append(
            {
                "filename": filename,
                "message": f"{filename} is {metadata['duration']:.0f}s long; shorter loops are easier on devices",
                "durationSeconds": metadata["duration"],
                "targetDurationSeconds": VIDEO_WARN_DURATION_SECONDS,
            }
        )
    if metadata["size"] > VIDEO_WARN_SIZE_BYTES:
        warnings.append(
            {
                "filename": filename,
                "message": f"{filename} is {metadata['size'] // (1024 * 1024)} MB; large videos can slow sync and playback",
                "sizeBytes": metadata["size"],
                "targetSizeBytes": VIDEO_WARN_SIZE_BYTES,
            }
        )
    return warnings


def write_upload_media(upload, media_path):
    extension = Path(upload["filename"]).suffix.lower()
    if extension in VIDEO_MEDIA_EXTENSIONS:
        media_path.write_bytes(upload["content"])
        try:
            return video_warnings(upload["filename"], video_metadata(media_path))
        except (subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError, OSError) as exc:
            media_path.unlink(missing_ok=True)
            raise RuntimeError(f"ffprobe could not inspect {upload['filename']}: {exc}")

    if extension not in IMAGE_MEDIA_EXTENSIONS:
        media_path.write_bytes(upload["content"])
        return []

    command = imagemagick_command()
    media_path.parent.mkdir(parents=True, exist_ok=True)
    input_path = None
    output_path = None
    warnings = []
    try:
        with tempfile.NamedTemporaryFile(dir=media_path.parent, suffix=extension, delete=False) as input_file:
            input_file.write(upload["content"])
            input_path = Path(input_file.name)
        with tempfile.NamedTemporaryFile(dir=media_path.parent, suffix=extension, delete=False) as output_file:
            output_path = Path(output_file.name)
        output_path.unlink(missing_ok=True)

        width, height = image_size(command, input_path)
        if width < IMAGE_WARN_MIN_WIDTH or height < IMAGE_WARN_MIN_HEIGHT:
            warnings.append(
                {
                    "filename": upload["filename"],
                    "message": f"{upload['filename']} is {width}x{height}, below 1080p target {IMAGE_WARN_MIN_WIDTH}x{IMAGE_WARN_MIN_HEIGHT}",
                    "width": width,
                    "height": height,
                    "targetWidth": IMAGE_WARN_MIN_WIDTH,
                    "targetHeight": IMAGE_WARN_MIN_HEIGHT,
                }
            )

        subprocess.run(
            [
                command,
                str(input_path),
                "-auto-orient",
                "-resize",
                f"{IMAGE_MAX_GEOMETRY}>",
                "-strip",
                "-quality",
                IMAGE_QUALITY,
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(SUBPROCESS_CWD),
        )
        output_path.replace(media_path)
        output_path = None
        return warnings
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ImageMagick could not process {upload['filename']}: {detail or exc.returncode}")
    finally:
        for path in (input_path, output_path):
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def media_version(media_root, name):
    try:
        return str((media_root / name).stat().st_mtime_ns)
    except OSError:
        return ""


def slide_from_entry(client, entry, media_root):
    name = entry.get("name") or entry.get("file") or ""
    slide_type = media_type_for_name(name)
    duration = int(entry.get("time") or entry.get("duration") or entry.get("durationMs") or 10000)
    version = media_version(media_root, name)
    src = f"/api/clients/{quote(client, safe='')}/media/{quote(name, safe='')}"
    if version:
        src = f"{src}?v={version}"
    return {
        "name": name,
        "src": src,
        "type": slide_type,
        "durationMs": None if slide_type == "video" else duration,
        "maxDurationMs": duration if slide_type == "video" and duration else None,
        "startsOn": entry.get("starts") or entry.get("startsOn") or "",
        "expiresOn": entry.get("expires") or entry.get("expiresOn") or "",
    }


def referenced_media_names(deck_data):
    names = set()
    for location in deck_data.get("locations", []):
        for slide in location.get("slides", []):
            name = slide.get("name") or ""
            if name:
                names.add(name)
    return names


def location_names(deck_data):
    return [location.get("name", "") for location in deck_data.get("locations", [])]


def yaml_quote(value):
    value = str(value)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def deck_to_media_yml(deck_data):
    lines = [
        "####",
        "# Promocaster slide deck configuration",
        "# Generated by Promocaster Control",
        "####",
        "",
    ]

    for location in deck_data.get("locations", []):
        name = location.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"invalid location name: {name}")
        lines.append(f"{name}:")
        lines.append("")
        for slide in location.get("slides", []):
            slide_name = slide.get("name", "")
            if not is_safe_media_name(slide_name):
                raise ValueError(f"invalid slide filename: {slide_name}")
            slide_type = slide.get("type") or media_type_for_name(slide_name)
            if slide_type == "video":
                duration = int(slide.get("maxDurationMs") or slide.get("durationMs") or 0)
            else:
                duration = int(slide.get("durationMs") or 10000)
            starts_on = slide.get("startsOn") or slide.get("starts") or ""
            expires_on = slide.get("expiresOn") or slide.get("expires") or ""
            lines.append(f"- name: {yaml_quote(slide_name)}")
            if duration:
                lines.append(f"  time: {max(duration, 1000)}")
            lines.append(f"  starts: {yaml_quote(starts_on)}")
            lines.append(f"  expires: {yaml_quote(expires_on)}")
            lines.append("")
        if not location.get("slides"):
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_media_yml(client, media_yml):
    locations = []
    current = None
    current_slide = None
    key_pattern = re.compile(r"^[A-Za-z0-9_-]+:\s*$")
    media_root = media_yml.parent.parent / "media"

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
                    slide_from_entry(client, slide, media_root)
                    for slide in location["slides"]
                    if slide.get("name") or slide.get("file")
                ],
            }
        )

    return {
        "client": client_info(client),
        "activeLocation": normalized_locations[0]["name"] if normalized_locations else "",
        "locations": normalized_locations,
    }


def git_env():
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(CONTROL_GIT_CONFIG),
        "GIT_SSH_COMMAND": f"ssh -i {CLIENT_GITHUB_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new",
    }


def run_git(repo_path, args, *, check=True, capture=True):
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=False,
        capture_output=capture,
        text=True,
        env=git_env(),
        cwd=str(SUBPROCESS_CWD),
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} exited {proc.returncode}")
    return proc


def git_output(repo_path, *args):
    return run_git(repo_path, list(args)).stdout.strip()


def git_status_short(repo_path):
    return git_output(repo_path, "status", "--short")


def ensure_git_safe_directory(repo_path):
    CONTROL_GIT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONTROL_GIT_CONFIG.touch(mode=0o640, exist_ok=True)
    safe_path = str(repo_path.resolve())
    proc = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        check=False,
        capture_output=True,
        text=True,
        env=git_env(),
        cwd=str(SUBPROCESS_CWD),
    )
    safe_paths = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    if safe_path not in safe_paths:
        proc = subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", safe_path],
            check=False,
            capture_output=True,
            text=True,
            env=git_env(),
            cwd=str(SUBPROCESS_CWD),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or "could not configure git safe.directory")


def ensure_save_preconditions(repo_path, branch):
    ensure_git_safe_directory(repo_path)
    if git_status_short(repo_path):
        raise RuntimeError("repo checkout has local changes; run client-repo status before saving")
    run_git(repo_path, ["fetch", "origin", branch])
    local = git_output(repo_path, "rev-parse", "HEAD")
    remote = git_output(repo_path, "rev-parse", f"origin/{branch}")
    base = git_output(repo_path, "merge-base", "HEAD", f"origin/{branch}")
    if local == remote:
        return
    if local == base:
        raise RuntimeError(f"repo checkout is behind origin/{branch}; run client-repo sync before saving")
    if remote == base:
        raise RuntimeError(f"repo checkout is ahead of origin/{branch}; push or inspect it before saving")
    raise RuntimeError(f"repo checkout has diverged from origin/{branch}; inspect it before saving")
