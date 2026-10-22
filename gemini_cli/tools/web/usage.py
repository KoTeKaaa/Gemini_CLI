"""Read-only Tavily Usage без поиска, повторов и платного fallback."""

import time

import requests

from ...protocol.quotas import Quota, number, unavailable


def tavily_usage(api_key: str | None, scope: str, *, transport=requests, clock=time.time) -> list[dict]:
    now = clock()
    def failed(reason):
        return [unavailable("tavily", scope, reason, fetched_at=now)]
    if not api_key:
        return failed("key_missing")
    try:
        with transport.get("https://api.tavily.com/usage",
                           headers={"Authorization": "Bearer " + api_key},
                           timeout=(5, 10), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                return failed({401: "auth_required", 429: "rate_limited"}.get(
                    response.status_code, "provider_unavailable"))
            data = bytearray()
            for chunk in response.iter_content(4096):
                data.extend(chunk)
                if len(data) > 65536:
                    return failed("invalid_response")
            import json
            data = json.loads(data)
        account, key = data["account"], data["key"]
        tier = account.get("current_plan")
        if not isinstance(tier, str) or len(tier) > 80:
            return failed("invalid_response")
        common = dict(provider="tavily", tier=tier, unit="credits", window="month",
                      fetched_at=now)
        rows = [Quota(scope=scope + "/account", limit=account.get("plan_limit"),
                      used=account.get("plan_usage"), **common).wire(),
                Quota(scope=scope + "/key", limit=key.get("limit"),
                      used=key.get("usage"), **common).wire()]
        # Only a confirmed free plan can supply a free-policy budget.
        free = tier.casefold() in {"researcher", "free"}
        remaining = rows[0]["remaining"] if free else None
        key_limit, key_used = number(key.get("limit")), number(key.get("usage"))
        if key.get("limit") is not None and (key_limit is None or key_used is None):
            remaining = None
        elif remaining is not None and key_limit is not None:
            remaining = min(remaining, max(0, key_limit - key_used))
        rows[0]["free_remaining"] = remaining
        rows[0]["policy_reason"] = None if remaining is not None else "free_budget_unknown"
        return rows
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return failed("provider_unavailable")
