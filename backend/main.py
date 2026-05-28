from __future__ import annotations

import json
import mimetypes
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.control import (
    CLIENTS_FILE,
    DATA_DIR,
    MAX_JSON_BODY_BYTES,
    MAX_MULTIPART_BODY_BYTES,
    REPOS_DIR,
    SYNC_DIR,
    WEB_ROOT,
    client_branch,
    client_repo_name,
    deck_to_media_yml,
    ensure_save_preconditions,
    git_output,
    git_status_short,
    is_safe_media_name,
    location_names,
    parse_media_yml,
    referenced_media_names,
    run_git,
    write_upload_media,
)


app = FastAPI(title="Promocaster Control")


def repo_path(client: str) -> Path:
    return REPOS_DIR / client_repo_name(client)


def api_error(error: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": error, "message": message}, status_code=status_code)


def authenticated_user(request: Request) -> str:
    return (
        request.headers.get("X-Promocaster-User")
        or request.headers.get("Remote-User")
        or request.headers.get("X-Remote-User")
        or "unknown"
    ).strip() or "unknown"


def read_sync_status(client: str) -> dict:
    status_path = SYNC_DIR / f"{client}.json"
    path = repo_path(client)
    if status_path.exists():
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"client": client, "state": "error", "message": f"could not read sync status: {exc}"}
    if path.exists():
        return {"client": client, "state": "ready", "message": "repo checkout is present", "repo_path": str(path)}
    return {
        "client": client,
        "state": "not_started",
        "message": "repo has not been cloned yet; UI should start sync and keep polling this endpoint",
        "repo_path": str(path),
    }


async def read_save_request(
    request: Request,
    deck: str | None,
    uploads: list[UploadFile],
) -> tuple[dict, list[dict]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        length = int(request.headers.get("content-length", "0") or "0")
        if length <= 0:
            raise ValueError("empty request body")
        if length > MAX_MULTIPART_BODY_BYTES:
            raise ValueError("upload is too large")
        if not deck:
            raise ValueError("multipart save is missing deck data")
        payload = json.loads(deck)
        files = []
        for upload in uploads:
            files.append({"field": "media", "filename": Path(upload.filename or "").name, "content": await upload.read()})
        return payload, files

    body = await request.body()
    if not body:
        raise ValueError("empty request body")
    if len(body) > MAX_JSON_BODY_BYTES:
        raise ValueError("request body is too large")
    return json.loads(body.decode("utf-8")), []


def iter_file_range(path: Path, start: int, length: int):
    with path.open("rb") as media_file:
        media_file.seek(start)
        remaining = length
        while remaining > 0:
            chunk = media_file.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@app.on_event("startup")
def ensure_runtime_dirs() -> None:
    if not WEB_ROOT.exists():
        raise RuntimeError(f"web root does not exist: {WEB_ROOT}")
    SYNC_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "repos_dir": str(REPOS_DIR),
        "sync_dir": str(SYNC_DIR),
        "clients_file": str(CLIENTS_FILE),
        "clients_file_exists": CLIENTS_FILE.exists(),
    }


@app.get("/api/clients/{client}/sync/status")
def sync_status(client: str) -> dict:
    return read_sync_status(client)


@app.get("/api/clients/{client}/decks")
def get_decks(client: str):
    path = repo_path(client)
    media_yml = path / "_data" / "media.yml"
    if not path.exists():
        return api_error("repo_not_synced", f"run promocaster-control client-repo sync {client}", 409)
    if not media_yml.exists():
        return api_error("missing_media_yml", f"{media_yml} was not found", 404)
    try:
        return parse_media_yml(client, media_yml)
    except (OSError, ValueError) as exc:
        return api_error("media_yml_parse_failed", str(exc), 500)


@app.api_route("/api/clients/{client}/media/{requested_name:path}", methods=["GET", "HEAD"])
def get_media(client: str, requested_name: str, request: Request):
    safe_name = posixpath.normpath("/" + unquote(requested_name)).lstrip("/")
    if safe_name.startswith("../") or safe_name == "..":
        raise HTTPException(status_code=403)

    media_root = (repo_path(client) / "media").resolve()
    media_path = (media_root / safe_name).resolve()
    if media_root not in media_path.parents and media_path != media_root:
        raise HTTPException(status_code=403)
    if not media_path.is_file():
        raise HTTPException(status_code=404)

    content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    file_size = media_path.stat().st_size
    start = 0
    end = file_size - 1
    status_code = 200
    range_header = request.headers.get("range")

    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
        if match:
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
            end = min(end, file_size - 1)
            if start <= end:
                status_code = 206

    length = max(end - start + 1, 0)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    if request.method == "HEAD":
        return Response(status_code=status_code, media_type=content_type, headers=headers)
    return StreamingResponse(
        iter_file_range(media_path, start, length),
        status_code=status_code,
        media_type=content_type,
        headers=headers,
    )


@app.post("/api/clients/{client}/decks")
async def save_decks(
    client: str,
    request: Request,
    deck: str | None = Form(default=None),
    media: list[UploadFile] | None = File(default=None),
):
    try:
        payload, uploads = await read_save_request(request, deck, media or [])
        path = repo_path(client)
        branch = client_branch(client)
        media_yml = path / "_data" / "media.yml"
        if not path.exists():
            return api_error("repo_not_synced", f"run promocaster-control client-repo sync {client}", 409)
        if not media_yml.exists():
            return api_error("missing_media_yml", f"{media_yml} was not found", 404)

        ensure_save_preconditions(path, branch)
        before = parse_media_yml(client, media_yml)
        before_locations = location_names(before)
        after_locations = location_names(payload)
        if before_locations != after_locations:
            raise ValueError("location keys cannot be added, removed, renamed, or reordered in the editor")
        before_names = referenced_media_names(before)
        after_names = referenced_media_names(payload)
        removed_names = sorted(before_names - after_names)
        upload_names = [upload["filename"] for upload in uploads]
        upload_name_set = set(upload_names)
        if len(upload_names) != len(upload_name_set):
            raise ValueError("upload filenames must be unique")
        unknown_uploads = sorted(upload_name_set - after_names)
        if unknown_uploads:
            raise ValueError(f"uploaded files are not referenced by the deck: {', '.join(unknown_uploads)}")
        for upload_name in upload_names:
            if not is_safe_media_name(upload_name):
                raise ValueError(f"invalid upload filename: {upload_name}")

        media_yml.write_text(deck_to_media_yml(payload), encoding="utf-8")
        run_git(path, ["add", "_data/media.yml"])

        uploaded_files = []
        warnings = []
        media_root = path / "media"
        media_root.mkdir(parents=True, exist_ok=True)
        for upload in uploads:
            media_path = media_root / upload["filename"]
            warnings.extend(write_upload_media(upload, media_path))
            run_git(path, ["add", "--", f"media/{upload['filename']}"])
            uploaded_files.append(upload["filename"])

        deleted_files = []
        for name in removed_names:
            if name in upload_name_set:
                continue
            media_path = path / "media" / name
            if media_path.is_file():
                run_git(path, ["rm", "-f", "--", f"media/{name}"])
                deleted_files.append(name)

        status = git_status_short(path)
        if not status:
            return {"ok": True, "state": "no_changes", "message": "No changes to save", "warnings": warnings}

        user = authenticated_user(request)
        commit_message = [
            "Update slide decks",
            "",
            f"Edited by: {user}",
            f"Client: {client}",
            "Source: Promocaster Control",
        ]
        run_git(
            path,
            [
                "-c",
                "user.name=Promocaster Control",
                "-c",
                "user.email=control@promocaster.io",
                "commit",
                "-m",
                commit_message[0],
                "-m",
                "\n".join(commit_message[2:]),
            ],
        )
        commit = git_output(path, "rev-parse", "--short", "HEAD")
        run_git(path, ["push", "origin", branch])
        return {
            "ok": True,
            "state": "pushed",
            "client": client,
            "branch": branch,
            "commit": commit,
            "editedBy": user,
            "uploadedMedia": uploaded_files,
            "deletedMedia": deleted_files,
            "warnings": warnings,
        }
    except json.JSONDecodeError:
        return api_error("invalid_json", "request body must be JSON", 400)
    except ValueError as exc:
        return api_error("invalid_deck", str(exc), 400)
    except RuntimeError as exc:
        return api_error("save_failed", str(exc), 409)
    except OSError as exc:
        return api_error("save_failed", str(exc), 500)


@app.api_route("/", methods=["GET", "HEAD"])
def editor() -> FileResponse:
    return FileResponse(WEB_ROOT / "editor.html")


app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")
