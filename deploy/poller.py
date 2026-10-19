"""VPS pull deployment: no VPS/model secrets are sent to GitHub."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sys

if __package__:
    from .promote import prepare_release, promote_release, healthy
    from .verified_main import GitHub, verified_main
else:
    from promote import prepare_release, promote_release, healthy
    from verified_main import GitHub, verified_main


def load_config(path: Path) -> dict:
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Deploy configuration must be root-owned and not group/world writable')
    config = json.loads(path.read_text())
    GitHub(config['repository'])
    for name in ('env', 'releases', 'state', 'override'):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', config[name]) or '..' in Path(config[name]).parts:
            raise ValueError('Unsafe deployment path')
    if config['user'] == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]*', config['user']):
        raise ValueError('Runtime must use an unprivileged account')
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.service', config['service']):
        raise ValueError('Invalid service')
    if config['override'] != f'/etc/systemd/system/{config["service"]}.d/zz-autodeploy.conf':
        raise ValueError('Unexpected service override')
    if Path(config['releases']) == Path('/') or Path(config['state']) == Path('/'):
        raise ValueError('Deployment directories cannot be root')
    return config


def run_once(config, *, check=False, api=None, build=prepare_release, promote=promote_release, probe=healthy):
    api = api or GitHub(config['repository'])
    state = Path(config['state']) / 'state.json'
    installed = json.loads(state.read_text()).get('sha') if state.exists() else None
    if installed and not probe(8000, installed, timeout=2):
        installed = None
    sha = verified_main(api, config['repository'], installed=installed)
    if sha is None:
        print('No new verified dev -> main release; installed service retained')
        return None
    if check:
        print('Verified candidate ' + sha + '; check-only, production unchanged')
        return sha
    release = build(config, sha)
    if verified_main(api, config['repository']) != sha:
        print('Main or CI changed while staging; installed service retained')
        return None
    promote(config, release, sha)
    print('Deployed verified revision ' + sha)
    return sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run through the installed root-owned systemd service')
    def interrupted(*_args):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        config = load_config(args.config)
        with (Path(config['state']) / 'deploy.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Deployment already running; skipped')
                return
            run_once(config, check=args.check)
    except Exception as error:
        print(f'Deployment stopped: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
