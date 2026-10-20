#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
"$project_dir/client/run.sh" --setup-only --with-local
python="$project_dir/.venv/bin/python"
"$python" -m pip install 'pyinstaller>=6.22,<7'
"$python" -m PyInstaller --noconfirm --clean --onefile \
    --name gemini-cli \
    --hidden-import PIL.PngImagePlugin --hidden-import PIL.JpegImagePlugin --hidden-import PIL.WebPImagePlugin --hidden-import PIL.BmpImagePlugin --collect-all google.genai --collect-all trafilatura --collect-submodules keyring.backends \
    --distpath "$project_dir/dist" \
    --workpath "$project_dir/build" \
    --specpath "$project_dir/build" \
    "$project_dir/main.py"
printf 'Built: %s/dist/gemini-cli\n' "$project_dir"
