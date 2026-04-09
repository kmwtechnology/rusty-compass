#!/bin/bash
# Rusty Compass — GCP Database & Document Initialization
# One-time script to initialize Cloud SQL (checkpoints) and ingest docs to OpenSearch.
#
# This script:
#   1. Starts Cloud SQL Auth Proxy to connect to the Cloud SQL instance
#   2. Runs init_db.py to create checkpoint and metadata tables
#   3. Ingests Lucille documentation into hosted OpenSearch
#   4. Shuts down the proxy
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Cloud SQL Auth Proxy installed (auto-downloaded if missing)
#   - Python virtual environment with dependencies installed (.venv/)
#   - Lucille javadocs generated (../lucille/target/site/apidocs)
#   - GOOGLE_API_KEY set in .env (needed for embedding generation)
#   - deploy.sh already run (Cloud SQL instance must exist)
#
# Usage:
#   ./scripts/gcp-init.sh                     # Uses gcloud default project
#   ./scripts/gcp-init.sh --project my-proj   # Specific project
#   ./scripts/gcp-init.sh --skip-docs         # Skip doc ingestion

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

REGION="us-central1"
CLOUD_SQL_INSTANCE="rusty-compass-db"
DB_NAME="langchain_agent"
DB_USER="postgres"
PROXY_PORT="15432"  # Use non-standard port to avoid conflicts with local postgres

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

PROJECT_ID=""
SKIP_DOCS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        --skip-docs)
            SKIP_DOCS=true
            shift
            ;;
        -h|--help)
            cat << 'EOF'
Usage: ./scripts/gcp-init.sh [OPTIONS]

Initialize GCP resources for Rusty Compass.
This is a one-time operation after the first deployment.

Cloud SQL (PostgreSQL) is used for LangGraph checkpoints only.
Document search uses hosted OpenSearch (configured via env vars in deploy.sh).

OPTIONS:
    --project PROJECT_ID   GCP project ID (otherwise uses gcloud default)
    --skip-docs            Skip Lucille documentation ingestion into OpenSearch
    -h, --help             Show this help message

WHAT THIS SCRIPT DOES:
    1. Downloads Cloud SQL Auth Proxy (if not installed)
    2. Starts the proxy to tunnel to Cloud SQL
    3. Creates checkpoint and metadata tables in Cloud SQL
    4. Ingests Lucille documentation into hosted OpenSearch
    5. Shuts down the proxy

PREREQUISITES:
    - Run deploy.sh first to create the Cloud SQL instance
    - Lucille javadocs generated: cd ../lucille && mvn javadoc:aggregate
    - GOOGLE_API_KEY set in .env (needed for embeddings)
    - Python venv with dependencies: source .venv/bin/activate

EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================================================
# HELPERS
# ============================================================================

log() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }
err() { echo "ERROR: $*" >&2; exit 1; }

cleanup() {
    log "Cleaning up..."
    if [ -n "${PROXY_PID:-}" ] && kill -0 "$PROXY_PID" 2>/dev/null; then
        kill "$PROXY_PID" 2>/dev/null || true
        wait "$PROXY_PID" 2>/dev/null || true
        log "Cloud SQL Auth Proxy stopped."
    fi
}

trap cleanup EXIT

# ============================================================================
# STEP 0: VALIDATE PREREQUISITES
# ============================================================================

log "Checking prerequisites..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if ! command -v gcloud &> /dev/null; then
    err "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
fi

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
    if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
        err "No GCP project set. Use --project PROJECT_ID or run: gcloud config set project PROJECT_ID"
    fi
fi

# Check virtual environment
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    err "Python virtual environment not found. Run: python3 -m venv .venv && pip install -r requirements.txt"
fi

# Check .env for GOOGLE_API_KEY
if [ -f "$PROJECT_DIR/.env" ]; then
    GOOGLE_KEY=$(grep "^GOOGLE_API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    if [ -z "$GOOGLE_KEY" ] || [ "$GOOGLE_KEY" = "your-google-api-key-here" ]; then
        err "GOOGLE_API_KEY not configured in .env. Needed for embedding generation."
    fi
else
    err ".env file not found. Run setup.sh first or create .env with GOOGLE_API_KEY."
fi

CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"
log "Project:    $PROJECT_ID"
log "Instance:   $CLOUD_SQL_CONNECTION"
log "Database:   $DB_NAME"
echo ""

# ============================================================================
# STEP 1: INSTALL / LOCATE CLOUD SQL AUTH PROXY
# ============================================================================

log "Setting up Cloud SQL Auth Proxy..."

PROXY_BIN=""

# Check if already installed
if command -v cloud-sql-proxy &> /dev/null; then
    PROXY_BIN="cloud-sql-proxy"
elif command -v cloud_sql_proxy &> /dev/null; then
    PROXY_BIN="cloud_sql_proxy"
elif [ -f "$PROJECT_DIR/.cloud-sql-proxy" ]; then
    PROXY_BIN="$PROJECT_DIR/.cloud-sql-proxy"
else
    log "Downloading Cloud SQL Auth Proxy..."

    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) ARCH="amd64" ;;
        arm64|aarch64) ARCH="arm64" ;;
    esac

    PROXY_URL="https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.${OS}.${ARCH}"
    curl -sSL "$PROXY_URL" -o "$PROJECT_DIR/.cloud-sql-proxy"
    chmod +x "$PROJECT_DIR/.cloud-sql-proxy"
    PROXY_BIN="$PROJECT_DIR/.cloud-sql-proxy"
    log "Cloud SQL Auth Proxy downloaded."
fi

# ============================================================================
# STEP 2: GET DATABASE PASSWORD
# ============================================================================

log "Retrieving database password from Secret Manager..."

DB_PASSWORD=$(gcloud secrets versions access latest \
    --secret=rusty-compass-db-password \
    --project="$PROJECT_ID" 2>/dev/null) || \
    err "Could not retrieve DB password from Secret Manager. Was deploy.sh run first?"

log "Retrieving OpenSearch credentials from Secret Manager..."

GCP_OPENSEARCH_USER=$(gcloud secrets versions access latest \
    --secret=rusty-compass-opensearch-user \
    --project="$PROJECT_ID" 2>/dev/null) || \
    err "Could not retrieve OpenSearch user from Secret Manager."

GCP_OPENSEARCH_PASSWORD=$(gcloud secrets versions access latest \
    --secret=rusty-compass-opensearch-password \
    --project="$PROJECT_ID" 2>/dev/null) || \
    err "Could not retrieve OpenSearch password from Secret Manager."

# ============================================================================
# STEP 3: START CLOUD SQL AUTH PROXY
# ============================================================================

log "Starting Cloud SQL Auth Proxy on port $PROXY_PORT..."

$PROXY_BIN "$CLOUD_SQL_CONNECTION" \
    --port="$PROXY_PORT" \
    --quiet &
PROXY_PID=$!

# Wait for proxy to be ready
log "Waiting for proxy connection..."
for i in {1..30}; do
    if pg_isready -h 127.0.0.1 -p "$PROXY_PORT" -U "$DB_USER" &>/dev/null; then
        log "Proxy connected."
        break
    fi
    if [ $i -eq 30 ]; then
        err "Cloud SQL Auth Proxy failed to connect after 30 seconds."
    fi
    sleep 1
done

# ============================================================================
# STEP 4: INITIALIZE CLOUD SQL (CHECKPOINT TABLES ONLY)
# ============================================================================

log "Initializing Cloud SQL checkpoint tables..."
echo ""

# Activate virtual environment
source "$PROJECT_DIR/.venv/bin/activate"

# Override database connection to use proxy
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$PROXY_PORT"
export POSTGRES_USER="$DB_USER"
export POSTGRES_PASSWORD="$DB_PASSWORD"
export POSTGRES_DB="$DB_NAME"

# Load GOOGLE_API_KEY and OpenSearch settings from .env
set -a
source "$PROJECT_DIR/.env"
set +a

# Re-override postgres settings to point at the proxy (not local docker)
export POSTGRES_HOST="127.0.0.1"
export POSTGRES_PORT="$PROXY_PORT"
export POSTGRES_PASSWORD="$DB_PASSWORD"

# Override OpenSearch settings for GCP hosted instance with credentials from Secret Manager
# (These override the .env file values)
export OPENSEARCH_HOST="34.138.97.13"
export OPENSEARCH_PORT="9200"
export OPENSEARCH_USER="$GCP_OPENSEARCH_USER"
export OPENSEARCH_PASSWORD="$GCP_OPENSEARCH_PASSWORD"
export OPENSEARCH_USE_SSL="true"
export OPENSEARCH_VERIFY_CERTS="false"

SETUP_ARGS=""
if $SKIP_DOCS; then
    SETUP_ARGS="--skip-docs"
fi

cd "$PROJECT_DIR"
python init_db.py $SETUP_ARGS

echo ""

# ============================================================================
# STEP 5: VERIFY
# ============================================================================

log "Verifying setup..."

# Verify Cloud SQL checkpoint tables
PGPASSWORD="$DB_PASSWORD" psql \
    -h 127.0.0.1 \
    -p "$PROXY_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -c "SELECT 'checkpoints' AS resource, COUNT(*)::text AS count FROM checkpoints
        UNION ALL
        SELECT 'conversation_metadata', COUNT(*)::text FROM conversation_metadata;" 2>/dev/null || \
    warn "Could not verify Cloud SQL (psql not installed locally)."

# Verify OpenSearch documents
python -c "
from vector_store import create_opensearch_client
from config import OPENSEARCH_INDEX_NAME
client = create_opensearch_client()
count = client.count(index=OPENSEARCH_INDEX_NAME, body={'query': {'match_all': {}}})['count']
print(f'      OpenSearch documents: {count}')
" 2>/dev/null || warn "Could not verify OpenSearch."

echo ""
echo "============================================================"
log "GCP INITIALIZATION COMPLETE"
echo "============================================================"
echo ""
echo "  Cloud SQL:    $CLOUD_SQL_INSTANCE (checkpoint tables)"
echo "  OpenSearch:   34.138.97.13:9200 (document search)"
echo "  Database:     $DB_NAME"
echo ""
echo "  The Cloud Run service should now pass health checks at:"
echo "    /api/health"
echo ""
echo "  To re-ingest docs later:"
echo "    python ingest_lucille_docs.py"
echo ""
echo "============================================================"
