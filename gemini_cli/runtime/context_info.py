"""Shared accounting for the actual built local/server context request."""
import json
import math


def _shape(value):
    """Return JSON-like text shape and whether counting needs media support."""
    if isinstance(value, bytes):
        return "", True
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        result, media = {}, False
        for key, child in value.items():
            shaped, nested = _shape(child)
            result[key] = shaped
            media |= nested or key in ("inline_data", "file_data", "images") and bool(child)
        return result, media
    if isinstance(value, (list, tuple)):
        pairs = [_shape(child) for child in value]
        return [child for child, _ in pairs], any(media for _, media in pairs)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, False
    return "", True


def estimate_context(history, info=None, instruction="", tools=None, *,
                     measured_usage=None) -> dict:
    """Use current-request counts, or a labelled characters/4 heuristic.

    `history` is contents actually sent after trimming/redaction/conversion.
    `measured_usage` must describe this exact request, never a previous turn.
    Media without measured counts stays unknown; limits aren't guessed.
    """
    info = info or {}
    shape, media = _shape({"contents": history, "system_instruction": instruction,
                           "tools": tools or []})
    text_estimate = math.ceil(len(json.dumps(shape, ensure_ascii=False)) / 4)
    measured = (measured_usage or {}).get("prompt_token_count")
    valid = type(measured) is int and measured >= 0
    tokens = measured if valid else (None if media else text_estimate)
    limit = info.get("input_token_limit")
    limit = limit if type(limit) is int and limit > 0 else None
    output = info.get("output_token_limit")
    output = output if type(output) is int and output > 0 else None
    return {"model": info.get("model"), "input_tokens": tokens,
            "input_token_limit": limit, "output_token_limit": output,
            "remaining_tokens": max(0, limit - tokens) if limit is not None and tokens is not None else None,
            "source": ((measured_usage or {}).get("source", "provider_usage") if valid
                       else "unavailable" if media else "estimate"),
            "estimated": not valid, "text_estimated_tokens": text_estimate,
            "has_unmeasured_media": media and not valid}
