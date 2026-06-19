import os
import threading
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google import genai
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
api = os.getenv("API_KEY")

client = genai.Client(api_key=api)

chat = client.chats.create(model="gemini-3.1-flash-lite")


def auto_reset_chat_loop():
    global chat
    # 8 часов = 8 * 60 * 60 = 28800 секунд
    interval = 8 * 60 * 60

    while True:
        time.sleep(interval)
        try:
            chat = client.chats.create(model="gemini-3.1-flash-lite")
            print("[INFO] Контекст чата автоматически сброшен по таймеру (прошло 8 часов).")
        except Exception as e:
            print(f"[ERROR] Не удалось перезапустить чат: {e}")


threading.Thread(target=auto_reset_chat_loop, daemon=True).start()

class UserMessage(BaseModel):
    message: str

@app.post("/chat/stream")
def stream_chat(payload: UserMessage):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    def event_generator():
        try:
            response_stream = chat.send_message_stream(payload.message)
            for chunk in response_stream:
                if chunk.text:
                    yield f"{chunk.text}\n".encode('utf-8')
        except Exception as e:
            yield f"\n[Ошибка сервера: {str(e)}]\n".encode('utf-8')


    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)