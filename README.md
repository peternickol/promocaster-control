# promocaster-control

Promocaster Control is the authenticated admin surface for managing client
slideshow content repos.

The control app is not deployed to signage devices. Devices continue to pull a
client content repo, such as `promocaster.phgi`, and `nix.promocaster` builds the
single slideshow selected by the device-local `promocaster.location` value.

## Repo Map

Local development checkouts:

- Control/admin repo: `/home/pan/temp/promocaster-control`
- PHGI runtime/content repo: `/home/pan/temp/promocaster.phgi`
- Device-side Nix appliance repo: `/home/pan/temp/nix.promocaster`

Remote repos:

- Control/admin repo: `git@github.com:peternickol/promocaster-control.git`
- PHGI runtime/content repo: `git@github.com:peternickol/promocaster.phgi.git`

This repo is the future global control plane. It may know about many clients,
but it must only expose the authenticated user's allowed clients and allowed
locations through the API.

## Current Split

- `web/` contains the editor and inspector UI copied out of the PHGI content repo.
- `clients.yml` is the control-side registry of clients and content repos.
- Locations are derived from the synced client repo's `_data/media.yml`.
- Each client record has an explicit `id`; it must match the `clients.yml` key.
- `server/` is reserved for the authenticated API and git publisher.

The copied UI currently uses an empty embedded payload so it can load as static
HTML. The next implementation step is to replace that bootstrap payload with API
calls such as `GET /api/me` and `GET /api/clients/:client/decks`.

## Ownership Boundary

This repo owns:

- authenticated admin UI
- client/location access control
- deck editor and inspector
- media uploads
- validation before publish
- git writer/publisher for client repos

This repo does not get deployed to signage devices.

Client runtime/content repos, such as `/home/pan/temp/promocaster.phgi`, own:

- `_data/media.yml`
- `media/`
- runtime `index.html`
- generated `deck.json`
- `assets/js/promocaster.js`
- `assets/css/promocaster.css`

Do not put editor/inspector/admin assets back into client runtime repos.

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

Expected future flow:

1. User authenticates to `promocaster-control`.
2. API scopes the user to an allowed client, such as `phgi`.
3. API derives that client's locations from the synced repo's `_data/media.yml`.
4. UI fetches only that client's authorized deck data.
5. API clones or updates that client's repo checkout.
6. API writes `_data/media.yml`, media uploads, and media deletions.
7. API removes no-longer-referenced media files from the repo with `git rm`.
8. API runs Jekyll validation for affected locations.
9. API commits and pushes the client repo.
10. `nix.promocaster` devices pull the client repo and build their configured location.

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

## Local Static Preview

The copied UI can be viewed with any static file server from `web/`:

```sh
cd web
python3 -m http.server 4173
```

The pages currently load an empty embedded deck payload until the API is wired.

## Debian VPS Setup

This repo owns the operator-facing Debian installer for the control server:

```sh
bash install-debian.sh
```

Run server setup commands from a root shell. These installs assume root-operated
Debian boxes, like the monitor repos, and do not assume `sudo` is installed.

The installer follows the same product-repo pattern used by the monitor repos:
install Debian packages, create a service user, copy this repo into
`/opt/promocaster-control/app`, create `/var/lib/promocaster-control`, install a
systemd service, and put Caddy in front of the local app.
Caddy is configured for `control.promocaster.io` by default.
Caddy owns Let's Encrypt certificate issuance and renewal. There is no separate
certbot job.

Default runtime layout:

```text
/root/promocaster-control         source checkout used by install/update
/opt/promocaster-control/app       copied application repo
/etc/promocaster-control/config.env
/etc/promocaster-control/basic-auth.caddy
/etc/promocaster-control/source-root
/var/lib/promocaster-control/repos client repo checkouts
/var/lib/promocaster-control/uploads upload staging
/var/lib/promocaster-control/sync  repo sync progress state
/var/lib/promocaster-control/ssh   GitHub writer key material
/usr/local/bin/promocaster-control operator maintenance command
```

Useful install overrides:

```sh
PROMOCASTER_CONTROL_PORT=8080 bash install-debian.sh
```

The current server is a thin placeholder: it serves `web/`, redirects `/` to the
editor, and exposes `GET /api/health`. The real auth, deck editing API, upload
handling, and git publisher should be added under `server/` without moving the
runtime slideshow files back into this repo.

### Test Box Preflight

Before standing up a Debian test box, confirm:

- `control.promocaster.io` has an `A` record pointing at the VPS.
- Public TCP ports `80` and `443` reach the VPS.
- The repo is cloned at the fixed server path: `/root/promocaster-control`.
- The VPS has enough disk for large client repos. For testing, keep at least
  `40-60 GB` free under `/var/lib/promocaster-control`.
- After install, the generated GitHub writer public key must be added to
  `promocaster.phgi` with write access.

Initial install flow:

```sh
cd /root
git clone git@github.com:peternickol/promocaster-control.git
cd /root/promocaster-control
bash install-debian.sh
promocaster-control basic-auth set peter
promocaster-control github-key show-public
promocaster-control github-key test
promocaster-control client-repo sync phgi
promocaster-control tls-check
promocaster-control doctor
```

The first test deployment should prove:

- Debian package installation
- systemd service wiring
- Caddy reverse proxy wiring
- Let's Encrypt issuance and renewal path
- HTTP-to-HTTPS redirect
- Phase 1 Basic Auth guard
- GitHub SSH authentication
- `doctor` diagnostics

The installer also disables cloud-init `manage_etc_hosts` with
`/etc/cloud/cloud.cfg.d/99-promocaster-control-hosts.cfg`, then removes
`control.promocaster.io` from loopback entries in `/etc/hosts` if Debian put the
FQDN on `127.0.1.1`. The short hostname can stay there, but the public FQDN must
resolve through DNS so Caddy and Let's Encrypt see the real VPS address.

Current limitation: this server is not yet a functional remote deck editor. It
does not yet clone/fetch the PHGI repo, parse `_data/media.yml`, save deck
changes, upload media, delete removed media, validate Jekyll builds, commit, or
push. Those belong to the next repo/API implementation layer.

### Maintenance Commands

The installer records the source checkout in
`/etc/promocaster-control/source-root` and exposes a global command. On the VPS,
the repo checkout is always `/root/promocaster-control`.

```sh
promocaster-control doctor
promocaster-control basic-auth set peter
promocaster-control basic-auth test
promocaster-control github-key generate
promocaster-control github-key edit
promocaster-control github-key show-public
promocaster-control github-key test
promocaster-control client-repo list
promocaster-control client-repo sync phgi
promocaster-control client-repo status phgi
promocaster-control tls-check
promocaster-control update
promocaster-control update --no-pull
promocaster-control update --force
promocaster-control repair
```

This intentionally mirrors the hard-won monitor pattern. `doctor` checks runtime
paths, storage pressure, service state, Caddy wiring, GitHub writer key health,
and whether the source checkout is clean and pullable. `update` refuses detached
heads and dirty checkouts, pulls with `--ff-only`, refreshes
`/opt/promocaster-control/app`, rewrites systemd and Caddy files, reloads
services, and leaves the global command symlink in sync. `repair` performs that
refresh path without pulling.

### Phase 1 Authentication

Phase 1 uses Caddy Basic Auth as a public-site guard while the app-level Google
OAuth/user model is still pending. This is intentionally coarse: anyone with the
Basic Auth password can reach the control UI, so do not use it as the final
client authorization model.

Set the initial login on the VPS:

```sh
promocaster-control basic-auth set peter
promocaster-control basic-auth test
promocaster-control doctor
```

The password is hashed with `caddy hash-password` and written to:

```text
/etc/promocaster-control/basic-auth.caddy
```

The Caddy site imports that snippet before proxying to the app. Until credentials
are configured, the installer writes a placeholder snippet that returns `503`
instead of exposing the app. `doctor` reports this as a failed `Auth` check.

For manual recovery, the snippet can be edited directly:

```sh
promocaster-control basic-auth edit
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy.service
```

### Storage Checks

Client content repos can be large. PHGI-style repos may already be around 1.5 GB,
and control may eventually cache many client repos under
`/var/lib/promocaster-control/repos`. `doctor` reports:

- free space on the data filesystem
- total repo cache size
- each cached client repo size
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
while, so editor/inspector should show a progress state while the server clones
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

The placeholder server already exposes that status endpoint. The future repo
sync worker should write status JSON to `/var/lib/promocaster-control/sync` as
it clones/fetches, and the UI should poll until `state` becomes `ready` before
loading decks.

Operators can sync configured client repos from the command line:

```sh
promocaster-control client-repo list
promocaster-control client-repo sync phgi
promocaster-control client-repo status phgi
```

`client-repo sync <client>` reads `clients.yml`, uses the GitHub writer key,
clones or fetches into a directory named after the Git repo, writes progress
state to `/var/lib/promocaster-control/sync/<client>.json`, and leaves the
checkout at the configured branch. For PHGI, that means:

```text
/var/lib/promocaster-control/repos/promocaster.phgi
/var/lib/promocaster-control/sync/phgi.json
```

First sync can take a while for large media repos.

### GitHub Writer Key

The control API needs a GitHub SSH key with write access to each client content
repo it manages, starting with `promocaster.phgi`. The installer generates a
dedicated ed25519 writer key on first install:

```text
/var/lib/promocaster-control/ssh/github_writer_key
/var/lib/promocaster-control/ssh/github_writer_key.pub
```

Show the public key and test GitHub auth:

```sh
promocaster-control github-key show-public
promocaster-control github-key test
promocaster-control doctor
```

Add the public key printed by `github-key show-public` to GitHub with write
access. For one repo, a writable deploy key is fine. For many client repos, use a
dedicated machine user such as `promocaster-bot` and grant that user write access
to the client repos.

Manual key commands:

```sh
promocaster-control github-key generate
promocaster-control github-key generate --force
promocaster-control github-key edit
```

`github-key generate` creates a key if one does not already exist. Use
`generate --force` only when intentionally rotating the GitHub writer key.
`github-key edit` follows the same operator pattern as `wg-manager edit`: it
creates the secure directory/file if needed, locks permissions down, and opens
the private key in `nano` for paste/edit workflows.

### Let's Encrypt Bring-Up

For the public control site, point DNS for `control.promocaster.io` at the VPS
before expecting HTTPS to come up. Public TCP ports `80` and `443` must reach
Caddy on the box. Caddy uses port `80` for HTTP-01 challenges and redirects all
normal HTTP traffic to HTTPS. The control app is served on `443`.

Useful checks on the server:

```sh
promocaster-control tls-check
journalctl -u caddy.service -n 100 --no-pager
caddy validate --config /etc/caddy/Caddyfile
```

## API Contract

Initial API shape for replacing the embedded Jekyll data used by the prototype
editor and inspector.

### Session

`GET /api/me`

Returns the authenticated user and the clients/locations they can access.
Locations are discovered from the client repo after sync, then filtered by auth
policy. They are not duplicated in `clients.yml`.

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
validates the affected location builds, commits, and pushes.

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
  "commit": "abc1234",
  "deleted_media": ["old-special.mp4", "expired-promo.jpg"]
}
```

### Media

`POST /api/clients/:client/media`

Uploads image or MP4 media into the client repo's `media/` directory. The server
normalizes filenames, rejects invalid types, and returns the final filename.

### Publish

`POST /api/clients/:client/publish`

For the PHGI-style repo model this can be a no-op wrapper around commit/push,
because `nix.promocaster` already polls and builds by location. It remains useful
as a future explicit action for validation status, git commit metadata, and
rollback workflows.
