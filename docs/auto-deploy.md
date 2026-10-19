# Verified dev → main deployment

After a PR from this repository's `dev` is merged into `main`, `production.yml`
runs the full unit regression, dependency check, deployment preflight, Linux and
Windows executable builds/startup and the `production-ready` gate. A direct push,
a different source branch, a fork PR, skipped/failed gate or a different revision
cannot authorize deployment. Existing real Supabase tests remain opt-in; real
clipboard/GUI/provider acceptance is separate from these automated checks.

The VPS checks public GitHub metadata every five minutes. No VPS SSH key, model
key or Supabase key is stored in GitHub Actions. No repository token is needed for
this public repository. Polling is bounded; unchanged releases use one request per
poll, pending releases normally use two. API failures/rate limiting retain the
installed service and are retried by the next timer tick, not a tight retry loop.
The latest run for the exact main SHA must pass, including `production-ready`, and
the associated merged PR must be from `dev` in the same repository. Main/CI are
checked again after staging.

## Server setup

Requires the existing `gemini-cli.service`, unprivileged `gemini-cli` account,
private `/etc/gemini-cli/server.env`, Python with venv, Git, systemd and network
access to public GitHub/PyPI. From a reviewed checkout on the VPS:

```bash
sudo python3 deploy/enable_autodeploy.py --repository OWNER/REPOSITORY
```

The installer only installs the root-owned watcher, its configuration and timer.
It does not restart the API, replace its existing release override, copy/rewrite
the env, change Nginx/TLS or migrate the database. Existing custom env entries and
permissions remain. `/etc/gemini-cli/deploy.json` holds repository and runtime
paths, with no credential values. Existing deployments are locked against setup.
Before the workflow exists on main, the watcher waits without touching production.

## Release transaction

1. Fetch exact verified main into a root-owned mirror, reject a changed main.
2. Export only runtime source and server requirements, reject links/traversal and
   excessive source size; use the existing runtime payload filter.
3. Create a separate release under `/opt/gemini-cli-releases`. Run dependency
   installation/check as the service user, without production environment values.
4. Start a transient candidate on loopback port 18000 with the existing
   `EnvironmentFile`. `/healthz` must report the exact expected SHA. It does not
   invoke Gemini, Tavily or test-account operations.
5. If the env changed during preview, refuse promotion and retain the owner's
   new env. Otherwise atomically write only `zz-autodeploy.conf`, reload/restart
   the API and verify its health/revision on port 8000.
6. If promotion fails, restore the previous override (or remove only the new one
   if there was no previous managed override), restart and verify the old service.
   The env is never restored from a backup or overwritten.

Failed or abandoned candidates are removed before/after deployment. Cleanup keeps
the active release and the recorded rollback; unrelated older release directories
are preserved. If the active path cannot be identified, deployment stops before
building. Database migrations require separate preparation/verification before merging a release;
autodeploy never applies SQL. Do not merge incompatible schema changes before
those migrations are complete.

## Operations

```bash
sudo systemctl status gemini-cli-autodeploy.timer
sudo journalctl -u gemini-cli-autodeploy.service -n 40 --no-pager
sudo python3 /usr/local/libexec/gemini-cli-deploy/poller.py --config /etc/gemini-cli/deploy.json --check
curl --fail http://127.0.0.1:8000/healthz
```

`--check` reads metadata but never builds or switches production. To stop future
checks, disable the timer with `sudo systemctl disable --now gemini-cli-autodeploy.timer`.
For recovery, the previous managed override is retained in the private watcher
state directory when one existed; previous releases and unrelated overrides are
preserved. A rollback-health failure is reported as requiring operator action.
