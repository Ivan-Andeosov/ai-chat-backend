import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from groq import APIError, Groq
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from pathlib import Path

from database import get_db, init_db
from models import Chat, Message, RequestLog, utcnow

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
PROVIDER = "groq"
MODEL = "openai/gpt-oss-120b"
HISTORY_LIMIT = 20  # сколько последних сообщений отправлять модели


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # создаст таблицы, если их ещё нет
    yield


app = FastAPI(title="ai-chat-backend", lifespan=lifespan)

INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX_FILE)


# ---------- схемы запросов и ответов ----------

class ChatCreate(BaseModel):
    title: str = "Новый чат"


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    provider: str | None = None
    model: str | None = None


class AskRequest(BaseModel):
    question: str
    chat_id: int | None = None  # если не указан, создастся новый чат


class AskResponse(BaseModel):
    answer: str
    chat_id: int


# ---------- чаты ----------

@app.post("/chats", response_model=ChatOut)
def create_chat(data: ChatCreate, db: Session = Depends(get_db)):
    chat = Chat(title=data.title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@app.get("/chats", response_model=list[ChatOut])
def list_chats(db: Session = Depends(get_db)):
    return db.scalars(select(Chat).order_by(Chat.updated_at.desc())).all()


@app.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
def get_messages(chat_id: int, db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat.messages


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: int, db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    db.delete(chat)
    db.commit()
    return {"deleted": chat_id}


# ---------- вопрос модели ----------

@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db)):
    # 1. Находим чат или создаём новый
    if not request.chat_id:
        chat = Chat(title=request.question[:50])
        db.add(chat)
        db.commit()
        db.refresh(chat)
    else:
        chat = db.get(Chat, request.chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Чат не найден")

    # 2. Берём последние сообщения чата в правильном порядке
    history = db.scalars(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    history.reverse()

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.question})

    # 3. Отправляем модели и замеряем время
    started = time.perf_counter()
    try:
        completion = client.chat.completions.create(messages=messages, model=MODEL)
    except APIError as exc:
        db.add(
            RequestLog(
                chat_id=chat.id,
                provider=PROVIDER,
                model=MODEL,
                status="error",
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_message=str(exc),
            )
        )
        db.commit()
        raise HTTPException(status_code=502, detail="Ошибка при обращении к модели")
    duration_ms = int((time.perf_counter() - started) * 1000)

    answer = completion.choices[0].message.content
    usage = completion.usage

    # 4. Сохраняем вопрос, ответ и запись в журнал
    db.add(Message(chat_id=chat.id, role="user", content=request.question))
    db.add(
        Message(
            chat_id=chat.id,
            role="assistant",
            content=answer,
            provider=PROVIDER,
            model=MODEL,
        )
    )
    db.add(
        RequestLog(
            chat_id=chat.id,
            provider=PROVIDER,
            model=MODEL,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            status="success",
            duration_ms=duration_ms,
        )
    )
    chat.updated_at = utcnow()
    db.commit()

    return AskResponse(answer=answer, chat_id=chat.id)