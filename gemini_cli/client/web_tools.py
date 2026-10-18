"""Бюджет поиска и кэш принадлежат одному исходному сообщению CLI."""

import json
from dataclasses import dataclass, field

from ..tools.results import failure


@dataclass
class ToolTurn:
    searches: int = 0
    disabled: bool = False
    cache: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)

    @property
    def search_available(self) -> bool:
        return self.searches < 3 and not self.disabled

    def search(self, args: dict, request) -> str:
        query, count = args.get("query"), args.get("max_results", 5)
        if not isinstance(query, str) or not query.strip() or type(count) is not int or not 1 <= count <= 5:
            return json.dumps(failure("invalid_arguments", "Некорректный запрос поиска"))
        key = (query.strip(), count)
        if key in self.cache:
            return self.cache[key]
        if not self.search_available:
            return json.dumps(failure("budget", "Поиск завершён для этого сообщения; отвечайте по доступным данным"))
        self.searches += 1
        result = request("search", {"query": key[0], "max_results": count})
        if result.get("status") == "error":
            self.disabled = True
        self.cache[key] = json.dumps(result, ensure_ascii=False)
        return self.cache[key]

    def report(self, kind: str, result: dict, notify) -> None:
        if result.get("status") != "ok":
            notify("Веб-инструмент не выполнен; причина передана модели.")
            return
        data = result.get("data", {})
        items = data.get("results", []) if kind == "search" else [data]
        for item in items:
            url = item.get("url") if kind == "search" else item.get("final_url", item.get("url"))
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            key = (kind, url)
            if key not in self.sources:
                self.sources[key] = item.get("title", "")
                label = "Найден источник" if kind == "search" else "Прочитан источник"
                notify(f"{label}: {url}")
        if result.get("truncated"):
            notify("Текст источника усечён по лимиту.")

    def read(self, args: dict, request) -> str:
        url = args.get("url")
        if not isinstance(url, str) or not url:
            return json.dumps(failure("invalid_arguments", "Не указан URL"))
        return json.dumps(request("read", {"url": url}), ensure_ascii=False)
