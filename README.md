# promocaster-control

Promocaster Control is the Promocaster-specific admin UI/API. Dish is the
installable Debian server component that builds and serves the project repo
cloned to `/root/project`. This repo contributes
`dish.yml` and does not own Debian installation.

Promocaster Control is the authenticated admin surface for managing client
slideshow content repos.

The control app is not deployed to signage devices. Devices continue to pull a
client content repo, such as `promocaster.phgi`, and `nix.promocaster` builds the
single slideshow selected by the device-local `promocaster.location` value.

## TODO

- Add CSRF protection for browser form posts and state-changing API requests.
- Add two-factor authentication after the initial public launch.

## Repo Map

Local development checkouts:

- Control/admin repo: `/home/pan/temp/promocaster-control`
- Debian project host repo: `/home/pan/temp/dish`
- Fleet orchestration repo: `/home/pan/temp/fleet.sh`
- Monitor core repo: `/home/pan/temp/monitor.core`
- PHGI runtime/content repo: `/home/pan/temp/promocaster.phgi`
- Device-side Nix appliance repo: `/home/pan/temp/nix.promocaster`

Remote repos:

- Control/admin repo: `git@github.com:peternickol/promocaster-control.git`
- PHGI runtime/content repo: `git@github.com:peternickol/promocaster.phgi.git`

This repo is the global control plane. It may know about many clients, but it
must only expose the authenticated user's allowed clients and allowed locations
through the API.

## Current Split

- `backend/templates/` contains the editor and viewer pages.
- `assets/` contains shared CSS, JavaScript, images, and vendored browser assets.
- The control SQLite database is the registry of clients, users, and access rules.
- Locations are derived from the synced client repo's `_data/media.yml`.
- The client id is stored as the `clients.id` database key.
- `backend/` contains the FastAPI web app and Promocaster domain helpers.
- Dish owns Debian install, Caddy/service wiring, project builds, refreshes,
  and Dish self-update.
- Promocaster client/content repos are cached under
  `/var/lib/dish/project/client/<directory>`, not under Dish's
  `/root/project` source checkout.

## UI Standards

- Use Lucide for all UI icons across Promocaster projects.
- Do not add new Iconify, Tabler, Solar, Boxicons, or mixed icon-system markup.
- Use `data-lucide="icon-name"` in templates and call `lucide.createIcons()`
  from the page or shared footer after the Lucide bundle loads.
- Existing vendored/demo theme assets may contain other icon systems, but
  product templates and project-owned CSS/JS should stay Lucide-only.

The editor and viewer now load deck data from the synced client repo through
`GET /api/clients/:client/decks`. The first save path is also wired:
`POST /api/clients/:client/decks` rewrites `_data/media.yml`, deletes media that
is no longer referenced anywhere, commits, and pushes the client repo.

## Ownership Boundary

This repo owns:

- authenticated admin UI
- client/location access control
- users, sessions, roles, and authorization policy
- deck editor and viewer
- media uploads
- validation before publish
- git writer/publisher for client repos

Dish may render generic Caddy directives from `dish.yml`, but Dish does
not own Promocaster users or authorization. Do not add Promocaster-specific auth
commands to Dish.

This repo does not get deployed to signage devices.
This repo is deployed on a Debian host by Dish from `/root/project`.

Client runtime/content repos, such as `/home/pan/temp/promocaster.phgi`, own:

- `_data/media.yml`
- `media/`
- runtime `index.html`
- generated `deck.json`
- `assets/js/promocaster.js`
- `assets/css/promocaster.css`

Do not put editor/viewer/admin assets back into client runtime repos.
Do not add `dish.yml` to client runtime repos unless they are intentionally
being hosted as standalone Dish projects.

## PHGI Client Repo

`promocaster.phgi` remains the runtime/content repo for PHGI only. Control will
edit that repo by writing `_data/media.yml`, copying uploaded media into
`media/`, validating the affected location builds, then committing and pushing.

`nix.promocaster` can keep its current workflow:

1. Pull the PHGI repo.
2. Generate device-local Jekyll config with the device location.
3. Build the site with Jekyll.
4. Serve `/srv/site/current` through Caddy.

The PHGI device-side config continues to look like:

```nix
promocaster.repoUrl = "git@github.com:peternickol/promocaster.phgi.git";
promocaster.location = "pnwpizza-yacolt";
```

PHGI has multiple locations in one client repo. That is intentional. The split is
by client, not by individual screen/location.

## Location Lifecycle

Location lifecycle is an admin operation, not a control UI operation.
`nix.promocaster` devices are preprogrammed with a location code, so location
keys must already exist in the client content repo before a device can use them.

For PHGI, adding or removing a location means manually editing the client repo's
top-level `_data/media.yml` keys and coordinating the matching device-side
`promocaster.location` value in `nix.promocaster` configuration.

Promocaster Control may derive and display locations, but the editor must not
create, rename, or delete location keys. It only edits slides inside locations
that already exist in the synced client repo. The API must reject save payloads
that add a new location, remove an existing location, or rename a location.

## Save and Publish Flow

Current save flow:

1. User authenticates to `promocaster-control`.
2. API scopes the user to an allowed client, such as `phgi`.
3. API derives that client's locations from the synced repo's `_data/media.yml`.
4. UI fetches only that client's authorized deck data.
5. API clones or updates that client's repo checkout.
6. API writes `_data/media.yml`, media uploads, and media deletions.
7. API removes no-longer-referenced media files from the repo with `git rm`.
8. API commits and pushes the client repo.
9. `nix.promocaster` devices pull the client repo and build their configured location.

The save implementation edits deck data and uploads new media files in the same
commit. Jekyll validation is still planned follow-up work.
Generated YAML quotes slide filenames and schedule values, even when the current
value is simple. That keeps long filenames, punctuation, and empty dates safe.

When a slide is removed in the editor, the backing media file must be deleted
from the client repo if no remaining slide references it. This is important for
large media repos: removing a slide from YAML but leaving the file on disk would
make the repo grow forever.

Deletion safety rules:

- only delete files inside the client repo's `media/` directory
- normalize to plain media filenames, never trust user-supplied paths
- do not delete a file if any remaining deck/location still references it
- do not delete a file that was just uploaded and is still referenced by the new payload
- do not treat removed locations as a content-editor deletion; location removal is manual/admin-only
- use `git rm -- media/<filename>` so the deletion is committed and pushed
- include deleted files in the API response so the UI can show what changed

## Local Development

Run the FastAPI app with a synced repo path when testing real data:

```sh
uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

## Debian VPS Setup

Dish is the intended Debian server component. A server should install
Dish, clone this repo to `/root/project`, and let Dish read this
repo's `dish.yml` to build/publish/refresh the control app.

```sh
dish project clone git@github.com:peternickol/promocaster-control.git
dish build
```

Dish-style runtime layout:

```text
/root/project                 source checkout used by Dish
/root/project/dish.yml
/srv/dish/project/current
/var/lib/dish/project
/var/lib/dish/project/client
/var/lib/dish/status/status.json
```

Promocaster Control runs as the unprivileged `dish-project` service user.
Dish performs host operations as root, but the app only writes under
`/var/lib/dish/project`, including client repo checkouts, sync state, uploads,
Git config, and its client GitHub key.

The FastAPI app serves `backend/templates/`, exposes static files from
`assets/`, redirects `/` to `/editor`, exposes
`GET /api/health`, reads synced client deck data, serves synced media previews,
processes media uploads, and can save deck edits back to the client repo. Full
Jekyll validation is still pending.

### Test Box Preflight

Before standing up a Debian test box, confirm:

- `control.promocaster.io` has an `A` record pointing at the VPS.
- Public TCP ports `80` and `443` reach the VPS.
- Dish is installed on the VPS.
- Dish's deploy key public half has read access to this repo, unless the
  first clone is being done with a separate operator SSH key.
- The repo is cloned at `/root/project`.
- The VPS has enough disk for large client repos. For testing, keep at least
  `40-60 GB` free under `/var/lib/dish/project`.
- After install, Promocaster Control needs its own client GitHub key with write
  access to `promocaster.phgi`.

Initial install flow:

```sh
cd /root
git clone git@github.com:peternickol/dish.git /root/dish
cd /root/dish
bash install-debian.sh
dish build
promocaster-control client-github-key generate
promocaster-control client-github-key show-public
promocaster-control client-github-key test
promocaster-control client-repo sync phgi
promocaster-control auth setup-token
promocaster-control doctor
```

During `bash install-debian.sh`, Dish generates its deploy key, prints the
public key to add to the Promocaster Control GitHub repo, then asks for the
project repo URL. Enter:

```text
git@github.com:peternickol/promocaster-control.git
```

Run `dish build` before any `promocaster-control ...` command. The global
`promocaster-control` command is installed by Dish from this repo's
`components.bin` declaration and does not exist until the project has been
published.

After the service starts for the first time, create the first admin user from
the login page. The setup token is stored under the Dish project data directory
and can be printed with:

```sh
promocaster-control auth setup-token
```

The first test deployment should prove:

- Dish can install the Debian host component
- Dish can build and publish this repo from `dish.yml`
- Dish's one-minute refresh timer can pull and rebuild repo updates
- client GitHub SSH authentication
- `doctor` diagnostics

Current limitation: Jekyll validation is not yet implemented. The existing save
path covers order, duration, start date, expiration date, new media upload,
image normalization to 1080p, removal from `_data/media.yml`, deletion of
unreferenced media files, commit, and push.

### Maintenance Commands

Dish owns app install, build, refresh, update, and Dish/project GitHub key
management. Promocaster Control's operator command is only for app-specific
checks, its client GitHub key, and client/content repo syncs.

Dish's README is the point of truth for Dish install, manifest, refresh,
status, and fleet behavior. Keep Promocaster Control documentation focused on
what this hosted app owns.

```sh
promocaster-control doctor
promocaster-control auth setup-token
promocaster-control client-repo list
promocaster-control client-repo sync phgi
promocaster-control client-repo status phgi
```

Use Dish for build and update work:

```sh
dish build
dish refresh
dish update
```

`dish refresh` pulls the app repo, rebuilds/publishes it, installs missing
packages declared in this repo's `dish.yml`, restarts the declared services,
and then runs any project-specific commands listed under `refresh.commands`.

This repo's `dish.yml` presents the project host shortname, generated
service, rendered environment, operator command link, simple Caddy reverse-proxy
route, and blank firewall allow list as data. Dish installs those
generically; it does not carry Promocaster-specific server logic.
Promocaster authentication and client/location authorization stay in the
Promocaster app. Temporary Caddy access gates, if needed, should be represented
as generic `components.caddy.directives` in `dish.yml`.
Promocaster Control does not expose extra ports; app traffic stays on
`127.0.0.1:8080` behind Caddy, so `components.firewall.allow` remains blank.

Promocaster Control declares `promocaster-control.service` under
`components.service` and leaves `refresh.commands` blank. Its app deployment
has no extra post-refresh step beyond Dish's build, publish, component
install, and service restart. `promocaster-control client-repo sync <client>`
is intentionally separate: it refreshes a client/content repo under
`/var/lib/dish/project/client`, not the Promocaster Control app under
`/root/project`.

Promocaster Control is currently file/repo-backed. If it later needs a database,
the database engine and schema file should be declared in this repo's
`dish.yml` under `database` so Dish can build and refresh it from
project-owned files.
If that database becomes server-owned state, Dish's built-in database
commands own backup, export, restore, and clear.

`promocaster-control doctor` checks runtime paths, storage pressure, client
GitHub key health, and client repo status.

### Storage Checks

Client content repos can be large. PHGI-style repos may already be around 1.5 GB,
and control may eventually cache many client repos under
`/var/lib/dish/project/client`. This is intentionally separate from
Dish's `/root/project` source checkout. `doctor` reports:

- free space on the data filesystem
- total repo cache size
- each cached client repo size
- whether each cached git repo is trusted in Control's Git config
- upload staging size
- temporary validation build size under `/tmp/promocaster-control-builds`

Default thresholds are intentionally conservative:

```text
data free space: warn below 20 GB, fail below 8 GB
single client repo: warn above 5 GB
all repos total: warn above 25 GB
upload staging: warn above 2 GB
temp builds: warn above 5 GB
```

These can be adjusted with environment variables such as
`PROMOCASTER_CONTROL_DATA_FREE_WARN_GB` and
`PROMOCASTER_CONTROL_REPO_SIZE_WARN_GB` if the VPS is sized differently.

Initial repo sync must never make the UI look frozen. A first clone can take a
while, so editor/viewer should show a progress state while Control clones
or fetches the client repo. The intended API shape is:

```http
GET /api/clients/phgi/sync/status
```

Example response while a first clone is running:

```json
{
  "client": "phgi",
  "state": "cloning",
  "percent": 42,
  "message": "Receiving objects: 42%",
  "started_at": "2026-05-18T22:10:00Z"
}
```

The FastAPI app exposes that status endpoint. The future repo sync worker should write status JSON to
`/var/lib/dish/project/sync` as
it clones/fetches, and the UI should poll until `state` becomes `ready` before
loading decks.

Operators can sync configured client repos from the command line:

```sh
promocaster-control client-repo list
promocaster-control client-repo sync phgi
promocaster-control client-repo status phgi
```

Clients are added and edited from the admin UI. The operator CLI intentionally
does not mutate the client registry.
`client-repo sync <client>` reads the client registry from SQLite, uses the client GitHub key,
clones or fetches into a directory named after the Git repo, writes progress
state to `/var/lib/dish/project/sync/<client>.json`, and leaves the
checkout at the configured branch. It also repairs ownership of the checkout for
the `promocaster-control` service user and adds the checkout to Control's Git
`safe.directory` list in `/var/lib/dish/project/gitconfig`.
`client-repo status <client>` fetches origin and reports whether the local
checkout is clean and matches the remote branch.
For PHGI, that means:

```text
/var/lib/dish/project/client/promocaster.phgi
/var/lib/dish/project/sync/phgi.json
/var/lib/dish/project/gitconfig
```

First sync can take a while for large media repos.

If Git reports `detected dubious ownership` for a cached client repo, run:

```sh
promocaster-control client-repo sync phgi
```

`promocaster-control client-repo sync <client>` also repairs ownership and marks
the client checkout safe.

### GitHub Keys

There are three GitHub keys in a full Promocaster Control install, with
different owners.

Dish manages its own deploy key for pulling the hosted project repo into
`/root/project` and updating Dish itself from `/root/dish`:

```text
/var/lib/dish/ssh/deploy_key
/var/lib/dish/ssh/deploy_key.pub
```

Manage it with:

```sh
dish github-key show-public
dish github-key test
dish github-key generate
dish github-key edit
```

Dish manages the hosted project key for the Promocaster Control project
lifecycle. That key belongs to Dish's project layer:

```text
/var/lib/dish/project/ssh/github_key
/var/lib/dish/project/ssh/github_key.pub
```

Manage it with:

```sh
dish project github-key show-public
dish project github-key test
dish project github-key generate
dish project github-key edit
```

Promocaster Control separately manages a client GitHub key. This key is
project-specific and is used only for the downstream client repos listed in
the control database:

```text
/var/lib/dish/project/ssh/client_github_key
/var/lib/dish/project/ssh/client_github_key.pub
```

Show the public key and test GitHub auth:

```sh
promocaster-control client-github-key show-public
promocaster-control client-github-key test
promocaster-control doctor
```

Add the public key printed by `promocaster-control client-github-key
show-public` to GitHub with write access to the client content repos. For one
repo, a writable deploy key is fine. For many client repos, use a dedicated
machine user such as `promocaster-bot` and grant that user write access to the
client repos.

Manual client key commands:

```sh
promocaster-control client-github-key generate
promocaster-control client-github-key generate --force
promocaster-control client-github-key edit
```

`promocaster-control client-github-key generate` creates a key if one does not
already exist. Use `--force` only when intentionally rotating the client key.
`promocaster-control client-github-key edit` creates the secure directory/file
if needed, locks permissions down, and opens the private key in `$EDITOR` or
`nano` for paste/edit workflows.

## API Contract

Initial API shape for replacing the embedded Jekyll data used by the prototype
editor and viewer.

### Session

`GET /api/me`

Returns the authenticated user and the clients/locations they can access.
Locations are discovered from the client repo after sync, then filtered by auth
policy. They are not duplicated in the control database.

```json
{
  "user": {"email": "manager@example.com", "role": "editor"},
  "clients": [
    {
      "id": "phgi",
      "name": "PHGI",
      "repo_status": "ready",
      "locations": ["pnwpizza-yacolt"]
    }
  ]
}
```

### Decks

`GET /api/clients/:client/decks`

Returns the editable deck data for the authorized client. The response should
match the current `all-decks.json` shape used by the UI.

`POST /api/clients/:client/decks`

Accepts structured deck JSON, validates it, writes the client repo's
`_data/media.yml`, deletes removed media files that are no longer referenced,
uploads new media files, normalizes image uploads to fit within 1920x1080,
commits, and pushes. Jekyll validation is planned but not implemented yet.

The submitted location set must exactly match the existing location set derived
from the repo's current `_data/media.yml`. If the payload adds, removes, or
renames a location, the API must reject the save and tell the operator that
location lifecycle is an admin operation.

The save handler must compare the old repo state to the new payload:

```text
old_refs = all media files referenced by current _data/media.yml
new_refs = all media files referenced by submitted deck JSON
delete_candidates = old_refs - new_refs
deleted = delete_candidates that are not referenced anywhere else
```

Each deleted media file should be removed with:

```sh
git rm -- media/<filename>
```

The endpoint should return the committed deletion list:

```json
{
  "ok": true,
  "state": "pushed",
  "commit": "abc1234",
  "editedBy": "peter",
  "uploadedMedia": ["new-special.jpg"],
  "deletedMedia": ["old-special.mp4", "expired-promo.jpg"]
}
```

The browser sends saves as `multipart/form-data` with one `deck` JSON part and
one `media` file part for each pending upload. Uploaded filenames must already
be referenced by the submitted deck JSON.

Image uploads (`.jpg`, `.jpeg`, `.png`) are processed with ImageMagick before
commit: auto-orient, resize to fit inside 1920x1080 without upscaling, strip
metadata, and write with quality 85. Videos are not transformed. If an uploaded
image is smaller than 1920x1080, the save response includes a warning so the
operator knows the source is below the 1080p target.

Video uploads (`.mp4`) are inspected with `ffprobe` before commit. Control
rejects files that are not valid videos and warns when a video is below or above
the 1920x1080 target, uses a non-H.264 codec, runs longer than 120 seconds, or
is larger than 250 MB.

Commits created by Control include the authenticated user:

```text
Update slide decks

Edited by: peter
Client: phgi
Source: Promocaster Control
```

### Media

Standalone media uploads are not the current path. Media files are uploaded as
part of `POST /api/clients/:client/decks` so YAML and files land in one commit.
Control rejects invalid media filenames and unsupported extensions.

### Publish

`POST /api/clients/:client/publish`

For the PHGI-style repo model this can be a no-op wrapper around commit/push,
because `nix.promocaster` already polls and builds by location. It remains useful
as a future explicit action for validation status, git commit metadata, and
rollback workflows.
