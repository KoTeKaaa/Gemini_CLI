"""Owner-scoped history APIs; entrypoint dependencies are injected explicitly."""
from contextlib import contextmanager
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .history_store import HistoryStore
from ..backends.genai import AGENT_INSTRUCTION, to_gemini
from ..backends.model_info import model_info, count_context
from ..protocol.images import validate_payload_images
from ..runtime.context import select_context
from ..runtime.context_info import estimate_context
from ..tools.definitions import available_tools


class ForkPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    boundary_id: UUID | None = None


@contextmanager
def history_errors():
    try:
        yield
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(404, "Чат или граница не найдены") from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "Некорректная история или граница") from None
    except Exception:
        raise HTTPException(503, "История временно недоступна") from None


def register_history_routes(app, *, get_user, provider, payload_model, authorize, reserve):
    class ContextPayload(payload_model):
        refresh: bool = False

    def selected(payload, user):
        store = HistoryStore(user.db, user.user_id)
        rows = store.read(payload.chat_id) if payload.chat_id else None
        metadata = store.metadata(payload.chat_id) if rows is not None else {}
        incoming = [row.model_dump(mode="json") for row in payload.history or []]
        history = select_context(rows, incoming, continuing=payload.continue_after_tool,
            turn_id=str(payload.turn_id) if payload.turn_id else None,
            summary=metadata.get("summary") if rows is not None else payload.summary,
            summary_boundary=metadata.get("summary_boundary") if rows is not None else
                (str(payload.summary_boundary) if payload.summary_boundary else None))
        if payload.message and not payload.continue_after_tool:
            history.append({"role": "user", "content": payload.message, "images": payload.images})
        return history

    @app.get("/chats/{chat_id}/history")
    def get_history(chat_id: UUID, user=Depends(get_user)):
        with history_errors():
            return HistoryStore(user.db, user.user_id).read(str(chat_id))

    @app.post("/chats/{chat_id}/fork")
    def fork_chat(chat_id: UUID, payload: ForkPayload, user=Depends(get_user)):
        with history_errors():
            return HistoryStore(user.db, user.user_id).fork(str(chat_id), payload.title,
                str(payload.boundary_id) if payload.boundary_id else None)

    @app.post("/chat/context")
    def context_info(payload: ContextPayload, user=Depends(get_user)):
        rights = authorize(user, model=payload.model_name)
        with history_errors():
            validate_payload_images(payload.model_dump())
            contents = to_gemini(selected(payload, user))
            client = provider()
            from google.genai import types
            functions = available_tools(payload.supported_tools, set(rights["features"]))
            tools = ([types.Tool(function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(
                callable=function, api_option="GEMINI_API") for function in functions])] if functions else [])
            info = model_info(client, payload.model_name, ("server", id(client), user.user_id),
                              refresh=payload.refresh)
            usage = count_context(client, payload.model_name, contents, AGENT_INSTRUCTION, tools) if payload.refresh else None
            return estimate_context(contents, info, AGENT_INSTRUCTION, tools, measured_usage=usage)
