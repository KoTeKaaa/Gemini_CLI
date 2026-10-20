"""Доставка server.py и управляемого пакета без файлов окружения и тестов."""

import argparse
import os
from pathlib import Path
import shutil
import tempfile


def install_runtime(source: Path, destination: Path) -> None:
    package = source / "gemini_cli"
    server = source / "server.py"
    if (package.is_symlink() or not package.is_dir()
            or not (package / "__init__.py").is_file()
            or (package / "__init__.py").is_symlink()
            or server.is_symlink() or not server.is_file()):
        raise ValueError("Incomplete runtime source")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "gemini_cli"
    server_target = destination / "server.py"
    if (target.is_symlink() or server_target.is_symlink()
            or (target.exists() and not target.is_dir())
            or (server_target.exists() and not server_target.is_file())):
        raise ValueError("Runtime target must not be a link or an unexpected file type")

    # Prepare everything before replacing the installed runtime, including in-place installs.
    with tempfile.TemporaryDirectory(prefix=".runtime-", dir=destination) as temporary:
        staging = Path(temporary)
        staged_package = staging / "gemini_cli"
        staged_package.mkdir()
        staged_package.chmod(0o755)
        def abort_walk(error: OSError) -> None:
            raise error

        for directory, subdirs, files in os.walk(
                package, followlinks=False, onerror=abort_walk):
            current = Path(directory)
            relative = current.relative_to(package)
            subdirs[:] = [
                name for name in subdirs
                if name.isidentifier() and name not in {"tests", "__pycache__"}
                and not (current / name).is_symlink()
                and not (relative == Path(".") and name == "client")
                and not (relative == Path("tools") and name == "local")
            ]
            output = staged_package / relative
            output.mkdir(parents=True, exist_ok=True)
            output.chmod(0o755)
            for name in files:
                module = current / name
                if relative == Path("backends") and name not in {"__init__.py", "genai.py", "model_info.py"}:
                    continue
                panel_asset = (relative.as_posix() in {"server/admin/templates", "server/admin/static"}
                               and module.suffix in {".html", ".css", ".js"})
                if ((module.suffix != ".py" and not panel_asset) or not module.stem.isidentifier()
                        or name.startswith("test_") or name.endswith("_test.py")
                        or name == "conftest.py" or module.is_symlink()
                        or not module.is_file()):
                    continue
                shutil.copyfile(module, output / name)
                (output / name).chmod(0o644)
        shutil.copyfile(server, staging / "server.py")
        (staging / "server.py").chmod(0o644)

        backup = staging / "previous-package"
        if target.exists():
            target.rename(backup)
        try:
            staged_package.rename(target)
            os.replace(staging / "server.py", server_target)
        except OSError:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    install_runtime(arguments.source, arguments.destination)
