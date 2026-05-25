# KnowForge

KnowForge is a FastAPI-based backend for a self-hosted institutional memory engine.

This repository contains the FastAPI backend foundation plus the first LLMWiki engine slice:
PDF ingestion, Markdown wiki compilation, wiki-first chat routing, Groq-backed answering,
hard-question planning/verification, compact context loading, and knowledge-gap logging.

## Project Shape

```text
app/
  api/        HTTP routes
  core/       settings and shared application setup
  llmwiki/    Markdown wiki, ingestion, routing, Groq, chat orchestration
  schemas/    Pydantic API contracts
tests/        automated tests
```

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

API docs will be available at `http://localhost:8000/docs`.

The dashboard UI is served from the backend root:

```bash
http://localhost:8000/
```

## Main Endpoints

- `GET /api/v1/health`
- `POST /api/v1/sources/upload` uploads a PDF, capped at 5 MB, and compiles wiki content.
- `GET /api/v1/wiki/index` returns the compact routing index.
- `GET /api/v1/wiki/pages` lists generated wiki pages.
- `GET /api/v1/wiki/pages/{slug}` reads a page.
- `PUT /api/v1/wiki/pages/{slug}` manually creates or updates a page.
- `POST /api/v1/wiki/compact` compacts oversized wiki pages.
- `POST /api/v1/chat` answers from the wiki first, then fallback evidence if needed.

When the wiki has no relevant context, KnowForge falls back to a direct Groq assistant
answer for general chat instead of returning a dead-end no-answer response. It still avoids
pretending to know unsupported internal facts.

## Configuration

Set `GROQ_API_KEY` in `.env` for Groq-backed compile, planning, answering, and verification.
Without it, the backend still works in local deterministic mode for development and tests.

Runtime wiki/source files are stored under `KNOWFORGE_STORAGE_PATH`, defaulting to `storage/`.

## Next Build Direction

Add the next pieces only when we start implementing them:

1. Persistent users, auth, and organization workspaces.
2. Database models and migrations.
3. Background job queue for large ingestion/compilation runs.
4. Pinecone or another vector fallback provider.
5. Frontend dashboard and chat UI.
