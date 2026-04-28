"""
Regression tests for `lucille_validator._dedupe_jars` and JVM error classification.

These tests pin the behavior introduced after the Jackson 2.17 / 2.19 classpath
duplication incident:
  - Stale duplicate jars must be dropped (newest version kept).
  - A WARNING must be logged so operators see the signal.
  - False positives must be avoided: same artifactId across different
    classifiers (native libs) or different groupIds (JetBrains vs Google
    'annotations') must NOT collapse.
  - JVM linkage / resource errors must classify as VALIDATOR_UNHEALTHY with no
    fake config errors leaking into `errors`.

Run:
    cd langchain_agent && PYTHONPATH=. .venv/bin/pytest \
        tests/unit/test_lucille_validator.py -v
"""

import logging
import sys
import zipfile
from pathlib import Path

import pytest

# Make `langchain_agent` importable when running from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lucille_validator import (  # noqa: E402
    ValidationOutcome,
    _dedupe_jars,
    _parse_validation_output,
)


# ============================================================================
# Helpers
# ============================================================================


def _write_jar(path: Path, group_id: str, artifact_id: str, version: str) -> Path:
    """Build a minimal Maven-shaped jar at `path` and return it.

    Embeds `META-INF/maven/<groupId>/<artifactId>/pom.properties` so
    `_read_maven_coords` recognizes the artifact authoritatively.
    """
    pom = (
        f"groupId={group_id}\n"
        f"artifactId={artifact_id}\n"
        f"version={version}\n"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            f"META-INF/maven/{group_id}/{artifact_id}/pom.properties",
            pom,
        )
    return path


# ============================================================================
# _dedupe_jars regression tests
# ============================================================================


class TestDedupeJarsJacksonVersionSkew:
    """Stale-version jars must be collapsed; the kept jar is the newest."""

    def test_jackson_core_2_17_dropped_in_favor_of_2_19(self, tmp_path, caplog):
        old_jar = _write_jar(
            tmp_path / "jackson-core-2.17.0.jar",
            "com.fasterxml.jackson.core",
            "jackson-core",
            "2.17.0",
        )
        new_jar = _write_jar(
            tmp_path / "jackson-core-2.19.1.jar",
            "com.fasterxml.jackson.core",
            "jackson-core",
            "2.19.1",
        )

        with caplog.at_level(logging.WARNING, logger="lucille_validator"):
            result = _dedupe_jars([old_jar, new_jar])

        assert new_jar in result, "newest jackson-core version must be kept"
        assert old_jar not in result, "stale 2.17.0 jackson-core must be dropped"
        assert len(result) == 1

        # WARN must mention the artifact and the dropped version so operators
        # see what happened in their logs.
        warn_messages = [
            rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
        ]
        assert warn_messages, "_dedupe_jars must WARN when collapsing duplicates"
        joined = "\n".join(warn_messages)
        assert "jackson-core" in joined
        assert "2.17.0" in joined

    def test_dedupe_picks_newest_regardless_of_input_order(self, tmp_path):
        # Reverse order from above to ensure ordering can't accidentally pick stale.
        new_jar = _write_jar(
            tmp_path / "jackson-databind-2.19.1.jar",
            "com.fasterxml.jackson.core",
            "jackson-databind",
            "2.19.1",
        )
        old_jar = _write_jar(
            tmp_path / "jackson-databind-2.17.0.jar",
            "com.fasterxml.jackson.core",
            "jackson-databind",
            "2.17.0",
        )
        result = _dedupe_jars([new_jar, old_jar])
        assert result == [new_jar]


class TestDedupeJarsClassifiersNotDuplicates:
    """Native-platform classifiers must NOT be treated as duplicates."""

    def test_netty_tcnative_native_classifiers_kept_separately(self, tmp_path, caplog):
        # netty-tcnative-boringssl-static ships per-OS native binaries with the
        # same groupId/artifactId/version but distinct classifiers. Loading all
        # is correct — collapsing them would break the JVM on platforms whose
        # classifier got dropped.
        osx = _write_jar(
            tmp_path / "netty-tcnative-boringssl-static-2.0.73.Final-osx-x86_64.jar",
            "io.netty",
            "netty-tcnative-boringssl-static",
            "2.0.73.Final",
        )
        linux = _write_jar(
            tmp_path
            / "netty-tcnative-boringssl-static-2.0.73.Final-linux-x86_64.jar",
            "io.netty",
            "netty-tcnative-boringssl-static",
            "2.0.73.Final",
        )

        with caplog.at_level(logging.WARNING, logger="lucille_validator"):
            result = _dedupe_jars([osx, linux])

        assert osx in result, "osx-x86_64 classifier must be kept"
        assert linux in result, "linux-x86_64 classifier must be kept"
        assert len(result) == 2

        # No "stale jar" WARN should fire when the inputs are simply different
        # classifiers of the same artifact.
        warn_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "dropped stale" in rec.getMessage()
        ]
        assert warn_messages == []


class TestDedupeJarsDistinctGroupIdsNotDuplicates:
    """Same artifactId in different groupIds is two distinct artifacts."""

    def test_jetbrains_vs_google_annotations_kept_separately(
        self, tmp_path, caplog
    ):
        # 'annotations' is a notoriously collision-prone artifactId. JetBrains
        # ships org.jetbrains:annotations:13.0 and Google ships
        # com.google.api:annotations:2.33.13. They are completely unrelated
        # libraries and must stay on the classpath together.
        jetbrains = _write_jar(
            tmp_path / "annotations-13.0.jar",
            "org.jetbrains",
            "annotations",
            "13.0",
        )
        google = _write_jar(
            tmp_path / "annotations-2.33.13.jar",
            "com.google.api",
            "annotations",
            "2.33.13",
        )

        with caplog.at_level(logging.WARNING, logger="lucille_validator"):
            result = _dedupe_jars([jetbrains, google])

        assert jetbrains in result
        assert google in result
        assert len(result) == 2

        # No "dropped stale" WARN should fire — they are different artifacts.
        warn_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "dropped stale" in rec.getMessage()
        ]
        assert warn_messages == []


# ============================================================================
# JVM linkage error classification — additional edge cases beyond the
# existing NoSuchMethodError test in tests/config_builder/test_config_builder.py
# ============================================================================


class TestJvmErrorClassification:
    """Each linkage/resource error class must classify as VALIDATOR_UNHEALTHY
    with no fake config errors surfaced in `errors`."""

    def test_incompatible_class_change_error(self):
        output = (
            'Exception in thread "main" java.lang.IncompatibleClassChangeError: '
            "Class com.fasterxml.jackson.core.JsonFactory does not implement "
            "the requested interface com.fasterxml.jackson.core.TSFBuilder\n"
            "\tat com.kmwllc.lucille.indexer.SolrIndexer.<init>(SolrIndexer.java:71)"
        )
        result = _parse_validation_output(output, 1)
        assert result.outcome == ValidationOutcome.VALIDATOR_UNHEALTHY
        assert result.valid is False
        assert result.can_retry is False
        assert result.errors == {}, "linkage errors must NOT leak as fake config errors"
        assert result.diagnostic and "IncompatibleClassChangeError" in result.diagnostic

    def test_no_such_field_error(self):
        output = (
            'Exception in thread "main" java.lang.NoSuchFieldError: '
            "DEFAULT_BASE_SETTINGS\n"
            "\tat com.kmwllc.lucille.core.Runner.<init>(Runner.java:42)"
        )
        result = _parse_validation_output(output, 1)
        assert result.outcome == ValidationOutcome.VALIDATOR_UNHEALTHY
        assert result.valid is False
        assert result.can_retry is False
        assert result.errors == {}
        assert result.diagnostic and "NoSuchFieldError" in result.diagnostic

    def test_out_of_memory_error(self):
        output = (
            'Exception in thread "main" java.lang.OutOfMemoryError: '
            "Java heap space\n"
            "\tat com.kmwllc.lucille.core.Runner.run(Runner.java:120)"
        )
        result = _parse_validation_output(output, 1)
        assert result.outcome == ValidationOutcome.VALIDATOR_UNHEALTHY
        assert result.valid is False
        assert result.can_retry is False
        assert result.errors == {}
        assert result.diagnostic and "OutOfMemoryError" in result.diagnostic
