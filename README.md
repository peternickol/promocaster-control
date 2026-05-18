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
but it must only expose the authenticated user's allowed clients and locations
through the API.

## Current Split

- `web/` contains the editor and inspector UI copied out of the PHGI content repo.
- `clients.yml` is the control-side registry of clients, content repos, and editable locations.
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

## Save and Publish Flow

Expected future flow:

1. User authenticates to `promocaster-control`.
2. API scopes the user to an allowed client, such as `phgi`.
3. UI fetches only that client's deck data.
4. API clones or updates that client's repo checkout.
5. API writes `_data/media.yml` and media uploads.
6. API runs Jekyll validation for affected locations.
7. API commits and pushes the client repo.
8. `nix.promocaster` devices pull the client repo and build their configured location.

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
sudo bash install-debian.sh
```

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
/etc/promocaster-control/source-root
/var/lib/promocaster-control/repos client repo checkouts
/var/lib/promocaster-control/uploads upload staging
/var/lib/promocaster-control/ssh   GitHub writer key material
/usr/local/bin/promocaster-control operator maintenance command
```

Useful install overrides:

```sh
sudo PROMOCASTER_CONTROL_PORT=8080 bash install-debian.sh
```

The current server is a thin placeholder: it serves `web/`, redirects `/` to the
editor, and exposes `GET /api/health`. The real auth, deck editing API, upload
handling, and git publisher should be added under `server/` without moving the
runtime slideshow files back into this repo.

### Maintenance Commands

The installer records the source checkout in
`/etc/promocaster-control/source-root` and exposes a global command. On the VPS,
the repo checkout is always `/root/promocaster-control`.

```sh
promocaster-control doctor
promocaster-control tls-check
promocaster-control update
promocaster-control update --no-pull
promocaster-control update --force
promocaster-control repair
```

This intentionally mirrors the hard-won monitor pattern. `doctor` checks runtime
paths, service state, Caddy wiring, and whether the source checkout is clean and
pullable. `update` refuses detached heads and dirty checkouts, pulls with
`--ff-only`, refreshes `/opt/promocaster-control/app`, rewrites systemd and
Caddy files, reloads services, and leaves the global command symlink in sync.
`repair` performs that refresh path without pulling.

### Let's Encrypt Bring-Up

For the public control site, point DNS for `control.promocaster.io` at the VPS
before expecting HTTPS to come up. Public TCP ports `80` and `443` must reach
Caddy on the box. Caddy uses port `80` for HTTP-01 challenges and redirects, then
serves the app on `443` after the certificate is issued.

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

```json
{
  "user": {"email": "manager@example.com", "role": "editor"},
  "clients": [
    {
      "id": "phgi",
      "name": "PHGI",
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
`_data/media.yml`, validates the affected location builds, commits, and pushes.

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
