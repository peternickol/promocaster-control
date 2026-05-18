# Promocaster Control API

Initial API shape for replacing the embedded Jekyll data used by the prototype
editor and inspector.

## Session

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

## Decks

`GET /api/clients/:client/decks`

Returns the editable deck data for the authorized client. The response should
match the current `all-decks.json` shape used by the UI.

`POST /api/clients/:client/decks`

Accepts structured deck JSON, validates it, writes the client repo's
`_data/media.yml`, validates the affected location builds, commits, and pushes.

## Media

`POST /api/clients/:client/media`

Uploads image or MP4 media into the client repo's `media/` directory. The server
normalizes filenames, rejects invalid types, and returns the final filename.

## Publish

`POST /api/clients/:client/publish`

For the PHGI-style repo model this can be a no-op wrapper around commit/push,
because `nix.promocaster` already polls and builds by location. It remains useful
as a future explicit action for validation status, git commit metadata, and
rollback workflows.
