"""Изменяемый черновик без отправки и без постоянного хранения."""

from dataclasses import dataclass, field
from .paste import PasteBlock, expand_blocks
from ..protocol.attachments import ImageAttachment, validate_batch


@dataclass
class Draft:
    text: str = ''
    _items: dict[int, ImageAttachment | tuple[str, str] | PasteBlock] = field(default_factory=dict, repr=False)
    _next_number: int = 1

    @property
    def images(self) -> list[ImageAttachment]:
        return [item for item in self._items.values() if isinstance(item, ImageAttachment)]

    @property
    def files(self) -> list[tuple[str, str]]:
        return [item for item in self._items.values() if isinstance(item, tuple)]

    @property
    def pastes(self) -> list[PasteBlock]:
        return [item for item in self._items.values() if isinstance(item, PasteBlock)]

    def items(self) -> list[tuple[int, ImageAttachment | tuple[str, str] | PasteBlock]]:
        return list(self._items.items())

    def number_of(self, value) -> int:
        return next(number for number, item in self._items.items() if item is value)

    def item(self, number: int):
        try:
            return self._items[number]
        except KeyError:
            raise ValueError(f'Нет вложения #{number}. Список: /attachments') from None

    def _add(self, value) -> None:
        self._items[self._next_number] = value
        self._next_number += 1

    def add_paste(self, text: str) -> PasteBlock:
        block = PasteBlock.create(text)
        block.token = block.token.replace('Вставка ', f'Вставка #{self._next_number}: ')
        self._add(block)
        return block

    def remove_number(self, number: int) -> None:
        item = self.item(number)
        if isinstance(item, PasteBlock):
            self.text = self.text.replace(item.token, '')
        del self._items[number]

    def add_text_file(self, name: str, text: str) -> None:
        if sum(len(value.encode('utf-8')) for _, value in self.files) + len(text.encode('utf-8')) > 24000:
            raise ValueError('Текстовые вложения превышают 24000 байт')
        self._add((name, text))

    def message(self, text: str) -> str:
        result = expand_blocks(text, self.pastes) + ''.join(f'\nФайл {name!r}:\n{value}' for name, value in self.files)
        if len(result) > 28000:
            raise ValueError('Сообщение слишком большое; сократите текст или вложения')
        return result

    def add_image(self, name: str, data: bytes) -> ImageAttachment:
        image = ImageAttachment(name, data)
        validate_batch([*self.images, image])
        self._add(image)
        return image

    def remove(self, attachment_id: str) -> None:
        image = next((item for item in self.images if item.id == attachment_id), None)
        if image is None:
            raise ValueError('Вложение не найдено')
        self.remove_number(self.number_of(image))

    def clear(self) -> None:
        self.text = ''
        self._items.clear()
        self._next_number = 1
