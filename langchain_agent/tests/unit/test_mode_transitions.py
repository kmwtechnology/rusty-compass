"""
Unit tests for workflow state management / mode transition logic.

Tests cover:
- _detect_mode_shift() for all permutations of (current_mode, new_intent)
- _route_after_intent() with mode shift scenarios
- Stale awaiting_clarification reset on hard_shift
- State cleanup fields after hard_shift (from intent_classifier_node)
- follow_up soft_shift routing back to previous mode

Run:
    cd langchain_agent
    python -m pytest tests/unit/test_mode_transitions.py -v
"""

import sys
from pathlib import Path
import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from main import LucilleAgent


# ============================================================================
# TestDetectModeShift — _detect_mode_shift() permutation tests
# ============================================================================

class TestDetectModeShift:
    """Tests for LucilleAgent._detect_mode_shift()."""

    @pytest.fixture(autouse=True)
    def agent(self):
        self.agent = LucilleAgent()

    # -- continuation cases --

    def test_continuation_no_prior_mode_question(self):
        state = {}  # no agent_mode set
        assert self.agent._detect_mode_shift(state, "question") == "continuation"

    def test_continuation_no_prior_mode_follow_up(self):
        state = {}
        assert self.agent._detect_mode_shift(state, "follow_up") == "continuation"

    def test_continuation_rag_to_question(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "question") == "continuation"

    def test_continuation_rag_to_follow_up(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "follow_up") == "continuation"

    def test_continuation_rag_to_summary(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "summary") == "continuation"

    def test_continuation_rag_to_clarify(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "clarify") == "continuation"

    def test_continuation_config_builder_to_config_request(self):
        state = {"agent_mode": "config_builder"}
        assert self.agent._detect_mode_shift(state, "config_request") == "continuation"

    def test_continuation_doc_writer_to_documentation_request(self):
        state = {"agent_mode": "doc_writer"}
        assert self.agent._detect_mode_shift(state, "documentation_request") == "continuation"

    # -- soft_shift cases --

    def test_soft_shift_follow_up_after_config_builder(self):
        state = {"agent_mode": "config_builder"}
        assert self.agent._detect_mode_shift(state, "follow_up") == "soft_shift"

    def test_soft_shift_follow_up_after_doc_writer(self):
        state = {"agent_mode": "doc_writer"}
        assert self.agent._detect_mode_shift(state, "follow_up") == "soft_shift"

    # -- hard_shift cases --

    def test_hard_shift_config_to_doc(self):
        state = {"agent_mode": "config_builder"}
        assert self.agent._detect_mode_shift(state, "documentation_request") == "hard_shift"

    def test_hard_shift_doc_to_config(self):
        state = {"agent_mode": "doc_writer"}
        assert self.agent._detect_mode_shift(state, "config_request") == "hard_shift"

    def test_hard_shift_config_to_question(self):
        state = {"agent_mode": "config_builder"}
        assert self.agent._detect_mode_shift(state, "question") == "hard_shift"

    def test_hard_shift_doc_to_question(self):
        state = {"agent_mode": "doc_writer"}
        assert self.agent._detect_mode_shift(state, "question") == "hard_shift"

    def test_hard_shift_config_to_summary(self):
        state = {"agent_mode": "config_builder"}
        assert self.agent._detect_mode_shift(state, "summary") == "hard_shift"

    def test_hard_shift_doc_to_clarify(self):
        state = {"agent_mode": "doc_writer"}
        assert self.agent._detect_mode_shift(state, "clarify") == "hard_shift"

    def test_hard_shift_rag_to_config(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "config_request") == "hard_shift"

    def test_hard_shift_rag_to_doc(self):
        state = {"agent_mode": "rag"}
        assert self.agent._detect_mode_shift(state, "documentation_request") == "hard_shift"

    def test_hard_shift_first_turn_config(self):
        """First turn config request (no prior mode) should be hard_shift from implicit rag."""
        state = {}
        assert self.agent._detect_mode_shift(state, "config_request") == "hard_shift"

    def test_hard_shift_first_turn_doc(self):
        """First turn doc request (no prior mode) should be hard_shift from implicit rag."""
        state = {}
        assert self.agent._detect_mode_shift(state, "documentation_request") == "hard_shift"


# ============================================================================
# TestRouteAfterIntentModeShifts — _route_after_intent() with shift scenarios
# ============================================================================

class TestRouteAfterIntentModeShifts:
    """Tests for mode-shift routing logic in _route_after_intent()."""

    @pytest.fixture(autouse=True)
    def agent(self):
        self.agent = LucilleAgent()

    def test_follow_up_after_config_builder_routes_to_config_builder(self):
        """Soft shift: follow_up while in config mode should stay in config pipeline."""
        state = {
            "agent_mode": "config_builder",
            "previous_agent_mode": "config_builder",
            "mode_shift_type": "soft_shift",
            "intent": "follow_up",
        }
        result = self.agent._route_after_intent(state)
        assert result == "config_builder"

    def test_follow_up_after_doc_writer_routes_to_doc_writer(self):
        """Soft shift: follow_up while in doc_writer should stay in doc pipeline."""
        state = {
            "agent_mode": "doc_writer",
            "previous_agent_mode": "doc_writer",
            "mode_shift_type": "soft_shift",
            "intent": "follow_up",
        }
        result = self.agent._route_after_intent(state)
        assert result == "doc_writer"

    def test_follow_up_in_rag_still_routes_to_other(self):
        """Continuation: follow_up in RAG mode should use normal RAG pipeline."""
        state = {
            "agent_mode": "rag",
            "previous_agent_mode": "rag",
            "mode_shift_type": "continuation",
            "intent": "follow_up",
        }
        result = self.agent._route_after_intent(state)
        assert result == "other"

    def test_hard_shift_bypasses_stale_awaiting_clarification(self):
        """Hard shift should not get trapped by stale awaiting_clarification."""
        state = {
            "agent_mode": "doc_writer",
            "previous_agent_mode": "doc_writer",
            "mode_shift_type": "hard_shift",
            "intent": "config_request",
            "awaiting_clarification": True,  # stale
            "clarification_type": "format",
        }
        result = self.agent._route_after_intent(state)
        assert result == "config_builder"

    def test_legitimate_clarification_still_routes_correctly(self):
        """A real in-mode clarification response must still hit the resolver."""
        state = {
            "agent_mode": "doc_writer",
            "previous_agent_mode": "doc_writer",
            "mode_shift_type": "continuation",
            "intent": "follow_up",  # user answering the clarification
            "awaiting_clarification": True,
            "clarification_type": "format",
        }
        result = self.agent._route_after_intent(state)
        assert result == "format_resolver"

    def test_config_request_routes_to_config_builder(self):
        """Explicit config_request intent should route to config_builder."""
        state = {
            "mode_shift_type": "hard_shift",
            "intent": "config_request",
        }
        result = self.agent._route_after_intent(state)
        assert result == "config_builder"

    def test_documentation_request_routes_to_doc_writer(self):
        """Explicit documentation_request intent should route to doc_writer."""
        state = {
            "mode_shift_type": "hard_shift",
            "intent": "documentation_request",
        }
        result = self.agent._route_after_intent(state)
        assert result == "doc_writer"


# ============================================================================
# TestNoPriorModeEdgeCases
# ============================================================================

class TestNoPriorModeEdgeCases:
    """Tests for first-turn behavior where agent_mode is not yet set."""

    @pytest.fixture(autouse=True)
    def agent(self):
        self.agent = LucilleAgent()

    def test_first_turn_rag_is_continuation(self):
        state = {}  # no agent_mode
        assert self.agent._detect_mode_shift(state, "question") == "continuation"

    def test_first_turn_config_is_hard_shift_from_implicit_rag(self):
        state = {}  # treated as rag
        assert self.agent._detect_mode_shift(state, "config_request") == "hard_shift"

    def test_first_turn_follow_up_in_empty_state_is_continuation(self):
        """follow_up on first turn (no prior mode) should be continuation, not soft_shift."""
        state = {}
        # current_mode defaults to "rag", follow_up maps to "rag" → continuation
        assert self.agent._detect_mode_shift(state, "follow_up") == "continuation"


# ============================================================================
# TestIntentClassifierNodeStateWrites — cleanup fields on hard shift
# ============================================================================

class TestIntentClassifierNodeStateWrites:
    """
    Tests that intent_classifier_node returns correct mode shift fields
    and clears stale state on hard shifts.

    These tests directly call intent_classifier_node with a constructed state
    and verify the return dict contains the expected fields.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        from unittest.mock import patch
        self.agent = LucilleAgent()
        # We'll mock _classify_intent to return controlled values
        self.classify_intent_patcher = patch.object(
            self.agent,
            '_classify_intent',
            return_value=("question", "test intent", 0.95, [])
        )
        self.mock_classify = self.classify_intent_patcher.start()
        yield
        self.classify_intent_patcher.stop()

    def test_hard_shift_clears_awaiting_clarification(self):
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="How does CopyFields work?")],
            "agent_mode": "doc_writer",
            "awaiting_clarification": True,
            "clarification_type": "format",
        }
        result = self.agent.intent_classifier_node(state)
        assert result.get("awaiting_clarification") is False

    def test_hard_shift_sets_previous_agent_mode(self):
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="How does CopyFields work?")],
            "agent_mode": "config_builder",
        }
        result = self.agent.intent_classifier_node(state)
        assert result.get("previous_agent_mode") == "config_builder"

    def test_hard_shift_sets_mode_shift_type_to_hard_shift(self):
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="How does CopyFields work?")],
            "agent_mode": "config_builder",
        }
        result = self.agent.intent_classifier_node(state)
        # Hard shift because "question" intent while in config_builder mode
        assert result.get("mode_shift_type") == "hard_shift"

    def test_continuation_does_not_clear_extra_fields(self):
        """Continuation should NOT have extra cleanup fields in return dict."""
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="Tell me more")],
            "agent_mode": "rag",
        }
        result = self.agent.intent_classifier_node(state)
        # Continuation mode should NOT clear awaiting_clarification
        assert "awaiting_clarification" not in result

    def test_hard_shift_clears_config_state(self):
        """Hard shift should clear all config_builder state fields."""
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="Tell me about RAG")],
            "agent_mode": "config_builder",
            "config_components": [{"name": "CSVConnector"}],
            "config_output": "some hocon",
        }
        result = self.agent.intent_classifier_node(state)
        assert result.get("config_components") is None
        assert result.get("config_output") is None
        assert result.get("config_validation_passed") is None

    def test_hard_shift_clears_doc_state(self):
        """Hard shift should clear all doc_writer state fields."""
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="Build me a config")],
            "agent_mode": "doc_writer",
            "doc_outline": [{"section": "intro"}],
            "doc_gathered_content": {"intro": "some content"},
        }
        result = self.agent.intent_classifier_node(state)
        assert result.get("doc_outline") is None
        assert result.get("doc_gathered_content") is None
        assert result.get("doc_sections_gathered") is None

    def test_hard_shift_clears_rag_state(self):
        """Hard shift should clear RAG-mode state fields when shifting away from RAG."""
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content="Build me a config")],
            "agent_mode": "rag",
            "retrieved_documents": [{"source": "test"}],
            "alpha_adjusted": True,
        }
        # Mock _classify_intent to return config_request (hard shift away from rag)
        with patch.object(
            self.agent,
            '_classify_intent',
            return_value=("config_request", "test intent", 0.95, [])
        ):
            result = self.agent.intent_classifier_node(state)
        assert result.get("retrieved_documents") == []
        assert result.get("alpha_adjusted") is False
