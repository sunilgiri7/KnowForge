# KnowForge

KnowForge is a FastAPI-based LLMWiki assistant for turning uploaded PDFs into private,
user-owned Markdown knowledge pages and chatting with that knowledge through a clean
dashboard UI.

It uses Groq for LLM calls, Postgres for users and chat persistence, JWT auth, email
verification, and an AI Harness layer that controls routing, retrieval, thread context,
wiki grounding, direct answers, and verification.

## Features

- PDF upload and source extraction into Markdown wiki pages.
- User-isolated storage under `storage/users/{user_id}/`.
- Groq-backed wiki compilation and chat answers.
- Smart chat routing: wiki when relevant, direct LLM when not.
- AI Harness for query understanding, context selection, threaded replies, and answer checks.
- Exact wiki-page summaries when a user clicks a page.
- Long-chat persistence with Postgres chat sessions and messages.
- Reddit-style nested comments and X-style quick replies.
- Register, email verification, login, JWT auth, and protected APIs.
- Static dashboard UI served by FastAPI.

## Tech Stack

- FastAPI
- SQLAlchemy + Alembic
- Postgres
- Groq `llama-3.3-70b-versatile`
- Static HTML/CSS/JS frontend
- File-based Markdown wiki storage

## Setup

```bash
python3 -m venv env
source env/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Open the dashboard:

```text
http://localhost:8000/
```

API docs:

```text
http://localhost:8000/docs
```

## Configuration

Create `.env`

Required for LLM features:

```env
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
```

Default local Postgres:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=knowforge
DB_USER=knowforge
DB_PASSWORD=knowforge
```

Auth and email:

```env
JWT_SECRET_KEY=change-this-local-secret
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
```

If SMTP is not configured, verification codes are logged by the backend for local development.
Use a strong `JWT_SECRET_KEY` before deployment.

## Main APIs

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/resend-code`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/sources/upload`
- `GET /api/v1/wiki/pages`
- `GET /api/v1/wiki/pages/{slug}`
- `POST /api/v1/wiki/compact`
- `POST /api/v1/chat`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`

## Chat Payload

```json
{
  "question": "Summarize this page",
  "session_id": "optional-session-id",
  "parent_id": "optional-message-id",
  "interaction": "message",
  "context_page_slugs": [],
  "intent": "auto",
  "allow_fallback": true
}
```

Use `interaction: "reply"` or `interaction: "comment"` with `parent_id` for threaded chat.
Use `intent: "wiki"` with `context_page_slugs` for exact page-grounded answers.

## Checks

```bash
ruff check .
python3 -m py_compile app/**/*.py
node --check app/web/static/app.js
```
