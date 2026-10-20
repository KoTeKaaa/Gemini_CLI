"""Win32: ограничить сырой блок до копирования, не открывать списки файлов."""

from io import BytesIO
from .clipboard import ClipboardError, ClipboardImage
from ..protocol.attachments import MAX_IMAGE_BYTES, MAX_PIXELS, image_details

MAX_DIB_BYTES = MAX_PIXELS * 4 + 65536


def _read_windows(*, text=False):
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype = wintypes.UINT
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalSize.argtypes = [wintypes.HANDLE]
    kernel.GlobalSize.restype = ctypes.c_size_t
    kernel.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not user.OpenClipboard(None):
        raise ClipboardError('Буфер Windows занят или недоступен; повторите вставку')
    try:
        if user.IsClipboardFormatAvailable(15):  # CF_HDROP
            raise ClipboardError('В буфере список файлов; выберите изображение через @')
        png = user.RegisterClipboardFormatW('PNG')
        formats = [(13, 'TEXT')] if text else [(png, 'PNG'), (17, 'DIB'), (8, 'DIB')]
        for code, kind in formats:
            if not code or not user.IsClipboardFormatAvailable(code):
                continue
            handle = user.GetClipboardData(code)
            size = kernel.GlobalSize(handle)
            limit = 65536 if kind == 'TEXT' else MAX_IMAGE_BYTES if kind == 'PNG' else MAX_DIB_BYTES
            if not handle or not size or size > limit:
                raise ClipboardError('Изображение в буфере слишком велико или повреждено')
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise ClipboardError('Не удалось прочитать изображение из буфера')
            try:
                return kind, ctypes.string_at(pointer, size)
            finally:
                kernel.GlobalUnlock(handle)
        return None
    finally:
        user.CloseClipboard()


class WindowsClipboard:
    def __init__(self, reader=None):
        self.reader = reader or _read_windows

    def read_image(self) -> ClipboardImage | None:
        from PIL import Image
        try:
            result = self.reader()
            if result is None:
                return None
            kind, data = result
            if kind == 'DIB':
                if len(data) > MAX_DIB_BYTES:
                    raise ClipboardError('Слишком большой DIB')
                with Image.open(BytesIO(data)) as image:
                    if image.format != 'DIB' or image.width * image.height > MAX_PIXELS:
                        raise ClipboardError('Некорректный DIB или превышен предел пикселей')
                    output = BytesIO()
                    image.save(output, format='PNG')
                    data = output.getvalue()
            image_details(data)
            return ClipboardImage(data)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, ClipboardError):
                raise
            raise ClipboardError('Не удалось прочитать изображение Windows; прикрепите файл через @') from None

    def read_text(self) -> str | None:
        result = _read_windows(text=True)
        if result is None:
            return None
        try:
            return result[1].decode('utf-16-le').split('\0', 1)[0]
        except UnicodeError:
            raise ClipboardError('Некорректный текст в буфере') from None
