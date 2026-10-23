# Deploy after a dev → main merge

[Русский](../auto-deploy.md) · [English](auto-deploy.md) · [Home](../../README.en.md)

The server promotes only an exact current `main` commit backed by successful
`production.yml` checks, including Linux and Windows clients and `production-ready`.
The commit must come from a merged same-repository dev → main PR. Direct pushes,
fork PRs, another source branch or failed checks do not authorize promotion.

The watcher checks public GitHub metadata every five minutes. Public repositories
need no GitHub token; server SSH/provider keys are not sent to Actions. API failures
or rate limits leave the installed service running. The watcher rechecks the main
SHA and CI after preparing a candidate, before switching production.

## Install or update the watcher

Prerequisites: `gemini-cli.service`, unprivileged `gemini-cli` user, private
`/etc/gemini-cli/server.env`, Python with venv, Git, systemd and GitHub/PyPI access.
From a reviewed server checkout, replace `OWNER/REPOSITORY` and run:

```sh
sudo python3 deploy/enable_autodeploy.py --repository OWNER/REPOSITORY
```

This installs root-owned watcher code/configuration and a timer without restarting
the API or changing its environment. Update this bundle when server module delivery
changes: it is not automatically replaced with the application runtime. Installation
uses the deployment lock and retains existing TLS, database and environment settings.

## Promotion and rollback

1. Fetch the verified main SHA and copy only required server modules/dependencies
   into a separate directory under `/opt/gemini-cli-releases`. Reject links and unsafe archives.
2. Install/check dependencies as the service user without the live environment.
3. Start a candidate on loopback port 18000 with the existing EnvironmentFile.
   Its `/healthz` must return the expected SHA; no provider generation is required.
4. Recheck the environment fingerprint and release eligibility. Atomically write
   the managed override, restart production and verify availability/SHA on port 8000.
5. On failure, restore the prior release configuration and check the old service.
   The environment is not restored from a backup or overwritten.

Unused candidates are removed; active and recorded rollback releases are retained.
The watcher does not apply SQL. Prepare compatible [history](history-migration.md)
and [subscription](subscription-migration.md) schema changes separately.

## Inspect state

```sh
sudo systemctl status gemini-cli-autodeploy.timer
sudo journalctl -u gemini-cli-autodeploy.service -n 40 --no-pager
sudo python3 /usr/local/libexec/gemini-cli-deploy/poller.py --config /etc/gemini-cli/deploy.json --check
curl --fail http://127.0.0.1:8000/healthz
```

`--check` reads eligibility without building or switching a release. Disable future
polling with `sudo systemctl disable --now gemini-cli-autodeploy.timer` when intended.
If rollback fails, the journal reports that operator intervention is needed.
