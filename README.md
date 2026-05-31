# KnowForge

> **Team Knowledge Operating Layer** — A production-grade private LLM assistant that transforms your uploaded PDFs into a living, intelligent knowledge base you can chat with, analyze, and generate structured reports from.

KnowForge is built on FastAPI with a fully custom single-page application frontend. It implements a sophisticated multi-stage AI pipeline: hybrid BM25 + semantic vector retrieval, LLM query expansion (HyDE, step-back prompting, RRF fusion), chain-of-thought answer generation, verification grounding, cross-document contradiction detection, temporal fact tracking, version-controlled wiki pages, workspace RBAC, and an academic research intelligence engine — all served through a minimalist Claude-style UI.

---

## What It Does

You upload PDFs. KnowForge extracts and compiles them into rich Markdown wiki pages using an LLM synthesis pipeline. From that moment, you can:

- **Chat** with your knowledge base — questions are routed to the right wiki pages automatically using hybrid retrieval
- **Detect conflicts** — the system cross-checks related pages for factual mismatches
- **Browse version history** — every page rewrite is versioned and diffed (with LLM semantic summaries)
- **Analyze research papers** — upload academic PDFs to extract authors, methods, claims, citation graphs, and literature gaps
- **Generate reports** — describe a report in plain chat and get a downloadable PDF/XLSX/DOCX back
- **Collaborate in teams** — create shared workspaces, invite members with RBAC roles

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Web Framework** | FastAPI 0.136 + Uvicorn |
| **Database** | PostgreSQL via SQLAlchemy 2 + Alembic |
| **LLM (system)** | Groq (`llama-3.3-70b-versatile`) |
| **LLM (user-configurable)** | OpenRouter, OpenAI, Anthropic, Google Gemini |
| **Vector Search** | Pinecone (all-MiniLM-L6-v2, 384-dim, optional) |
| **Graph Orchestration** | LangGraph (chat flow DAG) |
| **Retrieval** | BM25 in-memory index + Hybrid RRF fusion |
| **File Export** | WeasyPrint (PDF), python-docx (DOCX), openpyxl (XLSX) |
| **Auth** | JWT (PyJWT) + Email verification (SMTP) |
| **Frontend** | Vanilla HTML/CSS/JS (SPA), no build step |
| **Typography** | Plus Jakarta Sans + Newsreader (Google Fonts) |

---

## Quick Start

```bash
# 1. Create and activate environment
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt

# 2. Set up the database
alembic upgrade head

# 3. Configure environment (see .env section below)
cp .env.example .env   # edit as needed

# 4. Start the dev server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/` to access the dashboard.  
API docs: `http://localhost:8000/docs`

---

## Environment Configuration

```env
# LLM (system default — required for wiki compilation & chat routing)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=knowforge
DB_USER=knowforge
DB_PASSWORD=knowforge

# Auth & Email
JWT_SECRET_KEY=change-this-to-a-strong-secret
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=noreply@example.com

# Vector search (optional — BM25 works without it)
PINECONE_API_KEY=
PINECONE_INDEX_NAME=knowforge

# Storage path (default: ./storage)
KNOWFORGE_STORAGE_PATH=./storage
```

> If `SMTP_*` is not configured, verification codes are printed to the server console — useful for local development.

---

## Features

### Core Chat & RAG
- **Smart routing**: queries automatically go to wiki when relevant, direct LLM when not
- **Multi-query expansion**: HyDE, step-back prompting, context-aware rewriting, and keyword decomposition — all merged via Reciprocal Rank Fusion (RRF)
- **Knowledge graph retrieval**: entity linking + multi-hop graph expansion finds related pages the user didn't explicitly ask for
- **CoT answer generation**: hard questions trigger Chain-of-Thought scaffolding
- **Answer verification**: a separate verifier pass grades the answer (fully/partially/unsupported) before returning it
- **Threaded conversations**: reply to a specific message (X-style) or leave a comment; the harness injects parent context
- **Conversation compaction**: long chat histories are LLM-summarized to stay within token budgets

### Wiki Knowledge Base
- **PDF ingestion**: multi-stage pipeline — extraction → chunking → chunk notes → LLM synthesis → knowledge graph
- **Table-preserving extraction**: special regex detects table rows and numbered sections to preserve tabular structure
- **Compaction**: oversized pages get LLM-compressed into a compact form used at retrieval time
- **Version ledger**: every page write creates an immutable `WikiPageVersion` snapshot in Postgres
- **Semantic diffs**: compare any two versions — LLM explains what changed and flags the risk level
- **Supersession detection**: uploading a newer version of a document automatically links and archives the old page
- **Temporal fact extraction**: LLM extracts time-sensitive facts (dates, rates, deadlines, assignments) stored per page
- **Contradiction detection**: pairwise LLM scan across related pages detects factual mismatches with severity ratings
- **Inline conflict warnings**: open conflicts are prepended to wiki context during chat so the LLM flags them to users
- **Save-to-Wiki**: promote any AI answer into a draft wiki page via the "Save to Wiki" button
- **Compact wiki**: manually trigger wiki-wide page compression

### Research Intelligence
- **Academic PDF detection**: automatically classifies whether an upload is a research paper
- **Metadata extraction**: title, authors, venue, DOI, publication year, abstract
- **Section extraction**: structured sections (intro, methods, results, discussion, conclusion)
- **Method & dataset extraction**: what methods were used, on which datasets
- **Claim extraction**: findings, limitations, hypotheses, research gaps — with evidence and grounding level
- **Citation graph**: visualizes semantic relationships between uploaded papers
- **Comparison matrix**: LLM synthesizes a cross-paper comparison table for methodologies and findings
- **Literature gap analysis**: scans all workspace claims to detect open research opportunities
- **Auto-polling**: papers in "Processing" state are auto-refreshed until complete
- **Paper deletion**: delete papers with all linked sections, methods, and claims

### Report Generation (Chat-Based)
- **Fully chat-driven**: say "generate a PDF report comparing salaries across all pages" — KnowForge dynamically builds the template, runs extraction, and returns a download link
- **Multi-format export**: PDF (WeasyPrint), XLSX (openpyxl), DOCX (python-docx)
- **Smart scoping**: BM25 pre-selects the most relevant pages; global keywords ("all", "every") expand to the full workspace
- **Structured extraction**: per-column LLM extraction with confidence scores and supporting quotes
- **Markdown-to-document rendering**: list formatting, tables, bold/italic are faithfully rendered in exports

### Workspace & RBAC
- **Multi-workspace**: create team workspaces; each has its own wiki, chat sessions, and research papers
- **RBAC roles**: `owner > admin > editor > viewer`
- **Invite via email**: send workspace invites with role assignment
- **Legacy migration**: old user-scoped storage is automatically migrated to the workspace layout on first login
- **Workspace deletion**: owners can delete workspaces with "type 'delete' to confirm" safety gate

### User & Auth
- **Register/Login/Logout**
- **Email verification**: 6-digit code sent on registration
- **JWT tokens**: stored in `localStorage`, attached to every API call
- **Configurable LLM provider**: users can connect their own OpenRouter/OpenAI/Anthropic/Gemini key per session

### Frontend UI
- **Claude-style minimalist design**: dark terracotta-toned theme, clean borderless panels
- **Three-panel sidebar**: Chats | Wiki | Research tabs with persistent state
- **Sidebar resize**: drag handle to adjust sidebar width, persisted in `localStorage`
- **Workspace switcher**: dropdown in sidebar header to switch active workspace
- **Report mode toggle**: composer button switches chat into report-generation mode
- **Processing animations**: upload zones show spinner + status text during ingestion
- **Auto-scroll and smart focus**: chat always scrolls to the latest message
- **Toast notifications**: non-blocking success/error feedback
- **Markdown rendering**: full markdown in chat (headers, bold, italic, code, tables, lists)
- **Copy/Thread/Save actions**: per-message action buttons on AI responses

---

## Project Structure

```
app/
├── api/v1/routes/       # FastAPI route handlers (auth, chat, wiki, research, reports, versions, …)
├── core/                # Config, error classes
├── db/
│   ├── models.py        # SQLAlchemy ORM models (all 20+ tables)
│   └── session.py       # DB connection factory
├── llm/                 # LangGraph chat flow graph
├── llmwiki/
│   ├── chat.py          # Main chat orchestrator (routing, CoT, verification)
│   ├── harness.py       # Deterministic routing + multi-query expansion + HyDE
│   ├── indexer.py       # Hybrid BM25 + Pinecone retrieval engine
│   ├── ingest.py        # PDF ingestion pipeline
│   ├── research.py      # Academic paper analysis pipeline
│   ├── reports.py       # Report extraction, export, and chat-driven generation
│   ├── contradictions.py# Cross-page contradiction scanner
│   ├── temporal.py      # Version ledger, supersession detection, temporal facts
│   ├── knowledge_graph.py# Entity extraction, graph expansion
│   ├── vector_store.py  # Pinecone vector client
│   ├── embedder.py      # Sentence-transformer embeddings (all-MiniLM-L6-v2)
│   ├── compaction.py    # Wiki page + conversation compaction
│   ├── storage.py       # File-based wiki page store
│   ├── prompts.py       # All LLM prompts (centralized)
│   ├── groq.py          # Groq API client
│   ├── text.py          # BM25, RRF, tokenizer, text utilities
│   └── markdown.py      # Markdown render + page serialization
├── schemas/             # Pydantic request/response schemas
├── services/            # Auth, workspace lifecycle, LLM factory, chat sessions
└── web/static/
    ├── index.html       # Single-page app shell
    ├── app.js           # All frontend logic (~3000 lines)
    └── styles.css       # Design system (~2500 lines)

storage/
└── workspaces/{workspace_id}/
    ├── pages/           # Markdown wiki pages
    ├── compact/         # Compressed page versions
    ├── sources/         # Original uploaded PDFs
    ├── events/          # contradictions.json
    └── reports/         # Generated report files

alembic/                 # Database migration scripts
```

---

## Quality & Checks

```bash
# Lint
ruff check .

# Syntax check Python
python3 -m py_compile app/**/*.py

# Syntax check JavaScript
node --check app/web/static/app.js
```

---

## Design Principles

1. **Graceful degradation**: every AI feature (HyDE, vector search, temporal extraction) has a fallback that keeps the system functional without LLM
2. **Calibrated retrieval**: BM25 scores are converted to calibrated confidence values; routing thresholds are deterministic, not arbitrary
3. **Immutable version ledger**: wiki pages are never mutated in place — every write is a new version row, enabling full audit trails
4. **Workspace isolation**: all data (wiki pages, chat sessions, research papers, reports) is strictly scoped to the active workspace
5. **Chat-first UX**: report generation, knowledge promotion, and research analysis are all accessible from the chat interface — no separate "tool" screens
