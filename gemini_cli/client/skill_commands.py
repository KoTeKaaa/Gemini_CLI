"""Выбор одного навыка пользователем, без автоматических триггеров и LLM."""
import shlex

from .input import result_panel, safe_label
from ..integrations.skills import catalog
from ..protocol.skills import validate_skill

USAGE = ('/skill — каталог и активный навык\n/skill use имя — выбрать навык\n'
         '/skill off — отключить навык\nПример: /skill use code-review\n'
         'Каталоги задаются явно в приватном skills.json CLI.')


class Selection:
    def __init__(self, config):
        self.config = config
        self.scope = None
        self.skill = self.context = None

    def bind(self, scope):
        if scope != self.scope:
            self.clear()
            self.scope = scope
        return self

    def clear(self):
        self.skill = self.context = None

    def choices(self):
        try:
            return tuple(catalog(self.config)[0])
        except (ValueError, OSError):
            return ()

    def choose(self, name):
        found, _ = catalog(self.config)
        if name not in found:
            raise ValueError('Навык не найден или неоднозначен')
        skill = found[name]
        context = {'name': skill.name, 'content': skill.load()}
        validate_skill(context)
        self.skill, self.context = skill, context

    def payload(self):
        return dict(self.context) if self.context else None


def command(text, selection, *, console):
    try:
        parts = shlex.split(text)
        if parts in (['/skill'], ['/skill', 'list']):
            found, errors = catalog(selection.config)
            lines = [f'{name}: {safe_label(skill.description)}' for name, skill in sorted(found.items())]
            lines.extend(errors)
            active = selection.skill.name if selection.skill else 'нет'
            console.print(result_panel(f'Активный навык: {active}\n' + '\n'.join(lines or ['Навыков нет.'])
                                       + '\n\n' + USAGE, title='Skills'))
        elif parts == ['/skill', 'off']:
            selection.clear()
            console.print(result_panel('Навык отключён.', title='Skills'))
        elif len(parts) == 3 and parts[:2] == ['/skill', 'use']:
            selection.choose(parts[2])
            console.print(result_panel(f'Выбран навык: {selection.skill.name}. Инструкции пользователя имеют приоритет.\n'
                                       'Текст навыка будет отправлен вместе со следующим сообщением.', title='Skills'))
        else:
            raise ValueError('Неверная команда')
    except (ValueError, OSError, KeyboardInterrupt):
        console.print(result_panel('Навык не изменён: проверьте команду, skills.json и доступность SKILL.md.\n\n'
                                   + USAGE, title='Skills', error=True))
