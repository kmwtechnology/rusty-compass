# Rusty Compass

A production-grade **LangGraph agent** for multi-capability Lucille pipeline automation:

- 🤖 **RAG Q&A** — Intelligent question answering over Lucille documentation with hybrid search
- 🔧 **Config Builder** — Generate valid HOCON pipeline configs from natural language with LLM + validator loop
- 📚 **Documentation Writer** — Create blog posts, tutorials, and technical articles with intelligent content type classification

Built on **Google Gemini AI**, deployed on **GCP Cloud Run**, featuring real-time streaming, hybrid search with reranking, and live pipeline observability.

## Quick Start

### Local Development

```bash
cd langchain_agent
./scripts/setup.sh    # One-time setup (10-20 min)
./scripts/start.sh    # Start backend + frontend → http://localhost:5173
```

### Cloud Deployment (GCP)

```bash
cd langchain_agent
./scripts/deploy.sh --project <GCP_PROJECT_ID>
```

Deploys to Cloud Run with Cloud SQL (PostgreSQL), OpenSearch (document search),
Secret Manager, and Artifact Registry. Scales to zero when idle.

## What is It?

A multi-capability RAG agent powered by Google Gemini AI that combines:

- **Three Operating Modes** - RAG Q&A, Config Builder, Documentation Writer with **Workflow State Management**
- **Intelligent Mode Transitions** - Detects continuation vs. soft shifts vs. hard shifts; auto-resets stale context on mode changes
- **Intent Classification** - 5 intents (question, config_request,
  documentation_request, summary, follow_up) with 95%+ accuracy
- **Content Type System** - 5 content types (social post, blog, technical
  article, tutorial, comprehensive docs) with code-based vagueness detection
- **LangGraph Pipeline** - Deterministic graph-based orchestration with
  dynamic query evaluation and conditional routing
- **Hybrid Search** - Vector + full-text search with Reciprocal Rank
  Fusion (RRF)
- **LLM-Based Reranking** - Gemini Flash Lite reranker for improved
  relevance scoring
- **Dynamic Alpha** - Query-aware lexical/semantic balance with
  bidirectional refinement
- **Real-Time Streaming** - Token-by-token output via WebSocket with
  cancellation support
- **Observability Panel** - Live pipeline visualization showing every node
  execution, timing, search scores, and classification details
- **Smart Citations** - GitHub-linked document references with
  relevance-based suppression

## Workflow State Management

The agent intelligently manages state transitions across its three operating modes (RAG Q&A, Config Builder, Documentation Writer):

**Mode Transition Types:**
- **Continuation** — Same mode as previous turn (e.g., follow-up question while in RAG mode)
- **Soft Shift** — Ambiguous continuation (e.g., "tell me more" while in Config Builder mode) — stays in prior mode
- **Hard Shift** — Explicit mode change (e.g., "build me a config" while in RAG mode) — switches modes and clears stale context

**Smart Context Handling:**
- Detects whether user is refining prior work or starting fresh
- Auto-resets stale state fields (config_components, doc_outline, retrieved_documents) on hard shifts
- Prevents "awaiting clarification" traps when users abandon prior context
- Provides explicit feedback: "Switching to pipeline configuration — ..." or "Continuing from the documentation..."

**Test Coverage:** 37 comprehensive unit tests cover all transition permutations, edge cases, and state cleanup logic.

## Architecture

### System Overview

```mermaid
flowchart TB
    subgraph UI["User Interfaces"]
        CLI["CLI<br/>(main.py)"]
        WEB["Web UI<br/>(React + TypeScript)"]
    end

    subgraph Pipeline["LangGraph Pipeline"]
        IC["Intent Classifier"]
        QE["Query Evaluator<br/>Set α"]
        CTC["Content Type<br/>Classifier"]
        RET["Retriever<br/>Hybrid Search + Rerank"]
        AGENT["Agent / Generators"]
    end

    subgraph Search["Hybrid Search Pipeline"]
        VS["Vector Search<br/>(768-dim embeddings)"]
        TS["Full-Text Search<br/>(Lucene BM25)"]
        RRF["RRF Fusion<br/>(min-max normalization)"]
        RERANK["Gemini Reranker<br/>LLM-as-reranker"]
    end

    subgraph Storage["OpenSearch + PostgreSQL"]
        DOCS["Documents & Chunks<br/>(OpenSearch)"]
        IDX["knn_vector + BM25"]
        MEM["Conversation Checkpoints<br/>(PostgreSQL)"]
    end

    subgraph GoogleAI["Google Gemini AI"]
        LLM["gemini-2.5-flash"]
        LITE["gemini-2.5-flash-lite<br/>(classifier + reranker)"]
        EMB["gemini-embedding-001<br/>(3072-dim)"]
    end

    UI --> IC
    IC -->|question/follow_up| QE
    IC -->|documentation_request| CTC
    QE --> RET
    RET --> Search
    VS --> RRF
    TS --> RRF
    RRF --> RERANK
    RERANK --> AGENT
    CTC --> AGENT
    AGENT --> LLM
    AGENT --> UI
    Search --> Storage
    AGENT --> MEM
    VS --> EMB
```

### Agent Pipeline Flow

```text
intent_classifier
  ├── question/follow_up → query_expansion → query_evaluator → retriever → alpha_refiner → agent
  ├── config_request     → config_resolver → config_generator → config_validator ─→ config_response
  │                            ↑                                    │
  │                            └──── invalid (≤2 retries) ──────────┘
  ├── documentation_request → content_type_classifier
  │     ├── social_post         → social_content_generator
  │     ├── blog_post           → blog_content_generator
  │     ├── technical_article   → article_content_generator (3 retrieval passes)
  │     ├── tutorial            → tutorial_generator
  │     ├── comprehensive_docs  → doc_planner → doc_synthesizer (5 section passes)
  │     ├── missing_format      → format_clarification → (re-classify)
  │     └── missing_topic       → topic_clarification → (re-classify)
  ├── summary            → summary
  └── follow_up          → query_expansion → query_evaluator → retriever → agent
```

### Content Type System

| Type | Target Length | Temp | Retrieval Passes | Typical Time |
| ------ | ------------- | ------ | ------------------ | ------------- |
| social_post | 200 words | 0.8 | 1 | ~6s |
| blog_post | 1500 words | 0.7 | 2 | ~20s |
| technical_article | 1200 words | 0.5 | 3 | ~25s |
| tutorial | 1000 words | 0.4 | 2 | ~20s |
| comprehensive_docs | 2500 words | 0.3 | 5 sections | ~50s |

When a documentation request is missing format or topic, code-based
vagueness detection identifies what's missing and asks for clarification
before proceeding.

### Config Builder

Generates **valid, production-ready HOCON pipeline configurations** from natural language with LLM + Java validator loop.

```text
                      user request
                           ↓
   config_resolver ──→ config_generator ──→ config_validator ──valid──→ config_response
                       ↑                          │
                       │                          ↓
                       └──────── invalid (≤2) ────┘
```

**How it works:**

1. **Component Resolution** — Parses user request to identify 88 Lucille components (stages, connectors, indexers) using deterministic catalog lookup + vector store fallback
2. **Few-Shot Generation** — 5 curated example configs (CSV→Solr, S3→OpenSearch, DB→OpenSearch, etc.) selected by component overlap, injected into generation prompt
3. **Config Generation** — Gemini generates HOCON config with proper syntax (connectors array, pipelines.stages nesting, indexer block, env overrides)
4. **Validation Loop** — Java validator checks config syntax + required properties. If invalid, errors fed back to LLM for correction (up to 2 retries)

**Key Features:**

| Feature | Detail |
|---------|--------|
| **Component Catalog** | 88 components (66 stages, 10 connectors, 7 indexers, 4 file handlers) extracted from Lucille's Java `Spec` definitions |
| **Spec Resolution** | Catalog-first deterministic lookup (100% accuracy) → vector store fallback |
| **Few-Shot Examples** | 5 real Lucille configs, matched by component overlap with user's request |
| **Validation** | Lucille's `Runner.runInValidationMode()` (standalone, no external connections needed) |
| **Retry Loop** | Up to 2 retries with error context when validation fails |
| **Graceful Fallback** | Works without Java validator (validation skipped, just logs warning) |
| **Test Coverage** | 37 workflow state management tests + 35 config builder unit tests + 20 stress tests with 95%+ pass rate |

**Regenerate catalog** (after Lucille adds new components):

```bash
cd langchain_agent
python scripts/extract_specs.py
```

**Run tests**:

```bash
cd langchain_agent && source .venv/bin/activate

# Workflow state management tests (mode transitions, routing, state cleanup)
python -m pytest tests/unit/test_mode_transitions.py -v

# Config builder tests (unit only, fast)
python -m pytest tests/config_builder/ -v -k "not live"

# Config builder full test suite (requires GOOGLE_API_KEY)
python -m pytest tests/config_builder/ -v

# All unit tests
python -m pytest tests/unit/ -v
```

**Example Usage:**

```text
User: "Build a pipeline that reads CSV, renames columns, and indexes into OpenSearch"

Config Builder:
1. Resolves: CSVConnector, RenameFields (stage), OpenSearchIndexer
2. Selects few-shot examples: opensearch_ingest (has CSV + OpenSearch)
3. Generates HOCON config with correct nesting
4. Validates with Lucille validator → VALID ✓
5. Returns working config ready to deploy
```

## Tech Stack

| Category | Technology | Purpose |
|----------|-----------|---------|
| **LLM & AI** | Google Gemini 2.5 Flash | Primary generation and reasoning model |
| **Classifier** | Gemini 2.5 Flash Lite | Intent classification + content type detection |
| **Embeddings** | Gemini Embedding 001 | 768-dimensional semantic vectors |
| **Reranker** | Gemini 2.5 Flash Lite | LLM-as-reranker for relevance scoring |
| **Agent Framework** | LangGraph + LangChain | Graph-based pipeline orchestration |
| **Vector Search** | OpenSearch | 768-dim knn_vector with Lucene |
| **Full-Text Search** | OpenSearch (BM25) | Keyword indexing and retrieval |
| **Memory Store** | PostgreSQL (Cloud SQL) | LangGraph checkpoints + conversation state |
| **Config Validation** | Lucille Java Validator | HOCON config validation + error feedback |
| **Backend** | FastAPI + WebSocket | REST API with real-time streaming |
| **Frontend** | React 18 + TypeScript + Tailwind | Web UI with Zustand state management |
| **Deployment** | GCP Cloud Run + Cloud SQL | Serverless container orchestration |
| **Containerization** | Docker (multi-stage) | Frontend build + Python runtime |

## Example Queries

**RAG Q&A** (question intent):

```text
What is a Lucille Connector and how does it work?
```

**Config Builder** (config_request intent):

```text
Build me a CSV to OpenSearch pipeline with a regex stage
```

**Documentation Writer** (documentation_request intent):

```text
Write a technical article about the FileConnector
Write a LinkedIn post about Lucille's stage architecture
Create comprehensive documentation for the OpenSearch indexer
Write a tutorial on building custom connectors
```

**Summary** (summary intent):

```text
Summarize our conversation so far
```

**Follow-up** (follow_up intent):

```text
How about combining them?   → auto-expands with conversation context
```

## Observability Panel

The web UI includes a real-time observability panel that shows:

- **Intent Classification** - Detected intent with confidence score
- **Query Evaluation** - Alpha value and query type classification
- **Content Type Classification** - Detected content type with confidence
- **Hybrid Search Results** - Vector + full-text scores, RRF fusion
- **Reranker Results** - Per-document relevance scores
- **Alpha Refinement** - Retry strategy when initial search scores low
- **Config Resolver** - Per-component resolution details (catalog-matched
  vs search-fallback), class names, and descriptions
- **Config Validation** - Lucille validator results, retry attempts,
  error details per component
- **Token Streaming** - Live generation progress with timing

Each pipeline node shows execution time, status (running/complete/skipped),
and expandable detail cards.

## Key Techniques

| Technique | Description |
| ----------- | ------------- |
| **Intent Classification** | 5-intent detection (95%+ accuracy) using keyword fast-path + LLM fallback |
| **Content Type Classification** | 5 content types with code-based vagueness detection for missing format/topic |
| **Config Builder** | Generates HOCON pipeline configs with 88-component catalog, few-shot examples, and Java validator loop |
| **Documentation Writer** | Multi-pass content generation with per-type temperature and retrieval strategies |
| **Reciprocal Rank Fusion** | Combines vector and full-text rankings: `score = Σ 1/(rank + k)` where k=60 |
| **LLM-Based Reranking** | Gemini Flash Lite scores query-document relevance (0.0-1.0) |
| **Dynamic Alpha** | Query evaluator classifies query type and sets optimal α for hybrid search balance |
| **Bidirectional Alpha Refinement** | Retries with opposite search strategy if max relevance < 0.5 |
| **Smart Citations** | GitHub-linked references with suppression when max relevance < 10% |
| **Query Expansion** | Enriches vague follow-ups with conversation context before search |
| **Streaming Cancellation** | Stop button cancels backend execution via WebSocket task coordination |

## Directory Structure

```text
rusty-compass/
├── README.md                     # This file
├── docker-compose.yml            # PostgreSQL + PGVector (local dev)
├── langchain_agent/
│   ├── scripts/
│   │   ├── setup.sh              # One-time local setup (Docker + venv + DB init)
│   │   ├── start.sh              # Start local services (backend + frontend)
│   │   ├── stop.sh               # Stop all services
│   │   ├── logs.sh               # View service logs
│   │   ├── deploy.sh             # GCP Cloud Run deployment (builds Docker + deploys)
│   │   ├── gcp-init.sh           # Cloud SQL + OpenSearch initialization (one-time)
│   │   ├── gcp-teardown.sh       # Remove all GCP resources
│   │   ├── teardown.sh           # Full local cleanup
│   │   └── extract_specs.py      # Extract Lucille component SPEC definitions → catalog
│   ├── api/                      # FastAPI backend
│   │   ├── main.py               # API routes + WebSocket
│   │   ├── schemas/events.py     # Observable event models (Pydantic)
│   │   └── services/             # Observable agent service
│   ├── web/                      # React frontend
│   │   └── src/components/
│   │       └── ObservabilityPanel/  # Real-time pipeline visualization
│   ├── main.py                   # LangGraph agent + all graph nodes
│   ├── config.py                 # Configuration constants
│   ├── content_generators.py     # 5 content type generators + classifier
│   ├── config_builder.py         # Config Builder (catalog + few-shot + validator loop)
│   ├── lucille_validator.py      # Python wrapper for Lucille Java config validator
│   ├── data/
│   │   └── component_catalog.json  # 88-component catalog (generated by extract_specs.py)
│   ├── vector_store.py           # Hybrid search (vector + full-text + RRF)
│   ├── reranker.py               # LLM-based reranking (Gemini)
│   ├── agent_state.py            # LangGraph state TypedDict
│   ├── setup.py                  # Database initialization
│   ├── Dockerfile                # Multi-stage build (Node + Python)
│   └── ingest_lucille_docs.py    # Documentation ingestion
└── sample_docs/                  # Sample knowledge base documents
```

## Search Optimization

### Alpha Parameter

The Query Evaluator dynamically sets alpha based on query type:

| α Range | Strategy | Best For |
| --------- | ---------- | ---------- |
| 0.00-0.15 | Pure Lexical | Class names, identifiers, version numbers |
| 0.15-0.40 | Lexical-Heavy | Specific APIs, configurations |
| 0.40-0.60 | Balanced | Feature tutorials, patterns |
| 0.60-0.75 | Semantic-Heavy | How-to, architecture questions |
| 0.75-1.00 | Pure Semantic | Conceptual "What is" questions |

### Tunable Parameters

```bash
RRF_K=60                           # Reciprocal Rank Fusion constant (30-100)
ENABLE_EMBEDDING_CACHE=true        # Enable query embedding cache
EMBEDDING_CACHE_MAX_SIZE=100       # Max cached embeddings
QUERY_EVAL_MODEL=gemini-2.5-flash-lite  # Alpha estimator model
```

## Deployment

### GCP Cloud Run

The `deploy.sh` script handles the full deployment:

1. Enables required GCP APIs (Cloud Run, SQL, Artifact Registry, Secret Manager)
2. Creates Cloud SQL PostgreSQL instance (checkpoints only)
3. Stores secrets (GOOGLE_API_KEY, API_KEY, DB_PASSWORD, OpenSearch credentials)
   in Secret Manager
4. Builds multi-stage Docker image (React frontend + Python backend)
5. Pushes to Artifact Registry
6. Deploys to Cloud Run with Cloud SQL proxy

**Cost controls**:

- `min-instances=0` (scales to zero when idle)
- `max-instances=2` (prevents runaway scaling)
- CPU throttling (CPU only during requests)
- Cloud SQL `db-f1-micro` tier

```bash
# Deploy to Cloud Run
./scripts/deploy.sh --project <PROJECT_ID>

# Initialize Cloud SQL + ingest docs to OpenSearch (one-time after first deploy)
./scripts/gcp-init.sh --project <PROJECT_ID>

# View logs
gcloud logging read resource.type=cloud_run_revision --project=<PROJECT_ID>

# Remove all GCP resources (expensive instances)
./scripts/gcp-teardown.sh --project <PROJECT_ID>
```

**Note**: OpenSearch is hosted externally (GCP VM at 34.138.97.13:9200). Credentials
are stored in Secret Manager as `rusty-compass-opensearch-user` and
`rusty-compass-opensearch-password`.

### Local Development

Copy `.env.example` to `.env` and fill in your credentials before running
setup:

```bash
cd langchain_agent
cp .env.example .env   # Then edit .env with your GOOGLE_API_KEY and API_KEY
./scripts/setup.sh    # Creates venv, starts PostgreSQL, ingests docs
./scripts/start.sh    # Starts backend (port 8000) + frontend (port 5173)
./scripts/stop.sh     # Stops all services
./scripts/teardown.sh # Full cleanup (containers, venv, data)
```

**Prerequisites**: Docker, Python 3.13, Node.js 18+, Maven, Java 17+,
Google API Key ([get one here](https://aistudio.google.com/apikey))

## Link Verification & Citation Quality

All citations are automatically validated before being sent to the LLM:

- **Link Verification**: Each URL is checked for accessibility
  (200-299 status codes)
- **Broken Link Replacement**: If a URL returns 404 or timeout, automatically
  replaced with a valid alternative
- **Smart Caching**: Verification results cached for 60 minutes (TTL)
  to reduce API calls
- **Javadoc Mapping**: Javadoc sources map to Maven Central (javadoc.io)
  instead of broken GitHub paths

**Javadoc URL Mapping**:

- Local: Generated from Lucille javadoc (`target/site/apidocs/`)
- Deployed: `https://javadoc.io/doc/com.kmwllc/lucille-core/latest/{class-path}.html`
- Regular docs: GitHub URLs (`doc/site/content/en/docs/...`)

---

## Performance

### Latency Benchmarks

| Operation | Typical Time | Notes |
|-----------|------------|-------|
| **RAG Q&A** | 10-30s | End-to-end with search + reranking |
| **Config Builder** | 3-8s | Generation + validation (first attempt) |
| **Config Builder (with retry)** | 5-12s | If validation fails, max 2 retries |
| **Social Post** | ~6s | 200-300 words, 1 retrieval pass |
| **Blog Post** | ~20s | 1500-2000 words, 2 retrieval passes |
| **Technical Article** | ~25s | 1200-1500 words, 3 retrieval passes |
| **Tutorial** | ~20s | 1000 words, 2 retrieval passes |
| **Comprehensive Docs** | ~50s | 2500+ words, 5 section passes |
| **Hybrid Search** | ~2-3s | Vector + BM25 with RRF fusion |
| **LLM Reranking** | ~2-3s | 40 docs → 10 docs |
| **Query Evaluation** | ~1-2s | Alpha parameter detection |
| **Link Verification** | ~50ms | Per URL (cached) |

### Validation Results

- **Config Builder**: 95% pass rate on 20-query stress test across all component types
- **Intent Classification**: 95%+ accuracy across 5 intent classes
- **Catalog Resolution**: 100% accuracy (88/88 components)

---

## Troubleshooting

### Config Builder Issues

**"Validation skipped: Lucille validator not available"**
- Requires: Java 17+, Lucille built with `mvn package`
- Fix: `cd ../lucille && mvn package -DskipTests`

**"Unknown component: X"**
- Regenerate catalog: `python scripts/extract_specs.py`
- Restart backend: `./scripts/stop.sh && ./scripts/start.sh`

**"Config validation failed after 2 attempts"**
- This is expected for complex pipelines or model limitations
- Check observability panel for specific validation errors
- Consider simpler pipeline or provide more explicit instructions

### General Setup Issues

**ImportError: No module named 'X'**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**Services won't start**
```bash
# Check prerequisites are running
docker compose ps
# Check ports are free
lsof -i :8000  # Backend
lsof -i :5173  # Frontend
lsof -i :9200  # OpenSearch
```

**npm dependencies missing (after disk cleanup)**
```bash
# start.sh auto-installs, or manually:
cd langchain_agent/web
npm install
cd ..
./scripts/start.sh
```

---

**Status**: ✅ Production Deployed on GCP Cloud Run
