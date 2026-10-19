"""Действия черновика: клавиши не отправляют запрос и не запускают backend."""

from prompt_toolkit.key_binding import KeyBindings
from .paste import PasteBlock, is_large, view_text, edit_text
from prompt_toolkit.keys import Keys
from .clipboard import get_clipboard, ClipboardError


def safe_label(text: str) -> str:
    return ''.join(char if char.isprintable() else '?' for char in text)


class DraftInput:
    def __init__(self, draft, clipboard_factory=None):
        self.draft = draft
        self.clipboard_factory = clipboard_factory or get_clipboard
        self.notice = ''
        self.pasted_text = None
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
            self.draft.add_image(image.name, image.data)
            self.notice = 'Изображение добавлено; отправка только по Enter'
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
            block = PasteBlock.create(text)
            self.draft.pastes.append(block)
            buffer.insert_text(block.token)
        else:
            buffer.insert_text(text)

    def bracketed_paste(self, event):
        self.insert(event.current_buffer, event.data)
        self.draft.text = event.current_buffer.text
        event.app.invalidate()

    def status(self):
        images = ' | '.join(f'{index}: {safe_label(image.name)} ({len(image.data)} Б)'
                            for index, image in enumerate(self.draft.images, 1))
        files = ' | '.join(f'текст {index}: {safe_label(name)}' for index, (name, _) in enumerate(self.draft.files, 1))
        pastes = ' | '.join(f'вставка {index}: {len(block.text)} символов' for index, block in enumerate(self.draft.pastes, 1))
        return f'{images} {files} {pastes}  {self.notice}'.strip()

    def command(self, text: str) -> bool:
        if text.startswith(('/paste-show ', '/paste-edit ', '/paste-remove ')):
            try:
                action, number = text.split()
                index = int(number) - 1
                if index < 0:
                    raise ValueError()
                block = self.draft.pastes[index]
                if action == '/paste-show':
                    view_text(block.text)
                elif action == '/paste-edit':
                    block.text = edit_text(block.text)
                else:
                    self.draft.text = self.draft.text.replace(block.token, '')
                    self.draft.pastes.pop(index)
            except (ValueError, IndexError):
                self.notice = 'Укажите номер вставки из строки состояния'
            except (KeyboardInterrupt, EOFError):
                self.notice = 'Редактирование отменено'
        elif text == '/paste':
            self.paste()
            if self.pasted_text:
                if is_large(self.pasted_text):
                    block = PasteBlock.create(self.pasted_text)
                    self.draft.pastes.append(block)
                    self.draft.text += block.token
                else:
                    self.draft.text += self.pasted_text
        elif text == '/attachments':
            self.notice = 'Удалить: /remove НОМЕР'
        elif text.startswith('/remove-file '):
            try:
                index = int(text.split()[1]) - 1
                if index < 0:
                    raise ValueError()
                self.draft.files.pop(index)
            except (ValueError, IndexError):
                self.notice = 'Укажите номер текстового вложения'
        elif text.startswith('/remove '):
            try:
                number = int(text.split()[1])
                if not 1 <= number <= len(self.draft.images):
                    raise ValueError()
                self.draft.remove(self.draft.images[number - 1].id)
                self.notice = 'Вложение удалено'
            except (ValueError, IndexError):
                self.notice = 'Укажите номер из /attachments'
        else:
            return False
        return True
