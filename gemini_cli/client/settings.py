"""Выбор backend меняется только после успешной настройки нового профиля."""

from .profiles import private_json, read_json
from .secrets import SecretStore, KeyStorageUnavailable
from .local_setup import configure_local


class Settings:
    def __init__(self, root, *, remote_factory, choose_mode, read_server, choose_storage, read_secret, notify):
        self.root, self.path = root, root / "settings.json"
        self.remote_factory, self.choose_mode, self.read_server = remote_factory, choose_mode, read_server
        self.choose_storage, self.read_secret, self.notify = choose_storage, read_secret, notify
        self.stores, self.backends = {}, []

    def configure(self, *, force=False):
        config = read_json(self.path)
        mode = config.get("mode")
        if force or not isinstance(mode, str) or mode not in {"local", "remote"}:
            mode = self.choose_mode()
        if not isinstance(mode, str) or mode not in {"local", "remote"}:
            return None
        try:
            if mode == "remote":
                previous = config.get("remote_origin")
                origin = self.read_server(previous if isinstance(previous, str) else None, force)
                if origin is None:
                    return None
                backend = self.remote_factory(origin)
                if not backend.login():
                    return None
                config["remote_origin"] = backend.base_url
            else:
                profile = "default"
                store = self.stores.get(profile)
                if store is None and not force and config.get("storage") == "keyring":
                    try:
                        store = SecretStore(profile, persistent=True)
                        if not store.get("gemini"):
                            store = None
                    except KeyStorageUnavailable:
                        self.notify("Хранилище ОС недоступно; выберите хранение явно в мастере")
                if force or store is None or not store.get("gemini"):
                    store = configure_local(choose_storage=self.choose_storage, read_secret=self.read_secret,
                                            notify=self.notify, existing=store, profile=profile)
                if store is None:
                    return None
                from ..backends.local import LocalBackend
                backend = LocalBackend(store.get("gemini"), self.root / "profiles", profile=profile,
                                       tavily_key=store.get("tavily"))
                self.stores[profile] = store
                config["storage"] = store.mode
            private_json(self.path, {key: value for key, value in {**config, "version": 1, "mode": mode}.items()
                                     if key in {"version", "mode", "remote_origin", "storage"}})
            self.backends.append(backend)
            self.notify(f"Активен режим {mode}")
            return backend
        except (ValueError, OSError, KeyStorageUnavailable):
            self.notify("Не удалось применить настройки; прежний backend остаётся активным")
            return None

    def close(self):
        for backend in self.backends:
            close = getattr(backend, "close", None)
            if close:
                close()
        for store in self.stores.values():
            store.close()


def backend_identity(backend):
    if backend.mode == "remote":
        return ("remote", backend.base_url, backend.account_id)
    return ("local", getattr(backend, "profile", "default"),
            str(getattr(getattr(backend, "chats", None), "path", "memory")))
