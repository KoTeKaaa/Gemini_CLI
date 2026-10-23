"""Ресурсы по явному пути; скрипты — из просмотренного снимка через общий процесс."""
from contextlib import nullcontext
import logging
from pathlib import Path
import shutil
import sys
import tempfile

from ..integrations.skills import checked_path
from ..tools.local.workspace import plan_text_file, read_text_snapshot
from ..tools.local.command import execute_command


def snapshot(skill, relative):
    path = checked_path(skill.root, relative)
    expected = plan_text_file(str(skill.root), relative, max_bytes=65536)
    text = read_text_snapshot(str(skill.root), relative, expected, max_bytes=65536)
    if checked_path(skill.root, relative) != path:
        raise ValueError('Файл изменился')
    return expected, text


def show(selection, relative, viewer):
    if selection.skill is None:
        raise ValueError('Сначала выберите навык')
    expected, text = snapshot(selection.skill, relative)
    viewer(text)
    selection.viewed[relative] = (expected, text)


def read(selection, relative):
    if selection.skill is None:
        raise ValueError('Сначала выберите навык')
    _, text = snapshot(selection.skill, relative)
    resources = {**selection.resources, relative: text}
    context = {'name': selection.skill.name, 'content': selection.base_content + ''.join(
        f'\n\nРесурс навыка {path}:\n{body}' for path, body in resources.items())}
    from ..protocol.skills import validate_skill
    validate_skill(context)
    selection.resources, selection.context = resources, context


def run(selection, relative, cwd, *, approve, cancelled=lambda: False, notify=lambda _: None,
        on_process=None, monitor=nullcontext):
    if selection.skill is None or relative not in selection.viewed or not relative.startswith('scripts/'):
        raise ValueError('Сначала /skill show scripts/файл; затем /skill run scripts/файл')
    expected, text = selection.viewed[relative]
    suffix = Path(relative).suffix
    runtime = {'.sh': 'bash', '.ps1': 'pwsh', '.py': 'python' if sys.platform == 'win32' else 'python3'}.get(suffix)
    executable = sys.executable if suffix == '.py' and not getattr(sys, 'frozen', False) else shutil.which(runtime or '')
    if not executable:
        raise ValueError('Нужен установленный Python/Bash/PowerShell для выбранного скрипта')
    def preflight():
        if snapshot(selection.skill, relative) != (expected, text):
            raise ValueError('Скрипт изменился после просмотра')
    # The owned private copy closes the view/approve/execute race. Nothing is
    # written into the workspace, history or the original skill directory.
    with tempfile.TemporaryDirectory(prefix='gemini-skill-') as tmp:
        script = Path(tmp) / ('script' + suffix)
        script.write_bytes(text.encode('utf-8'))
        argv = [executable, *(['-NoProfile', '-File'] if suffix == '.ps1' else []), str(script)]
        return execute_command({'command': f'Навык {selection.skill.name}: {relative} ({runtime}); cwd={cwd}'},
            cwd, argv=argv, preflight=preflight, approve=approve, notify=notify,
            logger=logging.getLogger('gemini_cli'), cancelled=cancelled,
            on_process=on_process, monitor=monitor)
