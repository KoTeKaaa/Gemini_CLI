# Безопасность / Security

## По-русски

Если ошибка позволяет прочитать чужой чат, обойти подтверждение, раскрыть ключ
или выполнить непредусмотренное действие, не публикуйте детали в обычном issue.

Используйте **Security → Report a vulnerability**, если приватная форма доступна
в репозитории. Если её нет, создайте issue с просьбой о приватном канале связи,
не прикладывая уязвимость, код эксплуатации или секреты. Это не обещание круглосуточной
поддержки или фиксированного срока ответа.

В приватном сообщении достаточно версии, затронутого режима/платформы, минимальных
шагов, ожидаемого результата и возможного влияния. Используйте фиктивные аккаунты
и файлы. Не проверяйте проблему на чужих данных и не присылайте действующие ключи.

Исправления готовятся для текущей линии разработки. Отдельные сроки поддержки
старых выпусков не объявлены; рекомендуется актуальная стабильная версия.

### Что стоит помнить при использовании

- Подтверждённая shell-команда имеет права вашего пользователя, а не только workspace.
- MCP, skills и language server подключайте только после просмотра конфигурации.
- Вложения становятся частью запроса к модели; выбирайте содержимое осознанно.
- Контрольные точки и локальная история имеют ограниченные права, но не шифруются.
- Сессии, ключи, `.env` и полные логи не должны попадать в issue или репозиторий.

## English

If an issue could expose another user's chat or keys, bypass approval or perform
an unintended action, do not publish the details in a normal issue.

Use **Security → Report a vulnerability** if private reporting is available.
Otherwise open an issue asking for a private contact channel without vulnerability
details, exploit code or secrets. No response-time or round-the-clock support
commitment is implied.

Privately share the version, mode/platform, minimal reproduction, expected result
and likely impact. Use disposable accounts and dummy files. Do not test against
other people's data or send live credentials.

Fixes target the current development line. No separate maintenance window is
promised for older versions; use the latest stable release where possible.

Approved shell commands have your user permissions beyond the workspace. Inspect
MCP/skill/LSP configuration before enabling it. Select attachments carefully: their
content is sent to the model. Local history and checkpoints are not encrypted.
Keep credentials, sessions, `.env` and full logs out of public reports.
