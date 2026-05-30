from __future__ import annotations

import json
import mimetypes
import posixpath
import re
import sqlite3
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.auth import (
    SETUP_TOKEN_PATH,
    ROLE_LABELS,
    SESSION_COOKIE,
    allowed_client_ids,
    authenticate,
    consume_setup_token,
    create_session,
    create_user,
    delete_session,
    get_user,
    init_auth_db,
    list_users,
    set_user_clients,
    update_user,
    user_for_session,
    users_exist,
    verify_setup_token,
)
from backend.control import (
    ASSETS_DIR,
    CLIENTS_FILE,
    DATA_DIR,
    MAX_JSON_BODY_BYTES,
    MAX_MULTIPART_BODY_BYTES,
    REPOS_DIR,
    SYNC_DIR,
    TEMPLATE_DIR,
    client_branch,
    client_info,
    client_repo_name,
    deck_to_media_yml,
    ensure_save_preconditions,
    git_output,
    git_status_short,
    is_safe_media_name,
    location_names,
    load_clients,
    parse_media_yml,
    referenced_media_names,
    run_git,
    write_upload_media,
)


app = FastAPI(title="Promocaster Control")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
ADMIN_ASSETS_DIR = ASSETS_DIR / "admin"
ADMIN_TEMPLATE_DIR = TEMPLATE_DIR / "admin"
if ADMIN_ASSETS_DIR.exists():
    app.mount("/admin/assets", StaticFiles(directory=str(ADMIN_ASSETS_DIR)), name="admin_assets")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
admin_templates = Jinja2Templates(directory=str(ADMIN_TEMPLATE_DIR))


def request_user(request: Request) -> dict | None:
    if hasattr(request.state, "user"):
        return request.state.user
    user = user_for_session(request.cookies.get(SESSION_COOKIE))
    request.state.user = user
    return user


def login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/?next={quote(next_path, safe='/?=&')}", status_code=303)


def safe_next_path(next_path: str | None) -> str:
    next_path = (next_path or "/deck").strip() or "/deck"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/deck"
    return next_path


def require_user(request: Request) -> dict:
    user = request_user(request)
    if not user:
        raise HTTPException(status_code=401)
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403)
    return user


def user_can_edit(user: dict | None) -> bool:
    return bool(user and user["role"] in {"admin", "editor"})


def selected_deck_mode(mode: str, user: dict | None) -> str:
    if mode == "editor":
        if not user_can_edit(user):
            raise HTTPException(status_code=403)
        return "editor"
    return "viewer"


def ensure_client_access(request: Request, client: str) -> dict:
    user = require_user(request)
    if client not in allowed_client_ids(user):
        raise HTTPException(status_code=403)
    return user


def deck_nav(mode: str = "viewer", user: dict | None = None) -> list[dict]:
    clients = []
    allowed = allowed_client_ids(user)
    for client_id, config in load_clients().items():
        if allowed and client_id not in allowed:
            continue
        if not allowed and user is not None:
            continue
        locations = []
        media_yml = repo_path(client_id) / "_data" / "media.yml"
        if media_yml.exists():
            try:
                deck_data = parse_media_yml(client_id, media_yml)
                locations = [
                    {
                        "name": location.get("name", ""),
                        "slide_count": len(location.get("slides", [])),
                        "href": deck_href(client_id, location.get("name", ""), mode),
                    }
                    for location in deck_data.get("locations", [])
                    if location.get("name")
                ]
            except (OSError, ValueError):
                locations = []
        clients.append(
            {
                "id": client_id,
                "name": config.get("name") or client_id,
                "href": deck_href(client_id, locations[0]["name"] if locations else "", mode),
                "locations": locations,
            }
        )
    return clients


def deck_href(client: str, location: str = "", mode: str = "viewer") -> str:
    selected_mode = "editor" if mode == "editor" else "viewer"
    path = f"/deck/{quote(client, safe='')}"
    if location:
        path += f"/{quote(location, safe='')}"
    if selected_mode == "editor":
        return f"{path}?mode=editor"
    return path


def first_deck_href(mode: str = "viewer", user: dict | None = None) -> str:
    nav = deck_nav(mode, user)
    if not nav:
        return "/deck?mode=editor" if mode == "editor" else "/deck"
    first_client = nav[0]
    if first_client["locations"]:
        return first_client["locations"][0]["href"]
    return first_client["href"]


def admin_context(request: Request, page_title: str = "Dashboard") -> dict:
    user = request_user(request)
    role = (user or {}).get("role", "viewer")
    mode = request.query_params.get("mode", "viewer")
    if mode == "editor" and not user_can_edit(user):
        mode = "viewer"
    return {
        "request": request,
        "title": page_title,
        "admin_title": "Promocaster Control",
        "current_user": user,
        "admin_user": (user or {}).get("email", "Promocaster"),
        "admin_role": ROLE_LABELS.get(role, role.title()),
        "is_admin": role == "admin",
        "can_edit": user_can_edit(user),
        "deck_clients": deck_nav(mode, user),
        "selected_client_id": "",
        "selected_location_name": "",
        "editor_href": "/deck?mode=editor",
        "viewer_href": "/deck?mode=viewer",
        "deck_mode": "editor" if mode == "editor" else "viewer",
        "show_components": False,
        "sidebar_variant": "promocaster",
    }


def client_choices() -> list[dict]:
    return [
        {"id": client_id, "name": config.get("name") or client_id}
        for client_id, config in sorted(load_clients().items(), key=lambda item: (item[1].get("name") or item[0]).lower())
    ]


def user_admin_context(request: Request, page_title: str, **extra) -> dict:
    context = admin_context(request, page_title)
    context.update(
        {
            "roles": ROLE_LABELS,
            "clients": client_choices(),
            "form_error": "",
            "form_values": {},
        }
    )
    context.update(extra)
    return context


async def user_form_data(request: Request, *, require_password: bool) -> tuple[dict, list[str], str]:
    form = await request.form()
    password = str(form.get("password") or "")
    confirm_password = str(form.get("confirm_password") or "")
    data = {
        "email": str(form.get("email") or "").strip(),
        "role": str(form.get("role") or "viewer").strip().lower(),
        "active": str(form.get("status") or "active") == "active",
        "password": password,
    }
    client_ids = [str(client_id) for client_id in form.getlist("client_ids")]
    if not data["email"]:
        return data, client_ids, "Email is required."
    if data["role"] not in ROLE_LABELS:
        return data, client_ids, "Choose a valid role."
    if require_password and not password:
        return data, client_ids, "Password is required."
    if password and password != confirm_password:
        return data, client_ids, "Passwords do not match."
    if data["role"] != "admin" and not client_ids:
        return data, client_ids, "Assign at least one client for editor and viewer users."
    return data, client_ids, ""


def repo_path(client: str) -> Path:
    return REPOS_DIR / client_repo_name(client)


def api_error(error: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": error, "message": message}, status_code=status_code)


def authenticated_user(request: Request) -> str:
    user = request_user(request)
    if user:
        return user.get("email") or "unknown"
    return (
        request.headers.get("X-Promocaster-User")
        or request.headers.get("Remote-User")
        or request.headers.get("X-Remote-User")
        or "unknown"
    ).strip() or "unknown"


def wants_json_error(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api/") or "application/json" in accept


def error_template_name(status_code: int) -> str:
    if status_code in {400, 401, 403, 404, 408, 500}:
        return f"pages/error-{status_code}.html"
    if 400 <= status_code < 500:
        return "pages/error-400.html"
    return "pages/error-500.html"


def http_status_title(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    status_code = exc.status_code
    message = str(exc.detail or http_status_title(status_code))
    if wants_json_error(request):
        return api_error(http_status_title(status_code).lower().replace(" ", "_"), message, status_code)
    return admin_templates.TemplateResponse(
        error_template_name(status_code),
        admin_context(request, f"{status_code} Error"),
        status_code=status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if wants_json_error(request):
        return api_error("internal_server_error", "Internal Server Error", 500)
    return admin_templates.TemplateResponse(
        "pages/error-500.html",
        admin_context(request, "500 Error"),
        status_code=500,
    )


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
    if not ASSETS_DIR.exists():
        raise RuntimeError(f"assets directory does not exist: {ASSETS_DIR}")
    if not TEMPLATE_DIR.exists():
        raise RuntimeError(f"template directory does not exist: {TEMPLATE_DIR}")
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    init_auth_db()


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    public = (
        path == "/"
        or path == "/login"
        or path == "/setup"
        or path.startswith("/assets/")
        or path.startswith("/admin/assets/")
        or path == "/api/health"
    )
    request.state.user = user_for_session(request.cookies.get(SESSION_COOKIE))
    if not public and not request.state.user:
        if path.startswith("/api/"):
            return api_error("not_authenticated", "Sign in required", 401)
        return login_redirect(request)
    return await call_next(request)


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


@app.get("/api/me")
def api_me(request: Request) -> dict:
    user = require_user(request)
    return {"user": user, "clients": deck_nav("viewer", user)}


@app.get("/api/clients/{client}/sync/status")
def sync_status(request: Request, client: str) -> dict:
    ensure_client_access(request, client)
    return read_sync_status(client)


@app.get("/api/clients/{client}/decks")
def get_decks(request: Request, client: str):
    ensure_client_access(request, client)
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
    ensure_client_access(request, client)
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
        "Cache-Control": "public, max-age=31536000, immutable" if request.query_params.get("v") else "no-cache",
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
    user = ensure_client_access(request, client)
    if user["role"] not in {"admin", "editor"}:
        return api_error("not_authorized", "Editor access required", 403)
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


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def login(request: Request, next: str = "/deck", error: str = ""):
    next = safe_next_path(next)
    if not users_exist():
        return admin_templates.TemplateResponse(
            "pages/auth-sign-in.html",
            {
                **admin_context(request, "Set Up"),
                "setup_mode": True,
                "next": next,
                "login_error": error,
                "setup_token_path": str(SETUP_TOKEN_PATH),
            },
        )
    if request_user(request):
        return RedirectResponse(url=next, status_code=303)
    return admin_templates.TemplateResponse(
        "pages/auth-sign-in.html",
        {**admin_context(request, "Sign In"), "setup_mode": False, "next": next, "login_error": error},
    )


@app.post("/login", response_class=RedirectResponse)
def login_submit(
    request: Request,
    email: str = Form(default=""),
    password: str = Form(default=""),
    remember: str | None = Form(default=None),
    next: str = Form(default="/deck"),
) -> RedirectResponse:
    user = authenticate(email, password)
    if not user:
        return RedirectResponse(url=f"/?error=invalid&next={quote(safe_next_path(next), safe='/?=&')}", status_code=303)
    token, expires = create_session(user["id"], remember=bool(remember))
    response = RedirectResponse(url=safe_next_path(next), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.post("/setup", response_class=RedirectResponse)
def setup_submit(
    request: Request,
    setup_token: str = Form(default=""),
    email: str = Form(default=""),
    password: str = Form(default=""),
    confirm_password: str = Form(default=""),
) -> RedirectResponse:
    if users_exist():
        return RedirectResponse(url="/", status_code=303)
    if (
        not verify_setup_token(setup_token)
        or not email.strip()
        or not password
        or password != confirm_password
    ):
        return RedirectResponse(url="/?error=setup", status_code=303)
    user_id = create_user(
        {
            "email": email,
            "role": "admin",
            "active": True,
            "password": password,
        },
        [],
    )
    consume_setup_token()
    token, expires = create_session(user_id, remember=False)
    response = RedirectResponse(url="/deck", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, expires=expires, httponly=True, secure=request.url.scheme == "https", samesite="lax")
    return response


@app.api_route("/logout", methods=["GET", "POST"], response_class=RedirectResponse)
def logout(request: Request) -> RedirectResponse:
    delete_session(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.api_route("/deck", methods=["GET", "HEAD"], response_class=HTMLResponse)
def deck(request: Request, mode: str = "viewer"):
    user = require_user(request)
    selected_mode = selected_deck_mode(mode, user)
    nav = deck_nav(selected_mode, user)
    if not nav:
        raise HTTPException(status_code=403)
    first_client = nav[0]
    href = first_client["locations"][0]["href"] if first_client["locations"] else first_client["href"]
    return RedirectResponse(url=href, status_code=307)


@app.api_route("/deck/{client}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def deck_client(request: Request, client: str, mode: str = "viewer"):
    user = ensure_client_access(request, client)
    selected_mode = selected_deck_mode(mode, user)
    context = admin_context(request, "Viewer" if selected_mode == "viewer" else "Editor")
    context["deck_mode"] = selected_mode
    context["selected_client_id"] = client
    context["selected_client"] = client_info(client)
    context["selected_location_name"] = ""
    context["editor_href"] = deck_href(client, "", "editor")
    context["viewer_href"] = deck_href(client, "", "viewer")
    context["deck_clients"] = deck_nav(selected_mode, user)
    template_name = "viewer.html" if selected_mode == "viewer" else "editor.html"
    return templates.TemplateResponse(template_name, context)


@app.api_route("/deck/{client}/{location:path}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def deck_location(request: Request, client: str, location: str, mode: str = "viewer"):
    user = ensure_client_access(request, client)
    selected_mode = selected_deck_mode(mode, user)
    context = admin_context(request, "Viewer" if selected_mode == "viewer" else "Editor")
    context["deck_mode"] = selected_mode
    context["selected_client_id"] = client
    context["selected_client"] = client_info(client)
    context["selected_location_name"] = unquote(location)
    context["editor_href"] = deck_href(client, unquote(location), "editor")
    context["viewer_href"] = deck_href(client, unquote(location), "viewer")
    context["deck_clients"] = deck_nav(selected_mode, user)
    template_name = "viewer.html" if selected_mode == "viewer" else "editor.html"
    return templates.TemplateResponse(template_name, context)


@app.api_route("/admin", methods=["GET", "HEAD"], response_class=HTMLResponse)
def admin_home(request: Request):
    require_admin(request)
    return RedirectResponse(url="/dashboard", status_code=307)


@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
def dashboard(request: Request):
    require_admin(request)
    return admin_templates.TemplateResponse(
        "pages/promocaster-dashboard.html",
        admin_context(request, "Dashboard"),
    )


@app.api_route("/user", methods=["GET", "HEAD"], response_class=HTMLResponse)
def users_page(request: Request):
    require_admin(request)
    return admin_templates.TemplateResponse(
        "pages/promocaster-users.html",
        user_admin_context(request, "Users", users=list_users()),
    )


@app.api_route("/user/new", methods=["GET", "HEAD"], response_class=HTMLResponse)
def user_new_page(request: Request):
    require_admin(request)
    return admin_templates.TemplateResponse(
        "pages/promocaster-user-add.html",
        user_admin_context(request, "Add User", form_values={"role": "editor", "status": "active", "client_ids": []}),
    )


@app.post("/user/new", response_class=HTMLResponse)
async def user_new_submit(request: Request):
    require_admin(request)
    data, client_ids, error = await user_form_data(request, require_password=True)
    if error:
        data["client_ids"] = client_ids
        data["status"] = "active" if data.get("active") else "disabled"
        return admin_templates.TemplateResponse(
            "pages/promocaster-user-add.html",
            user_admin_context(request, "Add User", form_error=error, form_values=data),
            status_code=400,
        )
    try:
        user_id = create_user(data, client_ids)
    except sqlite3.IntegrityError:
        data["client_ids"] = client_ids
        data["status"] = "active" if data.get("active") else "disabled"
        return admin_templates.TemplateResponse(
            "pages/promocaster-user-add.html",
            user_admin_context(request, "Add User", form_error="Email already exists.", form_values=data),
            status_code=400,
        )
    return RedirectResponse(url=f"/user/edit/{user_id}", status_code=303)


@app.api_route("/user/edit/{user_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def user_edit_page(request: Request, user_id: int):
    require_admin(request)
    edit_user = get_user(user_id)
    if not edit_user:
        raise HTTPException(status_code=404)
    return admin_templates.TemplateResponse(
        "pages/promocaster-user-edit.html",
        user_admin_context(request, "Edit User", edit_user=edit_user),
    )


@app.post("/user/edit/{user_id}", response_class=HTMLResponse)
async def user_edit_submit(request: Request, user_id: int):
    require_admin(request)
    edit_user = get_user(user_id)
    if not edit_user:
        raise HTTPException(status_code=404)
    data, client_ids, error = await user_form_data(request, require_password=False)
    if error:
        data["id"] = user_id
        data["clients"] = client_ids
        data["status"] = "active" if data.get("active") else "disabled"
        return admin_templates.TemplateResponse(
            "pages/promocaster-user-edit.html",
            user_admin_context(request, "Edit User", form_error=error, edit_user=data),
            status_code=400,
        )
    try:
        update_user(user_id, data, client_ids)
    except sqlite3.IntegrityError:
        data["id"] = user_id
        data["clients"] = client_ids
        data["status"] = "active" if data.get("active") else "disabled"
        return admin_templates.TemplateResponse(
            "pages/promocaster-user-edit.html",
            user_admin_context(request, "Edit User", form_error="Email already exists.", edit_user=data),
            status_code=400,
        )
    return RedirectResponse(url=f"/user/edit/{user_id}", status_code=303)


@app.api_route("/access", methods=["GET", "HEAD"], response_class=HTMLResponse)
def access_page(request: Request):
    require_admin(request)
    return admin_templates.TemplateResponse(
        "pages/promocaster-access.html",
        user_admin_context(request, "Access", users=list_users()),
    )


@app.post("/access", response_class=HTMLResponse)
async def access_submit(request: Request):
    require_admin(request)
    form = await request.form()
    user_id = int(str(form.get("user_id") or "0") or 0)
    edit_user = get_user(user_id)
    if not edit_user:
        raise HTTPException(status_code=404)
    if edit_user["role"] != "admin":
        set_user_clients(user_id, [str(client_id) for client_id in form.getlist("client_ids")])
    return RedirectResponse(url="/access", status_code=303)


ADMIN_PAGE_ROUTES = {
    "clients": ("promocaster-clients.html", "Clients"),
    "client": ("promocaster-client-edit.html", "Client"),
    "client-sync": ("promocaster-client-sync.html", "Client Sync"),
    "user": ("promocaster-users.html", "Users"),
    "user/edit": ("promocaster-user-edit.html", "User"),
    "user/new": ("promocaster-user-add.html", "Add User"),
    "access": ("promocaster-access.html", "Access"),
    "profile": ("apps-users-profile.html", "Profile"),
}


@app.api_route("/{page_path:path}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def admin_flat_page(request: Request, page_path: str):
    if page_path in {"clients", "client", "client-sync", "user", "user/edit", "user/new", "access"}:
        require_admin(request)
    safe_path = posixpath.normpath("/" + unquote(page_path)).lstrip("/")
    route = ADMIN_PAGE_ROUTES.get(safe_path)
    if not route:
        raise HTTPException(status_code=404)
    template_name, title = route
    return admin_templates.TemplateResponse(
        f"pages/{template_name}",
        admin_context(request, title),
    )
