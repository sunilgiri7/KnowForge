# KnowForge

KnowForge is a FastAPI LLMWiki assistant with PDF ingestion, Groq-backed answers,
user login, email verification, Postgres chat persistence, and a clean dashboard UI.

## What It Does

- Upload PDFs up to the configured limit and compile them into Markdown wiki pages.
- Ask questions that use wiki context when relevant, or Groq directly for general chat.
- Click a wiki page to summarize that exact page with the correct context.
- Build better wiki pages from long documents with chunk-level extraction and final synthesis.
- Register, verify email, login, and keep user data isolated.
- Store chat sessions and messages in Postgres.
- Keep runtime wiki/source files under `storage/users/{user_id}/`.

## Setup

```bash
python3 -m venv env
source env/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000/
```

API docs:

```text
http://localhost:8000/docs
```

## Configuration

Copy `.env.example` to `.env` and set values as needed.

Required for LLM answers:

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

Email verification uses SMTP when configured. If `SMTP_HOST` is empty, verification
codes are logged by the backend for local development.

Use a strong `JWT_SECRET_KEY` before real deployment.

## Main Endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/resend-code`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/sources/upload`
- `GET /api/v1/wiki/pages`
- `GET /api/v1/wiki/pages/{slug}`
- `POST /api/v1/chat`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`

## Checks

```bash
pytest
ruff check .
python3 -m py_compile app/**/*.py
```
