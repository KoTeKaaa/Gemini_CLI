"""Временные startup-файлы: профили пользователя остаются на месте."""

import os
from pathlib import Path
import shlex


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def shell_command(executable: str, root: Path, returned: Path) -> tuple[list[str], dict[str, str]]:
    environment = os.environ.copy()
    name = Path(executable).stem.lower()
    if name in {'pwsh', 'powershell'}:
        # -Command загружается после обычных профилей; UTF8 без BOM и без смены codepage родителя.
        script = """function global:exit-to-cli {
    if ($args.Count -eq 1 -and $args[0] -ceq '--sync-dir') {
        if ((Get-Location).Provider.Name -ne 'FileSystem') {
            Write-Host 'Текущий путь не является каталогом файловой системы'; return
        }
        try {
            [IO.File]::WriteAllText(RETURN_PATH, (Get-Location).ProviderPath, [Text.UTF8Encoding]::new($false))
        } catch { Write-Host 'Не удалось передать каталог'; return }
    } elseif ($args.Count -ne 0) {
        Write-Host 'exit-to-cli [--sync-dir]'; return
    }
    exit
}
""".replace('RETURN_PATH', powershell_literal(str(returned)))
        # ASCII -EncodedCommand избегает ограничений -File/ExecutionPolicy и кодировки argv.
        import base64
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return [executable, '-NoLogo', '-NoExit', '-EncodedCommand', encoded], environment

    function = """
function exit-to-cli() {
    if [ "$#" -eq 1 ] && [ "$1" = '--sync-dir' ]; then
JOB_GUARD
        builtin printf '%s' "$PWD" > RETURN_PATH || { builtin printf '%s\n' 'Не удалось передать каталог'; return 1; }
    elif [ "$#" -ne 0 ]; then
        builtin printf '%s\n' 'exit-to-cli [--sync-dir]'; return 2
    fi
    builtin exit
    # Bash может отказать в выходе при остановленных задачах.
    # Пустая запись отменяет запрос синхронизации до следующего выхода.
    builtin printf '%s' '' > RETURN_PATH
}
""".replace('RETURN_PATH', shlex.quote(str(returned)))
    # zsh прерывает функцию при отказе exit; cleanup после exit тогда не выполняется.
    guard = """        if [ -n "$(jobs -p)" ]; then
            builtin printf '%s\\n' 'Сначала завершите задачи или отсоедините их через disown; workspace не передан.'
            return 1
        fi""" if name == 'zsh' else ''
    function = function.replace('JOB_GUARD', guard)
    if name == 'bash':
        startup = root / 'bashrc'
        startup.write_text('[ ! -f ~/.bashrc ] || . ~/.bashrc\n' + function, encoding='utf-8')
        return [executable, '--rcfile', str(startup), '-i'], environment
    if name != 'zsh':
        raise ValueError('Поддерживаются Bash, zsh и PowerShell.')
    original = environment.get('ZDOTDIR')
    profile_root = Path(original or Path.home())
    # ZDOTDIR направлен на временные файлы только во время инициализации ребёнка.
    restore = ('unset ZDOTDIR' if original is None else 'export ZDOTDIR=' + shlex.quote(original))
    (root / '.zshenv').write_text(
        restore + '\n[[ ! -f ' + shlex.quote(str(profile_root / '.zshenv')) + ' ]] || source '
        + shlex.quote(str(profile_root / '.zshenv'))
        + '\ntypeset -g __gemini_zdotdir_set=${+ZDOTDIR}\n'
        + 'typeset -g __gemini_zdotdir=${ZDOTDIR-}\nexport ZDOTDIR='
        + shlex.quote(str(root)) + '\n', encoding='utf-8')
    (root / '.zshrc').write_text(
        'if (( __gemini_zdotdir_set )); then export ZDOTDIR="$__gemini_zdotdir"; '
        'else unset ZDOTDIR; fi\nunset __gemini_zdotdir_set __gemini_zdotdir\n'
        '[[ ! -f ${ZDOTDIR:-$HOME}/.zshrc ]] || source "${ZDOTDIR:-$HOME}/.zshrc"\n'
        + function, encoding='utf-8')
    environment['ZDOTDIR'] = str(root)
    return [executable, '-i'], environment
