# Rusty Compass Test Suite

Comprehensive testing framework organized by test scope and purpose.

## Directory Structure

```
tests/
├── unit/                          # Component unit tests (no external dependencies)
│   ├── test_reranker.py          # Reranker validation (score bounds, model loading)
│   ├── test_vector_store.py      # Vector store & hybrid search (alpha, k params)
│   ├── test_auth.py              # API authentication (keys, origins, timing attacks)
│   └── test_link_verifier.py     # Link verification (URL validation, caching)
│
├── integration/                   # Multi-component integration tests (requires services)
│   ├── test_intent_routing.py    # Intent classification (104 tests, 95%+ accuracy)
│   ├── test_graph_error_handling.py  # Error propagation (graph, timeouts, state)
│   └── test_pipeline_flow.py     # End-to-end pipeline execution
│
├── e2e/                          # End-to-end deployment tests
│   └── test_deployment.py        # Health checks, service connectivity, config validation
│
├── conftest.py                   # Shared pytest fixtures and configuration
└── README.md                     # This file
```

## Running Tests

### All Tests
```bash
cd langchain_agent
PYTHONPATH=. .venv/bin/pytest tests/ -v
```

### By Scope

```bash
# Unit tests only (fast, ~0.5s)
PYTHONPATH=. .venv/bin/pytest tests/unit/ -v

# Integration tests (requires services, ~5-30s)
PYTHONPATH=. .venv/bin/pytest tests/integration/ -v

# E2E tests (requires deployment, ~10-60s)
PYTHONPATH=. .venv/bin/pytest tests/e2e/ -v
```

### By Component

```bash
# Reranker validation only
PYTHONPATH=. .venv/bin/pytest tests/unit/test_reranker.py -v

# Vector store and hybrid search
PYTHONPATH=. .venv/bin/pytest tests/unit/test_vector_store.py -v

# Intent classification (104 tests)
PYTHONPATH=. .venv/bin/pytest tests/integration/test_intent_routing.py -v

# Full pipeline E2E
PYTHONPATH=. .venv/bin/pytest tests/integration/test_pipeline_flow.py -v
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

## Test Results Summary

```
Total Tests: 248
├── Unit Tests: 78 (fast, no dependencies)
├── Integration Tests: 145 (requires services)
└── E2E Tests: 25 (requires deployment)

Status:
✅ 24 Unit tests passing
✅ 104 Intent routing tests passing (95%+ accuracy)
⏭️ 145 Integration tests (skipped without full stack)
⏭️ 25 E2E tests (skipped without deployment)
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
# Solution: Always set PYTHONPATH
PYTHONPATH=/Users/kevin/github/personal/rusty-compass/langchain_agent .venv/bin/pytest tests/
```

### ImportError: cannot import name 'XyzError'

```bash
# Solution: Add missing exception to exceptions.py (see MEMORY.md)
# The exceptions.py file must have all custom exception classes
```

### Tests timeout or hang

```bash
# Solution: Ensure services are running
docker compose ps
curl http://localhost:9200/_cluster/health  # OpenSearch
curl http://localhost:5432                  # PostgreSQL
```

### Skipped tests with "Requires full LangGraph setup"

```bash
# Solution: This is expected - some tests need async runtime
# To run integration tests:
./scripts/start.sh  # Start all services
PYTHONPATH=. .venv/bin/pytest tests/integration/ -v
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
