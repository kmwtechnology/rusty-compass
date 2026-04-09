"""
Python wrapper around Lucille's Java config validator.

Invokes Runner.runInValidationMode() via CLI to validate generated HOCON configs
without connecting to any external systems (bypass mode).
"""

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config import LUCILLE_PROJECT_DIR

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result from validating a Lucille config."""
    valid: bool
    errors: Dict[str, List[str]] = field(default_factory=dict)
    raw_output: str = ""
    exit_code: int = 0


def _build_classpath() -> Optional[str]:
    """Build Java classpath from compiled Lucille artifacts."""
    lucille_dir = Path(LUCILLE_PROJECT_DIR)
    classes_dir = lucille_dir / "lucille-core" / "target" / "classes"
    lib_dir = lucille_dir / "lucille-core" / "target" / "lib"

    if not classes_dir.exists() or not lib_dir.exists():
        logger.debug(f"Lucille classes not found at {classes_dir}")
        return None

    jars = list(lib_dir.glob("*.jar"))
    classpath_entries = [str(classes_dir)] + [str(j) for j in jars]

    # Include plugin classes and dependency JARs if available
    plugins_dir = lucille_dir / "lucille-plugins"
    if plugins_dir.exists():
        for plugin in plugins_dir.iterdir():
            plugin_classes = plugin / "target" / "classes"
            if plugin_classes.exists():
                classpath_entries.append(str(plugin_classes))
            plugin_lib = plugin / "target" / "lib"
            if plugin_lib.exists():
                classpath_entries.extend(str(j) for j in plugin_lib.glob("*.jar"))

    return os.pathsep.join(classpath_entries)


_VALIDATOR_AVAILABLE: Optional[bool] = None


def is_validator_available() -> bool:
    """Check if the Java validator is available (result is cached)."""
    global _VALIDATOR_AVAILABLE
    if _VALIDATOR_AVAILABLE is None:
        classpath = _build_classpath()
        if classpath is None:
            _VALIDATOR_AVAILABLE = False
        else:
            try:
                result = subprocess.run(
                    ["java", "-version"],
                    capture_output=True, timeout=5,
                )
                _VALIDATOR_AVAILABLE = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                _VALIDATOR_AVAILABLE = False

        logger.info(f"Lucille validator available: {_VALIDATOR_AVAILABLE}")

    return _VALIDATOR_AVAILABLE


def validate_config(config_text: str, timeout_seconds: int = 30) -> ValidationResult:
    """
    Validate a Lucille HOCON config using the Java validator.

    Writes config to a temp file, invokes Runner in validation mode,
    parses the output for validation errors.

    Returns ValidationResult with valid=True if no errors found.
    """
    classpath = _build_classpath()
    if classpath is None:
        return ValidationResult(
            valid=False,
            errors={"_system": ["Lucille classes not found. Run 'mvn package -DskipTests' in lucille/"]},
            raw_output="",
            exit_code=-1,
        )

    # Write config to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", delete=False, prefix="lucille_validate_"
    ) as f:
        f.write(config_text)
        config_path = f.name

    try:
        result = subprocess.run(
            [
                "java",
                f"-Dconfig.file={config_path}",
                "-Dlog4j2.configurationFile=classpath:log4j2.xml",
                "-cp", classpath,
                "com.kmwllc.lucille.core.Runner",
                "-validate",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        combined_output = (result.stdout or "") + (result.stderr or "")
        return _parse_validation_output(combined_output, result.returncode)

    except subprocess.TimeoutExpired:
        # Timeouts usually mean a connector is trying to connect to an external
        # system (Solr, Kafka, etc.) — not a config structure problem
        logger.info("Validator: timed out (likely connector trying to connect) — treating as valid")
        return ValidationResult(
            valid=True,
            errors={},
            raw_output="",
            exit_code=-1,
        )
    except FileNotFoundError:
        return ValidationResult(
            valid=False,
            errors={"_system": ["Java not found in PATH"]},
            raw_output="",
            exit_code=-1,
        )
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass


def _parse_validation_output(output: str, exit_code: int) -> ValidationResult:
    """Parse Runner validation output into structured errors.

    The Runner produces log4j2 output with this format:
        26/04/08 16:05:06   INFO Runner: Pipeline Configuration is valid.
        26/04/08 16:05:06   INFO Runner: Pipeline Configuration is invalid. See exceptions for each element:
        \tpipeline1:
        \t\tErrors with com.kmwllc.lucille.stage.Concatenate (badConcat) Config: [...]
    """
    errors: Dict[str, List[str]] = {}

    # Check for Java-level exceptions (classpath issues, etc.)
    # NoClassDefFoundError = missing plugin JARs, not a config problem — treat as valid
    if "NoClassDefFoundError" in output:
        logger.info("Validator: NoClassDefFoundError (missing plugin dependencies) — treating as valid")
        return ValidationResult(valid=True, errors={}, raw_output=output, exit_code=exit_code)
    # If output contains both structured validation AND an exception, prefer parsing
    # the structured output (e.g., SolrConnector logs errors then throws)
    has_structured = "Configuration is" in output
    if not has_structured and ("Exception in thread" in output or "ClassNotFoundException" in output):
        errors["_system"] = [f"Java runtime error: {output[:500]}"]
        return ValidationResult(valid=False, errors=errors, raw_output=output, exit_code=exit_code)

    # Check for HOCON parse errors
    if "com.typesafe.config.ConfigException" in output or "ConfigException" in output:
        parse_error = re.search(r'ConfigException[^:]*:\s*(.+?)(?:\n\tat|\Z)', output, re.DOTALL)
        msg = parse_error.group(1).strip() if parse_error else "HOCON parse error"
        errors["_parse"] = [msg[:500]]
        return ValidationResult(valid=False, errors=errors, raw_output=output, exit_code=exit_code)

    # Parse structured validation output from log lines
    # Each line may be prefixed with timestamp + log level: "26/04/08 16:05:06   INFO Runner: "
    current_component = None

    for raw_line in output.split("\n"):
        # Strip log4j2 prefix (timestamp + level + logger)
        line = re.sub(r'^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S*\s+\w+\s+\w+:\s*', '', raw_line)
        stripped = line.strip()

        if not stripped:
            continue

        # "Configuration is valid" — no errors for this category
        if "Configuration is valid" in stripped:
            current_component = None
            continue

        # "Configuration is invalid" — errors follow
        if "Configuration is invalid" in stripped:
            current_component = None
            continue

        # Component name line (tab-indented, ends with colon, e.g., "\tpipeline1:")
        component_match = re.match(r'^[\t ]*(\w[\w\[\].]*):$', stripped)
        if component_match:
            current_component = component_match.group(1)
            if current_component not in errors:
                errors[current_component] = []
            continue

        # Error message line (tab-indented under component)
        if current_component and stripped:
            # Clean up prefixes like:
            # "Error with Connector class / constructor: null"
            # "Errors with com.kmwllc.lucille.stage.Concatenate (badConcat) Config: [msg1, msg2]"
            # "Error with pipeline1 Config: Config contains unknown property X"
            cleaned = re.sub(
                r'^Errors?\s+with\s+[\w./]+(?:\s*\([^)]+\))?\s+(?:Config|class\s*/\s*constructor):\s*',
                '', stripped
            )
            # Handle bracketed error lists: [error1, error2]
            # Skip bare "null" messages (constructor failures, not spec errors)
            if cleaned == "null":
                continue
            if cleaned.startswith("[") and cleaned.endswith("]"):
                # Split on ", Config " pattern to separate individual errors
                inner = cleaned[1:-1]
                individual = re.split(r',\s*(?=Config\s)', inner)
                for err in individual:
                    errors[current_component].append(err.strip())
            else:
                errors[current_component].append(cleaned)
            continue

        # Standalone error line (e.g., from indexer/other validation with list format)
        # "Indexer Configuration is invalid. Errors:\n\tmessage"
        if stripped and not current_component and "Configuration" not in stripped:
            # Treat as indexer/other error
            if "indexer" not in errors:
                errors["indexer"] = []
            if stripped != "null":
                errors["indexer"].append(stripped)

    # Remove empty error lists (components with only null/filtered messages)
    errors = {k: v for k, v in errors.items() if v}

    # Filter out errors that are infrastructure issues, not config structure problems:
    # - "Unknown indexer.type" for plugin indexers (Weaviate, Pinecone, etc.)
    # - Connector constructor failures (can't connect to Solr/Kafka/DB)
    # - "No configuration setting found for key" (missing indexer-specific config block)
    NON_STRUCTURAL_PATTERNS = [
        r"Unknown indexer\.type",
        r"Error with Connector class / constructor",
        r"No configuration setting found for key",
    ]
    for key in list(errors.keys()):
        errors[key] = [
            e for e in errors[key]
            if not any(re.search(pat, e) for pat in NON_STRUCTURAL_PATTERNS)
        ]
    errors = {k: v for k, v in errors.items() if v}

    # If exit code is non-zero but we found no specific errors, note it
    if exit_code != 0 and not errors:
        errors["_unknown"] = [f"Validator exited with code {exit_code}"]

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        raw_output=output,
        exit_code=exit_code,
    )
