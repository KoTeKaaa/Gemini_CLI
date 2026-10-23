# Run your own Remote server

[Home](../../README.en.md) · [Русская инструкция](../../README.md#remote-и-панель-владельца)

You do not need this for Local. A Remote server needs its own Gemini key, Supabase
project, subscription schema and owner configuration. Personal Local keys are not
used for server requests. Prepare the database and invited accounts before exposing the API.

## Before installation

Read the [subscription guide](subscription-migration.md) and
[history schema guide](history-migration.md). Test migrations in preview, make a
production backup, close public signup and anonymous sign-in, and create the
intended subscriptions. Do not assume old accounts automatically have access.

Prepare a private `KEY=value` file outside the checkout with these settings:

```env
API_KEY=YOUR_SERVER_GEMINI_KEY
SUPABASE_URL=YOUR_SUPABASE_PROJECT_URL
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVER_SERVICE_ROLE_KEY
ADMIN_USER_ID=YOUR_TRUSTED_OWNER_UUID
ADMIN_ORIGIN=https://YOUR_HOST:9444
ADMIN_SESSION_SECRET=YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
```

These are placeholders, not usable credentials. Keep the real file private and
never attach it to an issue. Add a server Tavily key only if server web search is needed.

## Ubuntu/Debian installation

From a reviewed checkout on your server, use an existing certificate:

```sh
sudo ./deploy/install.sh --host YOUR_HOST --cert-mode existing \
  --cert-file /absolute/path/fullchain.pem --key-file /absolute/path/privkey.pem \
  --env-file /absolute/path/server.env
```

Add `--check` first for a read-only preflight. The installer defaults to HTTPS API
port 9443 and panel port 9444; configure ports with `--port` and `--panel-port`.
`ADMIN_ORIGIN` must exactly match the panel's HTTPS origin.

If you need certificate issuance, the installer supports `--cert-mode issue`
through a dedicated acme.sh installation. Public TCP port 80 must be reachable
and free for issuance/renewal. Do not displace an existing service to use this mode;
provide an existing certificate instead. Keep TLS validation enabled in clients.

The installed API runs as an unprivileged service on loopback behind Nginx.
The owner panel is reached at its separate HTTPS origin through `/admin/login`.
Inviting an account and issuing a subscription activation link are separate actions.
An account without a valid subscription cannot use working APIs.

## Development only

For a local preview, create a Python environment, install `requirements.txt`,
provide the same server variables in a private environment or `.env`, then run
`python server.py`. This binds `127.0.0.1:8000` without TLS and is not the VPS
installation path. Do not turn a preview run into a public HTTP endpoint.

## Updates

Use the [verified deployment watcher](auto-deploy.md) for approved dev → main
releases. It verifies CI and the exact revision, health-checks a candidate, keeps
the existing environment and rolls back on failed production health. SQL changes
remain separate operator actions; the watcher never migrates the database for you.
