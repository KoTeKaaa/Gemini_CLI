"""Мастер проверяет доступ без пробной генерации и меняет ключи после проверок."""

from .secrets import KeyStorageUnavailable, SecretStore
from ..protocol.models import MODEL_IDS


def validate_gemini(key: str) -> bool:
    from ..backends.genai import create_provider
    provider = create_provider(key)
    try:
        provider.models.get(model=MODEL_IDS[0])
        return True
    finally:
        provider.close()


def validate_tavily(key: str) -> bool:
    import requests
    with requests.Session() as session:
        session.trust_env = False
        with session.get("https://api.tavily.com/usage", headers={"Authorization": f"Bearer {key}"},
                         timeout=20, allow_redirects=False) as response:
            return response.status_code == 200


def configure_local(*, choose_storage, read_secret, notify, existing=None, profile="default",
                    gemini_check=validate_gemini, tavily_check=validate_tavily, store_factory=SecretStore):
    notify("Local отправляет личные ключи только провайдерам. Проверка доступа не генерирует ответ.")
    try:
        mode = choose_storage("Где хранить ключи? keyring — хранилище ОС; memory — только до закрытия CLI")
        if mode not in {"keyring", "memory"}:
            return None
        try:
            store = store_factory(profile, persistent=mode == "keyring")
            previous = {name: (existing or store).get(name) for name in ("gemini", "tavily")}
        except KeyStorageUnavailable:
            notify("Хранилище ОС недоступно. Записи в JSON/.env не будет.")
            if choose_storage("Продолжить только в памяти? Выберите memory или отмену") != "memory":
                return None
            store = store_factory(profile, persistent=False)
            previous = {"gemini": None, "tavily": None}
        gemini = read_secret("Gemini API key (Enter — оставить прежний): ")
        if gemini is None:
            return None
        gemini = gemini.strip() or previous["gemini"]
        if not gemini:
            notify("Для Local нужен личный Gemini API key")
            return None
        tavily = read_secret("Tavily key (необязательно; Enter — оставить, '-' — удалить): ")
        if tavily is None:
            return None
        tavily = None if tavily.strip() == "-" else tavily.strip() or previous["tavily"]
        if not gemini_check(gemini) or (tavily and not tavily_check(tavily)):
            notify("Проверка доступа не пройдена. Прежние ключи сохранены.")
            return None
        store.set("gemini", gemini)
        if tavily:
            store.set("tavily", tavily)
        elif previous["tavily"]:
            store.delete("tavily")
        notify("Ключи сохранены в хранилище ОС" if store.mode == "keyring"
               else "Ключи только в памяти до закрытия приложения")
        return store
    except (KeyboardInterrupt, EOFError):
        return None
    except KeyStorageUnavailable:
        notify("Сохранение ключей не подтверждено. Прежний режим остаётся активным.")
        return None
    except Exception as error:
        code = getattr(error, "code", None)
        notify("Провайдер ограничил проверку квотой; попробуйте позже" if code == 429
               else "Не удалось проверить ключ или сеть. Прежние ключи сохранены.")
        return None
