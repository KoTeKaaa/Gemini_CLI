"""Обнаружение буфера без его чтения; чтение только явным read_image()."""

from dataclasses import dataclass
import os
import shutil
import sys
from typing import Protocol


class ClipboardError(ValueError):
    pass


@dataclass(frozen=True)
class ClipboardImage:
    data: bytes
    name: str = "Скриншот.png"


class Clipboard(Protocol):
    def read_image(self) -> ClipboardImage | None: ...


def detect_backend(*, platform=None, environ=None, which=None) -> str:
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    if platform == "win32":
        return "windows"
    if platform.startswith("linux"):
        if environ.get("WAYLAND_DISPLAY"):
            if which("wl-paste"):
                return "wayland"
            raise ClipboardError("Установите wl-clipboard (wl-paste) для Wayland")
        if environ.get("DISPLAY") and which("xclip"):
            return "x11"
        raise ClipboardError("Нужен графический сеанс и xclip для X11")
    raise ClipboardError("Буфер поддерживается на Windows и Linux; прикрепите файл через @")


def get_clipboard() -> Clipboard:
    backend = detect_backend()
    if backend == 'windows':
        from .clipboard_windows import WindowsClipboard
        return WindowsClipboard()
    from .clipboard_linux import LinuxClipboard
    return LinuxClipboard(backend)
