"""wl-paste/xclip без shell: ограничены stdout и время процесса."""

import subprocess
from threading import Thread
from .clipboard import ClipboardError, ClipboardImage
from ..protocol.attachments import MAX_IMAGE_BYTES, image_details


def bounded_output(argv: list[str], *, limit: int, timeout: float = 2.0) -> bytes:
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise ClipboardError('Утилита буфера не запустилась; установите wl-clipboard или xclip') from None
    chunks = []
    def read():
        data = process.stdout.read(limit + 1)
        chunks.append(data)
        if len(data) > limit:
            process.kill()
    reader = Thread(target=read, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
        reader.join(timeout)
        if reader.is_alive():
            raise ClipboardError('Чтение буфера превысило время ожидания')
        data = chunks[0] if chunks else b''
        if len(data) > limit:
            raise ClipboardError('Данные буфера превышают допустимый размер')
        if process.returncode:
            raise ClipboardError('Буфер пуст, занят или графический сеанс недоступен')
        return data
    except subprocess.TimeoutExpired:
        raise ClipboardError('Чтение буфера превысило 2 секунды') from None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join(timeout)
        process.stdout.close()


class LinuxClipboard:
    def __init__(self, backend: str, run=None):
        if backend not in {'wayland', 'x11'}:
            raise ClipboardError('Неизвестный Linux backend')
        self.backend, self.run = backend, run or bounded_output

    def read_image(self) -> ClipboardImage | None:
        listing = (['wl-paste', '--list-types'] if self.backend == 'wayland'
                   else ['xclip', '-selection', 'clipboard', '-out', '-target', 'TARGETS'])
        types = self.run(listing, limit=8192).decode('utf-8', errors='replace').split()
        mime = next((kind for kind in ('image/png', 'image/jpeg', 'image/webp') if kind in types), None)
        if mime is None:
            if 'text/uri-list' in types:
                raise ClipboardError('В буфере список файлов; выберите файл через @')
            return None
        command = (['wl-paste', '--no-newline', '--type', mime] if self.backend == 'wayland'
                   else ['xclip', '-selection', 'clipboard', '-out', '-target', mime])
        data = self.run(command, limit=MAX_IMAGE_BYTES)
        try:
            actual, _, _ = image_details(data)
            if actual != mime:
                raise ValueError()
        except ValueError:
            raise ClipboardError('Буфер содержит повреждённое или слишком большое изображение') from None
        return ClipboardImage(data, 'Скриншот.' + {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime])
