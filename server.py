from gemini_cli.server.history_store import HistoryStore
from gemini_cli.runtime.context import select_context, current_turn
from gemini_cli.runtime.attachments import restore_images
from gemini_cli.protocol.images import IMAGE_PROTOCOL, MAX_WIRE_BYTES, validate_payload_images
import os
from typing import List, Optional, Literal, Dict, Any
import json
from dataclasses import dataclass
from uuid import UUID
import secrets
from starlette.middleware.sessions import SessionMiddleware
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

from gemini_cli.tools.definitions import TOOLS, LEGACY_NAMES
from gemini_cli.server.tool_history import REDACTED_READ_RESULT, persistent_tool_message
from gemini_cli.runtime.history import persistent_history_rows
from gemini_cli.backends.genai import to_gemini, create_provider, stream_events
from gemini_cli.server.subscriptions import require_subscription, working_user_dependency
from gemini_cli.server.budgets import reserve_request
from gemini_cli.server.admin.sessions import WebSessions, session_router, owner_dependency
from gemini_cli.server.admin.subscriptions import subscription_router
from gemini_cli.server.admin.invitations import invitation_router
from gemini_cli.server.admin.accounts import account_router
from gemini_cli.server.admin.pages import page_router, PanelHeaders
from gemini_cli.server.auth_limits import AUTH_LIMITS
from gemini_cli.protocol.models import ModelName
from gemini_cli.protocol.limits import MAX_HISTORY_CONTENT_CHARS
from gemini_cli.server.limits import BodyLimit, StreamJob, BoundedStreamingResponse as StreamingResponse

load_dotenv()

from gemini_cli.server.web_routes import create_web_router

api = os.getenv("API_KEY")
if not api:
    raise RuntimeError("API_KEY не найден в переменных окружения")

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("Данные Supabase (URL/KEY) не найдены в переменных окружения")

app = FastAPI()
app.add_middleware(BodyLimit, max_bytes=MAX_WIRE_BYTES)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("ADMIN_SESSION_SECRET") or secrets.token_hex(32),
                   session_cookie="gemini_admin", https_only=True, same_site="strict", max_age=1800)
app.add_middleware(PanelHeaders)
client = create_provider(api)


@dataclass(frozen=True)
class UserContext:
    user_id: str
    db: Client


def get_current_user(authorization: Optional[str] = Header(None), request: Request = None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок Authorization")

    try:
        token_type, token = authorization.split(" ", 1)
        if token_type.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Неверный тип токена. Ожидается Bearer")
    except ValueError:
        raise HTTPException(status_code=401, detail="Неверный формат заголовка Authorization")

    if request is not None:
        AUTH_LIMITS.check(request, "bearer", token, 90)

    try:
        db = create_client(
            supabase_url,
            supabase_key,
            options=SyncClientOptions(headers={"Authorization": f"Bearer {token}"}),
        )
        user_response = db.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Неверный токен сессии")
        return UserContext(user_id=user_response.user.id, db=db)
    except Exception as e:
        print("[AUTH ERROR] Ошибка валидации токена")
        raise HTTPException(status_code=401, detail="Ошибка авторизации")


get_working_user = working_user_dependency(get_current_user)
from gemini_cli.server.quota_routes import create_quota_router

app.include_router(create_quota_router(get_current_user))
app.include_router(create_web_router(get_working_user, api_key=os.getenv("TAVILY_API_KEY"),
                                    authorize=require_subscription, reserve=reserve_request))


class ChatCreate(BaseModel):
    title: str = Field(max_length=200)


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: str


class MessageItem(BaseModel):
    images: List[Dict[str, Any]] = Field(default_factory=list, max_length=4, repr=False)
    role: Literal["user", "model", "tool"]
    content: str = Field(max_length=MAX_HISTORY_CONTENT_CHARS)
    name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    call_id: Optional[str] = None
    thought_signature: Optional[str] = None
    id: Optional[UUID] = None
    turn_id: Optional[UUID] = None
    request_id: Optional[UUID] = None
    event_index: Optional[int] = Field(default=None, ge=0)
    status: Optional[Literal["legacy", "running", "completed", "cancelled", "failed"]] = None


class StreamChatPayload(BaseModel):
    images: List[Dict[str, Any]] = Field(default_factory=list, max_length=4, repr=False)
    request_id: Optional[UUID] = None
    turn_id: Optional[UUID] = None
    message: str = Field(default="", max_length=32768)
    chat_id: Optional[str] = None
    model_name: ModelName = "gemini-3.5-flash-lite"
    history: Optional[List[MessageItem]] = Field(default=None, max_length=1000)
    summary: Optional[str] = Field(default=None, max_length=8192)
    summary_boundary: Optional[UUID] = None
    current_dir: Optional[str] = None
    continue_after_tool: bool = False
    supported_tools: Optional[List[str]] = Field(default=None, max_length=32)
    end_tool_turn: bool = False

    @field_validator("supported_tools")
    @classmethod
    def known_tools(cls, value):
        if value is not None and (len(set(value)) != len(value) or not set(value) <= set(TOOLS)):
            raise ValueError("Неизвестные или повторяющиеся инструменты")
        return value


class LoginPayload(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024, repr=False)


class RefreshPayload(BaseModel):
    refresh_token: str = Field(max_length=8192, repr=False)


from fastapi import status

@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup_user(payload: LoginPayload):
    raise HTTPException(status_code=403, detail="Регистрация доступна только по приглашению владельца")

@app.post("/auth/login")
def login_user(payload: LoginPayload, request: Request = None):
    if request is not None:
        AUTH_LIMITS.check(request, "login", payload.email.strip().casefold())
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email и пароль обязательны")

    try:
        auth_response = create_client(supabase_url, supabase_key).auth.sign_in_with_password({
            "email": payload.email.strip(),
            "password": payload.password.strip(),
        })

        if not auth_response or not getattr(auth_response, "session", None):
            raise HTTPException(status_code=401, detail="Не удалось выполнить вход")

        return auth_response.session.model_dump()

    except Exception as e:
        print("[AUTH ERROR] Не удалось выполнить вход")
        raise HTTPException(status_code=401, detail="Не удалось выполнить вход")


@app.post("/auth/refresh")
def refresh_user_session(payload: RefreshPayload, request: Request = None):
    if request is not None:
        AUTH_LIMITS.check(request, "refresh", payload.refresh_token, 30)
    if not payload.refresh_token:
        raise HTTPException(status_code=401, detail="Не удалось обновить сессию")
    try:
        response = create_client(supabase_url, supabase_key).auth.refresh_session(
            payload.refresh_token)
        if not response or not response.session:
            raise HTTPException(status_code=401, detail="Не удалось обновить сессию")
        return response.session.model_dump()
    except Exception as e:
        print("[AUTH ERROR] Не удалось обновить сессию")
        status_code = (401 if isinstance(e, HTTPException) or
                       getattr(e, "status", None) in (400, 401, 403) else 503)
        raise HTTPException(status_code=status_code, detail="Не удалось обновить сессию")


web_sessions = WebSessions(get_current_user)
get_admin = owner_dependency(get_current_user)
app.include_router(session_router(web_sessions, login_user))
app.include_router(subscription_router(get_current_user, get_admin, web_sessions))
app.include_router(invitation_router(web_sessions))
app.include_router(account_router(web_sessions))
app.include_router(page_router(web_sessions))


@app.get("/chats", response_model=List[ChatResponse])
def get_chats(user: UserContext = Depends(get_working_user)):
    try:
        response = user.db.table("chats") \
            .select("id, title, created_at") \
            .eq("user_id", user.user_id) \
            .order("created_at", desc=True) \
            .execute()

        chats: List[ChatResponse] = []
        for row in response.data:
            chats.append(ChatResponse(
                id=str(row["id"]),
                title=row["title"],
                created_at=str(row["created_at"]),
            ))
        return chats

    except Exception as e:
        print("[SERVER ERROR] Ошибка получения чатов")
        raise HTTPException(status_code=500, detail="Не удалось получить список чатов")


@app.post("/chats", response_model=ChatResponse)
def create_chat(payload: ChatCreate, user: UserContext = Depends(get_working_user)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Название чата не может быть пустым")

    try:
        response = user.db.table("chats") \
            .insert({"user_id": user.user_id, "title": payload.title.strip()}) \
            .execute()

        if not response or not response.data:
            raise HTTPException(status_code=500, detail="Ошибка при записи чата в БД")

        row = response.data[0]
        return ChatResponse(
            id=str(row["id"]),
            title=row["title"],
            created_at=str(row["created_at"]),
        )

    except Exception as e:
        print("[SERVER ERROR] Ошибка создания чата")
        raise HTTPException(status_code=500, detail="Не удалось создать чат")


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, user: UserContext = Depends(get_working_user)):
    try:
        chat = user.db.table("chats").select("id") \
            .eq("id", chat_id).eq("user_id", user.user_id).execute()
        if not chat.data:
            raise HTTPException(status_code=404, detail="Чат не найден")

        # messages.chat_id has ON DELETE CASCADE; one database request is atomic.
        deleted = user.db.table("chats").delete() \
            .eq("id", chat_id).eq("user_id", user.user_id).execute()
        if not deleted.data:
            raise HTTPException(status_code=404, detail="Чат не найден")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        print("[SERVER ERROR] Ошибка удаления чата")
        raise HTTPException(status_code=500, detail="Не удалось удалить чат")


class MessageStorageError(RuntimeError):
    pass


def save_message_to_db(
        db: Client,
        chat_id: str,
        role: Literal["user", "model", "tool"],
        content: str,
        name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        call_id=None, thought_signature=None
):
    content, args = persistent_tool_message(role, name, content, args)
    data = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "name": name,
        "args": args,
    }
    if call_id is not None:
        data["call_id"] = call_id
    if thought_signature is not None:
        data["thought_signature"] = thought_signature
    try:
        db.table("messages").insert(data).execute()
    except Exception as e:
        print("[DB ERROR] Не удалось сохранить сообщение")
        raise MessageStorageError("Не удалось сохранить сообщение в БД") from None


def build_history_from_db(db: Client, chat_id: str,
                          before_user_content: Optional[str] = None, image_history=None) -> List[Any]:
    try:
        response = db.table("messages").select("*").eq("chat_id", chat_id).order("created_at").execute()
        messages = response.data

        return to_gemini(restore_images(persistent_history_rows(messages, before_user_content), image_history or []))
    except Exception as e:
        print("[DB ERROR] Ошибка загрузки истории")
        raise HTTPException(status_code=503, detail="Не удалось загрузить историю чата") from e


def build_history_from_client(history: Optional[List[MessageItem]]) -> List[Any]:
    try:
        return to_gemini([item.model_dump() for item in history or []])
    except ValueError:
        raise HTTPException(400, "Некорректная подпись вызова инструмента") from None




DEPLOYMENT_REVISION = os.getenv("GEMINI_RELEASE_SHA", "development")


@app.get("/healthz")
def deployment_health():
    return {"status": "ok", "revision": DEPLOYMENT_REVISION}


@app.get("/capabilities")
def capabilities(user: UserContext = Depends(get_working_user)):
    return {"images": IMAGE_PROTOCOL}


from gemini_cli.server.history_routes import register_history_routes
register_history_routes(app, get_user=get_working_user, provider=lambda: client,
    payload_model=StreamChatPayload, authorize=lambda *args, **kwargs: require_subscription(*args, **kwargs),
    reserve=lambda *args, **kwargs: reserve_request(*args, **kwargs))


@app.post("/chat/stream")
def stream_chat(
        payload: StreamChatPayload,
        user: UserContext = Depends(get_working_user),
):
    try:
        validate_payload_images(payload.model_dump())
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Некорректные изображения") from None
    requested_tools = set(payload.supported_tools if payload.supported_tools is not None else LEGACY_NAMES)
    rights = require_subscription(user, model=payload.model_name)
    requested_tools &= set(rights["features"])
    if payload.end_tool_turn and not payload.continue_after_tool:
        raise HTTPException(status_code=400, detail="Завершение допустимо только после результата инструмента")
    if payload.continue_after_tool:
        if payload.message.strip() or not payload.history or payload.history[-1].role != "tool":
            raise HTTPException(status_code=400, detail="Ожидается история с результатом инструмента")
    elif not payload.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if payload.chat_id:
        chat = user.db.table("chats").select("id") \
            .eq("id", payload.chat_id).eq("user_id", user.user_id).execute()
        if not chat.data:
            raise HTTPException(status_code=404, detail="Чат не найден")

    identified = bool(payload.chat_id and payload.turn_id and payload.request_id)
    store = HistoryStore(user.db, user.user_id) if identified else None
    incoming = [item.model_dump(mode="json") for item in payload.history or []]
    stored, metadata = None, {}
    if payload.chat_id:
        try:
            reader = store or HistoryStore(user.db, user.user_id)
            stored, metadata = reader.read(payload.chat_id), reader.metadata(payload.chat_id)
        except Exception:
            raise HTTPException(503, "Не удалось загрузить историю чата") from None
    try:
        selected = select_context(stored, incoming, continuing=payload.continue_after_tool,
            turn_id=str(payload.turn_id) if payload.turn_id else None,
            summary=metadata.get("summary") if stored is not None else payload.summary,
            summary_boundary=metadata.get("summary_boundary") if stored is not None else
                             (str(payload.summary_boundary) if payload.summary_boundary else None))
        history_content = to_gemini(selected)
    except ValueError:
        raise HTTPException(400, "Некорректная история или граница хода") from None

    def event_generator():
        full_response = ""
        sequence, ordinal, outcome = 0, 0, "failed"
        acquired = False
        def save_batch(rows):
            nonlocal ordinal
            if not payload.chat_id or job.cancelled.is_set():
                return
            if store:
                ordinal = store.append(payload.chat_id, rows, turn_id=payload.turn_id,
                    request_id=payload.request_id, start=ordinal)
            else:
                for row in rows:
                    save_message_to_db(user.db, payload.chat_id, row["role"], row["content"],
                        row.get("name"), row.get("args"), row.get("call_id"), row.get("thought_signature"))
        def save(role, content, name=None, args=None, call_id=None, signature=None):
            save_batch([{"role": role, "content": content, "name": name, "args": args,
                         "call_id": call_id, "thought_signature": signature}])
        try:
            if job.cancelled.is_set():
                return
            require_subscription(user, model=payload.model_name, features=requested_tools)
            if not payload.end_tool_turn:
                reserve_request(user, operation="gemini", request_id=payload.request_id,
                                model=payload.model_name, features=requested_tools)
                acquired = True
            if payload.chat_id and not payload.continue_after_tool:
                save("user", payload.message)

            current_contents = list(history_content)

            if payload.continue_after_tool:
                if payload.chat_id:
                    last_batch_start = len(payload.history) - 1
                    while last_batch_start and payload.history[last_batch_start - 1].role == "tool":
                        last_batch_start -= 1
                    save_batch([item.model_dump(mode="json") for item in payload.history[last_batch_start:]])
                    if payload.end_tool_turn:
                        acquired = True
                full_contents = current_contents
            else:
                active_message = to_gemini([{"role": "user", "content": payload.message, "images": payload.images}])[0]

                full_contents = current_contents + [active_message]

            if payload.end_tool_turn:
                message = "Достигнут предел продолжений инструментов. Последние результаты сохранены; продолжите новым сообщением."
                if payload.chat_id:
                    save("model", message)
                outcome = "completed"
                yield f"data: {json.dumps({'type': 'text', 'content': message}, ensure_ascii=False)}\n\n".encode("utf-8")
                return

            has_calls, failed = False, False
            permitted = set(TOOLS) - ({"web_search"} if not os.getenv("TAVILY_API_KEY") else set())
            for event in stream_events(client, model=payload.model_name, contents=full_contents,
                                       supported_tools=sorted(requested_tools), permitted_tools=permitted,
                                       cancelled=job.cancelled.is_set):
                if job.cancelled.is_set():
                    return
                if payload.turn_id is not None:
                    event = {**event, "turn_id": str(payload.turn_id),
                             "request_id": str(payload.request_id), "sequence": sequence}
                    sequence += 1
                if event["type"] == "text":
                    full_response += event["content"]
                elif event["type"] == "error":
                    failed = True
                elif event["type"] == "tool_call":
                    if not has_calls and full_response and payload.chat_id:
                        save("model", full_response)
                    has_calls = True
                    if payload.chat_id:
                        save("model", f"[Вызов локального инструмента: {event['name']}]",
                             event["name"], event["args"], event.get("call_id"), event.get("thought_signature"))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
            if payload.chat_id and full_response and not has_calls and not failed and not job.cancelled.is_set():
                save("model", full_response)
            outcome = "failed" if failed else "completed"

        except Exception as e:
            error_msg = str(e)
            if isinstance(e, MessageStorageError):
                content = "[Ошибка сервера: Не удалось сохранить сообщение в БД]"
            elif isinstance(e, HTTPException):
                content = e.detail
            elif "429" in error_msg or "ResourceExhausted" in error_msg:
                content = "Бесплатные токены или запросы для модели закончились. Пожалуйста, смените модель с помощью /model"
            else:
                content = "Сервер временно не смог обработать запрос"

            error_event = {
                "type": "error",
                "content": content
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n".encode("utf-8")
        finally:
            if store and acquired:
                try:
                    store.finish(payload.chat_id, payload.request_id,
                                 "cancelled" if job.cancelled.is_set() else outcome)
                except Exception:
                    print("[DB ERROR] Не удалось сохранить статус хода")

    job = StreamJob(event_generator(), user.user_id, rights.get("parallel_limit", 1))
    return StreamingResponse(job, media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1")
