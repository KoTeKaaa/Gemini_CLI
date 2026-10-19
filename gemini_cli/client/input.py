"""Действия черновика: клавиши не отправляют запрос и не запускают backend."""

from rich.panel import Panel
from rich.text import Text
from prompt_toolkit.key_binding import KeyBindings
from .preview import ImagePreview
from .paste import PasteBlock, is_large, view_text, edit_text
from prompt_toolkit.keys import Keys
from ..protocol.attachments import ImageAttachment
from .clipboard import get_clipboard, ClipboardError


def safe_label(text: str) -> str:
    return ''.join(char if char.isprintable() else '?' for char in text)


def result_panel(message: str, *, title='Черновик', error=False) -> Panel:
    color = 'yellow' if error else '#4285F4'
    return Panel(Text(message), title=Text(title, style=color), border_style=color,
                 padding=(0, 1), expand=False)


class DraftInput:
    def __init__(self, draft, clipboard_factory=None):
        self.draft = draft
        self.clipboard_factory = clipboard_factory or get_clipboard
        self.notice = ''
        self.pasted_text = None
        self.preview = ImagePreview()
        self.bindings = KeyBindings()
        self.bindings.add('c-v')(self.paste_key)
        self.bindings.add(Keys.BracketedPaste)(self.bracketed_paste)

    def paste(self) -> bool:
        self.pasted_text = None
        try:
            clipboard = self.clipboard_factory()
            image = clipboard.read_image()
            if image is None:
                self.pasted_text = clipboard.read_text()
                self.notice = 'Текст из буфера добавлен' if self.pasted_text else 'В буфере нет изображения или текста'
                return False
            item = self.draft.add_image(image.name, image.data)
            self.notice = 'Добавлено ' + self.describe(self.draft.number_of(item), item)
            return True
        except (ClipboardError, ValueError, OSError) as error:
            # Ошибка не содержит байтов, stderr дочернего процесса и секретов.
            self.notice = safe_label(str(error))
            return False

    def paste_key(self, event):
        self.draft.text = event.current_buffer.text
        self.paste()
        if self.pasted_text:
            self.insert(event.current_buffer, self.pasted_text)
            self.draft.text = event.current_buffer.text
        event.app.invalidate()

    def insert(self, buffer, text: str):
        if is_large(text):
            block = self.draft.add_paste(text)
            buffer.insert_text(block.token)
            self.notice = 'Добавлена ' + self.describe(self.draft.number_of(block), block)
        else:
            buffer.insert_text(text)

    def bracketed_paste(self, event):
        self.insert(event.current_buffer, event.data)
        self.draft.text = event.current_buffer.text
        event.app.invalidate()

    def describe(self, number: int, item) -> str:
        if isinstance(item, ImageAttachment):
            description = f'изображение {item.name} · {item.width}×{item.height} · {len(item.data)} Б'
        elif isinstance(item, tuple):
            description = f'файл {item[0]} · {len(item[1].splitlines())} строк · {len(item[1].encode("utf-8"))} Б'
        else:
            description = f'вставка · {len(item.text)} символов'
        return f'#{number} — {safe_label(description)}'

    def listing(self) -> str:
        items = self.draft.items()
        if not items:
            return 'Вложений нет. Ctrl+V — вставить; @file:1-20 — добавить строки файла.'
        return '\n'.join(self.describe(number, item) for number, item in items) + '\n/show N · /edit N · /remove N'

    def close(self) -> str | None:
        from .text_editor import cleanup_pending
        warnings = [self.preview.close(), cleanup_pending()]
        return "\n".join(message for message in warnings if message) or None

    def take_notice(self) -> str:
        self.preview.prune({image.id for image in self.draft.images})
        result, self.notice = self.notice, ''
        return result

    def status(self):
        if self.notice:
            return self.notice
        count = len(self.draft.items())
        return f'Вложений: {count} · /attachments — список · /remove N — удалить' if count else ''

    def command(self, text: str) -> bool:
        self.notice = ''
        parts = text.split()
        action = parts[0] if parts else ''
        aliases = {'/paste-show': '/show', '/paste-edit': '/edit',
                   '/paste-remove': '/remove', '/remove-file': '/remove'}
        action = aliases.get(action, action)
        if action in {'/show', '/edit', '/remove'}:
            if not self.draft.items():
                self.notice = self.listing()
                return True
            try:
                if len(parts) == 1 and action != '/remove' and len(self.draft.items()) == 1:
                    number, item = self.draft.items()[0]
                elif len(parts) == 2:
                    value = parts[1].removeprefix('#')
                    if not value.isdecimal():
                        raise ValueError(f'Нужен номер вложения. Список: /attachments')
                    number = int(value)
                    item = self.draft.item(number)
                else:
                    self.notice = self.listing() + f'\nВыберите номер: {action} {self.draft.items()[0][0]}'
                    return True
                label = self.describe(number, item)
                if action == '/remove':
                    self.draft.remove_number(number)
                    self.notice = f'Удалено {label}'
                elif isinstance(item, ImageAttachment):
                    if action == '/show':
                        self.preview.show(item)
                        self.notice = f'Открываю {label} в системном просмотрщике.'
                    else:
                        self.notice = 'Изображение нельзя редактировать как текст. Просмотр: /show ' + str(number)
                else:
                    content = item[1] if isinstance(item, tuple) else item.text
                    if action == '/show':
                        view_text(content)
                        self.notice = f'Просмотр закрыт: {label}'
                    else:
                        replacement = edit_text(content)
                        self.draft.replace_text(number, replacement)
                        self.notice = f'Изменено {self.describe(number, self.draft.item(number))}. Отправка — Enter.'
            except ValueError as error:
                self.notice = str(error)
            except (KeyboardInterrupt, EOFError):
                self.notice = 'Редактирование отменено; содержимое сохранено.'
        elif action == '/paste':
            if len(parts) != 1:
                self.notice = 'Использование: /paste без аргументов'
                return True
            self.paste()
            if self.pasted_text:
                if is_large(self.pasted_text):
                    block = self.draft.add_paste(self.pasted_text)
                    self.draft.text += block.token
                    self.notice = 'Добавлена ' + self.describe(self.draft.number_of(block), block)
                else:
                    self.draft.text += self.pasted_text
        elif action == '/attachments':
            self.notice = self.listing() if len(parts) == 1 else 'Использование: /attachments без аргументов'
        else:
            return False
        return True
