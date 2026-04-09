"""
Tests for config builder enhancements: catalog, validator, few-shot selection, and live graph.

Run all tests:
    cd langchain_agent && source .venv/bin/activate
    python -m pytest tests/config_builder/test_config_builder.py -v

Run unit tests only (no API keys or Docker needed):
    python -m pytest tests/config_builder/test_config_builder.py -v -k "not live"

Run live tests only (requires GOOGLE_API_KEY, PostgreSQL, OpenSearch):
    python -m pytest tests/config_builder/test_config_builder.py -v -k "live"
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure langchain_agent is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

TESTS_DIR = Path(__file__).parent
PROJECT_DIR = TESTS_DIR.parent.parent
LUCILLE_DIR = PROJECT_DIR.parent / "lucille"


# ============================================================================
# Config Validation Routing Tests
# ============================================================================

class TestConfigValidationRouting:
    """Tests for _route_after_config_validation() in main.py."""

    def test_route_when_validation_passed(self):
        """When config passes validation, route to response."""
        from main import LucilleAgent
        agent = LucilleAgent()

        state = {
            "config_validation_passed": True,
            "config_validation_attempts": 1,
        }
        result = agent._route_after_config_validation(state)
        assert result == "valid"

    def test_route_when_validation_failed_with_retries_remaining(self):
        """When validation fails but retries remain, route back to generator."""
        from main import LucilleAgent
        from config import CONFIG_VALIDATION_MAX_RETRIES

        agent = LucilleAgent()

        # With max_retries=2, attempt 1 should retry
        state = {
            "config_validation_passed": False,
            "config_validation_attempts": 1,
        }
        result = agent._route_after_config_validation(state)
        assert result == "retry", f"Attempt 1 of {CONFIG_VALIDATION_MAX_RETRIES} should retry"

    def test_route_when_validation_failed_at_max_retries(self):
        """When validation fails at max retries, route to response with errors."""
        from main import LucilleAgent
        from config import CONFIG_VALIDATION_MAX_RETRIES

        agent = LucilleAgent()

        # With max_retries=2, attempt 2 should NOT retry (move to max_retries)
        state = {
            "config_validation_passed": False,
            "config_validation_attempts": CONFIG_VALIDATION_MAX_RETRIES,
        }
        result = agent._route_after_config_validation(state)
        assert result == "max_retries", f"Attempt {CONFIG_VALIDATION_MAX_RETRIES} should reach max_retries"

    def test_route_prevents_infinite_retries(self):
        """Ensure routing logic prevents attempts beyond max_retries."""
        from main import LucilleAgent
        from config import CONFIG_VALIDATION_MAX_RETRIES

        agent = LucilleAgent()

        # Attempt beyond max_retries should also return max_retries
        state = {
            "config_validation_passed": False,
            "config_validation_attempts": CONFIG_VALIDATION_MAX_RETRIES + 5,
        }
        result = agent._route_after_config_validation(state)
        assert result == "max_retries"


# ============================================================================
# Component Catalog Tests
# ============================================================================

class TestComponentCatalog:
    """Tests for extract_specs.py and component_catalog.json."""

    @pytest.fixture(autouse=True)
    def load_catalog(self):
        catalog_path = PROJECT_DIR / "data" / "component_catalog.json"
        assert catalog_path.exists(), f"Catalog not found at {catalog_path}. Run: python scripts/extract_specs.py"
        with open(catalog_path) as f:
            self.catalog = json.load(f)
        self.components = self.catalog["components"]

    def test_catalog_has_components(self):
        assert self.catalog["component_count"] >= 85, f"Expected 85+ components, got {self.catalog['component_count']}"

    def test_catalog_has_all_types(self):
        types = {c["component_type"] for c in self.components.values()}
        assert "stage" in types
        assert "connector" in types
        assert "indexer" in types

    @pytest.mark.parametrize("name,expected_type,expected_params", [
        ("CopyFields", "stage", ["fieldMapping", "updateMode", "isNested"]),
        ("OpenSearchIndexer", "indexer", ["index", "url"]),
        ("FileConnector", "connector", ["paths"]),
        ("DeleteFields", "stage", ["fields"]),
        ("RenameFields", "stage", ["fieldMapping"]),
        ("Concatenate", "stage", ["dest", "formatString"]),
        ("TextExtractor", "stage", []),
        ("DatabaseConnector", "connector", []),
    ])
    def test_component_spot_check(self, name, expected_type, expected_params):
        comp = self.components.get(name)
        assert comp is not None, f"{name} not found in catalog"
        assert comp["component_type"] == expected_type, f"{name} type={comp['component_type']}, expected={expected_type}"
        param_names = [p["name"] for p in comp["parameters"]]
        for param in expected_params:
            assert param in param_names, f"{name} missing param '{param}', has: {param_names}"

    def test_catalog_regeneration(self):
        """Verify extract_specs.py produces consistent output."""
        result = subprocess.run(
            [sys.executable, str(PROJECT_DIR / "scripts" / "extract_specs.py")],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"extract_specs.py failed: {result.stderr}"
        assert "Wrote" in result.stdout


# ============================================================================
# Catalog Lookup Tests
# ============================================================================

class TestCatalogLookup:
    """Tests for deterministic catalog lookup in config_resolver_node."""

    @pytest.fixture(autouse=True)
    def load_catalog(self):
        catalog_path = PROJECT_DIR / "data" / "component_catalog.json"
        with open(catalog_path) as f:
            data = json.load(f)
        self.catalog = {name.lower(): spec for name, spec in data.get("components", {}).items()}

    @pytest.mark.parametrize("name,should_find", [
        ("copyfields", True),
        ("CopyFields", True),
        ("COPYFIELDS", True),
        ("opensearchindexer", True),
        ("fileconnector", True),
        ("NonExistentThing", False),
        ("textextractor", True),
        ("deletefields", True),
        ("renamefields", True),
        ("concatenate", True),
    ])
    def test_case_insensitive_lookup(self, name, should_find):
        found = name.lower() in self.catalog
        assert found == should_find, f"lookup('{name}'): found={found}, expected={should_find}"


# ============================================================================
# Few-Shot Example Selection Tests
# ============================================================================

class TestFewShotSelection:
    """Tests for _select_examples() in config_builder.py."""

    @pytest.fixture(autouse=True)
    def import_selector(self):
        # Import from the project root config_builder (not the test package)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "config_builder_mod",
            str(PROJECT_DIR / "config_builder.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.select = mod._select_examples
        self.examples = mod._EXAMPLE_CONFIGS

    def test_examples_exist(self):
        assert len(self.examples) >= 4, f"Expected 4+ examples, got {len(self.examples)}"

    def test_selects_opensearch_for_csv_rename(self):
        components = [
            {"name": "CSVConnector", "type": "connector"},
            {"name": "RenameFields", "type": "stage"},
            {"name": "OpenSearchIndexer", "type": "indexer"},
        ]
        selected = self.select(components)
        # Should select opensearch_ingest (has RenameFields + OpenSearchIndexer)
        assert any("opensearch" in ex[:50].lower() for ex in selected), \
            f"Expected OpenSearch example, got configs starting with: {[ex[:40] for ex in selected]}"

    def test_selects_db_for_database_pipeline(self):
        components = [
            {"name": "DatabaseConnector", "type": "connector"},
            {"name": "CopyFields", "type": "stage"},
            {"name": "OpenSearchIndexer", "type": "indexer"},
        ]
        selected = self.select(components)
        assert any("database" in ex.lower() or "Database" in ex for ex in selected), \
            f"Expected DB example in selection"

    def test_always_returns_results(self):
        components = [{"name": "UnknownThing", "type": "stage"}]
        selected = self.select(components)
        assert len(selected) > 0, "Should return at least one example even with no matches"


# ============================================================================
# Lucille Validator Tests
# ============================================================================

class TestLucilleValidator:
    """Tests for lucille_validator.py — requires Java and compiled Lucille."""

    @pytest.fixture(autouse=True)
    def check_java(self):
        try:
            result = subprocess.run(["java", "-version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                pytest.skip("Java not available")
        except FileNotFoundError:
            pytest.skip("Java not available")

        classes = LUCILLE_DIR / "lucille-core" / "target" / "classes"
        if not classes.exists():
            pytest.skip("Lucille not compiled")

    def _validate_file(self, conf_path: Path) -> dict:
        """Run validator on a .conf file and parse output."""
        classes_dir = LUCILLE_DIR / "lucille-core" / "target" / "classes"
        lib_dir = LUCILLE_DIR / "lucille-core" / "target" / "lib"
        cp_entries = [str(classes_dir)] + [str(j) for j in lib_dir.glob("*.jar")]

        plugins_dir = LUCILLE_DIR / "lucille-plugins"
        if plugins_dir.exists():
            for plugin in plugins_dir.iterdir():
                pc = plugin / "target" / "classes"
                if pc.exists():
                    cp_entries.append(str(pc))
                pl = plugin / "target" / "lib"
                if pl.exists():
                    cp_entries.extend(str(j) for j in pl.glob("*.jar"))

        cp = os.pathsep.join(cp_entries)
        result = subprocess.run(
            ["java", f"-Dconfig.file={conf_path}",
             "-Dlog4j2.configurationFile=classpath:log4j2.xml",
             "-cp", cp, "com.kmwllc.lucille.core.Runner", "-validate"],
            capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return {"output": output, "exit_code": result.returncode}

    def test_valid_config(self):
        result = self._validate_file(TESTS_DIR / "test_valid.conf")
        # Should not contain spec errors (null constructor errors are OK)
        assert "unknown property" not in result["output"]
        assert "missing required property" not in result["output"]

    def test_invalid_config_detects_errors(self):
        result = self._validate_file(TESTS_DIR / "test_invalid.conf")
        assert "unknown property unknownProp" in result["output"]
        assert "missing required property dest" in result["output"]
        assert "missing required property formatString" in result["output"]


# ============================================================================
# Validator Output Parser Tests
# ============================================================================

class TestValidatorParser:
    """Tests for _parse_validation_output() in lucille_validator.py."""

    @pytest.fixture(autouse=True)
    def import_parser(self):
        from lucille_validator import _parse_validation_output
        self.parse = _parse_validation_output

    def test_valid_output(self):
        output = (
            "26/04/08 16:06:24   INFO Runner: Pipeline Configuration is invalid. "
            "See exceptions for each element:\n"
            "\tpipeline1:\n"
            "\t\tnull\n"
            "26/04/08 16:06:24   INFO Runner: Connector Configuration is invalid. "
            "See exceptions for each element:\n"
            "\tconnector1:\n"
            "\t\tError with Connector class / constructor: null\n"
            "26/04/08 16:06:24   INFO Runner: Indexer Configuration is valid.\n"
            "26/04/08 16:06:24   INFO Runner: Other (Publisher, Runner, etc.) Configuration is valid."
        )
        result = self.parse(output, 0)
        assert result.valid is True, f"Expected valid (null errors filtered), got errors: {result.errors}"

    def test_spec_errors_detected(self):
        output = (
            "26/04/08 16:05:06   INFO Runner: Pipeline Configuration is invalid. "
            "See exceptions for each element:\n"
            "\tpipeline1:\n"
            "\t\tErrors with com.kmwllc.lucille.stage.Concatenate (badConcat) Config: "
            "[Config is missing required property dest, Config contains unknown property "
            "invalidProp, Config is missing required property formatString]\n"
            "26/04/08 16:05:06   INFO Runner: Connector Configuration is valid.\n"
            "26/04/08 16:05:06   INFO Runner: Indexer Configuration is valid.\n"
            "26/04/08 16:05:06   INFO Runner: Other (Publisher, Runner, etc.) Configuration is valid."
        )
        result = self.parse(output, 0)
        assert result.valid is False
        assert "pipeline1" in result.errors
        errors = result.errors["pipeline1"]
        assert any("missing required property dest" in e for e in errors)
        assert any("unknown property invalidProp" in e for e in errors)
        assert any("missing required property formatString" in e for e in errors)

    def test_noclassdeffounderror_treated_as_valid(self):
        output = (
            "Exception in thread \"main\" java.lang.NoClassDefFoundError: "
            "org/apache/tika/parser/Parser\n"
            "\tat java.base/java.lang.Class.forName0(Native Method)"
        )
        result = self.parse(output, 0)
        assert result.valid is True

    def test_hocon_parse_error(self):
        output = (
            "Exception in thread \"main\" com.typesafe.config.ConfigException$Parse: "
            "file.conf: 5: Expecting a value but got end of file"
        )
        result = self.parse(output, 1)
        assert result.valid is False
        # Parse errors may land in _parse or _system depending on order of checks
        assert "_parse" in result.errors or "_system" in result.errors


# ============================================================================
# Live Graph Tests (require API keys + Docker)
# ============================================================================

@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY") and not Path(PROJECT_DIR / ".env").exists(),
    reason="GOOGLE_API_KEY not set and no .env file",
)
class TestLiveConfigBuilder:
    """Live end-to-end tests through the LangGraph pipeline."""

    @pytest.fixture(autouse=True)
    def setup_agent(self):
        os.environ.setdefault("ENABLE_CONFIG_VALIDATION", "true")
        from main import LucilleAgent
        self.agent = LucilleAgent()
        self.agent.initialize_components()
        self.agent.create_agent_graph()

    @pytest.mark.asyncio
    async def _run_query(self, query: str, thread_id: str) -> dict:
        return await self.agent.app.ainvoke(
            {"messages": [("human", query)]},
            config={"configurable": {"thread_id": thread_id}},
        )

    @pytest.mark.asyncio
    async def test_live_csv_to_opensearch(self):
        result = await self._run_query(
            "Build a CSV to OpenSearch pipeline with field renaming",
            "pytest-csv-os",
        )
        assert result.get("intent") == "config_request"
        assert result.get("agent_mode") == "config_builder"
        components = result.get("config_components", [])
        assert len(components) >= 2
        assert all(c.get("resolution_source") == "catalog" for c in components), \
            f"Not all from catalog: {[(c['name'], c.get('resolution_source')) for c in components]}"

    @pytest.mark.asyncio
    async def test_live_s3_to_opensearch(self):
        result = await self._run_query(
            "Create a pipeline that ingests from S3 and indexes into OpenSearch with text extraction",
            "pytest-s3-os",
        )
        assert result.get("intent") == "config_request"
        components = result.get("config_components", [])
        assert all(c.get("resolution_source") == "catalog" for c in components), \
            f"Not all from catalog: {[(c['name'], c.get('resolution_source')) for c in components]}"

    @pytest.mark.asyncio
    async def test_live_db_to_opensearch(self):
        result = await self._run_query(
            "Build a database to OpenSearch pipeline with field copying and concatenation",
            "pytest-db-os",
        )
        assert result.get("intent") == "config_request"
        assert result.get("config_validation_passed") is True
        assert result.get("config_validation_attempts") == 1
        components = result.get("config_components", [])
        assert all(c.get("resolution_source") == "catalog" for c in components)
