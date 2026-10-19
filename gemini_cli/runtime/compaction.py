"""Prepare private-safe whole-turn summaries; storage remains adapter-owned."""
from copy import deepcopy
from hashlib import sha256
import json
import math

from .history import persistent_history_rows

MAX_SUMMARY_CHARS = 8192


def completed_turn(rows):
    if not rows or rows[0].get("role") != "user":
        return False
    if any(row.get("status", "legacy") not in (None, "legacy", "completed") for row in rows):
        return False
    pending = []
    for row in rows:
        if row.get("role") == "model" and row.get("name"):
            pending.append((row.get("name"), row.get("call_id")))
        elif row.get("role") == "tool":
            matches = [call for call in pending if call[0] == row.get("name")
                       and (row.get("call_id") is None or call[1] == row.get("call_id"))]
            if len(matches) != 1:
                return False
            pending.remove(matches[0])
    last = rows[-1]
    return (not pending and last.get("role") == "model" and not last.get("name")
            and isinstance(last.get("content"), str) and bool(last["content"].strip()))


def completed_boundaries(history):
    """Explicit completed turn ends for fork selection; legacy identity is unknown."""
    groups = []
    for row in history:
        if row.get("role") == "user" or not groups:
            groups.append([])
        groups[-1].append(row)
    return [dict(group[-1]) for group in groups if completed_turn(group)
            and all(row.get("status") == "completed" for row in group)
            and group[0].get("turn_id")
            and all(row.get("turn_id") == group[0]["turn_id"] for row in group)
            and (group[-1].get("id") or group[-1].get("event_id"))]


def prepare_compaction(history, *, keep_turns=2) -> dict:
    """Keep recent/unfinished turns intact; require a durable boundary event ID."""
    if type(keep_turns) is not int or keep_turns < 1:
        raise ValueError("keep_turns must be positive")
    groups = []
    for row in history:
        if row.get("role") == "user" or not groups:
            groups.append([])
        groups[-1].append(row)
    count = 0
    for group in groups[:-keep_turns]:
        if not completed_turn(group):
            break
        count += len(group)
    boundary = (history[count - 1].get("id") or history[count - 1].get("event_id")) if count else None
    if not boundary:
        return {"source": [], "boundary_id": None, "tail": deepcopy(history),
                "reason": "no_completed_boundary"}
    # Strip images/bytes and unknown metadata before the persistence redactor.
    rows = [{key: row.get(key) for key in ("role", "content", "name", "args", "call_id")}
            for row in history[:count]]
    # No tool arguments/results, including execute_command output, enter a summary.
    for row in rows:
        row["args"] = None
        if not isinstance(row.get("content"), str):
            row["content"] = ""
        if row.get("role") == "tool" or row.get("name"):
            row["content"] = "[tool details omitted]"
    source = persistent_history_rows(rows)
    for row in source:
        row.pop("thought_signature", None)
    return {"source": source, "boundary_id": boundary,
            "tail": deepcopy(history[count:]), "reason": "ready"}


def run_compaction(history, summarize, *, cancelled=lambda: False,
                   blocked_fingerprint=None, keep_turns=2) -> dict:
    """Generate a candidate only; pass a failed fingerprint back to block retries."""
    prepared = prepare_compaction(history, keep_turns=keep_turns)
    fingerprint = sha256(json.dumps({key: prepared[key] for key in ("source", "boundary_id")},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {"summary": None, "boundary_id": None, "fingerprint": fingerprint,
              "reason": prepared["reason"]}
    if cancelled():
        return {**result, "reason": "cancelled"}
    if fingerprint == blocked_fingerprint:
        return {**result, "reason": "previous_failure"}
    if prepared["reason"] != "ready":
        return result
    try:
        summary = summarize(prepared["source"])
    except Exception:
        return {**result, "reason": "cancelled" if cancelled() else "summary_failed"}
    if cancelled():
        return {**result, "reason": "cancelled"}
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        return {**result, "reason": "invalid_summary"}
    return {**result, "summary": summary.strip(), "boundary_id": prepared["boundary_id"],
            "reason": "ready"}


def should_auto_compact(context_info, next_input=None) -> bool:
    """Use actual model limits, reserving output space; unknown media stays unknown."""
    values = [context_info.get(key) for key in
              ("input_tokens", "input_token_limit", "output_token_limit")]
    if context_info.get("has_unmeasured_media") or any(type(value) is not int for value in values):
        return False
    used, limit, reserve = values
    if used < 0 or limit <= 0 or reserve <= 0:
        return False
    extra = 0
    if isinstance(next_input, str):
        extra = math.ceil(len(next_input) / 4)
    elif isinstance(next_input, dict):
        extra = next_input.get("input_tokens")
        if next_input.get("has_unmeasured_media") or type(extra) is not int or extra < 0:
            return False
    elif next_input is not None:
        if type(next_input) is not int or next_input < 0:
            return False
        extra = next_input
    return used + extra + reserve >= math.ceil(limit * 0.8)
