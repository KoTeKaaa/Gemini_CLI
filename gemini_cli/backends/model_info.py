"""Provider metadata; callers supply clients and opaque profile/project scopes."""
from collections import OrderedDict
from threading import Lock
from time import monotonic

_CACHE = OrderedDict()
_LOCK = Lock()
_CACHE_SECONDS = 300
_CACHE_LIMIT = 64


def _limit(value):
    return value if type(value) is int and value > 0 else None


def model_info(provider, model: str, cache_scope=None, *, refresh=False) -> dict:
    """Fetch model limits. Change scope with provider/profile credentials.

    Without an explicit scope results aren't cached. Never use an API key as scope.
    Cached values contain metadata only; failures expire like successes.
    """
    key = (cache_scope, model) if cache_scope is not None else None
    now = monotonic()
    with _LOCK:
        cached = _CACHE.get(key) if key is not None else None
        if not refresh and cached and now - cached[0] < _CACHE_SECONDS:
            _CACHE.move_to_end(key)
            return dict(cached[1])
    result = {"model": model, "input_token_limit": None,
              "output_token_limit": None, "source": "unavailable"}
    try:
        metadata = provider.models.get(model=model)
        result.update(input_token_limit=_limit(metadata.input_token_limit),
                      output_token_limit=_limit(metadata.output_token_limit),
                      source="provider")
    except Exception:
        # SDK errors may include private request details. Don't expose/store them.
        pass
    result["updated_at_monotonic"] = monotonic()
    if key is not None:
        with _LOCK:
            _CACHE[key] = (result["updated_at_monotonic"], dict(result))
            _CACHE.move_to_end(key)
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
    return result


def count_context(provider, model: str, contents, instruction="", tools=None) -> dict:
    """Count bare contents only; Developer API SDK rejects instruction/tools.

    Full request accounting remains a labelled estimate until the SDK can count
    every request field. Never present a partial count as an exact total.
    """
    if instruction or tools:
        return {"prompt_token_count": None, "source": "unavailable"}
    try:
        count = provider.models.count_tokens(model=model, contents=contents)
        total = count.total_tokens
        if type(total) is int and total >= 0:
            return {"prompt_token_count": total, "source": "provider_count"}
    except Exception:
        pass
    return {"prompt_token_count": None, "source": "unavailable"}
