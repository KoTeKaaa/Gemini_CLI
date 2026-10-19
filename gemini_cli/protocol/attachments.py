"""Вложения: SDK/UI независимый DTO, байты существуют только в памяти."""

from dataclasses import dataclass, field
from io import BytesIO
from uuid import uuid4
import warnings

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_IMAGES = 4
MAX_TOTAL_BYTES = 4 * 1024 * 1024
FORMATS = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


def image_details(data: bytes) -> tuple[str, int, int]:
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Изображение пустое или больше 2 МиБ')
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in FORMATS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Нужен статический PNG, JPEG или WebP')
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError('Изображение больше 12 млн пикселей')
                result = FORMATS[image.format], image.width, image.height
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
        return result
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Не удалось декодировать изображение') from exc


@dataclass(frozen=True, repr=False)
class ImageAttachment:
    name: str
    data: bytes = field(repr=False)
    mime_type: str = field(init=False)
    width: int = field(init=False)
    height: int = field(init=False)
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        mime, width, height = image_details(self.data)
        if not isinstance(self.name, str) or not self.name or len(self.name) > 200:
            raise ValueError('Некорректное имя вложения')
        object.__setattr__(self, 'mime_type', mime)
        object.__setattr__(self, 'width', width)
        object.__setattr__(self, 'height', height)

    def metadata(self) -> dict:
        return dict(id=self.id, name=self.name, mime_type=self.mime_type,
                    size=len(self.data), width=self.width, height=self.height)


def validate_batch(images) -> None:
    if len(images) > MAX_IMAGES or sum(len(image.data) for image in images) > MAX_TOTAL_BYTES:
        raise ValueError('Не больше 4 изображений и 4 МиБ за сообщение')
