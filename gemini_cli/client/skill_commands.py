"""Выбор одного навыка пользователем, без автоматических триггеров и LLM."""
import shlex
import json

from .input import result_panel, safe_label
from ..integrations.skills import catalog
from ..protocol.skills import validate_skill

USAGE = ('/skill help — пошаговый гайд: создание SKILL.md, настройка и использование\n'
         '/skill — каталог и активный навык\n/skill use имя — выбрать навык\n'
         '/skill off — отключить навык\n/skill read путь — добавить ресурс к контексту навыка\n'
         '/skill show путь — только просмотреть файл\n/skill run scripts/файл — запустить после просмотра и подтверждения\n'
         '/skill output — открыть последний вывод скрипта локально\n'
         'Пример: /skill use code-review → /skill show scripts/check.py\n'
         'Каталоги задаются явно в приватном skills.json CLI.')


class Selection:
    def __init__(self, config):
        self.config = config
        self.scope = None
        self.skill = self.context = None
        self.resources, self.viewed, self.base_content = {}, {}, ''
        self.last_output = ''

    def bind(self, scope):
        if scope != self.scope:
            self.clear()
            self.scope = scope
        return self

    def clear(self):
        self.skill = self.context = None
        self.resources, self.viewed, self.base_content = {}, {}, ''
        self.last_output = ''

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
        self.clear()
        self.base_content = context['content']
        self.skill, self.context = skill, context

    def payload(self):
        return dict(self.context) if self.context else None


def command(text, selection, *, console, viewer=None, run_script=None):
    try:
        parts = shlex.split(text)
        if parts == ['/skill', 'help']:
            from .integration_help import show_guide
            show_guide('skill')
            return
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
        elif parts == ['/skill', 'output'] and viewer is not None:
            viewer(selection.last_output or 'Вывода скрипта пока нет.')
        elif len(parts) == 3 and parts[:2] == ['/skill', 'use']:
            selection.choose(parts[2])
            console.print(result_panel(f'Выбран навык: {selection.skill.name}. Инструкции пользователя имеют приоритет.\n'
                                       'Текст навыка будет отправлен вместе со следующим сообщением.', title='Skills'))
        elif len(parts) == 3 and parts[1] in {'show', 'read', 'run'}:
            from .skill_resources import show, read
            action, relative = parts[1:]
            if action == 'show' and viewer is not None:
                show(selection, relative, viewer)
                message = 'Файл просмотрен локально; содержимое не добавлено к запросу.'
            elif action == 'read':
                read(selection, relative)
                message = 'Ресурс добавлен к выбранному навыку для следующих сообщений.'
            elif action == 'run' and run_script is not None:
                result = run_script(selection, relative)
                selection.last_output = str(result)[-131072:]
                try:
                    data = json.loads(result)
                    selection.last_output = '\n'.join(str(data.get(key, '')) for key in ('error', 'stdout', 'stderr'))[-65536:]
                    message = ('Скрипт завершён.' if data.get('status') == 'completed' and data.get('exit_code') == 0
                               else 'Скрипт не завершён успешно: отмена, ошибка или конфликт. Выполните /skill show заново.')
                    message += ' Вывод: /skill output (локально).'
                except (ValueError, TypeError):
                    message = 'Запуск скрипта отменён.'
            else:
                raise ValueError('Действие недоступно')
            console.print(result_panel(message, title='Skills'))
        else:
            raise ValueError('Неверная команда')
    except (ValueError, OSError, KeyboardInterrupt):
        console.print(result_panel('Навык не изменён: проверьте команду, skills.json и доступность SKILL.md.\n\n'
                                   + USAGE, title='Skills', error=True))
