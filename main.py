import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from groq import APIError, Groq
from pydantic import BaseModel

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"

app = FastAPI(title="ai-chat-backend")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": request.question}],
            model=MODEL,
        )
    except APIError:
        raise HTTPException(status_code=502, detail="Модель не знайденв або непрацює")
    return AskResponse(answer=completion.choices[0].message.content)