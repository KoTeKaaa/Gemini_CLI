"""Только системный credential backend либо явно выбранная память процесса."""

import hashlib
import sys


class KeyStorageUnavailable(RuntimeError):
    pass


def system_backend():
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring
            backend = WinVaultKeyring()
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring
            backend = Keyring()
        else:
            raise KeyStorageUnavailable()
        if backend.priority <= 0:
            raise KeyStorageUnavailable()
        return backend
    except Exception:
        raise KeyStorageUnavailable("Защищённое хранилище ОС недоступно или заблокировано") from None


class SecretStore:
    def __init__(self, profile="default", *, persistent=False, backend_factory=system_backend):
        self.service = "gemini_cli.local." + hashlib.sha256(profile.encode()).hexdigest()
        self.backend = backend_factory() if persistent else None
        self.memory = {}
        self.mode = "keyring" if persistent else "memory"

    def validate_provider(self, provider):
        if provider not in {"gemini", "tavily"}:
            raise ValueError("Неизвестный провайдер ключа")

    def get(self, provider: str) -> str | None:
        self.validate_provider(provider)
        if provider in self.memory:
            return self.memory[provider]
        if self.backend is None:
            return None
        try:
            return self.backend.get_password(self.service, provider)
        except Exception:
            raise KeyStorageUnavailable("Не удалось прочитать ключ из хранилища ОС") from None

    def set(self, provider: str, value: str):
        self.validate_provider(provider)
        if not isinstance(value, str) or not value:
            raise ValueError("Ключ не должен быть пустым")
        if self.backend is not None:
            try:
                self.backend.set_password(self.service, provider, value)
            except Exception:
                raise KeyStorageUnavailable("Не удалось сохранить ключ в хранилище ОС") from None
        self.memory[provider] = value

    def delete(self, provider: str):
        self.validate_provider(provider)
        if self.backend is not None:
            try:
                if self.backend.get_password(self.service, provider) is not None:
                    self.backend.delete_password(self.service, provider)
            except Exception:
                raise KeyStorageUnavailable("Не удалось удалить ключ из хранилища ОС") from None
        self.memory.pop(provider, None)

    def close(self):
        self.memory.clear()
