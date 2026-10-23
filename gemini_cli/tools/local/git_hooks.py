"""Делегировать все hooks Git, затем проверить дерево до обновления ссылки."""
from pathlib import Path
import os
import shlex


def reviewed_hooks(git, directory: str, tree: str) -> Path:
    original = Path(git.run(['rev-parse', '--path-format=absolute', '--git-path', 'hooks'])['stdout'].strip())
    target = Path(directory, 'hooks')
    target.mkdir()
    if original.is_dir():
        for hook in original.iterdir():
            if hook.is_file() and not hook.name.endswith('.sample') and os.access(hook, os.X_OK):
                wrapper = target / hook.name
                wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(hook)) + ' "$@"\n', encoding='utf-8')
                wrapper.chmod(0o755)
    reference = target / 'reference-transaction'
    previous = original / 'reference-transaction'
    delegate = ''
    if previous.is_file() and os.access(previous, os.X_OK):
        delegate = ('printf "%s\\n" "$updates" | ' + shlex.quote(str(previous)) + ' "$@"\n'
                    'result=$?\n[ "$result" = 0 ] || exit "$result"\n')
    # reference-transaction's prepared phase can reject a commit after pre-commit
    # and commit-msg, before HEAD changes. No installed hook is skipped.
    script = '''#!/bin/sh
updates=$(cat)
DELEGATE
[ "$1" = prepared ] || exit 0
printf "%s\\n" "$updates" | while read -r old new ref; do
    case "$ref" in HEAD|refs/heads/*)
        actual=$(git rev-parse "$new^{tree}") || exit 1
        if [ "$actual" != EXPECTED ]; then
            echo 'Reviewed selection changed by hook; commit rejected' >&2
            exit 1
        fi
        ;;
    esac
done
'''.replace('DELEGATE', delegate).replace('EXPECTED', shlex.quote(tree))
    reference.write_text(script, encoding='utf-8')
    reference.chmod(0o755)
    return target
