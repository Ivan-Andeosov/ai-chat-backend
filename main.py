import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from groq import APIError, Groq
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_settings import HISTORY_LIMIT, LANGUAGE, MODEL, SYSTEM_PROMPT, USER_NAME
from database import get_db, init_db
from models import Chat, Message, RequestLog, Setting, utcnow

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
PROVIDER = "groq"
INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"

DEFAULT_SETTINGS = {
    "user_name": USER_NAME,
    "language": LANGUAGE,
    "system_prompt": SYSTEM_PROMPT,
}


def load_settings(db: Session) -> dict[str, str]:
    result = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        row = db.get(Setting, key)
        if row is not None:
            result[key] = row.value
    return result


def build_system_prompt(settings: dict[str, str]) -> str:
    parts = []
    prompt = settings["system_prompt"].strip()
    name = settings["user_name"].strip()
    language = settings["language"].strip()
    if prompt:
        parts.append(prompt)
    if name:
        parts.append(f"The user's name is {name}.")
    if language:
        parts.append(f"Always reply in this language: {language}.")
    return "\n".join(parts)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ai-chat-backend", lifespan=lifespan)


class SettingsData(BaseModel):
    user_name: str = Field(default="", max_length=100)
    language: str = Field(default="", max_length=50)
    system_prompt: str = Field(default="", max_length=4000)


class ChatCreate(BaseModel):
    title: str = "New chat"


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


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int | None = None
    provider: str
    model: str
    status: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    created_at: datetime


class AskRequest(BaseModel):
    question: str
    chat_id: int | None = None


class AskResponse(BaseModel):
    answer: str
    chat_id: int


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX_FILE)


@app.get("/settings", response_model=SettingsData)
def get_settings(db: Session = Depends(get_db)):
    return load_settings(db)


@app.put("/settings", response_model=SettingsData)
def update_settings(data: SettingsData, db: Session = Depends(get_db)):
    for key, value in data.model_dump().items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return load_settings(db)


@app.delete("/settings", response_model=SettingsData)
def reset_settings(db: Session = Depends(get_db)):
    for key in DEFAULT_SETTINGS:
        row = db.get(Setting, key)
        if row is not None:
            db.delete(row)
    db.commit()
    return load_settings(db)


@app.get("/logs", response_model=list[LogOut])
def get_logs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return db.scalars(
        select(RequestLog).order_by(RequestLog.id.desc()).limit(limit)
    ).all()


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
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat.messages


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: int, db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return {"deleted": chat_id}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db)):
    if not request.chat_id:
        chat = Chat(title=request.question[:50])
        db.add(chat)
        db.commit()
        db.refresh(chat)
    else:
        chat = db.get(Chat, request.chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")

    history = db.scalars(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    history.reverse()

    messages = []
    system_prompt = build_system_prompt(load_settings(db))
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({"role": "user", "content": request.question})

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
        raise HTTPException(status_code=502, detail="Model request failed")
    duration_ms = int((time.perf_counter() - started) * 1000)

    answer = completion.choices[0].message.content
    usage = completion.usage

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
