"""Изменяемый черновик без отправки и без постоянного хранения."""

from dataclasses import dataclass, field
from .paste import PasteBlock, expand_blocks
from ..protocol.attachments import ImageAttachment, validate_batch


@dataclass
class Draft:
    text: str = ''
    images: list[ImageAttachment] = field(default_factory=list)

    files: list[tuple[str, str]] = field(default_factory=list)
    pastes: list[PasteBlock] = field(default_factory=list)

    def add_text_file(self, name: str, text: str) -> None:
        if sum(len(value.encode('utf-8')) for _, value in self.files) + len(text.encode('utf-8')) > 24000:
            raise ValueError('Текстовые вложения превышают 24000 байт')
        self.files.append((name, text))

    def message(self, text: str) -> str:
        result = expand_blocks(text, self.pastes) + ''.join(f'\nФайл {name!r}:\n{value}' for name, value in self.files)
        if len(result) > 28000:
            raise ValueError('Сообщение слишком большое; сократите текст или вложения')
        return result

    def add_image(self, name: str, data: bytes) -> ImageAttachment:
        image = ImageAttachment(name, data)
        validate_batch([*self.images, image])
        self.images.append(image)
        return image

    def remove(self, attachment_id: str) -> None:
        image = next((item for item in self.images if item.id == attachment_id), None)
        if image is None:
            raise ValueError('Вложение не найдено')
        self.images.remove(image)

    def clear(self) -> None:
        self.text = ''
        self.images.clear()
        self.files.clear()
        self.pastes.clear()
