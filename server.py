import os
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException, Header, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

api = os.getenv("API_KEY")
if not api:
    raise RuntimeError("API_KEY не найден в переменных окружения")

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("Данные Supabase (URL/KEY) не найдены в переменных окружения")

supabase: Client = create_client(supabase_url, supabase_key)

app = FastAPI()
client = genai.Client(api_key=api)


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок Authorization")

    try:
        token_type, token = authorization.split(" ", 1)
        if token_type.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Неверный тип токена. Ожидается Bearer")
    except ValueError:
        raise HTTPException(status_code=401, detail="Неверный формат заголовка Authorization")

    try:
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Неверный токен сессии")
        return user_response.user.id
    except Exception as e:
        print(f"[AUTH ERROR] Ошибка валидации токена: {e}")
        raise HTTPException(status_code=401, detail="Ошибка авторизации")


class ChatCreate(BaseModel):
    title: str


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: str


class MessageItem(BaseModel):
    role: Literal["user", "model"]
    content: str


class StreamChatPayload(BaseModel):
    message: str
    chat_id: Optional[str] = None
    model_name: Optional[str] = "gemini-3.1-flash-lite"
    history: Optional[List[MessageItem]] = None


class LoginPayload(BaseModel):
    email: str
    password: str

from fastapi import status

@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup_user(payload: LoginPayload):
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email и пароль обязательны")

    try:
        resp = supabase.auth.sign_up({
            "email": payload.email.strip(),
            "password": payload.password.strip(),
        })

        if hasattr(resp, "session") and resp.session:
            return resp.session.model_dump()

        return {"detail": "Пользователь создан. Проверьте почту для подтверждения."}

    except Exception as e:
        print(f"[AUTH ERROR] Signup failed for {payload.email!r}: {e}")
        raise HTTPException(status_code=400, detail="Не удалось создать пользователя")

@app.post("/auth/login")
def login_user(payload: LoginPayload):
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email и пароль обязательны")

    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": payload.email.strip(),
            "password": payload.password.strip(),
        })

        if not auth_response or not getattr(auth_response, "session", None):
            raise HTTPException(status_code=401, detail="Не удалось выполнить вход")

        return auth_response.session.model_dump()

    except Exception as e:
        print(f"[AUTH ERROR] Login failed for {payload.email!r}: {e}")
        raise HTTPException(status_code=401, detail="Не удалось выполнить вход")


@app.get("/chats", response_model=List[ChatResponse])
async def get_chats(user_id: str = Depends(get_current_user)):
    try:
        response = supabase.table("chats") \
            .select("id, title, created_at") \
            .eq("user_id", user_id) \
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
        print(f"[SERVER ERROR] Ошибка получения чатов: {e}")
        raise HTTPException(status_code=500, detail="Не удалось получить список чатов")


@app.post("/chats", response_model=ChatResponse)
async def create_chat(payload: ChatCreate, user_id: str = Depends(get_current_user)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Название чата не может быть пустым")

    try:
        response = supabase.table("chats") \
            .insert({"user_id": user_id, "title": payload.title.strip()}) \
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
        print(f"[SERVER ERROR] Ошибка при создании чата: {e}")
        raise HTTPException(status_code=500, detail="Не удалось создать чат")


async def save_message_to_db(chat_id: str, user_message: str, model_response: str):
    try:
        supabase.table("messages").insert({
            "chat_id": chat_id,
            "role": "user",
            "content": user_message,
        }).execute()

        supabase.table("messages").insert({
            "chat_id": chat_id,
            "role": "model",
            "content": model_response,
        }).execute()

    except Exception as e:
        print(f"[BD ERROR] Не удалось сохранить сообщения в БД: {e}")


def build_history_from_db(chat_id: str) -> List[types.Content]:
    history_content: List[types.Content] = []

    db_response = supabase.table("messages") \
        .select("role, content") \
        .eq("chat_id", chat_id) \
        .order("created_at", desc=True) \
        .limit(20) \
        .execute()

    raw_messages = db_response.data[::-1]
    for msg in raw_messages:
        history_content.append(
            types.Content(
                role=msg["role"],
                parts=[types.Part.from_text(text=msg["content"])],
            )
        )

    return history_content


def build_history_from_client(history: Optional[List[MessageItem]]) -> List[types.Content]:
    history_content: List[types.Content] = []
    if not history:
        return history_content

    for msg in history[-20:]:
        history_content.append(
            types.Content(
                role=msg.role,
                parts=[types.Part.from_text(text=msg.content)],
            )
        )

    return history_content


@app.post("/chat/stream")
def stream_chat(
    payload: StreamChatPayload,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if payload.chat_id:
        try:
            history_content = build_history_from_db(payload.chat_id)
        except Exception as e:
            print(f"[SERVER ERROR] Ошибка загрузки контента: {e}")
            history_content = []
    else:
        history_content = build_history_from_client(payload.history)

    def event_generator():
        full_response = ""
        try:
            chat_session = client.chats.create(
                model=payload.model_name,
                history=history_content,
            )
            response_stream = chat_session.send_message_stream(payload.message)

            for chunk in response_stream:
                if chunk.text:
                    full_response += chunk.text
                    yield chunk.text.encode("utf-8")

            if payload.chat_id:
                background_tasks.add_task(
                    save_message_to_db,
                    payload.chat_id,
                    payload.message.strip(),
                    full_response,
                )

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "ResourceExhausted" in error_msg:
                yield "Бесплатные токены или запросы для модели закончились. Пожалуйста, смените модель с помощью /model".encode("utf-8")
            else:
                yield f"[Ошибка сервера: {error_msg}]".encode("utf-8")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)