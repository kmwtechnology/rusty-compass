"""
Regression tests for `config_validation_attempts` state initialization.

Bug context (commit bc1d2d3):
    `_route_after_config_validation` does
        `attempts = state.get("config_validation_attempts", 0)`
    which falls back to 0 *only if the key is missing*. If the key is present
    with value `None`, `state.get` happily returns `None`, and the next line
        `attempts < CONFIG_VALIDATION_MAX_RETRIES`
    raises `TypeError: '<' not supported between instances of 'NoneType'
    and 'int'`.

    The fix initializes `config_validation_attempts: 0` (not `None`) in the
    `extra_fields` dict that `intent_classifier_node` returns when a hard
    mode shift triggers state cleanup. The router itself was not changed —
    so these tests pin the contract on the *producer* side:

      1. After a hard shift, `intent_classifier_node` MUST write `0`,
         never `None`, into `config_validation_attempts`.
      2. The router's existing behavior is documented: if a future edit
         re-introduces `None` into this field, the router raises TypeError
         loudly rather than silently routing wrong. This test acts as a
         tripwire — when caught, fix the producer, never the router.

Run:
    cd langchain_agent && PYTHONPATH=. .venv/bin/pytest \
        tests/unit/test_state_init.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make `langchain_agent` importable when running from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.messages import HumanMessage  # noqa: E402

from main import LucilleAgent  # noqa: E402


# ============================================================================
# Producer-side contract: intent_classifier_node never writes None
# ============================================================================


class TestIntentClassifierNodeConfigValidationAttempts:
    """
    On hard mode shift, `intent_classifier_node` resets workflow state. The
    `config_validation_attempts` field MUST be set to `0` (a real int), not
    `None`, so that downstream `_route_after_config_validation` can compare
    it against `CONFIG_VALIDATION_MAX_RETRIES` without a TypeError.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.agent = LucilleAgent()

    def test_hard_shift_from_config_to_question_zeros_attempts(self):
        """Hard shift away from config_builder must reset attempts to 0, not None."""
        state = {
            "messages": [HumanMessage(content="Tell me about RAG instead")],
            "agent_mode": "config_builder",
            "config_validation_attempts": 2,  # stale value from prior turn
        }
        with patch.object(
            self.agent,
            "_classify_intent",
            return_value=("question", "shifting away from config", 0.95, []),
        ):
            result = self.agent.intent_classifier_node(state)

        assert result.get("mode_shift_type") == "hard_shift"
        assert "config_validation_attempts" in result, (
            "hard_shift cleanup must explicitly write config_validation_attempts"
        )
        attempts = result["config_validation_attempts"]
        assert attempts is not None, (
            "config_validation_attempts must NEVER be None — downstream router "
            "compares it as int and would raise TypeError. Use 0 instead."
        )
        assert attempts == 0
        assert isinstance(attempts, int)
        assert not isinstance(attempts, bool), (
            "attempts must be a real int, not bool (True/False would silently "
            "satisfy isinstance(int) but break arithmetic semantics)."
        )

    def test_hard_shift_into_config_request_zeros_attempts(self):
        """Hard shift into config_builder must also start with attempts=0."""
        state = {
            "messages": [HumanMessage(content="Build me a CSV pipeline")],
            "agent_mode": "rag",
            # No prior config_validation_attempts — fresh shift into config mode.
        }
        with patch.object(
            self.agent,
            "_classify_intent",
            return_value=("config_request", "shifting into config", 0.95, []),
        ):
            result = self.agent.intent_classifier_node(state)

        assert result.get("mode_shift_type") == "hard_shift"
        attempts = result.get("config_validation_attempts")
        assert attempts == 0
        assert isinstance(attempts, int)

    def test_hard_shift_from_doc_writer_to_config_zeros_attempts(self):
        """Hard shift between non-rag modes must also reset attempts to 0."""
        state = {
            "messages": [HumanMessage(content="Now build me a config")],
            "agent_mode": "doc_writer",
        }
        with patch.object(
            self.agent,
            "_classify_intent",
            return_value=("config_request", "switching modes", 0.95, []),
        ):
            result = self.agent.intent_classifier_node(state)

        assert result.get("mode_shift_type") == "hard_shift"
        assert result.get("config_validation_attempts") == 0

    def test_continuation_does_not_overwrite_attempts(self):
        """
        Continuation must NOT include config_validation_attempts in the
        return dict — overwriting an in-flight retry counter with 0 mid-loop
        would let the loop run forever.
        """
        state = {
            "messages": [HumanMessage(content="What about DBs?")],
            "agent_mode": "config_builder",
            "config_validation_attempts": 1,
        }
        with patch.object(
            self.agent,
            "_classify_intent",
            return_value=("config_request", "stay in config_builder", 0.95, []),
        ):
            result = self.agent.intent_classifier_node(state)

        assert result.get("mode_shift_type") == "continuation"
        assert "config_validation_attempts" not in result, (
            "continuation must not touch config_validation_attempts — the "
            "retry counter is owned by the validator loop while in mode."
        )


# ============================================================================
# Router-side tripwire: routing with None is unsupported by design
# ============================================================================


class TestRouteAfterConfigValidationWithNone:
    """
    Pin the contract: `_route_after_config_validation` requires
    `config_validation_attempts` to be an int (or absent so .get() default
    kicks in). If a future edit re-introduces `None` into this field, this
    test fails loudly so the producer is fixed — not the router.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.agent = LucilleAgent()

    def test_router_raises_typeerror_when_attempts_is_none(self):
        """
        `state.get("config_validation_attempts", 0)` returns None when the
        key exists with value None — the default only applies when the key
        is missing. This tripwire fires if anyone reintroduces None.
        """
        state = {
            "config_validation_passed": False,
            "config_validation_attempts": None,
        }
        with pytest.raises(TypeError, match="NoneType"):
            self.agent._route_after_config_validation(state)

    def test_router_handles_missing_key_via_default(self):
        """
        Sanity check: when the key is *missing* (not None), the .get default
        of 0 takes effect and routing succeeds. This is the contract that
        producers must uphold — write 0, or do not write the key at all.
        """
        state = {"config_validation_passed": False}  # key intentionally absent
        result = self.agent._route_after_config_validation(state)
        # With attempts == 0 and max_retries >= 1, this routes to "retry".
        assert result in ("retry", "max_retries")

    def test_router_handles_zero_attempts(self):
        """The post-fix initial value (0) must route cleanly."""
        state = {
            "config_validation_passed": False,
            "config_validation_attempts": 0,
        }
        result = self.agent._route_after_config_validation(state)
        assert result == "retry"
