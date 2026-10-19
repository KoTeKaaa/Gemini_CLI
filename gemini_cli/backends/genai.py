"""Общий Gemini adapter; SDK загружается только при вызове провайдера."""

import base64
import binascii
import json

from ..runtime.history import trim_history


def to_gemini(history: list[dict]):
    from google.genai import types
    history_content = []
    if not history:
        return history_content

    for msg in trim_history(history):
        role = msg.get("role")
        content = msg.get("content", "")
        name = msg.get("name")
        args = msg.get("args")
        call_id = msg.get("call_id")

        if role == "user":
            history_content.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=content)],
                )
            )

        elif role == "model":
            if name:
                signature = msg.get("thought_signature")
                if signature:
                    try:
                        signature = base64.b64decode(signature, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise ValueError("Некорректная подпись вызова инструмента") from exc
                part = types.Part(function_call=types.FunctionCall(
                    name=name, args=args or {}, id=call_id
                ), thought_signature=signature)
                if history_content and history_content[-1].role == "model" and all(
                    previous.function_call is not None for previous in history_content[-1].parts
                ):
                    history_content[-1].parts.append(part)
                else:
                    history_content.append(types.Content(role="model", parts=[part]))
            else:
                history_content.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)],
                    )
                )

        elif role == "tool":
            try:
                parsed_result = json.loads(content)
                if not isinstance(parsed_result, dict):
                    parsed_result = {"output": parsed_result}
            except Exception:
                parsed_result = {"output": content}

            part = types.Part(function_response=types.FunctionResponse(
                name=name or "unknown_tool", response=parsed_result, id=call_id
            ))
            if history_content and history_content[-1].role == "user" and all(
                previous.function_response is not None for previous in history_content[-1].parts
            ):
                history_content[-1].parts.append(part)
            else:
                history_content.append(types.Content(role="user", parts=[part]))

    while history_content and history_content[0].role != "user":
        history_content.pop(0)

    while (
            history_content
            and history_content[0].role == "user"
            and history_content[0].parts
            and hasattr(history_content[0].parts[0], "function_response")
            and history_content[0].parts[0].function_response is not None
    ):
        history_content.pop(0)

    return history_content

