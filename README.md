# KnowForge

KnowForge is a beta v1 private knowledge operating layer for teams, researchers, students, consultants, and document-heavy workflows. It turns uploaded PDFs into a structured, searchable wiki that can be chatted with, versioned, compared, reviewed, and used to generate reports.

The project is built as a FastAPI backend with a custom vanilla HTML/CSS/JavaScript single-page app. The core idea is simple: upload documents once, then let KnowForge compile them into living knowledge that remains searchable, auditable, and useful over time.

## What KnowForge Does

KnowForge converts PDFs into Markdown wiki pages, enriches them with metadata, links related pages, tracks versions, detects contradictions, extracts time-sensitive facts, supports chat-based retrieval, and provides research/reporting tools on top of the same workspace knowledge base.

It is not only a document chat app. The beta already includes workspace collaboration, authenticated users, user-provided LLM keys, semantic version history, research-paper intelligence, report generation, proactive knowledge health checks, daily digests, notifications, and flashcard review.

## Beta v1 Features

### Document-To-Wiki Pipeline

- Upload PDFs into a workspace knowledge base.
- Extract raw page text with `pypdf`.
- Preserve table-like rows, numbered sections, schedules, annexures, and addendum headings as much as possible during extraction.
- Split long documents into controlled chunks.
- Generate chunk-level notes containing important facts, summaries, and entities.
- Synthesize a complete structured Markdown wiki page from extracted text and chunk notes.
- Store original source files under workspace-scoped storage.
- Generate stable slugs, summaries, tags, aliases, entities, source references, confidence, and freshness metadata.
- Append related-page information after knowledge graph processing.
- Recompile and update existing wiki pages.
- Delete wiki pages and their compact/vector records.

### Retrieval And Chat

- Chat with the active workspace knowledge base.
- Automatic routing between wiki-grounded answers and direct LLM answers.
- Hybrid retrieval with in-memory BM25 and optional Pinecone vector search.
- Reciprocal Rank Fusion for combining lexical and semantic search results.
- Field-weighted BM25 over title, summary, tags, entities, and content.
- Calibrated retrieval confidence to decide whether a question should use wiki context.
- Context-aware query rewriting for follow-up questions and pronouns.
- Step-back prompting and keyword expansion for broader recall.
- HyDE-style hypothetical passage generation to bridge vocabulary gaps.
- Memory/wiki-intent overrides for profile, background, and document-specific questions.
- Entity graph expansion to pull in related pages the user did not name directly.
- Multi-hop planning for harder questions.
- LLM candidate reranking before final answer generation.
- Separate answer verification pass that checks whether the response is fully, partially, or not grounded.
- Local handling for simple gratitude and small-talk paths.
- Threaded replies and comments through parent-message context.
- Conversation compaction to keep long histories within prompt budgets.
- Citations, used-page traces, route details, and agent trace metadata in responses.
- Optional Tavily-backed web search support when configured.

### Wiki Versioning And Temporal Intelligence

- Immutable version ledger for every wiki page write.
- SHA-256 content hashes to skip duplicate versions.
- Version numbers per page.
- Restore previous versions.
- Semantic diff generation with changed facts and risk level.
- Line-level diff hunks for exact content comparison.
- Supersession detection when a newer document appears to replace or amend an older one.
- Page status tracking such as approved, draft, archived, and superseded.
- Temporal fact extraction for dates, deadlines, rates, assignments, obligations, expirations, and similar time-sensitive details.
- Regex fallback for date extraction if the LLM is unavailable.
- Fact review state, review notes, and reviewed-by tracking.
- Stale fact warnings injected into relevant chat answers.

### Contradiction Detection

- Pairwise contradiction scanning across related wiki pages.
- Candidate pair selection through related slugs and entity/title overlap.
- Fingerprinting to avoid rescanning unchanged page pairs.
- Severity labels for conflicts.
- Open, dismissed, and resolved conflict states.
- Persistent workspace conflict store.
- Inline contradiction warnings included in chat context so answers can warn users about disputed facts.

### Knowledge Graph

- Entity extraction from LLM notes, titles, tags, headings, and document content.
- Entity normalization and deduplication.
- Related-page resolution through title, slug, alias, prefix, and substring matching.
- Workspace-level in-memory graph rebuilt when wiki content changes.
- BFS graph expansion with different hop limits for normal and hard questions.
- Query-term entity matching to discover useful neighboring pages.

### Compaction

- Wiki page compaction for oversized pages.
- Compact page copies are stored separately from full Markdown pages.
- Retrieval can prefer compact versions to reduce context size.
- Conversation history compaction keeps recent messages verbatim and summarizes older history.
- Fallback keyword extraction keeps compaction usable when the LLM is unavailable.

### Research Intelligence

- Research-focused PDF upload mode.
- Automatic research-paper classification.
- Metadata extraction for title, authors, venue, DOI, year, and abstract.
- Section extraction for common academic sections.
- Method and dataset extraction.
- Claim extraction for findings, limitations, hypotheses, evidence, and research gaps.
- Research analysis job status tracking.
- Citation and relation graph data between papers.
- Cross-paper comparison matrix generation.
- Literature gap analysis across workspace research claims.
- Auto-refresh polling while papers are processing.
- Paper deletion with linked sections, methods, claims, edges, insights, and jobs.

### Report Generation

- Chat-driven report generation from wiki pages.
- Report intent detection from normal chat messages.
- Dynamic report template creation from a user request.
- Scope selection from relevant pages, with global keywords expanding to the whole workspace.
- Per-page structured extraction with confidence and supporting evidence.
- XLSX exports with rows and extraction columns.
- DOCX exports with rendered Markdown content.
- PDF exports through WeasyPrint with branded HTML rendering.
- Generated files saved per workspace and downloaded through the authenticated frontend.

### Workspaces And RBAC

- Personal workspace automatically created for each user.
- Team workspace creation, renaming, switching, and deletion.
- Workspace-scoped wiki pages, chats, research papers, reports, facts, notifications, and storage.
- Role hierarchy: owner, admin, editor, viewer.
- Role checks on mutating workspace actions.
- Email invites with role assignment and expiry.
- Invite acceptance flow.
- Legacy user storage migration into workspace storage.
- Owner-only delete confirmation flow.

### Authentication And User LLM Providers

- Register, login, logout, and current-user profile flow.
- Password hashing with bcrypt/passlib.
- Email verification with 6-digit codes.
- SMTP email sending when configured.
- Console verification-code fallback for local development.
- JWT access tokens stored by the frontend and sent with API requests.
- Per-user LLM provider keys stored encrypted.
- Provider support for OpenRouter, OpenAI, Anthropic, Google Gemini, and AWS Bedrock.
- Per-user active provider and model selection.
- System Groq fallback for core workflows when user keys are not configured.

### Proactive Knowledge Layer

- Fact timeline showing expired, expiring, current, undated, and reviewed facts.
- Bulk and single fact review actions.
- Knowledge health score based on freshness, accuracy, completeness, staleness, and integrity.
- Action-item generation for stale facts, contradictions, and old pages.
- Daily knowledge digest with expiring facts, conflicts, changed pages, and suggested review pages.
- Optional digest email delivery.
- In-app notifications with unread counts and read tracking.
- Flashcard generation from wiki pages.
- Due-card queue per user.
- Spaced review state with again, hard, and easy outcomes.
- Flashcard stats including total cards, reviewed cards, due count, and mastery percentage.

### Frontend

- Custom single-page app with no frontend build step.
- Authentication screen for login, registration, and email verification.
- Resizable app sidebar.
- Workspace switcher.
- Sidebar tabs for Chats, Wiki, and Research.
- Chat session list with create, rename, load, and delete flows.
- Drag-and-drop PDF upload.
- Wiki page list, insight modal, edit/delete/version actions, and compaction action.
- Factual conflict list with scan, resolve, and dismiss actions.
- Research paper list and research modal.
- Citation graph, comparison matrix, and literature gap views.
- Chat composer with report mode.
- Reply banner for threaded conversation context.
- Markdown rendering for answers, wiki content, tables, lists, code, and links.
- Copy, thread, and save-to-wiki actions on assistant messages.
- Save-to-wiki modal for promoting answers into draft wiki content.
- LLM settings modal with provider selection, API keys, models, and Bedrock fields.
- Version history modal with semantic and line diff views.
- Knowledge health, timeline, notifications, daily digest, and flashcard review UI.
- Toast notifications, loading states, progress indicators, and responsive styling.

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend | FastAPI, Uvicorn |
| Database | PostgreSQL, SQLAlchemy 2, Alembic |
| Auth | JWT, passlib/bcrypt, SMTP verification |
| LLM Orchestration | LangGraph |
| System LLM | Groq |
| User LLM Providers | OpenRouter, OpenAI, Anthropic, Gemini, AWS Bedrock |
| Retrieval | BM25, optional Pinecone vector search, RRF fusion |
| Embeddings | sentence-transformers, all-MiniLM-L6-v2 |
| PDF/Text | pypdf, custom text normalization |
| Reports | WeasyPrint, python-docx, openpyxl |
| Frontend | Vanilla HTML, CSS, JavaScript |

## Project Structure

```text
app/
  api/                 FastAPI dependencies, router setup, and route modules
  core/                Runtime config, security, encryption, mail, shared errors
  db/                  SQLAlchemy models and database session setup
  llm/                 LangGraph chat flow and provider clients
  llmwiki/             Ingestion, retrieval, chat, graph, research, reports, temporal logic
  schemas/             Pydantic request/response models
  services/            Auth, workspaces, LLM keys, web search, proactive services
  web/static/          Vanilla SPA assets
alembic/               Database migration environment and migration history
requirements.txt       Python dependency lock-style list
.env.example           Empty environment template for local setup
```

Runtime data is created under `storage/` by default and is intentionally ignored by Git.

## Installation

### 1. Clone The Repository

```bash
git clone <your-repository-url>
cd KnowForge
```

### 2. Create A Python Environment

```bash
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Python 3.12 is recommended.

### 3. Create A PostgreSQL Database

Create a local PostgreSQL database and user that match your environment values. The default development values are:

```text
database: knowforge
user: knowforge
password: knowforge
host: localhost
port: 5432
```

You can also provide a full `DATABASE_URL` instead of separate `DB_*` values.

### 4. Configure Environment Variables

Copy the template and fill in the values you need:

```bash
cp .env.example .env
```

Important values:

```env
DATABASE_URL=
DB_HOST=localhost
DB_PORT=5432
DB_NAME=knowforge
DB_USER=knowforge
DB_PASSWORD=

JWT_SECRET_KEY=
LLM_KEY_ENCRYPTION_SECRET=

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=

ENABLE_SEMANTIC_VECTOR_SEARCH=false
PINECONE_API_KEY=
PINECONE_INDEX_NAME=knowforge

TAVILY_API_KEY=

KNOWFORGE_STORAGE_PATH=storage
```

The complete empty template is available in `.env.example`.

For local development, SMTP is optional. If SMTP is not configured, verification codes are printed in the server console.

Pinecone is optional. If semantic vector search is disabled or no Pinecone key is provided, KnowForge continues to work with BM25 retrieval.

Tavily is optional. Web search features only activate when configured.

### 5. Run Database Migrations

```bash
alembic upgrade head
```

### 6. Start The App

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## Development Checks

```bash
python3 -m py_compile $(rg --files -g '*.py')
node --check app/web/static/app.js
ruff check .
```

`node --check` is only needed if Node.js is installed locally.

## Design And Architecture Notes

KnowForge beta v1 is designed around workspace isolation. A workspace owns its wiki pages, uploaded sources, chat sessions, research papers, reports, contradictions, fact events, notifications, flashcards, and generated storage files.

The retrieval system is intentionally layered. BM25 provides deterministic lexical recall, optional Pinecone vectors provide semantic recall, and RRF combines both rankings. The harness then expands queries, follows graph links, applies routing overrides, reranks candidates, and builds the final context.

The wiki is treated as a living record rather than a disposable answer cache. Pages are written as Markdown files for readability, while important audit and intelligence data is stored in PostgreSQL. Every meaningful page write creates an immutable version row.

The app is also built to degrade gracefully. If Pinecone is not configured, BM25 still works. If SMTP is unavailable, local verification codes are logged. If some LLM enrichment fails, the system falls back where possible instead of stopping the whole workflow.

## Current Beta Limitations

- The frontend is a large vanilla JavaScript SPA, so contributors should be careful when editing shared UI state.
- Background processing is lightweight and in-process; production deployments may want a dedicated worker queue.
- Runtime storage is local filesystem based by default.
- LLM quality, cost, and latency depend on the configured provider and model.
- The project currently focuses on PostgreSQL.

## Git Hygiene

The repository intentionally ignores:

- `.env`
- virtual environments
- Python caches
- test/lint caches
- runtime `storage/`
- local OS files

Do not commit real API keys, generated reports, uploaded PDFs, local databases, or runtime workspace data.

## Contributing

Contributions are welcome.

Good areas to help with:

- Tests for ingestion, retrieval routing, versioning, reports, and workspace permissions.
- Smaller frontend modules to reduce the size of `app/web/static/app.js`.
- More robust background job handling for long PDF, research, and report workflows.
- Better document extraction for complex tables and scanned PDFs.
- Additional LLM provider polish and model presets.
- Improved deployment documentation.
- UI accessibility and responsive behavior fixes.
- Performance profiling for large workspaces.

Before opening a pull request:

- Keep changes focused and easy to review.
- Avoid committing secrets or generated runtime files.
- Run the available checks.
- Include a clear explanation of the problem and the solution.
- Add or update tests when changing behavior.

KnowForge is in beta v1, so thoughtful issues, bug reports, documentation improvements, and architectural suggestions are all valuable.
