#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
venv_dir="$project_dir/.venv"
requirements="$project_dir/client/requirements.txt"
stamp="$venv_dir/.client-requirements.sha256"

if [[ ${1:-} == --setup-only ]]; then
    setup_only=true
    shift
else
    setup_only=false
fi

python_cmd=${PYTHON:-python3}
if ! command -v "$python_cmd" >/dev/null 2>&1; then
    printf 'Python 3.10+ is required; install it or set PYTHON to its path.\n' >&2
    exit 1
fi
"$python_cmd" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || {
    printf 'Python 3.10 or newer is required.\n' >&2
    exit 1
}

if [[ ! -x $venv_dir/bin/python ]]; then
    "$python_cmd" -m venv "$venv_dir" || {
        printf 'Cannot create a virtual environment. On Debian/Ubuntu install python3-venv.\n' >&2
        exit 1
    }
fi

requirements_hash=$(sha256sum "$requirements" | cut -d ' ' -f 1)
if [[ ! -f $stamp || $(<"$stamp") != "$requirements_hash" ]]; then
    "$venv_dir/bin/python" -m pip install -r "$requirements"
    "$venv_dir/bin/python" -m pip check
    printf '%s\n' "$requirements_hash" > "$stamp"
fi

if $setup_only; then
    printf 'Client environment ready: %s\n' "$venv_dir"
else
    exec "$venv_dir/bin/python" "$project_dir/main.py" "$@"
fi
