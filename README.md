# ai-chat-backend

A local AI chat application built with FastAPI. It talks to a language model through the Groq API, stores every conversation in SQLite and ships with a web interface in Ukrainian and English.

The project started as a learning exercise, so the code is kept small and the architecture is easy to follow: an API layer, a database layer, and a single-page front end served by the same server.

## Features

- Multiple chats, each with its own saved history. The model receives the recent history with every question, so it remembers the conversation.
- Settings in the interface: your name, the reply language and the system instructions for the model.
- Interface in Ukrainian or English, switchable at any time.
- Markdown rendering for model replies (headings, lists, tables, links) with a copy button on code blocks. Output is sanitized before it is shown.
- Request log with provider, model, token counts, duration and error text for every call.
- Runs entirely on your machine. Your API key stays in a local `.env` file, and chats stay in a local database file.

## Tech stack

- Python 3.10 or newer
- FastAPI and Pydantic
- SQLAlchemy with SQLite
- Groq Python SDK
- Plain HTML, CSS and JavaScript on the front end, with [marked](https://marked.js.org/) and [DOMPurify](https://github.com/cure53/DOMPurify) loaded from cdnjs

## Getting started

### 1. Get a Groq API key

Create a free account at [console.groq.com](https://console.groq.com) and generate an API key. Copy it right away, because it is shown only once.

### 2. Clone the repository and install dependencies

```
git clone https://github.com/Ivan-Andeosov/ai-chat-backend.git
cd ai-chat-backend
python -m venv .venv
```

Activate the virtual environment:

- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- macOS and Linux: `source .venv/bin/activate`

Then install the packages:

```
pip install -r requirements.txt
```

### 3. Add your key

Copy `.env.example` to `.env` and put your key after the equals sign, with no quotes and no spaces:

```
GROQ_API_KEY=your_key_here
```

The `.env` file is listed in `.gitignore` and must never be committed.

### 4. Choose a model

Open `chat_settings.py` and set `MODEL` to a model ID from the [Groq models page](https://console.groq.com/docs/models). Model availability changes over time and depends on your account, so use an ID from that page.

### 5. Run the server

```
fastapi dev main.py
```

If the `fastapi` command is not found, use `uvicorn main:app --reload` instead.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. The database file `chat.db` is created automatically on the first start.

## Configuration

Defaults live in `chat_settings.py`:

| Setting | Meaning |
|---|---|
| `USER_NAME` | Your name. The model is told who it is talking to. |
| `LANGUAGE` | Reply language, for example `"English"`. An empty string means the model answers in the language of your question. |
| `SYSTEM_PROMPT` | Instructions that are sent to the model with every request. |
| `MODEL` | The Groq model ID. Only configurable in this file. |
| `HISTORY_LIMIT` | How many of the latest messages of a chat are sent to the model. |

The name, reply language and instructions can also be changed from the **Settings** button in the interface. Values saved there are stored in the database and take priority over the defaults. The **Reset** button in the same window removes them and returns to the defaults from `chat_settings.py`. Changes apply from the next message, including chats that were started earlier.

The interface language (Ukrainian or English) is chosen in the same window and remembered in the browser.

## API

Interactive documentation is available at `/docs` while the server is running.

| Method and path | Description |
|---|---|
| `GET /` | The web interface |
| `POST /ask` | Send a question. Body: `question` and an optional `chat_id`. Without `chat_id` a new chat is created. |
| `GET /chats` | List chats, most recently updated first |
| `POST /chats` | Create an empty chat |
| `GET /chats/{chat_id}/messages` | Messages of a chat |
| `DELETE /chats/{chat_id}` | Delete a chat and its messages |
| `GET /settings` | Current name, reply language and instructions |
| `PUT /settings` | Save settings |
| `DELETE /settings` | Reset settings to the defaults |
| `GET /logs?limit=20` | Latest entries of the request log |

## Project structure

```
ai-chat-backend/
├── main.py            FastAPI app and all endpoints
├── chat_settings.py   Default settings and the model name
├── database.py        SQLite engine, sessions and table creation
├── models.py          SQLAlchemy models
├── init_db.py         Optional: create the tables and print the schema
├── static/
│   └── index.html     The whole front end
├── requirements.txt
├── .env.example
└── .gitignore
```

## Database

SQLite file `chat.db` in the project root, excluded from Git.

| Table | Purpose |
|---|---|
| `chats` | One row per chat |
| `messages` | Questions and answers, with the provider and model that answered |
| `request_logs` | One row per model call: tokens, duration, status and error text |
| `settings` | Name, reply language and instructions saved from the interface |
| `api_keys` | Reserved for storing several keys later. Not used yet. |

Deleting a chat deletes its messages. Log entries stay, and their `chat_id` becomes empty.

If you change the table definitions during development, delete `chat.db` and start the server again. Migrations with Alembic would be the next step once the data matters.

## Troubleshooting

**"The model did not reply" or a 502 error.** Open `http://127.0.0.1:8000/logs` and read `error_message` in the latest entry with status `error`.

- `model_not_found`: the `MODEL` value is wrong, or your account has no access to that model. Pick another ID from the models page.
- `invalid_api_key` or a 401 status: check `GROQ_API_KEY` in `.env`, then restart the server, because `.env` is read only at startup.
- A 429 status or a rate limit message: the free tier limit was reached. Wait a minute and try again.

**The page shows raw `**` and `#` characters instead of formatting.** The Markdown libraries could not be loaded from cdnjs. Check your internet connection and the browser console.

## Security notes

- The server has no authentication. Run it only on your own machine, which is the default (`127.0.0.1`), and do not expose it to the internet.
- Never commit `.env` or `chat.db`. Both are in `.gitignore`. If a key ever reaches a public repository, revoke it in the Groq console and create a new one.

## Roadmap

- Several models and providers with a model picker
- API key management in the interface
- Handling of rate limits, timeouts and retries
- Database migrations with Alembic
