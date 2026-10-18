"""Кодировка перенаправленного вывода Windows не зависит от локальной ANSI codepage."""

import os
import sys


def configure_output(*, platform=os.name, streams=None) -> None:
    if platform != "nt":
        return
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        if stream is not None and not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
