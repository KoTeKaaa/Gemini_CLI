import os
from typing import List, Optional, Literal, Dict, Any
import json
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
    role: Literal["user", "model", "tool"]
    content: str
    name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None


class StreamChatPayload(BaseModel):
    message: str
    chat_id: Optional[str] = None
    model_name: Optional[str] = "gemini-3.1-flash-lite"
    history: Optional[List[MessageItem]] = None
    current_dir: Optional[str] = None


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


@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user_id: str = Depends(get_current_user)):
    try:
        supabase.table("messages").delete().eq("chat_id", chat_id).execute()
        supabase.table("chats").delete().eq("id", chat_id).eq("user_id", user_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def save_message_to_db(
        chat_id: str,
        role: Literal["user", "model", "tool"],
        content: str,
        name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None
):
    try:
        data = {
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "name": name,
            "args": args,
        }
        supabase.table("messages").insert(data).execute()

    except Exception as e:
        print(f"[BD ERROR] Не удалось сохранить сообщения в БД: {e}")


def build_history_from_db(chat_id: str) -> List[types.Content]:
    history_content: List[types.Content] = []
    try:
        response = supabase.table("messages").select("*").eq("chat_id", chat_id).order("created_at").execute()
        messages = response.data

        for msg in messages[-20:]:
            role = msg.get("role")
            content = msg.get("content", "")
            tool_name = msg.get("name")

            if role in ["user", "model"]:
                history_content.append(
                    types.Content(
                        role=role,
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

                history_content.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name or "unknown_tool",
                                response=parsed_result
                            )
                        ],
                    )
                )
    except Exception as e:
        print(f"[DB ERROR] Ошибка загрузки истории: {e}")
    return history_content


def build_history_from_client(history: Optional[List[MessageItem]]) -> List[types.Content]:
    history_content: List[types.Content] = []
    if not history:
        return history_content

    for item in history[-20:]:
        msg = item.model_dump() if hasattr(item, "model_dump") else item.dict()

        role = msg.get("role")
        content = msg.get("content", "")
        name = msg.get("name")
        args = msg.get("args")

        if role == "user":
            history_content.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=content)],
                )
            )

        elif role == "model":
            if name:
                history_content.append(
                    types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=name,
                                    args=args or {}
                                )
                            )
                        ],
                    )
                )
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

            history_content.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=name or "unknown_tool",
                            response=parsed_result
                        )
                    ],
                )
            )

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



def read_local_files(filepaths: List[str]) -> str:
    """
    Reads the content of multiple text-based files (source code, text, configs, logs) from the workspace at once.
    ALWAYS use this when the user asks to fix, refactor, or analyze code across multiple files.

    Args:
        filepaths: A list of RELATIVE file paths starting from the current workspace root.
                   Do NOT use absolute paths. Example: ["main.py", "utils/helpers.py"]
    """
    return "Пакетное чтение файлов инициировано"


def write_local_files(files: List[dict]) -> str:
    """
    Creates or completely overwrites multiple text files in the workspace simultaneously.
    Use this to save generated source code, laboratory scripts, or Markdown documentation.

    CRITICAL: You must provide the FULL and COMPLETE content of the files. Do NOT truncate
    the code with placeholders like '// ... rest of code ...'. Write everything from scratch.

    Args:
        files: A list of dictionaries. Each dict MUST strictly contain:
               - 'filepath' (str): The relative path to the file from workspace root (e.g., 'src/app.py').
               - 'content' (str): The exact and complete text/code content to be written.
    """
    return "Пакетная запись файлов инициирована"


def execute_command(command: str) -> str:
    """
    Executes a SINGLE, NON-INTERACTIVE shell command in the user's terminal workspace (e.g., runs tests, compilers, pip).

    CRITICAL RULES:
    1. Do NOT string multiple commands together using '&&', '||', or ';'. Execute them one by one.
    2. The command MUST be non-interactive. Do NOT run commands that wait for user input (e.g., bare 'python', 'git commit' without -m, 'npm init' without -y).
    3. For Python scripts, use 'python <filename>' or 'python3 <filename>'.

    Args:
        command: The raw shell command string to execute in the workspace.
    """
    return "Выполнение команды инициировано"


@app.post("/chat/stream")
def stream_chat(
        payload: StreamChatPayload,
        background_tasks: BackgroundTasks,
        user_id: str = Depends(get_current_user),
):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if payload.chat_id and payload.message != "Продолжай работу на основе ответов инструментов.":
        background_tasks.add_task(
            save_message_to_db,
            payload.chat_id,
            "user",
            payload.message.strip()
        )

    if payload.history:
        history_content = build_history_from_client(payload.history)
    elif payload.chat_id:
        history_content = build_history_from_db(payload.chat_id)
    else:
        history_content = []

    def event_generator():
        full_response = ""
        try:

            agent_instruction = (
                "Ты — продвинутый AI-ассистент разработчика с доступом к локальной файловой системе и терминалу. "
                "Когда ты запрашиваешь вызов инструмента (чтение, запись файлов или выполнение команд), клиент "
                "выполняет его и возвращает тебе результат в блоке истории с ролью 'user' (технический ответ функции). "
                "КРИТИЧЕСКОЕ ПРАВИЛО: Получив ответ инструмента, ты должен сразу проанализировать этот результат "
                "и продолжить выполнение исходной задачи пользователя. НЕ запрашивай контекст повторно, "
                "НЕ пиши фразы в духе 'Уточните задачу' — вся хронология действий уже находится в истории чата! "
                "ВАЖНО: Если инструмент вернул успешный результат (например, файл записан, команда выполнена), "
                "считай задачу ВЫПОЛНЕННОЙ. НЕ повторяй вызов того же инструмента снова. "
                "Просто сообщи пользователю об успешном выполнении текстом."
            )

            config = types.GenerateContentConfig(
                tools=[read_local_files, write_local_files, execute_command],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                system_instruction=agent_instruction
            )

            current_contents = list(history_content)

            if payload.message == "Продолжай работу на основе ответов инструментов." and current_contents:

                if payload.chat_id and payload.history:
                    last_client_msg = payload.history[-1]
                    if last_client_msg.role == "tool":
                        background_tasks.add_task(
                            save_message_to_db,
                            payload.chat_id,
                            "tool",
                            last_client_msg.content,
                            last_client_msg.name,
                            None
                        )
                full_contents = current_contents
            else:
                active_message = types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=payload.message)]
                )

                full_contents = current_contents + [active_message]

            response_stream = client.models.generate_content_stream(
                model=payload.model_name,
                contents=full_contents,
                config=config
            )

            for chunk in response_stream:
                if chunk.function_calls:
                    for call in chunk.function_calls:
                        tool_event = {
                            "type": "tool_call",
                            "name": call.name,
                            "args": call.args,
                            "call_id": getattr(call, "id", None)
                        }

                        if payload.chat_id:
                            background_tasks.add_task(
                                save_message_to_db,
                                payload.chat_id,
                                "model",
                                f"[Вызов локального инструмента: {call.name}]",
                                call.name,
                                call.args
                            )

                        yield f"data: {json.dumps(tool_event, ensure_ascii=False)}\n\n".encode("utf-8")
                    return

                if chunk.text:
                    full_response += chunk.text
                    text_event = {
                        "type": "text",
                        "content": chunk.text
                    }
                    yield f"data: {json.dumps(text_event, ensure_ascii=False)}\n\n".encode("utf-8")

            if payload.chat_id and full_response:
                background_tasks.add_task(
                    save_message_to_db,
                    payload.chat_id,
                    "model",
                    full_response
                )

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "ResourceExhausted" in error_msg:
                content = "Бесплатные токены или запросы для модели закончились. Пожалуйста, смените модель с помощью /model"
            else:
                content = f"[Ошибка сервера: {error_msg}]"

            error_event = {
                "type": "error",
                "content": content
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)