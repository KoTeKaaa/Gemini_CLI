"""Однократный запрос Tavily Basic без повторов и платного fallback."""

import requests

from ..results import failure, success


def search(query: str, max_results: int = 5, *, api_key: str | None) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        return failure("invalid_arguments", "Нужен непустой поисковый запрос до 2000 символов")
    if type(max_results) is not int or not 1 <= max_results <= 5:
        return failure("invalid_arguments", "Допустимо от 1 до 5 результатов")
    if not api_key:
        return failure("unavailable", "Веб-поиск не настроен на сервере")
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query.strip(), "max_results": max_results,
                      "search_depth": "basic", "auto_parameters": False,
                      "include_answer": False, "include_raw_content": False},
                timeout=20, allow_redirects=False,
            )
            with response:
                if response.status_code in (402, 429, 432, 433):
                    return failure("quota", "Поиск ограничен квотой или частотой запросов")
                if response.status_code in (401, 403):
                    return failure("unavailable", "Поиск недоступен: проверьте серверную конфигурацию")
                if response.status_code != 200:
                    return failure("provider_error", "Сервис поиска вернул ошибку")
                payload = response.json()
        items = payload["results"]
        if not isinstance(items, list):
            raise ValueError("Invalid results")
        results = []
        for item in items[:max_results]:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str)
                                                    for key in ("title", "url", "content")):
                raise ValueError("Invalid search item")
            if not item["url"].startswith(("https://", "http://")):
                continue
            results.append({"title": item["title"][:500], "url": item["url"][:2048],
                            "snippet": item["content"][:2000]})
        return success({"results": results})
    except requests.Timeout:
        return failure("timeout", "Поиск не завершился вовремя; автоматического повтора нет")
    except requests.RequestException:
        return failure("network", "Не удалось связаться с сервисом поиска")
    except (ValueError, KeyError, TypeError):
        return failure("invalid_response", "Некорректный ответ сервиса поиска")
