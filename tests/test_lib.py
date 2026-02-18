"""Tests for lib.py — shared utilities."""

import pytest
import lib


def test_evaluate_context_unknown_strategy_raises():
    """Unknown strategy must raise ValueError, not silently return True."""
    with pytest.raises(ValueError, match="Unknown context strategy"):
        lib.evaluate_context([], {"strategy": "require_neighbor"})


def test_evaluate_context_valid_strategies_still_work():
    """All 4 valid strategies must still function."""
    assert lib.evaluate_context([], {"strategy": "always"}) is True
    assert lib.evaluate_context([], {"strategy": "requires_neighbor"}) is False
    assert lib.evaluate_context([], {"strategy": "exclude_neighbor"}) is True
    assert (
        lib.evaluate_context(
            ["AI"], {"strategy": "both", "neighbors": ["AI"], "exclude_neighbors": []}
        )
        is True
    )


@pytest.mark.parametrize(
    "pattern,text,expected_count",
    [
        ("C++", "I write C++ code", 1),
        ("C++", "C++ is great", 1),
        ("C++", "AC++ nonsense", 0),
        ("C#", "Learn C# today", 1),
        ("C#", "C# development", 1),
        (".NET", "Use .NET framework", 1),
        (".NET", "the .NET platform", 1),
        ("Node.js", "Install Node.js first", 1),
        ("github", "Check github repo", 1),
    ],
)
def test_find_matches_special_char_boundaries(pattern, text, expected_count):
    """Word boundary must work for patterns with non-word edge chars."""
    matches = lib.find_matches(text, pattern)
    assert len(matches) == expected_count
