"""Install the verified-main watcher without changing the API service or its env."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess

if __package__:
    from .promote import atomic_write
    from .verified_main import GitHub
else:
    from promote import atomic_write
    from verified_main import GitHub


def run(args, *, check=True):
    return subprocess.run(args, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def install(source: Path, root: Path, repository: str, *, execute=run):
    GitHub(repository)
    env = root / 'etc/gemini-cli/server.env'
    before = hashlib.sha256(env.read_bytes()).digest()
    if env.stat().st_mode & 0o077:
        raise ValueError('Existing server.env must have private permissions; installer does not change it')
    state = root / 'var/lib/gemini-cli-deploy'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if execute(['systemctl', 'is-active', '--quiet', 'gemini-cli-autodeploy.service'], check=False).returncode == 0:
            raise ValueError('Deployment is active; retry installing after it finishes')
        was_active = execute(['systemctl', 'is-active', '--quiet', 'gemini-cli-autodeploy.timer'], check=False).returncode == 0
        execute(['systemctl', 'stop', 'gemini-cli-autodeploy.timer'], check=False)
        try:
            library = root / 'usr/local/libexec/gemini-cli-deploy'
            library.mkdir(parents=True, exist_ok=True)
            for name in ('poller.py', 'promote.py', 'runtime_payload.py', 'verified_main.py'):
                atomic_write(library / name, (source / name).read_bytes(), 0o644)
            (root / 'opt/gemini-cli-releases').mkdir(parents=True, exist_ok=True)
            override = root / 'etc/systemd/system/gemini-cli.service.d'
            override.mkdir(parents=True, exist_ok=True)
            config = dict(repository=repository, service='gemini-cli.service', user='gemini-cli',
                          env='/etc/gemini-cli/server.env', state='/var/lib/gemini-cli-deploy',
                          releases='/opt/gemini-cli-releases',
                          override='/etc/systemd/system/gemini-cli.service.d/zz-autodeploy.conf')
            atomic_write(root / 'etc/gemini-cli/deploy.json', json.dumps(config, indent=2).encode())
            for name in ('gemini-cli-autodeploy.service', 'gemini-cli-autodeploy.timer'):
                atomic_write(root / 'etc/systemd/system' / name, (source / name).read_bytes(), 0o644)
            execute(['systemd-analyze', 'verify', str(root / 'etc/systemd/system/gemini-cli-autodeploy.service'),
                     str(root / 'etc/systemd/system/gemini-cli-autodeploy.timer')])
            if hashlib.sha256(env.read_bytes()).digest() != before:
                raise ValueError('Owner changed env during installation; no environment was overwritten')
            execute(['systemctl', 'daemon-reload'])
            execute(['systemctl', 'enable', '--now', 'gemini-cli-autodeploy.timer'])
        except BaseException:
            if was_active:
                execute(['systemctl', 'start', 'gemini-cli-autodeploy.timer'], check=False)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root on the server')
    install(Path(__file__).resolve().parent, Path('/'), args.repository)
    print('Verified-main timer enabled; existing API service and environment retained')


if __name__ == '__main__':
    main()
