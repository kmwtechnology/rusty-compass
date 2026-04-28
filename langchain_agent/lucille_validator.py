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
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import LUCILLE_PROJECT_DIR

logger = logging.getLogger(__name__)

# Filename-based fallback when a jar lacks Maven metadata. Captures
# "artifactId-version" with a non-greedy artifactId match anchored to the
# first digit-starting segment. Used only when pom.properties is absent.
_JAR_NAME_PATTERN = re.compile(r"^(.+?)-(\d[\w.\-]*)\.jar$")


class ValidationOutcome(str, Enum):
    """Classification of a validation attempt.

    Differentiates config-quality problems (LLM can iterate to fix) from
    validator-side problems (no amount of LLM retry will help).

    - VALID: config validates cleanly.
    - STRUCTURAL_ERRORS: spec violations in the user's config — retry-able.
    - PARSE_ERROR: HOCON syntax error — retry-able.
    - VALIDATOR_UNHEALTHY: validator process is broken (Jackson version
      mismatch, JVM linkage error, OOM). Operator action required.
    - MISSING_PLUGIN: optional plugin JAR missing from classpath. Validation
      is incomplete but the user's config isn't necessarily wrong.
    - TIMEOUT: validator subprocess exceeded its time budget — usually a
      connector trying to reach an external system.
    - VALIDATOR_UNAVAILABLE: validator binary/classpath not present.
    """

    VALID = "valid"
    STRUCTURAL_ERRORS = "structural_errors"
    PARSE_ERROR = "parse_error"
    VALIDATOR_UNHEALTHY = "validator_unhealthy"
    MISSING_PLUGIN = "missing_plugin"
    TIMEOUT = "timeout"
    VALIDATOR_UNAVAILABLE = "validator_unavailable"


# JVM linkage errors indicate validator-side dependency mismatches (e.g.,
# jackson-core/jackson-databind version skew). The LLM cannot fix these by
# editing HOCON; they require operator intervention on the validator's
# classpath. NoClassDefFoundError is intentionally excluded — it commonly
# means an optional plugin JAR is missing, handled separately.
_LINKAGE_ERROR_CLASSES = (
    "NoSuchMethodError",
    "IncompatibleClassChangeError",
    "AbstractMethodError",
    "NoSuchFieldError",
    "VerifyError",
    "UnsatisfiedLinkError",
    "ExceptionInInitializerError",
)
_JVM_RESOURCE_ERROR_CLASSES = (
    "OutOfMemoryError",
    "StackOverflowError",
)


@dataclass
class ValidationResult:
    """Result from validating a Lucille config.

    The primary signal is `outcome`. Callers should switch on it rather than
    `valid` alone, because `valid=False` covers both retry-able config bugs
    and non-retry-able validator infrastructure failures.
    """

    outcome: ValidationOutcome
    errors: Dict[str, List[str]] = field(default_factory=dict)
    diagnostic: Optional[str] = None
    raw_output: str = ""
    exit_code: int = 0

    @property
    def valid(self) -> bool:
        """True only when the validator confirmed the config is well-formed.

        Distinct from `should_block_response` — operators may want to surface
        configs to users even when validation was skipped (TIMEOUT,
        MISSING_PLUGIN) rather than blocking them on infra issues.
        """
        return self.outcome == ValidationOutcome.VALID

    @property
    def can_retry(self) -> bool:
        """Whether re-running the LLM with error feedback might fix this."""
        return self.outcome in (
            ValidationOutcome.STRUCTURAL_ERRORS,
            ValidationOutcome.PARSE_ERROR,
        )


def _parse_maven_version(version: str) -> Tuple:
    """Parse a Maven version string into a sortable key.

    Handles standard semver ('2.19.1'), qualifiers ('2.0.0-SNAPSHOT'), and
    mixed numeric/alpha tokens. Numeric segments sort numerically and rank
    below string segments at the same position, so '2.19.1' > '2.17.0' and
    '1.0.0' > '1.0.0-SNAPSHOT' (release > pre-release).
    """
    parts: List[Tuple[int, object]] = []
    for token in re.split(r"[.\-]", version):
        if not token:
            continue
        try:
            parts.append((0, int(token)))
        except ValueError:
            parts.append((1, token))
    return tuple(parts)


def _read_maven_coords(jar_path: Path) -> Optional[Tuple[str, str, str]]:
    """Read (groupId, artifactId, version) from a jar's embedded pom.properties.

    Maven-built artifacts embed `META-INF/maven/<groupId>/<artifactId>/pom.properties`
    by convention. This is the only authoritative way to distinguish artifacts
    that share a filename across groupIds (e.g., 'annotations-13.0.jar' from
    JetBrains vs 'annotations-2.33.13.jar' from Google). Returns None for jars
    without Maven metadata (rare for build dependencies) — caller falls back
    to filename parsing.
    """
    try:
        with zipfile.ZipFile(jar_path) as zf:
            for name in zf.namelist():
                if name.startswith("META-INF/maven/") and name.endswith("/pom.properties"):
                    with zf.open(name) as f:
                        props: Dict[str, str] = {}
                        for raw in f.read().decode("utf-8", errors="replace").splitlines():
                            line = raw.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            key, _, value = line.partition("=")
                            props[key.strip()] = value.strip()
                        gid = props.get("groupId")
                        aid = props.get("artifactId")
                        ver = props.get("version")
                        if gid and aid and ver:
                            return gid, aid, ver
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        logger.debug("Could not read Maven coords from %s: %s", jar_path.name, e)
    return None


def _extract_classifier(filename: str, artifact_id: str, version: str) -> Optional[str]:
    """Recover the Maven classifier from a jar filename.

    pom.properties does not record the classifier (it's part of the artifact
    coordinate but not the artifact's own metadata). Given authoritative
    artifactId+version from pom.properties, anything between them and '.jar'
    in the filename is the classifier. Common classifiers: 'tests', 'sources',
    'javadoc', 'osx-x86_64', 'linux-aarch_64'.
    """
    if not filename.endswith(".jar"):
        return None
    stem = filename[:-4]
    expected = f"{artifact_id}-{version}"
    if stem == expected:
        return None
    if stem.startswith(expected + "-"):
        return stem[len(expected) + 1:]
    return None


@dataclass(frozen=True)
class _JarCoords:
    """Classifier-aware Maven coordinates for a jar on disk."""

    group_id: Optional[str]  # None when pom.properties was unavailable
    artifact_id: str
    version: str
    classifier: Optional[str]
    path: Path

    @property
    def dedup_key(self) -> Tuple:
        """Identity key for "this is the same artifact at a different version".

        Includes groupId when known, so that distinct artifacts sharing an
        artifactId across groups (JetBrains vs Google 'annotations') stay in
        separate groups and don't get falsely deduped.
        """
        return (self.group_id, self.artifact_id, self.classifier)


def _classify_jar(jar_path: Path) -> Optional[_JarCoords]:
    """Classify a jar into Maven coordinates, preferring pom.properties."""
    coords = _read_maven_coords(jar_path)
    if coords is not None:
        gid, aid, ver = coords
        classifier = _extract_classifier(jar_path.name, aid, ver)
        return _JarCoords(gid, aid, ver, classifier, jar_path)

    # Fallback: parse filename. groupId is unknown, so dedup is best-effort.
    match = _JAR_NAME_PATTERN.match(jar_path.name)
    if match is None:
        return None
    return _JarCoords(None, match.group(1), match.group(2), None, jar_path)


def _dedupe_jars(jar_paths: List[Path]) -> List[Path]:
    """Collapse multiple versions of the same artifact to the newest one.

    Defends the validator's classpath against stale jars from older builds.
    Maven's copy-dependencies plugin doesn't clean its output directory
    before copying, so bumping a dependency version leaves the old jar on
    disk alongside the new one. Loading both into the same classloader
    produces JVM linkage errors (different class definitions of the same
    fully-qualified name) — exactly the Jackson 2.17 / 2.19 incident that
    silently broke validation.

    Dedup key is (groupId, artifactId, classifier) read from each jar's
    embedded pom.properties; this prevents false positives where jars with
    different groupIds happen to share an artifactId. When pom.properties is
    unavailable the key falls back to filename parsing — best-effort, with a
    DEBUG log noting the limitation.

    Logs WARNING when duplicates are detected so operators have a clear
    signal that an upstream `mvn clean package` is overdue.
    """
    grouped: Dict[Tuple, List[_JarCoords]] = defaultdict(list)
    unclassified: List[Path] = []
    for path in jar_paths:
        coords = _classify_jar(path)
        if coords is None:
            unclassified.append(path)
            continue
        grouped[coords.dedup_key].append(coords)

    result: List[Path] = []
    for key, members in grouped.items():
        if len(members) == 1:
            result.append(members[0].path)
            continue

        members.sort(key=lambda c: _parse_maven_version(c.version), reverse=True)
        kept = members[0]
        dropped = members[1:]
        identity = (
            f"{kept.group_id}:{kept.artifact_id}" if kept.group_id else kept.artifact_id
        )
        if kept.classifier:
            identity = f"{identity}:{kept.classifier}"
        logger.warning(
            "Validator classpath: dropped stale '%s' jars at versions %s; "
            "kept %s. Leftover artifacts from an earlier build — run "
            "'mvn clean package -DskipTests' in the Lucille project to "
            "remove the stale jars from disk.",
            identity,
            [d.version for d in dropped],
            kept.version,
        )
        result.append(kept.path)

    return result + unclassified


def _collect_jars(lib_dir: Path) -> List[Path]:
    """Return all .jar files in a directory, or an empty list if missing."""
    if not lib_dir.exists():
        return []
    return list(lib_dir.glob("*.jar"))


_CLASSPATH_CACHE: Optional[str] = None
_CLASSPATH_COMPUTED: bool = False


def _build_classpath() -> Optional[str]:
    """Build a deduplicated Java classpath from compiled Lucille artifacts.

    Returns None when the validator can't be located (treated as
    VALIDATOR_UNAVAILABLE upstream, not as an error). Result is cached at
    module level — dedup involves reading Maven metadata from inside each jar,
    so we pay that cost once per process rather than per validation call.
    """
    global _CLASSPATH_CACHE, _CLASSPATH_COMPUTED
    if _CLASSPATH_COMPUTED:
        return _CLASSPATH_CACHE

    lucille_dir = Path(LUCILLE_PROJECT_DIR)
    classes_dir = lucille_dir / "lucille-core" / "target" / "classes"
    lib_dir = lucille_dir / "lucille-core" / "target" / "lib"

    if not classes_dir.exists() or not lib_dir.exists():
        logger.debug("Lucille classes not found at %s", classes_dir)
        _CLASSPATH_CACHE = None
        _CLASSPATH_COMPUTED = True
        return None

    classes_dirs: List[Path] = [classes_dir]
    all_jars: List[Path] = _collect_jars(lib_dir)

    plugins_dir = lucille_dir / "lucille-plugins"
    if plugins_dir.exists():
        for plugin in plugins_dir.iterdir():
            plugin_classes = plugin / "target" / "classes"
            if plugin_classes.exists():
                classes_dirs.append(plugin_classes)
            all_jars.extend(_collect_jars(plugin / "target" / "lib"))

    deduped_jars = _dedupe_jars(all_jars)
    entries = [str(d) for d in classes_dirs] + [str(j) for j in deduped_jars]
    classpath = os.pathsep.join(entries)
    logger.info(
        "Validator classpath built: %d class dirs, %d jars (from %d before dedup)",
        len(classes_dirs), len(deduped_jars), len(all_jars),
    )

    _CLASSPATH_CACHE = classpath
    _CLASSPATH_COMPUTED = True
    return classpath


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
            outcome=ValidationOutcome.VALIDATOR_UNAVAILABLE,
            diagnostic="Lucille classes not found. Run 'mvn package -DskipTests' in lucille/",
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
        # Timeouts usually mean a connector is trying to reach an external
        # system (Solr, Kafka, etc.). The config structure may still be fine —
        # surface as TIMEOUT so callers can decide whether to block.
        logger.info(
            "Validator: timed out after %ds — likely a connector attempting "
            "to reach an external system. Validation incomplete.",
            timeout_seconds,
        )
        return ValidationResult(
            outcome=ValidationOutcome.TIMEOUT,
            diagnostic=f"Validator exceeded {timeout_seconds}s budget",
            exit_code=-1,
        )
    except FileNotFoundError:
        return ValidationResult(
            outcome=ValidationOutcome.VALIDATOR_UNAVAILABLE,
            diagnostic="Java not found in PATH",
            exit_code=-1,
        )
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass


def _extract_jvm_error(output: str, error_classes: tuple) -> Optional[str]:
    """Find a JVM-level error class in output and return a one-line summary.

    Pulls the line containing the matching error class plus the first stack
    frame, so operators see the failing call site without 18 lines of trace.
    Returns None if no match.
    """
    for klass in error_classes:
        # Match either fully-qualified ("java.lang.NoSuchMethodError") or
        # bare ("NoSuchMethodError"). Capture the message that follows.
        match = re.search(
            rf"(?:[\w.]*\.)?{re.escape(klass)}(?::\s*(.+))?",
            output,
        )
        if not match:
            continue
        message = (match.group(1) or "").strip()
        # Look for the first useful stack frame (skip Jackson/JVM internals).
        first_frame = re.search(r"\s+at\s+(com\.kmwllc\.[\w.$<>]+\([^)]+\))", output)
        frame = first_frame.group(1) if first_frame else None
        parts = [klass]
        if message:
            parts.append(message[:240])
        if frame:
            parts.append(f"at {frame}")
        return ": ".join(parts)
    return None


def _parse_validation_output(output: str, exit_code: int) -> ValidationResult:
    """Parse Runner validation output into a classified ValidationResult.

    The Runner produces log4j2 output with this format:
        26/04/08 16:05:06   INFO Runner: Pipeline Configuration is valid.
        26/04/08 16:05:06   INFO Runner: Pipeline Configuration is invalid. See exceptions for each element:
        \tpipeline1:
        \t\tErrors with com.kmwllc.lucille.stage.Concatenate (badConcat) Config: [...]

    Detection order (specific → general): JVM linkage errors, JVM resource
    errors, missing plugin classes, HOCON parse errors, structured config
    errors. Mixing these up causes stack traces to be reported as fake config
    errors — exactly the bug this function previously had.
    """
    # JVM linkage errors mean the validator's own dependencies are broken
    # (e.g., jackson-core/jackson-databind version skew). The user's config
    # cannot fix this; route to VALIDATOR_UNHEALTHY so the caller skips retry.
    linkage_diag = _extract_jvm_error(output, _LINKAGE_ERROR_CLASSES)
    if linkage_diag is not None:
        logger.error(
            "Validator unhealthy — JVM linkage error: %s. "
            "Operator action required: rebuild Lucille with consistent "
            "dependency versions (mvn package -DskipTests).",
            linkage_diag,
        )
        return ValidationResult(
            outcome=ValidationOutcome.VALIDATOR_UNHEALTHY,
            diagnostic=linkage_diag,
            raw_output=output,
            exit_code=exit_code,
        )

    resource_diag = _extract_jvm_error(output, _JVM_RESOURCE_ERROR_CLASSES)
    if resource_diag is not None:
        logger.error("Validator unhealthy — JVM resource exhaustion: %s", resource_diag)
        return ValidationResult(
            outcome=ValidationOutcome.VALIDATOR_UNHEALTHY,
            diagnostic=resource_diag,
            raw_output=output,
            exit_code=exit_code,
        )

    # Missing plugin JARs: validation incomplete, but the user's config might
    # still be fine for the components they're using. Don't block them.
    if "NoClassDefFoundError" in output:
        missing_match = re.search(r"NoClassDefFoundError:\s*([\w./$]+)", output)
        missing_class = missing_match.group(1) if missing_match else "unknown class"
        logger.info(
            "Validator: missing plugin class '%s' — validation incomplete, "
            "treating as non-blocking. Install the corresponding plugin JAR "
            "to enable full validation.",
            missing_class,
        )
        return ValidationResult(
            outcome=ValidationOutcome.MISSING_PLUGIN,
            diagnostic=f"Missing plugin class: {missing_class}",
            raw_output=output,
            exit_code=exit_code,
        )

    # HOCON parse errors: user-fixable, route to retry path.
    if "ConfigException" in output:
        parse_error = re.search(r'ConfigException[^:]*:\s*(.+?)(?:\n\tat|\Z)', output, re.DOTALL)
        msg = parse_error.group(1).strip() if parse_error else "HOCON parse error"
        logger.info("Validator: HOCON parse error — %s", msg[:200])
        return ValidationResult(
            outcome=ValidationOutcome.PARSE_ERROR,
            errors={"_parse": [msg[:500]]},
            raw_output=output,
            exit_code=exit_code,
        )

    # Other unstructured Java exceptions with no validation output to fall
    # back on — treat as validator unhealthy rather than as 18 fake errors.
    has_structured = "Configuration is" in output
    if not has_structured and (
        "Exception in thread" in output or "ClassNotFoundException" in output
    ):
        first_line = next(
            (l.strip() for l in output.splitlines() if "Exception" in l or "Error" in l),
            "Java runtime error",
        )
        logger.error("Validator unhealthy — unhandled Java exception: %s", first_line[:240])
        return ValidationResult(
            outcome=ValidationOutcome.VALIDATOR_UNHEALTHY,
            diagnostic=first_line[:500],
            raw_output=output,
            exit_code=exit_code,
        )

    errors: Dict[str, List[str]] = {}

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

    if errors:
        return ValidationResult(
            outcome=ValidationOutcome.STRUCTURAL_ERRORS,
            errors=errors,
            raw_output=output,
            exit_code=exit_code,
        )
    return ValidationResult(
        outcome=ValidationOutcome.VALID,
        raw_output=output,
        exit_code=exit_code,
    )
