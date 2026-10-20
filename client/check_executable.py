"""Проверить автономный запуск сборки с временным профилем без серверных ключей."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check(executable: Path) -> None:
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="gemini-smoke-") as temporary:
        config = Path(temporary) / ".gemini_cli"
        config.mkdir()
        (config / "server_config.json").write_text(
            json.dumps({"server_url": "http://localhost:9"}), encoding="utf-8")
        (config / "settings.json").write_text(
            json.dumps({"mode": "remote", "remote_origin": "http://localhost:9"}), encoding="utf-8")
        (config / "session.json").write_text(
            json.dumps({"access_token": "smoke-fixture-token"}), encoding="utf-8")
        environment = os.environ.copy()
        environment.update(HOME=temporary, USERPROFILE=temporary)
        for name in ("API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "TAVILY_API_KEY"):
            environment.pop(name, None)
        result = subprocess.run([str(executable)], cwd=temporary, env=environment,
                                input="", capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        output = result.stdout + result.stderr
        if result.returncode != 0 or "Traceback" in output or "ModuleNotFoundError" in output:
            # This output belongs only to the isolated fixture profile, never to a real user session.
            raise RuntimeError(f"Standalone startup failed (exit {result.returncode}):\n{output}")
        print("Standalone startup passed with an offline fixture server and no server keys.")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
