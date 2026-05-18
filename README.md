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
- `docs/api.md` describes the first API contract.
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
