"""Изменяемый черновик без отправки и без постоянного хранения."""

from dataclasses import dataclass, field
from ..protocol.attachments import ImageAttachment, validate_batch


@dataclass
class Draft:
    text: str = ''
    images: list[ImageAttachment] = field(default_factory=list)

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
