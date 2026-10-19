"""Root-owned release promotion; production env is read, never copied or rewritten."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

if __package__:
    from .runtime_payload import install_runtime
else:
    from runtime_payload import install_runtime


def command(args, *, check=True, **kwargs):
    return subprocess.run(args, check=check, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=600, **kwargs)


def atomic_write(path: Path, data: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def healthy(port: int, revision: str | None, *, timeout=30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f'http://127.0.0.1:{port}/' + ('healthz' if revision else 'chats'), timeout=2) as response:
                data = json.loads(response.read(8192))
            if revision and data == {'status': 'ok', 'revision': revision}:
                return True
        except HTTPError as error:
            if revision is None and error.code == 401:
                return True
        except (OSError, URLError, ValueError):
            pass
        time.sleep(.25)
    return False


def prepare_release(config: dict, sha: str) -> Path:
    root = Path(config['releases'])
    existed = root.exists()
    root.mkdir(parents=True, exist_ok=True)
    if not existed:
        root.chmod(0o755)
    release = root / (sha + '-' + uuid4().hex[:8])
    mirror = Path(config['state']) / 'repository.git'
    if not mirror.exists():
        command(['git', 'init', '--bare', str(mirror)])
    remote = 'https://github.com/' + config['repository'] + '.git'
    command(['git', '--git-dir=' + str(mirror), 'fetch', '--depth=1', remote, 'refs/heads/main'])
    fetched = subprocess.check_output(['git', '--git-dir=' + str(mirror), 'rev-parse', 'FETCH_HEAD'], timeout=10).decode().strip()
    if fetched != sha:
        raise ValueError('Main advanced; candidate was not promoted')
    with tempfile.TemporaryDirectory(dir=config['state']) as temporary:
        archive = Path(temporary) / 'source.tar'
        command(['git', '--git-dir=' + str(mirror), 'archive', '--output=' + str(archive), sha,
                 'server.py', 'gemini_cli', 'deploy/requirements-server.txt'])
        source = Path(temporary) / 'source'
        source.mkdir()
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            if sum(member.size for member in members) > 32 * 1024 * 1024:
                raise ValueError('Runtime source too large')
            for member in members:
                parts = PurePosixPath(member.name)
                if parts.is_absolute() or '..' in parts.parts or not (member.isdir() or member.isfile()):
                    raise ValueError('Unsafe runtime archive')
                target = source.joinpath(*parts.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as content, target.open('wb') as output:
                        output.write(content.read())
        install_runtime(source, release)
        release.chmod(0o755)
        requirements = release / 'requirements-server.txt'
        requirements.write_bytes((source / 'deploy/requirements-server.txt').read_bytes())
        requirements.chmod(0o644)
    command(['python3', '-m', 'venv', str(release / '.venv')])
    command(['chown', '-R', config['user'], str(release / '.venv')])
    python = str(release / '.venv/bin/python')
    prefix = ['runuser', '-u', config['user'], '--']
    clean_env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    command(prefix + [python, '-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check',
                      '-r', str(requirements)], env=clean_env)
    command(prefix + [python, '-m', 'pip', 'check'], env=clean_env)
    return release


def promote_release(config: dict, release: Path, sha: str, *, run=command, probe=healthy):
    env = Path(config['env'])
    fingerprint = hashlib.sha256(env.read_bytes()).digest()
    override = Path(config['override'])
    previous = override.read_bytes() if override.exists() else None
    preview = 'gemini-cli-candidate-' + uuid4().hex[:10]
    uvicorn = str(release / '.venv/bin/uvicorn')
    switched = False
    try:
        run(['systemd-run', '--quiet', '--collect', '--unit=' + preview,
             '--property=User=' + config['user'], '--property=WorkingDirectory=' + str(release),
             '--property=EnvironmentFile=' + str(env), '--property=RuntimeMaxSec=120',
             '--property=NoNewPrivileges=yes', '--setenv=GEMINI_RELEASE_SHA=' + sha,
             '--setenv=PYTHONDONTWRITEBYTECODE=1', uvicorn, 'server:app', '--host', '127.0.0.1', '--port', '18000'])
        if not probe(18000, sha):
            raise RuntimeError('Candidate health failed; installed release retained')
        if hashlib.sha256(env.read_bytes()).digest() != fingerprint:
            raise RuntimeError('Environment changed during preview; promotion refused')
        content = (f'[Service]\nWorkingDirectory={release}\nExecStart=\n'
                   f'ExecStart={uvicorn} server:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1\n'
                   f'Environment=GEMINI_RELEASE_SHA={sha}\n')
        state = Path(config['state'])
        if previous is not None:
            atomic_write(state / 'previous-override.conf', previous)
        switched = True
        atomic_write(override, content.encode(), 0o644)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'restart', config['service']])
        if not probe(8000, sha):
            raise RuntimeError('Production health failed')
        atomic_write(state / 'state.json', json.dumps({'sha': sha, 'release': str(release)}).encode())
    except BaseException:
        if switched:
            if previous is None:
                override.unlink(missing_ok=True)
            else:
                atomic_write(override, previous, 0o644)
            run(['systemctl', 'daemon-reload'])
            run(['systemctl', 'restart', config['service']])
            if not probe(8000, None):
                raise RuntimeError('Promotion and rollback health failed; operator action required') from None
        raise
    finally:
        run(['systemctl', 'stop', preview], check=False)
