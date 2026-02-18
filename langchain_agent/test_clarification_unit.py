#!/usr/bin/env python3
"""
Unit tests for clarification system components.

Tests individual functions without running the full graph.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from content_generators import get_content_params

def test_get_content_params_descriptions():
    """Test that get_content_params returns descriptions."""
    print("=" * 80)
    print("TEST: get_content_params includes descriptions")
    print("=" * 80)

    content_types = ["social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"]

    for content_type in content_types:
        params = get_content_params(content_type)
        print(f"\n{content_type}:")
        print(f"  description: {params.get('description', 'MISSING')}")
        print(f"  target_length: {params.get('target_length')}")
        print(f"  tone: {params.get('tone')}")
        print(f"  temperature: {params.get('temperature')}")

        # Check that description exists
        if "description" not in params:
            print(f"  ❌ FAIL: Missing description for {content_type}")
            return False
        else:
            print(f"  ✅ PASS: Description present")

    return True

def test_config_constants():
    """Test that config constants are defined."""
    print("\n" + "=" * 80)
    print("TEST: Configuration constants")
    print("=" * 80)

    from config import CONTENT_TYPE_CLARIFICATION_THRESHOLD

    print(f"  CONTENT_TYPE_CLARIFICATION_THRESHOLD: {CONTENT_TYPE_CLARIFICATION_THRESHOLD}")

    if CONTENT_TYPE_CLARIFICATION_THRESHOLD < 0 or CONTENT_TYPE_CLARIFICATION_THRESHOLD > 1:
        print(f"  ❌ FAIL: Invalid threshold value")
        return False
    else:
        print(f"  ✅ PASS: Valid threshold (0.0-1.0)")

    return True

def test_state_schema():
    """Test that state schema includes clarification fields."""
    print("\n" + "=" * 80)
    print("TEST: Agent state schema")
    print("=" * 80)

    from agent_state import CustomAgentState

    # Check if clarification fields are in the TypedDict annotations
    annotations = CustomAgentState.__annotations__

    required_fields = [
        "needs_clarification",
        "clarification_type",
        "clarification_candidates",
        "awaiting_clarification",
    ]

    for field in required_fields:
        if field in annotations:
            print(f"  ✅ {field}: {annotations[field]}")
        else:
            print(f"  ❌ FAIL: Missing field '{field}'")
            return False

    return True

if __name__ == "__main__":
    print("UNIT TESTS FOR CLARIFICATION SYSTEM\n")

    tests = [
        test_get_content_params_descriptions,
        test_config_constants,
        test_state_schema,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Passed: {sum(results)}/{len(results)}")
    print(f"  Failed: {len(results) - sum(results)}/{len(results)}")

    if all(results):
        print("\n✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED")
        sys.exit(1)
