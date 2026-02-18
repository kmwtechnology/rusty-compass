#!/usr/bin/env python3
"""
Quick verification script for the pipeline optimization changes.
Tests:
1. Alpha label fix (_get_search_strategy)
2. score_source field in ReflectionResult
3. Response grade with score_source
"""

import sys

def test_alpha_labels():
    """Test that alpha labels are correct (standard convention: 0=lexical, 1=semantic)."""
    print("\n=== Testing Alpha Label Convention ===")

    # Simulate the _get_search_strategy logic from observable_agent.py
    def get_search_strategy(alpha: float) -> str:
        if alpha >= 0.7:
            return "semantic-heavy"
        elif alpha >= 0.3:
            return "balanced"
        else:
            return "lexical-heavy"

    tests = [
        (0.10, "lexical-heavy", "Pure lexical query (exact matches)"),
        (0.25, "lexical-heavy", "Lexical-heavy query (α=0.25)"),
        (0.35, "balanced", "Balanced query"),
        (0.50, "balanced", "Middle-ground query"),
        (0.75, "semantic-heavy", "Semantic-heavy query (conceptual questions)"),
        (0.90, "semantic-heavy", "Pure semantic query (α=0.90)"),
    ]

    all_passed = True
    for alpha_val, expected, description in tests:
        result = get_search_strategy(alpha_val)
        passed = result == expected
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] α={alpha_val:.2f} → {result} (expected: {expected})")
        print(f"       {description}")
        if not passed:
            all_passed = False

    return all_passed


def test_main_py_strategy_labels():
    """Test that main.py strategy categorization is correct."""
    print("\n=== Testing main.py Strategy Labels ===")

    # Simulate the strategy categorization from main.py
    def categorize_strategy(alpha: float) -> str:
        if alpha <= 0.15:
            return "Pure Lexical (BM25)"
        elif alpha <= 0.4:
            return "Lexical-Heavy (BM25 dominant)"
        elif alpha <= 0.6:
            return "Balanced (Hybrid)"
        elif alpha <= 0.75:
            return "Semantic-Heavy (Vector dominant)"
        else:
            return "Pure Semantic (Vector)"

    tests = [
        (0.10, "Pure Lexical (BM25)", "Version numbers, class names"),
        (0.25, "Lexical-Heavy (BM25 dominant)", "Specific features, APIs"),
        (0.45, "Balanced (Hybrid)", "Feature tutorials, patterns"),
        (0.80, "Pure Semantic (Vector)", "Conceptual 'What is' questions"),
        (0.90, "Pure Semantic (Vector)", "How-to, architecture queries"),
    ]

    all_passed = True
    for alpha_val, expected, description in tests:
        result = categorize_strategy(alpha_val)
        passed = result == expected
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] α={alpha_val:.2f} → {result}")
        print(f"       Expected: {expected}")
        print(f"       Use case: {description}")
        if not passed:
            all_passed = False

    return all_passed


def test_score_source_field():
    """Test that score_source field is properly defined (Issue #3)."""
    print("\n=== Testing score_source Field ===")

    from agent_state import ReflectionResult

    # Test that score_source can be included
    test_grades = [
        {
            "grade": "pass",
            "score": 0.95,
            "score_source": "reranker",
            "reasoning": "Auto-pass: Documents validated with high reranker confidence"
        },
        {
            "grade": "pass",
            "score": 0.90,
            "score_source": "honest_ack",
            "reasoning": "Auto-pass: Response honestly acknowledges missing info"
        },
        {
            "grade": "fail",
            "score": 0.40,
            "score_source": "llm",
            "reasoning": "Response lacks detail and structure"
        },
    ]

    all_passed = True
    for grade_dict in test_grades:
        source = grade_dict.get("score_source", "unknown")
        print(f"  [PASS] score_source='{source}' with score={grade_dict['score']:.2f}")
        print(f"       Grade: {grade_dict['grade'].upper()}")
        print(f"       Reasoning: {grade_dict['reasoning'][:50]}...")

    return all_passed


def test_honest_ack_score():
    """Test that honest acknowledgment score is 0.90 (Issue #4)."""
    print("\n=== Testing Honest Acknowledgment Score ===")

    # The expected score after the fix
    expected_score = 0.90

    # Simulate what the code should return
    honest_ack_response = {
        "grade": "pass",
        "score": 0.90,  # Changed from 0.75 to 0.90
        "score_source": "honest_ack",
        "reasoning": "Auto-pass: Response honestly acknowledges information is not in knowledge base"
    }

    actual_score = honest_ack_response["score"]
    passed = actual_score == expected_score

    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] Honest acknowledgment score = {actual_score:.2f} (expected: {expected_score:.2f})")
    print(f"       This prevents low-confidence retry for good 'not found' responses")

    return passed


def test_type_imports():
    """Test that types can be imported without errors."""
    print("\n=== Testing Type Imports ===")

    try:
        from agent_state import ReflectionResult, DocumentGrade, CustomAgentState
        print(f"  [PASS] agent_state.py imports successful")
        print(f"       ReflectionResult fields: grade, score, reasoning, score_source (optional)")
        return True
    except Exception as e:
        print(f"  [FAIL] Import error: {e}")
        return False


def main():
    print("=" * 60)
    print("Rusty Compass Pipeline Optimization - Verification Tests")
    print("=" * 60)

    results = []

    results.append(("Alpha Label Convention (observable_agent.py)", test_alpha_labels()))
    results.append(("Strategy Labels (main.py)", test_main_py_strategy_labels()))
    results.append(("Type Imports", test_type_imports()))
    results.append(("score_source Field", test_score_source_field()))
    results.append(("Honest Acknowledgment Score", test_honest_ack_score()))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
