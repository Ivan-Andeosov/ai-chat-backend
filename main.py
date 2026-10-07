from dotenv import load_dotenv
import os
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

chat_completion = client.chat.completions.create(
messages=[
        {
            "role": "user",
            "content": "Explain the importance of fast language models",
        }
    ],
model="openai/gpt-oss-120b",
)

print(chat_completion.choices[0].message.content)