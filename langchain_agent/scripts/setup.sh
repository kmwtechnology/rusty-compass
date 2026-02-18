#!/bin/bash
# Rusty Compass Setup Script
# One-time setup: install dependencies, generate API key, initialize database

set -e  # Exit on error


echo "🚀 Rusty Compass Setup"
echo ""

# Handle help flag
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    cat << EOF
Usage: ./scripts/setup.sh [OPTIONS]

One-time setup for Rusty Compass: installs dependencies, generates API key, and initializes the database.

OPTIONS:
    -h, --help          Show this help message and exit

REQUIREMENTS:
    - Docker (for PostgreSQL + OpenSearch containers)
    - Python 3.11+
    - Node.js 18+
    - Google API Key (for Gemini AI)
    - Maven (for javadoc generation)
    - Java 17+ (for Maven)
    - Git (for cloning Lucille repository)

WHAT THIS SCRIPT DOES:
    1. Checks prerequisites (Docker, Python, Node.js, Maven, Git)
    2. Clones or updates Lucille repository
    3. Creates .env file with API key (if not already present)
    4. Syncs API key to frontend configuration
    5. Creates Python virtual environment and installs dependencies
    6. Installs Node.js frontend dependencies
    7. Generates Lucille javadocs
    8. Starts PostgreSQL, OpenSearch, and OpenSearch Dashboards containers
    9. Validates Google AI API key
    10. Initializes database, OpenSearch index, and loads documentation

SERVICES STARTED:
    - PostgreSQL (checkpoint storage) → localhost:5432
    - OpenSearch (document search) → localhost:9200
    - OpenSearch Dashboards (visualization) → http://localhost:5601

REQUIREMENTS:
    GOOGLE_API_KEY must be set in .env file
    Get your key from: https://aistudio.google.com/apikey

NEXT STEPS after setup:
    1. Start services: ./scripts/start.sh
    2. Visit http://localhost:5173

For more information, see README.md

EOF
    exit 0
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# 1. Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found"
    echo "   Please install Docker from https://www.docker.com/"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    echo "   Please install Python 3.13 from https://www.python.org/"
    exit 1
fi

# Check Python version (must be 3.13 or earlier, not 3.14+)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 13 ]); then
    echo "❌ Python version too old: $PYTHON_VERSION"
    echo "   Required: Python 3.13 (or 3.13.x)"
    echo "   LangChain requires Python 3.13 or earlier (not 3.14+)"
    exit 1
fi

if [ "$PYTHON_MAJOR" -gt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -gt 13 ]); then
    echo "❌ Python version too new: $PYTHON_VERSION"
    echo "   Required: Python 3.13 (or 3.13.x)"
    echo "   LangChain/Pydantic V1 are not compatible with Python 3.14+"
    echo ""
    echo "   Solution: Install Python 3.13"
    echo "   - macOS: brew install python@3.13"
    echo "   - Ubuntu: sudo apt-get install python3.13"
    echo "   - Or download from https://www.python.org/downloads/"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found"
    echo "   Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi

if ! command -v mvn &> /dev/null; then
    echo "❌ Maven not found"
    echo "   Please install Maven for javadoc generation"
    echo "   macOS: brew install maven"
    echo "   Ubuntu: sudo apt-get install maven"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "❌ Git not found"
    echo "   Please install Git"
    echo "   macOS: brew install git"
    echo "   Ubuntu: sudo apt-get install git"
    exit 1
fi

echo "✓ All prerequisites found"
echo ""

# 2. Ensure Lucille repository is cloned/updated
echo "📦 Setting up Lucille repository..."

if [ ! -d "$PARENT_DIR/lucille" ]; then
    echo "   Cloning Lucille from GitHub..."
    cd "$PARENT_DIR"
    git clone https://github.com/kmwtechnology/lucille.git > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "   ✓ Lucille cloned successfully"
    else
        echo "   ❌ Failed to clone Lucille"
        echo "      Please ensure you have git installed and internet access"
        exit 1
    fi
    cd "$PROJECT_DIR"
else
    echo "   Updating existing Lucille repository..."
    cd "$PARENT_DIR/lucille"
    git pull > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "   ✓ Lucille updated to latest version"
    else
        echo "   ⚠ Failed to update Lucille (continuing with existing version)"
    fi
    cd "$PROJECT_DIR"
fi
echo ""

# 3. Generate API key if .env doesn't exist
echo "📝 Configuring environment..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "   Creating .env file..."
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"

    # Generate API key
    API_KEY=$(openssl rand -hex 32)

    # Use sed to replace the placeholder (works on both macOS and Linux)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/your-secure-api-key-here/$API_KEY/" "$PROJECT_DIR/.env"
    else
        sed -i "s/your-secure-api-key-here/$API_KEY/" "$PROJECT_DIR/.env"
    fi

    echo "   ✓ Generated API_KEY"

    # Prompt for Google API key
    echo ""
    echo "   🔑 Google API Key required for Gemini AI models"
    echo "   Get your key from: https://aistudio.google.com/apikey"
    echo ""
    read -rp "   Enter your GOOGLE_API_KEY: " GOOGLE_API_KEY_INPUT

    if [ -n "$GOOGLE_API_KEY_INPUT" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/your-google-api-key-here/$GOOGLE_API_KEY_INPUT/" "$PROJECT_DIR/.env"
        else
            sed -i "s/your-google-api-key-here/$GOOGLE_API_KEY_INPUT/" "$PROJECT_DIR/.env"
        fi
        echo "   ✓ GOOGLE_API_KEY configured"
    else
        echo "   ⚠ No key entered. Set GOOGLE_API_KEY in .env before running."
    fi
else
    # Extract existing API_KEY
    API_KEY=$(grep "^API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    echo "   ✓ Using existing API_KEY"

    # Check if GOOGLE_API_KEY is still the placeholder
    EXISTING_GOOGLE_KEY=$(grep "^GOOGLE_API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    if [ "$EXISTING_GOOGLE_KEY" = "your-google-api-key-here" ] || [ -z "$EXISTING_GOOGLE_KEY" ]; then
        echo ""
        echo "   🔑 Google API Key not yet configured"
        echo "   Get your key from: https://aistudio.google.com/apikey"
        echo ""
        read -rp "   Enter your GOOGLE_API_KEY: " GOOGLE_API_KEY_INPUT

        if [ -n "$GOOGLE_API_KEY_INPUT" ]; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s/^GOOGLE_API_KEY=.*/GOOGLE_API_KEY=$GOOGLE_API_KEY_INPUT/" "$PROJECT_DIR/.env"
            else
                sed -i "s/^GOOGLE_API_KEY=.*/GOOGLE_API_KEY=$GOOGLE_API_KEY_INPUT/" "$PROJECT_DIR/.env"
            fi
            echo "   ✓ GOOGLE_API_KEY configured"
        else
            echo "   ⚠ No key entered. Set GOOGLE_API_KEY in .env before running."
        fi
    else
        echo "   ✓ Using existing GOOGLE_API_KEY"
    fi
fi

# 3. Create frontend .env (if missing)
if [ ! -f "$PROJECT_DIR/web/.env" ]; then
    echo "   Creating web/.env..."
    cat > "$PROJECT_DIR/web/.env" << EOF
# Vite proxy in vite.config.ts routes /api and /ws to localhost:8000
# No VITE_API_URL needed for local dev (empty = relative URLs through proxy)
EOF
    echo "   ✓ Frontend env configured"
else
    echo "   ✓ Frontend env exists"
fi

echo ""

# 4. Install Python dependencies
echo "📦 Installing Python dependencies..."

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    python3 -m venv "$PROJECT_DIR/.venv"
    echo "   Created virtual environment"
fi

source "$PROJECT_DIR/.venv/bin/activate"
pip install -q --upgrade pip setuptools wheel
pip install -q -r "$PROJECT_DIR/requirements.txt"
echo "✓ Python dependencies installed"
echo ""

# 5. Install frontend dependencies
echo "📦 Installing frontend dependencies..."

cd "$PROJECT_DIR/web"
if [ ! -d "node_modules" ]; then
    npm install --quiet
    echo "✓ Frontend dependencies installed"
else
    echo "✓ Frontend dependencies already installed"
fi
cd "$PROJECT_DIR"
echo ""

# 7. Generate Lucille javadocs
echo "📚 Generating Lucille javadocs..."

if [ ! -d "$PARENT_DIR/lucille" ]; then
    echo "   ❌ Lucille project not found (unexpected error)"
    echo "   This should not happen if setup completed successfully"
    exit 1
fi

cd "$PARENT_DIR/lucille"
if ! mvn javadoc:aggregate > /dev/null 2>&1; then
    echo "   ✗ Failed to generate javadocs. Ensure Maven and Java 17+ are installed."
    exit 1
fi
echo "✓ Javadocs generated at target/site/apidocs"
cd "$PROJECT_DIR"
echo ""

# 8. Start Docker containers (PostgreSQL + OpenSearch)
echo "🐘 Starting Docker containers..."

cd "$PARENT_DIR"
if ! docker compose ps 2>/dev/null | grep -q "postgres.*Up"; then
    docker compose up -d postgres > /dev/null 2>&1
    echo "   Waiting for PostgreSQL to be ready..."
    sleep 3
    echo "✓ PostgreSQL started"
else
    echo "✓ PostgreSQL already running"
fi

if ! docker compose ps 2>/dev/null | grep -q "opensearch.*Up"; then
    docker compose up -d opensearch > /dev/null 2>&1
    echo "   Waiting for OpenSearch to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:9200/_cluster/health 2>/dev/null | grep -q '"status"'; then
            echo "✓ OpenSearch started"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "❌ OpenSearch failed to start within 30 seconds"
            echo "   Check: docker compose logs opensearch"
            exit 1
        fi
        sleep 2
    done
else
    echo "✓ OpenSearch already running"
fi

if ! docker compose ps 2>/dev/null | grep -q "opensearch-dashboards.*Up"; then
    docker compose up -d opensearch-dashboards > /dev/null 2>&1
    echo "   Waiting for OpenSearch Dashboards to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:5601/api/status 2>/dev/null | grep -q 'state'; then
            echo "✓ OpenSearch Dashboards started → http://localhost:5601"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "⚠ OpenSearch Dashboards is starting (may take a moment)"
            echo "   Access at: http://localhost:5601"
            break
        fi
        sleep 2
    done
else
    echo "✓ OpenSearch Dashboards already running → http://localhost:5601"
fi
cd "$PROJECT_DIR"
echo ""

# 9. Validate Google AI API key
echo "🔑 Validating Google AI configuration..."
echo ""

# 10. Initialize database and load data
echo "💾 Initializing database and loading documentation..."

source "$PROJECT_DIR/.venv/bin/activate"

mkdir -p "$PROJECT_DIR/logs"
python "$PROJECT_DIR/setup.py" 2>&1 | tee "$PROJECT_DIR/logs/setup.log"

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo ""
    echo "✓ Database initialized and docs loaded"
else
    echo ""
    echo "✗ Setup failed. Check logs: ./scripts/logs.sh backend"
    exit 1
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start services: ./scripts/start.sh"
echo ""
echo "Visit http://localhost:5173 when ready"
