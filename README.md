# Mino-Chat (Flask)

A Flask port of the original Streamlit `Mino-chat.py` RAG assistant, with a
ChatGPT-style UI, optional login, and opt-in chat saving.

## Features

- **Chat without an account.** Anyone can open the app and chat immediately.
  A guest's conversation lives in server memory for that browser session.
- **Nothing is saved by default.** A conversation only reaches the database
  when the user clicks **Save chat** — matching the original requirement
  that saving is opt-in, not automatic.
- **Login extracts history from the database.** Once logged in, the sidebar
  ("Saved chats") lists every conversation that user has explicitly saved,
  fetched from SQLite via `/api/sessions`. Clicking one reloads it (and the
  underlying LangChain memory) so the conversation can continue.
- **Same RAG pipeline as the original app**: clarification check → section
  router → multi-store FAISS retrieval → answer generation, all ported
  1:1 into `rag_engine.py` (no Streamlit calls).
- **PDF attachments** are indexed into a private, per-conversation FAISS
  store (the `UPLOAD` section), exactly like the Streamlit version.

## Project layout

```
app.py            Flask app factory / entry point
config.py         Reads credentials.yaml / env vars into Flask config
extensions.py     Shared SQLAlchemy + Flask-Login instances
models.py         User, ChatSession, ChatMessage (SQLite via SQLAlchemy)
auth.py           /api/auth/register, /login, /logout, /me
chat_api.py       /api/chat, /api/new_chat, /api/save_chat, /api/sessions...
rag_engine.py     The ported RAG pipeline (LLM, embeddings, routing chain)
templates/chat.html   Single-page chat UI (adapted from the supplied template)
static/css/style.css  All styling (theme variables, light/dark mode)
static/js/app.js      All frontend behaviour (fetch calls, rendering, modal)
pdfs/<SECTION>/       Drop your base knowledge-base PDFs here, one folder per section
vectorstore/          FAISS indexes are cached here (auto-built on first run)
```

## Tools: Data Stores (web search + PERSONA) and Analyzer (hate speech)

The composer has a **Select Tools** picker with two pills:

- **Data Stores** — a checklist of explicit sources to force into the answer:
  - `WEB` — bypasses local retrieval entirely and answers using a live
    Tavily web search (`RagEngine.web_search`), grounded only in the
    search results, with the source URLs returned alongside the answer.
  - `PERSONA` (or any other value you add to the checkbox list in
    `chat.html`) — forces that section into local retrieval even if the
    router's chit-chat classifier would have skipped it. This only works
    if a matching folder exists under `pdfs/<SECTION>/` and has been
    indexed (via the admin panel's Rebuild index).
  - Selecting anything here also skips the clarification-agent step, the
    same way attaching a PDF does — an explicit tool selection is treated
    as unambiguous intent.
- **Analyzer** — runs the ICL hate-speech classifier
  (`RagEngine.analyze_hate_speech`) on the user's message and attaches the
  result as a `moderation` annotation. This **never blocks or alters the
  answer** — it's purely an annotation shown alongside the response
  (a small badge: flagged/clear/unavailable).

Both selections are sent with every message as a `tools` form field
(`{"vector_stores": [...], "hate_speech": true|false}`) and are **not**
sticky server-side — the frontend just re-sends the current picker state
on each `POST /api/chat`.

### Setup for these tools

- **Web search**: get a key at https://tavily.com and set `TAVILY_API_KEY`
  in `credentials.yaml` (or as an env var). Without it, the WEB tool
  replies with a friendly "not configured" message instead of failing.
- **Hate speech analyzer**: drop labeled vignette CSVs (each needs a
  `text`, `severity_tier`, `implicit_explicit`, `strategy`, and
  `target_group` column) into `indexes/`. The classifier is built lazily
  from every `*.csv` found there at startup. If the folder is empty, or
  `pandas`/`scikit-learn`/`sentence-transformers` aren't installed, the
  Analyzer tool responds with `{"error": "..."}"` instead of crashing the
  whole app.
- Both tools' results (`references`, `moderation`) are persisted alongside
  saved chats (`ChatMessage.extra_json`) and restored when a saved chat is
  reopened.

## Setup

1. **Install dependencies** (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   ```
   The RAG stack (`langchain*`, `faiss-cpu`, `PyMuPDF`, `sentence-transformers`)
   is only needed if you want real answers grounded in documents. The app
   will still start and let people chat (with a "no knowledge base" message)
   even if these aren't installed or Azure credentials aren't set — this
   makes it easy to develop/test the login and saving features in isolation.

2. **Add credentials** (optional, only needed for real LLM answers):
   ```bash
   cp credentials.example.yaml credentials.yaml
   # then edit credentials.yaml with your Azure OpenAI key/endpoint
   ```
   You can also set the same keys as environment variables
   (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, etc.) instead of using
   the yaml file. Also set `SECRET_KEY` to a long random string for
   production (Flask session signing).

3. **Add your knowledge base** (optional):
   ```
   pdfs/CIWA/*.pdf
   pdfs/RCC/*.pdf
   pdfs/GENERAL/*.pdf
   pdfs/DATA/*.pdf
   ```
   Any folder name works; unknown folders get a generic description. The
   index is built automatically on first run and cached under
   `vectorstore/`. Use the "Rebuild index" button in the UI (or
   `POST /api/rebuild_index`) to force a rebuild after adding new PDFs.

4. **Run**:
   ```bash
   python app.py
   ```
   Visit `http://localhost:5000`.

   For production, run behind a real WSGI server, e.g.:
   ```bash
   pip install gunicorn
   gunicorn -w 2 -b 0.0.0.0:8000 "app:app"
   ```
   Note: the RAG engine keeps FAISS indexes and LangChain memory in
   process memory, so stick to a single worker process unless you move
   that state into shared storage (e.g. Redis) first.

## How saving works

- Every browser gets an anonymous "runtime session id" (a signed cookie),
  independent of login, so guests can chat freely.
- Sending messages only ever updates in-memory state — no database writes.
- Clicking **Save chat**:
  - If not logged in → opens the login/sign-up modal.
  - If logged in → creates a `ChatSession` + its `ChatMessage` rows in
    SQLite, tied to `current_user.id`.
- Once a conversation is saved, any further messages in that same
  conversation are appended to the database automatically (so you don't
  have to click Save after every turn) — but a brand-new chat always
  starts unsaved again.
- The sidebar's "Saved chats" list, and the ability to reopen and continue
  an old conversation, are both driven directly from the database and are
  only ever shown to the logged-in owner.

## API summary

| Method | Path                     | Purpose                                   |
|--------|--------------------------|--------------------------------------------|
| GET    | `/`                      | Serves the chat UI                        |
| GET    | `/api/state`             | Initial state: user, current draft chat, saved sessions |
| POST   | `/api/chat`              | Send a message (+ optional PDF files)     |
| POST   | `/api/new_chat`          | Start a fresh, unsaved conversation       |
| POST   | `/api/save_chat`         | Persist the current conversation (login required) |
| GET    | `/api/sessions`          | List the current user's saved chats (login required) |
| GET    | `/api/sessions/<id>`     | Load a saved chat and resume it (login required) |
| DELETE | `/api/sessions/<id>`     | Delete a saved chat (login required)      |
| POST   | `/api/rebuild_index`     | Rebuild the base FAISS indexes            |
| POST   | `/api/auth/register`     | Create an account                         |
| POST   | `/api/auth/login`        | Log in                                    |
| POST   | `/api/auth/logout`       | Log out (login required)                  |
| GET    | `/api/auth/me`           | Current user, if any                      |
