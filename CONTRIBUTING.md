# Помочь проекту / Contributing

## По-русски

Можно начать с ошибки, неточного объяснения в документации или небольшого
улучшения привычного сценария. Не нужно сразу приносить большой PR.

### Ошибка или идея

Создайте [issue](https://github.com/KoTeKaaa/Gemini_CLI/issues/new/choose).
Для ошибки нужны версия (`gemini-cli --version`), ОС, режим Local/Remote,
короткие шаги и разница между ожидаемым и фактическим результатом.
Для идеи — задача, которую сейчас неудобно решать, и желаемое поведение.
По-русски и по-английски одинаково удобно.

Не прикладывайте ключи, сессии, `.env`, целые логи, личные пути, адрес своего
сервера или переписку. Достаточно минимального обезличенного примера.
Об уязвимостях сообщайте по [правилам безопасности](SECURITY.md).

### Изменение кода или документации

Обсудите крупную идею до реализации. Сделайте отдельную ветку от актуального
`dev` и PR в `dev`, оставив в нём одну понятную задачу. Объясните, что изменилось
для пользователя и почему. Для изменения поведения добавьте проверку регрессии.

Для узкой проверки выберите модуль:

```sh
python -B -m unittest tests.test_document_worker -q
```

Для общей регрессии в окружении с `requirements.txt` и `httpx`:

```sh
python -B -m unittest discover -s tests -p 'test_*.py' -q
git diff --check
```

Указывайте только действительно выполненные проверки. Документации достаточно
проверки ссылок, примеров и корректности текста; повторять сборку ради опечатки не нужно.
Не добавляйте сборки, локальные настройки, отчёты приёмки или личные файлы.

Текст важен так же, как код: пишите прямо, показывайте реальный сценарий и не
обещайте проверок, платформ или возможностей, которых пока нет. При изменении
руководства обновите обе языковые версии либо явно отметьте, где перевод отстал.

### Права на вклад

Вы сохраняете авторские права на свой вклад. Отправляя его, вы предлагаете его
под текущей лицензией проекта — [MIT с Commons Clause](LICENSE), не передавая
исключительные права владельцу репозитория. Отдельные коммерческие права не
возникают автоматически; если они нужны, их следует согласовать до слияния.

## English

Start with a bug, an unclear explanation or a small improvement to a workflow.
For a [bug report](https://github.com/KoTeKaaa/Gemini_CLI/issues/new/choose), include
version, OS, Local/Remote mode, minimal steps and expected versus actual behavior.
For an idea, describe the task and what currently gets in the way. Russian and
English reports are both welcome.

Never attach keys, session files, `.env`, full logs, private paths, server addresses
or chat history. Use a small sanitized example. Follow [SECURITY.md](SECURITY.md)
for vulnerability reports instead of publishing exploit details.

Discuss large changes first. Branch from current `dev`, target `dev` and keep a
PR focused on one task. Explain the user-visible result and why it is useful.
Behavior changes need regression coverage; the commands above show focused/full
unittest checks. Report only checks actually run. Documentation edits need link,
example and text verification, not an unnecessary executable rebuild.

Keep builds, personal configuration and internal acceptance reports out of PRs.
Update both language versions when practical, or point out a translation gap.
Write concrete instructions and keep unverified claims out of the documentation.

You retain copyright in your contributions and offer them under the current
[MIT with Commons Clause](LICENSE). This does not assign copyright or automatically
grant the maintainer separate commercial rights. Agree on such rights explicitly
before merging when needed.
