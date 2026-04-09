# Rusty Compass Test Suite

Comprehensive test coverage for all three operating modes: RAG Q&A, Config Builder, and Documentation Writer.

## Directory Structure

```
tests/
├── config_builder/               # Config Builder tests (35 unit + 20 stress tests)
│   ├── test_config_builder.py    # Catalog, resolver, validator, few-shot tests
│   ├── test_random_configs.py    # 20 stress tests across all components
│   ├── test_valid.conf           # Valid config fixture
│   ├── test_invalid.conf         # Invalid config fixture
│   └── README.md                 # Config builder testing guide
│
├── unit/                         # Component unit tests (no external dependencies)
│   ├── test_reranker.py          # Reranker model + score validation
│   ├── test_vector_store.py      # Hybrid search (alpha, k params)
│   ├── test_auth.py              # API authentication + security
│   └── test_link_verifier.py     # URL validation + caching
│
├── integration/                  # Multi-component integration tests (requires services)
│   ├── test_intent_routing.py    # Intent classification (95%+ accuracy)
│   ├── test_graph_error_handling.py  # Error propagation + recovery
│   └── test_pipeline_flow.py     # End-to-end pipeline execution
│
├── e2e/                          # End-to-end deployment tests
│   └── test_deployment.py        # Health checks + service validation
│
├── conftest.py                   # Shared pytest fixtures
└── README.md                     # This file
```

## Running Tests

### All Tests
```bash
cd langchain_agent
source .venv/bin/activate
pytest tests/ -v
```

### By Component

```bash
# Config Builder (fast, unit tests only)
pytest tests/config_builder/ -v -k "not live"

# Config Builder stress tests (requires GOOGLE_API_KEY)
python tests/config_builder/test_random_configs.py        # all 20
python tests/config_builder/test_random_configs.py 1 5 12  # specific tests

# Core unit tests (fast, ~1s)
pytest tests/unit/ -v

# Intent classification (104 tests)
pytest tests/integration/test_intent_routing.py -v

# Full pipeline E2E
pytest tests/integration/test_pipeline_flow.py -v

# All integration tests (requires services)
pytest tests/integration/ -v

# E2E deployment tests (requires deployment)
pytest tests/e2e/ -v
```

### By Scope

```bash
# Fast tests only (unit + config builder, no services)
pytest tests/config_builder/ tests/unit/ -v -k "not live"

# Medium tests (integration, requires PostgreSQL + OpenSearch)
./scripts/start.sh
pytest tests/integration/ -v

# Full suite (integration + E2E, requires deployment)
pytest tests/ -v
```

### With Coverage

```bash
PYTHONPATH=. .venv/bin/pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

### With Markers

```bash
# Run only Phase 1 unit tests (fast)
PYTHONPATH=. .venv/bin/pytest tests/unit/ -m phase1 -v

# Skip slow tests
PYTHONPATH=. .venv/bin/pytest tests/ -m "not slow" -v

# Smoke tests only
PYTHONPATH=. .venv/bin/pytest tests/e2e/ -m smoke -v
```

## Test Categories

### Config Builder Tests (`tests/config_builder/`)

**Purpose**: Validate Lucille HOCON config generation, component resolution, and validation

| Test Type | Count | Coverage |
|-----------|-------|----------|
| Catalog Tests | 9 | 88-component catalog, generation, spot-checks |
| Catalog Lookup | 10 | Case-insensitive resolution, 10 parametrized cases |
| Few-Shot Selection | 4 | Example matching by component overlap |
| Lucille Validator | 2 | Valid/invalid config detection via Java CLI |
| Validator Parser | 4 | Error parsing, edge cases (null, NoClassDef, parse errors) |
| **Validation Routing** | **4** | **Conditional routing paths (new)** |
| **Stress Tests** | **20** | **Diverse pipelines: 19/20 pass (95%)** |

**Run Time**: ~2 seconds (unit) + variable (stress tests)
**Dependencies**: Lucille (for validator), GOOGLE_API_KEY (for stress tests)
**Best For**: Validating config generation, testing component resolution accuracy

```bash
# Unit tests only
python -m pytest tests/config_builder/ -v -k "not live"

# Stress tests (requires GOOGLE_API_KEY)
python tests/config_builder/test_random_configs.py
python tests/config_builder/test_random_configs.py 1 5 12  # specific tests
```

### Unit Tests (`tests/unit/`)

**Purpose**: Test individual components in isolation, validate boundaries, check error handling

| File | Tests | Coverage |
|------|-------|----------|
| test_reranker.py | 24 | Reranker model, score validation (0.0-1.0), index ranges, batch processing |
| test_vector_store.py | 19 | Alpha parameter (0.0-1.0), k/fetch_k validation, search results, error propagation |
| test_auth.py | 5 | API key validation, origin headers, timing attack resistance, middleware |
| test_link_verifier.py | 30 | URL validation, broken link detection, cache TTL, batch verification |

**Run Time**: ~0.5 seconds
**Dependencies**: None (all mocked)
**Best For**: Quick validation, TDD, continuous testing

### Integration Tests (`tests/integration/`)

**Purpose**: Test multi-component interactions, state persistence, event streaming

| File | Tests | Coverage |
|------|-------|----------|
| test_intent_routing.py | 104 | Intent classification (question, config, doc, summary, follow-up), confidence scoring, keywords |
| test_graph_error_handling.py | 45 | Node errors, timeouts, state validation, error propagation, recovery |
| test_pipeline_flow.py | 35 | Query expansion, retrieval, reranking, response generation, citations |

**Run Time**: ~5-30 seconds (requires services)
**Dependencies**: PostgreSQL, OpenSearch, Google API
**Best For**: Validating workflows, catching cross-component issues, E2E before deployment

### E2E Tests (`tests/e2e/`)

**Purpose**: Validate deployment, health checks, service connectivity

| File | Tests | Coverage |
|------|-------|----------|
| test_deployment.py | 25 | Health check endpoints, config validation, graceful degradation, recovery |

**Run Time**: ~10-60 seconds (requires deployment)
**Dependencies**: Deployed Cloud Run service, OpenSearch, PostgreSQL
**Best For**: Post-deployment validation, smoke tests, production verification

## Test Coverage Summary

```
Total: 283+ tests across all modules

Config Builder:
├── 35 Unit Tests
│   ├── Catalog generation + spot-checks
│   ├── Case-insensitive catalog lookup
│   ├── Few-shot example selection
│   ├── HOCON validation (valid/invalid configs)
│   ├── Validator error parser
│   └── Validation routing (new)
└── 20 Stress Tests (95% pass rate)
    └── Diverse pipelines: Parquet→Pinecone, Kafka→OpenSearch, RSS→Elasticsearch, etc.

RAG & Core:
├── 78+ Unit Tests (fast, <1s total)
├── 145+ Integration Tests (requires services)
└── 25+ E2E Tests (requires deployment)

Status:
✅ 35 Config builder tests passing
✅ 20 Config builder stress tests (95% pass rate)
✅ 24+ Core unit tests passing
✅ 104 Intent classification tests (95%+ accuracy)
⏭️ Integration/E2E tests (skipped without full stack/deployment)
```

## Setting Up for Testing

### Local Development

```bash
# Install dependencies
cd langchain_agent
.venv/bin/pip install -r requirements-dev.txt

# Start local services
./scripts/setup.sh    # One-time: Docker, venv, DB, docs
./scripts/start.sh    # Start PostgreSQL, OpenSearch, backend, frontend

# Run tests
PYTHONPATH=. .venv/bin/pytest tests/ -v
```

### CI/CD (GitHub Actions)

Tests run automatically on:
- Push to `main`
- Pull requests
- Scheduled nightly runs

See `.github/workflows/test.yml` for configuration.

## Common Issues

### ModuleNotFoundError: No module named 'X'

```bash
# Solution: Ensure you're in the langchain_agent directory and venv is activated
cd langchain_agent
source .venv/bin/activate
pytest tests/
```

### ImportError: cannot import name 'Exception'

```bash
# Solution: Add missing exception to exceptions.py
# The exceptions.py file must define all custom exception classes
```

### Config builder tests skipped ("Requires GOOGLE_API_KEY")

```bash
# Solution: Set GOOGLE_API_KEY for stress tests
export GOOGLE_API_KEY=your-key-here
python tests/config_builder/test_random_configs.py

# Unit tests work without it
pytest tests/config_builder/ -v -k "not live"
```

### "Lucille validator not available"

```bash
# Solution: Build Lucille with Maven
cd ../lucille
mvn package -DskipTests
cd ../rusty-compass/langchain_agent
```

### Tests timeout or hang

```bash
# Solution: Ensure services are running (for integration tests)
./scripts/start.sh

# Verify connectivity
docker compose ps
curl http://localhost:9200/_cluster/health  # OpenSearch
```

### Validator can't find Java classes

```bash
# Solution: Rebuild Lucille with full Maven build
cd ../lucille
mvn clean package
# Then rebuild config builder and retry
```

## Writing New Tests

### Unit Test Template

```python
# tests/unit/test_my_component.py
import pytest
from my_module import MyComponent

class TestMyComponent:
    """Tests for MyComponent validation and error handling."""

    def test_valid_input(self):
        """Test with valid input."""
        result = MyComponent(valid_input=42)
        assert result.value == 42

    def test_invalid_input_raises_error(self):
        """Test that invalid input raises exception."""
        with pytest.raises(ValueError):
            MyComponent(invalid_input=-1)
```

### Integration Test Template

```python
# tests/integration/test_my_pipeline.py
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
class TestMyPipeline:
    """Tests for multi-component pipeline."""

    async def test_end_to_end_flow(self, mock_services):
        """Test complete pipeline execution."""
        result = await run_pipeline(query="test")
        assert result.success
        assert len(result.documents) > 0
```

### Running New Tests

```bash
# Add test file, then run:
PYTHONPATH=. .venv/bin/pytest tests/unit/test_my_component.py -v

# Or with coverage:
PYTHONPATH=. .venv/bin/pytest tests/unit/test_my_component.py --cov=my_module
```

## Troubleshooting

See `.venv/bin/pytest --help` for all options. Common flags:

```bash
# Verbose output with full diffs
-vv

# Show print statements
-s

# Stop on first failure
-x

# Run N tests in parallel (requires pytest-xdist)
-n auto

# Only run tests matching pattern
-k "pattern"

# Run with full traceback
--tb=long
```

## References

- [pytest documentation](https://docs.pytest.org/)
- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest markers](https://docs.pytest.org/en/stable/example/markers.html)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [conftest.py patterns](https://docs.pytest.org/en/stable/how-to/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files)
