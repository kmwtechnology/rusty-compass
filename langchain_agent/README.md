# Rusty Compass - Backend Implementation

Backend implementation of the Rusty Compass multi-capability LangGraph agent. See [../README.md](../README.md) for the complete project overview.

This directory contains:
- **LangGraph Pipeline** — Three operating modes (RAG Q&A, Config Builder, Documentation Writer)
- **FastAPI Backend** — REST API with WebSocket streaming
- **React Frontend** — Web UI with observability panel
- **Data Layer** — OpenSearch (hybrid search) + PostgreSQL (conversation state)
- **Integration** — Google Gemini AI, Lucille validator, vector embeddings

**Capabilities**:

- **RAG Q&A**: Hybrid search + reranking + self-improving retrieval for Lucille documentation
- **Config Builder**: Generate valid HOCON pipeline configs from natural language requests
- **Documentation Writer**: 5 content types with intelligent classification and optimized retrieval
  - **Social Posts** (100-300 words, 1 pass, ~6s) - Engaging LinkedIn/Twitter content
  - **Blog Posts** (1000-2000 words, 2 passes, ~20s) - Narrative articles with examples
  - **Technical Articles** (800-1500 words, 3 passes, ~25s) - Deep-dive analysis with code
  - **Tutorials** (1000 words, 2 passes, ~20s) - Step-by-step instructional guides
  - **Comprehensive Docs** (2500+ words, 5 passes, ~50s) - Full reference documentation

**Key Components**:

- **Backend**: Python (FastAPI) with LangGraph + LangChain
- **Frontend**: React 18 + TypeScript + Tailwind
- **Data Layer**: OpenSearch (document search + hybrid search) | PostgreSQL (checkpoints only)
- **LLM**: Google Gemini AI (gemini-2.5-flash, gemini-2.5-flash-lite)

---

## Quick Start

### Prerequisites

```bash
# Check you have these installed:
docker --version          # Docker Desktop
python3 --version         # Python 3.11+
node --version            # Node.js 18+
mvn --version             # Maven (for javadoc generation)
```

If not installed:

- **Docker**: <https://docker.com>
- **Python**: <https://python.org>
- **Node.js**: <https://nodejs.org>
- **Maven**: <https://maven.apache.org> (requires Java 17+)

**Additional Requirements**:

- **Google API Key**: Get one from <https://aistudio.google.com/apikey>
- Set `GOOGLE_API_KEY` in your `.env` file

### Setup (One-time)

```bash
cd langchain_agent
./scripts/setup.sh
```

This takes 10-20 minutes on first run and will:

1. Generate secure API keys
2. Install Python and frontend dependencies
3. Start PostgreSQL
4. Initialize database
5. Generate Lucille javadocs via Maven
6. Validate Google AI API key
7. Load Lucille documentation (~512 API classes)

### Start Services

```bash
cd langchain_agent
./scripts/start.sh
```

Then open: <http://localhost:5173>

To re-generate and load Lucille javadocs:

```bash
cd ../lucille
mvn javadoc:aggregate
cd ../rusty-compass/langchain_agent
python ingest_lucille_docs.py
```

### Stop Services

```bash
./scripts/stop.sh
```

This stops the backend, frontend, and Docker containers (PostgreSQL, OpenSearch, OpenSearch Dashboards).

### Teardown (Complete Removal)

To completely remove all installed components, data, and containers:

```bash
./scripts/teardown.sh
```

This removes:
- Python virtual environment
- Frontend node_modules
- Docker containers and volumes
- Local database and vector store
- All cached files

**Warning**: This is non-recoverable. Use with caution in production.

---

## Project Structure

```
langchain_agent/
├── api/                          # FastAPI backend
│   ├── main.py                   # Routes, WebSocket, server startup
│   └── schemas/events.py         # Observable event types
│
├── main.py                       # LangGraph agent definition
├── config.py                     # Configuration constants
├── agent_state.py                # LangGraph state definition
│
├── config_builder.py             # Config generation + validation
├── lucille_validator.py          # Lucille HOCON config validator
├── content_generators.py         # Documentation writers
├── vector_store.py               # Hybrid search (vector + BM25)
├── reranker.py                   # LLM-based reranking
│
├── scripts/                      # Deployment and setup automation
│   ├── setup.sh                  # One-time setup
│   ├── start.sh                  # Start services
│   ├── stop.sh                   # Stop services
│   ├── deploy.sh                 # Deploy to GCP Cloud Run
│   ├── gcp-init.sh              # Initialize GCP resources
│   └── extract_specs.py          # Extract Lucille component specs
│
├── data/                         # Static data
│   └── component_catalog.json    # 88-component Lucille catalog
│
├── tests/                        # Test suite
│   ├── config_builder/           # Config builder tests (35 unit + 20 stress)
│   ├── unit/                     # Component unit tests
│   ├── integration/              # Multi-component integration tests
│   └── e2e/                      # Deployment validation tests
│
├── web/                          # React frontend
│   ├── src/                      # React components
│   ├── public/                   # Static assets
│   └── package.json              # Frontend dependencies
│
├── requirements.txt              # Python dependencies
├── requirements-dev.txt          # Development tools (pytest, etc.)
├── .env.example                  # Environment configuration template
└── README.md                     # This file
```

---

## Key Components

### Config Builder

Generates valid Lucille HOCON pipeline configurations from natural language.

```text
User: "CSV to OpenSearch with field renaming"
  ↓
Catalog Resolution (CSVConnector, RenameFields, OpenSearchIndexer)
  ↓
Few-Shot Selection (opensearch_ingest example)
  ↓
LLM Generation (Gemini)
  ↓
Lucille Validation (Java validator)
  ↓
Response (valid config + validation status)
```

**Features:**
- 88-component catalog with deterministic resolution
- 5 curated few-shot example configs
- Lucille's own Java validator for config syntax checking
- Up to 2 retries when validation fails
- 95% pass rate on diverse config combinations

See [../README.md#config-builder](../README.md#config-builder) for detailed documentation.

### Hybrid Search

Vector + full-text search with Reciprocal Rank Fusion (RRF) and LLM reranking.

```
Query
  ↓
Embedding (Gemini) + BM25 Tokenization
  ↓
Vector Search (OpenSearch knn_vector) + Full-Text Search (BM25)
  ↓
RRF Fusion (combines rankings)
  ↓
LLM Reranking (Gemini scores relevance)
  ↓
Final Results (top K documents)
```

**Features:**
- Dynamic alpha parameter (lexical vs semantic balance)
- Reciprocal Rank Fusion for balanced results
- Gemini Flash Lite LLM-as-reranker
- Cached embeddings for performance
- Query expansion for follow-up questions

### Intent Classification

5 intent types with keyword fast-path + LLM fallback.

| Intent | Handler | Example |
|--------|---------|---------|
| `question` | RAG Q&A | "What is a Lucille connector?" |
| `config_request` | Config Builder | "Build a CSV to OpenSearch pipeline" |
| `documentation_request` | Documentation Writer | "Write a blog post about connectors" |
| `summary` | Conversation Summary | "Summarize our conversation" |
| `follow_up` | Query Expansion | "How about using Pinecone instead?" |

95%+ accuracy, typically <100ms classification time.

---

## Testing

Full test coverage with 35+ unit tests, 20 stress tests, and integration tests.

### Quick Test

```bash
# Unit tests (no dependencies, ~1s)
source .venv/bin/activate
python -m pytest tests/config_builder/ -v -k "not live"
```

### Full Test Suite

```bash
# Start services first
./scripts/start.sh

# Run all tests
source .venv/bin/activate
python -m pytest tests/ -v
```

See [tests/README.md](tests/README.md) for comprehensive testing documentation.

---

## Deployment

### Local Development

Default setup with Docker + Python + Node:

```bash
./scripts/setup.sh   # ~10-20 min, one-time
./scripts/start.sh   # Starts everything
# Visit http://localhost:5173
```

### GCP Cloud Run

Production deployment with auto-scaling:

```bash
./scripts/deploy.sh --project <GCP_PROJECT_ID>
./scripts/gcp-init.sh --project <GCP_PROJECT_ID>  # One-time DB setup
```

Features:
- Auto-scales to zero (cost-efficient)
- Cloud SQL for PostgreSQL
- Secret Manager for credentials
- Cloud Run for containerized backend
- Artifact Registry for images

See [../README.md#deployment](../README.md#deployment) for detailed instructions.

---

## Environment Configuration

Copy `.env.example` to `.env` and adjust:

```bash
cp .env.example .env
# Edit .env with your credentials:
# - GOOGLE_API_KEY (required)
# - API_KEY (secure random key)
# - POSTGRES_* (if not using Docker defaults)
# - LUCILLE_PROJECT_DIR (path to Lucille, for config builder)
```

Key variables:
- `GOOGLE_API_KEY` — Google Gemini API key (required)
- `ENABLE_CONFIG_VALIDATION` — Toggle validator on/off
- `CONFIG_VALIDATION_MAX_RETRIES` — Retry attempts (default: 2)
- `LUCILLE_PROJECT_DIR` — Path to Lucille source (for config builder)
- `LLM_MODEL` — LLM to use (default: gemini-2.5-flash)

---

## Troubleshooting

**Port already in use**
```bash
# Find and kill process on port 8000 (backend)
lsof -i :8000 | awk 'NR>1 {print $2}' | xargs kill -9
```

**Python dependencies out of sync**
```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

**Frontend won't start (npm issue)**
```bash
# start.sh auto-installs, but if needed:
cd web && npm install && cd ..
```

**Lucille validator not found**
```bash
# Build Lucille
cd ../lucille && mvn package -DskipTests
cd ../rusty-compass/langchain_agent && ./scripts/start.sh
```

See [../README.md#troubleshooting](../README.md#troubleshooting) for more issues.

This removes:

- Running services
- PostgreSQL container and volumes
- Python virtual environment
- Node modules
- Log files
- Optionally: .env file

---

## Usage

### Web UI

1. Visit <http://localhost:5173>
2. Type a message in the chat box
3. Press Enter to send
4. Watch the agent think and respond in real-time

### CLI (No Web UI)

```bash
cd langchain_agent
source .venv/bin/activate
python main.py
```

### API

All endpoints require the `X-API-Key` header (or `?api_key=` query param):

```bash
# Health check
curl -H "X-API-Key: $(grep API_KEY .env | cut -d= -f2)" \
  http://localhost:8000/api/health
```

### Example Queries

**RAG Q&A (Lucille Documentation):**
- "What is Lucille?"
- "How do I create a pipeline?"
- "What stages are available?"
- "How do I configure a connector?"
- "What is the RunMode interface?"

**Config Builder:**
- "Build me a CSV to OpenSearch pipeline"
- "Create a config for PDF ingestion with CopyFields and SetStaticField stages"
- "Generate a pipeline config that reads from Kafka and writes to Solr"

**Documentation Writer:**
- "Write a LinkedIn post about CSVConnector" (social post)
- "Create a blog post about hybrid search" (blog post)
- "Write a technical article analyzing the reranker" (technical article)
- "Create a tutorial for building a CSV pipeline" (tutorial)
- "Document all Lucille connectors" (comprehensive docs)

---

## Configuration

All settings in `config.py` or via `.env` file:

```python
# Models (Google Gemini AI)
LLM_MODEL = "gemini-2.5-flash"
EMBEDDINGS_MODEL = "models/gemini-embedding-001"
RERANKER_MODEL = "gemini-2.5-flash-lite"     # LLM-based reranker (Gemini)
QUERY_EVAL_MODEL = "gemini-2.5-flash-lite"   # Lightweight query evaluator
QUERY_EVAL_TEMPERATURE = 0
QUERY_EVAL_MAX_TOKENS = 1024

# OpenSearch (Document Search)
OPENSEARCH_HOST = "localhost"                 # Local: localhost:9200, GCP: 34.138.97.13:9200
OPENSEARCH_PORT = 9200
OPENSEARCH_INDEX_NAME = "rusty_compass_docs"
OPENSEARCH_USE_SSL = false                    # Local dev: false, GCP: true

# PostgreSQL (Checkpoints Only)
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "postgres"
POSTGRES_DB = "langchain_agent"

# Retrieval
RETRIEVER_K = 4              # Final documents
RETRIEVER_FETCH_K = 30       # Candidates before reranking
RETRIEVER_ALPHA = 0.25       # Balance: 0.0 (lexical/BM25) to 1.0 (semantic/vector)

# Reranking (Gemini LLM-as-Reranker)
ENABLE_RERANKING = True
RERANKER_FETCH_K = 40                        # Candidates before reranking
RERANKER_TOP_K = 10                          # Final documents after reranking

# Reflection Loop
ENABLE_REFLECTION = True
ENABLE_DOCUMENT_GRADING = True
ENABLE_RESPONSE_GRADING = True
REFLECTION_MAX_ITERATIONS = 2

# Multi-Capability Agent
ENABLE_CONFIG_BUILDER = True   # Config builder pipeline
ENABLE_DOC_WRITER = True       # Documentation writer pipeline
```

See `.env.example` for all available options.

### Multi-Capability Agent Feature Flags

The agent automatically routes requests based on user intent. Feature flags control which capabilities are available:

| Flag | Default | Capability | Description |
|------|---------|-----------|-------------|
| `ENABLE_CONFIG_BUILDER` | `True` | Config Builder | Generates Lucille HOCON pipeline configurations from natural language requests |
| `ENABLE_DOC_WRITER` | `True` | Documentation Writer | Creates 5 content types (social/blog/article/tutorial/comprehensive) with intelligent classification |
| `ENABLE_CONTENT_TYPE_CLASSIFICATION` | `True` | Content Type Sub-Classification | Enables LLM-based routing between the 5 documentation content types |

**Intent Routing:**

When both flags are enabled, the intent classifier automatically routes requests:

- **Questions** ("What connectors are available?", "How do I configure X?") → RAG Q&A pipeline (DEFAULT)
- **Config Requests** ("Build me a CSV to Solr pipeline") → Config Builder pipeline
- **Documentation Requests** ("Write a tutorial on X", "Create a guide", "Write documentation for X") → Documentation Writer pipeline → Content Type Classifier → Appropriate Generator (social/blog/article/tutorial/comprehensive)
- **Summaries** ("Summarize our conversation") → Summary generator

**Key Distinction:**
- **Conversational Q&A** (questions expecting direct answers) → RAG Q&A pipeline
- **Publication content** (tutorials, guides, articles, blogs, API docs) → Documentation Writer pipeline

**All 5 Intents:**

| Intent | Pipeline | Examples | Trigger Keywords |
|--------|----------|----------|------------------|
| `question` | RAG Q&A | "What connectors exist?", "How do I X?" | Questions expecting direct answers |
| `config_request` | Config Builder | "Build me a X to Y pipeline" | "pipeline", "config", "HOCON" |
| `documentation_request` | Doc Writer | "Write a tutorial on X", "Document the Y API" | "write", "create", "tutorial", "guide", "article", "document" |
| `summary` | Summary | "Summarize our conversation" | "summarize", "recap", "summary" |
| `follow_up` | RAG Q&A | "OK", "That makes sense", "Got it" | Short acknowledgments (<10 words) |

**When to Disable:**

- **Memory-constrained environments**: Disable both to reduce memory footprint
- **RAG-only deployments**: Set both to `False` for pure question-answering mode
- **Debugging**: Disable one capability at a time to isolate issues

When a feature is disabled, requests that would use it are automatically remapped to the RAG Q&A pipeline.

---

## GCP Deployment

### Deploy to Cloud Run

```bash
cd langchain_agent
./scripts/deploy.sh --project gen-lang-client-0250737934
```

This will:
1. Build Docker image locally
2. Push to Artifact Registry
3. Deploy to Cloud Run
4. Create Cloud SQL for checkpoints
5. Manage secrets in Secret Manager

### Initialize Cloud SQL + Ingest Docs

```bash
./scripts/gcp-init.sh --project gen-lang-client-0250737934
```

This initializes:
1. Cloud SQL checkpoint tables
2. OpenSearch index and search pipeline
3. Lucille documentation ingestion

### Check Cloud Run Logs

```bash
gcloud logging read resource.type=cloud_run_revision --project=gen-lang-client-0250737934
```

**Key events to watch**:
- `POST /api/chat` with status 200 = successful requests
- `AgentCompleteEvent` = response generation completed
- `DocReplacer` = broken links being fixed automatically
- `ERROR` = investigate problematic requests

### Live Deployment

- **Service URL**: https://rusty-compass-gyx7duaosq-uc.a.run.app
- **Health Check**: https://rusty-compass-gyx7duaosq-uc.a.run.app/api/health
- **API Docs**: https://rusty-compass-gyx7duaosq-uc.a.run.app/docs
- **OpenSearch**: 34.138.97.13:9200 (hosted, 1226+ documents indexed)
- **PostgreSQL**: Cloud SQL (checkpoints only)

**Recent Updates**:
- ✅ Phase 1-3 comprehensive testing framework deployed (validation, integration, E2E, load testing)
- ✅ Fixed alpha boundary logic in search strategy mapping (QueryEvaluationEvent validation)
- ✅ All components initialized and healthy

---

## Features

### Link Verification

The agent includes automatic link verification that:
- ✅ Validates all citation URLs before sending to the LLM
- ✅ Caches verification results for 60 minutes (TTL)
- ✅ Replaces broken links with valid alternatives automatically
- ✅ Gracefully handles timeouts (>2 seconds marked invalid)

This prevents citing broken links in responses.

### Javadoc URL Mapping

Javadoc sources are automatically mapped to Maven Central hosting:
- **Local**: Generated from Lucille javadoc (`target/site/apidocs/`)
- **Deployed**: Mapped to https://javadoc.io/doc/com.kmwllc/lucille-core/latest/{class-path}.html
- **Markdown**: GitHub URLs (doc/site/content/en/docs/*)

---

## Troubleshooting

### View Logs

```bash
./scripts/logs.sh backend     # Backend logs
./scripts/logs.sh frontend    # Frontend logs
./scripts/logs.sh all         # All logs
```

### Backend won't start

```bash
# Check API key exists
grep API_KEY .env

# Check logs
./scripts/logs.sh backend

# If "Address already in use" error, kill stale processes
lsof -ti :8000 | xargs kill -9
./scripts/start.sh
```

### Frontend shows connection error

```bash
# Check backend is running
curl http://localhost:8000/api/health

# Check logs
./scripts/logs.sh frontend
```

### Google AI API issues

```bash
# Check your API key is set
echo $GOOGLE_API_KEY

# Test with a simple Python call
python -c "from langchain_google_genai import GoogleGenerativeAIEmbeddings; e = GoogleGenerativeAIEmbeddings(model='models/gemini-embedding-001'); print(len(e.embed_query('test')))"
```

### Database issues

```bash
# Check PostgreSQL is running
docker compose ps

# Restart PostgreSQL
cd ..
docker compose down
docker compose up -d postgres
cd langchain_agent

# Re-initialize database
python setup.py
```

### Content not appearing after generation

If content generation completes in the observability panel but doesn't appear in chat:

**Symptom**: Observability shows "Content Complete: X words" but chat window is empty

**Cause**: WebSocket streaming events not properly initialized

**Fix**: This was resolved in commit `e773b0a`. If you're on an older version:
```bash
git pull
./scripts/stop.sh
./scripts/start.sh
```

**Verification**: Backend logs should show:
```
LLM STREAMING STARTED
Emitting AgentCompleteEvent: XXXX chars
```

### Verify Setup

```bash
# Check all services
docker compose ps                              # PostgreSQL
curl http://localhost:11434/api/tags           # Ollama
curl http://localhost:8000/api/health          # Backend
```

---

## Architecture

### Agent Pipeline

The agent uses intent-based routing to direct queries to one of three pipelines:

```text
START → Intent Classifier
  ├── [question]                 → Query Evaluator → Summary → Retriever → Alpha Refiner → Agent → END
  ├── [summary]                  → Summary → Agent → END
  ├── [config_request]           → Config Resolver → Config Generator → Config Response → END
  ├── [documentation_request]    → Doc Planner → Doc Gatherer → Doc Synthesizer → END
  └── [follow_up]                → Query Evaluator → Summary → Retriever → Alpha Refiner → Agent → END
```

#### RAG Q&A Pipeline (Default)

```text
Query → Intent Classifier → Query Expansion → Query Evaluator → Summary
  → Retriever (hybrid search + reranking) → Alpha Refiner → Agent → END
```

**Features**:
- **Intent Detection**: 5 intents (question, config_request, documentation_request, summary, follow_up) with confidence scoring
- **Smart Routing**: Summary/follow_up skip retrieval or use minimal context; config/doc intents route to specialized pipelines
- **Query Expansion**: Automatically expands vague follow-up queries using conversation context
- **Alpha Refinement**: Bidirectional - tries opposite search strategy when max score < 0.5
- **Citation Suppression**: Suppresses citations when max relevance < 10%
- **Honest Responses**: Returns "no info found" when retrieval fails (prevents hallucination)

#### Config Builder Pipeline

```text
Config Request → Config Resolver → Config Generator → Config Response → END
```

- **Config Resolver**: Parses natural language request into component needs, resolves specs via metadata queries
- **Config Generator**: Generates valid HOCON config using LLM with component spec context
- **Config Response**: Formats config in markdown with validation notes and parameter reference

#### Documentation Writer Pipeline

```text
Doc Request → Content Type Classifier → [Route by Type]
  ├─ social_post → Social Generator (1 pass) → END (~6s)
  ├─ blog_post → Blog Generator (2 passes) → END (~20s)
  ├─ technical_article → Article Generator (3 passes) → END (~25s)
  ├─ tutorial → Tutorial Generator (2 passes) → END (~20s)
  └─ comprehensive_docs → Doc Planner → Doc Gatherer → Doc Synthesizer → END (~50s)
```

**Content Type Classifier**: Uses lightweight LLM (`gemini-2.5-flash-lite`) to detect content type based on keywords and query structure

**Lightweight Generators** (social/blog/article/tutorial):
- **Outline Creation**: LLM generates structure (sections or steps)
- **Multi-Pass Retrieval**: 1-3 targeted retrieval passes with different alpha values
- **Streaming Generation**: Real-time token streaming for instant feedback
- **Specialized Prompts**: Optimized for tone, length, and structure per content type

**Comprehensive Docs Pipeline** (existing):
- **Doc Planner**: Creates documentation outline from component catalog
- **Doc Gatherer**: Iterative retrieval loop - 5 retrieval passes
- **Doc Synthesizer**: Multi-pass generation producing full multi-section documentation

**Performance**: Lightweight modes are 2-10× faster than comprehensive mode while maintaining quality

**Streaming Architecture**:
All content generators emit real-time streaming events:
1. `LLMResponseStartEvent` - Creates placeholder message in chat UI before generation
2. `LLMResponseChunkEvent` - Streams each token as generated (display updates instantly)
3. `ContentCompleteEvent` - Finalizes with word/character counts

**Frontend Integration**:
- **Observability Panel**: Purple-themed nodes for content type classification and generation
- **Event Types**: 6 new event types (ContentTypeClassificationEvent, 4 progress events, ContentCompleteEvent)
- **Real-time Display**: WebSocket events update UI as content streams in

### Hybrid Search

Uses **Reciprocal Rank Fusion (RRF)** to combine vector and full-text rankings:

```text
rrf_score = sum of 1/(rank_vector + k) + 1/(rank_text + k)
where k=60 (constant)
```

The **Alpha Parameter** controls weighting (standard hybrid search convention):

- `α=0.0-0.15`: Pure lexical (BM25, exact matches, class names)
- `α=0.15-0.4`: Lexical-heavy (specific features, APIs)
- `α=0.4-0.6`: Balanced hybrid
- `α=0.6-0.75`: Semantic-heavy (how-to, architecture queries)
- `α=0.75-1.0`: Pure semantic (vector, conceptual questions)

Query Evaluator dynamically adjusts alpha based on query type.

### Observability Events

The UI provides real-time observability via WebSocket events:

| Event | Description |
|-------|-------------|
| `intent_classification` | Intent with confidence score (5 intents: question, config_request, documentation_request, summary, follow_up) |
| `query_expansion` | Original and expanded query for vague follow-ups |
| `query_evaluation` | Alpha value and query analysis reasoning |
| `hybrid_search_start/result` | Search candidates with scores |
| `reranker_start/result` | Reranked documents with relevance scores |
| `alpha_refinement` | Whether alpha was adjusted due to low relevance |
| `config_builder_start` | Config builder user request |
| `component_spec_retrieval` | Components requested/found/not found |
| `config_generated` | Config preview with validation notes |
| `content_type_classification` | Content type detected (social_post, blog_post, technical_article, tutorial, comprehensive_docs) with confidence, target length, tone, retrieval depth, temperature |
| `social_post_progress` / `blog_post_progress` / `article_progress` / `tutorial_progress` | Progress events per content type (retrieval, outline, generation stages) |
| `llm_response_start` | LLM streaming started (creates placeholder message) |
| `llm_response_chunk` | LLM token chunk (real-time content display) |
| `content_complete` | Content generation complete with word/char counts |
| `doc_outline` | Documentation outline with sections |
| `doc_section_progress` | Section gathering progress |
| `doc_complete` | Completed documentation stats |
| `agent_complete` | Final response with citations (if relevant) |

### Query Evaluation & Alpha Refinement

Intelligent query optimization:

1. **Query Evaluator**: Dynamically determines optimal alpha value (0.0-1.0) for hybrid search based on query type
   - `0.0-0.15`: Pure lexical (exact matches, class names)
   - `0.4-0.6`: Balanced hybrid
   - `0.75-1.0`: Pure semantic (conceptual questions)

2. **Alpha Refiner**: Automatically retries with opposite strategy if max relevance score < 0.5
   - Low semantic score → retry with lexical-heavy search
   - Low lexical score → retry with semantic-heavy search

3. **Reranker**: LLM-based relevance scoring (Gemini) refines retrieved documents

---

## Development

### Update Data

```bash
# Ingest Lucille javadoc
python ingest_lucille_docs.py

# Show ingestion stats
python ingest_lucille_docs.py --stats

# Or full re-initialization
python setup.py
```

### Add Custom Tool

```python
# In main.py
from langchain_core.tools import tool

@tool
def my_tool(query: str) -> str:
    """Tool description"""
    return "result"

tools = [knowledge_base, my_tool]
```

### Change Models

```python
# In config.py
LLM_MODEL = "llama2:13b"  # Any Ollama model
RERANKER_MODEL = "BAAI/bge-reranker-v2-large"  # Larger, more accurate
ENABLE_RERANKING = False  # Disable for speed
```

### Debug Search

```python
from main import SimplePostgresVectorStore
from config import EMBEDDINGS_MODEL

embeddings = ...  # Initialize embeddings
vector_store = SimplePostgresVectorStore(embeddings)

results = vector_store.hybrid_search("your query", k=4, alpha=0.25)
for doc in results:
    print(f"{doc.metadata['score']:.3f}: {doc.page_content[:100]}")
```

### Database Inspection

```bash
# Connect to DB
psql -h localhost -U postgres -d langchain_agent

# Check tables
\dt  # list tables
\di  # list indexes

# Sample data
SELECT * FROM documents LIMIT 1;
SELECT COUNT(*) FROM document_chunks;
```

### Testing

```bash
python verify_changes.py       # Pipeline optimization verification
python benchmark_search.py     # Search performance benchmarks
```

---

## Performance

| Operation | Typical Time |
| --------- | ------------ |
| Hybrid search (lexical + semantic) | ~2-3s |
| LLM-based reranking (40→10 docs) | ~2-3s |
| Query evaluation (alpha detection) | ~1-2s |
| Alpha refinement (if needed) | ~2-3s |
| LLM response generation | ~5-15s (depends on length) |
| **Total per query** | 10-30s (Cloud Run, GCP) |
| **Link verification** | ~50ms per URL (cached) |

**Optimizations**:

- OpenSearch hybrid search (Lucene + knn_vector)
- Min-max normalization for score fusion
- Gemini batch API for embeddings
- Link cache with 60-minute TTL
- Thread-safe concurrent URL verification

---

## Files

```text
langchain_agent/
├── scripts/
│   ├── setup.sh           # One-time setup
│   ├── start.sh           # Start all services
│   ├── stop.sh            # Stop all services
│   └── logs.sh            # View logs
├── api/                   # FastAPI backend
│   ├── main.py            # Entry point (lifespan-based)
│   ├── routes/            # API endpoints
│   ├── middleware/        # Authentication (constant-time compare)
│   └── schemas/           # Pydantic event models
├── web/                   # React frontend
│   ├── src/
│   │   ├── components/
│   │   ├── stores/
│   │   └── App.tsx
│   └── package.json
├── main.py                # CLI agent + core graph nodes
├── setup.py               # Database + OpenSearch initialization
├── config.py              # Configuration constants (OpenSearch, PostgreSQL, LLM)
├── agent_state.py         # LangGraph state schema (TypedDict)
├── vector_store.py        # OpenSearch hybrid search + metadata queries
├── reranker.py            # Gemini LLM-based reranker
├── config_builder.py      # Config builder pipeline (HOCON generation)
├── doc_writer.py          # Documentation writer pipeline (5 content types)
├── component_specs.py     # Structured component spec extraction
├── catalog_generator.py   # Auto-generated component catalogs
├── exceptions.py          # Custom exception hierarchy
├── retry_utils.py         # Retry decorators (tenacity)
├── link_verifier.py       # URL validation with TTL cache (httpx)
├── doc_replacer.py        # Broken link detection + replacement
├── embedding_cache.py     # Thread-safe embedding cache
├── logging_config.py      # Structured logging (JSON format)
├── ingest_lucille_docs.py # Lucille javadoc + markdown ingestion
├── observable_agent.py    # SSE streaming + event emission
├── verify_changes.py      # Pipeline integration tests
├── benchmark_search.py    # Search performance benchmarks
└── README.md              # This file
```

## Security

- **API Key**: Required for all endpoints (X-API-Key header)
- **Timing Attack Prevention**: Uses `hmac.compare_digest` for key comparison
- **Input Validation**: Thread ID validated with regex pattern
- **Thread Safety**: All caches use `threading.Lock`
- **Rate Limiting**: Configurable via slowapi

---

## External References

- **LangGraph**: <https://langchain-ai.github.io/langgraph/>
- **LangChain**: <https://python.langchain.com/>
- **OpenSearch**: <https://opensearch.org/docs/latest/>
- **OpenSearch Python Client**: <https://opensearch-project.github.io/opensearch-py/>
- **Google Gemini AI**: <https://ai.google.dev/>
- **Google AI Studio**: <https://aistudio.google.com/>
- **Google Cloud Run**: <https://cloud.google.com/run/docs>
